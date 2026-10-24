"""서비스 기능 테스트 — 조건 기반 탐색 · 빛의 편지.

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
from vasthorizon.data.enrich import enrich_items
from vasthorizon.data.item_text import item_category
from vasthorizon.data.items.common import LY_KM, REF_SURFACE_ALTITUDE
from vasthorizon.features.explore import Filters, explore, parse_filters, rank_rows
from vasthorizon.features.explore_rules import parse_rules
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

    def explore(self, *replies, query="맨눈으로 볼 수 있는 은하", rules=False):
        """LLM 경로(필터 추출 → 검색 → 선별) 시험 — 기본은 규칙 해석을 끈다 (규칙 경로는 ExploreRulePathTest)."""
        llm = FakeChat(*[r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in replies])
        return explore(query, llm=llm, embedding=self.emb, db=self.db, rules=rules), llm


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


# ── 조건 기반 탐색 ───────────────────────────────────────────────────

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


# ── 빛의 편지 ────────────────────────────────────────────────────────

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


class ExploreFactQuestionTest(ExploreTestBase):
    """조건 탐색에 특정 천체의 사실 질문이 들어온 경우 — '찾지 못함' 대신 그 천체에게 묻게 한다."""

    def run_explore(self, query, *replies):
        llm = FakeChat(*[json.dumps(r, ensure_ascii=False) for r in replies])
        return explore(query, llm=llm, embedding=self.emb, db=self.db, items=CATALOG), llm

    def test_names_in_query_found_by_code(self):
        from vasthorizon.features.explore import mentioned_items
        cases = {
            "안드로메다 은하 가운데에 있는 블랙홀 이름은 뭐야?": ["안드로메다 은하"],
            "안드로메다은하보다 가까운 은하": ["안드로메다 은하"],            # 붙여 써도
            "베텔게우스와 시리우스 중 더 먼 별은?": ["베텔게우스", "시리우스"],   # 질문에 나온 순서
            "오리온자리의 가장 밝은 별": ["오리온자리"],
            "맨눈으로 볼 수 있는 은하": [],
            "시리우스터미널": [],                                            # 낱말 일부에는 걸리지 않는다
        }
        for query, names in cases.items():
            self.assertEqual([m["name"] for m in mentioned_items(query, CATALOG)], names, query)

    def test_fact_question_returns_ask_without_search(self):
        result, llm = self.run_explore("안드로메다 은하 가운데에 있는 블랙홀 이름은 뭐야?",
                                       {"semantic_query": "블랙홀", "asks_fact": True})
        self.assertEqual((result.status, result.cards, result.candidates), ("ask", [], 0))
        self.assertEqual([m["id"] for m in result.mentioned], ["Q2469"])
        self.assertEqual(len(llm.received), 1)                       # 필터 추출 한 번 — 선별 호출 없음

    def test_condition_with_name_still_searches_and_offers_ask(self):
        result, llm = self.run_explore("안드로메다 은하보다 가까운 은하",
                                       {"semantic_query": "가까운 은하", "categories": ["은하"], "asks_fact": False},
                                       {"selected": [{"id": "Q4", "reason": "은하"}]})
        self.assertEqual(result.status, "ok")
        self.assertEqual([m["id"] for m in result.mentioned], ["Q2469"])
        self.assertEqual(len(llm.received), 2)

    def test_fact_flag_without_known_name_is_normal_search(self):
        result, _ = self.run_explore("블랙홀의 이름은?", {"semantic_query": "블랙홀", "asks_fact": True}, {"selected": []})
        self.assertEqual((result.status, result.mentioned), ("no_match", []))

    def test_api_returns_mentioned_and_notice(self):
        from vasthorizon.features.explore import ExploreResult
        services = Services(items=API_ITEMS, ask=FakeAsk(), health=healthy, explore=lambda q: ExploreResult(
            query=q, applied=[], cards=[], candidates=0, status="ask",
            mentioned=[{"id": "Q2469", "name": "안드로메다 은하", "group": "messier", "kind": "나선 은하"}]))
        body = TestClient(create_app(services, web_dir=None)).post("/api/explore", json={"query": "안드로메다 은하 블랙홀 이름"}).json()
        self.assertEqual((body["status"], body["mentioned"][0]["item_id"]), ("ask", "Q2469"))
        self.assertIn("그 천체에게 물으면", body["notice"])


NAMED_STARS = [
    item("Q3427", "베가", "star", "항성", 25), item("Q12179", "데네브", "star", "항성", 2600),
    item("Q12975", "알타이르", "star", "항성", 16.7), item("Q13072", "알니타크", "star", "항성", 1260),
    item("Q13070", "알닐람", "star", "항성", 2000), item("Q680341", "민타카", "star", "항성", 1200),
]


class ExploreNameQueryTest(ExploreTestBase):
    """이름만 있는 질문 · 성군 이름 — '찾지 못함' 대신 그 천체 · 구성 천체를 카드로 돌려준다."""

    def run_explore(self, query, *replies):
        llm = FakeChat(*[json.dumps(r, ensure_ascii=False) for r in replies])
        return explore(query, llm=llm, embedding=self.emb, db=self.db, items=CATALOG + NAMED_STARS), llm

    def test_name_only_query_returns_card_without_llm(self):
        result, llm = self.run_explore("베가")
        self.assertEqual((result.status, [c.item_id for c in result.cards]), ("ok", ["Q3427"]))
        self.assertIn("이름", result.cards[0].reason)
        self.assertEqual(llm.received, [])                            # 조건이 없으니 LLM을 부르지 않는다
        self.assertEqual(result.mentioned, [])                        # 카드가 곧 그 천체 — '질문하기' 보조 블록 없음
        result, _ = self.run_explore("베텔게우스와 시리우스")
        self.assertEqual([c.item_id for c in result.cards], ["Q12124", "Q3409"])

    def test_asterism_alias_returns_members(self):
        for query in ("여름 삼각형", "여름삼각형", "Summer Triangle"):
            result, llm = self.run_explore(query)
            self.assertEqual((result.status, [c.item_id for c in result.cards]), ("ok", ["Q3427", "Q12179", "Q12975"]), query)
            self.assertEqual(result.cards[0].reason, "여름 삼각형을 이루는 별입니다.")
            self.assertEqual((llm.received, result.mentioned), ([], []))

    def test_asterism_alias_table_matches_catalog(self):
        from vasthorizon.data.asterisms import ASTERISMS
        from vasthorizon.data.item_text import display_name
        names = {display_name(i["name"]) for i in json.loads(
            (get_settings().paths.data_dir / "items.json").read_text(encoding="utf-8"))["items"]}
        for group, (_, members) in ASTERISMS.items():
            self.assertEqual([m for m in members if m not in names], [], group)

    def test_llm_members_matched_against_catalog(self):
        result, llm = self.run_explore("오리온의 허리띠를 이루는 별",
                                       {"semantic_query": "오리온 허리띠", "members": ["알니타크", "알닐람", "민타카", "없는별"]},
                                       {"selected": []})
        self.assertEqual((result.status, [c.item_id for c in result.cards]), ("ok", ["Q13072", "Q13070", "Q680341"]))
        self.assertEqual(len(llm.received), 2)
        result, _ = self.run_explore("오리온의 허리띠", {"semantic_query": "오리온 허리띠", "members": ["없는별"]},
                                     {"selected": []})
        self.assertEqual((result.status, result.cards), ("no_match", []))   # 카탈로그에 없는 이름은 버린다

    def test_fact_question_still_asks(self):
        result, llm = self.run_explore("베가는 몇 광년 떨어져 있어?", {"semantic_query": "베가 거리", "asks_fact": True})
        self.assertEqual((result.status, result.cards, [m["id"] for m in result.mentioned]), ("ask", [], ["Q3427"]))
        self.assertEqual(len(llm.received), 1)

    def test_condition_with_name_keeps_selection(self):
        result, llm = self.run_explore("베가보다 밝은 별",
                                       {"semantic_query": "밝은 별", "categories": ["별"]},
                                       {"selected": [{"id": "Q3409", "reason": "겉보기 등급 -1.46"},
                                                     {"id": "Q3427", "reason": "중복"}]})
        self.assertEqual(len(llm.received), 2)                       # 필터 추출 + 선별
        self.assertEqual(result.applied, ["종류: 별"])
        self.assertEqual([c.item_id for c in result.cards], ["Q3427", "Q3409"])   # 이름이 나온 천체가 맨 앞, 중복 없음
        self.assertEqual(result.cards[1].reason, "겉보기 등급 -1.46")
        self.assertEqual([m["id"] for m in result.mentioned], ["Q3427"])   # 조건어가 있으면 보조 블록은 그대로


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
                                 cards=[ExploreCard("Q48469", "보이저 1호", "human_made", "우주 탐사선", "이유"),
                                        ExploreCard("Q193", "토성", "solar_system", "행성", "고리가 있음 · 근거: NASA NSSDCA",
                                                    "https://nssdc.gsfc.nasa.gov/planetary/factsheet/saturnfact.html")])

        def fake_letter(it):
            return LetterResult(item=it, departure=Departure(light_years=0.0027, light_time="약 24시간"),
                                letter="편지 [근거 1]", status="cited", cited=[], evidences=[])

        stars = API_ITEMS + [item("Q3409", "시리우스", "star", "항성", 8.6)]
        services = Services(items=stars, ask=FakeAsk(), health=healthy, explore=fake_explore, letter=fake_letter)
        return TestClient(create_app(services, web_dir=None), raise_server_exceptions=False)

    def test_explore_endpoint(self):
        body = self.client().post("/api/explore", json={"query": "은하"}).json()
        self.assertEqual((body["status"], body["cards"][0]["item_id"], body["applied"]), ("ok", "Q48469", ["종류: 은하"]))
        self.assertEqual([c["source_url"] for c in body["cards"]],
                         [None, "https://nssdc.gsfc.nasa.gov/planetary/factsheet/saturnfact.html"])   # 근거 링크는 따로

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


# ── 규칙 해석 · 정렬 · 결정적 경로 · 보강 데이터 (RAG 개선 1단계 묶음 B) ─────────

def solar(qid, name, kind, km, **attrs) -> dict:
    it = item(qid, name, "solar_system", kind, **attrs)
    it["distance"] = {"km": km, "ly": km / LY_KM, "basis": "horizons", "reference": "지구 중심에서 천체 중심까지",
                      "approximate": False, "method": None, "km_min": None, "km_max": None, "n_values": 1}
    return it


def sky(it: dict, dec: float) -> dict:
    it["dec_deg"], it["ra_deg"] = dec, 10.0
    return it


# 실제 QID — 보강 표(vasthorizon/data/enrich.json)가 붙는다
RULE_CATALOG = enrich_items([
    solar("Q525", "태양", "항성", 1.496e8),
    solar("Q2", "지구", "행성", 1.0), solar("Q111", "화성", "행성", 2.3e8),
    solar("Q319", "목성", "행성", 7.0e8, **{"평균 반지름(km)": 69911.0}),
    solar("Q193", "토성", "행성", 1.3e9, **{"평균 반지름(km)": 58232.0}),
    solar("Q324", "천왕성", "행성", 2.9e9), solar("Q332", "해왕성", "행성", 4.4e9),
    solar("Q11558", "101955 베누", "소행성", 3.3e8), solar("Q1385178", "162173 류구", "소행성", 3.0e8),
    solar("Q3030", "4 베스타", "소행성", 3.5e8), solar("Q118931", "99942 아포피스", "소행성", 2.2e8),
    solar("Q23054", "핼리 혜성", "혜성", 5.0e9),
    sky(item("Q14266", "센타우루스자리 프록시마", "star", "항성", 4.24, **{"겉보기 등급": 11.13}), -62.7),
    sky(item("Q2472", "센타우루스자리 알파", "star", "항성", 4.37, **{"겉보기 등급": -0.27, "맨눈 관측": True}), -60.8),
    sky(item("Q3409", "시리우스", "star", "항성", 8.6, **{"겉보기 등급": -1.44, "맨눈 관측": True}), -16.7),
    sky(item("Q2469", "안드로메다 은하", "messier", "나선 은하", 2_540_000,
             **{"겉보기 등급": 3.44, "맨눈 관측": True, "분류": "나선 은하"}), 41.3),
    sky(item("Q14041", "처녀자리 A 은하", "messier", "BC 은하", 53_000_000, **{"겉보기 등급": 8.6, "분류": "타원 은하"}), 12.4),
    sky(item("Q13724", "삼각형자리 은하", "messier", "나선 은하", 2_730_000,
             **{"겉보기 등급": 5.72, "맨눈 관측": True, "분류": "나선 은하"}), 30.7),
    item("Q8860", "오리온자리", "constellation", "별자리", **{"관측 계절": "겨울", "서울에서 관측": "전체 관측 가능"}),
    item("Q10476", "큰곰자리", "constellation", "별자리", **{"관측 계절": "봄", "서울에서 관측": "일년 내내 보임 (주극 별자리)"}),
    item("Q10506", "남십자자리", "constellation", "별자리", **{"관측 계절": "봄", "서울에서 관측": "관측 불가"}),
    item("Q10488", "용골자리", "constellation", "별자리", **{"관측 계절": "봄", "서울에서 관측": "일부만 관측 가능"}),
])


class RuleParseTest(unittest.TestCase):
    def test_full_interpretations(self):
        cases = {
            "블랙홀이 발견된 천체": {"has_black_hole": True},
            "고리가 있는 행성": {"has_rings": True, "categories": ["행성"]},
            "가장 가까운 별": {"sort_by": "distance", "order": "asc", "limit": 5, "categories": ["별"]},
            "한국에서 보이는 별자리": {"visible_from_korea": True, "categories": ["별자리"]},
            "탐사선이 방문한 소행성": {"visited_by_probe": True, "categories": ["소천체"], "kinds": ["소행성"]},
            "맨눈으로 보이는 은하": {"naked_eye": True, "categories": ["은하"]},
            "가장 먼 은하 3개": {"sort_by": "distance", "order": "desc", "limit": 3, "categories": ["은하"]},
            "겨울에 보이는 별자리": {"season": "겨울", "categories": ["별자리"]},
            "100광년 이내의 별": {"distance_ly_max": 100.0, "categories": ["별"]},
            "한국이 쏘아 올린 인공위성": {"korean": True, "categories": ["인공위성"]},
            # 부정형 — 긍정 규칙보다 먼저
            "탐사선이 방문하지 않은 행성": {"visited_by_probe": False, "categories": ["행성"]},
            "탐사선이 방문한 적 없는 소행성": {"visited_by_probe": False, "categories": ["소천체"], "kinds": ["소행성"]},
            "탐사선이 안 간 행성": {"visited_by_probe": False, "categories": ["행성"]},
            "블랙홀이 없는 은하": {"has_black_hole": False, "categories": ["은하"]},
            "고리가 있지 않은 행성": {"has_rings": False, "categories": ["행성"]},
            "맨눈으로 안 보이는 은하": {"naked_eye": False, "categories": ["은하"]},
            "한국에서 보이지 않는 별자리": {"visible_from_korea": False, "categories": ["별자리"]},
            "탐사선이 방문한 고리 없는 행성": {"visited_by_probe": True, "has_rings": False, "categories": ["행성"]},
        }
        for query, data in cases.items():
            parsed = parse_rules(query)
            self.assertTrue(parsed.complete, (query, parsed.leftover))
            self.assertEqual(parsed.data, data, query)
            parse_filters(parsed.data, query)                 # 규칙 결과도 LLM 결과와 같은 검증을 통과한다

    def test_partial_or_ambiguous_goes_to_llm(self):
        for query in ("빛이 조선 시대에 출발한 천체", "멀고 고요한 곳", "은하수", "구상성단", "겨울에 보이는 별",
                      "블랙홀이 있는 멋진 은하", "안드로메다 은하 가운데 블랙홀 이름은?"):
            self.assertFalse(parse_rules(query).complete, query)
        partial = parse_rules("블랙홀이 있는 멋진 은하")
        self.assertEqual((partial.data, partial.leftover), ({"has_black_hole": True, "categories": ["은하"]}, ["멋진"]))

    def test_negated_positive_rule_is_dropped(self):
        """긍정 규칙 바로 뒤에 부정어가 오면 긍정 필터를 버리고 LLM에 맡긴다 — 틀린 True가 data에 섞이지 않는다."""
        for query, key in (("블랙홀이 아닌 천체", "has_black_hole"), ("한국 관련 없는 위성", "korean"),
                           ("맨눈으로 보이는 게 아닌 은하", "naked_eye"), ("고리 없지 않은 행성", "has_rings")):
            parsed = parse_rules(query)
            self.assertFalse(parsed.complete, query)
            self.assertNotEqual(parsed.data.get(key), True, (query, parsed.data))


class SortAndFilterFieldTest(unittest.TestCase):
    def test_new_where_clauses_and_describe(self):
        f = parse_filters({"categories": ["별자리"], "group": "constellation", "visible_from_korea": True,
                           "has_black_hole": None, "has_rings": True, "visited_by_probe": True}, "q")
        self.assertEqual(f.where(), {"$and": [{"category": {"$in": ["별자리"]}}, {"group": {"$eq": "constellation"}},
                                              {"rings": {"$eq": True}}, {"visited": {"$eq": True}},
                                              {"seoul_visible": {"$eq": True}}]})
        self.assertEqual([a for a in f.describe() if "별자리" in a], ["종류: 별자리"])    # '분류: 별자리' 중복 없음
        sort = parse_filters({"sort_by": "distance", "limit": 3}, "q")
        self.assertEqual((sort.order, sort.limit), ("asc", 3))
        self.assertIn("정렬: 가까운 순 · 상위 3", sort.describe())
        self.assertEqual(parse_filters({"sort_by": "size"}, "q").order, "desc")
        self.assertIsNone(parse_filters({"limit": 3}, "q").limit)                # 정렬 없는 limit은 버린다

    def test_bad_sort_values_rejected(self):
        for bad in ({"sort_by": "mass"}, {"sort_by": "distance", "order": "up"}, {"sort_by": "distance", "limit": 0},
                    {"sort_by": "distance", "limit": 99}, {"has_rings": "yes"}, {"visible_from_korea": 1}):
            with self.assertRaises(JsonReplyError, msg=bad):
                parse_filters(bad, "q")

    def test_rank_rows_sorts_whole_rows(self):
        rows = [("a", "", {"name": "a", "distance_ly": 8.6, "magnitude": -1.4}), ("b", "", {"name": "b", "distance_ly": 4.2}),
                ("c", "", {"name": "c", "magnitude": 3.0})]
        near = rank_rows(rows, parse_filters({"sort_by": "distance"}, "q"))
        self.assertEqual([r[0] for r in near], ["b", "a"])                         # 거리가 없는 항목은 뺀다
        far = rank_rows(rows, parse_filters({"sort_by": "distance", "order": "desc"}, "q"))
        self.assertEqual([r[0] for r in far], ["a", "b"])
        self.assertEqual([r[0] for r in rank_rows(rows, parse_filters({"sort_by": "brightness"}, "q"))], ["a", "c"])

    def test_size_sort_never_mixes_radius_and_area(self):
        # 리뷰 지적: 반지름(km)과 면적(제곱도)을 한 열로 정렬해 "가장 큰 천체"에 바다뱀자리(1303제곱도)가 목성보다 앞섰다
        rows = [("jup", "", {"name": "목성", "radius_km": 69911.0}), ("ear", "", {"name": "지구", "radius_km": 6371.0}),
                ("hya", "", {"name": "바다뱀자리", "area_sqdeg": 1303.0}), ("cru", "", {"name": "남십자자리", "area_sqdeg": 68.0}),
                ("gal", "", {"name": "은하", "magnitude": None})]
        size = lambda data: [r[0] for r in rank_rows(rows, parse_filters({"sort_by": "size", **data}, "q"))]
        self.assertEqual(size({}), ["jup", "ear"])                                          # 반지름이 있는 항목만
        self.assertEqual(size({"order": "asc"}), ["ear", "jup"])
        self.assertEqual(size({"categories": ["별자리"]}), ["hya", "cru"])                   # 별자리면 면적만
        self.assertEqual(size({"group": "constellation", "order": "asc"}), ["cru", "hya"])
        self.assertEqual([r[0] for r in rank_rows(rows[2:], parse_filters({"sort_by": "size"}, "q"))], ["hya", "cru"])
        # 정렬 기준이 없을 때 None 값은 맨 뒤 (None과 숫자를 비교하다 멈추지 않는다)
        loose = [("a", "", {"name": "a", "magnitude": None}), ("b", "", {"name": "b", "magnitude": 2.0, "distance_ly": None})]
        self.assertEqual([r[0] for r in rank_rows(loose, parse_filters({}, "q"))], ["b", "a"])

    def test_single_clause_where_is_plain(self):
        """Chroma의 $and는 조건이 둘 이상이어야 한다 — 조건이 하나면 $and 없이 그 조건만."""
        self.assertEqual(parse_filters({"has_rings": True}, "q").where(), {"rings": {"$eq": True}})
        self.assertIsNone(parse_filters({}, "q").where())

    def test_select_prompt_text_is_compact(self):
        from vasthorizon.data.item_text import build_item_text
        from vasthorizon.rag.prompts import SELECT_TEXT_CHARS, compact_item_text
        andromeda = next(it for it in RULE_CATALOG if it["id"] == "Q2469")
        full = build_item_text(andromeda, REF_YEAR)
        short = compact_item_text(full)
        self.assertLessEqual(len(short), SELECT_TEXT_CHARS)
        self.assertLess(len(short), len(full))
        for fact in ("안드로메다 은하", "M31*", "맨눈", "254만광년"):                   # 핵심 속성은 남는다
            self.assertIn(fact, short)
        self.assertNotIn("데이터 출처", short)


class ExploreRulePathTest(unittest.TestCase):
    """규칙으로 완전히 해석되는 질의 — 필터 추출 · 선별 LLM을 모두 부르지 않는다 (가짜 LLM이 호출되면 실패)."""

    def setUp(self):
        self.db = chromadb.EphemeralClient()
        self.emb = FakeEmbedding()
        sync_items(RULE_CATALOG, chroma.open_collection(ITEMS_NAME, self.emb, self.db), self.emb, REF_YEAR)

    def tearDown(self):
        chroma.drop_collection(ITEMS_NAME, self.db)

    def run_explore(self, query, *replies):
        llm = FakeChat(*[json.dumps(r, ensure_ascii=False) for r in replies])
        return explore(query, llm=llm, embedding=self.emb, db=self.db, items=RULE_CATALOG), llm

    def test_black_hole_without_llm(self):
        result, llm = self.run_explore("블랙홀이 발견된 천체")
        self.assertEqual(llm.received, [])
        self.assertEqual((result.status, {c.item_id for c in result.cards}), ("ok", {"Q2469", "Q14041"}))
        andromeda = next(c for c in result.cards if c.item_id == "Q2469")
        self.assertIn("중심에 M31* 블랙홀(질량 약 1억 4,000만 태양질량)", andromeda.reason)
        self.assertIn("근거: 한국어 위키백과", andromeda.reason)
        self.assertNotIn("http", andromeda.reason)                                # URL은 설명이 아니라 source_url로
        self.assertTrue(andromeda.source_url.startswith("https://ko.wikipedia.org/"), andromeda.source_url)
        self.assertIn("중심 블랙홀: 예", result.applied)

    def test_ringed_planets(self):
        result, llm = self.run_explore("고리가 있는 행성")
        self.assertEqual(llm.received, [])
        self.assertEqual({c.name for c in result.cards}, {"목성", "토성", "천왕성", "해왕성"})
        self.assertIn("근거: NASA NSSDCA", result.cards[0].reason)
        self.assertNotIn("http", result.cards[0].reason)
        self.assertTrue(all(c.source_url.startswith("https://nssdc.gsfc.nasa.gov/") for c in result.cards))
        self.assertIn("알려진 위성", result.cards[0].reason)

    def test_nearest_star_sun_first_then_proxima(self):
        result, llm = self.run_explore("가장 가까운 별")
        self.assertEqual(llm.received, [])
        self.assertEqual([c.item_id for c in result.cards][:3], ["Q525", "Q14266", "Q2472"])
        self.assertIn("가장 가까운 별", result.cards[0].reason)
        self.assertIn("태양 다음으로 가까운 별", result.cards[1].reason)
        self.assertIn("4.24광년", result.cards[1].reason)
        self.assertEqual(result.candidates, 4)                                    # 별 범주 전체에서 정렬

    def test_korea_visible_constellations_without_duplicate_applied(self):
        result, llm = self.run_explore("한국에서 보이는 별자리")
        self.assertEqual(llm.received, [])
        self.assertEqual({c.name for c in result.cards}, {"오리온자리", "큰곰자리"})   # 관측 불가 · 일부만 보임은 빠진다
        self.assertEqual(result.applied, ["종류: 별자리", "서울에서 관측: 예"])

    def test_probe_visited_asteroids(self):
        result, llm = self.run_explore("탐사선이 방문한 소행성")
        self.assertEqual(llm.received, [])
        self.assertEqual({c.name for c in result.cards}, {"101955 베누", "162173 류구", "4 베스타"})   # 아포피스 · 핼리 없음
        bennu = next(c for c in result.cards if c.item_id == "Q11558")
        self.assertIn("OSIRIS-REx", bennu.reason)

    def test_negated_probe_rule_without_llm(self):
        # 리뷰 지적: "탐사선이 방문하지 않은 행성"이 visited_by_probe=True로 잡혀 방문한 행성을 돌려줬다
        result, llm = self.run_explore("탐사선이 방문하지 않은 행성")
        self.assertEqual(llm.received, [])
        self.assertIn("탐사선 방문: 아니오", result.applied)
        visited = {it["id"] for it in RULE_CATALOG if it["attrs"].get("탐사선 방문")}
        self.assertTrue(result.cards)
        self.assertFalse({c.item_id for c in result.cards} & visited)
        self.assertTrue(all(c.source_url is None for c in result.cards))
        result, llm = self.run_explore("블랙홀이 없는 은하")
        self.assertEqual((llm.received, [c.item_id for c in result.cards]), ([], ["Q13724"]))

    def test_uses_llm_matches_explore_paths(self):
        from vasthorizon.features.explore import uses_llm
        for query in ("고리가 있는 행성", "탐사선이 방문하지 않은 행성", "가장 가까운 별", "시리우스", "시리우스와 안드로메다 은하"):
            self.assertFalse(uses_llm(query, RULE_CATALOG), query)
            _, llm = self.run_explore(query)
            self.assertEqual(llm.received, [], query)
        for query in ("블랙홀이 있는 멋진 은하", "시리우스보다 가까운 별", "신비로운 별"):
            self.assertTrue(uses_llm(query, RULE_CATALOG), query)

    def test_naked_eye_galaxies_and_farthest(self):
        result, llm = self.run_explore("맨눈으로 보이는 은하")
        self.assertEqual((llm.received, [c.item_id for c in result.cards]), ([], ["Q2469", "Q13724"]))
        result, _ = self.run_explore("가장 먼 은하")
        self.assertEqual(result.cards[0].item_id, "Q14041")

    def test_rules_off_uses_llm(self):
        result, llm = explore("고리가 있는 행성", llm=FakeChat(json.dumps({"categories": ["행성"], "has_rings": True}),
                                                       json.dumps({"selected": [{"id": "Q193", "reason": "고리: 예"}]})),
                              embedding=self.emb, db=self.db, items=RULE_CATALOG, rules=False), None
        self.assertEqual([c.item_id for c in result.cards], ["Q193"])

    def test_partial_rule_merged_into_llm_filters(self):
        """'멋진'은 표에 없어 LLM을 부른다. LLM이 블랙홀 필드를 비워도 표의 해석(블랙홀)이 합쳐진다."""
        result, llm = self.run_explore("블랙홀이 있는 멋진 은하", {"semantic_query": "은하", "categories": ["은하"]},
                                       {"selected": [{"id": "Q14041", "reason": "블랙홀: M87*"}]})
        self.assertEqual(len(llm.received), 2)
        candidates = json.loads(llm.received[1][-1].content.split("후보:\n", 1)[1])
        self.assertEqual({c["id"] for c in candidates}, {"Q2469", "Q14041"})
        self.assertEqual([c.item_id for c in result.cards], ["Q14041"])

    def test_llm_sort_query_ranks_whole_catalog(self):
        """표로 다 해석되지 않는 정렬 질의 — 후보는 의미 검색이 아니라 정렬 결과이고, 선별 뒤에도 정렬 순서를 지킨다."""
        result, llm = self.run_explore("가장 가까운 붉은 별",
                                       {"semantic_query": "붉은 별", "categories": ["별"], "sort_by": "distance", "limit": 2},
                                       {"selected": [{"id": "Q2472", "reason": "붉은 별"}, {"id": "Q14266", "reason": "적색 왜성"}]})
        candidates = json.loads(llm.received[1][-1].content.split("후보:\n", 1)[1])
        self.assertEqual([c["id"] for c in candidates], ["Q525", "Q14266", "Q2472", "Q3409"])
        self.assertEqual([c.item_id for c in result.cards], ["Q14266", "Q2472"])

    def test_fact_question_with_rule_words_still_asks(self):
        result, llm = self.run_explore("안드로메다 은하 가운데 블랙홀 이름은?", {"semantic_query": "블랙홀", "asks_fact": True})
        self.assertEqual((result.status, len(llm.received)), ("ask", 1))


class EnrichmentDataTest(unittest.TestCase):
    """공용 카탈로그(data/items.json)와 보강 표 — 블랙홀 · 고리 · 탐사선 방문 · 서울 관측."""

    @classmethod
    def setUpClass(cls):
        from vasthorizon.data.catalog import load_items
        cls.items = enrich_items(load_items())
        cls.by_id = {it["id"]: it for it in cls.items}

    def test_black_holes(self):
        holes = [it for it in self.items if it["attrs"].get("블랙홀")]
        self.assertGreaterEqual(len(holes), 4)
        for qid in ("Q2469", "Q92258118", "Q14041", "Q91461627"):       # web/data/blackholes.json의 네 은하
            self.assertIn(qid, {it["id"] for it in holes})
        self.assertEqual(self.by_id["Q2469"]["attrs"]["블랙홀"], "M31*")
        for it in holes:
            self.assertTrue(it["attrs"].get("블랙홀 질량"), it["name"])
            self.assertTrue(any(s.get("used_for", "").startswith("블랙홀") for s in it["sources"]), it["name"])
        self.assertNotIn("블랙홀", self.by_id["Q13724"]["attrs"])        # 근거가 없는 은하(M33)에는 생기지 않는다

    def test_rings_and_moons(self):
        planets = [it for it in self.items if item_category(it) == "행성"]
        self.assertEqual({it["name"] for it in planets if it["attrs"].get("고리") is True}, {"목성", "토성", "천왕성", "해왕성"})
        self.assertEqual({it["name"] for it in planets if it["attrs"].get("고리") is False}, {"수성", "금성", "지구", "화성"})
        self.assertTrue(all(isinstance(it["attrs"].get("위성 수"), int) for it in planets))

    def test_probe_visits(self):
        visited = {it["id"] for it in self.items if it["attrs"].get("탐사선 방문")}
        self.assertTrue({"Q11558", "Q1385178", "Q3030", "Q596", "Q339", "Q6604", "Q18325885", "Q23054",
                         "Q844672", "Q2565"} <= visited)
        self.assertNotIn("Q118931", visited)                                # 아포피스는 계획만 (2029년 도착 예정)
        self.assertIn("탐사 계획", self.by_id["Q118931"]["attrs"])

    def test_seoul_visibility_boolean(self):
        for it in self.items:
            if it["group"] == "constellation" or (it["group"] in ("star", "messier") and it.get("dec_deg") is not None):
                self.assertIsInstance(it["attrs"].get("서울에서_관측"), bool, it["name"])
        self.assertIs(self.by_id["Q14266"]["attrs"]["서울에서_관측"], False)    # 프록시마 (적위 -62.7°)
        self.assertIs(self.by_id["Q2469"]["attrs"]["서울에서_관측"], True)
        self.assertIs(self.by_id["Q8860"]["attrs"]["서울에서_관측"], True)      # 오리온자리 '전체 관측 가능'

    def test_enrichment_is_idempotent_and_valid(self):
        from vasthorizon.data.catalog import validate_items
        self.assertEqual(enrich_items(self.items), self.items)
        self.assertEqual(validate_items(self.items), [])                  # 새 출처도 이용 조건이 기록돼 있다

    def test_catalog_file_already_enriched(self):
        """data/items.json에 보강이 반영돼 있다 (화면의 항목 상세와 색인이 같은 속성을 본다)."""
        from vasthorizon.data.catalog import load_items
        self.assertEqual(load_items(), self.items)


if __name__ == "__main__":
    unittest.main()
