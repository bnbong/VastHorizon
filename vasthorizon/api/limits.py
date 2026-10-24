"""공개 배포에서 개인 API 키를 지키는 AI 호출 한도 — 실제로 LLM을 부르는 요청만 센다.

  - 사용자마다 1분 · 하루 한도, 서버 전체 하루 한도. 넘으면 429와 다시 시도할 수 있는 시각 안내
  - 무엇을 세는가: 질문 · 조건 탐색 · 빛의 편지 · 마음 한 줄 · 별자리 설명 · 하늘 안내(guide=true).
    하늘 계산(guide=false) · 조회(GET)는 세지 않는다 — 예산을 다 써도 하늘과 내 세계 보기는 그대로 (app.py의 spend_ai)
  - 사용자 주소: 전달 헤더(X-Forwarded-For · CF-Connecting-IP)를 여기서 직접 읽지 않는다.
    Uvicorn이 신뢰할 프록시(FORWARDED_ALLOW_IPS, IP · CIDR)에서 온 연결일 때만 X-Forwarded-For를 오른쪽부터 읽어
    신뢰하지 않는 첫 주소를 request.client로 정한다. 그 값만 쓴다 — 사용자가 맨 앞에 끼워 넣은 주소는 고를 수 없다
  - 메모리에만 둔다 (서버 한 대 기준). 다시 시작하면 처음부터 센다
기본 설정(config.toml)에서는 꺼져 있다. 배포 설정(config.deploy.toml)에서 켠다.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

from vasthorizon.config import LimitsConfig

DAY = 86400.0


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    retry_after: int = 0       # 초
    reason: str = ""           # "minute" | "day" | "global" | "budget" (하루 예산 — app.py의 spend_ai)


class RateLimitedError(RuntimeError):
    """AI 호출 한도를 넘었을 때 — 429와 Retry-After로 바꿔 보낸다."""

    def __init__(self, verdict: Verdict) -> None:
        super().__init__(message(verdict))
        self.verdict = verdict


class RateLimiter:
    def __init__(self, cfg: LimitsConfig, clock=time.monotonic) -> None:
        self.cfg = cfg
        self.clock = clock
        self._per_ip: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()
        self._lock = threading.Lock()

    def check(self, ip: str) -> Verdict:
        now = self.clock()
        with self._lock:
            hits = self._per_ip.setdefault(ip, deque())
            while hits and now - hits[0] >= DAY:
                hits.popleft()
            while self._global and now - self._global[0] >= DAY:
                self._global.popleft()
            recent = [t for t in hits if now - t < 60]
            if len(recent) >= self.cfg.per_ip_per_minute:
                return Verdict(False, max(1, int(60 - (now - recent[0])) + 1), "minute")
            if len(hits) >= self.cfg.per_ip_per_day:
                return Verdict(False, max(1, int(DAY - (now - hits[0])) + 1), "day")
            if len(self._global) >= self.cfg.global_per_day:
                return Verdict(False, max(1, int(DAY - (now - self._global[0])) + 1), "global")
            hits.append(now)
            self._global.append(now)
            if len(self._per_ip) > 50000:                    # 오래된 주소 정리 (메모리 보호)
                for key in [k for k, v in self._per_ip.items() if not v or now - v[-1] >= DAY][:10000]:
                    del self._per_ip[key]
            return Verdict(True)


def client_key(request) -> str:
    """한도를 셀 사용자 주소 — Uvicorn이 신뢰 프록시 설정으로 확정한 request.client. 전달 헤더는 다시 읽지 않는다."""
    return request.client.host if request.client else "unknown"


def message(v: Verdict) -> str:
    minutes = max(1, round(v.retry_after / 60))
    if v.reason == "minute":
        return "질문이 너무 빠르게 이어지고 있습니다. 1분쯤 뒤에 다시 물어봐 주세요."
    if v.reason == "day":
        return f"오늘 이 기기에서 물을 수 있는 횟수를 다 썼습니다. 약 {minutes // 60 or 1}시간 뒤에 다시 이용해 주세요."
    if v.reason == "budget":
        return "오늘의 예산을 다 썼습니다. 내일 다시 찾아 주세요. 하늘과 내 세계 보기는 그대로 쓸 수 있습니다."
    return "오늘 서비스가 답할 수 있는 횟수를 모두 썼습니다. 내일 다시 찾아 주세요. 하늘과 내 세계 보기는 그대로 쓸 수 있습니다."
