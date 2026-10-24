"""서버 응답 캐시 — 같은 입력이면 LLM을 부르지 않고 저장한 응답(JSON)을 돌려준다.

| 대상 (namespace)  | 키                                              | TTL (설정 [cache])                 |
|-------------------|-------------------------------------------------|------------------------------------|
| explore           | 정규화한 조건 문장                               | explore_days (7일)                 |
| letter            | 항목 ID (나이로 찾은 별도 같은 항목이면 같은 키)   | letter_days (7일)                  |
| unfold            | 별자리 항목 ID                                   | unfold_days (30일)                 |
| perspective       | 마음 한 줄의 해시 + 감정 버튼                     | perspective_days (1일)             |
| ask               | 항목 ID + 정규화한 질문 + 검색 방식 (대화 기록이 없을 때만) | ask_days (7일), 실시간 근거가 들어간 답은 ask_live_days (1일)와 다음 UTC 자정 중 이른 때 |

모든 키에는 '판'(fingerprint)이 들어간다 — 모델 이름 · effort · 프롬프트 파일 · 항목 카탈로그가 바뀌면 키가 달라져
예전 응답을 쓰지 않는다 (api/app.py가 만든다).

저장소: 메모리 LRU(memory_items개) + 디스크(파일 하나에 응답 하나, 원자적 쓰기). 만료된 파일은 읽을 때 지운다.
만료 정리(sweep): 읽지 않는 만료 파일도 남지 않게 한다 — 시작할 때, put 100회마다, 그리고 default_cache()가 띄우는
정리 스레드가 한 시간마다 디스크 · 메모리의 만료 응답과 쓰다 남은 임시 파일을 지운다.
마음 한 줄(perspective)의 응답도 TTL(1일)이 지나면 늦어도 한 시간 안에 디스크에서 사라진다.
정규화는 과하지 않게 한다 — 유니코드 정규화(NFC) · 앞뒤 공백 · 연속 공백 · 영문 대소문자 · 끝의 문장 부호만.
조사 · 어미는 건드리지 않는다 (뜻이 달라질 수 있다).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from vasthorizon.data.atomic import atomic_write_text

log = logging.getLogger(__name__)
DAY = 86400.0
SWEEP_EVERY_PUTS = 100           # put 이 횟수마다 만료 정리
SWEEP_SECONDS = 3600.0           # 정리 스레드 간격 (default_cache)
TMP_STALE_SECONDS = 3600.0       # 쓰다 남은 임시 파일(원자적 쓰기 도중 프로세스가 죽은 경우)을 지울 나이

_SPACES = re.compile(r"\s+")
_TRAILING = re.compile(r"[\s?!.,~…。？！]+$")


def normalize_text(text: str) -> str:
    """캐시 키용 문장 정리 — 같은 뜻의 사소한 차이(공백 · 대소문자 · 끝의 물음표)만 없앤다."""
    text = unicodedata.normalize("NFC", text or "")
    text = _SPACES.sub(" ", text).strip().lower()
    return _TRAILING.sub("", text)


def text_hash(text: str) -> str:
    """사용자 문장을 그대로 저장하지 않을 때의 키 (마음 한 줄)."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def next_utc_midnight(now: float) -> float:
    """now(유닉스 시각) 다음의 UTC 자정."""
    return (now // DAY + 1) * DAY


def cache_key(namespace: str, parts) -> str:
    raw = json.dumps([namespace, parts], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, directory: Path | None, memory_items: int = 512, clock: Callable[[], float] = time.time) -> None:
        self.directory = directory
        self.memory_items = max(0, memory_items)
        self.clock = clock
        self._memory: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._lock = threading.Lock()
        self._sweep_lock = threading.Lock()
        self._puts = 0
        self.sweep()                                                # 시작할 때 — 지난 실행이 남긴 만료 파일

    def _path(self, namespace: str, key: str) -> Path | None:
        if self.directory is None:
            return None
        return self.directory / namespace / key[:2] / f"{key}.json"

    def _remember(self, key: str, expires: float, value: dict) -> None:
        if self.memory_items == 0:
            return
        with self._lock:
            self._memory[key] = (expires, value)
            self._memory.move_to_end(key)
            while len(self._memory) > self.memory_items:
                self._memory.popitem(last=False)

    def get(self, namespace: str, parts) -> dict | None:
        """저장한 응답, 없거나 만료됐으면 None."""
        key = cache_key(namespace, parts)
        now = self.clock()
        with self._lock:
            hit = self._memory.get(key)
            if hit is not None:
                if hit[0] > now:
                    self._memory.move_to_end(key)
                    return json.loads(json.dumps(hit[1]))          # 호출하는 쪽이 고쳐도 저장본은 그대로
                del self._memory[key]
        path = self._path(namespace, key)
        if path is None or not path.exists():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            expires, value = float(record["expires"]), record["value"]
        except (OSError, ValueError, KeyError, TypeError):
            path.unlink(missing_ok=True)                            # 깨진 파일 — 다시 만든다
            return None
        if expires <= now or not isinstance(value, dict):
            path.unlink(missing_ok=True)
            return None
        self._remember(key, expires, value)
        return json.loads(json.dumps(value))

    def put(self, namespace: str, parts, value: dict, ttl_days: float, day_boundary: bool = False) -> None:
        """day_boundary=True면 TTL과 다음 UTC 자정 중 이른 때에 만료한다 (오늘 기준 값이 든 응답)."""
        if ttl_days <= 0:
            return
        key = cache_key(namespace, parts)
        now = self.clock()
        expires = now + ttl_days * DAY
        if day_boundary:
            expires = min(expires, next_utc_midnight(now))
        value = json.loads(json.dumps(value, ensure_ascii=False))
        self._remember(key, expires, value)
        path = self._path(namespace, key)
        if path is None:
            return
        try:
            atomic_write_text(path, json.dumps({"created": now, "expires": expires, "value": value}, ensure_ascii=False))
        except OSError as e:                                        # 캐시 저장 실패로 응답을 막지 않는다
            log.warning("응답 캐시를 저장하지 못했습니다: %s", type(e).__name__)
        with self._lock:
            self._puts += 1
            due = self._puts % SWEEP_EVERY_PUTS == 0
        if due:
            self.sweep()

    def sweep(self) -> int:
        """만료된 응답을 메모리 · 디스크에서 지운다. 지운 파일 수. 이미 다른 스레드가 정리 중이면 0.

        파일은 읽은 뒤 그사이 바뀌지 않았을 때만 지운다 (같은 키를 새로 쓴 응답을 지우지 않게).
        """
        if not self._sweep_lock.acquire(blocking=False):
            return 0
        try:
            now = self.clock()
            with self._lock:
                for key in [k for k, (expires, _) in self._memory.items() if expires <= now]:
                    del self._memory[key]
            if self.directory is None or not self.directory.exists():
                return 0
            removed = 0
            for path in self.directory.glob("*/*/*"):
                try:
                    if path.name.startswith(".") and path.suffix == ".tmp":      # 원자적 쓰기의 남은 임시 파일
                        if time.time() - path.stat().st_mtime > TMP_STALE_SECONDS:
                            path.unlink(missing_ok=True)
                            removed += 1
                        continue
                    if path.suffix != ".json":
                        continue
                    before = path.stat().st_mtime_ns
                    try:
                        expires = float(json.loads(path.read_text(encoding="utf-8"))["expires"])
                    except (ValueError, KeyError, TypeError):
                        expires = 0.0                                           # 깨진 파일
                    if expires <= now and path.stat().st_mtime_ns == before:
                        path.unlink(missing_ok=True)
                        removed += 1
                except OSError:                                                 # 그사이 지워졌거나 읽을 수 없음
                    continue
            if removed:
                log.info("만료된 응답 캐시 %d개를 지웠습니다.", removed)
            return removed
        finally:
            self._sweep_lock.release()

    def start_sweeper(self, interval: float = SWEEP_SECONDS) -> threading.Thread:
        """interval초마다 sweep하는 데몬 스레드 — 요청이 없어도 만료 파일이 남지 않게."""
        def loop() -> None:
            while not stop.wait(interval):
                try:
                    self.sweep()
                except Exception:                                               # 정리 실패로 서버를 멈추지 않는다
                    log.exception("응답 캐시 정리 실패")
        stop = threading.Event()
        thread = threading.Thread(target=loop, name="response-cache-sweeper", daemon=True)
        thread.stop = stop                                                      # 테스트 · 종료용
        thread.start()
        return thread


def default_cache() -> ResponseCache | None:
    """설정에 따른 응답 캐시. [cache] enabled = false면 None."""
    from vasthorizon.config import get_settings
    s = get_settings()
    if not s.cache.enabled:
        return None
    cache = ResponseCache(s.cache.dir or s.paths.cache_dir / "responses", s.cache.memory_items)
    cache.start_sweeper()
    return cache
