"""항목 공통 구조와 단위 변환."""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field

LY_KM = 9_460_730_472_580.8          # 1광년 (km)
AU_KM = 149_597_870.7                # 1천문단위 (km)
EARTH_RADIUS_KM = 6_371.0

GROUPS = {
    "solar_system": "태양계",
    "human_made": "인류의 발자취",
    "star": "별",
    "messier": "메시에 천체",
    "constellation": "별자리",
}


# 거리의 기준 — 무엇에서 무엇까지 잰 값인지 (Distance.reference)
REF_FROM_EARTH = "지구에서 천체까지"
REF_GEOCENTER = "지구 중심에서 천체 중심까지"
REF_SURFACE_ALTITUDE = "지표면 위 궤도 고도"


@dataclass
class Distance:
    """지구로부터의 거리.

    - reference: 무엇에서 무엇까지의 거리인지 (지구 중심 거리인지, 지표 고도인지)
    - approximate: 대상 자체를 직접 잰 값이 아니면 True, method에 근사 방법을 적는다
    - 출처마다 값이 다르면 중앙값과 범위(km_min ~ km_max)를 함께 둔다
    """

    km: float
    basis: str                       # 근거 — wikidata / parallax / horizons / satcat / parent_body / lagrange
    reference: str = REF_FROM_EARTH
    approximate: bool = False
    method: str | None = None
    km_min: float | None = None
    km_max: float | None = None
    n_values: int = 1

    @property
    def ly(self) -> float:
        return self.km / LY_KM


@dataclass
class Item:
    id: str                          # Wikidata QID — 색인 청크 ID로도 쓴다 (F2002)
    group: str
    name: str                        # 한국어 이름 (한국어 위키 문서 제목 기준)
    wiki_title: str                  # 연결된 한국어 위키 문서 (F2004 항목 자체 문서)
    name_en: str | None = None
    kind: str | None = None          # 세부 종류 — 행성 · 산개성단 · 우주 탐사선 …
    distance: Distance | None = None
    ra_deg: float | None = None      # 적경 · 적위 — 하늘에서의 방향
    dec_deg: float | None = None
    # 대상 자체의 실제 위치 (태양 중심 ICRF, AU). 직접 계산한 값만 넣는다.
    position_au: list[float] | None = None
    position_basis: str | None = None        # position_au의 근거 — 현재는 "horizons"뿐
    # 실제 위치를 모를 때 쓸 수 있는 근삿값 — {"body", "position_au", "method"}
    # 예: 탐사선 궤도력이 없어 모천체(달)의 위치로 대신한 경우. 실제 좌표와 섞지 않는다.
    position_proxy: dict | None = None
    attrs: dict = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.distance:
            data["distance"]["ly"] = self.distance.ly
        return data


def distance_from_values(values_km: list[float], basis: str) -> Distance | None:
    values = sorted(v for v in values_km if v and v > 0)
    if not values:
        return None
    if len(values) == 1:
        return Distance(km=values[0], basis=basis)
    return Distance(km=statistics.median(values), basis=basis,
                    method=f"출처 {len(values)}개 값의 중앙값",
                    km_min=values[0], km_max=values[-1], n_values=len(values))


def parallax_to_km(parallax_mas: float) -> float:
    """연주시차(밀리각초) → 거리(km). 1파섹 = 3.2616광년."""
    parsec_ly = 3.261563777
    return (1000.0 / parallax_mas) * parsec_ly * LY_KM


def vector_norm(v: list[float]) -> float:
    return math.sqrt(sum(c * c for c in v))


def vector_sub(a: list[float], b: list[float]) -> list[float]:
    return [x - y for x, y in zip(a, b)]


def first_float(value: str | None) -> float | None:
    """빈 값 · 숫자가 아닌 값은 None."""
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None
