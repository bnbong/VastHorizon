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


def item_brief(item: dict) -> str:
    """프롬프트에 넣을 항목 한 줄 설명 — 이름 · 그룹 · 종류 · 대표 속성."""
    attrs = item.get("attrs", {})
    parts = [GROUPS[item["group"]], item.get("kind") or ""]
    for key in ("별자리", "국가", "발사일", "현재 위치", "메시에 번호"):
        if attrs.get(key):
            parts.append(f"{key} {attrs[key]}")
    english = f" / {item['name_en']}" if item.get("name_en") else ""
    return f"{display_name(item['name'])}{english} ({' · '.join(p for p in parts if p)})"
