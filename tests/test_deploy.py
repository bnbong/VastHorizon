"""배포 (Claude API + 로컬 임베딩) — 제공자 선택 · 키 · 응답 글 · 호출 한도 · CORS · 정적 화면 빌드.

외부 호출 없이 확인한다 (키 값은 가짜, 모델은 내려받지 않는다).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from vasthorizon import config as config_module
from vasthorizon.api.limits import RateLimiter
from vasthorizon.config import PROJECT_ROOT, LimitsConfig, ServerConfig, get_settings
from vasthorizon.store import chroma
from vasthorizon.llm import API_ERRORS, MissingApiKeyError, reply_text


def deploy_settings(**changes):
    with mock.patch.dict(os.environ, {"VH_CONFIG": "config.deploy.toml"}):
        get_settings.cache_clear()
        try:
            s = get_settings()
        finally:
            get_settings.cache_clear()
    return dataclasses.replace(s, **changes) if changes else s


class ConfigTest(unittest.TestCase):
    def test_submission_config_unchanged(self):
        # 과제 제출 환경은 GMS 그대로, 한도 · CORS 없음
        s = get_settings()
        self.assertEqual((s.llm.provider, s.llm.embedding_provider), ("gms", "gms"))
        self.assertFalse(s.limits.enabled)
        self.assertEqual(s.server.cors_origins, ())

    def test_deploy_config(self):
        s = deploy_settings()
        self.assertEqual((s.llm.provider, s.llm.embedding_provider), ("anthropic", "local"))
        self.assertTrue(s.limits.enabled)
        self.assertIn("deploy", str(s.paths.chroma_dir))            # GMS 색인과 다른 폴더 (벡터를 섞지 않는다)
        self.assertNotEqual(s.paths.chroma_dir, get_settings().paths.chroma_dir)

    def test_env_overrides(self):
        with mock.patch.dict(os.environ, {"VH_CONFIG": "config.deploy.toml", "VH_CORS_ORIGINS": "https://a.pages.dev, https://b.dev"}):
            get_settings.cache_clear()
            try:
                s = get_settings()
            finally:
                get_settings.cache_clear()
        self.assertEqual(s.server.cors_origins, ("https://a.pages.dev", "https://b.dev"))

    def test_invalid_provider_rejected(self):
        text = (PROJECT_ROOT / "config.toml").read_text(encoding="utf-8").replace("[llm]", '[llm]\nprovider = "openai"', 1)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bad.toml"
            path.write_text(text, encoding="utf-8")
            with mock.patch.dict(os.environ, {"VH_CONFIG": str(path)}):
                get_settings.cache_clear()
                try:
                    with self.assertRaises(ValueError):
                        get_settings()
                finally:
                    get_settings.cache_clear()


class KeyTest(unittest.TestCase):
    def test_key_follows_provider(self):
        with mock.patch.object(config_module, "get_settings", return_value=deploy_settings()), \
             mock.patch.dict(os.environ, {"CLAUDE_API_KEY": "sk-test", "GMS_KEY": ""}):
            self.assertEqual(config_module.key_name(), "CLAUDE_API_KEY")
            self.assertEqual(config_module.get_llm_key(), "sk-test")
        with mock.patch.object(config_module, "get_settings", return_value=deploy_settings()), \
             mock.patch.object(config_module, "load_dotenv"), \
             mock.patch.dict(os.environ, {"CLAUDE_API_KEY": "", "ANTHROPIC_API_KEY": "sk-alt"}):
            self.assertEqual(config_module.get_llm_key(), "sk-alt")    # ANTHROPIC_API_KEY도 받는다

    def test_missing_claude_key_message_names_the_key(self):
        from vasthorizon import llm
        with mock.patch.object(config_module, "get_settings", return_value=deploy_settings()), \
             mock.patch.object(llm, "get_settings", return_value=deploy_settings()), \
             mock.patch.object(llm, "get_claude_key", return_value=None):
            with self.assertRaises(MissingApiKeyError) as ctx:
                llm.chat_model()
        self.assertIn("CLAUDE_API_KEY", str(ctx.exception))


HAS_DEPLOY = all(importlib.util.find_spec(m) for m in ("anthropic", "langchain_anthropic", "fastembed"))


@unittest.skipUnless(HAS_DEPLOY, "배포 의존성(requirements-deploy.txt)이 없는 과제 환경")
class ClaudeModelTest(unittest.TestCase):
    def test_chat_model_is_claude_without_openai_options(self):
        from vasthorizon import llm
        with mock.patch.object(llm, "get_settings", return_value=deploy_settings()), \
             mock.patch.object(llm, "get_claude_key", return_value="sk-test"):
            m = llm.chat_model(model_kwargs={"response_format": {"type": "json_object"}}, temperature=0)
            j = llm.json_chat_model()
        self.assertEqual(type(m).__name__, "ChatAnthropic")
        self.assertEqual(m.model, "claude-sonnet-5-5")
        self.assertIsNone(getattr(m, "temperature", None))         # 최신 Claude는 temperature를 받지 않는다
        self.assertEqual(type(j).__name__, "ChatAnthropic")

    def test_api_errors_cover_both_providers(self):
        import anthropic
        import openai
        self.assertIn(openai.APIError, API_ERRORS)
        self.assertIn(anthropic.APIError, API_ERRORS)

    def test_reply_text(self):
        class Msg:
            def __init__(self, content): self.content = content
        self.assertEqual(reply_text(Msg("답")), "답")                               # GMS (문자열)
        self.assertEqual(reply_text(Msg([{"type": "text", "text": "베가는 "}, {"type": "text", "text": "0등급"},
                                         {"type": "thinking", "thinking": "숨은 생각"}])), "베가는 0등급")   # Claude (블록)
        self.assertEqual(reply_text(Msg(None)), "")

    def test_local_embedding_dimension_known_without_download(self):
        from vasthorizon.llm import _local_dim
        self.assertEqual(_local_dim("intfloat/multilingual-e5-large"), 1024)


class PromptLanguageTest(unittest.TestCase):
    def test_korean_only_rule_in_shared_roles(self):
        # Claude가 검색어를 일본어로("見かけの等級") 뽑거나 답에 한자("1950년代")를 섞던 문제 — 공통 역할 문장에 규칙
        from vasthorizon.data.domain import ANSWER_PERSONA, EXPERT_DESCRIPTION
        from vasthorizon.rag.prompts import ANSWER_SYSTEM, QUERY_SYSTEM
        self.assertIn("일본어", EXPERT_DESCRIPTION)
        self.assertIn("한자", ANSWER_PERSONA)
        self.assertIn("한자", ANSWER_SYSTEM)
        self.assertIn("일본어", QUERY_SYSTEM)


class RateLimiterTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.limiter = RateLimiter(LimitsConfig(enabled=True, per_ip_per_minute=2, per_ip_per_day=3, global_per_day=4),
                                   clock=lambda: self.now)

    def test_per_minute_then_recovers(self):
        self.assertTrue(self.limiter.check("a").allowed)
        self.assertTrue(self.limiter.check("a").allowed)
        v = self.limiter.check("a")
        self.assertEqual((v.allowed, v.reason), (False, "minute"))
        self.assertGreater(v.retry_after, 0)
        self.assertTrue(self.limiter.check("b").allowed)                # 다른 사용자는 따로
        self.now = 61
        self.assertTrue(self.limiter.check("a").allowed)

    def test_per_day_and_global(self):
        for t in (0, 61, 122):
            self.now = t
            self.assertTrue(self.limiter.check("a").allowed)
        self.now = 200
        self.assertEqual(self.limiter.check("a").reason, "day")
        self.assertTrue(self.limiter.check("b").allowed)                 # 전체 4번째
        self.assertEqual(self.limiter.check("c").reason, "global")
        self.now = 86400 + 1
        self.assertTrue(self.limiter.check("a").allowed)                 # 하루가 지나면 다시

def limited_app(limits=None, cors=(), trusted=None, peer=("203.0.113.50", 50000)):
    """가짜 AI 서비스 · 한도를 켠 앱. trusted가 있으면 Uvicorn의 신뢰 프록시 처리(배포와 같은 미들웨어)로 감싼다."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    from tests.test_api import ITEMS, FakeAsk, healthy
    from vasthorizon.api.app import create_app
    from vasthorizon.api.services import Services
    from vasthorizon.features.sky import SkyGuide
    calls = {"sky": 0}

    def fake_sky(view):
        calls["sky"] += 1
        return SkyGuide(view=view, guide="안내 [근거 1]", status="cited")

    ask = FakeAsk()
    s = dataclasses.replace(get_settings(), limits=limits or LimitsConfig(), server=ServerConfig(cors_origins=tuple(cors)))
    with mock.patch.object(config_module, "get_settings", return_value=s):
        app = create_app(Services(items=ITEMS, ask=ask, health=healthy, sky_guide=fake_sky), web_dir=None)
    if trusted is not None:
        app = ProxyHeadersMiddleware(app, trusted_hosts=trusted)
    return TestClient(app, raise_server_exceptions=False, client=peer), ask, calls


