"""ChromaDB 컬렉션 생성 · 조회 · 교체.

임베딩 호환성
- 컬렉션 메타데이터에 임베딩 모델(embedding_model)과 차원(embedding_dim)을 기록한다.
  API 키 · base_url 같은 비밀 · 환경 값은 기록하지 않는다.
- 색인과 검색 모두 열 때 현재 임베딩 설정과 비교한다. 다르면 EmbeddingMismatchError로 멈춘다.
  식별 정보가 없는 예전 컬렉션도 불일치로 본다 — 전체 재구축(--rebuild)으로 해결한다.

완성 표식 (index_complete · index_count)
- 항목 · 서가 색인 스크립트가 끝까지 성공했을 때만 같은 메타데이터에 완성 표식과 그때의 건수를 남긴다.
  증분 반영을 시작하기 전에는 표식을 내린다. 그래서 도중에 죽은 색인(메모리 부족 등)은 건수가 있어도
  표식이 없거나 기록된 건수와 실제 건수가 달라, scripts/deploy_init.py가 불완전한 색인으로 알아챈다.
- 재구축은 임시 컬렉션에서 만들고 교체한 뒤 활성 컬렉션에 표식을 남긴다 (임시 컬렉션에는 남기지 않는다).
- 항목 색인은 표식과 함께 색인한 카탈로그 내용의 해시(catalog_hash)를 남긴다. 건수 · 모델이 같아도
  카탈로그 · 보강(enrich.json) · 색인 텍스트 생성 코드가 바뀌어 해시가 다르면 deploy_init이 다시 만든다.

재구축 · 교체 정책 (Chroma에는 트랜잭션이 없다)
1. 임시 컬렉션 <이름>__staging 에 처음부터 색인한다. 활성 컬렉션은 이 동안 그대로 조회된다.
2. 임시 컬렉션의 건수 · ID · 식별 정보를 검증한다. 실패하면 임시 컬렉션만 지우고 끝난다.
3. 활성 → <이름>__backup, 임시 → 활성 순서로 이름을 바꾼다. 두 번째 단계가 실패하면
   백업을 활성 이름으로 되돌린다.
4. 교체가 끝나면 백업을 지운다.
이름 변경 사이의 짧은 순간에는 활성 컬렉션이 없을 수 있다. 실행 중인 서비스는
'색인 없음' 안내를 띄우고, 다음 요청부터 새 컬렉션을 쓴다.

컬렉션별 저장소 분리 — data/chroma/<컬렉션 이름>/
  로컬 Chroma(1.5.9)는 한 저장소(클라이언트) 안에서 컬렉션을 오가며 다루면, 방금 쓴 컬렉션의
  벡터 영역이 메타데이터와 어긋난 상태로 굳는 일이 있었다. 그 뒤로는 검색(query)과 벡터 조회
  (get embeddings)가 계속 "Error finding id"를 냈고, 개수 · 메타데이터 조회만 정상이었다.
  같은 시나리오 1,000회에서 한 저장소는 9회 오류, 컬렉션별로 저장소를 나누자 0회였다.
  그래서 cosmos_items · cosmos_docs를 서로 다른 저장소에 둔다. 재구축용 임시 · 백업 컬렉션은
  원래 컬렉션과 같은 저장소에 둔다 (이름 변경으로 교체하려면 같은 저장소여야 한다).
  기존 한 저장소 배치는 scripts/migrate_chroma.py가 재임베딩 없이 옮긴다.
"""

from __future__ import annotations

import threading
from functools import lru_cache

import chromadb
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

from vasthorizon.config import get_settings

COLLECTION_CONFIG = {"hnsw": {"space": "cosine"}}

# 프로세스 안에서 Chroma 읽기 · 쓰기 구간을 직렬화한다 — 동시 요청이 색인 · 검색을 섞지 않게.
# LLM 호출처럼 오래 걸리는 작업은 이 잠금 밖에서 한다.
LOCK = threading.RLock()
STAGING_SUFFIX = "__staging"
BACKUP_SUFFIX = "__backup"

ITEMS_REBUILD = "python -m scripts.index_items --rebuild"
DOCS_REBUILD = "python -m scripts.index_docs --rebuild"
PERSPECTIVE_REBUILD = "python -m scripts.index_perspective --rebuild"


def base_name(name: str) -> str:
    """임시 · 백업 컬렉션 이름에서 원래 컬렉션 이름을 얻는다."""
    return name.removesuffix(STAGING_SUFFIX).removesuffix(BACKUP_SUFFIX)


def rebuild_hint(name: str) -> str:
    """컬렉션별 재구축 명령. 임시 · 백업 이름이면 원래 이름 기준으로 찾는다."""
    collections = get_settings().collections
    return {collections.docs: DOCS_REBUILD, collections.perspective: PERSPECTIVE_REBUILD}.get(base_name(name), ITEMS_REBUILD)


class EmbeddingMismatchError(RuntimeError):
    """컬렉션 벡터와 현재 임베딩 설정이 호환되지 않을 때."""


