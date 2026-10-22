"""서비스 기능 테스트 — 조건 기반 탐색(F2011) · 빛의 편지(F2010).

가짜 임베딩 · 가짜 LLM · 메모리 전용 Chroma를 쓴다. 외부 호출 · 토큰 사용 없음.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

import chromadb
from fastapi.testclient import TestClient

from tests.fakes import FakeChat, FakeEmbedding
from tests.test_api import ITEMS as API_ITEMS, FakeAsk, healthy
from vasthorizon.api.app import create_app
from vasthorizon.api.services import Services
from vasthorizon.config import get_settings
from vasthorizon.data.docs import Document
from vasthorizon.data.item_text import item_category
from vasthorizon.data.items.common import LY_KM, REF_SURFACE_ALTITUDE
from vasthorizon.features.explore import Filters, explore, parse_filters
from vasthorizon.features.light_letter import (
    Departure, LetterResult, LetterUnavailableError, compute_departure, star_for_age, write_letter,
)
from vasthorizon.rag.graph import REJECTED_ANSWER
from vasthorizon.rag.llm_json import JsonReplyError
from vasthorizon.rag.retrieval import IndexMissingError
from vasthorizon.store import chroma
from vasthorizon.store.item_index import index_drift, sync_items

ITEMS_NAME = get_settings().collections.items
REF_YEAR = 2026


def dist(ly: float, **kw) -> dict:
    data = {"km": ly * LY_KM, "ly": ly, "basis": "wikidata", "reference": "지구에서 천체까지",
            "approximate": False, "method": None, "km_min": None, "km_max": None, "n_values": 1}
    data.update(kw)
    return data


def item(qid, name, group, kind, ly=None, **attrs) -> dict:
    return {"id": qid, "group": group, "name": name, "wiki_title": name, "name_en": None, "kind": kind,
            "distance": dist(ly) if ly else None, "ra_deg": None, "dec_deg": None, "attrs": attrs,
            "sources": [{"name": "Wikidata", "url": f"https://www.wikidata.org/wiki/{qid}"}]}


CATALOG = [
    item("Q2469", "안드로메다 은하", "messier", "나선 은하", 2_540_000, **{"맨눈 관측": True, "분류": "나선 은하"}),
    item("Q13423", "플레이아데스 성단", "messier", "산개 성단", 439, **{"맨눈 관측": True, "분류": "산개 성단"}),
    item("Q4", "희미한 은하", "messier", "적외선원", 20_000_000, **{"맨눈 관측": False, "분류": "적외선원, 타원 은하"}),
    item("Q3409", "시리우스", "star", "항성", 8.6, **{"맨눈 관측": True}),
    item("Q12124", "베텔게우스", "star", "항성", 548, **{"맨눈 관측": True}),
    item("Q8860", "오리온자리", "constellation", "별자리", **{"관측 계절": "겨울"}),
]


class ExploreTestBase(unittest.TestCase):
    def setUp(self):
        self.db = chromadb.EphemeralClient()
        self.emb = FakeEmbedding()
        sync_items(CATALOG, chroma.open_collection(ITEMS_NAME, self.emb, self.db), self.emb, REF_YEAR)

    def tearDown(self):
        chroma.drop_collection(ITEMS_NAME, self.db)

    def explore(self, *replies, query="맨눈으로 볼 수 있는 은하"):
        llm = FakeChat(*[r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in replies])
        return explore(query, llm=llm, embedding=self.emb, db=self.db), llm


# ── 범주 · 필터 ───────────────────────────────────────────────────────────

class CategoryAndFilterTest(unittest.TestCase):
    def test_item_category(self):
        cases = [
            (item("Q1", "어떤 은하", "messier", "LINER", **{"분류": "LINER, 나선 은하"}), "은하"),
            (item("Q1", "게 성운", "messier", "초신성잔해"), "성운"),
            (item("Q1", "보데 은하", "messier", "적외선원", **{"분류": "적외선원, 전파원"}), "은하"),     # 이름으로
            (item("Q1", "메시에 40", "messier", "이중성"), "기타"),
            (item("Q1", "국제우주정거장", "human_made", "우주선", **{"현재 위치": "지구 궤도"}), "우주정거장"),
            (item("Q1", "보이저 1호", "human_made", "우주선", **{"현재 위치": "태양계 탈출 궤도"}), "탐사선"),
            (item("Q1", "아리랑 1호", "human_made", "우주선", **{"현재 위치": "지구 궤도"}), "인공위성"),
            (item("Q1", "다누리", "human_made", "궤도선"), "탐사선"),
            (item("Q1", "태양", "solar_system", "항성"), "별"),
            (item("Q1", "핼리 혜성", "solar_system", "혜성"), "소천체"),
        ]
        for it, expected in cases:
            self.assertEqual(item_category(it), expected, it["name"])

    def test_where_clause(self):
        f = Filters(semantic_query="q", categories=["은하"], naked_eye=True, departure_year_min=1392,
                    departure_year_max=1896)
        self.assertEqual(f.where(), {"$and": [{"category": {"$in": ["은하"]}}, {"naked_eye": {"$eq": True}},
                                              {"light_departure_year": {"$gte": 1392}},
                                              {"light_departure_year": {"$lte": 1896}}]})
        self.assertIsNone(Filters(semantic_query="q").where())
        self.assertIn("빛이 출발한 해: 1392년 ~ 1896년", f.describe())

    def test_parse_filters_rejects_bad_values(self):
        for bad in ({"group": "planet"}, {"season": "장마"}, {"naked_eye": "yes"}, {"categories": "은하"},
                    {"categories": ["블랙홀"]}, {"distance_ly_min": 10, "distance_ly_max": 1},
                    {"departure_year_min": True}):
            with self.assertRaises(JsonReplyError, msg=bad):
                parse_filters(bad, "q")
        ok = parse_filters({"semantic_query": "은하", "categories": ["은하"], "naked_eye": True}, "q")
        self.assertEqual((ok.categories, ok.naked_eye), (["은하"], True))


# ── F2011 조건 기반 탐색 ───────────────────────────────────────────────────

class ExploreTest(ExploreTestBase):
    def test_category_filter_excludes_wrong_kinds(self):
        """'맨눈 은하' — 성단 · 맨눈으로 안 보이는 은하는 검색 단계에서 이미 빠진다."""
        result, llm = self.explore({"semantic_query": "맨눈 은하", "categories": ["은하"], "naked_eye": True},
                                   {"selected": [{"id": "Q2469", "reason": "나선 은하, 맨눈 관측: 예"}]})
        candidates = json.loads(llm.received[1][-1].content.split("후보:\n", 1)[1])
        self.assertEqual([c["id"] for c in candidates], ["Q2469"])
        self.assertEqual(([c.name for c in result.cards], result.status), (["안드로메다 은하"], "ok"))
        self.assertIn("종류: 은하", result.applied)

    def test_departure_year_filter(self):
        result, llm = self.explore({"semantic_query": "조선 시대 빛", "departure_year_min": 1392, "departure_year_max": 1896},
                                   {"selected": [{"id": "Q13423", "reason": "1587년 무렵 출발"}]},
                                   query="빛이 조선 시대에 출발한 천체")
        candidates = json.loads(llm.received[1][-1].content.split("후보:\n", 1)[1])
        self.assertEqual({c["id"] for c in candidates}, {"Q13423", "Q12124"})          # 1587년 · 1478년

    def test_no_candidates_is_no_match_without_selection_call(self):
        result, llm = self.explore({"semantic_query": "조선 성운", "categories": ["성운"]})
        self.assertEqual((result.status, result.cards, len(llm.received)), ("no_match", [], 1))

    def test_ids_outside_candidates_dropped(self):
        result, _ = self.explore({"semantic_query": "은하", "categories": ["은하"]},
                                 {"selected": [{"id": "Q999", "reason": "지어냄"}, {"id": "Q2469", "reason": "은하"},
                                               {"id": "Q2469", "reason": "중복"}]})
        self.assertEqual([c.item_id for c in result.cards], ["Q2469"])

    def test_filter_failure_falls_back_to_semantic_with_warning(self):
        result, _ = self.explore("필터 아님", {"selected": [{"id": "Q3409", "reason": "맨눈"}]})
        self.assertEqual(result.applied, [])
        self.assertIn("의미 검색만", result.warnings[0])
        self.assertEqual(result.status, "ok")

    def test_selection_failure_returns_no_cards(self):
        for bad in ("선별 결과 없음", {"selected": "Q2469"}, {"selected": [{"id": 1}]}):
            with self.subTest(bad=bad):
                result, _ = self.explore({"semantic_query": "은하", "categories": ["은하"]}, bad)
                self.assertEqual((result.status, result.cards), ("failed", []))


# ── F2010 빛의 편지 ────────────────────────────────────────────────────────

class StubCollector:
    def __init__(self, doc: Document | None):
        self.doc, self.titles = doc, []

    def fetch_wiki(self, title, failures):
        self.titles.append(title)
        return self.doc


def year_doc(title="1587년") -> Document:
    return Document(doc_id="wiki:1587", title=title, url=f"https://ko.wikipedia.org/wiki/{title}",
                    permalink="p", text="== 사건 ==\n2월 26일 - 정해왜변", source_type="위키백과",
                    license="CC BY-SA 4.0", fetched_at="2026-10-21T00:00:00+00:00")


class DepartureTest(unittest.TestCase):
    def test_year_and_range(self):
        pleiades = item("Q13423", "플레이아데스 성단", "messier", "산개 성단")
        pleiades["distance"] = dist(439, km_min=424 * LY_KM, km_max=444 * LY_KM, n_values=3)
        d = compute_departure(pleiades, REF_YEAR)
        self.assertEqual((d.year, d.year_label, d.era, d.year_range), (1587, "1587년", "조선 시대", (1582, 1602)))
        self.assertIn("1582년 ~ 1602년", d.summary())

    def test_near_and_far_have_no_year(self):
        mars = item("Q111", "화성", "solar_system", "행성")
        mars["distance"] = dist(0, km=2.27e8)
        mars["distance"]["km"] = 2.27e8
        self.assertIsNone(compute_departure(mars, REF_YEAR).year)
        andromeda = compute_departure(CATALOG[0], REF_YEAR)
        self.assertIsNone(andromeda.year)
        self.assertIn("인류 문명 이전", andromeda.summary())

    def test_unavailable(self):
        with self.assertRaises(LetterUnavailableError):
            compute_departure(item("Q8860", "오리온자리", "constellation", "별자리"), REF_YEAR)
        sat = item("Q1", "아리랑 1호", "human_made", "인공위성")
        sat["distance"] = dist(0, reference=REF_SURFACE_ALTITUDE)
        sat["distance"]["km"] = 639
        with self.assertRaises(LetterUnavailableError):
            compute_departure(sat, REF_YEAR)

    def test_star_for_age(self):
        star, gap = star_for_age(CATALOG, 9)
        self.assertEqual((star["name"], round(gap, 1)), ("시리우스", 0.4))
        for bad in (0, 121):
            with self.assertRaises(LetterUnavailableError):
                star_for_age(CATALOG, bad)


class LetterTest(ExploreTestBase):
    """setUp이 CATALOG(플레이아데스 439광년, 기준 연도 2026)로 항목 색인을 만들어 둔다."""

    def letter(self, collector, *replies, target=None, ref_year=REF_YEAR):
        llm = FakeChat(*replies)
        result = write_letter(target or CATALOG[1], ref_year, llm=llm, collector=collector)
        return result, llm

    def test_letter_cites_item_and_year_doc(self):
        collector = StubCollector(year_doc())
        result, _ = self.letter(collector, "지금 당신에게 닿은 이 빛이 출발했을 때 1587년 무렵이었어요 [근거 1]. 정해왜변이 있었어요 [근거 2].")
        self.assertEqual(collector.titles, ["1587년"])
        self.assertEqual([e.title for e in result.evidences], ["플레이아데스 성단", "1587년"])
        self.assertEqual((result.status, [e.number for e in result.cited]), ("cited", [1, 2]))
        self.assertIn("1587년 무렵", result.evidences[0].text)

    # ── [P1] 계산값과 근거가 같은 데이터에서 나온다 ─────────────────────────

    def test_catalog_changed_but_index_stale(self):
        """색인에는 439광년이 남아 있어도, 편지는 카탈로그(500광년)로 계산과 근거를 함께 만든다."""
        changed = {**CATALOG[1], "distance": dist(500)}
        collector = StubCollector(year_doc("1526년"))
        result, llm = self.letter(collector, "1526년 무렵 출발했어요 [근거 1].", target=changed)
        evidence = result.evidences[0].text
        self.assertEqual((result.departure.year, collector.titles), (1526, ["1526년"]))
        self.assertIn("약 500광년", evidence)
        self.assertIn("1526년 무렵", evidence)
        self.assertNotIn("439", evidence)
        self.assertNotIn("439", llm.received[0][-1].content)                  # 오래된 색인 텍스트가 프롬프트에 없다

    def test_distance_range_changed(self):
        changed = {**CATALOG[1], "distance": dist(439, km_min=400 * LY_KM, km_max=480 * LY_KM, n_values=4)}
        result, llm = self.letter(StubCollector(year_doc()), "1587년 무렵 [근거 1].", target=changed)
        self.assertEqual(result.departure.year_range, (1546, 1626))
        self.assertIn("범위 400~480광년", result.evidences[0].text)
        self.assertIn("1546년 ~ 1626년", llm.received[0][-1].content)

    def test_reference_year_differs_from_index(self):
        collector = StubCollector(year_doc("1591년"))
        result, _ = self.letter(collector, "1591년 무렵 [근거 1].", ref_year=2030)
        self.assertEqual((result.departure.year, collector.titles), (1591, ["1591년"]))
        self.assertIn("1591년 무렵", result.evidences[0].text)
        self.assertNotIn("1587년", result.evidences[0].text)

    def test_index_drift_detects_catalog_changes(self):
        same = index_drift(CATALOG, REF_YEAR, ITEMS_NAME, self.db)
        self.assertTrue(same.consistent)
        changed = [{**CATALOG[1], "distance": dist(500)}] + CATALOG[2:] + [item("Q9", "새 항목", "star", "항성", 10)]
        drift = index_drift(changed, REF_YEAR, ITEMS_NAME, self.db)
        self.assertEqual((drift.stale, drift.missing, drift.extra), (["Q13423"], ["Q9"], ["Q2469"]))
        other_year = index_drift(CATALOG, 2030, ITEMS_NAME, self.db)        # 기준 연도가 다르면 출발 연도 문구가 바뀐다
        self.assertIn("Q13423", other_year.stale)

    def test_health_reports_outdated_index(self):
        from vasthorizon.api import services as svc_module
        from vasthorizon.store.item_index import IndexDrift
        with mock.patch("vasthorizon.config.get_gms_key", return_value="k"), \
                mock.patch("vasthorizon.store.chroma.collection_count", return_value=6), \
                mock.patch("vasthorizon.store.item_index.index_drift", return_value=IndexDrift(stale=["Q13423"])):
            health = svc_module.check_health(CATALOG, REF_YEAR)
        self.assertEqual([n.code for n in health.notices], ["index_outdated"])
        self.assertIn("변경 1", health.notices[0].message)

    def test_missing_year_doc_still_writes_with_warning(self):
        result, _ = self.letter(StubCollector(None), "1587년 무렵 출발한 빛이에요 [근거 1].")
        self.assertEqual(len(result.evidences), 1)
        self.assertIn("1587년", result.warnings[0])

    def test_invented_citations_rejected(self):
        result, _ = self.letter(StubCollector(year_doc()), "임진왜란이 있었어요 [근거 7].", "또 지어낸 사건.")
        self.assertEqual((result.status, result.letter, result.cited), ("rejected", REJECTED_ANSWER, []))


# ── [P2] 색인 준비 상태와 조건 불일치를 구분한다 ─────────────────────────────

class ExploreReadinessTest(unittest.TestCase):
    def setUp(self):
        self.db = chromadb.EphemeralClient()
        self.emb = FakeEmbedding()

    def tearDown(self):
        chroma.drop_collection(ITEMS_NAME, self.db)

    def test_missing_index_is_readiness_error_without_llm(self):
        llm = FakeChat()                                                     # 호출되면 실패한다
        with self.assertRaises(IndexMissingError):
            explore("맨눈 은하", llm=llm, embedding=self.emb, db=self.db)
        self.assertEqual(llm.received, [])

    def test_empty_index_is_readiness_error(self):
        chroma.open_collection(ITEMS_NAME, self.emb, self.db)              # 컬렉션은 있지만 비어 있음
        with self.assertRaises(IndexMissingError):
            explore("맨눈 은하", llm=FakeChat(), embedding=self.emb, db=self.db)


class ExploreNoMatchTest(ExploreTestBase):
    def test_candidates_but_none_selected_is_no_match(self):
        result, _ = self.explore({"semantic_query": "은하", "categories": ["은하"]}, {"selected": []})
        self.assertEqual((result.status, result.cards), ("no_match", []))
        self.assertGreater(result.candidates, 0)


# ── API ───────────────────────────────────────────────────────────────────

class FeatureApiTest(unittest.TestCase):
    def client(self):
        from vasthorizon.features.explore import ExploreCard, ExploreResult

        def fake_explore(query):
            return ExploreResult(query=query, applied=["종류: 은하"], candidates=3, status="ok",
                                 cards=[ExploreCard("Q48469", "보이저 1호", "human_made", "우주 탐사선", "이유")])

        def fake_letter(it):
            return LetterResult(item=it, departure=Departure(light_years=0.0027, light_time="약 24시간"),
                                letter="편지 [근거 1]", status="cited", cited=[], evidences=[])

        stars = API_ITEMS + [item("Q3409", "시리우스", "star", "항성", 8.6)]
        services = Services(items=stars, ask=FakeAsk(), health=healthy, explore=fake_explore, letter=fake_letter)
        return TestClient(create_app(services, web_dir=None), raise_server_exceptions=False)

    def test_explore_endpoint(self):
        body = self.client().post("/api/explore", json={"query": "은하"}).json()
        self.assertEqual((body["status"], body["cards"][0]["item_id"], body["applied"]), ("ok", "Q48469", ["종류: 은하"]))

    def test_explore_without_index_is_503(self):
        c = self.client()
        c.app.state.services.explore = mock.Mock(side_effect=IndexMissingError("항목 색인이 없어 조건 탐색을 할 수 없습니다."))
        r = c.post("/api/explore", json={"query": "은하"})
        self.assertEqual((r.status_code, r.json()["code"]), (503, "index_missing"))
        self.assertNotIn("조건을 조금 넓혀", r.text)

    def test_letter_by_item_and_age(self):
        c = self.client()
        by_item = c.post("/api/light-letter", json={"item_id": "Q48469"}).json()
        self.assertEqual((by_item["item_name"], by_item["notice"]), ("보이저 1호", "답변에 인용된 근거가 없습니다."))
        by_age = c.post("/api/light-letter", json={"age": 9}).json()
        self.assertEqual((by_age["item_name"], by_age["matched_age"], by_age["age_gap_ly"]), ("시리우스", 9, 0.4))

    def test_letter_request_validation(self):
        c = self.client()
        for payload in ({}, {"item_id": "Q48469", "age": 9}):
            r = c.post("/api/light-letter", json=payload)
            self.assertEqual((r.status_code, r.json()["code"]), (422, "letter_unavailable"))
        self.assertEqual(c.post("/api/light-letter", json={"age": 200}).json()["code"], "invalid_request")
        self.assertEqual(c.post("/api/light-letter", json={"item_id": "Q404"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
