"""외부 API 공용 HTTP 클라이언트. (NF2006)

- 출처가 요구하는 식별 정보: `앱이름/버전 (연락처) python-requests/x.y` 형식의 User-Agent
- 호출 간격: 같은 호스트에는 min_interval_sec 이상 간격을 둔다
- 재시도: 연결 오류 · 429 · 5xx는 지수 백오프로 재시도하고, Retry-After가 있으면 따른다
"""

from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlparse

import requests

from vasthorizon.config import get_contact, get_settings

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class PoliteSession:
    def __init__(self) -> None:
        cfg = get_settings().http
        self.min_interval = cfg.min_interval_sec
        self.max_retries = cfg.max_retries
        self.timeout = cfg.timeout_sec

        contact = get_contact()
        if not contact:
            log.warning("WIKI_CONTACT가 없습니다. 위키백과 · Wikidata 호출 한도가 줄어들 수 있습니다.")
        contact_part = f" ({contact})" if contact else ""
        self.user_agent = f"{cfg.app_name}{contact_part} python-requests/{requests.__version__}"

        self._session = requests.Session()
        self._session.headers["User-Agent"] = self.user_agent
        self._last_call: dict[str, float] = {}
        self._lock = threading.Lock()

    def _wait_turn(self, host: str) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_call.get(host, 0.0)
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_call[host] = time.monotonic()

    def get(self, url: str, **kwargs) -> requests.Response:
        host = urlparse(url).netloc
        kwargs.setdefault("timeout", self.timeout)

        for attempt in range(self.max_retries + 1):
            self._wait_turn(host)
            try:
                resp = self._session.get(url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt == self.max_retries:
                    raise
                delay = 2 ** attempt
                log.info("%s 연결 실패(%s) — %ds 후 재시도", host, type(e).__name__, delay)
                time.sleep(delay)
                continue

            if resp.status_code in RETRY_STATUS and attempt < self.max_retries:
                delay = _retry_after(resp) or 2 ** attempt
                log.info("%s 응답 %d — %ss 후 재시도", host, resp.status_code, delay)
                time.sleep(delay)
                continue

            resp.raise_for_status()
            return resp

        raise RuntimeError("unreachable")

    def get_json(self, url: str, **kwargs):
        return self.get(url, **kwargs).json()


def _retry_after(resp: requests.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if value and value.isdigit():
        return float(value)
    return None


_default: PoliteSession | None = None


def http() -> PoliteSession:
    """프로세스 전체에서 공유하는 세션. 호스트별 호출 간격이 함께 지켜진다."""
    global _default
    if _default is None:
        _default = PoliteSession()
    return _default
