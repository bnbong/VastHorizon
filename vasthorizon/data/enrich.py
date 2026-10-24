"""카탈로그 보강 — 수집한 항목에 조건 탐색용 사실(블랙홀 · 고리 · 위성 수 · 탐사선 방문 · 서울 관측)을 덧붙인다.

수집(scripts/collect_items.py)은 Wikidata 기본 속성만 모은다. 그래서 "블랙홀이 발견된 천체", "고리가 있는 행성",
"한국에서 보이는 별자리" 같은 조건은 데이터가 없어 찾을 수 없었다. 이 모듈이 다음 둘을 합친다.
  - enrich.json: 사람이 출처를 확인해 적은 사실 (항목 QID → attrs, sources). 값마다 출처를 sources에 남긴다
  - 계산: '서울에서_관측' (불리언) — 적위로 계산한다. 별자리는 수집 때 경계로 계산한 '서울에서 관측' 문구를 구조화한다

수집 · 색인 · 보강 스크립트가 모두 이 함수를 거친다. 여러 번 적용해도 결과가 같다 (멱등).
items.json을 다시 수집해도 보강이 사라지지 않도록 사실은 이 파일 옆의 enrich.json에 둔다.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

from vasthorizon.data.items.constellations import SEOUL_LAT

ENRICH_PATH = Path(__file__).with_name("enrich.json")
SEOUL_KEY = "서울에서_관측"
# 수집 때 별자리 경계로 계산한 문구 — 별자리 전체가 지평선 위로 오르면 '보인다'로 본다 (일부만 보이면 False)
SEOUL_TEXT = {"전체 관측 가능": True, "일년 내내 보임 (주극 별자리)": True, "일부만 관측 가능": False, "관측 불가": False}


@lru_cache(maxsize=1)
def enrichment() -> dict[str, dict]:
    """항목 QID → {"name", "attrs", "sources", "quote"?}"""
    return json.loads(ENRICH_PATH.read_text(encoding="utf-8"))["items"]


def rises_over_seoul(dec_deg: float) -> bool:
    """남중 고도가 0°보다 높은가 — 서울(북위 SEOUL_LAT°)에서 지평선 위로 떠오르는가."""
    return dec_deg > SEOUL_LAT - 90


def seoul_visible(item: dict) -> bool | None:
    """서울에서 관측 가능 여부. 모르면 None (태양계 천체 · 인공 천체는 계산하지 않는다)."""
    attrs = item.get("attrs") or {}
    if item["group"] == "constellation":
        return SEOUL_TEXT.get(attrs.get("서울에서 관측") or "")
    if item["group"] in ("star", "messier") and item.get("dec_deg") is not None:
        return rises_over_seoul(float(item["dec_deg"]))
    return None


def enrich_item(item: dict, table: dict[str, dict] | None = None) -> dict:
    """보강한 사본. 값이 None인 보강 속성은 지운다 (예: 아직 방문하지 않은 아포피스의 '탐사선 방문')."""
    table = enrichment() if table is None else table
    out = copy.deepcopy(item)
    attrs = out.setdefault("attrs", {})
    extra = table.get(item["id"])
    if extra:
        for key, value in extra.get("attrs", {}).items():
            if value is None:
                attrs.pop(key, None)
            else:
                attrs[key] = value
        sources = out.setdefault("sources", [])
        have = {(s.get("name"), s.get("url")) for s in sources}
        for src in extra.get("sources", []):
            if (src["name"], src["url"]) not in have:
                sources.append(dict(src))
                have.add((src["name"], src["url"]))
    visible = seoul_visible(out)
    if visible is None:
        attrs.pop(SEOUL_KEY, None)
    else:
        attrs[SEOUL_KEY] = visible
    return out


def enrich_items(items: list[dict], table: dict[str, dict] | None = None) -> list[dict]:
    return [enrich_item(it, table) for it in items]
