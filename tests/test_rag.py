"""근거 검색 · 병합 · LangGraph · 답변 검증 · 장애 처리 테스트 (F2006 · F2007 · F2008 · F2014).

가짜 임베딩 · 가짜 LLM · 메모리 전용 Chroma를 쓴다. 외부 호출 · 토큰 사용 없음.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from unittest import mock

import chromadb
import chromadb.errors
import httpx
import openai

from tests.fakes import FakeChat, FakeEmbedding
from vasthorizon.collect.collector import CollectResult
from vasthorizon.config import get_settings
from vasthorizon.data.docs import Document
from vasthorizon.rag import retrieval
from vasthorizon.rag.citations import citation_issue, resolve_citations
from vasthorizon.rag.graph import REJECTED_ANSWER, build_graph, is_not_found
from vasthorizon.rag.pipeline import ask
from vasthorizon.rag.prompts import answer_messages
from vasthorizon.rag.retrieval import Evidence, IndexMissingError, retrieve_evidence
from vasthorizon.store import chroma
from vasthorizon.store.doc_index import sync_item_docs

ITEMS = get_settings().collections.items
DOCS = get_settings().collections.docs
VOYAGER = {"id": "Q48469", "name": "보이저 1호", "group": "human_made", "kind": "우주 탐사선", "attrs": {}}
PIONEER = {"id": "Q1", "name": "파이어니어 10호", "group": "human_made", "kind": "우주 탐사선", "attrs": {}}
SHARED = "태양권계면은 태양풍이 성간 매질과 만나 멈추는 경계다. 보이저 1호는 2012년에 이곳을 지났다."
NEW_DOC = None   # setUp에서 채운다


def doc(doc_id: str, title: str, text: str, source: str = "위키백과") -> Document:
    return Document(doc_id=doc_id, title=title, url=f"https://example.org/{doc_id}",
                    permalink=f"https://example.org/{doc_id}?oldid=1", text=text, source_type=source,
                    license="CC BY-SA 4.0", fetched_at="2026-10-21T00:00:00+00:00")


def ev(n: int, kind="외부 문서") -> Evidence:
    return Evidence(number=n, chunk_id=f"c{n}", kind=kind, source_type="위키백과", title=f"문서{n}",
                    section="", url=f"https://example.org/{n}", text=f"내용 {n}")


def connection_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(request=httpx.Request("POST", "https://gms.example/v1/embeddings"))


def OutageEmbedding(query_down: bool = False) -> FakeEmbedding:
    """같은 모델(식별 정보 동일)에 장애만 주입한다 — 문서 임베딩은 장애, 질의 임베딩은 선택."""
    emb = FakeEmbedding()
    emb.embed_documents = mock.Mock(side_effect=connection_error())
    if query_down:
        emb.embed_query = mock.Mock(side_effect=connection_error())
    return emb


class IsolatedRagTest(unittest.TestCase):
    """운영과 같은 구조 — 컬렉션마다 다른 저장소(임시 폴더의 영속 클라이언트)를 쓴다.

    chroma.client를 바꿔 끼워 실제 data/chroma는 건드리지 않는다. db=None으로 넘겨
    컬렉션 이름에 따라 저장소를 고르는 라우팅(chroma.db_for)까지 함께 검증한다.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)    # Windows 파일 잠금 대비
        self.stores: dict[str, chromadb.ClientAPI] = {}
        patcher = mock.patch.object(chroma, "client", side_effect=lambda store: self.stores.setdefault(
            store, chromadb.PersistentClient(path=f"{self.tmp.name}/{store}")))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.db = None
        self.emb = FakeEmbedding()
        items = chroma.open_collection(ITEMS, self.emb, self.db)
        texts = {"Q48469": "[인류의 발자취] 보이저 1호\n지금은 태양계를 벗어나는 궤도를 날고 있다.",
                 "Q1": "[인류의 발자취] 파이어니어 10호\n태양계 탈출 궤도"}
        items.upsert(ids=list(texts), documents=list(texts.values()),
                     embeddings=self.emb.embed_documents(list(texts.values())),
                     metadatas=[{"name": "보이저 1호", "source_url": "https://www.wikidata.org/wiki/Q48469"},
                                {"name": "파이어니어 10호", "source_url": "https://www.wikidata.org/wiki/Q1"}])
        docs_col = chroma.open_collection(DOCS, self.emb, self.db)
        voyager_docs = [
            doc("wiki:10350", "보이저 1호", "보이저 1호는 1977년에 발사되었다. " * 40),
            doc("wiki:1", "태양권계면", SHARED),
            doc("wiki:2", "태양권계면 (사본)", SHARED),                     # 같은 본문 — 중복 제거 대상
            doc("nssdca:1977-084A", "Voyager 1 (NASA NSSDCA)", "Voyager 1 crossed the heliopause. " * 20, "NASA"),
        ]
        sync_item_docs(VOYAGER, voyager_docs, {}, docs_col, self.emb, 300, 50)
        sync_item_docs(PIONEER, [doc("wiki:9", "파이어니어 10호", "파이어니어 10호는 1972년에 발사되었다. " * 20)],
                       {}, docs_col, self.emb, 300, 50)

    def tearDown(self):
        chroma.drop_collection(ITEMS, self.db)
        chroma.drop_collection(DOCS, self.db)

    def retrieve(self, question="보이저 1호는 태양계를 벗어났나?", **kw):
        return retrieve_evidence(VOYAGER, question, embedding=kw.pop("embedding", self.emb), db=self.db, **kw)


