"""RAG 그래프 (F2007) — LangGraph의 retrieve · generate 두 노드.

    START → retrieve → generate → END

- retrieve: 항목 범위 외부 문서 청크 검색 + 항목 메타데이터 청크(항상) → 병합 · 중복 제거 · 번호
- generate: 답변 생성 프롬프트(③)로 근거만 써서 답하고, 인용 규칙을 검증한다

답변 검증 정책 (generate)
| 상태       | 조건                                                  | 처리                               |
|------------|-------------------------------------------------------|------------------------------------|
| cited      | 인용 1개 이상, 모든 번호가 근거 목록에 있음           | 반환                               |
| not_found  | '문서에서 확인되지 않음' 답변, 인용이 있다면 모두 유효 | 반환 (인용 없어도 됨)              |
| (위반)     | 목록에 없는 번호 · 인용 없는 사실 답변                 | 위반 내용을 알려 주고 1회 재생성   |
| rejected   | 재생성도 위반                                         | 원문은 내보내지 않고 고정 안내 문구 |
'cited'는 번호가 근거 목록에 있다는 형식 검증일 뿐, 주장과 근거의 의미 일치를 보장하지 않는다.
"""

from __future__ import annotations

import re
from typing import TypedDict

import chromadb
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from vasthorizon.data.domain import NOT_FOUND_SENTENCE
from vasthorizon.rag.citations import citation_issue, resolve_citations
from vasthorizon.rag.prompts import answer_messages
from vasthorizon.rag.retrieval import Evidence, retrieve_evidence

MAX_ATTEMPTS = 2        # 첫 생성 + 재생성 1회
REJECTED_ANSWER = ("근거 문서로 확인할 수 있는 답변을 만들지 못했습니다. "
                   "질문을 조금 바꾸어 다시 물어봐 주세요.")

_NOT_FOUND = re.compile(r"(문서|근거)[^.\n]{0,40}확인(되지|할 수 없)")


def is_not_found(answer: str) -> bool:
    """'문서에서 확인되지 않는다'는 취지가 답변 첫 문장에 있는가.

    모델이 정해 준 문장(NOT_FOUND_SENTENCE)을 조금 바꿔 쓰기도 해서 표현을 넓게 본다.
    """
    first = re.split(r"(?<=[.!?])\s", answer.strip(), maxsplit=1)[0]
    return answer.strip().startswith(NOT_FOUND_SENTENCE) or bool(_NOT_FOUND.search(first))


class RagState(TypedDict, total=False):
    # 입력
    item: dict
    question: str
    history: list[dict]
    search_type: str | None          # None이면 설정값 (similarity · mmr)
    # retrieve 결과
    evidences: list[Evidence]
    doc_search: str                  # ok · empty · failed
    warnings: list[str]
    # generate 결과
    answer: str
    status: str                      # cited · not_found · rejected
    cited: list[Evidence]
    attempts: int
    issues: list[str]                # 시도별 인용 규칙 위반 내용


def retry_message(issue: str) -> HumanMessage:
    return HumanMessage(
        f"직전 답변은 규칙을 어겼다: {issue}. "
        "근거 목록에 있는 번호만 써서, 사실을 말하는 문장마다 [근거 N]을 붙여 다시 답하라. "
        f"근거로 답할 수 없으면 \"{NOT_FOUND_SENTENCE}\"로 시작하라.")


def generate_validated(model: BaseChatModel, messages: list, evidences: list[Evidence]) -> dict:
    """답변 생성 + 인용 검증 + 1회 재생성 (모듈 설명의 '답변 검증 정책').

    질의응답과 특화 기능(빛의 편지 등)이 같은 정책을 쓴다.
    돌려주는 값: answer · status · cited · attempts · issues
    """
    issues: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        reply = model.invoke(messages)
        cited = resolve_citations(reply.content, evidences)
        not_found = is_not_found(cited.text)
        issue = citation_issue(cited, not_found)
        if issue is None:
            return {"answer": cited.text, "status": "not_found" if not_found else "cited",
                    "cited": cited.cited, "attempts": attempt, "issues": issues}
        issues.append(issue)
        messages = [*messages, AIMessage(reply.content), retry_message(issue)]
    # 재생성도 규칙을 어겼다 — 근거 없는 본문을 내보내지 않는다
    return {"answer": REJECTED_ANSWER, "status": "rejected", "cited": [], "attempts": MAX_ATTEMPTS, "issues": issues}


def default_chat_model(llm: BaseChatModel | None) -> BaseChatModel:
    if llm is not None:
        return llm
    from vasthorizon.llm import chat_model
    return chat_model()


def build_graph(llm: BaseChatModel | None = None, embedding: Embeddings | None = None,
                db: chromadb.ClientAPI | None = None):
    """llm · embedding · db를 넘기지 않으면 실행할 때 GMS · 기본 Chroma를 쓴다 (테스트는 가짜를 넣는다)."""

    def retrieve(state: RagState) -> dict:
        found = retrieve_evidence(state["item"], state["question"], embedding=embedding, db=db,
                                  search_type=state.get("search_type"))
        return {"evidences": found.evidences, "doc_search": found.doc_search,
                "warnings": state.get("warnings", []) + found.warnings}

    def generate(state: RagState) -> dict:
        messages = answer_messages(state["item"], state["question"], state["evidences"], state.get("history"))
        return generate_validated(default_chat_model(llm), messages, state["evidences"])

    graph = StateGraph(RagState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    return graph.compile()
