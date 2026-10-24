"""편지 공유 — 서버 응답 캐시에 있는 빛의 편지 · 마음 한 줄을 링크로 남긴다.

    POST /api/share       캐시 적중만 공유한다 (임의 내용을 대신 호스팅하지 않는다). 없으면 404 share_not_ready
    GET  /api/l/<id>      미리보기 카드(OG 태그)가 있는 HTML — sharecard.py
    GET  /api/l/<id>.json 저장한 기록 그대로 (앱이 공유 링크를 열 때)
    GET  /api/l/<id>.png  1200×630 미리보기 이미지 — 처음 요청할 때 그려 <id>.png로 둔다

기록 (<dir>/<id>.json, 파일 하나에 공유 하나)
    id        내용 해시(SHA-256)의 앞 16자 — 같은 편지는 같은 id (다시 공유하면 기존 링크, 만료 시각은 새로)
              같은 id에 다른 내용이 있으면(해시 앞부분 충돌) 2자씩 더 붙인다
    kind      letter | perspective
    created   만든 시각 (UTC, ISO 8601) · expires 만료 시각 (유닉스 시각, [share] days 뒤)
    item_id · item_name · eyebrow(항목 그룹 · '마음 한 줄') · title · text · departure(편지만) · themes
    cited     [{number, title, source_type, url}]
마음 한 줄은 사용자 문장을 저장하지 않는다 — 답 · 주제 · 근거만. 근거 · 위기 판정을 통과한 응답(cited · not_found)만 받는다.
답이 사용자 문장을 15자 넘게 되풀이하면 공유하지 않는다 (echoes).

만료 정리(sweep): 시작할 때와 하루 한 번(start_sweeper) 만료된 기록과 그 이미지, 기록 없는 이미지, 쓰다 남은 임시 파일을 지운다.
읽을 때도 만료된 기록은 지우고 없는 것으로 본다. 기록 쓰기(put)와 지우기는 한 잠금(RLock) 안에서 — 지우기 직전에 파일을
다시 읽어 정말 만료됐는지 본다 (sweep이 읽은 뒤 put이 만료를 늘린 기록을 지우지 않게).
활성 기록은 max_records(기본 20,000)개까지 — 넘치면 503. 개수는 시작할 때 한 번 세고 메모리에서 고친다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from vasthorizon.data.atomic import atomic_write_text

log = logging.getLogger(__name__)
DAY = 86400.0
TMP_STALE_SECONDS = 3600.0
ID_LEN = 16
SHARE_ID = re.compile(r"^[0-9a-f]{12,64}$")       # 12자는 예전 기록 — 지금은 16자(충돌하면 18 · 20 …)
META_KEYS = ("id", "created", "expires")          # 기록에서 내용이 아닌 칸 — 내용 해시에서 뺀다
ECHO_LEN = 15                                     # 답이 사용자 문장을 이만큼 연속으로 되풀이하면 공유하지 않는다
SHAREABLE = ("cited", "not_found")             # 근거 검증을 통과한 응답만 — crisis · rejected · unchecked · failed는 거절

LETTER_TITLE = "{name}에서 온 빛의 편지"
PERSPECTIVE_TITLE = "마음 한 줄에 닿은 우주의 사실"
PERSPECTIVE_EYEBROW = "마음 한 줄"


class ShareNotReadyError(LookupError):
    """공유할 응답이 캐시에 없다 — 편지를 다시 받은 뒤 공유한다 (404)."""


class ShareRefusedError(ValueError):
    """공유하지 않는 응답 — 위기 안내 · 인용 규칙 위반 · 확인 실패 (409). message가 있으면 그 안내를 보여 준다."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        super().__init__(reason)
        self.message = message


class ShareUnavailableError(RuntimeError):
    """공유 저장소가 없다 (503)."""


def valid_id(share_id: str) -> bool:
    return bool(SHARE_ID.match(share_id or ""))


def _cited(cited: list[dict]) -> list[dict]:
    return [{"number": c.get("number"), "title": c.get("title", ""), "source_type": c.get("source_type", ""),
             "url": c.get("url", "")} for c in cited or []]


