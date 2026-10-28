"""cosmos_items 색인 · 재구축 · 임베딩 호환성 회귀 테스트.

가짜 임베딩과 메모리 전용 Chroma(테스트마다 고유한 컬렉션 이름)를 쓴다.
외부 API 호출 · 토큰 사용이 없고, 실제 data/chroma 색인은 건드리지 않는다.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import chromadb

from scripts import index_items as index_cli
from tests.fakes import FakeEmbedding
from vasthorizon.data import catalog
from vasthorizon.data.items.common import LY_KM
from vasthorizon.llm import MissingApiKeyError
from vasthorizon.store import chroma, item_index
from vasthorizon.store.item_index import IndexingError, rebuild_items, sync_items
from vasthorizon.store.search import search

REF_YEAR = 2026


def dist(km: float) -> dict:
    return {"km": km, "ly": km / LY_KM, "basis": "wikidata", "reference": "지구에서 천체까지",
            "approximate": False, "method": None, "km_min": None, "km_max": None, "n_values": 1}


def item(qid: str, name: str, group: str = "messier", **kw) -> dict:
    data = {"id": qid, "group": group, "name": name, "wiki_title": name, "name_en": None, "kind": "산개 성단",
            "distance": None, "ra_deg": 56.75, "dec_deg": 24.1, "attrs": {},
            "sources": [{"name": "Wikidata", "url": f"https://www.wikidata.org/wiki/{qid}"}]}
    data.update(kw)
    return data


def valid_items(n: int = 120) -> list[dict]:
    """카탈로그 검증을 통과하는 항목 n개 (카탈로그 그룹마다)."""
    groups = catalog.GROUP_KEYS
    return [item(f"Q{i + 1}", f"항목{i}", group=groups[i % len(groups)], distance=dist((i + 1) * LY_KM))
            for i in range(n)]


class IsolatedChromaTest(unittest.TestCase):
    def setUp(self):
        self.db = chromadb.EphemeralClient()
        self.name = f"t_{uuid.uuid4().hex[:10]}"

    def tearDown(self):
        for suffix in ("", chroma.STAGING_SUFFIX, chroma.BACKUP_SUFFIX):
            chroma.drop_collection(self.name + suffix, self.db)

    def open(self, emb: FakeEmbedding):
        return chroma.open_collection(self.name, emb, self.db)

    def sync(self, items: list[dict], emb: FakeEmbedding):
        return sync_items(items, self.open(emb), emb, REF_YEAR)

    def stored(self, qid: str) -> dict:
        return self.db.get_collection(self.name).get(ids=[qid], include=["metadatas"])["metadatas"][0]


# ── [P2] 3. 텍스트 변경과 메타데이터 변경을 따로 반영한다 ─────────────────────

class IncrementalSyncTest(IsolatedChromaTest):
    def setUp(self):
        super().setUp()
        self.items = [item(f"Q{i}", f"항목{i}", distance=dist((i + 1) * LY_KM)) for i in range(5)]

    def test_identical_rerun_skips_embedding(self):
        emb = FakeEmbedding()
        first = self.sync(self.items, emb)
        self.assertEqual((len(first.embedded), first.indexed), (5, 5))
        calls = emb.calls
        second = self.sync(self.items, emb)
        self.assertEqual((len(second.embedded), len(second.meta_updated), second.unchanged), (0, 0, 5))
        self.assertEqual(emb.calls, calls)
        self.assertEqual(chroma.collection_count(self.name, self.db), 5)

    def test_metadata_only_change_updates_without_embedding(self):
        emb = FakeEmbedding()
        self.sync(self.items, emb)
        calls = emb.calls
        changed = [dict(it) for it in self.items]
        changed[0] = {**changed[0], "ra_deg": 20.0, "wiki_title": "새 제목",
                      "sources": [{"name": "Wikidata", "url": "https://example.org/new"}]}
        report = self.sync(changed, emb)
        self.assertEqual((report.embedded, report.meta_updated), ([], ["Q0"]))
        self.assertEqual(emb.calls, calls)                    # 임베딩 호출 없음
        meta = self.stored("Q0")
        self.assertEqual((meta["ra_deg"], meta["wiki_title"], meta["source_url"]),
                         (20.0, "새 제목", "https://example.org/new"))

    def test_removed_fields_do_not_linger(self):
        emb = FakeEmbedding()
        self.sync(self.items, emb)
        changed = [dict(it) for it in self.items]
        changed[0] = {**changed[0], "ra_deg": None, "dec_deg": None}       # 메타데이터만 제거
        changed[1] = {**changed[1], "distance": None}                      # 텍스트도 바뀜
        report = self.sync(changed, emb)
        self.assertEqual(report.meta_updated, ["Q0"])
        self.assertEqual(report.embedded, ["Q1"])
        self.assertNotIn("ra_deg", self.stored("Q0"))
        self.assertNotIn("dec_deg", self.stored("Q0"))
        for key in ("distance_km", "distance_ly", "light_departure_year"):
            self.assertNotIn(key, self.stored("Q1"))

    def test_text_change_reembeds(self):
        emb = FakeEmbedding()
        self.sync(self.items, emb)
        changed = [dict(it) for it in self.items]
        changed[0] = {**changed[0], "kind": "구상 성단"}
        report = self.sync(changed, emb)
        self.assertEqual((report.embedded, report.meta_updated), (["Q0"], []))

    def test_chunk_id_is_item_id(self):
        self.sync(self.items, FakeEmbedding())
        got = self.db.get_collection(self.name).get(ids=["Q2"], include=["metadatas", "documents"])
        self.assertEqual(got["metadatas"][0]["item_id"], "Q2")
        self.assertIn("[메시에 천체] 항목2", got["documents"][0])

    def test_missing_collection_counts_zero(self):
        self.assertEqual(chroma.collection_count("does_not_exist", self.db), 0)


# ── [P2] 4. 임베딩 모델 · 차원이 다르면 멈춘다 ────────────────────────────────

class EmbeddingIdentityTest(IsolatedChromaTest):
    def setUp(self):
        super().setUp()
        self.items = [item(f"Q{i}", f"항목{i}") for i in range(3)]
        self.sync(self.items, FakeEmbedding(size=16, model="fake-a"))

    def test_same_model_rerun_ok(self):
        report = self.sync(self.items, FakeEmbedding(size=16, model="fake-a"))
        self.assertEqual(report.unchanged, 3)

    def test_different_dimension_rejected(self):
        with self.assertRaises(chroma.EmbeddingMismatchError):
            self.open(FakeEmbedding(size=32, model="fake-a"))

    def test_same_dimension_different_model_rejected(self):
        with self.assertRaises(chroma.EmbeddingMismatchError):
            self.open(FakeEmbedding(size=16, model="fake-b"))

    def test_search_side_also_checks(self):
        with self.assertRaises(chroma.EmbeddingMismatchError):
            chroma.vector_store(self.name, FakeEmbedding(size=16, model="fake-b"), db=self.db)
        store = chroma.vector_store(self.name, FakeEmbedding(size=16, model="fake-a"), db=self.db)
        self.assertEqual(len(store.similarity_search("항목", k=2)), 2)

    def test_legacy_collection_without_identity_rejected(self):
        legacy = f"{self.name}_legacy"
        self.db.create_collection(legacy).upsert(ids=["Q1"], embeddings=[[0.1] * 16], documents=["d"])
        try:
            with self.assertRaises(chroma.EmbeddingMismatchError):
                chroma.open_collection(legacy, FakeEmbedding(size=16), self.db)
        finally:
            chroma.drop_collection(legacy, self.db)

    def test_dimension_recorded_after_first_embedding_when_unknown(self):
        name = f"{self.name}_dim"
        emb = FakeEmbedding(size=None, model="openai-like", vector_len=8)   # OpenAI처럼 차원을 미리 모름
        try:
            sync_items(self.items, chroma.open_collection(name, emb, self.db), emb, REF_YEAR)
            self.assertEqual(self.db.get_collection(name).metadata["embedding_dim"], 8)
            stale = FakeEmbedding(size=None, model="openai-like", vector_len=12)
            changed = [{**self.items[0], "kind": "바뀐 종류"}] + self.items[1:]
            with self.assertRaises(chroma.EmbeddingMismatchError):     # 쓰기 전에 멈춘다
                sync_items(changed, chroma.open_collection(name, stale, self.db), stale, REF_YEAR)
            self.assertNotIn("바뀐 종류", self.db.get_collection(name).get(ids=["Q0"])["documents"][0])
        finally:
            chroma.drop_collection(name, self.db)


# ── [P2] 5. 빈 · 잘못된 입력이 기존 색인을 지우지 않는다 ─────────────────────

class InputGuardTest(IsolatedChromaTest):
    def setUp(self):
        super().setUp()
        self.items = [item(f"Q{i}", f"항목{i}") for i in range(4)]
        self.emb = FakeEmbedding()
        self.sync(self.items, self.emb)

    def test_empty_input_rejected_and_index_kept(self):
        with self.assertRaises(IndexingError):
            self.sync([], self.emb)
        self.assertEqual(chroma.collection_count(self.name, self.db), 4)

    def test_duplicate_qid_rejected_before_change(self):
        with self.assertRaises(IndexingError):
            self.sync(self.items + [item("Q0", "중복")], self.emb)
        self.assertEqual(self.stored("Q0")["name"], "항목0")

    def test_removed_item_only_deleted(self):
        report = self.sync(self.items[:3], self.emb)
        self.assertEqual(report.deleted, ["Q3"])
        self.assertEqual(chroma.collection_count(self.name, self.db), 3)


# ── [P1] 2. 재구축이 실패해도 기존 컬렉션을 보존한다 ─────────────────────────

class RebuildTest(IsolatedChromaTest):
    def setUp(self):
        super().setUp()
        self.items = [item(f"Q{i}", f"항목{i}") for i in range(5)]
        self.sync(self.items, FakeEmbedding())
        self.before = sorted(self.db.get_collection(self.name).get(include=[])["ids"])

    def assert_active_intact(self):
        names = {c.name for c in self.db.list_collections()}
        self.assertIn(self.name, names)
        self.assertNotIn(chroma.staging_name(self.name), names)
        self.assertEqual(sorted(self.db.get_collection(self.name).get(include=[])["ids"]), self.before)
        # 계속 조회할 수 있다 — 서비스가 쓰는 검증된 검색으로 확인 (store/search.py)
        self.assertTrue(search(self.name, "항목", FakeEmbedding(), self.db, k=1).hits)

    def test_first_embedding_failure_keeps_active(self):
        with self.assertRaises(RuntimeError):
            rebuild_items(self.items, self.name, FakeEmbedding(fail_on_call=1), REF_YEAR, self.db)
        self.assert_active_intact()

    def test_mid_batch_failure_keeps_active(self):
        with mock.patch.object(item_index, "BATCH_SIZE", 2):
            with self.assertRaises(RuntimeError):
                rebuild_items(self.items, self.name, FakeEmbedding(fail_on_call=2), REF_YEAR, self.db)
        self.assert_active_intact()

    def test_swap_failure_restores_active(self):
        real_get = self.db.get_collection

        def flaky_get(name, *a, **kw):
            col = real_get(name, *a, **kw)
            if name == chroma.staging_name(self.name):
                col.modify = mock.Mock(side_effect=RuntimeError("이름 변경 실패 (모의)"))
            return col

        with mock.patch.object(self.db, "get_collection", side_effect=flaky_get):
            with self.assertRaises(RuntimeError):
                rebuild_items(self.items[:2], self.name, FakeEmbedding(), REF_YEAR, self.db)
        names = {c.name for c in self.db.list_collections()}
        self.assertIn(self.name, names)
        self.assertNotIn(self.name + chroma.BACKUP_SUFFIX, names)
        self.assertEqual(sorted(self.db.get_collection(self.name).get(include=[])["ids"]), self.before)

    def test_successful_rebuild_swaps_and_cleans_up(self):
        new_items = self.items[:3] + [item("Q99", "새 항목")]
        report = rebuild_items(new_items, self.name, FakeEmbedding(size=16, model="fake-b"), REF_YEAR, self.db)
        self.assertEqual(report.indexed, 4)
        names = {c.name for c in self.db.list_collections()}
        self.assertNotIn(chroma.staging_name(self.name), names)
        self.assertNotIn(self.name + chroma.BACKUP_SUFFIX, names)
        col = self.db.get_collection(self.name)
        self.assertEqual(sorted(col.get(include=[])["ids"]), ["Q0", "Q1", "Q2", "Q99"])
        self.assertEqual(col.metadata["embedding_model"], "FakeEmbedding:fake-b")   # 모델 교체도 재구축으로

    def test_legacy_collection_rebuilt(self):
        legacy = f"{self.name}_legacy"
        self.db.create_collection(legacy).upsert(ids=["Q1"], embeddings=[[0.1] * 16], documents=["d"])
        try:
            rebuild_items(self.items, legacy, FakeEmbedding(), REF_YEAR, self.db)
            self.assertEqual(self.db.get_collection(legacy).metadata["embedding_model"], "FakeEmbedding:fake-a")
        finally:
            for suffix in ("", chroma.STAGING_SUFFIX, chroma.BACKUP_SUFFIX):
                chroma.drop_collection(legacy + suffix, self.db)


# ── CLI — 컬렉션을 바꾸기 전에 카탈로그 · 키를 확인한다 ──────────────────────

class CliGuardTest(IsolatedChromaTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "items.json"
        catalog.save_items(valid_items(), {"collected_at": "2026-10-21"}, self.path)
        for p in (mock.patch.object(catalog, "items_path", return_value=self.path),
                  mock.patch.object(index_cli, "get_settings",
                                    return_value=mock.Mock(collections=mock.Mock(items=self.name)))):
            p.start()
            self.addCleanup(p.stop)
        self.assertEqual(self.run_cli([], embedding=FakeEmbedding()), 0)
        self.count = chroma.collection_count(self.name, self.db)

    def tearDown(self):
        super().tearDown()
        self.tmp.cleanup()

    def run_cli(self, argv, embedding=None) -> int:
        with redirect_stdout(io.StringIO()):
            return index_cli.main(argv, embedding=embedding, db=self.db)

    def write_catalog(self, items: list[dict]) -> None:
        self.path.write_text(json.dumps({"meta": {"collected_at": "2026-10-21"}, "items": items}), encoding="utf-8")

    def test_rebuild_without_key_keeps_collection(self):
        with mock.patch.object(chroma, "default_embedding", side_effect=MissingApiKeyError()):
            self.assertEqual(self.run_cli(["--rebuild"]), 1)
        self.assertEqual(chroma.collection_count(self.name, self.db), self.count)

    def test_empty_catalog_keeps_collection(self):
        self.write_catalog([])
        self.assertEqual(self.run_cli([], embedding=FakeEmbedding()), 1)
        self.assertEqual(chroma.collection_count(self.name, self.db), self.count)

    def test_duplicate_qid_catalog_keeps_collection(self):
        items = valid_items()
        items[1]["id"] = items[0]["id"]
        self.write_catalog(items)
        self.assertEqual(self.run_cli(["--rebuild"], embedding=FakeEmbedding()), 1)
        self.assertEqual(chroma.collection_count(self.name, self.db), self.count)

    def test_model_change_requires_rebuild(self):
        self.assertEqual(self.run_cli([], embedding=FakeEmbedding(model="fake-b")), 1)
        self.assertEqual(self.run_cli(["--rebuild"], embedding=FakeEmbedding(model="fake-b")), 0)


if __name__ == "__main__":
    unittest.main()
