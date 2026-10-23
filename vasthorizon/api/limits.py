"""공개 배포에서 개인 API 키를 지키는 호출 한도 — LLM을 부르는 요청(POST /api/...)만 센다.

  - 사용자(IP)마다 1분 · 하루 한도, 서버 전체 하루 한도. 넘으면 429와 다시 시도할 수 있는 시각 안내
  - 메모리에만 둔다 (서버 한 대 기준). 다시 시작하면 처음부터 센다
  - 리버스 프록시 뒤라면(trust_proxy) X-Forwarded-For의 첫 주소를 사용자 주소로 본다.
    프록시가 없는데 이 헤더를 믿으면 누구나 주소를 바꿔 한도를 피할 수 있으므로 기본은 끔
과제 환경(config.toml)에서는 꺼져 있다. 배포 설정(config.deploy.toml)에서 켠다.
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
    reason: str = ""           # "minute" | "day" | "global"


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


def client_ip(headers, peer: str | None, trust_proxy: bool) -> str:
    if trust_proxy:
        forwarded = headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
        real = headers.get("cf-connecting-ip") or headers.get("x-real-ip")
        if real:
            return real.strip()
    return peer or "unknown"


def message(v: Verdict) -> str:
    minutes = max(1, round(v.retry_after / 60))
    if v.reason == "minute":
        return "질문이 너무 빠르게 이어지고 있습니다. 1분쯤 뒤에 다시 물어봐 주세요."
    if v.reason == "day":
        return f"오늘 이 기기에서 물을 수 있는 횟수를 다 썼습니다. 약 {minutes // 60 or 1}시간 뒤에 다시 이용해 주세요."
    return "오늘 서비스가 답할 수 있는 횟수를 모두 썼습니다. 내일 다시 찾아 주세요. 하늘과 내 세상 보기는 그대로 쓸 수 있습니다."
