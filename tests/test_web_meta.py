"""공개 화면 메타데이터 — web/index.html의 제목 · 설명 · 공유 이미지 · manifest · canonical과 그 파일들.

표준 라이브러리(html.parser)로만 읽는다.
"""

from __future__ import annotations

import json
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

WEB = Path(__file__).resolve().parent.parent / "web"
SITE = "https://vasthorizon.bnbong.com/"


class HeadParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title, self.meta, self.links, self.ld = "", {}, {}, []
        self._in_title = self._in_ld = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "meta" and "content" in a:
            key = a.get("name") or a.get("property")
            if key:
                self.meta[key] = a["content"]
        elif tag == "link":
            for rel in a.get("rel", "").split():
                self.links.setdefault(rel, []).append(a)
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in_ld = True
            self.ld.append("")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_ld = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._in_ld:
            self.ld[-1] += data


def parse() -> HeadParser:
    p = HeadParser()
    p.feed((WEB / "index.html").read_text(encoding="utf-8"))
    return p


def local(href: str) -> Path:
    """사이트 안 주소(절대 URL이나 /로 시작하는 경로) → web/ 아래 파일."""
    path = urlparse(href).path if href.startswith("http") else href
    return WEB / path.lstrip("/")


class WebMetaTest(unittest.TestCase):
    def setUp(self):
        self.head = parse()

    def test_title_and_description(self):
        self.assertIn("VastHorizon", self.head.title)
        desc = self.head.meta.get("description", "")
        self.assertTrue(0 < len(desc) <= 150, desc)

    def test_canonical(self):
        self.assertEqual([l["href"] for l in self.head.links.get("canonical", [])], [SITE])
        self.assertEqual(self.head.meta.get("og:url"), SITE)

    def test_og_image_is_absolute_and_exists(self):
        for key in ("og:image", "twitter:image"):
            url = self.head.meta.get(key, "")
            self.assertTrue(url.startswith(SITE), f"{key}={url!r}는 절대 URL이어야 한다")
            self.assertTrue(local(url).is_file(), url)
        self.assertEqual(self.head.meta.get("twitter:card"), "summary_large_image")
        self.assertLess(local(self.head.meta["og:image"]).stat().st_size, 300 * 1024)

    def test_manifest_and_icons(self):
        manifests = self.head.links.get("manifest", [])
        self.assertEqual(len(manifests), 1)
        path = local(manifests[0]["href"])
        self.assertEqual(path.suffix, ".json")      # Nginx 기본 mime.types에 .webmanifest가 없을 수 있다
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((manifest["name"], manifest["start_url"]), ("VastHorizon", "/"))
        for icon in manifest["icons"]:
            self.assertTrue(local(icon["src"]).is_file(), icon["src"])
        for link in self.head.links["icon"] + self.head.links["apple-touch-icon"]:
            self.assertTrue(local(link["href"]).is_file(), link["href"])

    def test_json_ld(self):
        self.assertEqual(len(self.head.ld), 1)
        data = json.loads(self.head.ld[0])
        self.assertEqual((data["@type"], data["url"]), ("WebApplication", SITE))

    def test_robots_and_sitemap(self):
        robots = (WEB / "robots.txt").read_text(encoding="utf-8")
        self.assertIn(f"Sitemap: {SITE}sitemap.xml", robots)
        self.assertIn("Disallow: /api/", robots)
        self.assertIn(f"<loc>{SITE}</loc>", (WEB / "sitemap.xml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
