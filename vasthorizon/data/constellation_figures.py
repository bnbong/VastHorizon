"""별자리 모양 데이터 — 선을 이루는 별과 그 별들의 실제 거리. (별자리 펼치기 · 3D 시각화)

| 데이터           | 출처                                   | 이용 조건          |
|------------------|----------------------------------------|--------------------|
| 별자리 선 · 별 좌표 · 등급 | d3-celestial (constellations.lines · stars.6) | BSD-3-Clause |
| 별 거리 · 이름   | Wikidata (히파르코스 번호로 연결)       | CC0 1.0            |

d3-celestial의 별자리 선은 좌표만 있고 별 ID가 없어서, 꼭짓점마다 같은 출처의 별 목록에서
좌표가 가장 가까운 별(0.02도 이내)을 찾아 히파르코스 번호를 붙인다.
찾지 못한 꼭짓점에서는 선을 끊는다 — 그 앞뒤 별을 직접 이으면 원본에 없는 선이 생긴다.
거리는 Wikidata 거리 값을 연주시차로 검증해 정한다 (common.distance_with_parallax). 모르면 None.
"""

from __future__ import annotations

import math
from collections import defaultdict

from vasthorizon.data import sources
from vasthorizon.data.items.common import distance_with_parallax
from vasthorizon.data.items.stars import HIPPARCOS, MILLIARCSECOND, constellation_names, ra_from_lon

MATCH_DEG = 0.02
LICENSES = {"d3-celestial": "BSD-3-Clause (© 2015 Olaf Frohn)", "Wikidata": "CC0 1.0"}
BATCH = 120


def _star_index(stars: list[dict]) -> dict[tuple[float, float], list[dict]]:
    index: dict[tuple[float, float], list[dict]] = defaultdict(list)
    for f in stars:
        lon, lat = f["geometry"]["coordinates"]
        index[(round(lon, 1), round(lat, 1))].append(f)
    return index


def _nearest(index, lon: float, lat: float) -> dict | None:
    best = None
    for dl in (-0.1, 0, 0.1):
        for db in (-0.1, 0, 0.1):
            for f in index.get((round(lon + dl, 1), round(lat + db, 1)), []):
                d = math.dist(f["geometry"]["coordinates"], (lon, lat))
                if d < MATCH_DEG and (best is None or d < best[0]):
                    best = (d, f)
    return best[1] if best else None


def split_at_gaps(vertices: list[int | None]) -> list[list[int]]:
    """미매칭 꼭짓점(None)에서 선을 끊는다. A → (미매칭) → C를 A → C로 잇지 않는다.

    별 2개 이상인 연속 구간만 남긴다. 예: [A, B, None, D, E] → [[A, B], [D, E]]
    """
    segments, current = [], []
    for v in [*vertices, None]:
        if v is None:
            if len(current) >= 2:
                segments.append(current)
            current = []
        else:
            current.append(v)
    return segments


