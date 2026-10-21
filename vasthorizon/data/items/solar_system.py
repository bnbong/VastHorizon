"""☀️ 태양계 — 행성 · 왜행성 · 주요 위성 · 소행성 · 혜성.

목록은 직접 고른다. 위치는 JPL Horizons에서 수집일 기준 실제 위치를 받는다.
"""

from __future__ import annotations

import logging

from vasthorizon.data import sources
from vasthorizon.data.items.common import AU_KM, REF_GEOCENTER, Distance, Item, vector_norm, vector_sub

log = logging.getLogger(__name__)

# (영문 위키 제목, Horizons 명령, 종류, 모천체 영문 위키 제목)
BODIES: list[tuple[str, str, str, str | None]] = [
    ("Sun", "10", "항성", None),
    ("Mercury (planet)", "199", "행성", None),
    ("Venus", "299", "행성", None),
    ("Earth", "399", "행성", None),
    ("Moon", "301", "위성", "Earth"),
    ("Mars", "499", "행성", None),
    ("Phobos (moon)", "401", "위성", "Mars"),
    ("Deimos (moon)", "402", "위성", "Mars"),
    ("Jupiter", "599", "행성", None),
    ("Io (moon)", "501", "위성", "Jupiter"),
    ("Europa (moon)", "502", "위성", "Jupiter"),
    ("Ganymede (moon)", "503", "위성", "Jupiter"),
    ("Callisto (moon)", "504", "위성", "Jupiter"),
    ("Saturn", "699", "행성", None),
    ("Titan (moon)", "606", "위성", "Saturn"),
    ("Enceladus", "602", "위성", "Saturn"),
    ("Uranus", "799", "행성", None),
    ("Neptune", "899", "행성", None),
    ("Triton (moon)", "801", "위성", "Neptune"),
    ("Pluto", "999", "왜행성", None),
    ("Charon (moon)", "901", "위성", "Pluto"),
    ("Ceres (dwarf planet)", "1;", "왜행성", None),
    ("Eris (dwarf planet)", "136199;", "왜행성", None),
    ("Haumea", "136108;", "왜행성", None),
    ("Makemake", "136472;", "왜행성", None),
    ("4 Vesta", "4;", "소행성", None),
    ("101955 Bennu", "101955;", "소행성", None),
    ("162173 Ryugu", "162173;", "소행성", None),
    ("99942 Apophis", "99942;", "소행성", None),
    ("486958 Arrokoth", "486958;", "카이퍼대 천체", None),
    ("Halley's Comet", "DES=1P; CAP;", "혜성", None),
    ("67P/Churyumov–Gerasimenko", "DES=67P; CAP;", "혜성", None),
]

EARTH = "Earth"


def collect(epoch: str, refresh: bool = False) -> tuple[list[Item], dict[str, Item]]:
    """태양계 항목과, 영문 제목 → 항목 사전(탐사선 위치 계산용)을 돌려준다."""
    titles = [b[0] for b in BODIES]
    ents = sources.cached("solar_entities", lambda: sources.entities_by_titles("enwiki", titles), refresh)

    qids = " ".join(f"wd:{e['qid']}" for e in ents.values())
    radius_rows = sources.cached("solar_radius", lambda: sources.sparql(f"""
        SELECT ?item ?r WHERE {{ VALUES ?item {{ {qids} }}
          ?item p:P2120/psn:P2120/wikibase:quantityAmount ?r . }}"""), refresh)
    radius_km = {}
    for row in radius_rows:
        radius_km.setdefault(sources.qid(row["item"]), float(row["r"]) / 1000)

    positions = {title: sources.horizons_position(cmd, epoch, refresh) for title, cmd, _, _ in BODIES}
    earth_pos = positions[EARTH]
    if earth_pos is None:
        raise RuntimeError("Horizons에서 지구 위치를 받지 못했습니다. 모든 거리의 기준점이라 수집을 중단합니다.")

    by_title: dict[str, Item] = {}
    for title, cmd, kind, parent in BODIES:
        ent = ents.get(title)
        if not ent or not ent["kowiki"]:
            log.warning("태양계: 한국어 위키 문서 없음 — %s", title)
            continue
        pos = positions.get(title)
        distance = None
        if pos and title != EARTH:
            distance = Distance(km=vector_norm(vector_sub(pos, earth_pos)) * AU_KM,
                                basis="horizons", reference=REF_GEOCENTER)

        attrs = {"horizons_id": cmd}
        if pos:
            attrs["Horizons 위치 기준일"] = epoch
        else:
            log.warning("태양계: Horizons 위치 없음 — %s", title)
        if title == EARTH:
            attrs["기준점"] = "VastHorizon의 모든 거리는 지구를 기준으로 잰다"
        if ent["qid"] in radius_km:
            attrs["평균 반지름(km)"] = round(radius_km[ent["qid"]], 1)

        item_sources = [{"name": "Wikidata", "url": sources.SOURCE_URLS["Wikidata"].format(id=ent["qid"])}]
        if pos:
            item_sources.append({"name": "JPL Horizons", "url": sources.SOURCE_URLS["JPL Horizons"]})
        item = Item(
            id=ent["qid"], group="solar_system", name=ent["kowiki"], wiki_title=ent["kowiki"],
            name_en=ent["label_en"], kind=kind, distance=distance, position_au=pos,
            position_basis="horizons" if pos else None, attrs=attrs, sources=item_sources,
        )
        by_title[title] = item

    for title, _, _, parent in BODIES:
        if title in by_title and parent in by_title:
            by_title[title].attrs["모천체"] = by_title[parent].name

    return list(by_title.values()), by_title
