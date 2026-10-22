"""실시간 위치 근거 — 질문하는 날의 위치를 JPL Horizons로 계산한다.

카탈로그의 위치는 수집 기준일 값이다. 보이저 1호는 하루에 약 150만 km씩 멀어지므로
"지금 얼마나 멀리 있나"에는 질문하는 날의 값이 맞다. (9번 작업 — 사용자 피드백)

| 대상                                     | 동작                                               |
|------------------------------------------|----------------------------------------------------|
| Horizons로 위치를 직접 계산한 항목 (52개) | 오늘(UTC) 위치를 계산해 근거로 추가 — LLM 호출 없음 |
| 그 밖의 항목 · 지구 자신                  | 추가하지 않음                                       |
| Horizons 응답 실패                        | 경고를 남기고 수집일 값만으로 답한다                 |

같은 날 같은 대상은 data/raw 캐시를 다시 쓴다 (sources.horizons_position — 대상 · 날짜별 캐시).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import requests

from vasthorizon.data import sources
from vasthorizon.data.item_text import korean_number, light_time_text
from vasthorizon.data.items.common import AU_KM, vector_norm, vector_sub
from vasthorizon.data.items.human_made import HORIZONS_SPACECRAFT
from vasthorizon.rag.retrieval import KIND_ITEM, Evidence

EARTH_COMMAND = "399"
SOURCE_TYPE = "JPL Horizons 실시간 계산"
HORIZONS_URL = "https://ssd.jpl.nasa.gov/horizons/"
LIVE_ERRORS = (requests.RequestException, ValueError, KeyError)


def horizons_command(item: dict) -> str | None:
    """이 항목을 Horizons로 계산할 수 있으면 그 명령(대상 ID). 지구 자신은 None."""
    if item.get("position_basis") != "horizons":
        return None
    attrs = item.get("attrs", {})
    command = attrs.get("horizons_id") or HORIZONS_SPACECRAFT.get(attrs.get("COSPAR ID", ""))
    return None if command in (None, EARTH_COMMAND) else command


def live_evidence(item: dict, today: date | None = None) -> tuple[Evidence | None, str | None]:
    """(근거, 경고). 계산 대상이 아니면 (None, None)."""
    command = horizons_command(item)
    if command is None:
        return None, None
    day = (today or datetime.now(timezone.utc).date()).isoformat()
    try:
        target = sources.horizons_position(command, day)
        earth = sources.horizons_position(EARTH_COMMAND, day)
    except LIVE_ERRORS:
        target = earth = None
    if not target or not earth:
        return None, f"{item['name']}의 오늘 위치를 계산하지 못해 수집 기준일 값으로 답합니다."

    from_earth = vector_norm(vector_sub(target, earth)) * AU_KM
    from_sun = vector_norm(target) * AU_KM
    lines = [f"{day} 기준 (질문한 날 JPL Horizons로 계산)",
             f"지구로부터 거리: 약 {korean_number(from_earth)}km ({from_earth:,.0f}km)",
             f"태양으로부터 거리: 약 {korean_number(from_sun)}km ({from_sun / AU_KM:.1f}천문단위)",
             f"빛이 지구까지 걸리는 시간: {light_time_text(from_earth)}"]
    collected = item.get("attrs", {}).get("Horizons 위치 기준일")
    if collected and collected != day and item.get("distance"):
        change = from_earth - item["distance"]["km"]
        lines.append(f"수집 기준일({collected}) 값과 비교: 지구로부터 약 {korean_number(abs(change))}km "
                     f"{'멀어짐' if change > 0 else '가까워짐'}")
    title = f"{item['name']} 오늘 위치"
    return Evidence(number=0, chunk_id=f"live:{item['id']}:{day}", kind=KIND_ITEM, source_type=SOURCE_TYPE,
                    title=title, section="", url=HORIZONS_URL, text=f"[{title}]\n" + "\n".join(lines)), None
