"""오늘 밤 나의 하늘 — 내가 있는 곳 · 시각의 하늘에 떠 있는 별자리와 행성.

계산 (외부 호출 없음)
1. 시각 → 율리우스일(JD) → 그리니치 항성시(GMST) → 지방 항성시(LST = GMST + 경도)
2. 시간각 HA = LST − 적경
3. 고도 alt = asin(sin δ sin φ + cos δ cos φ cos HA)
   방위 az = atan2(−cos δ sin HA, sin δ cos φ − cos δ sin φ cos HA)   (북 0° → 동 90°)

| 대상     | 하늘 위치                                       | 정밀도                     |
|----------|-------------------------------------------------|----------------------------|
| 별자리   | 선을 이루는 별들의 방향 평균 (없으면 항목 좌표) | 별자리 안내에 충분          |
| 행성     | Horizons 위치(기준일)를 지구 중심으로 옮긴 값   | 기준일 ±3일 안에서만 쓴다  |
| 태양     | 저정밀 태양 위치식 (약 0.01도)                  | 낮 · 밤 판정용             |
| 달       | 쓰지 않음 — 하루 13도씩 움직여 기준일 위치로는 틀린다 |                       |

판정
- 별자리는 고도 15도 이상, 행성은 5도 이상을 '보인다'로 본다 (지평선 근처는 건물 · 대기에 가린다).
- 고도 75도 이상은 방위 대신 '머리 위'로 안내한다 (천정 근처에서는 방위가 거의 의미 없다).
- 태양 고도가 −6도보다 높으면 낮 · 박명 — 안내 문장을 만들지 않는다 (LLM 호출 없음).
- 별자리 · 행성이 모두 없을 때만 빈 결과다. 행성만 보여도 안내한다.

안내 문장 근거
1. 하늘 위치 계산표 (코드가 계산한 별자리 · 행성의 방향 · 높이)
2~. 높이 뜬 별자리의 항목 텍스트 (관측 계절 · 가장 밝은 별 …) — 별자리가 없으면 없다
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from langchain_core.language_models import BaseChatModel

from vasthorizon.data.items.common import vector_sub
from vasthorizon.features.evidence import catalog_evidence, computed_evidence
from vasthorizon.rag.graph import default_chat_model, generate_validated
from vasthorizon.rag.prompts import sky_messages
from vasthorizon.rag.retrieval import Evidence

KST = timezone(timedelta(hours=9))
CONSTELLATION_MIN_ALT = 15.0
PLANET_MIN_ALT = 5.0
ZENITH_ALT = 75.0
OVERHEAD = "머리 위"
NIGHT_SUN_ALT = -6.0           # 시민박명 끝
PLANET_EPOCH_DAYS = 3
NAKED_EYE_PLANETS = ("수성", "금성", "화성", "목성", "토성")
GUIDE_CONSTELLATIONS = 4       # 안내 근거로 항목 텍스트를 넣는 별자리 수
TABLE_CONSTELLATIONS = 10
DIRECTIONS = ("북", "북동", "동", "남동", "남", "남서", "서", "북서")


class SkyInputError(ValueError):
    """위도 · 경도 · 시각이 올바르지 않다."""


@dataclass
class SkyObject:
    name: str
    item_id: str | None
    group: str
    alt_deg: float
    az_deg: float
    direction: str


@dataclass
class SkyView:
    lat: float
    lon: float
    at: datetime
    sun_alt_deg: float
    constellations: list[SkyObject]           # 보이는 별자리 — 높은 순
    planets: list[SkyObject]                  # 보이는 맨눈 행성 — 높은 순
    notes: list[str] = field(default_factory=list)

    @property
    def is_night(self) -> bool:
        return self.sun_alt_deg < NIGHT_SUN_ALT

    def place(self) -> str:
        return f"위도 {self.lat:.2f}도, 경도 {self.lon:.2f}도, {self.at.strftime('%Y-%m-%d %H:%M')} ({self.at.tzname()})"


@dataclass
class SkyGuide:
    view: SkyView
    guide: str | None
    status: str                                # cited · not_found · rejected · daytime · empty
    cited: list[Evidence] = field(default_factory=list)
    evidences: list[Evidence] = field(default_factory=list)
    attempts: int = 0
    warnings: list[str] = field(default_factory=list)


# ── 천문 계산 ─────────────────────────────────────────────────────────────

def as_aware(at: datetime | None) -> datetime:
    """시각이 없으면 지금, 시간대가 없으면 한국 시간(UTC+9)으로 본다."""
    if at is None:
        return datetime.now(KST)
    return at if at.tzinfo else at.replace(tzinfo=KST)


def julian_day(at: datetime) -> float:
    return at.timestamp() / 86400.0 + 2440587.5


def local_sidereal_deg(at: datetime, lon: float) -> float:
    gmst = 280.46061837 + 360.98564736629 * (julian_day(at) - 2451545.0)
    return (gmst + lon) % 360.0


def alt_az(ra_deg: float, dec_deg: float, lat: float, lst_deg: float) -> tuple[float, float]:
    ha, dec, phi = math.radians(lst_deg - ra_deg), math.radians(dec_deg), math.radians(lat)
    sin_alt = math.sin(dec) * math.sin(phi) + math.cos(dec) * math.cos(phi) * math.cos(ha)
    alt = math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))
    az = math.degrees(math.atan2(-math.cos(dec) * math.sin(ha),
                                 math.sin(dec) * math.cos(phi) - math.cos(dec) * math.sin(phi) * math.cos(ha)))
    return alt, az % 360.0


def direction(az_deg: float) -> str:
    return DIRECTIONS[int((az_deg + 22.5) % 360 // 45)]


def sun_ra_dec(at: datetime) -> tuple[float, float]:
    """저정밀 태양 위치 (천문연감 근사식, 약 0.01도)."""
    n = julian_day(at) - 2451545.0
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians((280.460 + 0.9856474 * n + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360)
    eps = math.radians(23.439 - 0.0000004 * n)
    ra = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))) % 360
    return ra, math.degrees(math.asin(math.sin(eps) * math.sin(lam)))


def vector_ra_dec(v: list[float]) -> tuple[float, float]:
    """ICRF(적도 좌표) 벡터 → 적경 · 적위."""
    x, y, z = v
    return math.degrees(math.atan2(y, x)) % 360, math.degrees(math.asin(z / math.sqrt(x * x + y * y + z * z)))


def mean_direction(stars: list[dict]) -> tuple[float, float]:
    """별들의 방향 평균 (단위 벡터 평균) — 적경 0도 · 360도 경계를 넘는 별자리도 맞게 나온다."""
    vec = [0.0, 0.0, 0.0]
    for s in stars:
        ra, dec = math.radians(s["ra_deg"]), math.radians(s["dec_deg"])
        vec[0] += math.cos(dec) * math.cos(ra)
        vec[1] += math.cos(dec) * math.sin(ra)
        vec[2] += math.sin(dec)
    return vector_ra_dec(vec)


# ── 하늘 위치 ─────────────────────────────────────────────────────────────

def _planet_epoch(items: list[dict]) -> date | None:
    for it in items:
        epoch = it.get("attrs", {}).get("Horizons 위치 기준일")
        if epoch:
            return date.fromisoformat(epoch)
    return None


def compute_sky(items: list[dict], figures: dict, lat: float, lon: float, at: datetime | None = None) -> SkyView:
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise SkyInputError("위도는 −90~90, 경도는 −180~180 사이여야 합니다.")
    at = as_aware(at)
    lst = local_sidereal_deg(at, lon)

    def place(name, item_id, group, ra, dec) -> SkyObject:
        alt, az = alt_az(ra, dec, lat, lst)
        return SkyObject(name, item_id, group, round(alt, 1), round(az, 1),
                         OVERHEAD if alt >= ZENITH_ALT else direction(az))

    sun_alt, _ = alt_az(*sun_ra_dec(at), lat, lst)
    view = SkyView(lat=lat, lon=lon, at=at, sun_alt_deg=round(sun_alt, 1), constellations=[], planets=[])

    for it in items:
        if it["group"] != "constellation":
            continue
        stars = list(figures.get(it["id"], {}).get("stars", {}).values())
        if stars:
            ra, dec = mean_direction(stars)
        elif it.get("ra_deg") is not None and it.get("dec_deg") is not None:
            ra, dec = it["ra_deg"], it["dec_deg"]
        else:
            continue
        obj = place(it["name"], it["id"], "constellation", ra, dec)
        if obj.alt_deg >= CONSTELLATION_MIN_ALT:
            view.constellations.append(obj)

    epoch = _planet_epoch(items)
    by_name = {it["name"]: it for it in items if it["group"] == "solar_system"}
    earth = by_name.get("지구", {}).get("position_au")
    if epoch is None or earth is None:
        view.notes.append("행성 위치 데이터가 없어 행성은 표시하지 않습니다.")
    elif abs((at.astimezone(timezone.utc).date() - epoch).days) > PLANET_EPOCH_DAYS:
        view.notes.append(f"행성 위치 기준일({epoch.isoformat()})과 {PLANET_EPOCH_DAYS}일 넘게 떨어진 시각이라 "
                          "행성은 표시하지 않습니다.")
    else:
        for name in NAKED_EYE_PLANETS:
            planet = by_name.get(name)
            if planet and planet.get("position_au"):
                obj = place(name, planet["id"], "solar_system",
                            *vector_ra_dec(vector_sub(planet["position_au"], earth)))
                if obj.alt_deg >= PLANET_MIN_ALT:
                    view.planets.append(obj)
    view.constellations.sort(key=lambda o: -o.alt_deg)
    view.planets.sort(key=lambda o: -o.alt_deg)
    return view


# ── 안내 문장 ─────────────────────────────────────────────────────────────

def _where(obj: SkyObject) -> str:
    return "머리 위 (천정 근처)" if obj.direction == OVERHEAD else f"{obj.direction}쪽 하늘"


def sky_table(view: SkyView) -> list[str]:
    lines = [f"관측 위치 · 시각: {view.place()}",
             f"태양 고도 약 {view.sun_alt_deg:g}도 ({'밤' if view.is_night else '낮 또는 박명'})"]
    lines += [f"- {o.name}: {_where(o)}, 고도 약 {o.alt_deg:.0f}도" for o in view.constellations[:TABLE_CONSTELLATIONS]]
    lines += [f"- 행성 {o.name}: {_where(o)}, 고도 약 {o.alt_deg:.0f}도" for o in view.planets]
    return lines


def sky_guide(view: SkyView, items: list[dict], ref_year: int, llm: BaseChatModel | None = None) -> SkyGuide:
    """안내 문장. 별자리 · 행성 중 하나라도 보이면 만든다 (행성만 있어도 계산표가 근거).

    view.notes(행성 데이터 없음 · 기준일 초과 등)는 결과마다 warnings로 이어 준다.
    """
    if not view.is_night:
        return SkyGuide(view=view, guide=None, status="daytime", warnings=[
            *view.notes, "지금은 해가 떠 있거나 아직 하늘이 밝아 별자리 안내를 만들지 않았습니다."])
    if not view.constellations and not view.planets:
        return SkyGuide(view=view, guide=None, status="empty",
                        warnings=[*view.notes, "지금 높이 뜬 별자리와 행성이 없습니다."])

    by_id = {it["id"]: it for it in items}
    evidences = [computed_evidence(1, "지금 하늘의 별자리 · 행성 위치", sky_table(view), chunk_id="sky:table")]
    for obj in view.constellations[:GUIDE_CONSTELLATIONS]:
        if obj.item_id in by_id:
            evidences.append(catalog_evidence(by_id[obj.item_id], ref_year, number=len(evidences) + 1))

    result = generate_validated(default_chat_model(llm), sky_messages(view.place(), evidences), evidences, purpose="sky")
    warnings = list(view.notes)
    warnings += result["notes"]                  # 언어 혼입 등 — 답은 내보내되 알린다
    if result["status"] == "rejected":
        warnings.append("안내가 인용 규칙을 두 번 어겨 내보내지 않았습니다.")
    return SkyGuide(view=view, guide=result["answer"], status=result["status"], cited=result["cited"],
                    evidences=evidences, attempts=result["attempts"], warnings=warnings)
