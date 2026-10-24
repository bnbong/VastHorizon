"""성군(아스테리즘) · 별 묶음 이름 → 카탈로그 항목 이름. (조건 탐색)

카탈로그에는 '여름 삼각형' 같은 성군 항목이 없다. 그래서 질문에 성군 이름이 나오면 구성 천체를 찾아 카드로 보여 준다.
- 구성 천체 이름은 카탈로그(data/items.json)의 한국어 표시 이름이다. 카탈로그에 없는 별은 넣지 않는다.
  (북두칠성의 메그레즈, 남두육성의 눈키 밖 다섯 별은 카탈로그에 없어 별자리 항목으로 잇는다)
- 별칭은 한국어 · 영어 이름. 띄어쓰기는 비교할 때 무시한다.
- 이 표에 없는 묶음은 필터 추출 LLM의 members가 안전망이다 (features/explore.py).
"""

from __future__ import annotations

# 대표 이름 → (별칭, 구성 천체 이름) — 대표 이름은 카드 이유 문구에 쓴다
ASTERISMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "여름 삼각형": (
        ("여름의 대삼각형", "여름 대삼각형", "여름철 대삼각형", "Summer Triangle"),
        ("베가", "데네브", "알타이르"),
    ),
    "겨울 대삼각형": (
        ("겨울의 대삼각형", "겨울 삼각형", "겨울철 대삼각형", "Winter Triangle"),
        ("시리우스", "베텔게우스", "프로키온"),
    ),
    "겨울 다이아몬드": (
        ("겨울의 다이아몬드", "겨울 육각형", "겨울의 육각형", "겨울철 대육각형", "Winter Hexagon", "Winter Circle"),
        ("시리우스", "프로키온", "폴룩스", "카펠라", "알데바란", "리겔"),
    ),
    "봄의 대삼각형": (
        ("봄 대삼각형", "봄 삼각형", "봄철 대삼각형", "Spring Triangle"),
        ("아르크투루스", "스피카", "데네볼라"),
    ),
    "봄의 대곡선": (
        ("봄 대곡선", "Spring Arc", "Arc to Arcturus"),
        ("아르크투루스", "스피카"),
    ),
    "북두칠성": (
        ("Big Dipper", "Plough"),
        ("두베", "메라크", "페크다", "알리오스", "미자르", "알카이드", "큰곰자리"),
    ),
    "남두육성": (
        ("Milk Dipper",),
        ("눈키", "궁수자리"),
    ),
    "오리온 벨트": (
        ("오리온자리 벨트", "삼태성", "Orion's Belt", "Belt of Orion"),
        ("알니타크", "알닐람", "민타카"),
    ),
}


def asterism_aliases() -> list[tuple[str, str]]:
    """(별칭, 대표 이름) 목록 — 대표 이름 자신도 별칭으로 넣는다."""
    return [(alias, name) for name, (aliases, _) in ASTERISMS.items() for alias in (name, *aliases)]


def asterism_members(name: str) -> tuple[str, ...]:
    return ASTERISMS[name][1]