# ── F2006 근거 검색 · 병합 ─────────────────────────────────────────────────

class RetrievalTest(IsolatedRagTest):
    def test_item_metadata_always_first(self):
        evs = self.retrieve("전혀 관계없는 질문").evidences
        self.assertEqual((evs[0].number, evs[0].kind, evs[0].chunk_id), (1, "항목 메타데이터", "Q48469"))
        self.assertEqual([e.number for e in evs], list(range(1, len(evs) + 1)))

    def test_docs_scoped_to_item(self):
        evs = self.retrieve().evidences
        self.assertTrue(all(e.chunk_id.startswith("Q48469") for e in evs))
        self.assertNotIn("파이어니어 10호", {e.title for e in evs[1:]})

    def test_duplicates_removed(self):
        cfg = dataclasses.replace(get_settings().retrieval, top_k_docs=50)
        evs = self.retrieve(cfg=cfg).evidences
        bodies = [e.text.split("\n", 1)[1] for e in evs[1:]]
        self.assertEqual(len(bodies), len(set(bodies)))                    # 같은 본문은 한 번만
        self.assertEqual(sum(1 for e in evs if e.title.startswith("태양권계면")), 1)
        self.assertEqual(len({e.chunk_id for e in evs}), len(evs))

    def test_top_k_from_config(self):
        for k in (2, 4):
            cfg = dataclasses.replace(get_settings().retrieval, top_k_docs=k)
            self.assertLessEqual(len(self.retrieve(cfg=cfg).evidences) - 1, k)
        small = dataclasses.replace(get_settings().retrieval, top_k_docs=2)
        big = dataclasses.replace(get_settings().retrieval, top_k_docs=6)
        self.assertGreater(len(self.retrieve(cfg=big).evidences), len(self.retrieve(cfg=small).evidences))

    def test_source_kinds_distinguished(self):
        cfg = dataclasses.replace(get_settings().retrieval, top_k_docs=50)
        kinds = {(e.kind, e.source_type) for e in self.retrieve(cfg=cfg).evidences}
        self.assertIn(("항목 메타데이터", "항목 메타데이터"), kinds)
        self.assertIn(("외부 문서", "위키백과"), kinds)
        self.assertIn(("외부 문서", "NASA"), kinds)

    def test_mmr_switch(self):
        evs = self.retrieve(search_type="mmr").evidences
        self.assertEqual(evs[0].kind, "항목 메타데이터")
        self.assertTrue(all(e.score is None for e in evs[1:]))              # MMR 경로를 탔다
        self.assertTrue(all(e.chunk_id.startswith("Q48469") for e in evs))

    def test_missing_item_index_raises(self):
        chroma.drop_collection(ITEMS, self.db)
        with self.assertRaises(IndexMissingError):
            self.retrieve()

    def test_missing_item_chunk_raises(self):
        with self.assertRaises(IndexMissingError):
            retrieve_evidence({**VOYAGER, "id": "Q404"}, "질문", embedding=self.emb, db=self.db)

    def test_no_doc_index_still_answers_with_item(self):
        chroma.drop_collection(DOCS, self.db)
        found = self.retrieve()
        self.assertEqual(([e.kind for e in found.evidences], found.doc_search), (["항목 메타데이터"], "empty"))

    def test_collections_live_in_separate_stores(self):
        """cosmos_items · cosmos_docs는 서로 다른 저장소에 있다 (chroma.py '컬렉션별 저장소 분리')."""
        self.assertEqual(set(self.stores), {ITEMS, DOCS})
        self.assertEqual([c.name for c in self.stores[ITEMS].list_collections()], [ITEMS])
        self.assertEqual([c.name for c in self.stores[DOCS].list_collections()], [DOCS])

    def test_doc_search_runs_before_item_read(self):
        """로컬 Chroma 경쟁 조건 회피 — 다른 컬렉션을 읽은 직후 검색하지 않는다 (retrieval.py 설명 참고)."""
        order = []
        real_search, real_item = retrieval.search_docs, retrieval.item_evidence
        with mock.patch.object(retrieval, "search_docs", side_effect=lambda *a, **k: order.append("docs") or real_search(*a, **k)), \
                mock.patch.object(retrieval, "item_evidence", side_effect=lambda *a, **k: order.append("item") or real_item(*a, **k)):
            self.retrieve()
        self.assertEqual(order, ["docs", "item"])

    def test_search_outage_falls_back_to_item(self):
        found = self.retrieve(embedding=OutageEmbedding(query_down=True))
        self.assertEqual(found.doc_search, "failed")
        self.assertEqual([e.kind for e in found.evidences], ["항목 메타데이터"])
        self.assertIn("연결 오류", found.warnings[0])
        self.assertNotIn("gms.example", found.warnings[0])                  # 내부 주소를 노출하지 않는다

    def test_chroma_internal_error_falls_back_to_item(self):
        with mock.patch.object(retrieval, "search_docs", side_effect=chromadb.errors.InternalError("Error finding id")):
            found = self.retrieve()
        self.assertEqual((found.doc_search, len(found.evidences)), ("failed", 1))
        self.assertIn("검색 저장소 내부 오류", found.warnings[0])

    def test_embedding_mismatch_not_swallowed(self):
        with self.assertRaises(chroma.EmbeddingMismatchError):
            self.retrieve(embedding=FakeEmbedding(model="fake-b"))


