"""GMS 경유 OpenAI 모델 생성.

상용 API를 직접 부르지 않고, base_url만 SSAFY GMS로 바꿔 OpenAI 라이브러리를 그대로 쓴다.
"""

from __future__ import annotations

import openai
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from vasthorizon.config import get_gms_key, get_settings

# 잠시 뒤 다시 하면 될 수 있는 API 장애 — 이미 있는 색인 · 근거로 답변을 이어 간다.
# 인증 실패 · 잘못된 요청처럼 계속하면 안 되는 오류는 여기에 넣지 않는다.
TRANSIENT_API_ERRORS = (
    openai.APIConnectionError,        # 연결 실패 (APITimeoutError 포함)
    openai.RateLimitError,
    openai.InternalServerError,
)

_ERROR_LABELS = {
    openai.APITimeoutError: "응답 시간 초과",
    openai.APIConnectionError: "연결 오류",
    openai.RateLimitError: "호출 한도 초과",
    openai.InternalServerError: "서버 오류",
}


def describe_api_error(error: Exception) -> str:
    """사용자에게 보여줄 장애 종류. 키 · URL · 요청 본문 같은 내부 정보는 넣지 않는다. (NF2004)"""
    for cls, label in _ERROR_LABELS.items():
        if isinstance(error, cls):
            return label
    return "일시적 오류"


class MissingApiKeyError(RuntimeError):
    """GMS_KEY가 설정되지 않았을 때. 화면에는 키 설정 안내로 바꿔 보여준다. (F2012)"""

    def __init__(self) -> None:
        super().__init__("GMS_KEY가 설정되지 않았습니다. 프로젝트 폴더의 .env 파일을 확인하세요.")


def _require_key() -> str:
    key = get_gms_key()
    if not key:
        raise MissingApiKeyError()
    return key


def chat_model(**overrides) -> ChatOpenAI:
    cfg = get_settings().llm
    params = dict(
        model=cfg.chat_model,
        api_key=_require_key(),
        base_url=cfg.base_url,
        timeout=cfg.timeout_sec,
        max_retries=2,
    )
    params.update(overrides)
    return ChatOpenAI(**params)


def embeddings() -> OpenAIEmbeddings:
    cfg = get_settings().llm
    return OpenAIEmbeddings(
        model=cfg.embedding_model,
        api_key=_require_key(),
        base_url=cfg.base_url,
        timeout=cfg.timeout_sec,
        max_retries=2,
    )
