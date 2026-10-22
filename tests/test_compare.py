"""검색 방식 비교 테스트 (F2014) — 유사도 · MMR 분기 · 필터 · 상태 안내, Streamlit 화면.

가짜 임베딩 · 격리된 색인(임시 폴더)을 쓴다. 외부 호출 · 토큰 사용 없음.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import chromadb

from tests.test_rag import DOCS, VOYAGER, IsolatedRagTest
from vasthorizon.features import compare as compare_module
from vasthorizon.features.compare import CompareResult, Hit, compare_search
from vasthorizon.store import chroma

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"
QUESTION = "보이저 1호는 태양계를 벗어났나?"


class CompareSearchTest(IsolatedRagTest):
    def run_compare(self, **kw):
        with mock.patch.object(compare_module, "search", wraps=compare_module.search) as spy:
            result = compare_search(VOYAGER["id"], QUESTION, embedding=self.emb, db=self.db, **kw)
        return result, spy

    def test_both_methods_with_same_filter_and_settings(self):
        result, spy = self.run_compare(top_k=3, fetch_k=8, lambda_mult=0.3)
        self.assertEqual(result.status, "ok")
        calls = {c.kwargs["search_type"]: c.kwargs for c in spy.call_args_list}
        self.assertEqual(set(calls), {"similarity", "mmr"})
        for kw in calls.values():
            self.assertEqual((kw["where"], kw["k"], kw["fetch_k"], kw["lambda_mult"]), ({"item_id": "Q48469"}, 3, 8, 0.3))
        self.assertIs(calls["similarity"]["query_vector"], calls["mmr"]["query_vector"])   # 같은 질문 벡터
        self.assertEqual({k: result.settings[k] for k in ("top_k", "fetch_k", "lambda", "collection")},
                         {"top_k": 3, "fetch_k": 8, "lambda": 0.3, "collection": DOCS})

    def test_results_side_by_side(self):
        result, _ = self.run_compare(top_k=3)
        for method in ("similarity", "mmr"):
            hits = result.hits[method]
            self.assertEqual([h.rank for h in hits], list(range(1, len(hits) + 1)))
            self.assertTrue(all(h.chunk_id.startswith("Q48469:") for h in hits))       # 다른 항목 청크가 섞이지 않음
            self.assertTrue(all(h.score is not None for h in hits))                     # MMR도 유사도를 함께 표시
        self.assertEqual(result.overlap, {h.chunk_id for h in result.hits["similarity"]}
                         & {h.chunk_id for h in result.hits["mmr"]})
        self.assertGreater(result.chunks_in_scope, 3)

    def test_fetch_k_is_at_least_top_k(self):
        result, _ = self.run_compare(top_k=5, fetch_k=2)
        self.assertEqual(result.settings["fetch_k"], 5)

    def test_index_missing(self):
        chroma.drop_collection(DOCS, self.db)
        emb = mock.Mock(wraps=self.emb)
        result = compare_search(VOYAGER["id"], QUESTION, embedding=emb, db=self.db)
        self.assertEqual((result.status, result.hits), ("index_missing", {}))
        emb.embed_query.assert_not_called()

    def test_no_chunks_for_item(self):
        result, _ = self.run_compare()
        other = compare_search("Q999", QUESTION, embedding=self.emb, db=self.db)
        self.assertEqual((result.status, other.status, other.chunks_in_scope), ("ok", "empty", 0))
        self.assertIn("문서 청크가 없습니다", other.warnings[0])

    def test_search_failure(self):
        with mock.patch.object(compare_module, "search", side_effect=chromadb.errors.InternalError("boom")):
            result = compare_search(VOYAGER["id"], QUESTION, embedding=self.emb, db=self.db)
        self.assertEqual(result.status, "failed")
        self.assertIn("InternalError", result.warnings[0])


def fake_result(status="ok") -> CompareResult:
    hit = lambda rank, cid, title: Hit(rank, cid, title, "개요", "위키백과", "https://ko.wikipedia.org", "본문", 0.9)  # noqa: E731
    result = CompareResult("Q48469", QUESTION, {"top_k": 2, "fetch_k": 8, "lambda": 0.5, "collection": DOCS,
                                                 "embedding": None}, status, chunks_in_scope=12)
    if status == "ok":
        result.hits = {"similarity": [hit(1, "a", "보이저 1호"), hit(2, "b", "태양권계면")],
                       "mmr": [hit(1, "a", "보이저 1호"), hit(2, "c", "Voyager 1 (NASA NSSDCA)")]}
        result.paths = {"similarity": "chroma", "mmr": "exact"}
    else:
        result.warnings = ["문서 색인이 없습니다."]
    return result


class StreamlitAppTest(unittest.TestCase):
    """Streamlit 화면 — 같은 입력으로 두 결과를 나란히, 상태 안내 (AppTest: 브라우저 없이 스크립트 실행)."""

    def app(self, result=None, ids=("Q48469",)):
        from streamlit.testing.v1 import AppTest
        items = [{"id": "Q48469", "name": "보이저 1호", "group": "human_made"}]
        patches = [mock.patch("vasthorizon.data.catalog.load_items", return_value=items),
                   mock.patch("vasthorizon.store.doc_index.indexed_item_ids", return_value=list(ids)),
                   mock.patch("vasthorizon.features.compare.compare_search", return_value=result or fake_result())]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        at = AppTest.from_file(str(APP), default_timeout=30)
        at.run()
        return at

    def test_side_by_side(self):
        at = self.app()
        self.assertFalse(at.exception)
        at.button[0].click().run()
        self.assertFalse(at.exception)
        headers = [m.value for m in at.markdown if m.value.startswith("####")]
        self.assertEqual(headers, ["#### 유사도 검색", "#### MMR 검색 (정확 비교로 재계산)"])
        self.assertEqual(at.metric[0].value, "1개")                                     # 공통 근거 1개 (a)
        self.assertTrue(any("두 방식 공통" in m.value for m in at.markdown))
        self.assertTrue(any("top-k 2 · fetch-k 8 · lambda 0.5" in c.value for c in at.caption))

    def test_no_indexed_items(self):
        at = self.app(ids=())
        self.assertIn("문서 색인에 항목이 없습니다", at.warning[0].value)
        self.assertEqual(len(at.button), 0)

    def test_index_missing_message(self):
        at = self.app(result=fake_result("index_missing"))
        at.button[0].click().run()
        self.assertEqual(at.error[0].value, "문서 색인이 없습니다.")
        self.assertEqual(len(at.metric), 0)


if __name__ == "__main__":
    unittest.main()
