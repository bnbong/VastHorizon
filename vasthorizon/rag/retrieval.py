"""근거 검색 · 병합 (F2006 · F2014).

1. 외부 문서 청크는 그 항목 범위(item_id 필터)에서 질문과의 의미 유사도로 검색한다.
2. 선택한 항목의 메타데이터 청크는 검색 없이 ID로 가져와 항상 근거 1번으로 넣는다.
   검색 방식은 설정으로 바꾼다 — similarity(유사도) · mmr(다양성, fetch_k개 후보 중 top_k개)
3. 두 컬렉션의 결과를 병합하고 중복을 지운다 — 같은 청크 ID, 그리고 본문이 같은 청크
   (같은 문단이 여러 문서 · 겹침 구간에 반복되는 경우)
4. 근거 번호를 1부터 붙인다. 답변의 [근거 N]과 화면 근거 목록이 이 번호로 이어진다.

컬렉션은 호출마다 이름으로 연다 — 재구축으로 컬렉션이 교체돼도 오래된 객체를 쓰지 않게.

검색 순서 — 외부 문서 검색을 항목 청크 조회보다 먼저 한다
  로컬 Chroma(1.5.9)에서 방금 쓴 컬렉션을 검색하기 직전에 다른 컬렉션을 읽으면
  약 1~2% 확률로 InternalError("Error finding id")가 났다 (메모리 · 영속 클라이언트 모두).
  같은 조건에서 순서만 바꾸면 각 500회 중 0회였다. 재시도가 아니라 순서로 피한다.
  그래도 검색이 실패하면 항목 메타데이터만으로 진행하고 경고를 남긴다.

장애 처리
  임베딩 API 일시 장애 · Chroma 내부 오류 → 문서 검색 실패로 기록, 항목 근거로 진행
  임베딩 모델 불일치 · 항목 색인 없음     → 그대로 올린다 (호환되지 않는 벡터로 검색하지 않는다)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field

import chromadb
import chromadb.errors
from langchain_core.embeddings import Embeddings

from vasthorizon.config import RetrievalConfig, get_settings
from vasthorizon.data.item_text import SOURCE_TYPE as ITEM_SOURCE
from vasthorizon.llm import TRANSIENT_API_ERRORS, describe_api_error
from vasthorizon.store import chroma

SEARCH_OUTAGE_ERRORS = (*TRANSIENT_API_ERRORS, chromadb.errors.InternalError)

KIND_ITEM = "항목 메타데이터"
KIND_DOC = "외부 문서"


class IndexMissingError(RuntimeError):
    """색인이 없거나 선택한 항목의 메타데이터 청크가 없을 때. 화면에서 색인 안내로 바꾼다. (F2012)"""


@dataclass
class Evidence:
    number: int                 # 근거 번호 — 답변의 [근거 N]
    chunk_id: str
    kind: str                   # 항목 메타데이터 · 외부 문서 (F2007 출처 유형)
    source_type: str            # 항목 메타데이터 · 위키백과 · NASA (F2016 출처 종류)
    title: str
    section: str
    url: str                    # 원문 출처
    text: str
    score: float | None = None

    def label(self) -> str:
        where = f" > {self.section}" if self.section else ""
        return f"[근거 {self.number}] {self.title}{where} · {self.source_type}"

    def to_dict(self) -> dict:
        return asdict(self)


def _body_key(text: str) -> str:
    """머리말(첫 줄 [제목 > 절])을 뺀 본문으로 중복을 판단한다."""
    body = text.split("\n", 1)[1] if text.startswith("[") and "\n" in text else text
    return hashlib.sha256(re.sub(r"\s+", " ", body).strip().encode("utf-8")).hexdigest()


def item_evidence(item_id: str, db: chromadb.ClientAPI, name: str) -> Evidence:
    if chroma.collection_count(name, db) == 0:
        raise IndexMissingError(f"항목 색인({name})이 없습니다. python -m scripts.index_items 를 실행하세요.")
    got = db.get_collection(name).get(ids=[item_id], include=["documents", "metadatas"])
    if not got["ids"]:
        raise IndexMissingError(f"항목 {item_id}의 메타데이터 청크가 색인에 없습니다. 항목 색인을 다시 실행하세요.")
    meta = got["metadatas"][0]
    return Evidence(number=0, chunk_id=item_id, kind=KIND_ITEM, source_type=ITEM_SOURCE,
                    title=meta["name"], section="", url=meta.get("source_url", ""), text=got["documents"][0])


def search_docs(item_id: str, question: str, embedding: Embeddings, db: chromadb.ClientAPI, name: str,
                cfg: RetrievalConfig, search_type: str | None = None) -> list[Evidence]:
    """항목 범위의 외부 문서 청크 검색. 문서 색인이 아직 없으면 빈 목록."""
    if chroma.collection_count(name, db) == 0:
        return []
    store = chroma.vector_store(name, embedding, db)
    where = {"item_id": item_id}
    if (search_type or cfg.search_type) == "mmr":
        pairs = [(d, None) for d in store.max_marginal_relevance_search(
            question, k=cfg.top_k_docs, fetch_k=cfg.mmr_fetch_k, lambda_mult=cfg.mmr_lambda, filter=where)]
    else:
        pairs = store.similarity_search_with_relevance_scores(question, k=cfg.top_k_docs, filter=where)
    found = []
    for doc, score in pairs:
        m = doc.metadata
        found.append(Evidence(
            number=0, chunk_id=doc.id or f"{m['item_id']}:{m['doc_id']}:{m['seq']}", kind=KIND_DOC,
            source_type=m["source_type"], title=m["title"], section=m.get("section", ""),
            url=m.get("source_url", ""), text=doc.page_content, score=score,
        ))
    return found


def merge(item_ev: Evidence, doc_evs: list[Evidence]) -> list[Evidence]:
    """항목 근거를 맨 앞에 두고, 같은 청크 · 같은 본문을 지운 뒤 번호를 붙인다."""
    merged, seen_ids, seen_bodies = [], set(), set()
    for ev in [item_ev, *doc_evs]:
        key = _body_key(ev.text)
        if ev.chunk_id in seen_ids or key in seen_bodies:
            continue
        seen_ids.add(ev.chunk_id)
        seen_bodies.add(key)
        merged.append(ev)
    for i, ev in enumerate(merged, 1):
        ev.number = i
    return merged


@dataclass
class Retrieval:
    evidences: list[Evidence]
    doc_search: str = "ok"                       # ok · empty(문서 색인 없음) · failed(장애로 건너뜀)
    warnings: list[str] = field(default_factory=list)


def retrieve_evidence(item: dict, question: str, embedding: Embeddings | None = None,
                      db: chromadb.ClientAPI | None = None, search_type: str | None = None,
                      cfg: RetrievalConfig | None = None) -> Retrieval:
    settings = get_settings()
    cfg = cfg or settings.retrieval
    db = db or chroma.client()
    embedding = embedding or chroma.default_embedding()
    warnings: list[str] = []

    # 1. 외부 문서 검색을 먼저 한다 (모듈 설명의 '검색 순서' 참고)
    try:
        doc_evs = search_docs(item["id"], question, embedding, db, settings.collections.docs, cfg, search_type)
        status = "ok" if doc_evs else "empty"
    except SEARCH_OUTAGE_ERRORS as e:
        doc_evs, status = [], "failed"
        reason = "검색 저장소 내부 오류" if isinstance(e, chromadb.errors.InternalError) else describe_api_error(e)
        warnings.append(f"문서 검색 실패({reason}) — 항목 정보만으로 답합니다.")

    # 2. 항목 메타데이터 청크 — 항상 근거 1
    item_ev = item_evidence(item["id"], db, settings.collections.items)
    return Retrieval(evidences=merge(item_ev, doc_evs), doc_search=status, warnings=warnings)
