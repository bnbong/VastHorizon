"""외부 문서 색인 (RAG 2, F2005 · F2016) — 수집한 문서를 청킹해 cosmos_docs에 넣는다.

- 항목 메타데이터(cosmos_items)와 분리된 컬렉션
- 청크 ID = "항목 ID:문서 ID:순번" — 여러 항목이 같은 문서를 수집해도 서로 덮어쓰지 않는다
- 청크 메타데이터 — 문서 제목 · 절 · 원문 URL · 고정 판 주소 · 출처 종류 · 관련 항목 · 검색어 · 수집일 · 청크 설정
- 항목 단위 동기화 — 그 항목의 청크만 비교해 바뀐 청크만 재임베딩하고, 사라진 청크만 지운다
  (청크 크기를 바꿔 다시 색인하면 그 항목의 청크가 새 설정으로 바뀐다)
- 질문이 들어온 항목만 색인한다 — 토큰 할당량을 아끼기 위해 전체 문서를 미리 임베딩하지 않는다

삭제와 실패의 구분
| 입력 상태                               | 처리                                              |
|-----------------------------------------|---------------------------------------------------|
| 연결이 풀린 문서 (입력에 없음)          | 그 문서의 청크를 지운다 — 정상적인 삭제           |
| 본문이 비었거나 절 제목뿐인 문서        | 유효하지 않은 문서 — 그 문서의 기존 청크는 보존   |
| 연결됐지만 본문 캐시가 없는 문서        | 누락 문서(missing) — 그 문서의 기존 청크는 보존    |
| 유효한 문서가 하나도 없음               | 컬렉션을 바꾸지 않고 DocIndexError                |
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

import chromadb
from langchain_core.embeddings import Embeddings

from vasthorizon.config import get_settings
from vasthorizon.data.docs import Document
from vasthorizon.data.item_text import display_name
from vasthorizon.store import chroma
from vasthorizon.store.chunking import chunk_document
from vasthorizon.store.sync import Record, sync_records, with_hashes

_HEADING_LINE = re.compile(r"^\s*(=+)\s*.+?\s*\1\s*$")


class DocIndexError(RuntimeError):
    """색인을 시작하기 전에 거부된 입력 · 재구축 검증 실패."""


@dataclass
class DocIndexReport:
    item_id: str
    docs: int = 0                                               # 색인한(유효한) 문서 수
    chunks: int = 0
    by_source: dict[str, int] = field(default_factory=dict)    # 출처 종류별 청크 수
    embedded: int = 0
    meta_updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    invalid: list[str] = field(default_factory=list)           # 본문이 없어 건너뛴 문서 — 기존 청크 보존
    missing: list[str] = field(default_factory=list)           # 본문 캐시가 없는 연결 문서 — 기존 청크 보존

    @property
    def complete(self) -> bool:
        return not (self.invalid or self.missing)


def chunk_id(item_id: str, doc_id: str, seq: int) -> str:
    return f"{item_id}:{doc_id}:{seq}"


def has_body(doc: Document) -> bool:
    """절 제목 줄을 빼고도 남는 본문이 있는가."""
    return any(line.strip() and not _HEADING_LINE.match(line) for line in (doc.text or "").splitlines())


def build_records(item: dict, docs: list[Document], links: dict[str, dict],
                  chunk_size: int, chunk_overlap: int) -> list[Record]:
    records = []
    for doc in docs:
        link = links.get(doc.doc_id, {})
        for chunk in chunk_document(doc, chunk_size, chunk_overlap):
            meta = {
                "item_id": item["id"],
                "item_name": display_name(item["name"]),
                "doc_id": doc.doc_id,
                "title": doc.title,
                "section": chunk.section,
                "seq": chunk.seq,
                "source_type": doc.source_type,              # 위키백과 · NASA (F2016 출처 종류)
                "source_url": doc.url,
                "permalink": doc.permalink,
                "license": doc.license,
                "role": link.get("role", ""),                 # 항목 문서 · 관련 문서
                "query": link.get("query") or "",
                "fetched_at": doc.fetched_at,
                "truncated": doc.truncated,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            }
            records.append((chunk_id(item["id"], doc.doc_id, chunk.seq), chunk.text, with_hashes(chunk.text, meta)))
    return records


def sync_item_docs(item: dict, docs: list[Document], links: dict[str, dict], collection,
                   embedding: Embeddings, chunk_size: int, chunk_overlap: int,
                   missing: Iterable[str] = ()) -> DocIndexReport:
    """항목 하나의 문서 청크를 컬렉션과 맞춘다. 다른 항목의 청크는 건드리지 않는다.

    컬렉션을 바꾸기 전에 문서별로 청크를 만들어 검증한다. 유효하지 않은 문서와 missing 문서의
    기존 청크는 삭제 대상에서 빼서 그대로 둔다.
    """
    records, valid, invalid = [], [], []
    for doc in docs:
        doc_records = build_records(item, [doc], links, chunk_size, chunk_overlap) if has_body(doc) else []
        if doc_records:
            records.extend(doc_records)
            valid.append(doc)
        else:
            invalid.append(doc.doc_id)
    missing = sorted(set(missing))
    if not records:
        raise DocIndexError(f"{item['name']}: 유효한 본문이 있는 문서가 없습니다 "
                            f"(유효하지 않음 {invalid}, 누락 {missing}) — 기존 청크를 지우지 않고 멈춥니다.")

    protected = set(invalid) | set(missing)
    existing = collection.get(where={"item_id": item["id"]}, include=["metadatas"])
    scope = {cid: meta for cid, meta in zip(existing["ids"], existing["metadatas"])
             if meta.get("doc_id") not in protected}
    synced = sync_records(collection, embedding, records, scope)
    return DocIndexReport(
        item_id=item["id"], docs=len(valid), chunks=len(records),
        by_source=dict(Counter(m["source_type"] for _, _, m in records)),
        embedded=len(synced.embedded), meta_updated=len(synced.meta_updated),
        unchanged=synced.unchanged, deleted=len(synced.deleted), invalid=invalid, missing=missing,
    )


def indexed_item_ids(name: str, db: chromadb.ClientAPI | None = None) -> list[str]:
    """색인된 항목 ID — 임베딩 호환성 검사 없이 읽는다 (모델이 바뀐 뒤 재구축 대상 확보용)."""
    return sorted({m["item_id"] for m in chroma.raw_metadatas(name, db) if m and m.get("item_id")})


def rebuild_docs(targets: list[tuple[dict, list[Document], dict[str, dict], list[str]]], name: str,
                 embedding: Embeddings, chunk_size: int, chunk_overlap: int,
                 db: chromadb.ClientAPI | None = None) -> list[DocIndexReport]:
    """임시 컬렉션에서 처음부터 색인 · 검증한 뒤 활성 컬렉션과 교체한다.

    targets = (항목, 문서, 연결 정보, 누락 문서 ID). 누락 · 유효하지 않은 문서가 하나라도 있으면
    새 컬렉션에서 그 문서가 빠지므로 재구축을 멈춘다. 어떤 실패에도 활성 컬렉션은 그대로 남는다.
    """
    db = chroma.db_for(name, db)
    staging = chroma.staging_name(name)
    chroma.drop_collection(staging, db)
    try:
        for item, _, _, missing in targets:
            if missing:
                raise DocIndexError(f"{item['name']}: 본문 캐시가 없는 문서 {missing} — 재구축하면 빠지므로 멈춥니다.")
        collection = chroma.open_collection(staging, embedding, db)
        reports, expected = [], set()
        for item, docs, links, _ in targets:
            report = sync_item_docs(item, docs, links, collection, embedding, chunk_size, chunk_overlap)
            if report.invalid:
                raise DocIndexError(f"{item['name']}: 본문이 없는 문서 {report.invalid} — 재구축을 멈춥니다.")
            expected |= {cid for cid, _, _ in build_records(item, docs, links, chunk_size, chunk_overlap)}
            reports.append(report)
        got = set(collection.get(include=[])["ids"])
        if got != expected:
            raise DocIndexError(f"재구축 검증 실패 — 색인 {len(got)}개, 기대 {len(expected)}개")
        chroma.check_identity(collection, chroma.embedding_identity(embedding))
    except BaseException:
        chroma.drop_collection(staging, db)
        raise
    chroma.swap_in(name, db)
    return reports


class DocIndex:
    """cosmos_docs 색인기. 열 때 임베딩 호환성을 확인한다."""

    def __init__(self, embedding: Embeddings | None = None, db: chromadb.ClientAPI | None = None,
                 name: str | None = None) -> None:
        settings = get_settings()
        self.name = name or settings.collections.docs
        self.chunking = settings.chunking
        self.embedding = embedding or chroma.default_embedding()
        self.db = chroma.db_for(self.name, db)
        self.collection = chroma.open_collection(self.name, self.embedding, self.db)

    def ensure(self, item: dict, docs: list[Document], links: dict[str, dict],
               missing: Iterable[str] = ()) -> DocIndexReport:
        with chroma.LOCK:
            # 재구축으로 컬렉션이 교체됐을 수 있으므로 이름으로 다시 연다
            self.collection = chroma.open_collection(self.name, self.embedding, self.db)
            return sync_item_docs(item, docs, links, self.collection, self.embedding,
                                  self.chunking.chunk_size, self.chunking.chunk_overlap, missing)

    def indexed_items(self) -> Counter:
        """항목 ID → 청크 수."""
        metas = self.collection.get(include=["metadatas"])["metadatas"]
        return Counter(m["item_id"] for m in metas)

    def stats(self) -> dict:
        metas = self.collection.get(include=["metadatas"])["metadatas"]
        return {
            "chunks": len(metas),
            "items": len({m["item_id"] for m in metas}),
            "docs": len({(m["item_id"], m["doc_id"]) for m in metas}),
            "by_source": dict(Counter(m["source_type"] for m in metas)),
            "chunk_settings": dict(Counter(f"{m['chunk_size']}/{m['chunk_overlap']}" for m in metas)),
        }
