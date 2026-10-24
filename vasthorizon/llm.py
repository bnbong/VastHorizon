"""채팅 · 임베딩 모델 생성 — 설정(config.toml의 [llm])에 따라 제공자를 고른다.

  - gms (config.toml 기본값): base_url만 OpenAI 호환 엔드포인트로 바꿔 OpenAI 라이브러리를 그대로 쓴다.
  - anthropic (배포): Claude 채팅 (langchain-anthropic, requirements-deploy.txt). 키는 CLAUDE_API_KEY.
    두 진입점 — llm(): 답변 모델(anthropic_model, answer_effort) · fast_llm(): 구조화 모델(anthropic_fast_model, fast_effort)
  - 임베딩 local (배포): Claude에는 임베딩 API가 없어서, 서버 안에서 fastembed(ONNX)로 다국어 모델을 돌린다.
배포 전용 패키지는 그 제공자를 쓸 때만 불러온다 — 기본 의존성(requirements.txt)에는 없어도 된다.
"""

from __future__ import annotations

import re
from functools import lru_cache

import openai
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from vasthorizon.config import get_claude_key, get_gms_key, get_settings, key_name

try:                                   # 배포용 (requirements-deploy.txt) — 없으면 GMS 오류만 다룬다
    import anthropic
except ImportError:                    # pragma: no cover - 배포 의존성 없음
    anthropic = None

# 잠시 뒤 다시 하면 될 수 있는 API 장애 — 이미 있는 색인 · 근거로 답변을 이어 간다.
# 인증 실패 · 잘못된 요청처럼 계속하면 안 되는 오류는 여기에 넣지 않는다.
TRANSIENT_API_ERRORS = (
    openai.APIConnectionError,        # 연결 실패 (APITimeoutError 포함)
    openai.RateLimitError,
    openai.InternalServerError,
) + ((anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) if anthropic else ())

# LLM 호출이 실패한 모든 경우 — 기능마다 '실패'로 처리하고 결과를 캐시하지 않는다
API_ERRORS = (openai.APIError,) + ((anthropic.APIError,) if anthropic else ())

_ERROR_LABELS = [
    (openai.APITimeoutError, "응답 시간 초과"),
    (openai.APIConnectionError, "연결 오류"),
    (openai.RateLimitError, "호출 한도 초과"),
    (openai.InternalServerError, "서버 오류"),
] + ([(anthropic.APITimeoutError, "응답 시간 초과"), (anthropic.APIConnectionError, "연결 오류"),
      (anthropic.RateLimitError, "호출 한도 초과"), (anthropic.InternalServerError, "서버 오류")] if anthropic else [])


def describe_api_error(error: Exception) -> str:
    """사용자에게 보여줄 장애 종류. 키 · URL · 요청 본문 같은 내부 정보는 넣지 않는다."""
    for cls, label in _ERROR_LABELS:
        if isinstance(error, cls):
            return label
    return "일시적 오류"


class MissingApiKeyError(RuntimeError):
    """LLM 키(GMS_KEY 또는 CLAUDE_API_KEY)가 설정되지 않았을 때. 화면에는 키 설정 안내로 바꿔 보여준다."""

    def __init__(self) -> None:
        super().__init__(f"{key_name()}가 설정되지 않았습니다. 프로젝트 폴더의 .env 파일을 확인하세요.")


def _require_key() -> str:
    key = get_claude_key() if get_settings().llm.provider == "anthropic" else get_gms_key()
    if not key:
        raise MissingApiKeyError()
    return key


_CLAUDE_VERSION = re.compile(r"claude-(opus|sonnet|haiku|fable|mythos)-(\d{1,2})(?:-(\d{1,2}))?(?:-|$)")


def supports_effort(model: str) -> bool:
    """output_config.effort를 받는 Claude 모델인가. 모르는 모델 · 구형 모델(Haiku 4.5 · Sonnet 4.5 등)은 False.

    langchain-anthropic 1.7.0의 모델 정보(profile)에는 5.5 세대가 없어서 이름으로 판단한다.
    effort 지원: Opus 4.5 이상 · Sonnet 4.6 이상 · Haiku 5 이상 · Fable · Mythos
    """
    m = _CLAUDE_VERSION.match(model or "")
    if not m:
        return False
    family, version = m.group(1), (int(m.group(2)), int(m.group(3) or 0))
    if family in ("fable", "mythos"):
        return True
    minimum = {"opus": (4, 5), "sonnet": (4, 6), "haiku": (5, 0)}[family]
    return version >= minimum


