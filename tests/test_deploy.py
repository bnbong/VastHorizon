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
from vasthorizon.api.limits import RateLimiter, client_ip
from vasthorizon.config import PROJECT_ROOT, LimitsConfig, ServerConfig, get_settings
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
        self.assertFalse(s.limits.trust_proxy)                      # 프록시가 없으면 헤더를 믿지 않는다
        self.assertIn("deploy", str(s.paths.chroma_dir))            # GMS 색인과 다른 폴더 (벡터를 섞지 않는다)
        self.assertNotEqual(s.paths.chroma_dir, get_settings().paths.chroma_dir)

    def test_env_overrides(self):
        with mock.patch.dict(os.environ, {"VH_CONFIG": "config.deploy.toml", "VH_CORS_ORIGINS": "https://a.pages.dev, https://b.dev",
                                          "VH_TRUST_PROXY": "1"}):
            get_settings.cache_clear()
            try:
                s = get_settings()
            finally:
                get_settings.cache_clear()
        self.assertEqual(s.server.cors_origins, ("https://a.pages.dev", "https://b.dev"))
        self.assertTrue(s.limits.trust_proxy)

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

    def test_client_ip(self):
        headers = {"x-forwarded-for": "1.2.3.4, 10.0.0.1"}
        self.assertEqual(client_ip(headers, "10.0.0.1", trust_proxy=False), "10.0.0.1")   # 헤더를 믿지 않는다
        self.assertEqual(client_ip(headers, "10.0.0.1", trust_proxy=True), "1.2.3.4")
        self.assertEqual(client_ip({"cf-connecting-ip": "5.6.7.8"}, "10.0.0.1", trust_proxy=True), "5.6.7.8")
        self.assertEqual(client_ip({}, None, trust_proxy=False), "unknown")


class DeployApiTest(unittest.TestCase):
    def app(self, **changes):
        from tests.test_api import ITEMS, FakeAsk, healthy
        from vasthorizon.api.app import create_app
        from vasthorizon.api.services import Services
        s = dataclasses.replace(get_settings(), **changes)
        with mock.patch.object(config_module, "get_settings", return_value=s):
            return TestClient(create_app(Services(items=ITEMS, ask=FakeAsk(), health=healthy), web_dir=None),
                              raise_server_exceptions=False)

    def test_rate_limit_on_llm_requests_only(self):
        c = self.app(limits=LimitsConfig(enabled=True, per_ip_per_minute=2, per_ip_per_day=10, global_per_day=10))
        from tests.test_api import SESSION
        body = {"session_id": SESSION, "item_id": "Q48469", "question": "태양계를 벗어났나?"}
        self.assertEqual([c.post("/api/ask", json=body).status_code for _ in range(3)], [200, 200, 429])
        r = c.post("/api/ask", json=body)
        self.assertEqual(r.json()["code"], "rate_limited")
        self.assertIn("Retry-After", r.headers)
        self.assertEqual(c.get("/api/items").status_code, 200)            # 조회(GET)는 세지 않는다

    def test_no_limit_by_default(self):
        c = self.app()
        from tests.test_api import SESSION
        body = {"session_id": SESSION, "item_id": "Q48469", "question": "태양계를 벗어났나?"}
        self.assertTrue(all(c.post("/api/ask", json=body).status_code == 200 for _ in range(8)))

    def test_cors_only_for_listed_origin(self):
        c = self.app(server=ServerConfig(cors_origins=("https://vasthorizon.pages.dev",)))
        ok = c.get("/api/items", headers={"Origin": "https://vasthorizon.pages.dev"})
        self.assertEqual(ok.headers.get("access-control-allow-origin"), "https://vasthorizon.pages.dev")
        other = c.get("/api/items", headers={"Origin": "https://evil.example"})
        self.assertIsNone(other.headers.get("access-control-allow-origin"))
        self.assertIsNone(self.app().get("/api/items", headers={"Origin": "https://x.dev"}).headers.get("access-control-allow-origin"))


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
