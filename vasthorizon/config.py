"""실행 설정 로드.

비밀 값(API 키, 연락처)은 .env 환경변수에서, 나머지 설정은 config.toml에서 읽는다.
설정 파일 경로는 VH_CONFIG 환경변수로 바꿀 수 있다. (청크 · Top-k 비교 실험용 · 배포용 config.deploy.toml)

LLM 제공자
  - gms (config.toml 기본값): OpenAI 호환 엔드포인트의 채팅 + 임베딩, 키는 GMS_KEY
  - anthropic (배포): Claude 채팅, 키는 CLAUDE_API_KEY (ANTHROPIC_API_KEY도 받는다)
임베딩 제공자
  - gms: OpenAI 호환 임베딩 API
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
EFFORTS = ("", "low", "medium", "high", "xhigh", "max")   # Claude output_config.effort — 빈 값이면 모델 기본값


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    chat_model: str
    embedding_model: str
    timeout_sec: int
    provider: str = "gms"
    anthropic_model: str = "claude-sonnet-5-5"       # 답변 모델 — 사용자에게 보이는 긴 글 (질의응답 · 편지 · 마음 한 줄 · 펼치기 · 하늘 안내)
    anthropic_fast_model: str = "claude-haiku-5-5"   # 구조화 모델 — 짧은 JSON (검색어 · 선별 · 필터 · 분류). 비우면 답변 모델을 쓴다
    answer_effort: str = "medium"                    # output_config.effort (low · medium · high · xhigh · max). 비우면 모델 기본값
    fast_effort: str = "low"
    max_tokens: int = 2048
    embedding_provider: str = "gms"
    local_embedding_model: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    local_embedding_batch_size: int = 16    # 한 번에 임베딩할 문서 수 — fastembed 기본 256은 큰 모델에서 메모리를 수 GB 쓴다


@dataclass(frozen=True)
class LimitsConfig:
    """공개 배포에서 개인 API 키를 지키는 한도 — LLM을 부르는 요청만 센다. 기본은 꺼짐 (config.toml)."""
    enabled: bool = False
    per_ip_per_minute: int = 6
    per_ip_per_day: int = 60
    global_per_day: int = 1500
    daily_cost_usd: float = 0.0     # 하루(한국 시각) 추정 비용 상한 — 넘으면 LLM 요청에 429. 0이면 끈다 (usage.py 기록 기준)
    # 사용자 주소는 Uvicorn이 신뢰 프록시(환경변수 FORWARDED_ALLOW_IPS, IP · CIDR)로 확정한 값만 쓴다 (api/limits.py)


@dataclass(frozen=True)
class ModelPrice:
    """모델 가격 ($/100만 토큰). 캐시 쓰기 · 읽기를 비우면 입력 단가의 1.25배 · 0.1배로 계산한다."""
    input: float
    output: float
    cache_read: float | None = None
    cache_write: float | None = None


@dataclass(frozen=True)
class UsageConfig:
    """LLM 호출 기록 (usage.py) — 호출마다 JSONL 한 줄. 프롬프트 · 응답 본문은 남기지 않는다."""
    enabled: bool = True
    log_path: Path | None = None                     # 없으면 cache_dir/usage.jsonl
    prices: tuple[tuple[str, ModelPrice], ...] = ()  # 모델 이름 → 가격. 표에 없는 모델은 비용 0으로 센다

    def price(self, model: str) -> ModelPrice | None:
        return dict(self.prices).get(model)


@dataclass(frozen=True)
class CacheConfig:
    """서버 응답 캐시 (cache.py) — 같은 입력이면 LLM을 부르지 않고 저장한 응답을 돌려준다."""
    enabled: bool = False
    dir: Path | None = None                          # 없으면 cache_dir/responses
    memory_items: int = 512                          # 메모리 LRU 크기 (디스크는 크기 제한 없이 TTL로 만료)
    explore_days: float = 7
    letter_days: float = 7
    unfold_days: float = 30
    perspective_days: float = 1
    ask_days: float = 7
    ask_live_days: float = 1                         # 근거에 '오늘 기준' 값(실시간 위치 · 거리)이 들어간 답변


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
    usage: UsageConfig = UsageConfig()
    cache: CacheConfig = CacheConfig()


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
    for name in ("answer_effort", "fast_effort"):
        if getattr(llm, name) not in EFFORTS:
            raise ValueError(f"llm.{name}는 {' · '.join(e or '(빈 값)' for e in EFFORTS)} 중 하나여야 합니다: {getattr(llm, name)}")
    usage_raw = dict(raw.get("usage", {}))
    prices = tuple(sorted((name, ModelPrice(**p)) for name, p in usage_raw.pop("prices", {}).items()))
    if usage_raw.get("log_path"):
        usage_raw["log_path"] = _resolve(usage_raw["log_path"])
    cache_raw = dict(raw.get("cache", {}))
    if cache_raw.get("dir"):
        cache_raw["dir"] = _resolve(cache_raw["dir"])
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
        limits=LimitsConfig(**raw.get("limits", {})),
        server=ServerConfig(cors_origins=origins),
        usage=UsageConfig(**usage_raw, prices=prices),
        cache=CacheConfig(**cache_raw),
    )


def get_gms_key() -> str | None:
    """GMS 키. 없으면 None — 호출하는 쪽에서 안내 메시지를 띄운다."""
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
    """외부 API User-Agent에 넣을 연락처."""
    load_dotenv(PROJECT_ROOT / ".env")
    contact = os.environ.get("WIKI_CONTACT", "").strip()
    return contact or None
