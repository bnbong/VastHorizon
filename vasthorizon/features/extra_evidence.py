"""질의응답의 추가 근거 — 색인 밖에서 계산하는 근거를 항목 종류에 따라 붙인다.

| 항목                         | 추가 근거                                                      |
|------------------------------|----------------------------------------------------------------|
| Horizons로 계산하는 천체 · 탐사선 | 질문한 날의 실시간 위치 (features/live_position.py)            |
| 별자리                       | 선을 이루는 별들의 실제 거리표 — 별자리 펼치기와 같은 표         |

별자리 거리표는 F2015 비교에서 '오리온자리 별들은 서로 가까이 모여 있나?'에 근거가 없다고 답한 것을 보고 더했다.
같은 데이터가 펼치기 화면에는 있는데 질의응답 근거에는 없었기 때문이다. (재색인 필요 없음, LLM 호출 없음)
"""

from __future__ import annotations

from functools import lru_cache

from vasthorizon.data.constellation_figures import figure_stats, load_figures
from vasthorizon.features.constellation import FIGURE_SOURCE_URL, star_table
from vasthorizon.features.evidence import computed_evidence
from vasthorizon.features.live_position import live_evidence


@lru_cache(maxsize=1)
def _figures() -> dict:
    return load_figures()


def figure_evidence(item: dict, figures: dict | None = None):
    if item.get("group") != "constellation":
        return None
    figure = (figures if figures is not None else _figures()).get(item["id"])
    if not figure:
        return None
    stats = figure_stats(figure)
    if stats["known"] < 2:
        return None
    return computed_evidence(0, f"{item['name']} 별 거리표", star_table(figure, stats),
                             chunk_id=f"figure:{item['id']}", url=FIGURE_SOURCE_URL)


def extra_evidence(item: dict):
    """(근거 | None, 경고 | None) — retrieve_evidence 의 live 인자로 쓴다."""
    ev = figure_evidence(item)
    if ev is not None:
        return ev, None
    return live_evidence(item)
