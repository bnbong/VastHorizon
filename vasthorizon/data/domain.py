"""도메인(우주)에 묶인 표현 — 프롬프트의 역할 · 항목 설명. (NF2005)

RAG 파이프라인 코드는 이 모듈의 값만 가져다 쓴다. 다른 도메인으로 옮길 때는 여기만 바꾼다.
"""

from __future__ import annotations

from vasthorizon.data.item_text import display_name
from vasthorizon.data.items.common import GROUPS

DOMAIN = "우주 — 천체 · 별자리 · 인류의 우주 탐사"
EXPERT_ROLE = "천문학 해설사"
EXPERT_DESCRIPTION = (
    "너는 천체 · 별자리 · 우주 탐사를 일반인에게 정확하게 설명하는 천문학 해설사다. "
    "한국어 위키백과에서 근거 문서를 찾는 일을 돕는다."
)

# 답변 생성 역할 — VastHorizon의 원칙 "위로를 지어내지 않는다. 사실로 위로한다."
ANSWER_PERSONA = (
    "너는 VastHorizon의 천문학 해설사다. 사용자가 고른 천체 · 별자리 · 우주 탐사에 대해, "
    "검색된 근거 문서에 적힌 사실만으로 답한다. 사실은 근거로만 말하고, 말투는 따뜻하게 한다. "
    "지어낸 위로나 감상은 틀린 사실을 퍼뜨릴 수 있으므로 쓰지 않는다."
)
NOT_FOUND_SENTENCE = "제공된 문서에서는 확인되지 않습니다."


# 시연용 대표 항목 — 기획안 7장 '근거가 필요한 질문'과 화면 시연에 쓰는 항목.
# 이 항목들의 자체 문서는 미리 색인해 첫 질문의 응답 시간을 줄인다. (scripts/index_docs.py --demo)
DEMO_ITEMS = [
    "아리랑 1호", "제임스 웹 우주망원경", "보이저 1호", "플레이아데스 성단", "오리온자리",
    "땅꾼자리", "알타이르", "베가", "베텔게우스", "안드로메다 은하", "다누리 (우주선)", "톈궁 1호",
]


def item_brief(item: dict) -> str:
    """프롬프트에 넣을 항목 한 줄 설명 — 이름 · 그룹 · 종류 · 대표 속성."""
    attrs = item.get("attrs", {})
    parts = [GROUPS[item["group"]], item.get("kind") or ""]
    for key in ("별자리", "국가", "발사일", "현재 위치", "메시에 번호"):
        if attrs.get(key):
            parts.append(f"{key} {attrs[key]}")
    english = f" / {item['name_en']}" if item.get("name_en") else ""
    return f"{display_name(item['name'])}{english} ({' · '.join(p for p in parts if p)})"