SKY = {"lat": 37.57, "lon": 126.98, "at": "2026-10-22T21:00:00"}


def ask_body():
    from tests.test_api import SESSION
    return {"session_id": SESSION, "item_id": "Q48469", "question": "태양계를 벗어났나?"}


class AiBudgetTest(unittest.TestCase):
    """[P2] 실제로 LLM을 부르는 요청만 AI 예산을 쓴다 — 하늘 계산(guide=false) · 조회 · 형식 오류는 세지 않는다."""

    def setUp(self):
        self.c, self.ask, self.calls = limited_app(LimitsConfig(enabled=True, per_ip_per_minute=2, per_ip_per_day=10, global_per_day=10))

    def test_sky_calculation_does_not_spend_budget(self):
        self.assertEqual([self.c.post("/api/sky", json={**SKY, "guide": False}).status_code for _ in range(5)], [200] * 5)
        self.assertEqual([self.c.post("/api/ask", json=ask_body()).status_code for _ in range(3)], [200, 200, 429])
        self.assertEqual((len(self.ask.calls), self.calls["sky"]), (2, 0))

    def test_after_budget_runs_out_sky_still_works_but_guide_does_not(self):
        for _ in range(2):
            self.c.post("/api/ask", json=ask_body())
        r = self.c.post("/api/sky", json={**SKY, "guide": False})
        self.assertEqual((r.status_code, r.json()["status"]), (200, "skipped"))
        g = self.c.post("/api/sky", json={**SKY, "guide": True})
        self.assertEqual((g.status_code, g.json()["code"]), (429, "rate_limited"))
        self.assertEqual(self.calls["sky"], 0)                           # 한도를 넘으면 LLM을 부르기 전에 막는다
        self.assertIn("Retry-After", g.headers)
        self.assertEqual(self.c.get("/api/items").status_code, 200)

    def test_guide_true_spends_budget(self):
        codes = [self.c.post("/api/sky", json={**SKY, "guide": True}).status_code for _ in range(3)]
        self.assertEqual((codes, self.calls["sky"]), ([200, 200, 429], 2))

    def test_invalid_requests_are_not_counted(self):
        self.assertEqual([self.c.post("/api/ask", json={"question": ""}).status_code for _ in range(4)], [422] * 4)
        self.assertEqual(self.c.post("/api/ask", json=ask_body()).status_code, 200)

    def test_no_limit_by_default(self):
        c, ask, _ = limited_app()
        self.assertTrue(all(c.post("/api/ask", json=ask_body()).status_code == 200 for _ in range(8)))

    def test_global_limit_across_users(self):
        codes = []
        limits = LimitsConfig(enabled=True, per_ip_per_minute=10, per_ip_per_day=10, global_per_day=3)
        base, _, _ = limited_app(limits, peer=("203.0.113.1", 1))
        for i in range(4):                                                # 같은 앱(한도 저장소)에 사용자 4명
            client = TestClient(base.app, raise_server_exceptions=False, client=(f"203.0.113.{i}", 1))
            codes.append(client.post("/api/ask", json=ask_body()).status_code)
        self.assertEqual(codes, [200, 200, 200, 429])


