"""LLM 호출 사용량 기록과 하루 비용 집계.

호출마다 JSONL 한 줄을 남긴다 (설정 [usage] log_path, 기본 cache_dir/usage.jsonl).

| 필드                  | 내용                                                                   |
|-----------------------|------------------------------------------------------------------------|
| ts · day              | 기록 시각 (한국 시각, ISO) · 집계 날짜                                   |
| kind                  | llm (모델 호출) · cache (서버 응답 캐시 적중 — LLM을 부르지 않았다)        |
|                       | tts (편지 읽어 주기 — Google TTS 합성, 비용 0 · 무료 구간 안에서만 쓴다)    |
| feature · purpose     | 요청 기능 (ask · explore · letter …) · 호출 용도 (ask.query · ask.select …) |
| model                 | 모델 이름                                                               |
| input · output        | 입력 토큰 (캐시 읽기 · 쓰기 포함) · 출력 토큰 (추론 포함)                   |
| chars                 | tts만 — 합성한 글자 수 (Google이 과금하는 입력 문자 수)                    |
| reasoning             | 출력 토큰 가운데 추론(thinking) 토큰                                      |
| cache_read · cache_write | Anthropic 프롬프트 캐시 읽기 · 쓰기 토큰. prompt_cache_hit은 읽기가 있었는가 |
| seconds · cost_usd    | 소요 시간 · 설정 가격표로 계산한 추정 비용                                |
| error                 | 실패한 호출의 오류 종류 (메시지 · 키 · 요청 본문은 남기지 않는다)           |

프롬프트 · 응답 본문은 기록하지 않는다.
하루 합계는 메모리에 두고, 서버를 다시 시작하면 기록 파일에서 오늘 줄을 다시 읽어 이어 센다.
'오늘'은 한국 시각(UTC+9, 서머타임 없음) 기준이다 — 하루 예산([limits] daily_cost_usd)도 같은 날짜로 센다.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from vasthorizon.config import ModelPrice, get_settings

log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

_feature: ContextVar[str | None] = ContextVar("vasthorizon_usage_feature", default=None)


@contextmanager
def feature(name: str) -> Iterator[None]:
    """이 블록 안의 LLM 호출을 name 기능(ask · explore · letter …)으로 기록한다. 스레드마다 따로 정한다."""
    token = _feature.set(name)
    try:
        yield
    finally:
        _feature.reset(token)


def current_feature() -> str | None:
    return _feature.get()


def kst_now() -> datetime:
    return datetime.now(KST)


def seconds_until_tomorrow(now: datetime | None = None) -> int:
    now = (now or kst_now()).astimezone(KST)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()) + 1)


@dataclass
class DayTotals:
    day: str
    calls: int = 0                  # LLM 호출 수 (실패 포함)
    errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    cache_hits: int = 0             # 서버 응답 캐시 적중 (LLM 호출 없음)
    tts_chars: int = 0              # 편지 읽어 주기로 합성한 글자 수 (LLM 호출 · 비용에 넣지 않는다)

    def add(self, row: dict) -> None:
        if row.get("kind") == "cache":
            self.cache_hits += 1
            return
        if row.get("kind") == "tts":
            self.tts_chars += int(row.get("chars") or 0)
            return
        self.calls += 1
        self.errors += 1 if row.get("error") else 0
        self.input_tokens += int(row.get("input") or 0)
        self.output_tokens += int(row.get("output") or 0)
        self.reasoning_tokens += int(row.get("reasoning") or 0)
        self.cache_read_tokens += int(row.get("cache_read") or 0)
        self.cost_usd += float(row.get("cost_usd") or 0.0)


def call_cost(price: ModelPrice | None, input_tokens: int, output_tokens: int,
              cache_read: int = 0, cache_write: int = 0) -> float:
    """추정 비용 ($). input_tokens는 캐시 읽기 · 쓰기를 포함한 전체 입력 (LangChain usage_metadata와 같은 기준)."""
    if price is None:
        return 0.0
    read_price = price.cache_read if price.cache_read is not None else price.input * 0.1
    write_price = price.cache_write if price.cache_write is not None else price.input * 1.25
    plain = max(0, input_tokens - cache_read - cache_write)
    return (plain * price.input + cache_read * read_price + cache_write * write_price
            + output_tokens * price.output) / 1_000_000


def usage_numbers(usage) -> dict:
    """LangChain usage_metadata(dict) → 기록할 숫자. 없으면 모두 0."""
    usage = usage or {}
    details_in = usage.get("input_token_details") or {}
    details_out = usage.get("output_token_details") or {}
    return {"input": int(usage.get("input_tokens") or 0), "output": int(usage.get("output_tokens") or 0),
            "reasoning": int(details_out.get("reasoning") or 0),
            "cache_read": int(details_in.get("cache_read") or 0),
            "cache_write": int(details_in.get("cache_creation") or 0)}


class UsageLog:
    """호출 기록 파일 + 오늘 합계. path가 None이면 파일 없이 메모리에서만 센다 (테스트)."""

    def __init__(self, path: Path | None, price: Callable[[str], ModelPrice | None] = lambda model: None,
                 now: Callable[[], datetime] = kst_now) -> None:
        self.path = path
        self.price = price
        self.now = now
        self._lock = threading.Lock()
        self._totals = DayTotals(day=self._day())
        self._load()

    def _day(self) -> str:
        return self.now().astimezone(KST).date().isoformat()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            with self.path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue                          # 쓰다 끊긴 마지막 줄 등
                    if isinstance(row, dict) and row.get("day") == self._totals.day:
                        self._totals.add(row)
        except OSError as e:
            log.warning("사용량 기록을 읽지 못했습니다: %s", type(e).__name__)

    def _write(self, row: dict) -> None:
        with self._lock:
            if row["day"] != self._totals.day:            # 날짜가 바뀌었다 — 새 날의 합계로
                self._totals = DayTotals(day=row["day"])
            self._totals.add(row)
            if self.path is None:
                return
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            except OSError as e:                          # 기록 실패로 답변을 막지 않는다
                log.warning("사용량을 기록하지 못했습니다: %s", type(e).__name__)

    def _base(self, kind: str) -> dict:
        now = self.now().astimezone(KST)
        return {"ts": now.isoformat(timespec="seconds"), "day": now.date().isoformat(), "kind": kind,
                "feature": current_feature()}

    def record_call(self, model: str, purpose: str, usage=None, seconds: float = 0.0,
                    error: str | None = None) -> dict:
        numbers = usage_numbers(usage)
        row = {**self._base("llm"), "purpose": purpose, "model": model, **numbers,
               "prompt_cache_hit": numbers["cache_read"] > 0, "seconds": round(seconds, 3),
               "cost_usd": round(call_cost(self.price(model), numbers["input"], numbers["output"],
                                           numbers["cache_read"], numbers["cache_write"]), 6)}
        if error:
            row["error"] = error
        self._write(row)
        return row

    def record_cache_hit(self, namespace: str) -> dict:
        row = {**self._base("cache"), "purpose": namespace}
        self._write(row)
        return row

    def record_tts(self, chars: int, seconds: float = 0.0, error: str | None = None, voice: str | None = None) -> dict:
        """편지 읽어 주기 합성 한 번 — 글자 수 · 소요 시간. 비용은 0 (무료 구간 안에서만 쓴다)."""
        row = {**self._base("tts"), "purpose": "tts", "model": voice, "chars": int(chars), "seconds": round(seconds, 3),
               "cost_usd": 0.0}
        if error:
            row["error"] = error
        self._write(row)
        return row

    def today(self) -> DayTotals:
        with self._lock:
            if self._totals.day != self._day():
                self._totals = DayTotals(day=self._day())
            return DayTotals(**asdict(self._totals))

    def today_cost(self) -> float:
        return self.today().cost_usd


@lru_cache(maxsize=1)
def default_log() -> UsageLog | None:
    """설정에 따른 기록기 (프로세스에 하나). [usage] enabled = false면 None — 기록 · 예산 집계를 하지 않는다."""
    s = get_settings()
    if not s.usage.enabled:
        return None
    return UsageLog(s.usage.log_path or s.paths.cache_dir / "usage.jsonl", s.usage.price)


def model_name(llm, reply=None) -> str:
    name = getattr(llm, "model", None) or getattr(llm, "model_name", None)
    if not name and reply is not None:
        name = (getattr(reply, "response_metadata", None) or {}).get("model_name")
    return str(name or type(llm).__name__)


def tracked_invoke(llm, messages, purpose: str, usage_log: UsageLog | None = None):
    """llm.invoke(messages)를 부르고 사용량을 기록한다.

    실제 채팅 모델(LangChain BaseChatModel)만 기록한다 — 테스트의 가짜 모델은 기록 파일에 남기지 않는다.
    """
    from langchain_core.language_models import BaseChatModel
    target = usage_log or (default_log() if isinstance(llm, BaseChatModel) else None)
    if target is None:
        return llm.invoke(messages)
    t = time.perf_counter()
    try:
        reply = llm.invoke(messages)
    except Exception as e:
        target.record_call(model_name(llm), purpose, None, time.perf_counter() - t, error=type(e).__name__)
        raise
    target.record_call(model_name(llm, reply), purpose, getattr(reply, "usage_metadata", None), time.perf_counter() - t)
    return reply
