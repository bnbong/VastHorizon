"""별자리 선의 별 — 카탈로그 밖의 별도 하나의 천체로. (오늘 밤 하늘에서 누른 별에 대해 바로 물어보기)

카탈로그(424건)에는 밝은 별 94개만 있지만, 하늘에서 누를 수 있는 별자리 선의 별은 756개다 (중복 제외).
카탈로그 밖의 별은 별자리 모양 데이터(data/constellations.json)로 '임시 항목'을 만든다.

| 항목 필드   | 값                                                            |
|-------------|---------------------------------------------------------------|
| id          | hip:<히파르코스 번호>                                          |
| wiki_title  | Wikidata에 연결된 한국어 위키 문서 (없으면 None — 문서 검색만) |
| distance    | Wikidata 거리(연주시차로 검증) — 별자리 모양 데이터와 같은 값   |
| adhoc       | True — 질의응답의 근거 1을 색인이 아니라 이 데이터로 만든다     |

임시 항목은 문서 수집 · 색인 · 대화 기록에서 일반 항목과 똑같이 쓰인다 (항목 ID로 구분).
"""

from __future__ import annotations

import re

from vasthorizon.data.items.common import LY_KM

STAR_ID = re.compile(r"^hip:(\d+)$")


def star_index(figures: dict) -> dict[int, tuple[dict, dict]]:
    """히파르코스 번호 → (별, 그 별이 속한 별자리 모양). 카탈로그 별은 빼지 않는다 (호출 쪽이 고른다)."""
    index: dict[int, tuple[dict, dict]] = {}
    for figure in figures.values():
        for star in figure["stars"].values():
            index.setdefault(int(star["hip"]), (star, figure))
    return index


def star_item(item_id: str, index: dict[int, tuple[dict, dict]], ref_year: int) -> dict | None:
    m = STAR_ID.match(item_id or "")
    if not m or int(m.group(1)) not in index:
        return None
    star, figure = index[int(m.group(1))]
    if not star.get("distance_ly"):
        return None
    km = star["distance_ly"] * LY_KM
    return {
        "id": item_id, "group": "star", "kind": "항성", "adhoc": True, "ref_year": ref_year,
        "name": star["name"], "name_en": None, "wiki_title": star.get("wiki_title"),
        "ra_deg": star["ra_deg"], "dec_deg": star["dec_deg"],
        "distance": {"km": km, "ly": star["distance_ly"], "basis": star.get("distance_basis") or "wikidata",
                     "reference": "지구에서 천체까지", "approximate": False, "method": None,
                     "km_min": None, "km_max": None, "n_values": 1},
        "attrs": {"히파르코스 번호": f"HIP {star['hip']}", "별자리": figure["name"], "겉보기 등급": star["mag"],
                  "맨눈 관측": star["mag"] <= 6.0},
        "sources": [{"name": "Wikidata", "url": "https://www.wikidata.org/", "used_for": "거리 (연주시차로 검증)"},
                    {"name": "d3-celestial", "url": "https://github.com/ofrohn/d3-celestial", "used_for": "좌표 · 등급"}],
    }
