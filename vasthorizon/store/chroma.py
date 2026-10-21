"""ChromaDB 컬렉션 생성 · 조회 · 교체.

임베딩 호환성
- 컬렉션 메타데이터에 임베딩 모델(embedding_model)과 차원(embedding_dim)을 기록한다.
  API 키 · base_url 같은 비밀 · 환경 값은 기록하지 않는다.
- 색인과 검색 모두 열 때 현재 임베딩 설정과 비교한다. 다르면 EmbeddingMismatchError로 멈춘다.
  식별 정보가 없는 예전 컬렉션도 불일치로 본다 — 전체 재구축(--rebuild)으로 해결한다.

재구축 · 교체 정책 (Chroma에는 트랜잭션이 없다)
1. 임시 컬렉션 <이름>__staging 에 처음부터 색인한다. 활성 컬렉션은 이 동안 그대로 조회된다.
2. 임시 컬렉션의 건수 · ID · 식별 정보를 검증한다. 실패하면 임시 컬렉션만 지우고 끝난다.
3. 활성 → <이름>__backup, 임시 → 활성 순서로 이름을 바꾼다. 두 번째 단계가 실패하면
   백업을 활성 이름으로 되돌린다.
4. 교체가 끝나면 백업을 지운다.
이름 변경 사이의 짧은 순간에는 활성 컬렉션이 없을 수 있다. 실행 중인 서비스는
'색인 없음' 안내를 띄우고, 다음 요청부터 새 컬렉션을 쓴다.
"""

from __future__ import annotations

from functools import lru_cache

import chromadb
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

from vasthorizon.config import get_settings

COLLECTION_CONFIG = {"hnsw": {"space": "cosine"}}
STAGING_SUFFIX = "__staging"
BACKUP_SUFFIX = "__backup"


class EmbeddingMismatchError(RuntimeError):
    """컬렉션 벡터와 현재 임베딩 설정이 호환되지 않을 때."""


@lru_cache(maxsize=1)
def client() -> chromadb.ClientAPI:
    path = get_settings().paths.chroma_dir
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def default_embedding() -> Embeddings:
    from vasthorizon.llm import embeddings
    return embeddings()


# ── 임베딩 식별 정보 ────────────────────────────────────────────────────────

def embedding_identity(embedding: Embeddings) -> dict:
    """벡터 호환성 판단용 식별 정보. 차원을 미리 알 수 없으면(OpenAI) 첫 임베딩 후 기록한다."""
    model = getattr(embedding, "model", None) or getattr(embedding, "model_name", None)
    dim = getattr(embedding, "dimensions", None) or getattr(embedding, "size", None)
    return {"embedding_model": f"{type(embedding).__name__}:{model or 'default'}",
            "embedding_dim": int(dim) if dim else None}


def stored_identity(collection) -> dict:
    meta = collection.metadata or {}
    return {"embedding_model": meta.get("embedding_model"), "embedding_dim": meta.get("embedding_dim")}


def check_identity(collection, identity: dict) -> None:
    """현재 임베딩 설정이 컬렉션 벡터와 호환되는지 확인한다. 빈 컬렉션은 통과."""
    stored = stored_identity(collection)
    if collection.count() == 0:
        return
    hint = "python -m scripts.index_items --rebuild 로 전체 재구축하세요."
    if not stored["embedding_model"]:
        raise EmbeddingMismatchError(f"컬렉션 {collection.name}에 임베딩 식별 정보가 없습니다 (예전 색인). {hint}")
    if stored["embedding_model"] != identity["embedding_model"]:
        raise EmbeddingMismatchError(
            f"임베딩 모델 불일치 — 컬렉션 {stored['embedding_model']}, 현재 설정 {identity['embedding_model']}. {hint}")
    if stored["embedding_dim"] and identity["embedding_dim"] and stored["embedding_dim"] != identity["embedding_dim"]:
        raise EmbeddingMismatchError(
            f"임베딩 차원 불일치 — 컬렉션 {stored['embedding_dim']}, 현재 설정 {identity['embedding_dim']}. {hint}")


def record_dimension(collection, dim: int) -> None:
    """첫 임베딩 결과로 차원을 기록하거나, 기록된 차원과 다르면 쓰기 전에 멈춘다."""
    stored = stored_identity(collection)
    if stored["embedding_dim"] and stored["embedding_dim"] != dim:
        raise EmbeddingMismatchError(f"임베딩 차원 불일치 — 컬렉션 {stored['embedding_dim']}, 새 벡터 {dim}.")
    if not stored["embedding_dim"]:
        collection.modify(metadata={**(collection.metadata or {}), "embedding_dim": dim})


# ── 컬렉션 열기 ───────────────────────────────────────────────────────────

def _exists(name: str, db: chromadb.ClientAPI) -> bool:
    return name in {c.name for c in db.list_collections()}


def open_collection(name: str, embedding: Embeddings, db: chromadb.ClientAPI | None = None):
    """색인용 원본 컬렉션. 새로 만들면 식별 정보를 기록하고, 있으면 호환성을 확인한다."""
    db = db or client()
    identity = embedding_identity(embedding)
    if _exists(name, db):
        collection = db.get_collection(name)
        check_identity(collection, identity)
        if collection.count() == 0 and not stored_identity(collection)["embedding_model"]:
            collection.modify(metadata={**(collection.metadata or {}),
                                        **{k: v for k, v in identity.items() if v is not None}})
        return collection
    return db.create_collection(
        name, configuration=COLLECTION_CONFIG,
        metadata={k: v for k, v in identity.items() if v is not None},
    )


def vector_store(name: str, embedding: Embeddings | None = None,
                 db: chromadb.ClientAPI | None = None) -> Chroma:
    """검색용 LangChain Chroma 래퍼. 열기 전에 임베딩 호환성을 확인한다."""
    db = db or client()
    embedding = embedding or default_embedding()
    if _exists(name, db):
        check_identity(db.get_collection(name), embedding_identity(embedding))
    return Chroma(client=db, collection_name=name, embedding_function=embedding,
                  collection_configuration=COLLECTION_CONFIG, create_collection_if_not_exists=False)


def collection_count(name: str, db: chromadb.ClientAPI | None = None) -> int:
    """색인 건수. 컬렉션이 없으면 0 — 임베딩 · API 키 없이도 조회할 수 있다. (F2012 색인 없음 안내)"""
    db = db or client()
    if not _exists(name, db):
        return 0
    return db.get_collection(name).count()


def drop_collection(name: str, db: chromadb.ClientAPI | None = None) -> bool:
    db = db or client()
    if _exists(name, db):
        db.delete_collection(name)
        return True
    return False


# ── 재구축 교체 ───────────────────────────────────────────────────────────

def staging_name(name: str) -> str:
    return name + STAGING_SUFFIX


def swap_in(name: str, db: chromadb.ClientAPI | None = None) -> None:
    """검증을 마친 <name>__staging 을 활성 컬렉션 <name>으로 교체한다."""
    db = db or client()
    staging, backup = staging_name(name), name + BACKUP_SUFFIX
    drop_collection(backup, db)
    had_active = _exists(name, db)
    if had_active:
        db.get_collection(name).modify(name=backup)
    try:
        db.get_collection(staging).modify(name=name)
    except Exception:
        if had_active:
            db.get_collection(backup).modify(name=name)   # 복구 — 이전 활성 컬렉션을 되돌린다
        raise
    if had_active:
        db.delete_collection(backup)
