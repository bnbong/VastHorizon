"""문서 청킹 · cosmos_docs 색인 테스트 — 가짜 임베딩 · 메모리 전용 Chroma.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

import chromadb
import requests

from tests.fakes import FakeEmbedding
from vasthorizon.collect.cache import CollectCache
from vasthorizon.collect.collector import Collector
from vasthorizon.data.docs import Document
from vasthorizon.store import chroma
from vasthorizon.store.chunking import chunk_document, section_paths
from vasthorizon.store.doc_index import (
    DocIndexError, build_records, has_body, indexed_item_ids, rebuild_docs, sync_item_docs,
)

WIKI_TEXT = (
    "보이저 1호는 1977년에 발사된 탐사선이다. " * 20 + "\n\n"
    "== 임무 과정 ==\n\n=== 목성 탐사 ===\n" + "보이저 1호는 1979년 목성을 지났다. " * 30 + "\n\n"
    "=== 토성 탐사 ===\n" + "보이저 1호는 1980년 토성을 지났다. " * 30 + "\n\n"
    "== 태양권 탈출 ==\n" + "2012년 태양권계면을 지났다. " * 30
)
NASA_TEXT = ("Voyager 1 was launched in 1977. It flew past Jupiter and Saturn. " * 15 + "\n\n"
             + "Voyager 1 is speeding away from the Sun at about 3.5 AU per year. " * 15)


def doc(doc_id: str, title: str, text: str, source: str = "위키백과") -> Document:
    return Document(doc_id=doc_id, title=title, url=f"https://example.org/{title}",
                    permalink=f"https://example.org/{title}?oldid=1", text=text, source_type=source,
                    license="CC BY-SA 4.0" if source == "위키백과" else "미국 정부 저작물",
                    fetched_at="2026-10-21T00:00:00+00:00")


WIKI = doc("wiki:10350", "보이저 1호", WIKI_TEXT)
NASA = doc("nssdca:1977-084A", "Voyager 1 (NASA NSSDCA)", NASA_TEXT, source="NASA")
HELIO = doc("wiki:1", "태양권계면", "태양권계면은 태양풍이 성간 매질에 막혀 멈추는 경계이다. " * 10)
VOYAGER = {"id": "Q48469", "name": "보이저 1호"}
VOYAGER2 = {"id": "Q48470", "name": "보이저 2호"}
LINKS = {"wiki:10350": {"role": "항목 문서", "query": None},
         "nssdca:1977-084A": {"role": "항목 문서", "query": None},
         "wiki:1": {"role": "관련 문서", "query": "태양권계면"}}


class ChunkingTest(unittest.TestCase):
    def test_body_within_chunk_size(self):
        for d in (WIKI, NASA):
            for size, overlap in ((1000, 200), (400, 80)):
                chunks = chunk_document(d, size, overlap)
                self.assertTrue(all(len(c.body) <= size for c in chunks), (d.title, size))

    def test_chunk_count_changes_with_settings(self):
        self.assertGreater(len(chunk_document(WIKI, 400, 80)), len(chunk_document(WIKI, 1000, 200)))

    def test_wiki_chunks_carry_section_path(self):
        chunks = chunk_document(WIKI, 400, 80)
        sections = {c.section for c in chunks}
        self.assertIn("임무 과정 > 목성 탐사", sections)
        self.assertIn("태양권 탈출", sections)
        jupiter = next(c for c in chunks if c.section == "임무 과정 > 목성 탐사")
        self.assertTrue(jupiter.text.startswith("[보이저 1호 > 임무 과정 > 목성 탐사]\n"))

    def test_nasa_chunks_split_on_sentences_not_headings(self):
        chunks = chunk_document(NASA, 300, 60)
        self.assertTrue(all(c.section == "" for c in chunks))
        self.assertTrue(all(c.text.startswith("[Voyager 1 (NASA NSSDCA)]\n") for c in chunks))
        self.assertFalse(any(c.body.startswith(".") for c in chunks))     # 마침표는 앞 문장 끝에 남는다

    def test_section_paths(self):
        paths = dict((p, s) for p, s in section_paths("서론\n== 가 ==\n본문\n=== 나 ===\n본문\n== 다 ==\n"))
        self.assertEqual(list(paths.values()), ["가", "가 > 나", "다"])


class DocIndexTest(unittest.TestCase):
    def setUp(self):
        self.db = chromadb.EphemeralClient()
        self.name = f"d_{uuid.uuid4().hex[:10]}"
        self.emb = FakeEmbedding()
        self.col = chroma.open_collection(self.name, self.emb, self.db)

    def tearDown(self):
        chroma.drop_collection(self.name, self.db)

    def sync(self, item, docs, size=1000, overlap=200, emb=None):
        return sync_item_docs(item, docs, LINKS, self.col, emb or self.emb, size, overlap)

    def test_chunk_ids_and_metadata(self):
        report = self.sync(VOYAGER, [WIKI, NASA, HELIO])
        got = self.col.get(include=["metadatas"])
        self.assertEqual(len(got["ids"]), report.chunks)
        self.assertTrue(all(cid.startswith("Q48469:") for cid in got["ids"]))
        self.assertIn("Q48469:wiki:10350:0", got["ids"])
        meta = dict(zip(got["ids"], got["metadatas"]))["Q48469:wiki:1:0"]
        for key in ("title", "source_url", "permalink", "item_id", "query", "fetched_at", "source_type", "license"):
            self.assertIn(key, meta)
        self.assertEqual((meta["role"], meta["query"], meta["source_type"]), ("관련 문서", "태양권계면", "위키백과"))
        self.assertEqual(set(report.by_source), {"위키백과", "NASA"})                  # 출처 종류 구분

    def test_same_document_for_two_items_does_not_overwrite(self):
        self.sync(VOYAGER, [WIKI, HELIO])
        self.sync(VOYAGER2, [HELIO])
        ids = self.col.get(include=[])["ids"]
        self.assertIn("Q48469:wiki:1:0", ids)
        self.assertIn("Q48470:wiki:1:0", ids)

    def test_rerun_skips_embedding(self):
        first = self.sync(VOYAGER, [WIKI, NASA])
        texts = self.emb.texts
        second = self.sync(VOYAGER, [WIKI, NASA])
        self.assertEqual((second.embedded, second.unchanged), (0, first.chunks))
        self.assertEqual(self.emb.texts, texts)

    def test_new_document_only_embeds_its_chunks(self):
        self.sync(VOYAGER, [WIKI])
        texts = self.emb.texts
        report = self.sync(VOYAGER, [WIKI, HELIO])
        self.assertEqual(report.embedded, len(build_records(VOYAGER, [HELIO], LINKS, 1000, 200)))
        self.assertEqual(self.emb.texts - texts, report.embedded)

    def test_chunk_setting_change_rechunks_and_removes_stale(self):
        self.sync(VOYAGER, [WIKI])
        big = self.col.count()
        report = self.sync(VOYAGER, [WIKI], size=400, overlap=80)
        self.assertGreater(self.col.count(), big)
        self.assertEqual(self.col.count(), report.chunks)                       # 예전 설정 청크는 남지 않는다
        metas = self.col.get(include=["metadatas"])["metadatas"]
        self.assertEqual({(m["chunk_size"], m["chunk_overlap"]) for m in metas}, {(400, 80)})

    def test_other_items_untouched(self):
        self.sync(VOYAGER2, [HELIO])
        before = self.col.get(where={"item_id": "Q48470"}, include=[])["ids"]
        self.sync(VOYAGER, [WIKI])
        self.sync(VOYAGER, [NASA])                                               # 보이저 1호 문서 교체
        self.assertEqual(self.col.get(where={"item_id": "Q48470"}, include=[])["ids"], before)

    def test_empty_docs_rejected_without_deleting(self):
        self.sync(VOYAGER, [WIKI])
        count = self.col.count()
        with self.assertRaises(DocIndexError):
            self.sync(VOYAGER, [])
        self.assertEqual(self.col.count(), count)

    def test_embedding_mismatch_rejected(self):
        self.sync(VOYAGER, [WIKI])
        with self.assertRaises(chroma.EmbeddingMismatchError):
            chroma.open_collection(self.name, FakeEmbedding(model="fake-b"), self.db)


class IsolatedDocsTest(unittest.TestCase):
    def setUp(self):
        self.db = chromadb.EphemeralClient()
        self.name = f"d_{uuid.uuid4().hex[:10]}"
        self.emb = FakeEmbedding()
        self.col = chroma.open_collection(self.name, self.emb, self.db)

    def tearDown(self):
        for suffix in ("", chroma.STAGING_SUFFIX, chroma.BACKUP_SUFFIX):
            chroma.drop_collection(self.name + suffix, self.db)

    def sync(self, item, docs, missing=(), size=1000, overlap=200):
        return sync_item_docs(item, docs, LINKS, self.col, self.emb, size, overlap, missing)

    def snapshot(self, where=None):
        # 재구축은 컬렉션을 교체하므로 객체를 재사용하지 않고 이름으로 다시 연다
        got = self.db.get_collection(self.name).get(where=where, include=["documents", "metadatas"])
        return sorted(zip(got["ids"], got["documents"], [tuple(sorted(m.items())) for m in got["metadatas"]]))


# ── [P1] 1. 본문 없는 문서가 기존 청크를 지우지 않는다 ────────────────────────

class InvalidDocumentTest(IsolatedDocsTest):
    def setUp(self):
        super().setUp()
        self.sync(VOYAGER, [WIKI, NASA])
        self.before = self.snapshot()

    def test_blank_documents_rejected_and_chunks_preserved(self):
        for text in ("", "   \n\t ", "== 임무 과정 ==\n\n=== 목성 탐사 ===\n"):
            with self.subTest(text=repr(text)):
                with self.assertRaises(DocIndexError):
                    self.sync(VOYAGER, [doc("wiki:10350", "보이저 1호", text)])
                self.assertEqual(self.snapshot(), self.before)

    def test_mixed_input_keeps_invalid_docs_chunks(self):
        nasa_before = self.snapshot({"doc_id": "nssdca:1977-084A"})
        report = self.sync(VOYAGER, [WIKI, doc("nssdca:1977-084A", "Voyager 1 (NASA NSSDCA)", " ", "NASA")])
        self.assertEqual(report.invalid, ["nssdca:1977-084A"])
        self.assertFalse(report.complete)
        self.assertEqual(report.deleted, 0)
        self.assertEqual(self.snapshot({"doc_id": "nssdca:1977-084A"}), nasa_before)

    def test_valid_shrink_still_applied(self):
        shorter = doc("wiki:10350", "보이저 1호", "보이저 1호는 1977년에 발사된 탐사선이다. " * 5)
        report = self.sync(VOYAGER, [shorter, NASA])
        self.assertGreater(report.deleted, 0)
        self.assertTrue(report.complete)
        self.assertEqual(len(self.col.get(where={"doc_id": "wiki:10350"}, include=[])["ids"]), 1)

    def test_heading_only_detected(self):
        self.assertFalse(has_body(doc("wiki:1", "x", "== 가 ==\n=== 나 ===")))
        self.assertTrue(has_body(doc("wiki:1", "x", "== 가 ==\n짧은 본문")))


# ── [P1] 2. 캐시 누락을 연결 해제로 오인하지 않는다 ────────────────────────────

class _Wiki:
    def __init__(self, pages):
        self.pages = pages

    def search(self, query, limit):
        return []

    def fetch(self, title, max_chars):
        return self.pages.get(title)


class _Nasa:
    def __init__(self):
        self.down = False

    def fetch(self, cospar, max_chars):
        if self.down:
            raise requests.ConnectionError("모의 장애")
        return NASA


class MissingCacheTest(IsolatedDocsTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = CollectCache(Path(self.tmp.name))
        self.nasa = _Nasa()
        self.collector = Collector(cache=self.cache, llm=object(), wiki=_Wiki({"보이저 1호": WIKI}), nasa=self.nasa)
        item = {**VOYAGER, "wiki_title": "보이저 1호", "attrs": {"COSPAR ID": "1977-084A"}}
        self.collector.prefetch_own(item)
        self.index_linked()
        self.sync(VOYAGER2, [HELIO])
        self.nasa_chunks = self.snapshot({"doc_id": "nssdca:1977-084A"})
        self.other = self.snapshot({"item_id": "Q48470"})

    def tearDown(self):
        super().tearDown()
        self.tmp.cleanup()

    def index_linked(self):
        linked = self.collector.linked(VOYAGER["id"])
        return linked, sync_item_docs(VOYAGER, linked.docs, linked.links, self.col, self.emb, 1000, 200, linked.missing)

    def test_missing_cache_preserves_chunks_and_link(self):
        self.cache._doc_path("nssdca:1977-084A").unlink()
        self.nasa.down = True                                              # 다시 받기도 실패
        linked, report = self.index_linked()
        self.assertEqual(linked.missing, ["nssdca:1977-084A"])
        self.assertEqual(report.missing, ["nssdca:1977-084A"])
        self.assertFalse(report.complete)
        self.assertEqual(self.snapshot({"doc_id": "nssdca:1977-084A"}), self.nasa_chunks)
        self.assertIn("nssdca:1977-084A", self.cache.get_manifest(VOYAGER["id"])["docs"])   # 연결 유지
        self.assertEqual(self.snapshot({"item_id": "Q48470"}), self.other)

    def test_missing_cache_restored_from_link(self):
        self.cache._doc_path("nssdca:1977-084A").unlink()
        linked, report = self.index_linked()                               # 연결 정보로 다시 받는다
        self.assertEqual(linked.missing, [])
        self.assertTrue(report.complete)
        self.assertEqual(report.embedded, 0)                               # 같은 본문 — 재임베딩 없음
        self.assertEqual(self.snapshot({"doc_id": "nssdca:1977-084A"}), self.nasa_chunks)

    def test_explicit_unlink_deletes_chunks(self):
        self.assertTrue(self.collector.unlink(VOYAGER["id"], "nssdca:1977-084A"))
        _, report = self.index_linked()
        self.assertGreater(report.deleted, 0)
        self.assertEqual(self.col.get(where={"doc_id": "nssdca:1977-084A"}, include=[])["ids"], [])
        self.assertEqual(self.snapshot({"item_id": "Q48470"}), self.other)


# ── [P2] 3. 임베딩 모델이 바뀐 cosmos_docs를 안전하게 재구축한다 ──────────────

class DocRebuildTest(IsolatedDocsTest):
    def setUp(self):
        super().setUp()
        self.sync(VOYAGER, [WIKI, NASA, HELIO])
        self.sync(VOYAGER2, [HELIO])
        self.before = self.snapshot()
        self.targets = [(VOYAGER, [WIKI, NASA, HELIO], LINKS, []), (VOYAGER2, [HELIO], LINKS, [])]
        self.items_col = chroma.open_collection(f"{self.name}_items", self.emb, self.db)
        self.items_col.upsert(ids=["Q1"], embeddings=[[0.1] * 16], documents=["항목"], metadatas=[{"a": 1}])

    def tearDown(self):
        chroma.drop_collection(f"{self.name}_items", self.db)
        super().tearDown()

    def rebuild(self, emb, targets=None):
        return rebuild_docs(targets or self.targets, self.name, emb, 1000, 200, self.db)

    def test_mismatch_points_to_docs_rebuild(self):
        self.assertEqual(chroma.rebuild_hint("cosmos_docs"), chroma.DOCS_REBUILD)
        self.assertEqual(chroma.rebuild_hint("cosmos_docs__staging"), chroma.DOCS_REBUILD)
        self.assertEqual(chroma.rebuild_hint("cosmos_items"), chroma.ITEMS_REBUILD)
        name = "cosmos_docs"
        col = chroma.open_collection(name, self.emb, self.db)
        try:
            col.upsert(ids=["x"], embeddings=[[0.1] * 16], documents=["d"], metadatas=[{"item_id": "Q1"}])
            with self.assertRaises(chroma.EmbeddingMismatchError) as ctx:
                chroma.open_collection(name, FakeEmbedding(model="fake-b"), self.db)
            self.assertIn(chroma.DOCS_REBUILD, str(ctx.exception))
        finally:
            chroma.drop_collection(name, self.db)

    def test_targets_readable_without_opening_with_new_model(self):
        self.assertEqual(indexed_item_ids(self.name, self.db), ["Q48469", "Q48470"])

    def test_rebuild_with_new_model(self):
        for emb in (FakeEmbedding(model="fake-b"), FakeEmbedding(size=32)):
            with self.subTest(emb=(emb.model, emb.size)):
                with self.assertRaises(chroma.EmbeddingMismatchError):
                    chroma.open_collection(self.name, emb, self.db)
                self.rebuild(emb)
                col = self.db.get_collection(self.name)
                self.assertEqual(chroma.stored_identity(col), chroma.embedding_identity(emb))
                metas = col.get(include=["metadatas"])["metadatas"]
                nasa = next(m for m in metas if m["source_type"] == "NASA")
                wiki = next(m for m in metas if m["doc_id"] == "wiki:10350")
                self.assertEqual((nasa["source_url"], nasa["license"]), (NASA.url, NASA.license))
                self.assertEqual((wiki["permalink"], wiki["license"]), (WIKI.permalink, WIKI.license))
                self.assertEqual(sorted(i for i, _, _ in self.snapshot()), sorted(i for i, _, _ in self.before))
                names = {c.name for c in self.db.list_collections()}
                self.assertNotIn(chroma.staging_name(self.name), names)
                self.assertEqual(self.items_col.get(include=["metadatas"])["metadatas"], [{"a": 1}])

    def test_rebuild_embedding_failure_keeps_active(self):
        with self.assertRaises(RuntimeError):
            self.rebuild(FakeEmbedding(model="fake-b", fail_on_call=2))
        self.assertEqual(self.snapshot(), self.before)
        self.assertEqual(chroma.stored_identity(self.db.get_collection(self.name))["embedding_model"],
                         "FakeEmbedding:fake-a")
        self.assertNotIn(chroma.staging_name(self.name), {c.name for c in self.db.list_collections()})

    def test_rebuild_stops_on_missing_documents(self):
        targets = [(VOYAGER, [WIKI, HELIO], LINKS, ["nssdca:1977-084A"]), self.targets[1]]
        with self.assertRaises(DocIndexError):
            self.rebuild(FakeEmbedding(model="fake-b"), targets)
        self.assertEqual(self.snapshot(), self.before)


if __name__ == "__main__":
    unittest.main()
