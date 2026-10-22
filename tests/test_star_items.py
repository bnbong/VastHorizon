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
from vasthorizon.features.star_items import StarLookup, StarLookupError, star_facts, star_index, star_item
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


# ── 아무 별 — 히파르코스 번호로 Wikidata 조회 (12번) ─────────────────────

POSITIONS = {71683: (219.9, -60.83, -0.01, 0.71), 5: (0.004, -19.5, 9.27, 0.9), 22449: (72.46, 6.96, 3.19, 0.45)}
ALPHA_CEN = [
    {"item": "http://www.wikidata.org/entity/Q2090157", "en": "Alpha Centauri A", "ko": "센타우루스자리 알파 A",
     "distM": "41300000000000000", "plx": "747.1"},
    {"item": "http://www.wikidata.org/entity/Q2090157", "en": "Alpha Centauri A", "ko": "센타우루스자리 알파 A",
     "distM": "41340000000000000", "plx": "747.1"},
]


class StarLookupTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.calls = []
        self.rows = {71683: ALPHA_CEN, 5: [{"item": "http://www.wikidata.org/entity/Q1", "en": "HD 224700"}]}

    def tearDown(self):
        self.tmp.cleanup()

    def lookup(self, fetch=None):
        def fake(query):
            self.calls.append(query)
            hip = int(query.split('"HIP ')[1].split('"')[0])
            return self.rows.get(hip, [])
        return StarLookup(INDEX, POSITIONS, Path(self.tmp.name), fetch or fake, 2026)

    def test_figure_star_without_fetch(self):
        self.assertEqual(self.lookup()("hip:22449")["name"], "타비트")
        self.assertEqual(self.calls, [])                  # 별자리 선의 별은 외부 호출 없음

    def test_wikidata_star_item_and_cache(self):
        look = self.lookup()
        it = look("hip:71683")
        self.assertEqual((it["id"], it["name"], it["name_en"], it["adhoc"]), ("hip:71683", "센타우루스자리 알파 A", "Alpha Centauri A", True))
        self.assertAlmostEqual(it["distance"]["ly"], 4.37, places=1)
        self.assertEqual((it["ra_deg"], it["dec_deg"]), (219.9, -60.83))
        self.assertEqual(it["attrs"]["겉보기 등급"], -0.01)
        self.assertIn("Q2090157", it["sources"][0]["url"])
        look("hip:71683")
        self.assertEqual(len(self.calls), 1)               # 두 번째는 캐시
        self.assertIn("센타우루스자리 알파 A", adhoc_evidence(it).text)

    def test_no_distance_or_unknown_star_is_none(self):
        look = self.lookup()
        self.assertIsNone(look("hip:5"))                   # Wikidata에 거리 없음 — 지어내지 않는다
        self.assertIsNone(look("hip:424242"))              # 하늘 데이터에 없는 번호 — 조회도 하지 않는다
        self.assertEqual(len(self.calls), 1)
        self.assertIsNone(look("Q1"))

    def test_failure_raises_and_is_not_cached(self):
        def broken(query):
            raise ConnectionError("down")
        with self.assertRaises(StarLookupError):
            self.lookup(broken)("hip:71683")
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
        self.assertEqual(self.lookup()("hip:71683")["name"], "센타우루스자리 알파 A")   # 장애가 풀리면 다시 조회

    def test_star_facts_cross_checks_parallax(self):
        # 단위가 틀린 값(1000배)은 연주시차와 맞지 않아 빠진다 (common.distance_with_parallax)
        rows = [{"item": "x/Q9", "distM": str(int(4.37 * 9.4607e15))},
                {"item": "x/Q9", "distM": str(int(4370 * 9.4607e15)), "plx": "747.1"}]
        self.assertAlmostEqual(star_facts(rows)["distance"]["ly"], 4.37, places=1)
        self.assertIsNone(star_facts([{"item": "x/Q9", "en": "Nameless"}])["distance"])

    # ── 12-1 리뷰 P1: 엔티티별로 나누기 ──

    def test_entities_are_not_mixed(self):
        rows = [{"item": "x/Q1", "en": "Alpha", "distM": str(int(10 * 9.4607e15))},
                {"item": "x/Q2", "en": "Beta", "distM": str(int(100 * 9.4607e15))}]
        facts = star_facts(rows)
        self.assertEqual((facts["distance"], facts["qid"], facts["name_en"]), (None, None, None))   # 모호함 — 55광년을 만들지 않는다
        self.assertEqual(facts["ambiguous"], ["Q1", "Q2"])
        self.assertEqual(star_facts(list(reversed(rows))), facts)                                  # 행 순서와 무관

    def test_only_entity_with_distance_is_chosen_whole(self):
        rows = [{"item": "x/Q7", "en": "System", "title": "계"},
                {"item": "x/Q3", "en": "Star B", "ko": "별 B", "distM": str(int(20 * 9.4607e15))}]
        for order in (rows, list(reversed(rows))):
            f = star_facts(order)
            self.assertEqual((f["qid"], f["name_en"], f["name_ko"], f["wiki_title"]), ("Q3", "Star B", "별 B", None))
            self.assertAlmostEqual(f["distance"]["ly"], 20, places=3)

    def test_repeated_join_rows_do_not_weight_the_median(self):
        ly = lambda v: str(int(v * 9.4607e15))
        rows = [{"item": "x/Q8", "distM": ly(10), "en": f"name {i}"} for i in range(5)]      # 같은 거리 값이 5행에 반복
        rows += [{"item": "x/Q8", "distM": ly(11)}, {"item": "x/Q8", "distM": ly(12)}]
        self.assertAlmostEqual(star_facts(rows)["distance"]["ly"], 11, places=3)              # 서로 다른 값 {10, 11, 12}의 중앙값
        self.assertEqual(star_facts(rows)["name_en"], "name 0")                              # 이름도 정렬해 고른다

    def test_ambiguous_star_is_not_collectable_and_old_cache_is_refetched(self):
        self.rows[71683] = [{"item": "x/Q1", "en": "Alpha", "distM": "1"}, {"item": "x/Q2", "en": "Beta", "distM": "2"}]
        self.assertIsNone(self.lookup()("hip:71683"))
        # 이전 형식(버전 없음)의 캐시 — 다시 조회해 덮어쓴다
        import json
        old = Path(self.tmp.name) / "hip_5.json"
        old.write_text(json.dumps({"qid": "Q1", "name_en": "Mixed", "distance": {"km": 1e14, "ly": 10.6, "basis": "wikidata"}}), encoding="utf-8")
        self.rows[5] = ALPHA_CEN
        it = self.lookup()("hip:5")
        self.assertEqual(it["name"], "센타우루스자리 알파 A")
        self.assertEqual(json.loads(old.read_text(encoding="utf-8"))["version"], 2)

    def test_api_lookup_failure_is_503(self):
        def broken(query):
            raise TimeoutError()
        services = Services(items=ITEMS, ask=FakeAsk(), health=healthy, stars=self.lookup(broken))
        r = TestClient(create_app(services, web_dir=None), raise_server_exceptions=False).get("/api/items/hip:71683")
        self.assertEqual((r.status_code, r.json()["code"]), (503, "star_lookup_failed"))
        self.assertNotIn("TimeoutError", r.text)


if __name__ == "__main__":
    unittest.main()
