"""검색 방식 비교 (F2014) — 같은 항목 · 질문 · 색인으로 유사도 검색과 MMR을 나란히.

답변은 만들지 않는다 (LLM 호출 없음). 질문 임베딩 1회만 쓴다 — 두 방식이 같은 질문 벡터로 검색한다.
Streamlit 비교 화면(app/streamlit_app.py)과 CLI(scripts/ask.py --compare)가 이 결과를 쓴다.

| status         | 뜻                                              |
|----------------|-------------------------------------------------|
| ok             | 두 방식 모두 결과가 있다                         |
| empty          | 이 항목의 문서 청크가 없거나 결과가 없다          |
| index_missing  | 문서 색인(cosmos_docs)이 없다                    |
| failed         | 검색 중 오류 — 한 방식이라도 실패하면 이유를 남긴다 |
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chromadb
from langchain_core.embeddings import Embeddings

from vasthorizon.config import RetrievalConfig, get_settings
from vasthorizon.rag.retrieval import SEARCH_OUTAGE_ERRORS
from vasthorizon.store import chroma
from vasthorizon.store.search import search

METHODS = ("similarity", "mmr")


@dataclass
class Hit:
    rank: int
    chunk_id: str
    title: str
    section: str
    source_type: str
    url: str
    text: str
    score: float | None             # 코사인 유사도 (MMR은 순서만 의미 — 재계산한 유사도를 함께 보여준다)


@dataclass
class CompareResult:
    item_id: str
    question: str
    settings: dict                  # top_k · fetch_k · lambda · 컬렉션
    status: str
    hits: dict[str, list[Hit]] = field(default_factory=dict)       # 방식 → 결과
    paths: dict[str, str] = field(default_factory=dict)            # 방식 → chroma · exact (검증된 검색 경로)
    chunks_in_scope: int = 0                                        # 이 항목의 문서 청크 수
    warnings: list[str] = field(default_factory=list)

    @property
    def overlap(self) -> set[str]:
        ids = [{h.chunk_id for h in self.hits.get(m, [])} for m in METHODS]
        return ids[0] & ids[1] if len(ids) == 2 else set()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def compare_search(item_id: str, question: str, embedding: Embeddings | None = None,
                   db: chromadb.ClientAPI | None = None, top_k: int | None = None, fetch_k: int | None = None,
                   lambda_mult: float | None = None) -> CompareResult:
    settings = get_settings()
    name = settings.collections.docs
    base: RetrievalConfig = settings.retrieval
    k = top_k or base.top_k_docs
    fk = max(fetch_k or base.mmr_fetch_k, k)
    lam = base.mmr_lambda if lambda_mult is None else lambda_mult
    result = CompareResult(item_id=item_id, question=question, status="ok",
                           settings={"top_k": k, "fetch_k": fk, "lambda": lam, "collection": name,
                                     "embedding": settings.llm.embedding_model})
    if chroma.collection_count(name, db) == 0:
        result.status = "index_missing"
        result.warnings.append("문서 색인이 없습니다. python -m scripts.index_docs --demo 로 시연 항목을 색인하세요.")
        return result

    embedding = embedding or chroma.default_embedding()
    where = {"item_id": item_id}
    try:
        with chroma.LOCK:
            collection = chroma.db_for(name, db).get_collection(name)
            scope = collection.get(where=where, include=["embeddings"])
            result.chunks_in_scope = len(scope["ids"])
            vectors = dict(zip(scope["ids"], scope["embeddings"]))
            query_vec = embedding.embed_query(question)
            for method in METHODS:
                outcome = search(name, question, embedding, db, k=k, where=where, search_type=method,
                                 fetch_k=fk, lambda_mult=lam, query_vector=query_vec)
                result.paths[method] = outcome.path
                result.hits[method] = [Hit(
                    rank=i, chunk_id=h.id, title=h.metadata.get("title", ""), section=h.metadata.get("section", ""),
                    source_type=h.metadata.get("source_type", ""), url=h.metadata.get("source_url", ""), text=h.text,
                    score=h.score if h.score is not None else
                    (round(_cosine(query_vec, list(vectors[h.id])), 4) if h.id in vectors else None),
                ) for i, h in enumerate(outcome.hits, 1)]
    except SEARCH_OUTAGE_ERRORS as e:
        result.status = "failed"
        result.warnings.append(f"검색 중 오류가 났습니다: {type(e).__name__}")
        return result
    if not result.chunks_in_scope or not any(result.hits.values()):
        result.status = "empty"
        result.warnings.append("이 항목의 문서 청크가 없습니다. 먼저 질문하거나 scripts.index_docs --item 으로 색인하세요.")
    return result
