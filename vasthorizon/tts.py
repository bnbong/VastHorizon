"""편지 읽어 주기 — Google Cloud Text-to-Speech로 공유한 편지를 MP3로 만든다.

    GET /api/l/<id>/audio.mp3   공유 기록(제목 · 본문)을 읽은 MP3 — 처음 요청할 때 합성해 <dir>/<키>.mp3로 둔다

합성: POST https://texttospeech.googleapis.com/v1/text:synthesize (키는 ?key= 대신 X-Goog-Api-Key 헤더 — 주소가 남는 로그에 키가 찍히지 않게)
    본문 {"input": {"text"}, "voice": {"languageCode": "ko-KR", "name"}, "audioConfig": {"audioEncoding": "MP3", "speakingRate"}}
    응답 audioContent(base64). 요청 하나의 입력은 5,000바이트(UTF-8)까지라 문장 단위로 나눠 4,500바이트 안에 묶고
    차례로 합성해 MP3 바이트를 그대로 잇는다 (같은 인코딩 설정이라 이어서 재생된다).
    글은 web/js/tts.js(speakableText · speechChunks)와 같은 규칙으로 정리한다 — [근거 N] · **굵게** 를 걷어 내고 문장 단위로.
    숫자 사이 천 단위 쉼표("3,780만")는 지운다 — 쉼표 뒤가 정확히 세 자리일 때만 (그 밖의 "1,2"는 문장 쉼표). 전각 "，"도 같다.

키: 환경변수 GOOGLE_TTS_API_KEY만 (설정 파일에 두지 않는다). 없으면 [tts] enabled여도 쓰지 않는다 (available=False).
    키는 로그 · 오류 응답에 내보내지 않는다 — 오류는 종류(HTTP 상태 · 예외 이름)만 남긴다.

한도 (Google 무료 구간 안에서만 쓴다 — 비용은 0으로 기록)
    원장 <dir>/ledger.json {"month", "month_chars", "day", "day_chars"} — 월 · 일은 한국 시각(usage.KST) 기준.
    합성 전에 이번 글자 수를 더해도 [tts] monthly_chars · daily_chars 이하인지 본다. 넘으면 TtsQuotaError.
    원장을 믿을 수 없으면 한도도 셀 수 없다 — Google을 부르기 전에 TtsUnavailableError("ledger"):
    파일이 깨졌거나(JSON · 형식 오류 — 지우거나 덮어쓰지 않는다, 사람이 확인한다) · 읽지 못했거나 · 합성 전에 써 보지 못했을 때,
    합성 뒤 더한 값을 쓰지 못했으면 그 뒤로 계속 (서버를 다시 시작할 때까지). 파일이 없을 때만 새 원장으로 본다.
    합성 중인 글자 수는 메모리에 잡아 두고(동시 요청이 한도를 함께 넘지 않게), 성공한 조각만 원장에 더한다.
    Google이 429 · 403(RESOURCE_EXHAUSTED · 결제 비활성 등)을 돌려주면 TtsQuotaError로 보고 10분 동안 서버 합성을 쉰다.
    그 밖의 오류(5xx · 타임아웃 · 네트워크)는 TtsError. 화면은 두 경우 모두 기기 음성(speechSynthesis)으로 읽는다.

오디오 캐시: 키는 sha256(음성, 속도, 정리된 본문)의 앞 24자. 파일이 있으면 Google을 부르지 않는다.
    같은 키를 동시에 두 번 합성하지 않게 키마다 잠금을 두고, 잠금 안에서 파일을 다시 본다.
    만료 정리(sweep): 시작할 때와 하루 한 번 [tts] days보다 오래된 MP3와 쓰다 남은 임시 파일을 지운다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from vasthorizon.data.atomic import atomic_write_text
from vasthorizon.usage import KST, kst_now, seconds_until_tomorrow

log = logging.getLogger(__name__)
API_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
LANGUAGE = "ko-KR"
REQUEST_BYTES = 5000              # Google이 받는 요청 하나의 입력 상한 (UTF-8 바이트)
CHUNK_BYTES = 4500                # 조각 하나의 상한 — 여유를 둔다
COOLDOWN_SECONDS = 600.0          # Google 한도 · 결제 오류 뒤 서버 합성을 쉬는 시간
KEY_LEN = 24
DAY = 86400.0
TMP_STALE_SECONDS = 3600.0
AUDIO_KEY = re.compile(r"^[0-9a-f]{24}$")
QUOTA_STATUS = (403, 429)


class TtsError(RuntimeError):
    """합성 실패 — Google 5xx · 타임아웃 · 네트워크 (502 tts_failed)."""


class TtsUnavailableError(TtsError):
    """서버 읽어 주기를 쓸 수 없다 — 꺼져 있거나 키가 없다 (503 tts_unavailable)."""


class TtsQuotaError(TtsError):
    """이달 · 오늘 글자 수 한도, 또는 Google 한도 · 결제 오류 뒤 쉬는 중 (503 tts_quota). retry_after는 초."""

    def __init__(self, reason: str, retry_after: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after = max(1, int(retry_after))


# ── 글 정리 · 나누기 (web/js/tts.js와 같은 규칙) ─────────────────────────────

_CITE = re.compile(r"\s*\[근거\s*[\d,，\s]+\]")
_SENTENCE = re.compile(r"(?<=[.!?。？！…])\s+|\n+")
_COMMA = re.compile(r"(?<=[,，])\s+")
_THOUSANDS = re.compile(r"(?<=\d)[,，](?=\d{3}(?!\d))")   # 3,780만 → 3780만 (합성이 "삼, 칠백팔십"으로 끊어 읽지 않게)
_WORD = re.compile(r"[^\W_]")                     # 글자 · 숫자가 하나라도 있는 조각만


def speakable_text(text: str | None) -> str:
    """화면 표시용 기호를 걷어 낸 글 — [근거 1, 2] · **굵게** · 숫자 사이 천 단위 쉼표."""
    text = _CITE.sub("", str(text or "")).replace("**", "")
    return re.sub(r"[ \t]+", " ", _THOUSANDS.sub("", text)).strip()


def sentences(text: str | None) -> list[str]:
    """문장(. ! ? 。 … 뒤 공백 · 줄바꿈) 단위. 글자가 없는 조각은 버린다."""
    parts = (" ".join(s.split()) for s in _SENTENCE.split(speakable_text(text)))
    return [s for s in parts if _WORD.search(s)]


def _nbytes(s: str) -> int:
    return len(s.encode("utf-8"))


def _split_long(sentence: str, max_bytes: int) -> list[str]:
    """한 문장이 상한을 넘으면 쉼표 뒤 → 공백 → 글자 순서로 나눈다."""
    if _nbytes(sentence) <= max_bytes:
        return [sentence]
    for pattern in (_COMMA, re.compile(r"\s+")):
        pieces = pattern.split(sentence)
        if len(pieces) > 1:
            return _pack([p for piece in pieces for p in _split_long(piece, max_bytes)], max_bytes)
    out, cur = [], ""
    for ch in sentence:                           # 공백 없이 긴 글 — 글자 단위로
        if cur and _nbytes(cur + ch) > max_bytes:
            out.append(cur)
            cur = ""
        cur += ch
    return out + ([cur] if cur else [])


def _pack(pieces: list[str], max_bytes: int) -> list[str]:
    out, cur = [], ""
    for p in pieces:
        joined = f"{cur} {p}" if cur else p
        if cur and _nbytes(joined) > max_bytes:
            out.append(cur)
            cur = p
        else:
            cur = joined
    return out + ([cur] if cur else [])


def chunks(text: str | None, max_bytes: int = CHUNK_BYTES) -> list[str]:
    """합성 요청 단위 — 문장을 공백으로 이어 조각마다 max_bytes(UTF-8) 이하로 묶는다."""
    return _pack([p for s in sentences(text) for p in _split_long(s, max_bytes)], max_bytes)


def char_count(parts: list[str]) -> int:
    """Google이 세는 글자 수 — 보낸 입력의 문자 수 합."""
    return sum(len(p) for p in parts)


# ── 합성 ──────────────────────────────────────────────────────────────────

def synthesize(text: str, *, api_key: str, voice: str, speaking_rate: float, timeout: float = 20,
               post: Callable | None = None) -> bytes:
    """조각 하나 → MP3 바이트. 429 · 403은 TtsQuotaError, 그 밖의 실패는 TtsError (키 · 응답 본문은 메시지에 넣지 않는다)."""
    import requests
    post = post or requests.post
    body = {"input": {"text": text}, "voice": {"languageCode": LANGUAGE, "name": voice},
            "audioConfig": {"audioEncoding": "MP3", "speakingRate": speaking_rate}}
    try:
        resp = post(API_URL, headers={"X-Goog-Api-Key": api_key}, json=body, timeout=timeout)
    except Exception as e:                        # 타임아웃 · 연결 오류 — 예외 메시지에 주소(키)가 들어갈 수 있다
        raise TtsError(type(e).__name__) from None
    if resp.status_code in QUOTA_STATUS:
        raise TtsQuotaError(f"google {resp.status_code}", COOLDOWN_SECONDS)
    if resp.status_code != 200:
        raise TtsError(f"google {resp.status_code}")
    try:
        return base64.b64decode(resp.json()["audioContent"])
    except Exception:
        raise TtsError("bad response") from None


def synthesize_text(text: str, *, api_key: str, voice: str, speaking_rate: float, timeout: float = 20,
                    post: Callable | None = None) -> tuple[bytes, int]:
    """글 전체 → (MP3, 글자 수). 원장 · 캐시를 거치지 않는다 (scripts/tts_sample.py)."""
    parts = chunks(text)
    audio = b"".join(synthesize(p, api_key=api_key, voice=voice, speaking_rate=speaking_rate, timeout=timeout, post=post)
                     for p in parts)
    return audio, char_count(parts)


def record_text(record: dict) -> str:
    """공유 기록에서 읽어 줄 글 — 카드와 같이 제목, 그리고 본문."""
    title, text = (record.get("title") or "").strip(), record.get("text") or ""
    return f"{title}.\n{text}" if title else text


def seconds_until_next_month(now: datetime) -> int:
    now = now.astimezone(KST)
    first = (now.replace(day=1) + timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((first - now).total_seconds()) + 1)


@dataclass
class Ledger:
    month: str
    month_chars: int = 0
    day: str = ""
    day_chars: int = 0


class TtsService:
    """원장 · 쿨다운 · 오디오 캐시를 둔 합성기. synth를 바꿔 끼우면 Google을 부르지 않는다 (테스트)."""

    def __init__(self, directory: Path, *, api_key: str = "", enabled: bool = True,
                 voice: str = "ko-KR-Chirp3-HD-Aoede", speaking_rate: float = 0.95, days: float = 30,
                 monthly_chars: int = 900000, daily_chars: int = 60000, timeout: float = 20,
                 synth: Callable[[str], bytes] | None = None, usage=None,
                 clock: Callable[[], float] = time.time, now: Callable[[], datetime] = kst_now) -> None:
        self.directory = directory
        self.voice = voice
        self.speaking_rate = speaking_rate
        self.days = days
        self.monthly_chars = monthly_chars
        self.daily_chars = daily_chars
        self.usage = usage
        self.clock = clock
        self.now = now
        self._available = bool(enabled and api_key)
        self._synth = synth or (lambda text: synthesize(text, api_key=api_key, voice=voice,
                                                        speaking_rate=speaking_rate, timeout=timeout))
        self._ledger_lock = threading.RLock()     # 원장 읽기 · 쓰기 · 예약
        self._reserved = 0                        # 합성 중인 글자 수 — 원장에는 성공한 뒤 더한다
        self._cooldown_until = 0.0
        self._ledger_broken = False               # 합성 뒤 원장을 쓰지 못했다 — 그 뒤로는 합성하지 않는다
        self._keys_lock = threading.Lock()
        self._key_locks: dict[str, list] = {}     # 키 → [잠금, 기다리는 수]
        self._sweep_lock = threading.Lock()
        if self._available:
            self.sweep()

    @property
    def available(self) -> bool:
        return self._available

    # ── 캐시 ──
    def cache_key(self, text: str) -> str:
        body = "\n".join(chunks(text))
        raw = json.dumps([self.voice, self.speaking_rate, body], ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:KEY_LEN]

    def audio_path(self, key: str) -> Path:
        return self.directory / f"{key}.mp3"

    def cached(self, text: str) -> bytes | None:
        """만들어 둔 MP3 — 없으면 None (Google을 부르지 않는다)."""
        try:
            return self.audio_path(self.cache_key(text)).read_bytes()
        except OSError:
            return None

    def _save(self, key: str, data: bytes) -> None:
        path = self.audio_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ── 원장 ──
    @property
    def ledger_path(self) -> Path:
        return self.directory / "ledger.json"

    def _ledger(self) -> Ledger:
        """이번 달 · 오늘의 원장. 달 · 날짜가 바뀌었으면 0부터. 파일이 없으면 새 원장, 깨졌거나 못 읽으면 TtsUnavailableError."""
        now = self.now().astimezone(KST)
        month, day = now.strftime("%Y-%m"), now.date().isoformat()
        ledger = Ledger(month=month, day=day)
        try:
            raw = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return ledger
        except (OSError, ValueError) as e:
            log.warning("읽어 주기 원장(%s)을 읽지 못해 서버 읽어 주기를 멈춥니다: %s", self.ledger_path.name, type(e).__name__)
            raise TtsUnavailableError("ledger") from None
        try:
            if not isinstance(raw, dict):
                raise TypeError("not a dict")
            if raw.get("month") == month:
                ledger.month_chars = int(raw.get("month_chars") or 0)
                if raw.get("day") == day:
                    ledger.day_chars = int(raw.get("day_chars") or 0)
        except (TypeError, ValueError):
            log.warning("읽어 주기 원장(%s)의 형식이 맞지 않아 서버 읽어 주기를 멈춥니다. 파일을 확인해 주세요.",
                        self.ledger_path.name)
            raise TtsUnavailableError("ledger") from None
        return ledger

    def _write_ledger(self, ledger: Ledger) -> None:
        atomic_write_text(self.ledger_path, json.dumps(ledger.__dict__, ensure_ascii=False))

    def _add(self, chars: int) -> None:
        if chars <= 0:
            return
        with self._ledger_lock:
            try:
                ledger = self._ledger()
                ledger.month_chars += chars
                ledger.day_chars += chars
                self._write_ledger(ledger)
            except (OSError, TtsUnavailableError) as e:   # 합성한 오디오는 돌려주되, 그 뒤로는 합성하지 않는다
                self._ledger_broken = True
                log.warning("읽어 주기 원장을 쓰지 못해 서버 읽어 주기를 멈춥니다: %s", type(e).__name__)

    def _reserve(self, chars: int) -> None:
        """쿨다운 · 한도를 보고 글자 수를 잡아 둔다. 넘으면 TtsQuotaError, 원장을 믿을 수 없으면 TtsUnavailableError."""
        with self._ledger_lock:
            if self._ledger_broken:
                raise TtsUnavailableError("ledger")
            left = self._cooldown_until - self.clock()
            if left > 0:
                raise TtsQuotaError("cooldown", left)
            ledger = self._ledger()
            try:                                  # Google을 부르기 전에 원장을 쓸 수 있는지 같은 값으로 써 본다
                self._write_ledger(ledger)
            except OSError as e:
                log.warning("읽어 주기 원장을 쓸 수 없어 합성하지 않습니다: %s", type(e).__name__)
                raise TtsUnavailableError("ledger") from None
            if ledger.month_chars + self._reserved + chars > self.monthly_chars:
                raise TtsQuotaError("month", seconds_until_next_month(self.now()))
            if ledger.day_chars + self._reserved + chars > self.daily_chars:
                raise TtsQuotaError("day", seconds_until_tomorrow(self.now()))
            self._reserved += chars

    def cooling(self) -> bool:
        return self._cooldown_until > self.clock()

    def status(self) -> dict:
        """상태 점검용 — 키는 없다. ledger_ok: 원장을 읽을 수 있고 쓰기에 실패한 적이 없다."""
        with self._ledger_lock:
            try:
                ledger, ok = self._ledger(), not self._ledger_broken
            except TtsUnavailableError:
                now = self.now().astimezone(KST)
                ledger, ok = Ledger(month=now.strftime("%Y-%m"), day=now.date().isoformat()), False
        return {"available": self.available, "month_chars": ledger.month_chars, "monthly_chars": self.monthly_chars,
                "day_chars": ledger.day_chars, "cooldown": self.cooling(), "ledger_ok": ok}

    # ── 합성 ──
    def _key_lock(self, key: str):
        with self._keys_lock:
            entry = self._key_locks.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
        return entry

    def _release_key(self, key: str, entry: list) -> None:
        with self._keys_lock:
            entry[1] -= 1
            if entry[1] <= 0:
                self._key_locks.pop(key, None)

    def audio(self, text: str) -> bytes:
        """글 → MP3. 캐시에 있으면 그대로, 없으면 한도 안에서 합성해 둔다."""
        if not self.available:
            raise TtsUnavailableError("disabled")
        parts = chunks(text)
        if not parts:
            raise TtsUnavailableError("empty")
        key = self.cache_key(text)
        entry = self._key_lock(key)
        try:
            with entry[0]:
                try:                                  # 기다리는 동안 다른 요청이 만들었을 수 있다
                    return self.audio_path(key).read_bytes()
                except OSError:
                    pass
                data = self._synthesize(parts)
                try:
                    self._save(key, data)
                except OSError as e:
                    log.warning("읽어 주기 오디오를 저장하지 못했습니다: %s", type(e).__name__)
                return data
        finally:
            self._release_key(key, entry)

    def _synthesize(self, parts: list[str]) -> bytes:
        total = char_count(parts)
        self._reserve(total)
        done, out, error = 0, [], None
        t = time.perf_counter()
        try:
            for part in parts:
                out.append(self._synth(part))
                done += len(part)
        except TtsQuotaError as e:
            error = e
            with self._ledger_lock:
                self._cooldown_until = self.clock() + COOLDOWN_SECONDS
            log.warning("Google TTS 한도 · 결제 오류(%s) — %d분 동안 서버 읽어 주기를 쉽니다.", e, COOLDOWN_SECONDS // 60)
            raise TtsQuotaError("cooldown", COOLDOWN_SECONDS) from None
        except TtsError as e:
            error = e
            log.warning("Google TTS 합성 실패: %s", e)
            raise
        except Exception as e:                        # 바꿔 끼운 합성기 등 — 종류만 남긴다
            error = e
            log.warning("Google TTS 합성 실패: %s", type(e).__name__)
            raise TtsError(type(e).__name__) from None
        finally:
            with self._ledger_lock:
                self._reserved -= total
                self._add(done)                       # 실패해도 이미 합성한 조각은 Google이 센다
            if self.usage is not None:
                self.usage.record_tts(done, time.perf_counter() - t, voice=self.voice,
                                      error=type(error).__name__ if error is not None else None)
        return b"".join(out)

    # ── 정리 ──
    def sweep(self) -> int:
        """days보다 오래된 MP3와 쓰다 남은 임시 파일을 지운다. 지운 파일 수."""
        if not self._sweep_lock.acquire(blocking=False):
            return 0
        try:
            if not self.directory.exists():
                return 0
            now, removed = time.time(), 0
            for path in list(self.directory.iterdir()):
                try:
                    if path.name.startswith(".") and path.suffix == ".tmp":
                        stale = now - path.stat().st_mtime > TMP_STALE_SECONDS
                    elif path.suffix == ".mp3" and AUDIO_KEY.match(path.stem):
                        stale = now - path.stat().st_mtime > self.days * DAY
                    else:
                        continue
                    if stale:
                        path.unlink(missing_ok=True)
                        removed += 1
                except OSError:
                    continue
            if removed:
                log.info("오래된 읽어 주기 파일 %d개를 지웠습니다.", removed)
            return removed
        finally:
            self._sweep_lock.release()

    def start_sweeper(self, interval: float = DAY) -> threading.Thread:
        """interval초(기본 하루)마다 sweep하는 데몬 스레드."""
        def loop() -> None:
            while not stop.wait(interval):
                try:
                    self.sweep()
                except Exception:
                    log.exception("읽어 주기 파일 정리 실패")
        stop = threading.Event()
        thread = threading.Thread(target=loop, name="tts-sweeper", daemon=True)
        thread.stop = stop
        thread.start()
        return thread


@lru_cache(maxsize=1)
def default_tts() -> TtsService | None:
    """설정에 따른 합성기 (프로세스에 하나). [tts] enabled = false면 None. 키가 없으면 available=False."""
    from vasthorizon.config import get_settings, get_tts_key
    from vasthorizon.usage import default_log
    s = get_settings()
    cfg = s.tts
    if not cfg.enabled:
        return None
    key = get_tts_key() or ""
    if not key:
        log.warning("[tts] enabled지만 GOOGLE_TTS_API_KEY가 없어 서버 읽어 주기를 쓰지 않습니다 (기기 음성으로 읽습니다).")
    service = TtsService(cfg.dir or s.paths.cache_dir / "tts", api_key=key, voice=cfg.voice,
                         speaking_rate=cfg.speaking_rate, days=cfg.days, monthly_chars=cfg.monthly_chars,
                         daily_chars=cfg.daily_chars, timeout=cfg.timeout, usage=default_log())
    if service.available:
        service.start_sweeper()
    return service
