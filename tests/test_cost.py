"""비용 절감 — 호출별 사용량 기록 · 모델 분리 · 서버 응답 캐시 · 하루 예산.

외부 호출 없이 확인한다 (가짜 채팅 모델 · 가짜 기능 함수, 키 값은 가짜).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage

from tests.fakes import FakeChat
from vasthorizon import config as config_module
from vasthorizon import usage
from vasthorizon.cache import ResponseCache, normalize_text, text_hash
from vasthorizon.config import CacheConfig, LimitsConfig, ModelPrice, get_settings
from vasthorizon.usage import KST, UsageLog, call_cost, tracked_invoke

SONNET = ModelPrice(input=2.0, output=10.0, cache_read=0.2, cache_write=2.5)
HAIKU = ModelPrice(input=0.1, output=0.5)
PRICES = {"claude-sonnet-5-5": SONNET, "claude-haiku-5-5": HAIKU}


def fake_model(content: str, model: str = "claude-sonnet-5-5", **usage_metadata) -> GenericFakeChatModel:
    meta = {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200,
            "output_token_details": {"reasoning": 120}, "input_token_details": {"cache_read": 0}}
    meta.update(usage_metadata)
    m = GenericFakeChatModel(messages=iter([AIMessage(content, usage_metadata=meta,
                                                      response_metadata={"model_name": model})]))
    return m


class Clock:
    def __init__(self, at: datetime):
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class UsageLogTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "usage.jsonl"
        self.clock = Clock(datetime(2026, 10, 24, 23, 50, tzinfo=KST))

    def tearDown(self):
        self.dir.cleanup()

    def log(self) -> UsageLog:
        return UsageLog(self.path, PRICES.get, now=self.clock)

    def test_records_model_purpose_tokens_time_and_cost(self):
        log = self.log()
        with usage.feature("ask"):
            reply = tracked_invoke(fake_model("답 [근거 1]"), [HumanMessage("질문")], "ask.answer", usage_log=log)
        self.assertEqual(reply.content, "답 [근거 1]")
        [row] = rows(self.path)
        self.assertEqual((row["kind"], row["feature"], row["purpose"], row["model"]), ("llm", "ask", "ask.answer", "claude-sonnet-5-5"))
        self.assertEqual((row["input"], row["output"], row["reasoning"], row["cache_read"]), (1000, 200, 120, 0))
        self.assertFalse(row["prompt_cache_hit"])
        self.assertGreaterEqual(row["seconds"], 0)
        self.assertAlmostEqual(row["cost_usd"], (1000 * 2 + 200 * 10) / 1e6)
        self.assertEqual(row["day"], "2026-10-24")
        self.assertNotIn("질문", self.path.read_text(encoding="utf-8"))           # 프롬프트 · 응답 본문은 남기지 않는다
        self.assertNotIn("답 [근거 1]", self.path.read_text(encoding="utf-8"))

    def test_prompt_cache_tokens_priced_separately(self):
        self.assertAlmostEqual(call_cost(SONNET, 1000, 100, cache_read=600, cache_write=100),
                               (300 * 2 + 600 * 0.2 + 100 * 2.5 + 100 * 10) / 1e6)
        self.assertAlmostEqual(call_cost(HAIKU, 1000, 0, cache_read=1000), 1000 * 0.01 / 1e6)   # 비우면 입력 단가의 0.1배
        self.assertEqual(call_cost(None, 5000, 5000), 0.0)                                     # 가격표에 없는 모델
        log = self.log()
        tracked_invoke(fake_model("x", input_token_details={"cache_read": 800}), [], "explore.filter", usage_log=log)
        self.assertTrue(rows(self.path)[0]["prompt_cache_hit"])

    def test_failed_call_recorded_without_message(self):
        class Boom(GenericFakeChatModel):
            def _generate(self, *a, **k):
                raise RuntimeError("sk-secret 비밀")
        log = self.log()
        with self.assertRaises(RuntimeError):
            tracked_invoke(Boom(messages=iter([])), [], "ask.query", usage_log=log)
        [row] = rows(self.path)
        self.assertEqual(row["error"], "RuntimeError")
        self.assertNotIn("sk-secret", self.path.read_text(encoding="utf-8"))
        self.assertEqual(log.today().errors, 1)

    def test_today_totals_survive_restart_and_reset_next_day(self):
        log = self.log()
        tracked_invoke(fake_model("a"), [], "letter", usage_log=log)
        tracked_invoke(fake_model("b", model="claude-haiku-5-5"), [], "ask.query", usage_log=log)
        log.record_cache_hit("explore")
        again = self.log()                                                     # 서버 재시작
        t = again.today()
        self.assertEqual((t.calls, t.input_tokens, t.output_tokens, t.reasoning_tokens, t.cache_hits), (2, 2000, 400, 240, 1))
        self.assertAlmostEqual(t.cost_usd, (1000 * 2 + 200 * 10 + 1000 * 0.1 + 200 * 0.5) / 1e6)
        self.clock.at += timedelta(minutes=20)                                 # 한국 시각 자정이 지났다
        self.assertEqual(again.today().calls, 0)
        self.assertEqual(again.today().day, "2026-10-25")
        self.assertEqual(usage.seconds_until_tomorrow(datetime(2026, 10, 24, 23, 59, 30, tzinfo=KST)), 31)

    def test_invoke_json_and_generate_record_purpose(self):
        from vasthorizon.rag.graph import generate_validated
        from vasthorizon.rag.llm_json import invoke_json
        from vasthorizon.rag.retrieval import Evidence
        log = self.log()
        ev = Evidence(number=1, chunk_id="c1", kind="항목", source_type="카탈로그", title="베가", section="", url="", text="[베가]\n0등급")
        with mock.patch.object(usage, "default_log", return_value=log):
            invoke_json(fake_model('{"queries": ["베가"]}', model="claude-haiku-5-5"), [], purpose="ask.query")
            generate_validated(fake_model("베가는 0등급입니다 [근거 1]"), [], [ev], purpose="letter")
            invoke_json(FakeChat('{"a": 1}'), [], purpose="ask.select")         # 테스트용 가짜(BaseChatModel 아님)는 기록하지 않는다
        self.assertEqual([(r["purpose"], r["model"]) for r in rows(self.path)],
                         [("ask.query", "claude-haiku-5-5"), ("letter", "claude-sonnet-5-5")])

    def test_health_shows_today_usage_without_key(self):
        from vasthorizon.api.services import check_health
        log = self.log()
        tracked_invoke(fake_model("a"), [], "letter", usage_log=log)
        with mock.patch("vasthorizon.config.get_llm_key", return_value="sk-ant-secret-value"), \
             mock.patch("vasthorizon.store.chroma.collection_count", return_value=0):
            health = check_health([], 2026, log)
        body = health.model_dump_json()
        self.assertEqual((health.usage.calls, health.usage.input_tokens, health.usage.output_tokens), (1, 1000, 200))
        self.assertAlmostEqual(health.usage.cost_usd, 0.004)
        self.assertEqual(health.usage.budget_usd, get_settings().limits.daily_cost_usd or None)
        self.assertNotIn("sk-ant", body)


HAS_DEPLOY = all(importlib.util.find_spec(m) for m in ("anthropic", "langchain_anthropic"))


def deploy_settings(**llm_changes):
    from tests.test_deploy import deploy_settings as base
    s = base()
    return dataclasses.replace(s, llm=dataclasses.replace(s.llm, **llm_changes)) if llm_changes else s


@unittest.skipUnless(HAS_DEPLOY, "배포 의존성(requirements-deploy.txt)이 없는 환경")
class ModelSplitTest(unittest.TestCase):
    def models(self, settings):
        from vasthorizon import llm
        with mock.patch.object(llm, "get_settings", return_value=settings), \
             mock.patch.object(llm, "get_claude_key", return_value="sk-test"):
            return llm.llm(), llm.fast_llm(), llm.json_chat_model()

    def test_answer_and_fast_models_with_effort(self):
        answer, fast, json_model = self.models(deploy_settings())
        self.assertEqual((answer.model, answer.reasoning_effort), ("claude-sonnet-5-5", "medium"))
        self.assertEqual((fast.model, fast.reasoning_effort), ("claude-haiku-5-5", "low"))
        self.assertEqual(json_model.model, "claude-haiku-5-5")                 # 기존 호출부(json_chat_model)도 구조화 모델
        payload = fast._get_request_payload([HumanMessage("x")])
        self.assertEqual(payload["output_config"]["effort"], "low")
        self.assertNotIn("thinking", payload)                                  # thinking은 모델 기본값(adaptive)
        self.assertNotIn("temperature", payload)

    def test_effort_skipped_for_models_without_effort(self):
        _, fast, _ = self.models(deploy_settings(anthropic_fast_model="claude-haiku-4-5"))
        self.assertEqual(fast.model, "claude-haiku-4-5")
        self.assertIsNone(fast.reasoning_effort)
        self.assertNotIn("output_config", fast._get_request_payload([HumanMessage("x")]))
        answer, _, _ = self.models(deploy_settings(answer_effort=""))
        self.assertIsNone(answer.reasoning_effort)                             # 빈 값이면 모델 기본값

    def test_empty_fast_model_falls_back_to_answer_model(self):
        _, fast, _ = self.models(deploy_settings(anthropic_fast_model=""))
        self.assertEqual((fast.model, fast.reasoning_effort), ("claude-sonnet-5-5", "low"))

    def test_invalid_effort_rejected(self):
        from vasthorizon.config import PROJECT_ROOT
        text = (PROJECT_ROOT / "config.deploy.toml").read_text(encoding="utf-8").replace('fast_effort = "low"', 'fast_effort = "none"', 1)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bad.toml"
            path.write_text(text, encoding="utf-8")
            with mock.patch.dict("os.environ", {"VH_CONFIG": str(path)}):
                get_settings.cache_clear()
                try:
                    with self.assertRaises(ValueError):
                        get_settings()
                finally:
                    get_settings.cache_clear()


class ModelRoutingTest(unittest.TestCase):
    """기능별로 어느 모델을 부르는가 — 구조화(검색어 · 선별 · 분류)는 fast_llm, 사용자에게 보이는 글은 llm."""

    def setUp(self):
        self.answer, self.fast = FakeChat(), FakeChat()
        patches = [mock.patch("vasthorizon.llm.llm", return_value=self.answer),
                   mock.patch("vasthorizon.llm.fast_llm", return_value=self.fast)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_collector_uses_fast_model(self):
        from vasthorizon.collect.collector import Collector
        self.assertIs(Collector(cache=mock.Mock()).llm, self.fast)

    def test_letter_uses_answer_model(self):
        from vasthorizon.data.catalog import load_catalog
        from vasthorizon.features.light_letter import write_letter
        star = next(it for it in load_catalog()["items"] if it["group"] == "star" and it.get("distance"))
        self.answer.replies.append("이 빛은 오래전에 출발했습니다 [근거 1]")
        result = write_letter(star, 2026, collector=mock.Mock(fetch_wiki=mock.Mock(return_value=None)))
        self.assertEqual(result.status, "cited")
        self.assertEqual((len(self.answer.received), len(self.fast.received)), (1, 0))

    def test_perspective_classify_uses_fast_model(self):
        from vasthorizon.features.perspective import perspective
        self.fast.replies.append('{"crisis": true}')
        result = perspective("요즘 마음이 무겁다", None, [])
        self.assertEqual(result.status, "crisis")
        self.assertEqual((len(self.fast.received), len(self.answer.received)), (1, 0))


class FingerprintTest(unittest.TestCase):
    def test_prompt_version_changes_fingerprint(self):
        from vasthorizon.api import app as app_module
        before = app_module.cache_fingerprint([], 2026)
        bumped = {**app_module.PROMPT_VERSIONS, "perspective": app_module.PROMPT_VERSIONS["perspective"] + 1}
        with mock.patch.object(app_module, "PROMPT_VERSIONS", bumped):
            self.assertNotEqual(app_module.cache_fingerprint([], 2026), before)
        self.assertEqual(app_module.cache_fingerprint([], 2026), before)


class ResponseCacheTest(unittest.TestCase):
    def test_ttl_disk_and_memory(self):
        now = [1000.0]
        with tempfile.TemporaryDirectory() as d:
            c = ResponseCache(Path(d), memory_items=2, clock=lambda: now[0])
            c.put("letter", ["Q1"], {"letter": "편지"}, ttl_days=1)
            self.assertEqual(c.get("letter", ["Q1"]), {"letter": "편지"})
            other = ResponseCache(Path(d), clock=lambda: now[0])             # 서버 재시작 — 디스크에서
            self.assertEqual(other.get("letter", ["Q1"]), {"letter": "편지"})
            self.assertIsNone(other.get("letter", ["Q2"]))
            self.assertIsNone(other.get("unfold", ["Q1"]))                   # 대상이 다르면 다른 키
            now[0] += 86400 + 1
            self.assertIsNone(c.get("letter", ["Q1"]))                       # 만료
            self.assertFalse(any(Path(d).rglob("*.json")))                   # 만료 파일은 지운다

    def test_returned_value_is_a_copy_and_lru_bounded(self):
        c = ResponseCache(None, memory_items=2)
        c.put("a", [1], {"x": [1]}, 1)
        c.get("a", [1])["x"].append(2)
        self.assertEqual(c.get("a", [1]), {"x": [1]})
        c.put("a", [2], {}, 1)
        c.put("a", [3], {}, 1)
        self.assertIsNone(c.get("a", [1]))

    def test_corrupt_file_is_a_miss(self):
        with tempfile.TemporaryDirectory() as d:
            c = ResponseCache(Path(d))
            c.put("a", [1], {"x": 1}, 1)
            next(Path(d).rglob("*.json")).write_text("{깨짐", encoding="utf-8")
            self.assertIsNone(ResponseCache(Path(d)).get("a", [1]))

    def test_day_boundary_caps_ttl_at_next_utc_midnight(self):
        from vasthorizon.cache import DAY, next_utc_midnight
        noon = 20000 * DAY + 12 * 3600                                     # 어느 날 UTC 12시
        self.assertEqual(next_utc_midnight(noon), 20001 * DAY)
        self.assertEqual(next_utc_midnight(20000 * DAY), 20001 * DAY)     # 자정 정각이면 다음 자정
        now = [noon]
        with tempfile.TemporaryDirectory() as d:
            c = ResponseCache(Path(d), clock=lambda: now[0])
            c.put("ask", ["live"], {"a": 1}, ttl_days=1, day_boundary=True)
            c.put("ask", ["plain"], {"a": 2}, ttl_days=1)
            expires = sorted(json.loads(p.read_text(encoding="utf-8"))["expires"] for p in Path(d).rglob("*.json"))
            self.assertEqual(expires, [20001 * DAY, noon + DAY])           # 24시간 뒤가 아니라 그날 UTC 자정
            now[0] = 20001 * DAY - 1
            self.assertEqual(c.get("ask", ["live"]), {"a": 1})
            now[0] = 20001 * DAY + 1                                       # 날짜가 바뀌면 다시 만든다
            self.assertIsNone(c.get("ask", ["live"]))
            self.assertEqual(c.get("ask", ["plain"]), {"a": 2})
            now[0] = noon + 3600                                           # 자정까지가 TTL보다 길면 TTL이 먼저
            c.put("ask", ["short"], {"a": 3}, ttl_days=1 / 48, day_boundary=True)
            now[0] += 1801
            self.assertIsNone(c.get("ask", ["short"]))

    def test_sweep_removes_unread_expired_files(self):
        from vasthorizon import cache as cache_module
        now = [1000.0]
        json_files = lambda ns: sorted(p for p in Path(d).rglob("*.json") if p.parent.parent.name == ns)
        with tempfile.TemporaryDirectory() as d:
            c = ResponseCache(Path(d), clock=lambda: now[0])
            c.put("perspective", ["hash-a", None], {"answer": "사용자 문장이 든 응답"}, ttl_days=1)
            c.put("letter", ["Q1"], {"letter": "편지"}, ttl_days=7)
            stale_tmp = Path(d) / "letter" / "ab" / ".x.json.123.tmp"     # 원자적 쓰기 도중 죽어 남은 임시 파일
            stale_tmp.parent.mkdir(parents=True, exist_ok=True)
            stale_tmp.write_text("{", encoding="utf-8")
            os.utime(stale_tmp, (time.time() - 7200, time.time() - 7200))
            now[0] += 86400 + 1
            # 시작할 때 정리 — 아무도 다시 읽지 않은 마음 한 줄 응답 파일도 TTL 뒤에는 남지 않는다
            ResponseCache(Path(d), clock=lambda: now[0])
            self.assertEqual((len(json_files("perspective")), len(json_files("letter"))), (0, 1))
            self.assertFalse(stale_tmp.exists())
            self.assertEqual(c.sweep(), 0)
            self.assertNotIn(cache_module.cache_key("perspective", ["hash-a", None]), c._memory)   # 메모리에서도
            # put 100회마다 정리
            c.put("perspective", ["hash-b", None], {"answer": "b"}, ttl_days=1)
            now[0] += 86400 + 1
            with mock.patch.object(c, "sweep", wraps=c.sweep) as sweep:
                for i in range(cache_module.SWEEP_EVERY_PUTS):
                    c.put("explore", [i], {"i": i}, ttl_days=7)
            self.assertGreaterEqual(sweep.call_count, 1)
            self.assertEqual(json_files("perspective"), [])
            self.assertEqual(len(json_files("explore")), cache_module.SWEEP_EVERY_PUTS)   # 만료 전 응답은 남긴다
            self.assertEqual(c.get("letter", ["Q1"]), {"letter": "편지"})

    def test_sweeper_thread_runs_without_requests(self):
        now = [1000.0]
        with tempfile.TemporaryDirectory() as d:
            c = ResponseCache(Path(d), clock=lambda: now[0])
            c.put("perspective", ["hash-a", None], {"answer": "x"}, ttl_days=1)
            now[0] += 86400 + 1
            thread = c.start_sweeper(interval=0.01)
            try:
                deadline = time.time() + 5
                while any(Path(d).rglob("*.json")) and time.time() < deadline:
                    time.sleep(0.01)
                self.assertFalse(any(Path(d).rglob("*.json")))
            finally:
                thread.stop.set()
                thread.join(1)

    def test_normalize_is_light(self):
        self.assertEqual(normalize_text("  Voyager   1호는  어디?? "), "voyager 1호는 어디")
        self.assertNotEqual(normalize_text("베가는 밝아"), normalize_text("베가가 밝아"))   # 조사는 건드리지 않는다
        self.assertEqual(text_hash("마음이 무거워요."), text_hash(" 마음이 무거워요 "))
        self.assertNotIn("마음", text_hash("마음이 무거워요"))


# ── API: 캐시 적중은 LLM · 한도 · 예산을 쓰지 않는다 ─────────────────────────

STAR = {"id": "Q3415", "name": "베가", "name_en": "Vega", "group": "star", "kind": "별", "wiki_title": "베가",
        "attrs": {}, "distance": {"km": 25 * 9.4607e12, "ly": 25.0}, "ra_deg": 279.2, "dec_deg": 38.8, "sources": []}


class Calls:
    def __init__(self):
        self.explore = self.letter = self.perspective = 0


def cost_app(limits: LimitsConfig | None = None, log: UsageLog | None = None, cache: ResponseCache | None = None,
             cache_cfg: CacheConfig | None = None):
    from tests.test_api import ITEMS, FakeAsk, healthy
    from vasthorizon.api.app import create_app
    from vasthorizon.api.services import Services
    from vasthorizon.features.explore import ExploreResult
    from vasthorizon.features.light_letter import LetterResult, compute_departure
    from vasthorizon.features.perspective import PerspectiveResult
    from vasthorizon.rag.retrieval import Evidence
    calls = Calls()
    ev = Evidence(number=1, chunk_id="Q3415", kind="항목", source_type="카탈로그", title="베가", section="", url="", text="[베가]\n25광년")

    def explore(query):
        calls.explore += 1
        if log is not None:
            log.record_call("claude-haiku-5-5", "explore.filter", {"input_tokens": 1000, "output_tokens": 100})
        return ExploreResult(query=query, applied=["별"], cards=[], candidates=3, status="no_match")

    def letter(item):
        calls.letter += 1
        return LetterResult(item=item, departure=compute_departure(item, 2026), letter="편지 [근거 1]", status="cited",
                            cited=[ev], evidences=[ev])

    def perspective(text, theme):
        calls.perspective += 1
        return PerspectiveResult(text=text, status="cited", answer="곁에 놓을 사실 [근거 1]", cited=[ev], evidences=[ev])

    s = dataclasses.replace(get_settings(), limits=limits or LimitsConfig(), cache=cache_cfg or CacheConfig(enabled=True))
    ask = FakeAsk(warnings=[])                       # 경고가 있는 답은 캐시하지 않는다 (test_warning_answer_not_cached)
    with mock.patch.object(config_module, "get_settings", return_value=s):
        app = create_app(Services(items=[*ITEMS, STAR], ask=ask, health=healthy, explore=explore, letter=letter,
                                  perspective=perspective, cache=cache or ResponseCache(None), usage=log), web_dir=None)
    return TestClient(app, raise_server_exceptions=False), ask, calls


class ApiCacheTest(unittest.TestCase):
    LIMITS = LimitsConfig(enabled=True, per_ip_per_minute=2, per_ip_per_day=100, global_per_day=100)

    def setUp(self):
        self.log = UsageLog(None)
        self.c, self.ask, self.calls = cost_app(self.LIMITS, self.log)

    def test_explore_hit_skips_llm_and_limit(self):
        q = "신비로운 별"                             # 동의어 표로 다 풀리지 않아 LLM을 부르는 조건
        got = [self.c.post("/api/explore", json={"query": f" {q}{'?' * i} "}) for i in range(4)]
        self.assertEqual([r.status_code for r in got], [200] * 4)
        self.assertEqual([r.json()["cached"] for r in got], [False, True, True, True])
        self.assertEqual(got[3].json()["query"], f" {q}??? ")                      # 질문 글은 요청 그대로
        self.assertEqual(self.calls.explore, 1)
        self.assertEqual(self.log.today().cache_hits, 3)
        # 캐시 적중은 1분 한도(2회)를 쓰지 않았다 — 다른 조건 두 개 중 하나는 아직 된다
        codes = [self.c.post("/api/explore", json={"query": f"조건 {i}개인 은하"}).status_code for i in range(2)]
        self.assertEqual(codes, [200, 429])

    def test_failed_explore_not_cached(self):
        from vasthorizon.features.explore import ExploreResult
        services = self.c.app.state.services
        services.explore = lambda q: ExploreResult(query=q, applied=[], cards=[], candidates=0, status="failed")
        self.assertFalse(self.c.post("/api/explore", json={"query": "신비로운 행성"}).json()["cached"])
        self.assertFalse(self.c.post("/api/explore", json={"query": "신비로운 행성"}).json()["cached"])

    def test_letter_item_and_age_share_cache(self):
        a = self.c.post("/api/light-letter", json={"item_id": "Q3415"}).json()
        b = self.c.post("/api/light-letter", json={"age": 25}).json()               # 나이 25 → 같은 별
        self.assertEqual((a["cached"], b["cached"]), (False, True))
        self.assertEqual((b["matched_age"], b["item_id"], b["letter"]), (25, "Q3415", a["letter"]))
        self.assertIsNone(a["matched_age"])
        self.assertEqual(self.calls.letter, 1)

    def test_perspective_cached_by_hash(self):
        body = {"text": "오늘은 마음이 무겁다"}
        first, second = (self.c.post("/api/perspective", json=body).json() for _ in range(2))
        self.assertEqual((first["cached"], second["cached"], self.calls.perspective), (False, True, 1))

    def test_ask_cached_only_without_history(self):
        from tests.test_api import SESSION
        body = {"session_id": SESSION, "item_id": "Q48469", "question": "태양계를 벗어났나?"}
        first = self.c.post("/api/ask", json=body).json()
        again = self.c.post("/api/ask", json=body).json()                            # 같은 대화 — 기록이 있어 캐시 제외
        other = self.c.post("/api/ask", json={**body, "session_id": "other-session-02", "question": "태양계를 벗어났나"}).json()
        self.assertEqual([first["cached"], again["cached"], other["cached"]], [False, False, True])
        self.assertEqual(len(self.ask.calls), 2)
        self.assertEqual(other["question"], "태양계를 벗어났나")
        turns = self.c.get("/api/history/Q48469", params={"session_id": "other-session-02"}).json()["turns"]
        self.assertEqual([t["role"] for t in turns], ["user", "assistant"])          # 캐시 답도 대화 기록에 남는다

    def test_stream_hit_sends_result_without_progress(self):
        from tests.test_api import sse_events
        body = {"session_id": "stream-session-1", "item_id": "Q48469", "question": "태양계를 벗어났나?"}
        self.c.post("/api/ask", json=body)
        r = self.c.post("/api/ask/stream", json={**body, "session_id": "stream-session-2"})
        events = sse_events(r.text)
        self.assertEqual([e[0] for e in events], ["result"])
        self.assertTrue(events[0][1]["cached"])
        self.assertEqual(len(self.ask.calls), 1)
        # 캐시 적중 스트림도 처리권을 푼다 — 같은 대화의 다음 질문이 409(처리 중)가 아니다
        again = self.c.post("/api/ask/stream", json={**body, "session_id": "stream-session-2", "question": "다음 질문"})
        self.assertEqual(again.status_code, 200)
        self.assertEqual(sse_events(again.text)[-1][0], "result")

    def test_warning_answer_not_cached(self):
        # 리뷰 지적: 경고(문서 색인 실패 · 언어 혼입 등)가 붙은 답도 캐시되어 다음 사람에게 그대로 나갔다
        from tests.test_api import INDEX_WARNING, FakeAsk
        from vasthorizon.api import app as app_module
        self.c.app.state.services.ask = warned = FakeAsk(warnings=[INDEX_WARNING])
        body = {"session_id": "warn-session-1", "item_id": "Q48469", "question": "경고가 붙는 질문"}
        first = self.c.post("/api/ask", json=body).json()
        second = self.c.post("/api/ask", json={**body, "session_id": "warn-session-2"}).json()
        self.assertEqual((first["cached"], second["cached"], len(warned.calls)), (False, False, 2))
        self.assertIn(INDEX_WARNING, second["warnings"])
        result = warned({"id": "Q48469"}, "q")
        self.assertFalse(app_module.cacheable_answer(result))
        result.warnings = []
        self.assertTrue(app_module.cacheable_answer(result))

    def test_live_evidence_answer_gets_short_ttl(self):
        from vasthorizon.api import app as app_module
        from vasthorizon.rag.pipeline import AnswerResult
        from vasthorizon.rag.retrieval import Evidence
        live = Evidence(number=1, chunk_id="live:Q48469:2026-10-24", kind="항목", source_type="계산", title="x",
                        section="", url="", text="오늘 거리")
        result = AnswerResult(question="q", answer="a", status="cited", cited=[live], evidences=[live])
        self.assertTrue(app_module.has_live_evidence(result))
        cache = mock.Mock(wraps=ResponseCache(None))
        c, ask, _ = cost_app(cache=cache, cache_cfg=CacheConfig(enabled=True, ask_days=7, ask_live_days=1))
        ask_live = lambda *a, **k: AnswerResult(question="q", answer="오늘 거리는 [근거 1]", status="cited",
                                                cited=[live], evidences=[live])
        c.app.state.services.ask = ask_live
        c.post("/api/ask", json={"session_id": "live-session-1", "item_id": "Q48469", "question": "지금 어디야?"})
        self.assertEqual(cache.put.call_args.args[0], "ask")
        self.assertEqual(cache.put.call_args.args[3], 1)
        self.assertIs(cache.put.call_args.kwargs["day_boundary"], True)      # 다음 UTC 자정에 만료
        from tests.test_api import FakeAsk
        c.app.state.services.ask = FakeAsk(warnings=[])                     # 실시간 근거가 없으면 날짜 경계 없음
        c.post("/api/ask", json={"session_id": "live-session-2", "item_id": "Q48469", "question": "보통 질문"})
        self.assertEqual((cache.put.call_args.args[3], cache.put.call_args.kwargs["day_boundary"]), (7, False))

    def test_no_cache_without_cache_service(self):
        from tests.test_api import ITEMS, FakeAsk, healthy
        from vasthorizon.api.app import create_app
        from vasthorizon.api.services import Services
        ask = FakeAsk()
        c = TestClient(create_app(Services(items=ITEMS, ask=ask, health=healthy), web_dir=None))
        body = {"session_id": "nocache-session", "item_id": "Q48469", "question": "q"}
        c.post("/api/ask", json=body)
        self.assertFalse(c.post("/api/ask", json={**body, "session_id": "nocache-session-2"}).json()["cached"])
        self.assertEqual(len(ask.calls), 2)


class DailyBudgetTest(unittest.TestCase):
    def test_budget_exceeded_returns_429_but_cache_and_lookups_work(self):
        log = UsageLog(None, PRICES.get)
        c, _, calls = cost_app(LimitsConfig(enabled=False, daily_cost_usd=0.0002), log)
        self.assertEqual(c.post("/api/explore", json={"query": "신비로운 별"}).status_code, 200)       # 이 호출로 $0.00015
        self.assertEqual(c.post("/api/explore", json={"query": "가까운 은하"}).status_code, 200)       # $0.0003 — 예산 넘음
        over = c.post("/api/explore", json={"query": "신비로운 행성"})
        self.assertEqual((over.status_code, over.json()["code"]), (429, "rate_limited"))
        self.assertIn("오늘의 예산을 다 썼습니다", over.json()["message"])
        self.assertGreater(int(over.headers["Retry-After"]), 0)
        self.assertEqual(calls.explore, 2)                                           # LLM을 부르기 전에 막는다
        hit = c.post("/api/explore", json={"query": "신비로운 별"})                   # 캐시 적중은 예산을 쓰지 않는다
        self.assertEqual((hit.status_code, hit.json()["cached"]), (200, True))
        self.assertEqual(c.post("/api/explore", json={"query": "베가"}).status_code, 200)              # 이름만 — LLM 없음
        self.assertEqual(c.get("/api/items").status_code, 200)
        letter = c.post("/api/light-letter", json={"item_id": "Q3415"})
        self.assertEqual(letter.status_code, 429)

    def test_crisis_text_answered_even_when_budget_is_spent(self):
        # 리뷰 지적: 위기 표현도 예산 · 한도 검사(429)를 먼저 거쳐, 예산을 다 쓴 날에는 상담 창구 안내가 막혔다
        log = UsageLog(None, PRICES.get)
        log.record_call("claude-sonnet-5-5", "ask.answer", {"input_tokens": 10_000_000, "output_tokens": 0})
        c, _, calls = cost_app(LimitsConfig(enabled=True, per_ip_per_minute=1, per_ip_per_day=1, global_per_day=1,
                                            daily_cost_usd=0.0001), log)
        normal = c.post("/api/perspective", json={"text": "오늘은 마음이 무겁다"})
        self.assertEqual(normal.status_code, 429)                                   # 일반 문장은 예산에 막힌다
        for _ in range(3):                                                          # 한도(1회)를 넘겨도
            r = c.post("/api/perspective", json={"text": "죽고 싶어요"})
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual((body["status"], body["crisis"], body["cached"]), ("crisis", True, False))
            self.assertIn("109", [line["number"] for line in body["support"]])
        self.assertEqual(calls.perspective, 0)                                      # LLM · 서비스를 부르지 않았다

    def test_budget_zero_means_off(self):
        log = UsageLog(None, PRICES.get)
        log.record_call("claude-sonnet-5-5", "ask.answer", {"input_tokens": 10_000_000, "output_tokens": 0})
        c, _, _ = cost_app(LimitsConfig(daily_cost_usd=0.0), log)
        self.assertEqual(c.post("/api/explore", json={"query": "가까운 은하"}).status_code, 200)

    def test_deploy_budget_setting(self):
        from tests.test_deploy import deploy_settings as base
        s = base()
        self.assertEqual(s.limits.daily_cost_usd, 3.3)
        self.assertEqual(get_settings().limits.daily_cost_usd, 3.3)                    # 두 설정 파일이 같게
        self.assertEqual(s.usage.price("claude-sonnet-5-5"), SONNET)
        self.assertEqual(s.usage.price("claude-haiku-5-5").input, 0.1)
        self.assertIn("deploy", str(s.usage.log_path))
        self.assertIn("responses", str(s.cache.dir))
        self.assertTrue(s.cache.enabled and get_settings().cache.enabled)


if __name__ == "__main__":
    unittest.main()
