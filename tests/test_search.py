"""검증된 벡터 검색 테스트 (store/search.py) — 가짜 임베딩 · 메모리 전용 Chroma.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import unittest
import uuid
from unittest import mock

import chromadb
import chromadb.errors
from langchain_chroma import Chroma
from langchain_core.documents import Document

from tests.fakes import FakeEmbedding
from vasthorizon.store import chroma
from vasthorizon.store.search import search


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.db = chromadb.EphemeralClient()
        self.emb = FakeEmbedding()
        self.name = f"s_{uuid.uuid4().hex[:10]}"
        col = chroma.open_collection(self.name, self.emb, self.db)
        texts = [f"문서 {i} 내용" for i in range(12)]
        col.upsert(ids=[f"id{i}" for i in range(12)], documents=texts, embeddings=self.emb.embed_documents(texts),
                   metadatas=[{"item_id": "A" if i < 8 else "B", "seq": i} for i in range(12)])

    def tearDown(self):
        chroma.drop_collection(self.name, self.db)

    def run_search(self, **kw):
        kw.setdefault("k", 5)
        return search(self.name, "문서 3 내용", self.emb, self.db, **kw)

    def test_chroma_path_scores_match_exact(self):
        """Chroma 경로 점수(1 − 코사인 거리)와 정확 비교 점수(코사인 유사도)가 같다."""
        normal = self.run_search(where={"item_id": "A"})
        self.assertEqual(normal.path, "chroma")
        with mock.patch.object(Chroma, "similarity_search_by_vector_with_relevance_scores", return_value=[]):
            exact = self.run_search(where={"item_id": "A"})
        self.assertEqual(exact.path, "exact")
        self.assertEqual([h.id for h in normal.hits], [h.id for h in exact.hits])
        for a, b in zip(normal.hits, exact.hits):
            self.assertAlmostEqual(a.score, b.score, places=4)

    def test_internal_error_recomputed_exactly(self):
        with mock.patch.object(Chroma, "similarity_search_by_vector_with_relevance_scores",
                               side_effect=chromadb.errors.InternalError("Error finding id")), \
                self.assertLogs("vasthorizon.store.search", "WARNING"):
            outcome = self.run_search(where={"item_id": "A"})
        self.assertEqual((outcome.path, len(outcome.hits)), ("exact", 5))
        self.assertTrue(all(h.metadata["item_id"] == "A" for h in outcome.hits))

    def test_short_result_recomputed(self):
        one = [(Document(page_content="문서 0 내용", metadata={"item_id": "A"}, id="id0"), 0.1)]
        with mock.patch.object(Chroma, "similarity_search_by_vector_with_relevance_scores", return_value=one), \
                self.assertLogs("vasthorizon.store.search", "WARNING"):
            outcome = self.run_search(where={"item_id": "A"})
        self.assertEqual((outcome.path, len(outcome.hits), outcome.expected), ("exact", 5, 5))

    def test_expected_respects_scope_size(self):
        outcome = self.run_search(where={"item_id": "B"}, k=10)          # B는 4건뿐
        self.assertEqual((outcome.path, outcome.expected, len(outcome.hits)), ("chroma", 4, 4))

    def test_mmr_exact_path(self):
        with mock.patch.object(Chroma, "max_marginal_relevance_search_by_vector", return_value=[]), \
                self.assertLogs("vasthorizon.store.search", "WARNING"):
            outcome = self.run_search(where={"item_id": "A"}, search_type="mmr", fetch_k=8)
        self.assertEqual((outcome.path, len(outcome.hits)), ("exact", 5))
        self.assertTrue(all(h.score is None for h in outcome.hits))

    def test_empty_scope(self):
        self.assertEqual(self.run_search(where={"item_id": "Z"}).path, "empty")
        self.assertEqual(search("없는_컬렉션", "q", self.emb, self.db, k=3).path, "empty")

    def test_embedding_mismatch_not_hidden(self):
        with self.assertRaises(chroma.EmbeddingMismatchError):
            search(self.name, "q", FakeEmbedding(model="fake-b"), self.db, k=3)


if __name__ == "__main__":
    unittest.main()
