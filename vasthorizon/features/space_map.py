"""우주 지도 배치 (3D 화면) — 항목마다 지구에서 본 방향(단위 벡터)과 거리.

화면은 거리를 로그 스케일로 줄여 그린다. 방향은 실제 방향을 쓰고, 모르면 숨기지 않고 표시 방식으로 알린다.

| placement     | 방향의 근거                                       | 해당 항목                      |
|---------------|---------------------------------------------------|--------------------------------|
| origin        | 지구 — 화면의 중심 '나'                            | 지구                           |
| sky           | 적경 · 적위 (적도 좌표)                            | 별 · 메시에 천체               |
| computed      | Horizons 위치(태양 중심) − 지구 위치               | 태양계 천체 · 심우주 탐사선    |
| proxy         | 모천체 위치로 대신한 근삿값 (예: 달 궤도선 → 달)   | 궤도력이 없는 탐사선           |
| illustrative  | 궤도 정보가 없어 항목 ID로 정한 고정 방향 (예시)   | 지구 궤도 위성 (지표 고도)     |

배치하지 못한 항목(거리 · 위치 모름, 대기권 재진입 등)은 unplaced로 따로 돌려준다.
좌표계: 적도 좌표(ICRF) — x는 춘분점(적경 0), z는 천구 북극. 화면 좌표 변환은 프론트가 한다.
"""

from __future__ import annotations

import hashlib
import math

from vasthorizon.data.items.common import AU_KM, LY_KM, REF_SURFACE_ALTITUDE, vector_norm, vector_sub

# 거리 고리 — 거리 사다리
RINGS = [
    {"label": "1광초 · 달까지", "km": 299_792.458},
    {"label": "1광분 · 태양은 8.3광분", "km": 299_792.458 * 60},
    {"label": "1광일 · 인류가 만든 가장 먼 물체", "km": 299_792.458 * 86_400},
    {"label": "1광년", "km": LY_KM},
    {"label": "1천 광년 · 밤하늘의 별들", "km": 1_000 * LY_KM},
    {"label": "100만 광년 · 다른 은하", "km": 1_000_000 * LY_KM},
    # 관측 가능한 우주의 반지름(공변 거리) — 한국어 위키백과 「관측 가능한 우주」
    {"label": "관측 가능한 우주의 끝 · 약 465억 광년", "km": 46_500_000_000 * LY_KM, "edge": True},
]
OBSERVABLE_UNIVERSE_SOURCE = "https://ko.wikipedia.org/wiki/관측_가능한_우주"


def direction_from_radec(ra_deg: float, dec_deg: float) -> list[float]:
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    return [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]


def unit(v: list[float]) -> list[float] | None:
    n = vector_norm(v)
    return [c / n for c in v] if n > 0 else None


def illustrative_direction(item_id: str) -> list[float]:
    """항목 ID로 정한 고정 방향 — 구 위에 고르게 퍼진다. 실제 방향이 아니다."""
    digest = hashlib.sha256(item_id.encode()).digest()
    u, w = int.from_bytes(digest[:4], "big") / 2**32, int.from_bytes(digest[4:8], "big") / 2**32
    z, phi = 2 * u - 1, 2 * math.pi * w
    r = math.sqrt(1 - z * z)
    return [r * math.cos(phi), r * math.sin(phi), z]


def _from_earth(position_au: list[float] | None, earth: list[float] | None) -> list[float] | None:
    """태양 중심 위치 → 지구에서 본 벡터. 위치를 모르거나 지구와 같은 점이면 None."""
    if not position_au or not earth:
        return None
    geo = vector_sub(position_au, earth)
    return geo if vector_norm(geo) > 0 else None


def _point(item: dict, direction: list[float] | None, km: float, placement: str) -> dict:
    attrs = item.get("attrs", {})
    # 태양계 천체 — 하늘 보기가 그날의 지구 위치를 빼 방향을 다시 계산하도록 태양 중심 위치(ICRF 적도, AU)와 그 기준일을 함께 준다
    extra = {"position_au": item["position_au"], "epoch": attrs.get("Horizons 위치 기준일")} \
        if item["group"] == "solar_system" and item.get("position_au") else {}
    return {**extra, "id": item["id"], "name": item["name"], "group": item["group"], "kind": item.get("kind"),
            "dir": [round(c, 6) for c in direction] if direction else [0.0, 0.0, 0.0],
            "km": km, "ly": km / LY_KM, "placement": placement,
            "mag": attrs.get("겉보기 등급"), "naked_eye": attrs.get("맨눈 관측"),
            # 하늘 데이터(web/data)의 별 · 성운과 잇는 번호 — "M45" · "HIP 32349"
            "code": attrs.get("메시에 번호") or attrs.get("히파르코스 번호"),
            # 가까이 갔을 때의 모습 — 별의 색(분광형)
            "spectral": attrs.get("분광형")}


def map_points(items: list[dict]) -> dict:
    earth = next((it.get("position_au") for it in items if it["group"] == "solar_system" and it["name"] == "지구"), None)
    points, unplaced = [], []
    for it in items:
        if it["group"] == "constellation":
            continue                                   # 별자리는 천구 보기에서 그린다
        dist = it.get("distance") or {}
        km = dist.get("km")
        if it["group"] == "solar_system" and it["name"] == "지구":
            points.append(_point(it, None, 0.0, "origin"))
        elif it.get("ra_deg") is not None and it.get("dec_deg") is not None and km:
            points.append(_point(it, direction_from_radec(it["ra_deg"], it["dec_deg"]), km, "sky"))
        elif km and dist.get("reference") == REF_SURFACE_ALTITUDE:
            # 지구 궤도 위성 — 모천체가 지구라 근삿값 방향도 없다 (지구 − 지구 = 0)
            points.append(_point(it, illustrative_direction(it["id"]), km, "illustrative"))
        elif (geo := _from_earth(it.get("position_au"), earth)) is not None:
            points.append(_point(it, unit(geo), km or vector_norm(geo) * AU_KM, "computed"))
        elif km and (geo := _from_earth((it.get("position_proxy") or {}).get("position_au"), earth)) is not None:
            points.append(_point(it, unit(geo), km, "proxy"))
        else:
            unplaced.append({"id": it["id"], "name": it["name"], "group": it["group"],
                             "reason": it.get("attrs", {}).get("현재 위치") or "거리 · 위치 정보 없음"})
    return {"points": points, "unplaced": unplaced, "rings": RINGS,
            "observable_universe_source": OBSERVABLE_UNIVERSE_SOURCE}


def constellation_list(figures: dict) -> list[dict]:
    """천구 보기용 — 별자리 88개의 선과 별 (거리 포함, 펼치기에도 쓴다)."""
    keys = ("hip", "name", "item_id", "ra_deg", "dec_deg", "mag", "distance_ly")
    return [{"item_id": item_id, "name": fig["name"], "lines": fig["lines"],
             "stars": [{k: s.get(k) for k in keys} for s in fig["stars"].values()]}
            for item_id, fig in figures.items()]
