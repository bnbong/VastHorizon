"""카카오 JavaScript 키를 index.html meta에 넣는 경로 — 치환 함수 · 설정 · 서버의 index.html · 정적 빌드.

    python -m unittest tests.test_webmeta
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from vasthorizon import config as config_module
from vasthorizon.api.app import create_app
from vasthorizon.api.services import Services
from vasthorizon.config import PROJECT_ROOT, get_settings
from vasthorizon.webmeta import inject_kakao_key, valid_kakao_key

KEY = "0123456789abcdef0123456789abcdef"
EMPTY = '<meta name="vh-kakao-key" content="">'
HTML = f'<head>\r\n  <meta name="vh-api-base" content="">\r\n  {EMPTY}\r\n</head>\r\n'


class InjectTest(unittest.TestCase):
    def test_injects_key(self):
        out = inject_kakao_key(HTML, KEY)
        self.assertIn(f'<meta name="vh-kakao-key" content="{KEY}">', out)
        self.assertNotIn(EMPTY, out)
        self.assertEqual(out.replace(KEY, ""), HTML)               # 다른 줄 · 줄바꿈은 그대로

    def test_empty_key_keeps_original(self):
        for key in ("", None, "   "):
            self.assertEqual(inject_kakao_key(HTML, key), HTML)

    def test_unsafe_key_keeps_original(self):
        for key in ('abc" onload="x', "abc>", "a|b", "키", "a" * 65):
            self.assertFalse(valid_kakao_key(key), key)
            self.assertEqual(inject_kakao_key(HTML, key), HTML)

    def test_without_meta_keeps_original(self):
        html = "<head></head>"
        self.assertEqual(inject_kakao_key(html, KEY), html)

    def test_only_first_meta(self):
        out = inject_kakao_key(HTML + EMPTY, KEY)
        self.assertEqual(out.count(KEY), 1)

    def test_source_index_has_empty_meta(self):
        html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count(EMPTY), 1)                     # 저장소에는 키를 적지 않는다


class SettingsTest(unittest.TestCase):
    def tearDown(self):
        get_settings.cache_clear()

    def test_env_overrides_config(self):
        with mock.patch.dict(os.environ, {"KAKAO_JS_KEY": f" {KEY} "}):
            get_settings.cache_clear()
            self.assertEqual(get_settings().share.kakao_js_key, KEY)

    def test_default_empty(self):
        with mock.patch.dict(os.environ, {"KAKAO_JS_KEY": ""}), mock.patch.object(config_module, "load_dotenv"):
            get_settings.cache_clear()
            self.assertEqual(get_settings().share.kakao_js_key, "")


class ServeIndexTest(unittest.TestCase):
    def client(self, key: str, web: Path) -> TestClient:
        real = get_settings()
        settings = dataclasses.replace(real, share=dataclasses.replace(real.share, kakao_js_key=key))
        with mock.patch.object(config_module, "get_settings", return_value=settings):
            app = create_app(Services(items=[], ask=None, health=None), web_dir=web)
        return TestClient(app)

    def web(self) -> Path:
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        (d / "index.html").write_bytes(HTML.encode("utf-8"))
        (d / "app.js").write_text("// js", encoding="utf-8")
        return d

    def test_index_gets_key(self):
        client = self.client(KEY, self.web())
        for path in ("/", "/index.html"):
            res = client.get(path)
            self.assertEqual(res.status_code, 200, path)
            self.assertIn(f'<meta name="vh-kakao-key" content="{KEY}">', res.text)
            self.assertEqual(res.headers["cache-control"], "no-cache")
        self.assertEqual(client.head("/").headers["cache-control"], "no-cache")   # HEAD도 같은 경로 (StaticFiles의 원본 길이가 아니라)
        self.assertEqual(client.get("/app.js").text, "// js")    # 나머지는 StaticFiles 그대로

    def test_no_key_serves_original(self):
        client = self.client("", self.web())
        res = client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content, HTML.encode("utf-8"))

    def test_unsafe_key_serves_original(self):
        with self.assertLogs("vasthorizon.api.app", level="WARNING"):
            client = self.client('x"y', self.web())
        self.assertEqual(client.get("/").content, HTML.encode("utf-8"))


class StaticBuildKakaoTest(unittest.TestCase):
    def test_build_injects_key(self):
        from scripts.build_static import build
        with tempfile.TemporaryDirectory() as d:
            out = build("https://api.vasthorizon.dev", out=Path(d) / "dist", kakao_key=KEY)
            html = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn(f'<meta name="vh-kakao-key" content="{KEY}">', html)
            self.assertIn('<meta name="vh-api-base" content="https://api.vasthorizon.dev">', html)

    def test_build_without_key_keeps_meta_empty(self):
        from scripts.build_static import build
        with tempfile.TemporaryDirectory() as d:
            out = build("https://api.vasthorizon.dev", out=Path(d) / "dist")
            self.assertIn(EMPTY, (out / "index.html").read_text(encoding="utf-8"))

    def test_build_rejects_unsafe_key(self):
        from scripts.build_static import build
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            build("https://api.vasthorizon.dev", out=Path(d) / "dist", kakao_key='x"><script>')

    def test_main_reads_env(self):
        from scripts import build_static
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"VH_KAKAO_KEY": KEY}), mock.patch("sys.stdout"):
            self.assertEqual(build_static.main(["--api", "https://api.vasthorizon.dev", "--out", str(Path(d) / "dist")]), 0)
            self.assertIn(KEY, (Path(d) / "dist" / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