# ── F2008 인용 해석 · 답변 검증 ─────────────────────────────────────────────

class CitationTest(unittest.TestCase):
    def test_cited_kept_with_original_numbers(self):
        result = resolve_citations("2012년에 지났다 [근거 3]. 발사는 1977년 [근거 1].", [ev(1), ev(2), ev(3)])
        self.assertEqual([e.number for e in result.cited], [1, 3])
        self.assertIsNone(citation_issue(result, not_found=False))

    def test_invalid_numbers_are_not_hidden(self):
        result = resolve_citations("Unsupported claim [근거 99].", [ev(1)])
        self.assertEqual((result.cited, result.invalid_numbers), ([], [99]))
        self.assertIn("[근거 99]", result.text)                            # 지워서 근거 부재를 숨기지 않는다
        self.assertIsNotNone(citation_issue(result, not_found=False))

    def test_mixed_valid_and_invalid_is_violation(self):
        result = resolve_citations("사실 A [근거 1]. 지어낸 사실 B [근거 7].", [ev(1), ev(2)])
        self.assertTrue(result.has_citations)
        self.assertIn("7", citation_issue(result, not_found=False))

    def test_uncited_factual_answer_is_violation(self):
        result = resolve_citations("보이저 1호는 2012년에 태양권계면을 지났습니다.", [ev(1)])
        self.assertIsNotNone(citation_issue(result, not_found=False))

    def test_not_found_answer_needs_no_citation(self):
        text = "제공된 문서에서는 확인되지 않습니다."
        result = resolve_citations(text, [ev(1)])
        self.assertTrue(is_not_found(text))
        self.assertIsNone(citation_issue(result, not_found=True))

    def test_comma_list_split(self):
        result = resolve_citations("사실 [근거 1, 2].", [ev(1), ev(2)])
        self.assertIn("[근거 1][근거 2]", result.text)
        self.assertEqual(len(result.cited), 2)

    def test_repeated_citation_collapsed(self):
        result = resolve_citations("사실 [근거 1] [근거 2]  [근거 2].", [ev(1), ev(2)])
        self.assertEqual(result.text, "사실 [근거 1] [근거 2].")

    def test_not_found_detection(self):
        self.assertTrue(is_not_found("제공된 문서에서는 개발비가 정확히 얼마인지 확인되지 않습니다. 다만 …"))
        self.assertFalse(is_not_found("보이저 1호는 2012년에 태양권계면을 지났습니다 [근거 2]."))


