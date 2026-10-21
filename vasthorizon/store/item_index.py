"""항목 메타데이터 색인 (RAG 1, F2002).

- 컬렉션 cosmos_items에 항목당 1청크, 청크 ID = Wikidata QID
- 다시 실행해도 같은 ID로 덮어쓰기(upsert)만 일어나 중복 저장되지 않는다
- 변경 판정을 둘로 나눈다
    텍스트가 바뀜        → 다시 임베딩해 upsert
    메타데이터만 바뀜    → 임베딩 없이 메타데이터만 갱신 (좌표 · 문서 제목 · 출처 URL 등)
    둘 다 같음           → 건너뜀
- Chroma의 update/upsert는 메타데이터를 병합한다. 사라진 필드는 None으로 보내 지운다.
- 유효한 카탈로그에서 빠진 항목은 컬렉션에서도 지운다 — 로드 건수 = 색인 건수
- 빈 입력은 거부한다. 전체 삭제는 drop_collection으로 따로 해야 한다.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field

from langchain_core.embeddings import Embeddings

from vasthorizon.data.item_text import build_item_metadata, build_item_text
from vasthorizon.store import chroma

BATCH_SIZE = 100
HASH_KEYS = ("text_hash", "meta_hash")


class IndexingError(RuntimeError):
    """색인을 시작하기 전에 거부된 입력."""


@dataclass
class IndexReport:
    loaded: int = 0
    embedded: list[str] = field(default_factory=list)        # 텍스트 변경 → 재임베딩
    meta_updated: list[str] = field(default_factory=list)    # 메타데이터만 갱신 (임베딩 없음)
    unchanged: int = 0
    deleted: list[str] = field(default_factory=list)
    indexed: int = 0


def meta_hash(meta: dict) -> str:
    body = {k: v for k, v in meta.items() if k not in HASH_KEYS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def prepare(items: list[dict], ref_year: int) -> list[tuple[str, str, dict]]:
    """(청크 ID, 색인 텍스트, 메타데이터) 목록."""
    prepared = []
    for item in items:
        text = build_item_text(item, ref_year)
        meta = build_item_metadata(item, ref_year, text)
        meta["meta_hash"] = meta_hash(meta)
        prepared.append((item["id"], text, meta))
    return prepared


def _with_removals(new: dict, old: dict | None) -> dict:
    """이전에 있었지만 이제 없는 필드를 None으로 지운다 (Chroma 메타데이터 병합 대응)."""
    removed = {k: None for k in (old or {}) if k not in new}
    return {**removed, **new}


def sync_items(items: list[dict], collection, embedding: Embeddings, ref_year: int) -> IndexReport:
    """카탈로그와 컬렉션을 맞춘다. collection은 chroma.open_collection으로 연 원본 컬렉션."""
    if not items:
        raise IndexingError("빈 카탈로그로는 색인하지 않습니다 — 기존 색인을 지우려면 drop_collection을 쓰세요.")
    dup = [qid for qid, n in Counter(it["id"] for it in items).items() if n > 1]
    if dup:
        raise IndexingError(f"QID 중복 {dup[:5]} — 색인 전에 카탈로그를 고치세요.")

    report = IndexReport(loaded=len(items))
    prepared = prepare(items, ref_year)
    existing = collection.get(include=["metadatas"])
    old_meta = dict(zip(existing["ids"], existing["metadatas"]))

    to_embed, to_update = [], []
    for cid, text, meta in prepared:
        old = old_meta.get(cid) or {}
        if old.get("text_hash") != meta["text_hash"]:
            to_embed.append((cid, text, _with_removals(meta, old_meta.get(cid))))
        elif old.get("meta_hash") != meta["meta_hash"]:
            to_update.append((cid, _with_removals(meta, old)))
        else:
            report.unchanged += 1

    for start in range(0, len(to_embed), BATCH_SIZE):
        batch = to_embed[start:start + BATCH_SIZE]
        vectors = embedding.embed_documents([t for _, t, _ in batch])
        chroma.record_dimension(collection, len(vectors[0]))      # 차원이 다르면 쓰기 전에 멈춘다
        collection.upsert(ids=[c for c, _, _ in batch], embeddings=vectors,
                          documents=[t for _, t, _ in batch], metadatas=[m for _, _, m in batch])
        report.embedded.extend(c for c, _, _ in batch)

    for start in range(0, len(to_update), BATCH_SIZE):
        batch = to_update[start:start + BATCH_SIZE]
        collection.update(ids=[c for c, _ in batch], metadatas=[m for _, m in batch])
        report.meta_updated.extend(c for c, _ in batch)

    stale = sorted(set(old_meta) - {cid for cid, _, _ in prepared})
    if stale:
        collection.delete(ids=stale)
    report.deleted = stale
    report.indexed = collection.count()
    return report


def rebuild_items(items: list[dict], name: str, embedding: Embeddings, ref_year: int, db=None) -> IndexReport:
    """임시 컬렉션에서 처음부터 색인하고, 검증이 끝나면 활성 컬렉션과 교체한다.

    색인 · 검증 중 어떤 단계가 실패해도 활성 컬렉션은 그대로 남는다.
    """
    db = db or chroma.client()
    staging = chroma.staging_name(name)
    chroma.drop_collection(staging, db)                 # 지난번 실패로 남은 임시 컬렉션 정리
    try:
        collection = chroma.open_collection(staging, embedding, db)
        report = sync_items(items, collection, embedding, ref_year)
        _verify_staging(collection, items, embedding)
    except BaseException:
        chroma.drop_collection(staging, db)
        raise
    chroma.swap_in(name, db)
    return report


def _verify_staging(collection, items: list[dict], embedding: Embeddings) -> None:
    ids = set(collection.get(include=[])["ids"])
    expected = {it["id"] for it in items}
    if ids != expected:
        raise IndexingError(f"재구축 검증 실패 — 색인 {len(ids)}건, 기대 {len(expected)}건")
    chroma.check_identity(collection, chroma.embedding_identity(embedding))
