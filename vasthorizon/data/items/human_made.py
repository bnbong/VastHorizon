"""🚀 인류의 발자취 — 인공위성 · 우주 탐사선 · 우주정거장.

1. Wikidata에서 한국어 위키 문서가 있는 후보를 모은다.
2. 기준일까지 발사가 확인된 항목만 남긴다. (계획 · 음모론 · 개념 문서 같은 잡음 제거)
3. 한국 위성과 심우주 탐사선은 반드시 넣고, 나머지는 위키 문서가 긴 순서로 채운다.
4. 현재 위치는 JPL Horizons(심우주) → CelesTrak SATCAT(궤도 · 재진입) 순서로 정한다.

시점 구분
- Horizons 위치: --epoch 기준일에 계산한 값
- SATCAT 운용 상태 · 고도 · 재진입: 파일을 내려받은 스냅샷 시점의 값 (과거 기준일로 재구성하지 않음)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from vasthorizon.data import sources
from vasthorizon.data.items.common import (
    AU_KM, REF_GEOCENTER, REF_SURFACE_ALTITUDE, Distance, Item, first_float, vector_norm, vector_sub,
)

log = logging.getLogger(__name__)

TARGET_COUNT = 100

# COSPAR ID → JPL Horizons 우주선 ID. 궤도력이 없으면(임무 종료 등) SATCAT 정보로 대신한다.
HORIZONS_SPACECRAFT = {
    "1977-084A": "-31",      # 보이저 1호
    "1977-076A": "-32",      # 보이저 2호
    "1972-012A": "-23",      # 파이어니어 10호
    "1973-019A": "-24",      # 파이어니어 11호
    "2006-001A": "-98",      # 뉴 허라이즌스
    "2021-130A": "-170",     # 제임스 웹 우주망원경
    "2018-065A": "-96",      # 파커 태양 탐사선
    "2011-040A": "-61",      # 주노
    "2022-094A": "-155",     # 다누리
    "2006-047A": "-234",     # STEREO-A
    "2021-093A": "-49",      # 루시
    "2023-157A": "-255",     # 사이키
    "2024-182A": "-159",     # 유로파 클리퍼
    "2023-053A": "-28",      # JUICE
    "2018-080A": "-121",     # 베피콜롬보
    "2020-010A": "-144",     # 솔라 오비터
    "2016-055A": "-64",      # 오시리스-렉스
    "2014-076A": "-37",      # 하야부사2
    "2005-029A": "-74",      # 화성 정찰 위성
    "2001-014A": "-53",      # 2001 마스 오디세이
    "2013-063A": "-202",     # 메이븐
    "2013-074A": "-139479",  # 가이아
    "1995-065A": "-21",      # 소호
    "2003-038A": "-79",      # 스피처
    "2009-011A": "-227",     # 케플러
    "2007-043A": "-203",     # 돈
    "2004-006A": "-226",     # 로제타
}

KOREAN_NAME_PREFIXES = ("아리랑", "천리안", "무궁화", "우리별", "다누리", "과학기술위성", "차세대중형위성", "나로과학위성", "아나시스")

OPS_STATUS = {
    "+": "운용 중", "-": "운용 종료", "P": "부분 운용", "B": "예비", "S": "예비",
    "X": "확장 임무", "D": "소멸(재진입)", "?": "미상",
}

OWNER_KO = {
    "US": "미국", "CIS": "소련/러시아", "PRC": "중국", "SKOR": "대한민국", "NKOR": "북한", "JPN": "일본",
    "ESA": "유럽우주국", "IND": "인도", "FR": "프랑스", "UK": "영국", "GER": "독일", "IT": "이탈리아",
    "CA": "캐나다", "ISS": "국제우주정거장 참여국", "UAE": "아랍에미리트", "ISRA": "이스라엘",
}

# SATCAT ORBIT_CENTER → (설명, 태양계 항목 영문 제목)
ORBIT_CENTER = {
    "MO": ("달", "Moon"), "EM": ("지구-달 계", "Moon"), "MA": ("화성", "Mars"), "VE": ("금성", "Venus"), "ME": ("수성", "Mercury (planet)"),
    "JU": ("목성", "Jupiter"), "SA": ("토성", "Saturn"), "EL1": ("태양-지구 L1 라그랑주점", None),
    "EL2": ("태양-지구 L2 라그랑주점", None), "SU": ("태양 궤도", None), "SS": ("태양계 탈출 궤도", None),
}
LAGRANGE_KM = 1_500_000
ORBIT_TYPE = {"ORB": "궤도", "LAN": "착륙", "IMP": "충돌", "DOC": "도킹", "R/T": "귀환"}

# 종류 표시 우선순위 — 앞에 있을수록 대표 분류로 쓴다
KIND_PRIORITY = [
    "우주정거장", "우주망원경", "우주 탐사선", "궤도선", "달 착륙선", "착륙선", "지구 관측 위성",
    "기상 위성", "통신 위성", "과학 위성", "큐브샛", "정찰위성", "인공위성",
]
KIND_EXCLUDE = {"없어진 개체", "미완성 계획", "군사 계획", "연구 프로젝트", "우주 비행", "천체"}

QUERY = """
SELECT ?item ?title ?en ?typeLabel ?launch ?cospar ?end ?opLabel ?countryLabel ?vehLabel WHERE {
  { ?item wdt:P31/wdt:P279* wd:Q26540 } UNION { ?item wdt:P31/wdt:P279* wd:Q26529 }
  UNION { ?item wdt:P31/wdt:P279* wd:Q25956 }
  ?a schema:about ?item ; schema:isPartOf <https://ko.wikipedia.org/> ; schema:name ?title .
  OPTIONAL { ?item rdfs:label ?en FILTER(lang(?en) = "en") }
  OPTIONAL { ?item wdt:P31 ?type . ?type rdfs:label ?typeLabel FILTER(lang(?typeLabel) = "ko") }
  OPTIONAL { ?item wdt:P619 ?launch }
  OPTIONAL { ?item wdt:P247 ?cospar }
  OPTIONAL { ?item wdt:P730 ?end }
  OPTIONAL { ?item wdt:P137 ?op . ?op rdfs:label ?opLabel FILTER(lang(?opLabel) = "ko") }
  OPTIONAL { ?item wdt:P495 ?country . ?country rdfs:label ?countryLabel FILTER(lang(?countryLabel) = "ko") }
  OPTIONAL { ?item wdt:P375 ?veh . ?veh rdfs:label ?vehLabel FILTER(lang(?vehLabel) = "ko") }
}
"""


def _merge_rows(rows: list[dict]) -> dict[str, dict]:
    merged: dict[str, dict] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        rec = merged[sources.qid(row["item"])]
        for key, value in row.items():
            if key != "item":
                rec[key].add(value)
    return {k: {f: sorted(v) for f, v in rec.items()} for k, rec in merged.items()}


def _one(rec: dict, key: str) -> str | None:
    values = rec.get(key)
    return values[0] if values else None


def _kind(rec: dict) -> str:
    labels = [t for t in rec.get("typeLabel", []) if t not in KIND_EXCLUDE]
    ranked = sorted(labels, key=lambda t: KIND_PRIORITY.index(t) if t in KIND_PRIORITY else len(KIND_PRIORITY))
    return ranked[0] if ranked else "우주선"


def _is_korean(rec: dict, satcat: dict | None) -> bool:
    if "대한민국" in rec.get("countryLabel", []):
        return True
    if satcat and satcat.get("OWNER") == "SKOR":
        return True
    return _one(rec, "title").startswith(KOREAN_NAME_PREFIXES)


# ── 발사 여부 · SATCAT 연결 ─────────────────────────────────────────────────

def match_satcat(rec: dict, satcat: dict[str, dict]) -> dict | None:
    """COSPAR ID로 SATCAT 레코드를 찾되, 탑재체(PAY)이고 발사일이 같을 때만 인정한다.

    Wikidata의 COSPAR ID가 같은 발사의 로켓 단 · 파편을 가리키는 경우가 있어서다.
    (예: 갈릴레오 탐사정 → 1989-084E는 본체가 아님)
    """
    launch = (_one(rec, "launch") or "")[:10]
    for cospar in rec.get("cospar", []):
        row = satcat.get(cospar)
        if row and row["OBJECT_TYPE"] == "PAY" and (not launch or row["LAUNCH_DATE"] == launch):
            return row
    return None


def launch_date(rec: dict, sc: dict | None) -> tuple[str | None, str | None]:
    """(발사일, 출처). Wikidata 발사일을 먼저 쓰고, 없으면 SATCAT 발사일을 쓴다."""
    wikidata = (_one(rec, "launch") or "")[:10]
    if wikidata:
        return wikidata, "Wikidata"
    if sc and sc.get("LAUNCH_DATE"):
        return sc["LAUNCH_DATE"], "CelesTrak SATCAT"
    return None, None


def is_launched(launch: str | None, epoch: str) -> bool:
    """기준일까지 발사가 확인된 항목만 포함한다.

    - 발사일이 기준일 이후면 COSPAR ID가 있어도 제외한다
    - 발사일을 어디서도 확인할 수 없으면 제외한다 (계획 · 개념 문서가 섞이지 않게)
    """
    return launch is not None and launch <= epoch


# ── 현재 위치 결정 ──────────────────────────────────────────────────────────

# 중력 영향권 반지름 근사값(km). 행성은 SOI(라플라스 구), 위성 · 소천체는 힐 구 기준.
# 이 안에 있으면 "그 천체 부근"으로 본다.
SOI_KM = {
    "Mercury (planet)": 112_000, "Venus": 616_000, "Earth": 925_000, "Mars": 577_000,
    "Jupiter": 48_200_000, "Saturn": 54_800_000, "Uranus": 51_800_000, "Neptune": 86_800_000,
    "Moon": 66_000, "Phobos (moon)": 17, "Deimos (moon)": 25,
    "Io (moon)": 10_500, "Europa (moon)": 13_400, "Ganymede (moon)": 32_000, "Callisto (moon)": 49_700,
    "Titan (moon)": 52_000, "Enceladus": 950, "Triton (moon)": 45_000,
    "Pluto": 3_100_000, "Charon (moon)": 9_000, "Ceres (dwarf planet)": 77_000,
}
DEFAULT_SOI_KM = 1_000      # 목록에 없는 소행성 · 혜성 · 왜행성 — 근접 탐사 거리 수준


def _describe_direct_position(pos: list[float], sc: dict | None, bodies: dict[str, Item]) -> str:
    """Horizons로 계산한 위치를 설명한다.

    SATCAT 궤도 중심은 발사 · 순항 단계 값이 남아 있기도 하다 (예: 화성 정찰위성 → SU).
    그래서 실제 위치가 어느 천체의 중력 영향권 안인지 먼저 본다. 여러 영향권이 겹치면
    가장 작은(구체적인) 쪽을 고른다 — 달 궤도선은 지구가 아닌 달, 목성 궤도선은 목성.
    라그랑주점 · 탈출 궤도는 SATCAT을 따른다.
    """
    center = (sc or {}).get("ORBIT_CENTER")
    if center in ("EL1", "EL2"):
        return ORBIT_CENTER[center][0]
    inside = []
    for title, body in bodies.items():
        if title == "Sun" or not body.position_au:
            continue
        soi = SOI_KM.get(title, DEFAULT_SOI_KM)
        if vector_norm(vector_sub(pos, body.position_au)) * AU_KM < soi:
            inside.append((soi, body))
    if inside:
        return f"{min(inside, key=lambda t: t[0])[1].name} 부근"
    if center == "SS":
        return ORBIT_CENTER["SS"][0]
    return "심우주 (태양 궤도)"


@dataclass
class Placement:
    location: str                               # 사람이 읽는 위치 설명
    distance: Distance | None = None
    position_au: list[float] | None = None      # 직접 계산한 실제 위치만
    position_basis: str | None = None
    position_proxy: dict | None = None          # 표시용 근삿값 — 실제 좌표와 분리
    horizons_used_for: str | None = None        # Horizons 값을 어디에 썼는지 (출처 기록용)
    status_known: bool = True                   # 기준일의 상태를 SATCAT 스냅샷으로 판단할 수 있는지


def locate(sc: dict | None, horizons_pos: list[float] | None, earth: list[float],
           bodies: dict[str, Item], epoch: str, satcat_date: str | None) -> Placement:
    """현재 위치 설명 · 지구로부터 거리 · 위치를 정한다.

    우선순위: Horizons 직접 계산 → SATCAT 궤도 정보(스냅샷) → 정보 없음.
    대상 자체를 직접 계산하지 못한 값은 approximate · position_proxy로 구분한다.
    """
    if horizons_pos:
        km = vector_norm(vector_sub(horizons_pos, earth)) * AU_KM
        where = _describe_direct_position(horizons_pos, sc, bodies)
        return Placement(
            location=f"{where} (Horizons 직접 계산)",
            distance=Distance(km=km, basis="horizons", reference=REF_GEOCENTER),
            position_au=horizons_pos, position_basis="horizons",
            horizons_used_for=f"탐사선 위치 직접 계산 ({epoch})",
        )

    if not sc:
        return Placement(location="위치 정보 없음")

    center, otype = sc.get("ORBIT_CENTER", ""), sc.get("ORBIT_TYPE", "")
    decay = sc.get("DECAY_DATE") or None

    # 스냅샷에는 재진입 · 종료로 기록됐지만 기준일엔 아직이었던 경우 — 기준일의 상태를 단정하지 않는다
    if decay and decay > epoch:
        return Placement(
            location=f"기준일 상태 미상 — SATCAT 스냅샷({satcat_date})에는 {decay} 재진입·종료로 기록",
            status_known=False,
        )

    if center == "EA":
        if decay or otype == "IMP":
            return Placement(location=f"대기권 재진입 ({decay or '날짜 미상'})")
        perigee, apogee = first_float(sc.get("PERIGEE")), first_float(sc.get("APOGEE"))
        distance = None
        if perigee is not None and apogee is not None:
            distance = Distance(
                km=(perigee + apogee) / 2, basis="satcat", reference=REF_SURFACE_ALTITUDE,
                approximate=True, method=f"근지점 {perigee:g}km · 원지점 {apogee:g}km 고도의 평균",
            )
        return Placement(
            location="지구 궤도", distance=distance,
            position_proxy={"body": "지구", "position_au": earth,
                            "method": "궤도상 방향을 알 수 없어 지구 위치로 표시 (표시용 근삿값)"},
            horizons_used_for=f"표시용 근삿값 — 지구 위치 ({epoch})",
        )

    if center in ("EL1", "EL2"):
        label = ORBIT_CENTER[center][0]
        sun_to_earth = [c / vector_norm(earth) for c in earth]      # 태양 → 지구 방향 단위 벡터
        sign = -1 if center == "EL1" else 1                          # L1은 태양 쪽, L2는 반대쪽
        offset_au = LAGRANGE_KM / AU_KM
        return Placement(
            location=label,
            distance=Distance(km=LAGRANGE_KM, basis="lagrange", reference=REF_GEOCENTER, approximate=True,
                              method="지구에서 라그랑주점까지의 평균 거리(약 150만 km)로 근사"),
            position_proxy={"body": label,
                            "position_au": [e + sign * offset_au * d for e, d in zip(earth, sun_to_earth)],
                            "method": "지구-태양 축 위 약 150만 km 지점으로 계산 (표시용 근삿값)"},
            horizons_used_for=f"표시용 근삿값 — 지구 위치 ({epoch})",
        )

    if center in ORBIT_CENTER:
        label, body_title = ORBIT_CENTER[center]
        body = bodies.get(body_title) if body_title else None
        when = f" ({decay})" if decay else ""
        if not body or not body.distance:
            return Placement(location=label + when)
        return Placement(
            location=f"{label} {ORBIT_TYPE.get(otype, '궤도')}{when}",
            distance=Distance(km=body.distance.km, basis="parent_body", reference=REF_GEOCENTER,
                              approximate=True, method=f"탐사선 대신 {body.name}까지의 거리로 근사"),
            position_proxy={"body": body.name, "position_au": body.position_au,
                            "method": f"탐사선 위치 대신 {body.name}의 위치로 표시 (표시용 근삿값)"},
            horizons_used_for=f"근삿값 — {body.name} 위치 ({epoch})",
        )

    return Placement(location=f"기타 ({center or '미상'})")


# ── 수집 ──────────────────────────────────────────────────────────────────

def collect(epoch: str, bodies: dict[str, Item], refresh: bool = False) -> list[Item]:
    rows = sources.cached("human_made_wikidata", lambda: sources.sparql(QUERY), refresh)
    candidates = _merge_rows(rows)
    satcat, snapshot = sources.satcat_by_cospar(refresh)
    satcat_date = snapshot["fetched_at"][:10] + (" (추정)" if snapshot.get("estimated") else "")

    # 잡음 제거 — 기준일까지 발사가 확인된 항목만 남긴다
    matched = {k: match_satcat(rec, satcat) for k, rec in candidates.items()}
    launches = {k: launch_date(rec, matched[k]) for k, rec in candidates.items()}
    candidates = {k: rec for k, rec in candidates.items() if is_launched(launches[k][0], epoch)}

    titles = sorted({_one(r, "title") for r in candidates.values()})
    pages = sources.cached("human_made_pages", lambda: sources.kowiki_page_info(titles), refresh)

    def page_len(rec: dict) -> int:
        return pages.get(_one(rec, "title"), {}).get("length", 0)

    forced = {k for k, rec in candidates.items()
              if _is_korean(rec, matched[k]) or set(rec.get("cospar", [])) & HORIZONS_SPACECRAFT.keys()}
    rest = sorted((k for k in candidates if k not in forced), key=lambda k: -page_len(candidates[k]))
    chosen = sorted(forced) + rest[:max(0, TARGET_COUNT - len(forced))]

    earth = bodies["Earth"].position_au
    items = []
    for key in chosen:
        rec, sc = candidates[key], matched[key]
        title = _one(rec, "title")
        resolved = pages.get(title, {}).get("resolved", title)
        cmd = next((HORIZONS_SPACECRAFT[c] for c in rec.get("cospar", []) if c in HORIZONS_SPACECRAFT), None)
        horizons_pos = sources.horizons_position(cmd, epoch, refresh) if cmd else None
        place = locate(sc, horizons_pos, earth, bodies, epoch, satcat_date)
        launch, launch_source = launches[key]

        country = _one(rec, "countryLabel") or (OWNER_KO.get(sc["OWNER"], sc["OWNER"]) if sc else None)
        attrs = {
            "국가": country,
            "운영기관": ", ".join(rec.get("opLabel", [])) or None,
            "발사일": launch,
            "발사일 출처": launch_source,
            "발사체": ", ".join(rec.get("vehLabel", [])) or None,
            "임무 종료일": (_one(rec, "end") or "")[:10] or None,
            "COSPAR ID": _one(rec, "cospar"),
            "현재 위치": place.location,
            "한국 관련": _is_korean(rec, sc),
            "분류": ", ".join(t for t in rec.get("typeLabel", []) if t not in KIND_EXCLUDE) or None,
        }
        if place.position_basis == "horizons":
            attrs["Horizons 위치 기준일"] = epoch
        if sc:
            attrs["운용 상태"] = OPS_STATUS.get(sc["OPS_STATUS_CODE"], "미상") if place.status_known else "기준일 상태 미상"
            attrs["재진입·종료일"] = sc.get("DECAY_DATE") or None
            attrs["SATCAT 스냅샷"] = satcat_date
            if sc.get("ORBIT_CENTER") == "EA" and not sc.get("DECAY_DATE"):
                attrs["근지점 고도(km)"] = first_float(sc.get("PERIGEE"))
                attrs["원지점 고도(km)"] = first_float(sc.get("APOGEE"))
                attrs["공전 주기(분)"] = first_float(sc.get("PERIOD"))

        item_sources = [{"name": "Wikidata", "url": sources.SOURCE_URLS["Wikidata"].format(id=key),
                         "used_for": "항목 · 기본 속성"}]
        if sc:
            item_sources.append({"name": "CelesTrak SATCAT", "url": sources.SOURCE_URLS["CelesTrak SATCAT"],
                                 "used_for": f"궤도 · 운용 상태 (스냅샷 {satcat_date})"})
        if place.horizons_used_for:
            item_sources.append({"name": "JPL Horizons", "url": sources.SOURCE_URLS["JPL Horizons"],
                                 "used_for": place.horizons_used_for})

        items.append(Item(
            id=key, group="human_made", name=resolved, wiki_title=resolved, name_en=_one(rec, "en"),
            kind=_kind(rec), distance=place.distance, position_au=place.position_au,
            position_basis=place.position_basis, position_proxy=place.position_proxy,
            attrs={k: v for k, v in attrs.items() if v not in (None, "")}, sources=item_sources,
        ))
    return items


