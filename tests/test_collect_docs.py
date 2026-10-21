"""외부 문서 수집 테스트 (F2003 · F2004 · NF2002) — 가짜 위키 · NASA · LLM, 외부 호출 없음.

임시 폴더의 캐시만 쓴다. 실제 API 키 · 운영 캐시(data/cache)는 쓰지 않는다.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests
from langchain_core.messages import AIMessage

from vasthorizon.collect.cache import CollectCache
from vasthorizon.collect.collector import Collector
from vasthorizon.data.docs import Candidate, Document, SourceError, nssdca, wikipedia
from vasthorizon.rag.llm_json import JsonReplyError, parse_json_reply, string_list

ITEM = {"id": "Q48469", "group": "human_made", "name": "보이저 1호", "wiki_title": "보이저 1호",
        "name_en": "Voyager 1", "kind": "우주 탐사선", "attrs": {"COSPAR ID": "1977-084A", "국가": "미국"}}
Q1 = "보이저 1호는 태양계를 벗어났나?"
Q2 = "보이저 1호의 노래는 무엇인가?"
LONG = "본문 " * 200


def cand(pageid: int, title: str, summary: str = "충분히 긴 요약 문장입니다. " * 3, **kw) -> Candidate:
    return Candidate(doc_id=f"wiki:{pageid}", title=title, summary=summary, url=f"https://ko/{title}",
                     source_type="위키백과", **kw)


def doc(doc_id: str, title: str, text: str = LONG, source: str = "위키백과") -> Document:
    return Document(doc_id=doc_id, title=title, url=f"https://ko/{title}", permalink=f"https://ko/{title}?oldid=1",
                    text=text, source_type=source, license="CC BY-SA 4.0", fetched_at="2026-10-21T00:00:00+00:00")


class FakeWiki:
    """위키 대역. fail_* 집합에 넣은 대상은 실패한다 — 집합에서 빼면 '장애 해제'."""

    def __init__(self, results: dict[str, list[Candidate]], pages: dict[str, Document]):
        self.results, self.pages = results, pages
        self.searches: list[str] = []
        self.fetches: list[str] = []
        self.fail_search: set[str] = set()
        self.api_error_search: set[str] = set()
        self.fail_fetch: set[str] = set()

    def search(self, query, limit):
        self.searches.append(query)
        if query in self.fail_search:
            raise requests.ConnectionError("모의 네트워크 오류")
        if query in self.api_error_search:
            raise SourceError("위키백과", "maxlag", "모의 서버 지연")
        return self.results.get(query, [])[:limit]

    def fetch(self, title, max_chars):
        self.fetches.append(title)
        if title in self.fail_fetch:
            raise requests.ConnectionError("모의 네트워크 오류")
        return self.pages.get(title)


class FakeNasa:
    def __init__(self):
        self.calls = 0

    def fetch(self, cospar, max_chars):
        self.calls += 1
        return doc(f"nssdca:{cospar}", "Voyager 1 (NASA NSSDCA)", source="NASA")


class FakeLLM:
    """응답을 차례로 돌려주고, 받은 메시지를 기록한다. 응답이 바닥나면 실패한다."""

    def __init__(self, *replies: dict | str):
        self.replies = list(replies)
        self.received: list[list] = []

    def invoke(self, messages):
        self.received.append(messages)
        if not self.replies:
            raise AssertionError("예상하지 못한 LLM 호출")
        reply = self.replies.pop(0)
        return AIMessage(reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False))


class CollectorTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = CollectCache(Path(self.tmp.name))
        self.own = cand(10350, "보이저 1호")
        self.helio = cand(1, "태양권계면")
        self.song = cand(2, "사건의 지평선 (윤하의 노래)")
        self.disamb = cand(3, "L2", disambiguation=True)
        self.tiny = cand(4, "짧은 문서", summary="짧다")
        self.wiki = FakeWiki(
            results={"보이저 1호": [self.own, self.song], "태양권계면": [self.helio, self.disamb, self.tiny],
                     "결과 없음": []},
            pages={"보이저 1호": doc("wiki:10350", "보이저 1호", text="짧은 항목 문서"),   # 짧지만 유효
                   "태양권계면": doc("wiki:1", "태양권계면"),
                   "사건의 지평선 (윤하의 노래)": doc("wiki:2", "사건의 지평선 (윤하의 노래)")},
        )
        self.nasa = FakeNasa()

    def tearDown(self):
        self.tmp.cleanup()

    def collect(self, question: str, *replies):
        llm = FakeLLM(*replies)
        result = Collector(cache=self.cache, llm=llm, wiki=self.wiki, nasa=self.nasa).collect(ITEM, question)
        return result, llm

    def run_q1(self):
        return self.collect(Q1, {"queries": ["태양권계면"]}, {"selected": ["wiki:1", "wiki:999"], "reason": "관련"})


class CollectorTest(CollectorTestBase):
    def test_own_documents_always_included(self):
        """항목 자체 문서는 짧아도 · 선별되지 않아도 연결된다. NASA 미션 설명도 함께."""
        result, _ = self.run_q1()
        ids = {d.doc_id for d in result.docs}
        self.assertIn("wiki:10350", ids)
        self.assertIn("nssdca:1977-084A", ids)
        self.assertEqual(next(d for d in result.decisions if d.doc_id == "wiki:10350").decision, "색인")
        self.assertTrue(result.complete)

    def test_item_name_always_searched(self):
        result, _ = self.collect("질문", {"queries": ["태양권계면"]}, {"selected": []})
        self.assertEqual(result.queries[0], "보이저 1호")
        self.assertIn("보이저 1호", self.wiki.searches)

    def test_selection_sees_only_title_and_summary(self):
        """선별 전에는 본문을 받지 않는다 — 버려진 후보는 fetch되지 않는다."""
        result, llm = self.run_q1()
        select_input = llm.received[1][-1].content
        self.assertIn("태양권계면", select_input)
        self.assertNotIn(LONG.strip()[:20], select_input)
        self.assertNotIn("사건의 지평선 (윤하의 노래)", self.wiki.fetches)
        self.assertIn("wiki:1", {d.doc_id for d in result.new_docs})

    def test_rule_and_prompt_rejections_recorded(self):
        result, _ = self.run_q1()
        reasons = {d.title: (d.decision, d.reason) for d in result.decisions}
        self.assertEqual(reasons["L2"], ("제외", "동음이의 문서"))
        self.assertEqual(reasons["짧은 문서"], ("제외", "요약이 너무 짧음"))
        self.assertEqual(reasons["사건의 지평선 (윤하의 노래)"], ("제외", "선별 프롬프트에서 제외"))
        self.assertEqual(reasons["태양권계면"], ("색인", "선별됨"))
        self.assertNotIn("wiki:999", {d.doc_id for d in result.docs})       # 후보에 없는 ID는 무시

    def test_same_question_does_not_recollect(self):
        self.run_q1()
        counts = (len(self.wiki.searches), len(self.wiki.fetches), self.nasa.calls)
        result, _ = self.collect(Q1)                                       # LLM 응답 없음 — 호출되면 실패
        self.assertEqual((result.llm_calls, result.searched_queries, len(result.new_docs)), (0, [], 0))
        self.assertTrue(result.question_cached)
        self.assertEqual((len(self.wiki.searches), len(self.wiki.fetches), self.nasa.calls), counts)
        self.assertEqual(len(result.docs), 3)

    def test_search_cache_shared_across_items(self):
        self.run_q1()
        other = {**ITEM, "id": "Q1", "name": "보이저 2호", "wiki_title": "보이저 1호", "attrs": {}}
        before = len(self.wiki.searches)
        Collector(cache=self.cache, llm=FakeLLM({"queries": ["태양권계면"]}, {"selected": []}),
                  wiki=self.wiki, nasa=self.nasa).collect(other, "질문")
        self.assertEqual(self.wiki.searches[before:], ["보이저 2호"])        # 태양권계면은 캐시

    def test_prefetch_own_uses_no_llm(self):
        docs, _ = Collector(cache=self.cache, llm=FakeLLM(), wiki=self.wiki, nasa=self.nasa).prefetch_own(ITEM)
        self.assertEqual({d.source_type for d in docs}, {"위키백과", "NASA"})
        self.assertEqual({v["role"] for v in self.cache.get_manifest(ITEM["id"])["docs"].values()}, {"항목 문서"})


# ── [P1] 1. 실패한 단계는 완료로 기록되지 않고, 장애 해제 후 이어서 처리된다 ─────

class FailureRecoveryTest(CollectorTestBase):
    def test_search_failure_recovers_on_rerun(self):
        self.wiki.fail_search = {"태양권계면"}
        first, _ = self.collect(Q1, {"queries": ["태양권계면"]}, {"selected": []})
        self.assertFalse(first.complete)
        self.assertEqual([f.step for f in first.failures], ["검색"])
        self.assertNotIn("wiki:1", {d.doc_id for d in first.docs})

        self.wiki.fail_search = set()                                     # 장애 해제
        searches_before = list(self.wiki.searches)
        second, _ = self.collect(Q1, {"selected": ["wiki:1"]})            # 검색어는 재사용, 선별만 새로
        self.assertTrue(second.complete)
        self.assertIn("wiki:1", {d.doc_id for d in second.new_docs})
        self.assertEqual(self.wiki.searches[len(searches_before):], ["태양권계면"])   # 성공했던 검색은 반복 안 함
        self.assertEqual(second.cached_queries, ["보이저 1호"])

    def test_selection_json_error_recovers_on_rerun(self):
        first, _ = self.collect(Q1, {"queries": ["태양권계면"]}, "선별 결과는 태양권계면입니다")
        self.assertEqual([f.step for f in first.failures], ["선별"])
        self.assertTrue(any(d.decision == "보류" for d in first.decisions))
        record = self.cache.get_manifest(ITEM["id"])["questions"][Q1]
        self.assertEqual(record["judged"], {})                            # 실패를 '빈 선택'으로 저장하지 않음

        searches = len(self.wiki.searches)
        second, llm = self.collect(Q1, {"selected": ["wiki:1"]})
        self.assertTrue(second.complete)
        self.assertEqual(len(llm.received), 1)                             # 선별만 다시, 검색어 추출은 재사용
        self.assertEqual(len(self.wiki.searches), searches)                # 검색 API 재호출 없음
        self.assertIn("wiki:1", {d.doc_id for d in second.new_docs})

    def test_body_fetch_failure_recovers_on_rerun(self):
        self.wiki.fail_fetch = {"태양권계면"}
        first, _ = self.run_q1()
        self.assertEqual([f.step for f in first.failures], ["본문"])
        self.assertNotIn("wiki:1", {d.doc_id for d in first.docs})

        self.wiki.fail_fetch = set()
        second, llm = self.collect(Q1)                                    # 판정은 남아 있어 LLM 호출 없음
        self.assertEqual(len(llm.received), 0)
        self.assertTrue(second.complete)
        self.assertIn("wiki:1", {d.doc_id for d in second.new_docs})

    def test_query_extraction_failure_not_recorded(self):
        first, _ = self.collect(Q1, "JSON 아님", {"selected": []})       # 항목 이름 검색 후보는 그대로 선별
        self.assertEqual([f.step for f in first.failures], ["검색어 추출"])
        self.assertEqual(first.queries, ["보이저 1호"])
        self.assertNotIn(Q1, self.cache.get_manifest(ITEM["id"])["questions"])
        second, _ = self.collect(Q1, {"queries": ["태양권계면"]}, {"selected": ["wiki:1"]})
        self.assertIn("태양권계면", second.queries)
        self.assertTrue(second.complete)


# ── [P2] 2. 새 질문은 같은 검색어의 후보를 다시 선별한다 ───────────────────────

class PerQuestionSelectionTest(CollectorTestBase):
    def test_candidate_rejected_for_q1_can_be_selected_for_q2(self):
        self.run_q1()                                                      # Q1: 노래 문서 제외
        searches = len(self.wiki.searches)
        q2, llm = self.collect(Q2, {"queries": ["보이저 1호"]}, {"selected": ["wiki:2"]})
        self.assertIn("wiki:2", {d.doc_id for d in q2.new_docs})
        self.assertEqual(len(self.wiki.searches), searches)                 # 검색 API 재호출 없음
        self.assertIn("사건의 지평선 (윤하의 노래)", llm.received[1][-1].content)

        again, llm = self.collect(Q2)                                       # 성공한 Q2 재실행
        self.assertEqual((len(llm.received), again.llm_calls), (0, 0))


# ── [P2] 3. 응답 필드 타입을 검증한다 ──────────────────────────────────────────

class ReplySchemaTest(CollectorTestBase):
    def test_string_list_rejects_wrong_types(self):
        for bad in ({"queries": "NASA"}, {"queries": 42}, {"queries": None}, {"queries": {"a": 1}},
                    {"queries": ["a", 1]}, {}):
            with self.assertRaises(JsonReplyError, msg=bad):
                string_list(bad, "queries", 5)
        self.assertEqual(string_list({"queries": [" a ", "", "a", "b", "c"]}, "queries", 2), ["a", "b"])

    def test_bad_query_reply_never_splits_into_characters(self):
        for bad in ({"queries": "NASA"}, {"queries": 42}):
            with self.subTest(bad=bad):
                self.tearDown()
                self.setUp()
                result, _ = self.collect(Q1, bad, {"selected": []})
                self.assertEqual(result.queries, ["보이저 1호"])
                self.assertNotIn("N", self.wiki.searches)
                self.assertEqual([f.step for f in result.failures], ["검색어 추출"])

    def test_bad_selection_reply_is_failure_not_empty_choice(self):
        for bad in ({"selected": "wiki:1"}, {"selected": None}, {"selected": [1, "wiki:1"]}, ["wiki:1"]):
            with self.subTest(bad=bad):
                self.tearDown()
                self.setUp()
                result, _ = self.collect(Q1, {"queries": ["태양권계면"]}, bad)
                self.assertEqual([f.step for f in result.failures], ["선별"])
                self.assertEqual(self.cache.get_manifest(ITEM["id"])["questions"][Q1]["judged"], {})

    def test_duplicate_ids_in_selection_collapse(self):
        result, _ = self.collect(Q1, {"queries": ["태양권계면"]}, {"selected": ["wiki:1", "wiki:1"]})
        self.assertTrue(result.complete)
        self.assertEqual([d.doc_id for d in result.new_docs].count("wiki:1"), 1)


# ── [P2] 4. 위키 API 오류는 정상적인 0건과 구분한다 ─────────────────────────────

class FakeResponse:
    def __init__(self, data: dict, headers: dict | None = None):
        self._data, self.headers = data, headers or {}

    def json(self):
        return self._data


class WikiApiErrorTest(unittest.TestCase):
    def setUp(self):
        self.http = mock.Mock()
        patches = [mock.patch.object(wikipedia, "http", return_value=self.http),
                   mock.patch.object(wikipedia, "_sleep")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_error_body_raises_instead_of_empty_result(self):
        self.http.get.return_value = FakeResponse({"error": {"code": "badvalue", "info": "잘못된 값"}})
        with self.assertRaises(SourceError):
            wikipedia.search("블랙홀", 5)
        with self.assertRaises(SourceError):
            wikipedia.fetch("블랙홀", 1000)

    def test_transient_error_retried_then_raised(self):
        maxlag = FakeResponse({"error": {"code": "maxlag", "info": "지연"}}, {"Retry-After": "1"})
        self.http.get.return_value = maxlag
        with self.assertRaises(SourceError):
            wikipedia.search("블랙홀", 5)
        self.assertEqual(self.http.get.call_count, wikipedia.MAX_API_RETRIES + 1)

    def test_transient_error_then_success(self):
        ok = FakeResponse({"query": {"pages": [{"pageid": 1, "title": "블랙홀", "index": 1, "extract": "요약"}]}})
        self.http.get.side_effect = [FakeResponse({"error": {"code": "maxlag"}}), ok]
        self.assertEqual([c.title for c in wikipedia.search("블랙홀", 5)], ["블랙홀"])

    def test_zero_results_is_normal(self):
        self.http.get.return_value = FakeResponse({"batchcomplete": True})
        self.assertEqual(wikipedia.search("없는검색어", 5), [])

    def test_empty_extract_is_error(self):
        self.http.get.return_value = FakeResponse(
            {"query": {"pages": [{"pageid": 1, "title": "빈 문서", "extract": "  \n", "revisions": [{"revid": 1}]}]}})
        with self.assertRaises(SourceError):
            wikipedia.fetch("빈 문서", 1000)


class SearchCachePolicyTest(CollectorTestBase):
    def test_api_error_not_cached_and_recovers(self):
        self.wiki.api_error_search = {"태양권계면"}
        first, _ = self.collect(Q1, {"queries": ["태양권계면"]}, {"selected": []})
        self.assertIsNone(self.cache.get_search("위키백과", "태양권계면"))
        self.assertEqual(first.failures[0].reason, "maxlag")
        self.wiki.api_error_search = set()
        second, _ = self.collect(Q1, {"selected": ["wiki:1"]})
        self.assertIn("wiki:1", {d.doc_id for d in second.new_docs})

    def test_zero_results_cached(self):
        self.collect("질문", {"queries": ["결과 없음"]}, {"selected": []})
        self.assertEqual(self.cache.get_search("위키백과", "결과 없음"), [])
        searches = len(self.wiki.searches)
        self.collect("다른 질문", {"queries": ["결과 없음"]}, {"selected": []})
        self.assertNotIn("결과 없음", self.wiki.searches[searches:])

    def test_legacy_empty_search_cache_is_ignored(self):
        path = self.cache._search_path("위키백과", "태양권계면")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"query": "태양권계면", "candidates": []}), encoding="utf-8")   # status 없음
        self.assertIsNone(self.cache.get_search("위키백과", "태양권계면"))


# ── [P2] 5. 빈 본문 자체 문서는 성공으로 캐시 · 연결하지 않는다 ──────────────────

class EmptyOwnDocumentTest(CollectorTestBase):
    def test_short_nonempty_own_doc_included(self):
        result, _ = self.run_q1()
        self.assertIn("wiki:10350", {d.doc_id for d in result.docs})       # '짧은 항목 문서'

    def test_empty_own_doc_reported_and_retried(self):
        for empty in ("", "   \n "):
            with self.subTest(empty=repr(empty)):
                self.tearDown()
                self.setUp()
                self.wiki.pages["보이저 1호"] = doc("wiki:10350", "보이저 1호", text=empty)
                first, _ = self.run_q1()
                self.assertNotIn("wiki:10350", {d.doc_id for d in first.docs})
                self.assertIn("항목 문서", [f.step for f in first.failures])

                self.wiki.pages["보이저 1호"] = doc("wiki:10350", "보이저 1호", text="복구된 본문")
                second, _ = self.collect(Q1)
                self.assertIn("wiki:10350", {d.doc_id for d in second.docs})

    def test_existing_empty_cache_recovered(self):
        """예전에 저장된 빈 본문 캐시가 있어도 정상 본문으로 복구된다."""
        path = self.cache._doc_path("wiki:10350")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc("wiki:10350", "보이저 1호", text="").to_dict()), encoding="utf-8")
        self.cache.put_title("위키백과", "보이저 1호", "wiki:10350")
        result, _ = self.run_q1()
        own = next(d for d in result.docs if d.doc_id == "wiki:10350")
        self.assertEqual(own.text, "짧은 항목 문서")
        self.assertIn("보이저 1호", self.wiki.fetches)

    def test_put_doc_refuses_empty(self):
        with self.assertRaises(ValueError):
            self.cache.put_doc(doc("wiki:9", "빈", text=" "))


# ── 기존 캐시 점검 · 복구 ─────────────────────────────────────────────────────

class RepairTest(CollectorTestBase):
    def test_repair_migrates_v1_and_removes_bad_entries(self):
        root = Path(self.tmp.name)
        (root / "items").mkdir(parents=True)
        (root / "items" / "Q48469.json").write_text(json.dumps({
            "item_id": "Q48469", "questions": {Q1: ["태양권계면"]},
            "queries": {"태양권계면": {"selected": [], "rejected": []}},     # 실패도 완료로 남았던 v1 기록
            "docs": {"wiki:1": {"title": "태양권계면"}, "wiki:404": {"title": "사라진 문서"}},
        }), encoding="utf-8")
        self.cache.put_doc(doc("wiki:1", "태양권계면"))
        empty = self.cache._doc_path("wiki:5")
        empty.write_text(json.dumps(doc("wiki:5", "빈", text="").to_dict()), encoding="utf-8")
        legacy = self.cache._search_path("위키백과", "성간 매질")
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(json.dumps({"query": "성간 매질", "candidates": []}), encoding="utf-8")

        report = self.cache.repair()
        self.assertEqual(report, {"migrated_manifests": 1, "removed_empty_docs": 1,
                                  "removed_unverified_searches": 1, "unlinked_missing_docs": 1})
        manifest = self.cache.get_manifest("Q48469")
        self.assertNotIn("queries", manifest)
        self.assertEqual(manifest["questions"][Q1]["queries"], ["태양권계면"])
        self.assertEqual(manifest["questions"][Q1]["judged"], {})
        self.assertEqual(list(manifest["docs"]), ["wiki:1"])

        result, llm = self.collect(Q1, {"selected": []})                   # 변환 후: 검색어 재사용, 선별은 다시
        self.assertEqual(len(llm.received), 1)
        self.assertTrue(result.complete)


class ParsingTest(unittest.TestCase):
    def test_parse_json_reply_variants(self):
        self.assertEqual(parse_json_reply('{"queries": ["a"]}'), {"queries": ["a"]})
        self.assertEqual(parse_json_reply('```json\n{"queries": ["a"]}\n```'), {"queries": ["a"]})
        self.assertEqual(parse_json_reply('결과: {"queries": ["a"]} 입니다'), {"queries": ["a"]})
        with self.assertRaises(JsonReplyError):
            parse_json_reply("JSON 아님")

    def test_wiki_extract_cleaning(self):
        raw = ("보이저 1호는 탐사선이다.\n\n== 역사 ==\n발사되었다.\n\n== 빈 절 ==\n== 임무 ==\n=== 목성 ===\n"
               "목성을 지났다.\n\n== 각주 ==\n[1] 출처\n== 외부 링크 ==\n링크")
        cleaned = wikipedia.clean_extract(raw)
        self.assertIn("== 역사 ==\n발사되었다.", cleaned)
        self.assertNotIn("빈 절", cleaned)
        self.assertLess(cleaned.index("== 임무 =="), cleaned.index("=== 목성 ==="))   # 하위 절이 있으면 상위 제목 유지
        self.assertNotIn("각주", cleaned)
        self.assertNotIn("링크", cleaned)

    def test_nssdca_description_parsing(self):
        page = ('<h1>Voyager 1</h1><div class="urone"><h2>Description</h2><p><p>Voyager 1 was one of a pair'
                ' &amp; more.\n<p>\nSecond paragraph.</p></p></div><div class="urtwo"><h2>Alternate Names</h2>')
        title, text = nssdca.parse_description(page)
        self.assertEqual(title, "Voyager 1")
        self.assertEqual(text, "Voyager 1 was one of a pair & more.\n\nSecond paragraph.")
        self.assertIsNone(nssdca.parse_description("<h1>X</h1><p>no description</p>"))


if __name__ == "__main__":
    unittest.main()