# ── F2007 LangGraph · 답변 생성 · 재생성 정책 ─────────────────────────────────

class GraphTest(IsolatedRagTest):
    def run_graph(self, *replies):
        llm = FakeChat(*replies)
        state = build_graph(llm, self.emb, self.db).invoke(
            {"item": VOYAGER, "question": "벗어났나?", "history": [], "warnings": []})
        return state, llm

    def test_graph_has_retrieve_and_generate(self):
        nodes = set(build_graph(FakeChat(), self.emb, self.db).get_graph().nodes)
        self.assertTrue({"retrieve", "generate"} <= nodes)

    def test_valid_answer_returned(self):
        state, llm = self.run_graph("태양계를 벗어나는 궤도에 있습니다 [근거 1].")
        prompt = llm.received[0][-1].content
        for e in state["evidences"]:
            self.assertIn(f"[근거 {e.number}] ({e.kind} · {e.source_type})", prompt)
        self.assertEqual((state["status"], state["attempts"], [e.number for e in state["cited"]]), ("cited", 1, [1]))

    def test_all_invalid_then_regenerated(self):
        state, llm = self.run_graph("Unsupported claim [근거 99].", "궤도를 벗어나고 있습니다 [근거 1].")
        self.assertEqual((state["status"], state["attempts"]), ("cited", 2))
        self.assertIn("99", llm.received[1][-1].content)                   # 위반 내용을 알려 주고 다시 묻는다
        self.assertNotIn("Unsupported", state["answer"])

    def test_mixed_invalid_then_regenerated(self):
        state, _ = self.run_graph("사실 [근거 1]. 지어낸 사실 [근거 42].", "사실 [근거 1].")
        self.assertEqual((state["status"], len(state["issues"])), ("cited", 1))

    def test_uncited_then_regenerated(self):
        state, _ = self.run_graph("보이저 1호는 2012년에 태양권계면을 지났습니다.", "궤도를 벗어나는 중입니다 [근거 1].")
        self.assertEqual((state["status"], state["attempts"]), ("cited", 2))

    def test_not_found_accepted_without_citation(self):
        state, llm = self.run_graph("제공된 문서에서는 확인되지 않습니다.")
        self.assertEqual((state["status"], state["cited"], len(llm.received)), ("not_found", [], 1))

    def test_regeneration_failure_never_exposes_unsupported_text(self):
        state, llm = self.run_graph("근거 없는 주장 [근거 99].", "또 근거 없는 주장.")
        self.assertEqual((state["status"], state["answer"], state["cited"]), ("rejected", REJECTED_ANSWER, []))
        self.assertEqual(len(llm.received), 2)                              # 재생성은 1회까지

    def test_prompt_rules_and_history(self):
        history = [{"role": "user", "content": "보이저 1호는 언제 발사됐어?"},
                   {"role": "assistant", "content": "1977년입니다 [근거 1]."}]
        messages = answer_messages(VOYAGER, "그럼 지금은 어디야?", [ev(1)], history)
        system = messages[0].content
        self.assertIn("근거]에 적힌 내용만", system)
        self.assertIn("제공된 문서에서는 확인되지 않습니다.", system)
        self.assertEqual([m.content for m in messages[1:3]], [h["content"] for h in history])


