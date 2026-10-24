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
    id: str                          # Wikidata QID — 색인 청크 ID로도 쓴다
    group: str
    name: str                        # 한국어 이름 (한국어 위키 문서 제목 기준)
    wiki_title: str                  # 연결된 한국어 위키 문서 (항목 자체 문서)
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


PARALLAX_TOLERANCE = 1.5     # 거리 값과 연주시차 거리가 이 배수 안이면 서로 맞는다고 본다
PARALLAX_ANCHOR_MAS = 5.0    # 이보다 작은(먼) 연주시차는 오차가 커서 검증 기준으로 쓰지 않는다 (약 650광년)


def distance_with_parallax(values_km: list[float], parallax_mas: float | None) -> Distance | None:
    """별의 거리 — 출처 거리 값을 연주시차(독립 측정)로 검증한다.

    Wikidata 거리 값에 단위 · 자릿수가 틀린 값이 섞이면 중앙값 · 범위가 엉뚱해진다.
    (예: 타비트 — 8파섹 값 3개와 39,533파섹 값 3개 → 중앙값 약 6.4만 광년, 실제 약 26광년)

    | 연주시차                       | 처리                                                        |
    |--------------------------------|-------------------------------------------------------------|
    | 없음                           | 출처 값의 중앙값 · 범위 그대로 (검증 없음)                   |
    | PARALLAX_ANCHOR_MAS 미만 (먼 별) | 측정 오차가 커서 검증 기준으로 쓰지 않는다 — 출처 값 그대로 |
    |                                | (예: 알니타크 — 4.43 → 736광년, 참고 값 약 1,260광년)       |
    | 그 이상 (검증 기준)            | 값마다 연주시차 거리와 PARALLAX_TOLERANCE배 안인지 본다.     |
    |                                | 맞는 값만으로 중앙값 · 범위 · 개수를 다시 계산하고,          |
    |                                | 뺀 값 수를 method에 남긴다. 맞는 값이 없으면 연주시차로 계산 |

    중앙값이 맞아도 개별 값을 모두 본다 — 범위(km_min ~ km_max)에 이상값이 남으면
    빛의 편지의 출발 연도 범위가 수만 년으로 벌어진다. (8b 리뷰)
    출처 값이 없으면 연주시차 크기와 관계없이 연주시차로 계산한다.
    """
    valid = [v for v in values_km if v and v > 0]
    dist = distance_from_values(valid, "wikidata")
    if not parallax_mas or parallax_mas <= 0:
        return dist
    plx_km = parallax_to_km(parallax_mas)
    if dist is None:
        return Distance(km=plx_km, basis="parallax", method=f"연주시차 {parallax_mas:g} 밀리각초로 계산")
    if parallax_mas < PARALLAX_ANCHOR_MAS:
        return dist

    consistent = [v for v in valid if 1 / PARALLAX_TOLERANCE <= v / plx_km <= PARALLAX_TOLERANCE]
    if len(consistent) == len(valid):
        return dist
    if consistent:
        picked = distance_from_values(consistent, "wikidata")
        picked.method = (f"연주시차와 맞는 출처 값 {len(consistent)}개의 중앙값 "
                         f"(어긋난 값 {len(valid) - len(consistent)}개 제외)")
        return picked
    return Distance(km=plx_km, basis="parallax",
                    method=f"출처 거리 값 {len(valid)}개가 연주시차와 크게 달라 연주시차 {parallax_mas:g} 밀리각초로 계산")


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