def chat_model(model: str | None = None, effort: str | None = None, **overrides) -> BaseChatModel:
    """채팅 모델. model · effort를 주지 않으면 답변 모델 설정을 쓴다 (gms는 chat_model 하나뿐이라 무시)."""
    cfg = get_settings().llm
    if cfg.provider == "anthropic":
        key = _require_key()                        # 키가 없으면 패키지보다 먼저 키 안내
        from langchain_anthropic import ChatAnthropic
        overrides.pop("model_kwargs", None)         # OpenAI 전용 옵션(JSON 모드)은 Claude에 넘기지 않는다
        overrides.pop("temperature", None)          # 최신 Claude 모델은 기본값 외의 temperature를 받지 않는다
        name = model or cfg.anthropic_model
        params = dict(model=name, api_key=key, timeout=cfg.timeout_sec, max_retries=2, max_tokens=cfg.max_tokens)
        effort = cfg.answer_effort if effort is None else effort
        if effort and supports_effort(name):        # effort를 모르는 모델에는 보내지 않는다 (400 방지)
            params["reasoning_effort"] = effort
        params.update(overrides)
        return ChatAnthropic(**params)
    from langchain_openai import ChatOpenAI
    params = dict(
        model=cfg.chat_model,
        api_key=_require_key(),
        base_url=cfg.base_url,
        timeout=cfg.timeout_sec,
        max_retries=2,
    )
    params.update(overrides)
    return ChatOpenAI(**params)


def llm() -> BaseChatModel:
    """답변 모델 — 사용자에게 보이는 긴 글 (질의응답 · 빛의 편지 · 마음 한 줄 · 별자리 펼치기 · 하늘 안내).
    Claude: [llm] anthropic_model + answer_effort."""
    return chat_model()


def fast_llm() -> BaseChatModel:
    """구조화 모델 — 짧은 JSON (검색어 추출 · 후보 선별 · 조건 탐색 필터 · 선별 · 마음 한 줄 분류).
    Claude: [llm] anthropic_fast_model + fast_effort (비우면 답변 모델). GMS: 같은 채팅 모델의 JSON 모드.
    응답 형식은 프롬프트의 형식 지시로 맞추고, parse_json_reply가 정리한다."""
    cfg = get_settings().llm
    if cfg.provider == "anthropic":
        return chat_model(model=cfg.anthropic_fast_model or cfg.anthropic_model, effort=cfg.fast_effort)
    return chat_model(model_kwargs={"response_format": {"type": "json_object"}})


def json_chat_model() -> BaseChatModel:
    """JSON 객체로 답하는 모델 — fast_llm()과 같다 (기존 호출부 호환)."""
    return fast_llm()


def reply_text(reply) -> str:
    """모델 응답의 글만 — GMS(OpenAI)는 문자열, Claude는 내용 블록 목록([{type: "text", text}, ...])으로 온다."""
    content = getattr(reply, "content", reply)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b if isinstance(b, str) else b.get("text", "") if isinstance(b, dict) and b.get("type", "text") == "text" else ""
                       for b in content)
    return str(content or "")


class LocalEmbeddings(Embeddings):
    """서버 안에서 돌리는 다국어 임베딩 (fastembed, ONNX — torch 없이 CPU로). 처음 쓸 때 모델을 내려받아 캐시한다.

    문서는 passage_embed, 질문은 query_embed로 — e5 계열처럼 접두어가 필요한 모델도 fastembed가 맞춰 준다.
    batch_size는 한 번에 모델에 넣는 문서 수다. fastembed 기본값(256)으로 e5-large를 돌리면 활성값만 수 GB라
    작은 서버에서 프로세스가 죽는다. 배치를 줄여도 결과 벡터는 같다.
    """

    def __init__(self, model: str, batch_size: int = 16) -> None:
        self.model = model
        self.batch_size = batch_size
        self._engine = _local_engine(model)
        self.dimensions = _local_dim(model)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._engine.passage_embed(list(texts), batch_size=self.batch_size)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._engine.query_embed([text]))).tolist()


@lru_cache(maxsize=2)
def _local_engine(model: str):
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=model)


@lru_cache(maxsize=2)
def _local_dim(model: str) -> int | None:
    from fastembed import TextEmbedding
    return next((m.get("dim") for m in TextEmbedding.list_supported_models() if m["model"] == model), None)


def embeddings() -> Embeddings:
    cfg = get_settings().llm
    if cfg.embedding_provider == "local":
        return LocalEmbeddings(cfg.local_embedding_model, cfg.local_embedding_batch_size)
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(
        model=cfg.embedding_model,
        api_key=get_gms_key() or _missing(),
        base_url=cfg.base_url,
        timeout=cfg.timeout_sec,
        max_retries=2,
    )


def _missing() -> str:
    raise MissingApiKeyError()
