"""레코드 증분 동기화 — 항목 색인(cosmos_items)과 문서 색인(cosmos_docs)이 함께 쓴다.

레코드 = (청크 ID, 텍스트, 메타데이터). 기존 레코드와 비교해
    텍스트가 바뀜        → 다시 임베딩해 upsert
    메타데이터만 바뀜    → 임베딩 없이 메타데이터만 갱신
    둘 다 같음           → 건너뜀
Chroma의 update/upsert는 메타데이터를 병합하므로, 사라진 필드는 None으로 보내 지운다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from langchain_core.embeddings import Embeddings

from vasthorizon.store import chroma

BATCH_SIZE = 100
HASH_KEYS = ("text_hash", "meta_hash")

Record = tuple[str, str, dict]


@dataclass
class SyncReport:
    embedded: list[str] = field(default_factory=list)        # 텍스트 변경 → 재임베딩
    meta_updated: list[str] = field(default_factory=list)    # 메타데이터만 갱신 (임베딩 없음)
    unchanged: int = 0
    deleted: list[str] = field(default_factory=list)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def meta_hash(meta: dict) -> str:
    body = {k: v for k, v in meta.items() if k not in HASH_KEYS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def with_hashes(text: str, meta: dict) -> dict:
    meta = {**meta, "text_hash": text_hash(text)}
    meta["meta_hash"] = meta_hash(meta)
    return meta


def _with_removals(new: dict, old: dict | None) -> dict:
    """이전에 있었지만 이제 없는 필드를 None으로 지운다 (Chroma 메타데이터 병합 대응)."""
    removed = {k: None for k in (old or {}) if k not in new}
    return {**removed, **new}


def sync_records(collection, embedding: Embeddings, records: list[Record], existing: dict[str, dict],
                 batch_size: int = BATCH_SIZE) -> SyncReport:
    """records를 컬렉션에 반영하고, existing에 있지만 records에 없는 ID는 지운다.

    existing은 동기화 범위의 기존 레코드 {ID: 메타데이터} — 항목 색인은 컬렉션 전체,
    문서 색인은 해당 항목의 청크만 넘겨서 다른 범위의 레코드를 건드리지 않는다.
    """
    report = SyncReport()
    to_embed, to_update = [], []
    for cid, text, meta in records:
        old = existing.get(cid)
        if (old or {}).get("text_hash") != meta["text_hash"]:
            to_embed.append((cid, text, _with_removals(meta, old)))
        elif old.get("meta_hash") != meta["meta_hash"]:
            to_update.append((cid, _with_removals(meta, old)))
        else:
            report.unchanged += 1

    for start in range(0, len(to_embed), batch_size):
        batch = to_embed[start:start + batch_size]
        vectors = embedding.embed_documents([t for _, t, _ in batch])
        chroma.record_dimension(collection, len(vectors[0]))      # 차원이 다르면 쓰기 전에 멈춘다
        collection.upsert(ids=[c for c, _, _ in batch], embeddings=vectors,
                          documents=[t for _, t, _ in batch], metadatas=[m for _, _, m in batch])
        report.embedded.extend(c for c, _, _ in batch)

    for start in range(0, len(to_update), batch_size):
        batch = to_update[start:start + batch_size]
        collection.update(ids=[c for c, _ in batch], metadatas=[m for _, m in batch])
        report.meta_updated.extend(c for c, _ in batch)

    stale = sorted(set(existing) - {cid for cid, _, _ in records})
    if stale:
        collection.delete(ids=stale)
    report.deleted = stale
    return report
