"""GMS 경유 OpenAI 모델 생성.

상용 API를 직접 부르지 않고, base_url만 SSAFY GMS로 바꿔 OpenAI 라이브러리를 그대로 쓴다.
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from vasthorizon.config import get_gms_key, get_settings


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
