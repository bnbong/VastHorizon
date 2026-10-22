"""JSON으로 답하는 LLM 호출과 응답 검증.

GMS의 JSON 모드(response_format=json_object)로 받고, 그래도 형식이 깨지면
코드 블록 · 앞뒤 설명을 걷어 내고 한 번 더 파싱한다.
문법이 맞아도 필드 타입이 스키마와 다르면 같은 JsonReplyError로 다룬다.
호출하는 쪽은 이 오류를 '실패'로 처리하고, 정상 결과(빈 선택 등)로 캐시하지 않는다.
"""

from __future__ import annotations

import json
import re

from langchain_core.language_models import BaseChatModel


class JsonReplyError(ValueError):
    """LLM 응답을 JSON으로 읽을 수 없거나 스키마와 다를 때. 화면에는 원문을 보여주지 않는다. (NF2004)"""


def json_chat_model() -> BaseChatModel:
    from vasthorizon.llm import chat_model
    return chat_model(model_kwargs={"response_format": {"type": "json_object"}})


def parse_json_reply(content: str):
    text = content.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start >= 0:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            end = max(text.rfind("}"), text.rfind("]"))
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    raise JsonReplyError("LLM 응답을 JSON으로 읽을 수 없습니다.")


def invoke_json(llm: BaseChatModel, messages: list) -> dict:
    """JSON 객체 하나를 받는다. 배열 · 문자열 같은 다른 최상위 타입은 스키마 오류."""
    reply = llm.invoke(messages)
    data = parse_json_reply(reply.content if hasattr(reply, "content") else str(reply))
    if not isinstance(data, dict):
        raise JsonReplyError(f"LLM 응답이 JSON 객체가 아닙니다 ({type(data).__name__}).")
    return data


def optional_field(data: dict, field: str, types: tuple[type, ...]):
    """선택 필드 — 없거나 null이면 None, 있으면 지정한 타입이어야 한다 (bool은 숫자로 보지 않는다)."""
    value = data.get(field)
    if value is None:
        return None
    if isinstance(value, bool) and bool not in types:
        raise JsonReplyError(f"'{field}'의 타입이 올바르지 않습니다 (bool).")
    if not isinstance(value, types):
        raise JsonReplyError(f"'{field}'의 타입이 올바르지 않습니다 ({type(value).__name__}).")
    return value


def string_list(data: dict, field: str, max_items: int) -> list[str]:
    """필드가 문자열 배열인지 검증한다. 앞뒤 공백 · 빈 문자열 · 중복을 정리하고 max_items개로 자른다.

    필드가 없거나 · 배열이 아니거나 · 문자열이 아닌 원소가 하나라도 있으면 JsonReplyError.
    ("NASA"를 글자 단위로 순회하거나, 숫자 때문에 TypeError로 멈추는 일을 막는다.)
    """
    if field not in data:
        raise JsonReplyError(f"응답에 '{field}' 필드가 없습니다.")
    value = data[field]
    if not isinstance(value, list):
        raise JsonReplyError(f"'{field}'는 문자열 배열이어야 합니다 ({type(value).__name__}).")
    if any(not isinstance(v, str) for v in value):
        raise JsonReplyError(f"'{field}'에 문자열이 아닌 원소가 있습니다.")
    cleaned: list[str] = []
    for v in value:
        v = v.strip()
        if v and v not in cleaned:
            cleaned.append(v)
    return cleaned[:max_items]