def check_shareable(response: dict) -> None:
    if response.get("crisis") or response.get("status") not in SHAREABLE:
        raise ShareRefusedError(response.get("status") or "unknown")


def letter_record(response: dict, eyebrow: str) -> dict:
    """캐시한 LetterResponse → 공유 기록의 내용 (id · 시각 제외)."""
    check_shareable(response)
    name = response.get("item_name", "")
    return {"kind": "letter", "item_id": response.get("item_id"), "item_name": name, "eyebrow": eyebrow,
            "title": LETTER_TITLE.format(name=name), "text": response.get("letter", ""),
            "departure": response.get("departure"), "themes": [], "cited": _cited(response.get("cited"))}


def perspective_record(response: dict) -> dict:
    """캐시한 PerspectiveResponse → 공유 기록의 내용. 사용자 문장은 응답에도 기록에도 없다."""
    check_shareable(response)
    return {"kind": "perspective", "item_id": None, "item_name": None, "eyebrow": PERSPECTIVE_EYEBROW,
            "title": PERSPECTIVE_TITLE, "text": response.get("answer", ""), "departure": None,
            "themes": list(response.get("themes") or []), "cited": _cited(response.get("cited"))}


def content_hash(content: dict) -> str:
    """내용(id · 시각 제외)의 SHA-256 — 기록을 넣어도 같은 값."""
    body = {k: v for k, v in content.items() if k not in META_KEYS}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def share_id(content: dict) -> str:
    return content_hash(content)[:ID_LEN]


_CITE_MARK = re.compile(r"\[근거\s*[\d,，\s]+\]|\*\*")


def _normalized(text: str) -> str:
    return " ".join(_CITE_MARK.sub(" ", text or "").split())