@lru_cache(maxsize=None)
def client(store: str) -> chromadb.ClientAPI:
    """컬렉션별 저장소 data/chroma/<store>/ (모듈 설명의 '컬렉션별 저장소 분리')."""
    path = get_settings().paths.chroma_dir / store
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def db_for(name: str, db: chromadb.ClientAPI | None = None) -> chromadb.ClientAPI:
    """컬렉션이 사는 저장소. db를 넘기면(테스트의 메모리 전용 클라이언트 등) 그것을 쓴다."""
    return db if db is not None else client(base_name(name))


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
    hint = f"{rebuild_hint(collection.name)} 로 전체 재구축하세요."
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


# ── 완성 표식 ─────────────────────────────────────────────────────────────

COMPLETE_KEY = "index_complete"
COUNT_KEY = "index_count"
CATALOG_HASH_KEY = "catalog_hash"      # 항목 색인 — 색인한 카탈로그 내용의 해시 (item_index.catalog_hash)


def mark_complete(name: str, db: chromadb.ClientAPI | None = None, catalog_hash: str | None = None) -> int:
    """색인이 끝까지 성공했다는 표식과 지금 건수를 남긴다 (모듈 설명의 '완성 표식').
    catalog_hash를 주면 함께 남긴다 — 다음 준비(scripts/deploy_init.py)가 카탈로그 내용이 바뀌었는지 비교한다."""
    collection = db_for(name, db).get_collection(name)
    count = collection.count()
    extra = {CATALOG_HASH_KEY: catalog_hash} if catalog_hash else {}
    collection.modify(metadata={**(collection.metadata or {}), COMPLETE_KEY: True, COUNT_KEY: count, **extra})
    return count


def recorded_catalog_hash(name: str, db: chromadb.ClientAPI | None = None) -> str | None:
    """완성 표식과 함께 남긴 카탈로그 해시. 컬렉션이나 해시가 없으면(예전 색인) None."""
    db = db_for(name, db)
    if not _exists(name, db):
        return None
    return (db.get_collection(name).metadata or {}).get(CATALOG_HASH_KEY)


def mark_incomplete(name: str, db: chromadb.ClientAPI | None = None) -> None:
    """쓰기를 시작하기 전에 표식을 내린다 — 이번 실행이 도중에 끝나면 다음 준비가 알아챈다."""
    db = db_for(name, db)
    if not _exists(name, db):
        return
    collection = db.get_collection(name)
    meta = collection.metadata or {}
    if meta.get(COMPLETE_KEY):
        collection.modify(metadata={**meta, COMPLETE_KEY: False})


def recorded_count(name: str, db: chromadb.ClientAPI | None = None) -> int | None:
    """완성 표식에 기록된 건수. 컬렉션이나 표식이 없으면 None."""
    db = db_for(name, db)
    if not _exists(name, db):
        return None
    meta = db.get_collection(name).metadata or {}
    return meta.get(COUNT_KEY) if meta.get(COMPLETE_KEY) is True else None


# ── 컬렉션 열기 ───────────────────────────────────────────────────────────

def _exists(name: str, db: chromadb.ClientAPI) -> bool:
    return name in {c.name for c in db.list_collections()}


def open_collection(name: str, embedding: Embeddings, db: chromadb.ClientAPI | None = None):
    """색인용 원본 컬렉션. 새로 만들면 식별 정보를 기록하고, 있으면 호환성을 확인한다."""
    db = db_for(name, db)
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
    db = db_for(name, db)
    embedding = embedding or default_embedding()
    if _exists(name, db):
        check_identity(db.get_collection(name), embedding_identity(embedding))
    return Chroma(client=db, collection_name=name, embedding_function=embedding,
                  collection_configuration=COLLECTION_CONFIG, create_collection_if_not_exists=False)


def raw_metadatas(name: str, db: chromadb.ClientAPI | None = None) -> list[dict]:
    """임베딩 호환성 검사 없이 메타데이터만 읽는다 — 모델이 바뀐 컬렉션의 재구축 대상을 찾을 때 쓴다."""
    db = db_for(name, db)
    if not _exists(name, db):
        return []
    return db.get_collection(name).get(include=["metadatas"])["metadatas"]


def collection_count(name: str, db: chromadb.ClientAPI | None = None) -> int:
    """색인 건수. 컬렉션이 없으면 0 — 임베딩 · API 키 없이도 조회할 수 있다. (색인 없음 안내)"""
    db = db_for(name, db)
    if not _exists(name, db):
        return 0
    return db.get_collection(name).count()


def drop_collection(name: str, db: chromadb.ClientAPI | None = None) -> bool:
    db = db_for(name, db)
    if _exists(name, db):
        db.delete_collection(name)
        return True
    return False


# ── 재구축 교체 ───────────────────────────────────────────────────────────

def staging_name(name: str) -> str:
    return name + STAGING_SUFFIX


def swap_in(name: str, db: chromadb.ClientAPI | None = None) -> None:
    """검증을 마친 <name>__staging 을 활성 컬렉션 <name>으로 교체한다."""
    db = db_for(name, db)
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
