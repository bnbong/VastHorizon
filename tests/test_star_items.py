"""별자리 선의 별 — 카탈로그 밖의 별을 그 별 자체로 물어보기 (임시 항목 hip:…). 외부 호출 없음.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_api import ITEMS, FakeAsk, healthy
from vasthorizon.api.app import create_app
from vasthorizon.api.services import ItemNotFoundError, Services
from vasthorizon.features.intro import item_intro
from vasthorizon.features.star_items import star_index, star_item
from vasthorizon.rag.retrieval import adhoc_evidence

FIGURES = {"Q8860": {"item_id": "Q8860", "name": "오리온자리", "lines": [[22449, 27989]], "stars": {
    "22449": {"hip": 22449, "name": "타비트", "item_id": None, "ra_deg": 72.46, "dec_deg": 6.96, "mag": 3.19,
              "distance_ly": 26.21, "distance_basis": "parallax", "wiki_title": "타비트"},
    "27989": {"hip": 27989, "name": "베텔게우스", "item_id": "Q12124", "ra_deg": 88.79, "dec_deg": 7.41, "mag": 0.45,
              "distance_ly": 548.0, "distance_basis": "wikidata", "wiki_title": "베텔게우스"},
    "1": {"hip": 1, "name": "π6 오리온자리", "item_id": None, "ra_deg": 1, "dec_deg": 1, "mag": 4.5,
          "distance_ly": 950.0, "distance_basis": "wikidata", "wiki_title": None}}}}
INDEX = star_index(FIGURES)


class StarItemTest(unittest.TestCase):
    def test_item_from_figure_data(self):
        it = star_item("hip:22449", INDEX, 2026)
        self.assertEqual((it["id"], it["name"], it["group"], it["wiki_title"], it["adhoc"]), ("hip:22449", "타비트", "star", "타비트", True))
        self.assertAlmostEqual(it["distance"]["ly"], 26.21)
        self.assertEqual(it["attrs"]["별자리"], "오리온자리")

    def test_unknown_or_malformed(self):
        for bad in ("hip:999", "Q1", "hip:abc", ""):
            self.assertIsNone(star_item(bad, INDEX, 2026), bad)

    def test_evidence_one_from_data(self):
        ev = adhoc_evidence(star_item("hip:22449", INDEX, 2026))
        self.assertEqual((ev.number, ev.chunk_id, ev.kind), (0, "hip:22449", "항목 메타데이터"))
        self.assertIn("오리온자리", ev.text)
        self.assertIn("26.2광년", ev.text)

    def test_no_wiki_doc_intro_without_fetch(self):
        r = item_intro(star_item("hip:1", INDEX, 2026), collector=object())     # 수집기를 쓰면 실패한다
        self.assertEqual(r["status"], "unavailable")
        self.assertIn("위키 문서가 없어", r["notice"])


class StarCacheTest(unittest.TestCase):
    def test_manifest_with_colon_id(self):
        # Windows 파일 이름에는 ':'를 쓸 수 없다 — hip:… 항목의 수집 기록이 저장 · 복원돼야 한다
        import tempfile
        from vasthorizon.collect.cache import CollectCache
        with tempfile.TemporaryDirectory() as tmp:
            cache = CollectCache(Path(tmp))
            m = cache.get_manifest("hip:22449")
            m["docs"]["wiki:1"] = {"role": "항목 문서", "title": "타비트"}
            cache.put_manifest(m)
            self.assertEqual(cache.get_manifest("hip:22449")["docs"], {"wiki:1": {"role": "항목 문서", "title": "타비트"}})
            self.assertEqual([f.name for f in (Path(tmp) / "items").iterdir()], ["hip_22449.json"])


class StarApiTest(unittest.TestCase):
    def client(self):
        self.asked = FakeAsk()
        services = Services(items=ITEMS, ask=self.asked, health=healthy, stars=lambda i: star_item(i, INDEX, 2026))
        return TestClient(create_app(services, web_dir=None), raise_server_exceptions=False)

    def test_detail_and_lookup(self):
        c = self.client()
        body = c.get("/api/items/hip:22449").json()
        self.assertEqual((body["name"], body["group_ko"]), ("타비트", "별"))
        self.assertEqual(c.get("/api/items/hip:999").status_code, 404)
        no_wiki = c.get("/api/items/hip:1")                                      # 위키 문서가 없는 별도 상세가 열린다
        self.assertEqual((no_wiki.status_code, no_wiki.json()["wiki_title"]), (200, None))
        with self.assertRaises(ItemNotFoundError):
            Services(items=ITEMS, ask=FakeAsk(), health=healthy).item("hip:22449")      # 별 조회 없으면 찾지 못함

    def test_ask_accepts_star_id(self):
        r = self.client().post("/api/ask", json={"session_id": "test-session-01", "item_id": "hip:22449", "question": "타비트는 어떤 별이야?"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["item_name"], "타비트")
        r = self.client().post("/api/ask", json={"session_id": "test-session-01", "item_id": "hip:x", "question": "q"})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