def echoes(text: str | None, answer: str | None, n: int = ECHO_LEN) -> bool:
    """answer가 text의 연속 n자 이상을 그대로 담는가 (공백 · [근거 N] · 굵게 표시를 정리한 뒤)."""
    t, a = _normalized(text or ""), _normalized(answer or "")
    if len(t) < n or len(a) < n:
        return False
    return any(t[i:i + n] in a for i in range(len(t) - n + 1))


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class ShareStore:
    def __init__(self, directory: Path, days: float = 180, clock: Callable[[], float] = time.time,
                 max_records: int = 20000) -> None:
        self.directory = directory
        self.days = days
        self.clock = clock
        self.max_records = max_records
        self._sweep_lock = threading.Lock()                         # sweep은 한 번에 하나만
        self._lock = threading.RLock()                              # put · 지우기 — 같은 기록을 두고 겨루지 않게
        self._count = 0
        self.sweep()                                                # 시작할 때 — 지난 실행이 남긴 만료 기록
        self._count = self._scan_count()                            # 개수는 여기서 한 번만 센다

    def _path(self, share_id: str) -> Path:
        return self.directory / f"{share_id}.json"

    def image_path(self, share_id: str) -> Path:
        return self.directory / f"{share_id}.png"

    def _read(self, share_id: str) -> tuple[dict | None, float]:
        """(기록, 만료 시각). 없으면 (None, inf), 깨졌으면 (None, 0) — 깨진 파일은 만료된 것으로 본다."""
        try:
            record = json.loads(self._path(share_id).read_text(encoding="utf-8"))
            return record, float(record["expires"])
        except FileNotFoundError:
            return None, float("inf")
        except (OSError, ValueError, KeyError, TypeError):
            return None, 0.0

    def get(self, share_id: str) -> dict | None:
        """저장한 기록, 없거나 만료됐으면 None."""
        if not valid_id(share_id):
            return None
        record, expires = self._read(share_id)
        if expires <= self.clock():                                 # 만료 · 깨진 파일 — 지우고 없는 것으로
            self._remove(share_id)
            return None
        return record

    def put(self, content: dict) -> tuple[dict, bool]:
        """(기록, 새로 만들었는가). 같은 내용이 이미 있으면 만료 시각만 지금 + days로 고쳐 돌려준다 (이미지는 그대로).

        같은 id에 다른 내용이 있으면(해시 앞 16자 충돌) id를 2자씩 늘린다. 활성 기록이 max_records개면 ShareUnavailableError.
        """
        full = content_hash(content)
        with self._lock:
            now = self.clock()
            for length in range(ID_LEN, len(full) + 1, 2):
                sid = full[:length]
                existing = self.get(sid)
                if existing is None:
                    break
                if content_hash(existing) != full:                  # 충돌 — 다음 길이로
                    continue
                record = {**existing, "expires": now + self.days * DAY}
                atomic_write_text(self._path(sid), json.dumps(record, ensure_ascii=False))
                return record, False
            else:
                raise ShareUnavailableError("id")
            if self._count >= self.max_records:
                log.warning("공유 기록이 상한(%d개)에 닿았습니다.", self.max_records)
                raise ShareUnavailableError("full")
            record = {"id": sid, **content, "created": iso(now), "expires": now + self.days * DAY}
            atomic_write_text(self._path(sid), json.dumps(record, ensure_ascii=False))
            self.image_path(sid).unlink(missing_ok=True)             # 같은 id의 예전(만료된) 이미지
            self._count += 1
            return record, True

    def save_image(self, share_id: str, data: bytes) -> None:
        path = self.image_path(share_id)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _remove(self, share_id: str) -> int:
        """만료된 기록과 그 이미지를 지운다 — 잠금 안에서 파일을 다시 읽어 정말 만료됐을 때만. 지운 파일 수."""
        with self._lock:
            record, expires = self._read(share_id)
            if expires > self.clock():                              # 그 사이 put이 만료를 늘렸거나 이미 지워졌다
                return 0
            removed = 0
            path = self._path(share_id)
            if path.exists():
                path.unlink(missing_ok=True)
                removed += 1
                self._count = max(0, self._count - 1)
            image = self.image_path(share_id)
            if image.exists():
                image.unlink(missing_ok=True)
                removed += 1
            return removed

    def _scan_count(self) -> int:
        if not self.directory.exists():
            return 0
        return sum(1 for p in self.directory.glob("*.json") if valid_id(p.stem))

    def count(self) -> int:
        """활성 기록 수 — 시작할 때 센 값을 put · 지우기 때 고친다 (파일을 다시 세지 않는다)."""
        return self._count

    def sweep(self) -> int:
        """만료된 기록 · 그 이미지 · 기록 없는 이미지 · 남은 임시 파일을 지운다. 지운 파일 수."""
        if not self._sweep_lock.acquire(blocking=False):
            return 0
        try:
            if not self.directory.exists():
                return 0
            now, removed = self.clock(), 0
            for path in list(self.directory.iterdir()):
                try:
                    if path.name.startswith(".") and path.suffix == ".tmp":
                        if time.time() - path.stat().st_mtime > TMP_STALE_SECONDS:
                            path.unlink(missing_ok=True)
                            removed += 1
                        continue
                    if not valid_id(path.stem):
                        continue
                    if path.suffix == ".png":
                        with self._lock:                                # put이 기록을 막 쓴 이미지는 남긴다
                            if not self._path(path.stem).exists():
                                path.unlink(missing_ok=True)
                                removed += 1
                        continue
                    if path.suffix != ".json":
                        continue
                    if self._read(path.stem)[1] <= now:                 # 깨진 파일도 만료로 — _remove가 잠금 안에서 다시 본다
                        removed += self._remove(path.stem)
                except OSError:
                    continue
            if removed:
                log.info("만료된 공유 파일 %d개를 지웠습니다.", removed)
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
                    log.exception("공유 파일 정리 실패")
        stop = threading.Event()
        thread = threading.Thread(target=loop, name="share-sweeper", daemon=True)
        thread.stop = stop
        thread.start()
        return thread


def default_share() -> ShareStore:
    from vasthorizon.config import get_settings
    s = get_settings()
    store = ShareStore(s.share.dir or s.paths.cache_dir / "share", s.share.days, max_records=s.share.max_records)
    store.start_sweeper()
    return store
