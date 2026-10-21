"""실행 설정 로드.

비밀 값(API 키, 연락처)은 .env 환경변수에서, 나머지 설정은 config.toml에서 읽는다.
설정 파일 경로는 VH_CONFIG 환경변수로 바꿀 수 있다. (청크 · Top-k 비교 실험용)
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    chat_model: str
    embedding_model: str
    timeout_sec: int


@dataclass(frozen=True)
class PathConfig:
    data_dir: Path
    chroma_dir: Path
    cache_dir: Path


@dataclass(frozen=True)
class CollectionConfig:
    items: str
    docs: str


@dataclass(frozen=True)
class ChunkingConfig:
    chunk_size: int
    chunk_overlap: int


@dataclass(frozen=True)
class RetrievalConfig:
    search_type: str
    top_k_docs: int
    mmr_fetch_k: int
    mmr_lambda: float
    item_candidates: int


@dataclass(frozen=True)
class HttpConfig:
    app_name: str
    min_interval_sec: float
    max_retries: int
    timeout_sec: int


@dataclass(frozen=True)
class Settings:
    llm: LLMConfig
    paths: PathConfig
    collections: CollectionConfig
    chunking: ChunkingConfig
    retrieval: RetrievalConfig
    http: HttpConfig
    config_path: Path


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    config_path = _resolve(os.environ.get("VH_CONFIG", "config.toml"))
    with config_path.open("rb") as f:
        raw = tomllib.load(f)

    retrieval = RetrievalConfig(**raw["retrieval"])
    if retrieval.search_type not in ("similarity", "mmr"):
        raise ValueError(f"retrieval.search_type은 similarity 또는 mmr이어야 합니다: {retrieval.search_type}")

    chunking = ChunkingConfig(**raw["chunking"])
    if not 0 <= chunking.chunk_overlap < chunking.chunk_size:
        raise ValueError("chunking.chunk_overlap은 0 이상, chunk_size 미만이어야 합니다.")

    return Settings(
        llm=LLMConfig(**raw["llm"]),
        paths=PathConfig(**{k: _resolve(v) for k, v in raw["paths"].items()}),
        collections=CollectionConfig(**raw["collections"]),
        chunking=chunking,
        retrieval=retrieval,
        http=HttpConfig(**raw["http"]),
        config_path=config_path,
    )


def get_gms_key() -> str | None:
    """GMS 키. 없으면 None — 호출하는 쪽에서 안내 메시지를 띄운다. (F2012)"""
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.environ.get("GMS_KEY", "").strip()
    return key or None


def get_contact() -> str | None:
    """외부 API User-Agent에 넣을 연락처. (NF2006)"""
    load_dotenv(PROJECT_ROOT / ".env")
    contact = os.environ.get("WIKI_CONTACT", "").strip()
    return contact or None