class ProxyTrustTest(unittest.TestCase):
    """[P1] 사용자 주소는 Uvicorn이 신뢰 프록시로 확정한 값만 — 사용자가 끼워 넣은 전달 헤더로 한도를 피할 수 없다."""
    LIMITS = LimitsConfig(enabled=True, per_ip_per_minute=2, per_ip_per_day=10, global_per_day=100)

    def codes(self, client, headers_list):
        return [client.post("/api/ask", json=ask_body(), headers=h).status_code for h in headers_list]

    def test_review_repro_spoofed_first_xff_through_trusted_proxy(self):
        # 리뷰 재현: 신뢰 프록시를 거치며 XFF 첫 값만 바꾼다 → 같은 사용자(오른쪽의 실제 주소)로 센다
        c, _, _ = limited_app(self.LIMITS, trusted="10.0.0.2", peer=("10.0.0.2", 443))
        headers = [{"X-Forwarded-For": f"198.51.100.{i}, 203.0.113.10", "CF-Connecting-IP": "203.0.113.10"} for i in range(4)]
        self.assertEqual(self.codes(c, headers), [200, 200, 429, 429])

    def test_real_users_behind_proxy_are_separate(self):
        c, _, _ = limited_app(self.LIMITS, trusted="10.0.0.2", peer=("10.0.0.2", 443))
        self.assertEqual(self.codes(c, [{"X-Forwarded-For": "203.0.113.10"}] * 2 + [{"X-Forwarded-For": "203.0.113.11"}] * 2),
                         [200, 200, 200, 200])

    def test_proxy_chain_takes_rightmost_untrusted(self):
        c, _, _ = limited_app(self.LIMITS, trusted="10.0.0.0/24", peer=("10.0.0.2", 443))
        headers = [{"X-Forwarded-For": f"198.51.100.{i}, 203.0.113.10, 10.0.0.5"} for i in range(3)]
        self.assertEqual(self.codes(c, headers), [200, 200, 429])

    def test_untrusted_peer_headers_ignored(self):
        # 신뢰하지 않는 접속자(원본에 바로 접속)의 XFF · CF-Connecting-IP는 무시 — 접속한 주소로 센다
        c, _, _ = limited_app(self.LIMITS, trusted="10.0.0.2", peer=("198.51.100.7", 1234))
        headers = [{"X-Forwarded-For": f"203.0.113.{i}", "CF-Connecting-IP": f"203.0.113.{i}"} for i in range(3)]
        self.assertEqual(self.codes(c, headers), [200, 200, 429])

    def test_no_trusted_proxy_by_default(self):
        # 배포 기본값 FORWARDED_ALLOW_IPS="" — 어떤 연결의 헤더도 믿지 않는다
        c, _, _ = limited_app(self.LIMITS, trusted="", peer=("10.0.0.2", 443))
        self.assertEqual(self.codes(c, [{"X-Forwarded-For": f"203.0.113.{i}"} for i in range(3)]), [200, 200, 429])

    def test_cf_header_alone_never_used(self):
        # 앱은 CF-Connecting-IP를 읽지 않는다 — 신뢰 프록시를 거쳐도 XFF(오른쪽부터)만 기준
        c, _, _ = limited_app(self.LIMITS, trusted="10.0.0.2", peer=("10.0.0.2", 443))
        headers = [{"X-Forwarded-For": "203.0.113.10", "CF-Connecting-IP": f"198.51.100.{i}"} for i in range(3)]
        self.assertEqual(self.codes(c, headers), [200, 200, 429])

    def test_deploy_image_trusts_no_proxy_by_default(self):
        text = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('FORWARDED_ALLOW_IPS=""', text)
        self.assertIn("--proxy-headers", text)
        self.assertIn('FORWARDED_ALLOW_IPS: ""', (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


class CorsTest(unittest.TestCase):
    def test_cors_only_for_listed_origin(self):
        c, _, _ = limited_app(cors=("https://vasthorizon.pages.dev",))
        ok = c.get("/api/items", headers={"Origin": "https://vasthorizon.pages.dev"})
        self.assertEqual(ok.headers.get("access-control-allow-origin"), "https://vasthorizon.pages.dev")
        other = c.get("/api/items", headers={"Origin": "https://evil.example"})
        self.assertIsNone(other.headers.get("access-control-allow-origin"))
        plain, _, _ = limited_app()
        self.assertIsNone(plain.get("/api/items", headers={"Origin": "https://x.dev"}).headers.get("access-control-allow-origin"))


class DeployInitTest(unittest.TestCase):
    """[P1] 임베딩 모델이 바뀌면 항목 · 서가 · 문서 색인을 모두 새 모델로 — 문서는 캐시에서, 실패하면 기존 색인 보존."""

    def setUp(self):
        import chromadb
        from tests.fakes import FakeEmbedding
        from tests.test_doc_index import LINKS, VOYAGER, WIKI
        from tests.test_perspective import StubLibraryCollector
        from vasthorizon.store.doc_index import sync_item_docs
        self.db = chromadb.EphemeralClient()
        self.s = get_settings()
        self.names = [self.s.collections.items, self.s.collections.perspective, self.s.collections.docs]
        self.cleanup()
        self.old = FakeEmbedding(model="old-model")
        self.lib = StubLibraryCollector
        self.wiki, self.links, self.voyager = WIKI, {"wiki:10350": LINKS["wiki:10350"]}, VOYAGER
        from scripts import deploy_init
        self.deploy_init = deploy_init
        with mock.patch("sys.stdout"):
            self.assertEqual(deploy_init.main([], embedding=self.old, db=self.db, perspective_collector=self.lib()), 0)
        docs = chroma.open_collection(self.s.collections.docs, self.old, self.db)
        sync_item_docs(VOYAGER, [WIKI], self.links, docs, self.old, 1000, 200)       # 이전 모델로 질문하며 모은 문서

    def tearDown(self):
        self.cleanup()

    def cleanup(self):
        for name in self.names:
            for suffix in ("", chroma.STAGING_SUFFIX, chroma.BACKUP_SUFFIX):
                chroma.drop_collection(name + suffix, self.db)

    def models(self):
        return {n: chroma.stored_identity(self.db.get_collection(n))["embedding_model"] for n in self.names}

    def doc_collector(self, missing=False):
        from vasthorizon.collect.collector import LinkedDocs
        wiki, links = self.wiki, self.links

        class Cache:
            def linked(self, item_id):
                return LinkedDocs(docs=[] if missing else [wiki], links=links, missing=["wiki:10350"] if missing else [])
        return Cache()

    def test_model_change_rebuilds_all_three(self):
        from tests.fakes import FakeEmbedding
        new = FakeEmbedding(model="new-model")
        self.assertEqual(set(self.deploy_init.stale_collections(self.names, new, self.db)), set(self.names))
        with mock.patch("sys.stdout"):
            code = self.deploy_init.main([], embedding=new, db=self.db, doc_collector=self.doc_collector(),
                                         perspective_collector=self.lib())
        self.assertEqual(code, 0)
        self.assertTrue(all(m.endswith("new-model") for m in self.models().values()), self.models())
        self.assertEqual(self.deploy_init.stale_collections(self.names, new, self.db), [])
        # 이미 질문했던 천체의 문서 청크가 새 모델로 다시 들어 있다 (문서를 다시 받지 않고 캐시에서)
        got = self.db.get_collection(self.s.collections.docs).get(include=["metadatas"])
        self.assertTrue(got["ids"])
        self.assertEqual({m["item_id"] for m in got["metadatas"]}, {self.voyager["id"]})
        # 새 모델로 이후 질문의 문서도 그대로 색인된다
        from vasthorizon.store.doc_index import sync_item_docs
        sync_item_docs({"id": "Q48470", "name": "보이저 2호"}, [self.wiki], self.links,
                       chroma.open_collection(self.s.collections.docs, new, self.db), new, 1000, 200)

    def test_failed_docs_rebuild_keeps_old_index_and_fails(self):
        from tests.fakes import FakeEmbedding
        new = FakeEmbedding(model="new-model")
        before = self.db.get_collection(self.s.collections.docs).count()
        with mock.patch("sys.stdout"):
            code = self.deploy_init.main([], embedding=new, db=self.db, doc_collector=self.doc_collector(missing=True),
                                         perspective_collector=self.lib())
        self.assertEqual(code, 1)                                         # 성공으로 끝내지 않는다 (서버를 띄우지 않음)
        self.assertTrue(self.models()[self.s.collections.docs].endswith("old-model"))   # 기존 활성 색인 보존
        self.assertEqual(self.db.get_collection(self.s.collections.docs).count(), before)

    def test_same_model_is_noop_and_empty_docs_is_fine(self):
        with mock.patch("sys.stdout"):
            self.assertEqual(self.deploy_init.main([], embedding=self.old, db=self.db, perspective_collector=self.lib()), 0)
        chroma.drop_collection(self.s.collections.docs, self.db)          # 최초 배포처럼 문서 색인 없음
        from tests.fakes import FakeEmbedding
        with mock.patch("sys.stdout"):
            self.assertEqual(self.deploy_init.main(["--rebuild"], embedding=FakeEmbedding(model="new-model"), db=self.db,
                                                   perspective_collector=self.lib()), 0)


class StaticBuildTest(unittest.TestCase):
    def test_build_sets_api_base(self):
        from scripts.build_static import build
        with tempfile.TemporaryDirectory() as d:
            out = build("https://api.vasthorizon.dev/", out=Path(d) / "dist")
            html = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn('<meta name="vh-api-base" content="https://api.vasthorizon.dev">', html)
            self.assertTrue((out / "js" / "api.js").exists())
            self.assertFalse(any(p.name.startswith("_") and p.suffix == ".html" for p in out.iterdir()))
        with self.assertRaises(ValueError):
            build('javascript:alert(1)"', out=Path(tempfile.gettempdir()) / "vh-dist-bad")

    def test_source_index_keeps_same_origin(self):
        html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<meta name="vh-api-base" content="">', html)        # 기본은 같은 서버


if __name__ == "__main__":
    unittest.main()
