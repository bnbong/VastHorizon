"""실행 설정 로드.

비밀 값(API 키, 연락처)은 .env 환경변수에서, 나머지 설정은 config.toml에서 읽는다.
설정 파일 경로는 VH_CONFIG 환경변수로 바꿀 수 있다. (청크 · Top-k 비교 실험용 · 배포용 config.deploy.toml)

LLM 제공자
  - gms (기본, 과제 제출 환경): SSAFY GMS의 GPT 채팅 + text-embedding-3-small, 키는 GMS_KEY
  - anthropic (배포): Claude 채팅, 키는 CLAUDE_API_KEY (ANTHROPIC_API_KEY도 받는다)
임베딩 제공자
  - gms: GMS 임베딩 API
  - local: 서버 안에서 fastembed(ONNX)로 다국어 모델을 돌린다. 키 · 호출 비용 없음 (Claude에는 임베딩 API가 없다)
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


PROVIDERS = ("gms", "anthropic")
EMBEDDING_PROVIDERS = ("gms", "local")


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    chat_model: str
    embedding_model: str
    timeout_sec: int
    provider: str = "gms"
    anthropic_model: str = "claude-sonnet-5-5"
    max_tokens: int = 2048
    embedding_provider: str = "gms"
    local_embedding_model: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"


@dataclass(frozen=True)
class LimitsConfig:
    """공개 배포에서 개인 API 키를 지키는 한도 — LLM을 부르는 요청만 센다. 기본은 꺼짐 (과제 환경)."""
    enabled: bool = False
    per_ip_per_minute: int = 6
    per_ip_per_day: int = 60
    global_per_day: int = 1500
    trust_proxy: bool = False        # 리버스 프록시 뒤라면 X-Forwarded-For의 첫 주소를 사용자 주소로


@dataclass(frozen=True)
class ServerConfig:
    cors_origins: tuple[str, ...] = ()   # 프런트엔드를 다른 주소(Cloudflare Pages 등)에 둘 때 허용할 출처


@dataclass(frozen=True)
class PathConfig:
    data_dir: Path
    chroma_dir: Path
    cache_dir: Path


@dataclass(frozen=True)
class CollectionConfig:
    items: str
    docs: str
    perspective: str = "cosmos_perspective"


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
class CollectConfig:
    max_queries: int
    candidates_per_query: int
    max_selected: int
    min_summary_chars: int
    min_doc_chars: int
    max_doc_chars: int


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
    collect: CollectConfig
    http: HttpConfig
    config_path: Path
    limits: LimitsConfig = LimitsConfig()
    server: ServerConfig = ServerConfig()


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

    llm = LLMConfig(**raw["llm"])
    if llm.provider not in PROVIDERS:
        raise ValueError(f"llm.provider는 {' 또는 '.join(PROVIDERS)}여야 합니다: {llm.provider}")
    if llm.embedding_provider not in EMBEDDING_PROVIDERS:
        raise ValueError(f"llm.embedding_provider는 {' 또는 '.join(EMBEDDING_PROVIDERS)}여야 합니다: {llm.embedding_provider}")
    server = raw.get("server", {})
    cors = os.environ.get("VH_CORS_ORIGINS")          # 배포 환경에서 파일을 고치지 않고 바꿀 수 있게
    origins = tuple(o.strip() for o in (cors.split(",") if cors is not None else server.get("cors_origins", [])) if o.strip())

    return Settings(
        llm=llm,
        paths=PathConfig(**{k: _resolve(v) for k, v in raw["paths"].items()}),
        collections=CollectionConfig(**raw["collections"]),
        chunking=chunking,
        retrieval=retrieval,
        collect=CollectConfig(**raw["collect"]),
        http=HttpConfig(**raw["http"]),
        config_path=config_path,
        limits=_limits(raw.get("limits", {})),
        server=ServerConfig(cors_origins=origins),
    )


def _limits(raw: dict) -> LimitsConfig:
    """[limits] — 배포 환경에서 파일을 고치지 않고 VH_TRUST_PROXY=1로 프록시 신뢰를 켤 수 있다."""
    env = os.environ.get("VH_TRUST_PROXY")
    if env is not None:
        raw = {**raw, "trust_proxy": env.strip().lower() in ("1", "true", "yes")}
    return LimitsConfig(**raw)


def get_gms_key() -> str | None:
    """GMS 키. 없으면 None — 호출하는 쪽에서 안내 메시지를 띄운다. (F2012)"""
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.environ.get("GMS_KEY", "").strip()
    return key or None


def get_claude_key() -> str | None:
    """Claude API 키 (배포용). CLAUDE_API_KEY, 없으면 ANTHROPIC_API_KEY. 값은 어디에도 출력하지 않는다."""
    load_dotenv(PROJECT_ROOT / ".env")
    key = (os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    return key or None


def key_name() -> str:
    """지금 설정의 LLM 키 이름 — 안내 문구용."""
    return "CLAUDE_API_KEY" if get_settings().llm.provider == "anthropic" else "GMS_KEY"


def get_llm_key() -> str | None:
    """지금 설정한 LLM 제공자의 키."""
    return get_claude_key() if get_settings().llm.provider == "anthropic" else get_gms_key()


def get_contact() -> str | None:
    """외부 API User-Agent에 넣을 연락처. (NF2006)"""
    load_dotenv(PROJECT_ROOT / ".env")
    contact = os.environ.get("WIKI_CONTACT", "").strip()
    return contact or None
