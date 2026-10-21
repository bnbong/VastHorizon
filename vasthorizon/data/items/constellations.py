"""✨ 별자리 — 국제천문연맹(IAU) 88개 별자리.

좌표 · 경계 · 이름은 d3-celestial, 면적은 Wikidata에서 가져온다.
관측 계절과 서울에서의 관측 가능 여부는 좌표로 계산한 근사값이다.
"""

from __future__ import annotations

from vasthorizon.data import sources
from vasthorizon.data.items.common import Item

SEOUL_LAT = 37.57

# 태양이 지나는 길(황도) 위의 별자리 — 점성술의 12궁에 뱀주인자리가 더해진다
ECLIPTIC = {"Ari", "Tau", "Gem", "Cnc", "Leo", "Vir", "Lib", "Sco", "Oph", "Sgr", "Cap", "Aqr", "Psc"}

SEASONS = {12: "겨울", 1: "겨울", 2: "겨울", 3: "봄", 4: "봄", 5: "봄",
           6: "여름", 7: "여름", 8: "여름", 9: "가을", 10: "가을", 11: "가을"}


def evening_month(ra_deg: float) -> int:
    """저녁 9시 무렵 남쪽 하늘 높이 뜨는 달(근사).

    밤 9시의 항성시 ≈ 태양 적경 + 9시간, 태양 적경은 춘분(3월 21일)에 0시이고
    한 달에 약 2시간씩 늘어난다.
    """
    ra_h = ra_deg / 15
    month = ((ra_h - 9) / 2 + 3.7) % 12
    return int(round(month)) or 12


def seoul_visibility(dec_min: float, dec_max: float) -> str:
    horizon = SEOUL_LAT - 90
    if dec_min > 90 - SEOUL_LAT:
        return "일년 내내 보임 (주극 별자리)"
    if dec_min > horizon:
        return "전체 관측 가능"
    if dec_max > horizon:
        return "일부만 관측 가능"
    return "관측 불가"


def _dec_range(geometry: dict) -> tuple[float, float]:
    decs = []

    def walk(node):
        if isinstance(node[0], (int, float)):
            decs.append(node[1])
        else:
            for child in node:
                walk(child)

    walk(geometry["coordinates"])
    return min(decs), max(decs)


def collect(star_items: list[Item], refresh: bool = False) -> list[Item]:
    features = sources.d3_file("constellations.json", refresh)["features"]
    bounds = {f["id"]: f["geometry"] for f in sources.d3_file("constellations.bounds.json", refresh)["features"]}
    star_features = sources.d3_file("stars.6.json", refresh)["features"]
    starnames = sources.d3_file("starnames.json", refresh)

    ko_titles = sorted({f["properties"]["ko"] for f in features})
    pages = sources.cached("constellation_pages", lambda: sources.kowiki_page_info(ko_titles), refresh)
    resolved = sorted({pages[t]["resolved"] for t in ko_titles if t in pages})
    ents = sources.cached("constellation_entities", lambda: sources.entities_by_titles("kowiki", resolved), refresh)

    qids = " ".join(f"wd:{e['qid']}" for e in ents.values())
    area_rows = sources.cached("constellation_area", lambda: sources.sparql(f"""
        SELECT ?item ?area WHERE {{ VALUES ?item {{ {qids} }} ?item wdt:P2046 ?area . }}"""), refresh)
    area = {sources.qid(r["item"]): round(float(r["area"]), 1) for r in area_rows}

    # 별자리마다 가장 밝은 별 — 별 항목에 있으면 그 한국어 이름을 쓴다
    star_by_hip = {it.attrs["히파르코스 번호"]: it for it in star_items}
    brightest: dict[str, tuple[float, int]] = {}
    for f in star_features:
        abbr = starnames.get(str(f["id"]), {}).get("c")
        if abbr and (abbr not in brightest or f["properties"]["mag"] < brightest[abbr][0]):
            brightest[abbr] = (f["properties"]["mag"], f["id"])

    items, seen = [], set()
    for f in features:
        props, abbr = f["properties"], f["id"]
        page = pages.get(props["ko"])
        if not page or page["resolved"] in seen:
            continue
        seen.add(page["resolved"])
        ent = ents.get(page["resolved"])
        if not ent:
            continue

        ra = props["display"][0] % 360
        dec = props["display"][1]
        month = evening_month(ra)
        attrs = {
            "약어": abbr,
            "라틴어 이름": props.get("la"),
            "면적(제곱도)": area.get(ent["qid"]),
            "저녁에 잘 보이는 달": f"{month}월 무렵",
            "관측 계절": SEASONS[month],
            "서울에서 관측": seoul_visibility(*_dec_range(bounds[abbr])) if abbr in bounds else None,
            "황도 별자리": abbr in ECLIPTIC,
        }
        if abbr in brightest:
            mag, hip = brightest[abbr]
            star = star_by_hip.get(f"HIP {hip}")
            meta = starnames.get(str(hip), {})
            label = star.name if star else (meta.get("name") or f"{meta.get('bayer', '')} {abbr}".strip())
            attrs["가장 밝은 별"] = f"{label} ({mag}등급)"

        items.append(Item(
            id=ent["qid"], group="constellation", name=page["resolved"], wiki_title=page["resolved"],
            name_en=ent["label_en"] or props.get("en"), kind="별자리", ra_deg=ra, dec_deg=dec,
            attrs={k: v for k, v in attrs.items() if v not in (None, "")},
            sources=[
                {"name": "Wikidata", "url": sources.SOURCE_URLS["Wikidata"].format(id=ent["qid"])},
                {"name": "d3-celestial", "url": sources.SOURCE_URLS["d3-celestial"]},
            ],
        ))
    return items
