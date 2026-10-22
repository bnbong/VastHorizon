"""검증된 벡터 검색 — Chroma 유사도 · MMR 검색 + 결과 교차 검증.

배경 (로컬 Chroma 1.5.9에서 관찰)
- 다른 컬렉션을 다룬 직후의 HNSW 검색(query)이 간헐적으로 InternalError("Error finding id")를 내거나,
  오류 없이 결과를 덜(또는 0건) 돌려줬다. 같은 스레드의 순차 호출에서도 생긴다 (약 0.1~2%).
- 메타데이터 경로(get)는 같은 조건에서 틀린 적이 없었다.
- HNSW batch_size를 바꾸거나 같은 컬렉션을 미리 읽어 두는 것으로는 사라지지 않았다.

정책 — 재시도로 덮지 않고, 다른 경로로 검증한다
1. 질의 임베딩은 한 번만 만든다.
2. Chroma 검색(유사도 · MMR)을 먼저 한다 — Vector DB 의미 검색이 기본 경로다.
3. 같은 조건(where)의 레코드 수를 메타데이터 경로로 센다. 기대 개수 = min(k, 레코드 수).
4. 검색이 내부 오류를 내거나 기대 개수보다 적게 돌려주면, 그 범위의 벡터를 get으로 읽어
   정확(전수) 비교로 다시 계산하고 경고 로그를 남긴다. 범위는 항목 하나의 청크(수십 건) ·
   항목 카탈로그(수백 건) 수준이라 비용이 작고, 결과는 근사가 아니라 정확하다.
점수는 코사인 유사도(= 1 − 코사인 거리)로 두 경로가 같다. MMR은 점수를 돌려주지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import chromadb
import chromadb.errors
import numpy as np
from langchain_chroma.vectorstores import maximal_marginal_relevance
from langchain_core.embeddings import Embeddings

from vasthorizon.store import chroma

log = logging.getLogger(__name__)


@dataclass
class Hit:
    id: str
    text: str
    metadata: dict
    score: float | None = None          # 코사인 유사도 (MMR은 None)


@dataclass
class SearchOutcome:
    hits: list[Hit]
    path: str                           # chroma · exact(교차 검증 실패로 정확 비교) · empty
    expected: int = 0


def _exact(collection, query_vec: np.ndarray, where: dict | None, k: int, search_type: str,
           fetch_k: int, lambda_mult: float) -> list[Hit]:
    data = collection.get(where=where, include=["embeddings", "documents", "metadatas"])
    if not data["ids"]:
        return []
    vectors = np.asarray(data["embeddings"], dtype=float)
    norms = np.linalg.norm(vectors, axis=1) * np.linalg.norm(query_vec)
    sims = vectors @ query_vec / np.where(norms == 0, 1, norms)
    order = list(np.argsort(-sims))
    if search_type == "mmr":
        pool = order[:fetch_k]
        picked = [pool[i] for i in maximal_marginal_relevance(query_vec, [vectors[j] for j in pool], lambda_mult, k)]
        return [Hit(data["ids"][i], data["documents"][i], data["metadatas"][i]) for i in picked]
    return [Hit(data["ids"][i], data["documents"][i], data["metadatas"][i], float(sims[i])) for i in order[:k]]


def search(name: str, query: str, embedding: Embeddings, db: chromadb.ClientAPI | None, k: int,
           where: dict | None = None, search_type: str = "similarity", fetch_k: int = 20,
           lambda_mult: float = 0.5, query_vector: list[float] | None = None) -> SearchOutcome:
    """검증된 검색. 컬렉션이 없거나 비면 path='empty'. 임베딩 불일치는 그대로 올린다.
    query_vector를 넘기면 질문을 다시 임베딩하지 않는다 (검색 방식 비교 — 같은 질문 벡터로)."""
    if chroma.collection_count(name, db) == 0:
        return SearchOutcome(hits=[], path="empty")
    db = chroma.db_for(name, db)
    store = chroma.vector_store(name, embedding, db)            # 임베딩 호환성 확인
    collection = db.get_collection(name)
    available = len(collection.get(where=where, include=[])["ids"]) if where else collection.count()
    expected = min(k, available)
    if expected == 0:
        return SearchOutcome(hits=[], path="empty")

    query_vec = query_vector if query_vector is not None else embedding.embed_query(query)
    try:
        if search_type == "mmr":
            docs = store.max_marginal_relevance_search_by_vector(
                query_vec, k=k, fetch_k=fetch_k, lambda_mult=lambda_mult, filter=where)
            hits = [Hit(d.id, d.page_content, d.metadata) for d in docs]
        else:
            pairs = store.similarity_search_by_vector_with_relevance_scores(query_vec, k=k, filter=where)
            hits = [Hit(d.id, d.page_content, d.metadata, 1.0 - distance) for d, distance in pairs]
        problem = None if len(hits) >= expected else f"결과 {len(hits)}건 < 기대 {expected}건"
    except chromadb.errors.InternalError as e:
        hits, problem = [], f"InternalError: {e}"

    if problem is None:
        return SearchOutcome(hits=hits, path="chroma", expected=expected)
    log.warning("Chroma 검색 결과 검증 실패(%s, 컬렉션 %s) — 정확 비교로 다시 계산합니다.", problem, name)
    exact = _exact(collection, np.asarray(query_vec, dtype=float), where, k, search_type, fetch_k, lambda_mult)
    return SearchOutcome(hits=exact, path="exact", expected=expected)
