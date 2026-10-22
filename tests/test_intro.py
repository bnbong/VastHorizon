"""천체 소개 테스트 — 위키 문서 발췌 (LLM 없음) · API. 가짜 수집기를 쓴다.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from tests.test_api import ITEMS, FakeAsk, healthy
from tests.test_features import StubCollector
from vasthorizon.api.app import create_app
from vasthorizon.api.services import Services
from vasthorizon.data.docs import Document
from vasthorizon.features.intro import clip_sentences, item_intro, split_sections

TEXT = ("베텔게우스는 오리온자리에서 두 번째로 밝은 별이다. 뚜렷하게 붉은색으로 빛난다.\n"
        "== 특징 ==\n적색 초거성이다.\n"
        "== 관측 역사 ==\n고대부터 기록되었다.\n=== 근대 ===\n존 허셜이 밝기 변화를 처음 기록했다.\n")


def doc(text=TEXT):
    return Document(doc_id="wiki:1", title="베텔게우스", url="https://ko.wikipedia.org/wiki/베텔게우스", permalink="p",
                    text=text, source_type="위키백과", license="CC BY-SA 4.0", fetched_at="2026-10-22T00:00:00+00:00")


class IntroTest(unittest.TestCase):
    def test_sections_lead_and_story(self):
        self.assertEqual([h for h, _ in split_sections(TEXT)], ["", "특징", "관측 역사"])
        r = item_intro({"wiki_title": "베텔게우스"}, StubCollector(doc()))
        self.assertEqual([s["heading"] for s in r["sections"]], ["소개", "관측 역사"])
        self.assertIn("존 허셜", r["sections"][1]["text"])                     # 하위 절은 위 절에 이어 붙인다
        self.assertEqual((r["status"], r["license"]), ("ok", "CC BY-SA 4.0"))

    def test_clip_by_sentence(self):
        text = "첫 문장이다. 둘째 문장이다. 셋째 문장이다."
        self.assertEqual(clip_sentences(text, 16), "첫 문장이다. 둘째 문장이다.")   # 16자 — 셋째 문장은 넘친다
        self.assertEqual(clip_sentences("아주긴문장" * 10, 5), "아주긴문장…")

    def test_no_story_section(self):
        r = item_intro({"wiki_title": "x"}, StubCollector(doc("첫머리만 있다.\n== 구조 ==\n본문.")))
        self.assertEqual([s["heading"] for s in r["sections"]], ["소개"])

    def test_unavailable(self):
        r = item_intro({"wiki_title": "x"}, StubCollector(None))
        self.assertEqual((r["status"], r["sections"]), ("unavailable", []))
        self.assertIn("기본 정보", r["notice"])


class IntroApiTest(unittest.TestCase):
    def test_endpoint(self):
        services = Services(items=ITEMS, ask=FakeAsk(), health=healthy,
                            intro=lambda it: item_intro(it, StubCollector(doc())))
        c = TestClient(create_app(services, web_dir=None), raise_server_exceptions=False)
        body = c.get("/api/items/Q48469/intro").json()
        self.assertEqual((body["status"], body["sections"][0]["heading"], body["source_type"]), ("ok", "소개", "위키백과"))
        self.assertEqual(c.get("/api/items/Q999/intro").status_code, 404)


if __name__ == "__main__":
    unittest.main()