# ── 질의 파이프라인 — 단계 장애 처리 ────────────────────────────────────────

class StubCollector:
    def __init__(self, docs):
        self.docs = docs

    def collect(self, item, question, progress):
        return CollectResult(item_id=item["id"], question=question, docs=self.docs,
                             links={d.doc_id: {"role": "관련 문서"} for d in self.docs})


class StubIndex:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def ensure(self, item, docs, links, missing):
        if self.error:
            raise self.error
        from vasthorizon.store.doc_index import DocIndexReport
        return DocIndexReport(item_id=item["id"], docs=len(docs))


class PipelineTest(IsolatedRagTest):
    def ask(self, index: StubIndex, graph_llm: FakeChat, embedding=None):
        new_doc = doc("wiki:77", "새 문서", "새로 수집한 문서. " * 30)
        graph = build_graph(graph_llm, embedding or self.emb, self.db)
        return ask(VOYAGER, "벗어났나?", collector=StubCollector([new_doc]), doc_index=index, graph=graph)

    def test_normal_path(self):
        result = self.ask(StubIndex(), FakeChat("벗어나는 중입니다 [근거 1]."))
        self.assertEqual((result.status, result.stages["index"].status), ("cited", "ok"))
        self.assertEqual(result.warnings, [])

    def test_index_outage_uses_existing_index(self):
        result = self.ask(StubIndex(connection_error()), FakeChat("벗어나는 중입니다 [근거 2]."))
        self.assertEqual(result.stages["index"].status, "failed")
        self.assertGreater(len(result.evidences), 1)                         # 기존 문서 색인 근거 사용
        self.assertEqual(result.status, "cited")
        self.assertIn("임베딩 API 연결 오류", result.warnings[0])
        self.assertNotIn("gms.example", " ".join(result.warnings))

    def test_index_outage_with_item_only(self):
        chroma.drop_collection(DOCS, self.db)
        result = self.ask(StubIndex(connection_error()), FakeChat("벗어나는 궤도입니다 [근거 1]."))
        self.assertEqual([e.kind for e in result.evidences], ["항목 메타데이터"])
        self.assertEqual(result.status, "cited")

    def test_full_embedding_outage_still_answers_or_flags(self):
        result = self.ask(StubIndex(connection_error()), FakeChat("제공된 문서에서는 확인되지 않습니다."),
                          embedding=OutageEmbedding(query_down=True))
        self.assertEqual((result.stages["index"].status, result.stages["retrieve"].status), ("failed", "failed"))
        self.assertEqual(result.status, "not_found")
        self.assertEqual(len(result.warnings), 2)

    def test_embedding_mismatch_stops(self):
        graph_llm = FakeChat()                                                # 호출되면 실패한다
        with self.assertRaises(chroma.EmbeddingMismatchError):
            self.ask(StubIndex(chroma.EmbeddingMismatchError("불일치")), graph_llm)
        self.assertEqual(graph_llm.received, [])

    def test_rejected_answer_flagged(self):
        result = self.ask(StubIndex(), FakeChat("주장 [근거 99].", "주장 [근거 98]."))
        self.assertEqual((result.status, result.answer, result.has_citations), ("rejected", REJECTED_ANSWER, False))
        self.assertEqual(result.stages["answer"].status, "failed")


if __name__ == "__main__":
    unittest.main()
