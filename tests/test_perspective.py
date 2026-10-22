"""관점 전환 테스트 (F2010) — 위기 안내 우선 · 주제 분류 · 서가 검색 · 인용 검증 · 서가 색인.

가짜 임베딩 · 가짜 LLM · 메모리 전용 Chroma · 가짜 수집기를 쓴다. 외부 호출 · 토큰 사용 없음.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import hashlib
import json
import unittest

from unittest import mock

import chromadb
from fastapi.testclient import TestClient

from tests.fakes import FakeChat, FakeEmbedding
from tests.test_api import FakeAsk, healthy
from tests.test_features import item
from vasthorizon.api.app import create_app
from vasthorizon.api.services import Services
from vasthorizon.data.docs import Document
from vasthorizon.data.perspective_library import CRISIS_MESSAGE, DISCLAIMER, THEMES, is_crisis
from vasthorizon.features import perspective as perspective_module
from vasthorizon.features.perspective import (
    PerspectiveInputError, PerspectiveResult, library_name, library_titles, perspective, sync_library,
)
from vasthorizon.rag.graph import REJECTED_ANSWER
from vasthorizon.llm import MissingApiKeyError
from vasthorizon.rag.retrieval import IndexMissingError
from vasthorizon.store import chroma
from vasthorizon.store.doc_index import DocIndexError

ITEMS = [item("Q2", "지구", "solar_system", "행성"), item("Q48469", "보이저 1호", "human_made", "우주 탐사선"),
         item("Q12124", "베텔게우스", "star", "항성", 548)]
ANSWER = "그 마음을 여기 잠시 놓아 둡니다. 보이저 1호가 찍은 지구는 작은 점이었습니다 [근거 1]."


def doc(title: str) -> Document:
    return Document(doc_id="wiki:" + hashlib.sha1(title.encode()).hexdigest()[:8], title=title,
                    url=f"https://ko.wikipedia.org/wiki/{title}", permalink="p",
                    text=f"== 개요 ==\n{title}에 관한 사실을 담은 문서 본문이다. " * 3, source_type="위키백과",
                    license="CC BY-SA 4.0", fetched_at="2026-10-22T00:00:00+00:00")


class StubLibraryCollector:
    def __init__(self, fail=()):
        self.fail, self.titles = set(fail), []

    def fetch_wiki(self, title, failures):
        from vasthorizon.collect.collector import StepFailure
        self.titles.append(title)
        if title in self.fail:
            failures.append(StepFailure("문서", title, "모의 실패"))
            return None
        return doc(title)


def classify_reply(crisis=False, themes=("small",), query="멀리서 본 지구"):
    return json.dumps({"crisis": crisis, "themes": list(themes), "query": query}, ensure_ascii=False)


class LibraryTestBase(unittest.TestCase):
    def setUp(self):
        self.db = chromadb.EphemeralClient()
        self.emb = FakeEmbedding()
        sync_library(self.emb, self.db, StubLibraryCollector())

    def tearDown(self):
        for name in (library_name(), chroma.staging_name(library_name())):
            chroma.drop_collection(name, self.db)

    def run_perspective(self, text=None, theme=None, classify=None, answer=ANSWER, *more):
        json_llm = FakeChat(classify) if classify else FakeChat()
        llm = FakeChat(answer, *more) if answer else FakeChat()
        result = perspective(text, theme, ITEMS, llm=llm, json_llm=json_llm, embedding=self.emb, db=self.db)
        return result, llm, json_llm


# ── 위기 표현 ─────────────────────────────────────────────────────────────

class CrisisKeywordTest(unittest.TestCase):
    def test_detects_crisis_expressions(self):
        for text in ("죽고 싶어", "그냥 사라지고 싶다", "자 살 생각이 들어", "이제 그만 살고 싶어", "I want to die",
                     "영원히 잠들고 싶어"):
            self.assertTrue(is_crisis(text), text)

    def test_ordinary_expressions(self):
        for text in ("오늘 너무 지쳤어", "일을 빨리 끝내고 싶어", "별이 죽으면 어떻게 돼?", ""):
            self.assertFalse(is_crisis(text), text)


class CrisisFlowTest(LibraryTestBase):
    def test_keyword_crisis_before_index_and_llm(self):
        chroma.drop_collection(library_name(), self.db)     # 서가 색인이 없어도 위기 안내는 나간다
        result = perspective("죽고 싶어", None, ITEMS, llm=FakeChat(), json_llm=FakeChat(),
                             embedding=self.emb, db=self.db)
        self.assertEqual((result.status, result.answer, result.crisis_by), ("crisis", CRISIS_MESSAGE, "keyword"))
        self.assertEqual([s["number"] for s in result.support], ["109", "1577-0199"])
        self.assertEqual(result.disclaimer, DISCLAIMER)

    def test_classifier_crisis_makes_no_answer(self):
        result, llm, _ = self.run_perspective("다 내려놓고 멀리 떠나고 싶어", classify=classify_reply(crisis=True),
                                              answer=None)
        self.assertEqual((result.status, result.crisis_by, result.cited), ("crisis", "classifier", []))
        self.assertEqual(llm.received, [])


class CrisisOrderTest(LibraryTestBase):
    """관점 전환 리뷰 P1 — 위기 확인은 부가 필드 · 감정 버튼 값 · 서가 준비 상태와 관계없이 먼저 끝난다.

    검색 · 임베딩 · 답변 모델을 spy로 감싸 위기 경로에서 호출되지 않는지 본다.
    """

    def run_spied(self, text, theme=None, classify=None, drop_library=False, json_llm=None):
        if drop_library:
            chroma.drop_collection(library_name(), self.db)
        self.answer_llm = FakeChat()                       # 호출되면 AssertionError
        self.json_llm = json_llm or (FakeChat(classify) if classify else FakeChat())
        with mock.patch.object(perspective_module, "search", wraps=perspective_module.search) as self.search_spy,                 mock.patch.object(chroma, "default_embedding", side_effect=AssertionError("임베딩 호출")) as self.emb_spy:
            return perspective(text, theme, ITEMS, llm=self.answer_llm, json_llm=self.json_llm, db=self.db)

    def assert_no_search_or_answer(self):
        self.assertEqual((self.search_spy.call_count, self.emb_spy.call_count, self.answer_llm.received), (0, 0, []))

    def test_classifier_crisis_ignores_broken_hints(self):
        broken = [{"crisis": True}, {"crisis": True, "themes": None, "query": "q"},
                  {"crisis": True, "themes": "small", "query": "q"}, {"crisis": True, "themes": ["small"], "query": 42},
                  {"crisis": True, "themes": [1, 2]}]
        for reply in broken:
            result = self.run_spied("멀리 떠나고 싶어", classify=json.dumps(reply))
            self.assertEqual((result.status, result.crisis_by), ("crisis", "classifier"), reply)
            self.assert_no_search_or_answer()

    def test_keyword_crisis_with_bad_theme_and_no_library(self):
        result = self.run_spied("죽고 싶어", theme="unknown", drop_library=True)
        self.assertEqual((result.status, result.crisis_by, self.json_llm.received), ("crisis", "keyword", []))
        self.assert_no_search_or_answer()

    def test_classifier_crisis_without_library(self):
        result = self.run_spied("멀리 떠나고 싶어", classify=classify_reply(crisis=True), drop_library=True)
        self.assertEqual((result.status, len(self.json_llm.received)), ("crisis", 1))
        self.assert_no_search_or_answer()

    def test_classifier_crisis_with_bad_theme(self):
        result = self.run_spied("멀리 떠나고 싶어", theme="unknown", classify=classify_reply(crisis=True))
        self.assertEqual(result.status, "crisis")

    def test_normal_input_errors_come_after_crisis_check(self):
        with self.assertRaises(PerspectiveInputError):
            self.run_spied("지쳤어", theme="unknown", classify=classify_reply())
        self.assertEqual(len(self.json_llm.received), 1)                 # 위기 확인은 먼저 끝났다
        with self.assertRaises(IndexMissingError):
            self.run_spied("지쳤어", classify=classify_reply(), drop_library=True)
        self.assertEqual(len(self.json_llm.received), 1)
        self.assert_no_search_or_answer()

    def test_theme_button_alone_skips_classifier(self):
        with self.assertRaises(IndexMissingError):                      # 서가가 없어도 분류 호출은 없다
            self.run_spied(None, theme="small", drop_library=True)
        self.assertEqual(self.json_llm.received, [])

    def test_unchecked_when_classifier_unavailable(self):
        cases = {"응답이 JSON이 아님": "JSON 아님", "crisis가 참거짓이 아님": json.dumps({"crisis": "no"}),
                 "crisis 없음": json.dumps({"themes": ["small"]})}
        for label, reply in cases.items():
            result = self.run_spied("멀리 떠나고 싶어", classify=reply)
            self.assertEqual(result.status, "unchecked", label)
            self.assert_no_search_or_answer()
        with mock.patch.object(perspective_module, "json_chat_model", side_effect=MissingApiKeyError):
            result = perspective("멀리 떠나고 싶어", None, ITEMS, llm=FakeChat(), db=self.db)
        self.assertEqual(result.status, "unchecked")
        self.assertIn("상담 창구", result.answer)


# ── 관점 전환 ─────────────────────────────────────────────────────────────

class PerspectiveTest(LibraryTestBase):
    def test_text_flow_searches_only_theme_documents(self):
        result, llm, json_llm = self.run_perspective("내가 너무 작게 느껴져", classify=classify_reply())
        self.assertEqual((result.status, result.themes), ("cited", ["small"]))
        self.assertTrue(result.evidences)
        self.assertTrue({ev.title for ev in result.evidences} <= set(THEMES["small"].titles))
        self.assertEqual([it["name"] for it in result.items], ["지구", "보이저 1호"])
        self.assertEqual((len(json_llm.received), len(llm.received)), (1, 1))
        self.assertIn("내가 너무 작게 느껴져", llm.received[0][-1].content)

    def test_theme_button_makes_no_classification_call(self):
        result, _, json_llm = self.run_perspective(theme="meaning")
        self.assertEqual((result.status, json_llm.received), ("cited", []))
        self.assertTrue({ev.title for ev in result.evidences} <= set(THEMES["meaning"].titles))
        self.assertEqual([it["name"] for it in result.items], ["베텔게우스"])     # 카탈로그에 있는 항목만

    def test_unknown_theme_keys_from_llm_are_dropped(self):
        result, _, _ = self.run_perspective("외로워", classify=classify_reply(themes=("nope", "lonely", "small", "hurry")))
        self.assertEqual(result.themes, ["lonely", "small"])

    def test_bad_search_hints_without_crisis_searches_whole_library(self):
        # crisis=false가 확인되면 주제 · 검색어 오류는 기존처럼 서가 전체 검색으로 넘어간다
        reply = json.dumps({"crisis": False, "themes": None, "query": 42})
        result, _, _ = self.run_perspective("음", classify=reply)
        self.assertEqual((result.status, result.themes), ("cited", []))
        self.assertIn("분류하지 못해", result.warnings[0])
        self.assertTrue({ev.title for ev in result.evidences} <= set(library_titles()))

    def test_invalid_citation_is_rejected(self):
        llm = FakeChat("지어낸 위로 [근거 9].", "또 지어낸 위로.")
        result = perspective(None, "small", ITEMS, llm=llm, json_llm=FakeChat(), embedding=self.emb, db=self.db)
        self.assertEqual((result.status, result.answer), ("rejected", REJECTED_ANSWER))

    def test_invalid_input(self):
        with self.assertRaises(PerspectiveInputError):
            perspective("   ", None, ITEMS, llm=FakeChat(), json_llm=FakeChat(), embedding=self.emb, db=self.db)
        with self.assertRaises(PerspectiveInputError):
            perspective(None, "unknown", ITEMS, llm=FakeChat(), json_llm=FakeChat(), embedding=self.emb, db=self.db)

    def test_missing_library_raises_after_crisis_check(self):
        chroma.drop_collection(library_name(), self.db)     # EphemeralClient는 프로세스 안에서 상태를 공유한다
        json_llm, llm = FakeChat(classify_reply()), FakeChat()
        with self.assertRaises(IndexMissingError):
            perspective("지쳤어", None, ITEMS, llm=llm, json_llm=json_llm, embedding=self.emb, db=self.db)
        self.assertEqual((len(json_llm.received), llm.received), (1, []))   # 위기 확인만 하고 답변은 없음


# ── 서가 색인 ─────────────────────────────────────────────────────────────

class LibraryIndexTest(LibraryTestBase):
    def titles_in_index(self):
        metas = self.db.get_collection(library_name()).get(include=["metadatas"])["metadatas"]
        return {m["title"] for m in metas}

    def test_all_library_documents_indexed_once(self):
        self.assertEqual(self.titles_in_index(), set(library_titles()))
        report, failures = sync_library(self.emb, self.db, StubLibraryCollector())
        self.assertEqual((report.embedded, failures), (0, []))              # 다시 실행해도 재임베딩 없음

    def test_failed_document_keeps_existing_chunks(self):
        report, failures = sync_library(self.emb, self.db, StubLibraryCollector(fail={"창백한 푸른 점"}))
        self.assertEqual(len(failures), 1)
        self.assertEqual(report.deleted, 0)
        self.assertIn("창백한 푸른 점", self.titles_in_index())

    def test_rebuild_stops_when_a_document_is_missing(self):
        before = chroma.collection_count(library_name(), self.db)
        with self.assertRaises(DocIndexError):
            sync_library(self.emb, self.db, StubLibraryCollector(fail={"첨성대"}), rebuild=True)
        self.assertEqual(chroma.collection_count(library_name(), self.db), before)

    def test_rebuild_swaps_in_new_collection(self):
        report, _ = sync_library(self.emb, self.db, StubLibraryCollector(), rebuild=True)
        self.assertEqual(chroma.collection_count(library_name(), self.db), report.chunks)
        self.assertEqual(chroma.collection_count(chroma.staging_name(library_name()), self.db), 0)


# ── API ──────────────────────────────────────────────────────────────────

class PerspectiveApiTest(unittest.TestCase):
    def client(self, result: PerspectiveResult | Exception):
        self.calls = []

        def fake(text, theme):
            self.calls.append((text, theme))
            if isinstance(result, Exception):
                raise result
            return result

        services = Services(items=ITEMS, ask=FakeAsk(), health=healthy, perspective=fake)
        return TestClient(create_app(services, web_dir=None), raise_server_exceptions=False)

    def test_themes(self):
        body = self.client(None).get("/api/perspective/themes").json()
        self.assertEqual([t["key"] for t in body], list(THEMES))

    def test_crisis_response(self):
        crisis = PerspectiveResult(text="죽고 싶어", status="crisis", answer=CRISIS_MESSAGE, crisis_by="keyword")
        body = self.client(crisis).post("/api/perspective", json={"text": "죽고 싶어"}).json()
        self.assertTrue(body["crisis"])
        self.assertEqual(([s["number"] for s in body["support"]], body["notice"], body["cited"]),
                         (["109", "1577-0199"], None, []))
        self.assertEqual(body["disclaimer"], DISCLAIMER)

    def test_normal_response_has_disclaimer_and_items(self):
        ok = PerspectiveResult(text="작아", status="cited", answer=ANSWER, themes=["small"],
                               items=[{"id": "Q2", "name": "지구"}])
        body = self.client(ok).post("/api/perspective", json={"text": "작아", "theme": "small"}).json()
        self.assertEqual((body["crisis"], body["items"], body["disclaimer"]),
                         (False, [{"id": "Q2", "name": "지구"}], DISCLAIMER))
        self.assertEqual(self.calls, [("작아", "small")])

    def test_unchecked_response(self):
        unchecked = perspective_module.unchecked_result("멀리 떠나고 싶어")
        body = self.client(unchecked).post("/api/perspective", json={"text": "멀리 떠나고 싶어"}).json()
        self.assertEqual((body["status"], body["crisis"], body["notice"], len(body["support"])),
                         ("unchecked", False, None, 2))

    def test_errors(self):
        r = self.client(PerspectiveInputError("마음 한 줄을 적거나 감정 버튼을 골라 주세요.")).post("/api/perspective", json={})
        self.assertEqual((r.status_code, r.json()["code"]), (422, "invalid_request"))
        r = self.client(IndexMissingError("서가 없음")).post("/api/perspective", json={"theme": "small"})
        self.assertEqual((r.status_code, r.json()["code"]), (503, "index_missing"))
        r = self.client(None).post("/api/perspective", json={"text": "가" * 301})
        self.assertEqual((r.status_code, r.json()["code"]), (422, "invalid_request"))


if __name__ == "__main__":
    unittest.main()
