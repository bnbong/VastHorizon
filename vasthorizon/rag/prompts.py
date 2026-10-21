"""프롬프트 세 개 — 검색어 추출 · 후보 선별 · 답변 생성.

| 프롬프트        | 역할                                         | 출력 형식                                   |
|-----------------|----------------------------------------------|---------------------------------------------|
| ① 검색어 추출   | 도메인 전문가가 항목과 질문에서 위키 검색어를 뽑음 | {"queries": ["검색어", ...]}                |
| ② 후보 선별     | 제목 · 요약만 보고 색인할 문서를 고름          | {"selected": ["후보 ID", ...], "reason": ""} |
| ③ 답변 생성     | (6번 작업에서 추가)                           |                                             |

선별을 따로 두는 이유: 본문을 받기 전에 버릴 문서를 정해 외부 호출 수를 줄인다.
도메인 표현(역할 · 항목 설명)은 vasthorizon.data.domain에서 가져온다.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from vasthorizon.data.docs import Candidate
from vasthorizon.data.domain import EXPERT_DESCRIPTION, item_brief

# ── ① 검색어 추출 (F2003) ───────────────────────────────────────────────────

QUERY_SYSTEM = f"""{EXPERT_DESCRIPTION}

할 일: 사용자가 고른 항목과 질문에 답하는 데 필요한 한국어 위키백과 문서의 검색어를 뽑는다.

규칙
- 검색어는 한국어 위키백과 문서 제목처럼 짧은 명사구로 쓴다. 질문 문장을 그대로 쓰지 않는다.
- 항목 자체 문서는 따로 수집하므로, 질문에 답하려면 더 필요한 개념 · 사건 · 관련 천체를 고른다.
  예: "보이저 1호는 태양계를 벗어났나?" → "태양권계면", "성간 매질", "오르트 구름"
- 최대 {{max_queries}}개. 필요 없으면 적게 낸다.
- JSON 객체 하나만 출력한다. 형식: {{"queries": ["검색어1", "검색어2"]}}"""


def query_messages(item: dict, question: str, max_queries: int) -> list:
    return [
        SystemMessage(QUERY_SYSTEM.replace("{max_queries}", str(max_queries))),
        HumanMessage(f"항목: {item_brief(item)}\n질문: {question}"),
    ]


# ── ② 후보 선별 (F2004) ─────────────────────────────────────────────────────

SELECT_SYSTEM = f"""{EXPERT_DESCRIPTION}

할 일: 위키백과 검색 후보의 제목과 요약만 보고, 질문에 답하는 근거로 색인할 문서를 고른다.

고르는 순서
1. 질문에 대한 답(사실 · 수치 · 정의)이 들어 있을 문서
2. 그 답을 이해하는 데 필요한 핵심 개념 문서
3. 항목과 관련은 있지만 질문과 거리가 먼 문서(일화 · 다른 탐사선 · 일반 개론)는 자리가 남을 때만

규칙
- 이름만 같은 다른 주제(노래 · 영화 · 인물 등)는 버린다.
- 최대 {{max_selected}}개. 관련 문서가 없으면 빈 배열을 낸다.
- 후보에 없는 ID를 지어내지 않는다.
- JSON 객체 하나만 출력한다. 형식: {{"selected": ["후보 ID", ...], "reason": "한 문장"}}"""


def select_messages(item: dict, question: str, candidates: list[Candidate], max_selected: int) -> list:
    listing = [{"id": c.doc_id, "title": c.title, "summary": c.summary[:300]} for c in candidates]
    return [
        SystemMessage(SELECT_SYSTEM.replace("{max_selected}", str(max_selected))),
        HumanMessage(f"항목: {item_brief(item)}\n질문: {question}\n후보:\n"
                     + json.dumps(listing, ensure_ascii=False, indent=1)),
    ]