def _distances(hips: list[int], refresh: bool) -> dict[int, dict]:
    """히파르코스 번호 → {ly, basis, name_en}. Wikidata를 BATCH개씩 조회한다."""
    found: dict[int, dict] = {}
    for start in range(0, len(hips), BATCH):
        batch = hips[start:start + BATCH]
        values = " ".join(f'"HIP {h}"' for h in batch)
        rows = sources.cached(f"constellation_stars_{batch[0]}_{len(batch)}", lambda: sources.sparql(f"""
            SELECT ?code ?en ?distM ?plx WHERE {{
              VALUES ?code {{ {values} }}
              ?item p:P528 [ ps:P528 ?code ; pq:P972 wd:{HIPPARCOS} ] .
              OPTIONAL {{ ?item rdfs:label ?en FILTER(lang(?en) = "en") }}
              OPTIONAL {{ ?item p:P2583/psn:P2583/wikibase:quantityAmount ?distM }}
              OPTIONAL {{ ?item p:P2214/psv:P2214 [ wikibase:quantityAmount ?plx ;
                                                   wikibase:quantityUnit wd:{MILLIARCSECOND} ] }}
            }}"""), refresh)
        per: dict[int, dict] = defaultdict(lambda: {"dist": set(), "plx": set(), "en": set()})
        for r in rows:
            rec = per[int(r["code"].split()[-1])]
            for key, field in (("distM", "dist"), ("plx", "plx"), ("en", "en")):
                if r.get(key):
                    rec[field].add(r[key])
        for hip, rec in per.items():
            plx_values = sorted(float(v) for v in rec["plx"] if float(v) > 0)
            plx = plx_values[len(plx_values) // 2] if plx_values else None
            dist = distance_with_parallax([float(v) / 1000 for v in rec["dist"]], plx)   # 연주시차로 검증
            if dist is not None:
                found[hip] = {"ly": dist.ly, "basis": dist.basis}
            if hip in found and rec["en"]:
                found[hip]["name_en"] = min(rec["en"])
    return found


def _korean_names(hips: list[int], refresh: bool) -> dict[int, dict]:
    """히파르코스 번호 → {title: 한국어 위키 문서 제목, label: 한국어 이름}. 없는 값은 빠진다.

    카탈로그 밖의 별자리 별도 그 별 자체로 물어볼 수 있게, 항목 문서(위키)와 한국어 이름을 연결한다.
    """
    found: dict[int, dict] = {}
    for start in range(0, len(hips), BATCH):
        batch = hips[start:start + BATCH]
        values = " ".join(f'"HIP {h}"' for h in batch)
        rows = sources.cached(f"constellation_star_names_{batch[0]}_{len(batch)}", lambda: sources.sparql(f"""
            SELECT ?code ?title ?label WHERE {{
              VALUES ?code {{ {values} }}
              ?item p:P528 [ ps:P528 ?code ; pq:P972 wd:{HIPPARCOS} ] .
              OPTIONAL {{ ?page schema:about ?item ; schema:isPartOf <https://ko.wikipedia.org/> ; schema:name ?title }}
              OPTIONAL {{ ?item rdfs:label ?label FILTER(lang(?label) = "ko") }}
            }}"""), refresh)
        for r in rows:
            rec = found.setdefault(int(r["code"].split()[-1]), {})
            for key in ("title", "label"):
                if r.get(key) and key not in rec:
                    rec[key] = r[key]
    return found


def collect_figures(star_items: list[dict], constellation_items: list[dict], refresh: bool = False) -> dict:
    """별자리 약어 → {item_id, name, lines: [[HIP …]], stars: {HIP: {…}}}."""
    lines = sources.d3_file("constellations.lines.json", refresh)["features"]
    stars = sources.d3_file("stars.6.json", refresh)["features"]
    names = sources.d3_file("starnames.json", refresh)
    con_ko = constellation_names(refresh)
    index = _star_index(stars)
    item_by_abbr = {it["attrs"].get("약어"): it for it in constellation_items}
    star_item_by_hip = {int(it["attrs"]["히파르코스 번호"].split()[-1]): it for it in star_items
                        if it["attrs"].get("히파르코스 번호")}

    figures, unmatched = {}, 0
    for feat in lines:
        abbr = feat["id"]
        item = item_by_abbr.get(abbr)
        if item is None:
            continue
        polylines, members = [], {}
        for line in feat["geometry"]["coordinates"]:
            vertices = []
            for lon, lat in line:
                star = _nearest(index, lon, lat)
                if star is None:
                    unmatched += 1
                vertices.append(star)
            for segment in split_at_gaps([s["id"] if s else None for s in vertices]):
                polylines.append(segment)
            kept = {h for seg in polylines for h in seg}
            members.update({s["id"]: s for s in vertices if s and s["id"] in kept})
        figure = figures.setdefault(abbr, {"item_id": item["id"], "name": item["name"], "lines": [], "stars": {}})
        figure["lines"].extend(polylines)
        for hip, star in members.items():
            lon, lat = star["geometry"]["coordinates"]
            meta = names.get(str(hip), {})
            known = star_item_by_hip.get(hip)
            bayer = f"{meta['bayer']} {con_ko.get(meta.get('c'), abbr)}" if meta.get("bayer") else None
            figure["stars"][str(hip)] = {
                "hip": hip, "ra_deg": ra_from_lon(lon), "dec_deg": lat, "mag": star["properties"]["mag"],
                "name": known["name"] if known else (meta.get("name") or bayer or f"HIP {hip}"),
                "item_id": known["id"] if known else None,
            }

    all_hips = sorted({int(h) for f in figures.values() for h in f["stars"]})
    distances = _distances(all_hips, refresh)
    korean = _korean_names(all_hips, refresh)
    for figure in figures.values():
        for hip, star in figure["stars"].items():
            d = distances.get(int(hip))
            star["distance_ly"] = round(d["ly"], 2) if d else None
            star["distance_basis"] = d["basis"] if d else None
            ko = korean.get(int(hip), {})
            star["wiki_title"] = ko.get("title")                      # 한국어 위키 문서 (없으면 None)
            if not star["item_id"] and ko.get("label"):                # 카탈로그 밖의 별은 한국어 이름으로
                star["name"] = ko["label"]
    return {"figures": figures, "unmatched_vertices": unmatched,
            "licenses": LICENSES}


def collect_sky_stars(refresh: bool = False) -> list[list[float]]:
    """맨눈 별 (6등급까지, 약 5천 개) — 천구 화면의 배경 하늘. [적경, 적위, 등급, 색지수(B−V)].

    출처는 별자리 선과 같은 d3-celestial stars.6 (BSD-3-Clause). 색지수가 없으면 0.6(태양 정도)으로 둔다.
    """
    rows = []
    for f in sources.d3_file("stars.6.json", refresh)["features"]:
        lon, lat = f["geometry"]["coordinates"]
        bv = f["properties"].get("bv")
        try:
            bv = float(bv)
        except (TypeError, ValueError):
            bv = 0.6
        rows.append([round(ra_from_lon(lon), 3), round(lat, 3), round(f["properties"]["mag"], 2), round(bv, 2)])
    return rows


def sky_stars_path():
    from vasthorizon.config import get_settings
    return get_settings().paths.data_dir / "sky_stars.json"


def load_sky_stars() -> list[list[float]]:
    import json
    path = sky_stars_path()
    return json.loads(path.read_text(encoding="utf-8"))["stars"] if path.exists() else []


def figures_path():
    from vasthorizon.config import get_settings
    return get_settings().paths.data_dir / "constellations.json"


def load_figures() -> dict:
    """항목 ID → 별자리 모양. 파일이 없으면 빈 사전 (python -m scripts.collect_constellations)."""
    import json
    path = figures_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {fig["item_id"]: fig for fig in data["figures"].values()}


def figure_stats(figure: dict) -> dict:
    """펼치기 설명용 통계 — 거리가 알려진 별 기준."""
    known = sorted((s for s in figure["stars"].values() if s.get("distance_ly")), key=lambda s: s["distance_ly"])
    if not known:
        return {"stars": len(figure["stars"]), "known": 0}
    near, far = known[0], known[-1]
    return {"stars": len(figure["stars"]), "known": len(known), "nearest": near, "farthest": far,
            "spread_ly": round(far["distance_ly"] - near["distance_ly"], 1),
            "ratio": round(far["distance_ly"] / near["distance_ly"], 1) if near["distance_ly"] else None}
