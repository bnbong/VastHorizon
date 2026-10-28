"""우리 은하 — 우리 은하(Q321)와 그 중심의 초대질량 블랙홀 궁수자리 A*(Q237284).

우리는 우리 은하 안에 있어서 '우리 은하까지의 거리'는 없다. 대신 은하 중심(Q649112)의 방향과
지구에서 은하 중심까지의 거리를 쓰고, 거리 기준(reference)을 "지구에서 우리 은하 중심까지"로 밝힌다.
거리는 psv(원래 값 · 단위)로 환산한다 — psn(정규화 값)은 26,000광년을 2.5e20 m(약 26,425광년)로 반올림한다.

| 항목         | 방향(적경 · 적위)      | 거리                                                   |
|--------------|------------------------|--------------------------------------------------------|
| 우리 은하    | 은하 중심(Q649112)     | 은하 중심 · 궁수자리 A* 거리 값의 중앙값 (은하 중심 기준) |
| 궁수자리 A*  | 자기 값                | 자기 값과 불확도 범위(하한 ~ 상한)                       |

두 항목 중 하나라도 한국어 위키 문서가 없거나, 은하 중심 좌표가 없거나, 궁수자리 A*의 거리 값이 없으면 예외를 낸다 —
collect_items가 기존 카탈로그를 그대로 지킨다.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict

from vasthorizon.data import sources
from vasthorizon.data.item_text import korean_number
from vasthorizon.data.items.common import REF_GALACTIC_CENTER, Distance, Item, LY_KM, distance_from_values, first_float

log = logging.getLogger(__name__)

MILKY_WAY, GALACTIC_CENTER, SGR_A_STAR = "Q321", "Q649112", "Q237284"
PARSEC_KM = 3.261563777 * LY_KM
UNIT_KM = {"Q531": LY_KM, "Q12129": PARSEC_KM, "Q11929860": 1000 * PARSEC_KM}   # 광년 · 파섹 · 킬로파섹
SOLAR_MASS = "Q180892"

# 값과 단위 · 범위가 행 병합에서 짝을 잃지 않도록 한 글자열로 묶는다 (메시에의 magBand와 같은 방식)
QUERY = f"""
SELECT ?item ?title ?en ?typeLabel ?ra ?dec ?conLabel ?distRec ?massRec WHERE {{
  VALUES ?item {{ wd:{MILKY_WAY} wd:{GALACTIC_CENTER} wd:{SGR_A_STAR} }}
  OPTIONAL {{ ?a schema:about ?item ; schema:isPartOf <https://ko.wikipedia.org/> ; schema:name ?title }}
  OPTIONAL {{ ?item rdfs:label ?en FILTER(lang(?en) = "en") }}
  OPTIONAL {{ ?item wdt:P31 ?type . ?type rdfs:label ?typeLabel FILTER(lang(?typeLabel) = "ko") }}
  OPTIONAL {{ ?item wdt:P6257 ?ra }} OPTIONAL {{ ?item wdt:P6258 ?dec }}
  OPTIONAL {{ FILTER(?item = wd:{SGR_A_STAR}) ?item wdt:P59 ?con . ?con rdfs:label ?conLabel FILTER(lang(?conLabel) = "ko") }}
  OPTIONAL {{ ?item p:P2583/psv:P2583 ?dv . ?dv wikibase:quantityAmount ?d ; wikibase:quantityUnit ?du .
             OPTIONAL {{ ?dv wikibase:quantityLowerBound ?dlo }} OPTIONAL {{ ?dv wikibase:quantityUpperBound ?dhi }}
             BIND(CONCAT(STR(?d), "|", STR(?du), "|", COALESCE(STR(?dlo), ""), "|", COALESCE(STR(?dhi), "")) AS ?distRec) }}
  OPTIONAL {{ ?item p:P2067/psv:P2067 ?mv . ?mv wikibase:quantityAmount ?m ; wikibase:quantityUnit ?mu .
             BIND(CONCAT(STR(?m), "|", STR(?mu)) AS ?massRec) }}
}}
"""


def distance_records(recs: set[str] | list[str], qid: str = "") -> list[tuple[float, float | None, float | None]]:
    """'값|단위 URI|하한|상한' → [(km, 하한 km, 상한 km)]. 단위를 모르는 값은 버리고 경고를 남긴다."""
    out = []
    for rec in sorted(recs):
        amount, unit, lo, hi = (rec.split("|") + ["", "", "", ""])[:4]
        factor = UNIT_KM.get(sources.qid(unit)) if unit else None
        value = first_float(amount)
        if factor is None or value is None or value <= 0:
            log.warning("우리 은하 수집: %s 거리 값 %r — 단위를 알 수 없거나 값이 없어 버립니다", qid, rec)
            continue
        low, high = first_float(lo), first_float(hi)
        out.append((value * factor, low * factor if low else None, high * factor if high else None))
    return out


def solar_masses(recs: set[str] | list[str]) -> list[float]:
    """'값|단위 URI' → 태양질량 단위 값만."""
    values = []
    for rec in recs:
        amount, _, unit = rec.partition("|")
        value = first_float(amount)
        if value and value > 0 and sources.qid(unit) == SOLAR_MASS:
            values.append(value)
    return sorted(values)


def mass_text(values: list[float]) -> str | None:
    """'약 410만 태양질량 (Wikidata 값 3개, 402만~431만)'."""
    if not values:
        return None
    text = f"약 {korean_number(statistics.median(values))} 태양질량"
    if len(values) > 1:
        text += f" (Wikidata 값 {len(values)}개, {korean_number(values[0])}~{korean_number(values[-1])})"
    return text


def _merge(rows: list[dict]) -> dict[str, dict[str, set]]:
    merged: dict[str, dict] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        rec = merged[sources.qid(row["item"])]
        for key, value in row.items():
            rec[key].add(value)
    return merged


def _title(rec: dict, qid: str) -> str:
    if not rec.get("title"):
        raise ValueError(f"우리 은하 수집: {qid}의 한국어 위키 문서 제목이 없습니다")
    return min(rec["title"])


def _wikidata(qid: str, used_for: str | None = None) -> dict:
    src = {"name": "Wikidata", "url": sources.SOURCE_URLS["Wikidata"].format(id=qid)}
    if used_for:
        src["used_for"] = used_for
    return src


def _milky_way(rec: dict, center: dict, sgr_records: list[tuple[float, float | None, float | None]]) -> Item:
    center_ra, center_dec = first_float(min(center.get("ra") or [""])), first_float(min(center.get("dec") or [""]))
    if center_ra is None or center_dec is None:
        raise ValueError(f"우리 은하 수집: 은하 중심({GALACTIC_CENTER})의 적경 · 적위가 없습니다")
    values = [km for km, _, _ in distance_records(center.get("distRec", []), GALACTIC_CENTER)]
    values += [km for km, _, _ in sgr_records]
    dist = distance_from_values(values, "wikidata")
    if dist:
        dist.reference = REF_GALACTIC_CENTER
        dist.method = (f"Wikidata 은하중심({GALACTIC_CENTER}) · 궁수자리 A*({SGR_A_STAR}) "
                       f"거리 {dist.n_values}개 값의 중앙값")
    galaxy_types = sorted(t for t in rec.get("typeLabel", []) if "은하" in t)
    title = _title(rec, MILKY_WAY)
    return Item(
        id=MILKY_WAY, group="milky_way", name=title, wiki_title=title,
        name_en=min(rec["en"]) if rec.get("en") else None,
        kind=galaxy_types[0] if galaxy_types else "은하", distance=dist,
        ra_deg=center_ra, dec_deg=center_dec,
        attrs={"분류": ", ".join(galaxy_types)} if galaxy_types else {},
        sources=[_wikidata(MILKY_WAY), _wikidata(GALACTIC_CENTER, "은하 중심 방향 · 거리"),
                 _wikidata(SGR_A_STAR, "은하 중심 거리")],
    )


def _sgr_a_star(rec: dict, records: list[tuple[float, float | None, float | None]]) -> Item:
    # 거리가 없으면 카탈로그 검증은 통과하지만 지도 점이 생기지 않는다 — 제목 누락처럼 수집을 실패시켜 기존 카탈로그를 지킨다
    if not records:
        raise ValueError(f"우리 은하 수집: {SGR_A_STAR}의 거리 값(단위를 아는 값)이 없습니다")
    if len(records) == 1:
        km, low, high = records[0]
        method = (f"Wikidata 값 · 불확도 범위 {korean_number(low / LY_KM)}~{korean_number(high / LY_KM)}광년"
                  if low and high else None)
        dist = Distance(km=km, basis="wikidata", method=method, km_min=low if method else None,
                        km_max=high if method else None, n_values=1)
    else:
        dist = distance_from_values([km for km, _, _ in records], "wikidata")
    # 블랙홀 분류를 앞에 — kind는 '블랙홀'이 들어간 분류 (화면이 이것으로 블랙홀 점을 알아본다)
    types = sorted(rec.get("typeLabel", []), key=lambda t: ("블랙홀" not in t, t))
    hole = next((t for t in types if "블랙홀" in t), "초대질량 블랙홀")
    title = _title(rec, SGR_A_STAR)
    attrs = {
        "별자리": min(rec["conLabel"]) if rec.get("conLabel") else None,
        "분류": ", ".join(types[:3]) or None,
        "질량": mass_text(solar_masses(rec.get("massRec", []))),
        "맨눈 관측": False,
    }
    return Item(
        id=SGR_A_STAR, group="milky_way", name=title, wiki_title=title,
        name_en=min(rec["en"]) if rec.get("en") else None,
        kind=hole, distance=dist,
        ra_deg=first_float(min(rec.get("ra") or [""])), dec_deg=first_float(min(rec.get("dec") or [""])),
        attrs={k: v for k, v in attrs.items() if v not in (None, "")},
        sources=[_wikidata(SGR_A_STAR)],
    )


def collect(refresh: bool = False) -> list[Item]:
    rows = sources.cached("milky_way_wikidata_v1", lambda: sources.sparql(QUERY), refresh)
    merged = _merge(rows)
    empty: dict = {}
    sgr = merged.get(SGR_A_STAR, empty)
    sgr_records = distance_records(sgr.get("distRec", []), SGR_A_STAR)
    return [_milky_way(merged.get(MILKY_WAY, empty), merged.get(GALACTIC_CENTER, empty), sgr_records),
            _sgr_a_star(sgr, sgr_records)]
