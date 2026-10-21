"""⭐ 별 — 맨눈으로 잘 보이는 밝은 별과 가까운 별.

선정 기준
- 겉보기 등급 2.5 이하 (d3-celestial 별 목록 기준)
- 가장 가까운 별 몇 개는 어두워도 포함 (프록시마 센타우리 · 바너드별)
- 한국어 위키 문서가 있어야 한다

좌표 · 등급은 d3-celestial, 거리 · 분광형은 Wikidata (히파르코스 번호로 연결).
Wikidata에 거리가 없으면 연주시차로 계산한다.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from vasthorizon.data import sources
from vasthorizon.data.items.common import Distance, Item, distance_from_values, parallax_to_km

log = logging.getLogger(__name__)

MAG_LIMIT = 2.5
EXTRA_HIPS = [70890, 87937]   # 프록시마 센타우리, 바너드별
HIPPARCOS = "Q537199"
MILLIARCSECOND = "Q21500224"

SPECTRAL_COLOR = {
    "O": "청색", "B": "청백색", "A": "흰색", "F": "황백색", "G": "노란색", "K": "주황색", "M": "붉은색",
}


def ra_from_lon(lon: float) -> float:
    """d3-celestial 경도(-180~180) → 적경(0~360도)."""
    return lon % 360


def constellation_names(refresh: bool = False) -> dict[str, str]:
    """별자리 약어 → 한국어 이름 (d3-celestial)."""
    data = sources.d3_file("constellations.json", refresh)
    return {f["id"]: f["properties"]["ko"] for f in data["features"]}


def _query(match: str) -> str:
    """별 엔티티를 고르는 조건(match)에 공통 속성 조회를 붙인다."""
    return f"""
        SELECT ?code ?item ?title ?en ?sp ?distM ?plx ?ra ?dec ?mag WHERE {{
          {match}
          ?a schema:about ?item ; schema:isPartOf <https://ko.wikipedia.org/> ; schema:name ?title .
          OPTIONAL {{ ?item rdfs:label ?en FILTER(lang(?en) = "en") }}
          OPTIONAL {{ ?item wdt:P215 ?sp }}
          OPTIONAL {{ ?item p:P2583/psn:P2583/wikibase:quantityAmount ?distM }}
          OPTIONAL {{ ?item p:P2214/psv:P2214 [ wikibase:quantityAmount ?plx ;
                                               wikibase:quantityUnit wd:{MILLIARCSECOND} ] }}
          OPTIONAL {{ ?item wdt:P6257 ?ra }} OPTIONAL {{ ?item wdt:P6258 ?dec }}
          OPTIONAL {{ ?item wdt:P1215 ?mag }}
        }}"""


def collect(refresh: bool = False) -> list[Item]:
    stars = sources.d3_file("stars.6.json", refresh)["features"]
    names = sources.d3_file("starnames.json", refresh)
    con_ko = constellation_names(refresh)

    picked = {f["id"]: f for f in stars if f["properties"]["mag"] <= MAG_LIMIT or f["id"] in EXTRA_HIPS}
    missing_extra = [h for h in EXTRA_HIPS if h not in picked]
    if missing_extra:
        log.info("d3-celestial 6등성 목록 밖의 별은 Wikidata 좌표를 쓴다: %s", missing_extra)

    hips = sorted(set(picked) | set(EXTRA_HIPS))
    values = " ".join(f'"HIP {h}"' for h in hips)
    rows = sources.cached("stars_wikidata", lambda: sources.sparql(_query(
        f"VALUES ?code {{ {values} }} ?item p:P528 [ ps:P528 ?code ; pq:P972 wd:{HIPPARCOS} ] .")), refresh)

    # 같은 히파르코스 번호에 엔티티가 여럿이면(성계 · 구성별) 거리 정보가 있는 쪽을 쓴다
    by_hip: dict[int, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for row in rows:
        hip = int(row["code"].split()[-1])
        rec = by_hip[hip][sources.qid(row["item"])]
        for key, value in row.items():
            rec[key].add(value)

    # 보조 경로 — 히파르코스 번호가 구성별 항목에만 붙어 있으면(시리우스 · 알데바란 등)
    # 영문 고유명으로 위키 문서가 연결된 항목을 찾는다
    unmatched = {meta["name"]: h for h in hips
                 if h not in by_hip and (meta := names.get(str(h), {})).get("name")}
    if unmatched:
        # 영문 위키 리다이렉트를 먼저 따라간다 (예: Rigil Kentaurus → Alpha Centauri)
        en_pages = sources.cached("stars_fallback_enwiki",
                                  lambda: sources.kowiki_page_info(sorted(unmatched), sources.ENWIKI_API), refresh)
        resolved = {en_pages[n]["resolved"]: h for n, h in unmatched.items() if n in en_pages}
        ents = sources.cached("stars_fallback_entities",
                              lambda: sources.entities_by_titles("enwiki", sorted(resolved)), refresh)
        qid_to_hip = {e["qid"]: resolved[t] for t, e in ents.items() if e["kowiki"] and t in resolved}
        if qid_to_hip:
            qids = " ".join(f"wd:{q}" for q in qid_to_hip)
            extra = sources.cached("stars_fallback_wikidata",
                                   lambda: sources.sparql(_query(f"VALUES ?item {{ {qids} }}")), refresh)
            for row in extra:
                rec = by_hip[qid_to_hip[sources.qid(row["item"])]][sources.qid(row["item"])]
                for key, value in row.items():
                    rec[key].add(value)

    items = []
    for hip in hips:
        entities = by_hip.get(hip)
        if not entities:
            continue
        qid, rec = max(entities.items(), key=lambda kv: (bool(kv[1].get("distM") or kv[1].get("plx")), -len(kv[0])))
        title = min(rec["title"])

        dist = distance_from_values([float(v) / 1000 for v in rec.get("distM", [])], "wikidata")
        if dist is None and rec.get("plx"):
            plx = max(float(v) for v in rec["plx"])
            if plx > 0:
                dist = Distance(km=parallax_to_km(plx), basis="parallax",
                                method=f"연주시차 {plx} 밀리각초로 계산")

        feature = picked.get(hip)
        if feature:
            lon, dec = feature["geometry"]["coordinates"]
            ra, mag = ra_from_lon(lon), feature["properties"]["mag"]
        else:
            ra = float(min(rec["ra"])) if rec.get("ra") else None
            dec = float(min(rec["dec"])) if rec.get("dec") else None
            mag = min(float(v) for v in rec["mag"]) if rec.get("mag") else None

        meta = names.get(str(hip), {})
        abbr = meta.get("c")
        spectral = min(rec["sp"]) if rec.get("sp") else None
        attrs = {
            "히파르코스 번호": f"HIP {hip}",
            "별자리": con_ko.get(abbr) if abbr else None,
            "별자리 약어": abbr,
            "바이어 명칭": f"{meta['bayer']} {abbr}" if meta.get("bayer") and abbr else None,
            "겉보기 등급": mag,
            "맨눈 관측": mag is not None and mag <= 6,
            "분광형": spectral,
            "색": SPECTRAL_COLOR.get(spectral[0]) if spectral else None,
        }
        items.append(Item(
            id=qid, group="star", name=title, wiki_title=title,
            name_en=min(rec["en"]) if rec.get("en") else meta.get("name") or None,
            kind="항성", distance=dist, ra_deg=ra, dec_deg=dec,
            attrs={k: v for k, v in attrs.items() if v not in (None, "")},
            sources=[
                {"name": "Wikidata", "url": sources.SOURCE_URLS["Wikidata"].format(id=qid)},
                {"name": "d3-celestial", "url": sources.SOURCE_URLS["d3-celestial"]},
            ],
        ))
    return items
