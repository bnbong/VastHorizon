"""카탈로그 밖의 별도 하나의 천체로 — 오늘 밤 하늘에서 누른 별에 대해 바로 물어보기.

| 별                          | 항목 데이터                                                         |
|-----------------------------|---------------------------------------------------------------------|
| 별자리 선의 별 (756개)        | 별자리 모양 데이터(data/constellations.json) — 외부 호출 없음         |
| 그 밖의 히파르코스 별 (11만 개) | 위치 · 등급은 하늘 데이터(web/data), 거리 · 이름 · 위키 문서는 누를 때 Wikidata 조회 (캐시) |

카탈로그(424건)에는 밝은 별 94개만 있지만, 하늘에서 누를 수 있는 별자리 선의 별은 756개다 (중복 제외).
카탈로그 밖의 별은 별자리 모양 데이터(data/constellations.json)로 '임시 항목'을 만든다.

| 항목 필드   | 값                                                            |
|-------------|---------------------------------------------------------------|
| id          | hip:<히파르코스 번호>                                          |
| wiki_title  | Wikidata에 연결된 한국어 위키 문서 (없으면 None — 문서 검색만) |
| distance    | Wikidata 거리(연주시차로 검증) — 별자리 모양 데이터와 같은 값   |
| adhoc       | True — 질의응답의 근거 1을 색인이 아니라 이 데이터로 만든다     |

임시 항목은 문서 수집 · 색인 · 대화 기록에서 일반 항목과 똑같이 쓰인다 (항목 ID로 구분).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from vasthorizon.data.atomic import atomic_write_text
from vasthorizon.data.items.common import LY_KM, distance_with_parallax

STAR_ID = re.compile(r"^hip:(\d+)$")


def star_index(figures: dict) -> dict[int, tuple[dict, dict]]:
    """히파르코스 번호 → (별, 그 별이 속한 별자리 모양). 카탈로그 별은 빼지 않는다 (호출 쪽이 고른다)."""
    index: dict[int, tuple[dict, dict]] = {}
    for figure in figures.values():
        for star in figure["stars"].values():
            index.setdefault(int(star["hip"]), (star, figure))
    return index


def star_item(item_id: str, index: dict[int, tuple[dict, dict]], ref_year: int) -> dict | None:
    m = STAR_ID.match(item_id or "")
    if not m or int(m.group(1)) not in index:
        return None
    star, figure = index[int(m.group(1))]
    if not star.get("distance_ly"):
        return None
    km = star["distance_ly"] * LY_KM
    return {
        "id": item_id, "group": "star", "kind": "항성", "adhoc": True, "ref_year": ref_year,
        "name": star["name"], "name_en": None, "wiki_title": star.get("wiki_title"),
        "ra_deg": star["ra_deg"], "dec_deg": star["dec_deg"],
        "distance": {"km": km, "ly": star["distance_ly"], "basis": star.get("distance_basis") or "wikidata",
                     "reference": "지구에서 천체까지", "approximate": False, "method": None,
                     "km_min": None, "km_max": None, "n_values": 1},
        "attrs": {"히파르코스 번호": f"HIP {star['hip']}", "별자리": figure["name"], "겉보기 등급": star["mag"],
                  "맨눈 관측": star["mag"] <= 6.0},
        "sources": [{"name": "Wikidata", "url": "https://www.wikidata.org/", "used_for": "거리 (연주시차로 검증)"},
                    {"name": "d3-celestial", "url": "https://github.com/ofrohn/d3-celestial", "used_for": "좌표 · 등급"}],
    }


# ── 아무 별 — 히파르코스 번호로 Wikidata 조회 ──────────────────────────────

HIPPARCOS = "Q537199"
MILLIARCSECOND = "Q21500224"


class StarLookupError(RuntimeError):
    """Wikidata 조회 실패 (일시 장애) — 결과를 캐시하지 않는다."""


def wikidata_star_query(hip: int) -> str:
    return f"""
        SELECT ?item ?en ?ko ?title ?distM ?plx WHERE {{
          ?item p:P528 [ ps:P528 "HIP {hip}" ; pq:P972 wd:{HIPPARCOS} ] .
          OPTIONAL {{ ?item rdfs:label ?en FILTER(lang(?en) = "en") }}
          OPTIONAL {{ ?item rdfs:label ?ko FILTER(lang(?ko) = "ko") }}
          OPTIONAL {{ ?page schema:about ?item ; schema:isPartOf <https://ko.wikipedia.org/> ; schema:name ?title }}
          OPTIONAL {{ ?item p:P2583/psn:P2583/wikibase:quantityAmount ?distM }}
          OPTIONAL {{ ?item p:P2214/psv:P2214 [ wikibase:quantityAmount ?plx ; wikibase:quantityUnit wd:{MILLIARCSECOND} ] }}
        }}"""


FACTS_VERSION = 2       # 캐시 형식 — 엔티티별로 나누기 전(버전 없음)의 캐시는 다시 조회한다 (12-1 리뷰 P1)


def _entity_facts(qid: str, rows: list[dict]) -> dict:
    """한 엔티티의 행 → 사실. OPTIONAL 조인으로 같은 값이 여러 행에 반복되므로 서로 다른 값만 센다."""
    values = lambda key: sorted({r[key] for r in rows if r.get(key)})
    plx = sorted({float(v) for v in values("plx") if float(v) > 0})
    dist = distance_with_parallax([float(v) / 1000 for v in values("distM")], plx[len(plx) // 2] if plx else None)
    first = lambda key: (values(key) or [None])[0]
    return {"qid": qid, "name_en": first("en"), "name_ko": first("ko"), "wiki_title": first("title"),
            "distance": None if dist is None else {"km": dist.km, "ly": dist.ly, "basis": dist.basis, "method": dist.method}}


def star_facts(rows: list[dict]) -> dict:
    """SPARQL 행 → {qid, name_en, name_ko, wiki_title, distance, ambiguous, version}.

    한 히파르코스 번호에 Wikidata 엔티티가 여럿 걸릴 수 있다 (예: 쌍성의 별과 계). 이름 · 문서 · 거리 · 시차는
    반드시 한 엔티티 안에서만 만든다. 거리가 있는 엔티티가
      0개 → 거리 없음 (이름은 QID 순으로 첫 엔티티)
      1개 → 그 엔티티
      2개 이상 → 모호함 — 어느 별인지 정할 수 없으므로 거리를 쓰지 않는다 (담지 않음)
    행 순서와 관계없이 같은 결과가 나온다 (QID · 값 정렬). 거리는 연주시차로 교차 검증 (common.distance_with_parallax).
    """
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault((r.get("item") or "").rsplit("/", 1)[-1], []).append(r)
    entities = [_entity_facts(qid, groups[qid]) for qid in sorted(groups) if qid]
    with_distance = [e for e in entities if e["distance"]]
    if len(with_distance) > 1:
        return {"qid": None, "name_en": None, "name_ko": None, "wiki_title": None, "distance": None,
                "ambiguous": [e["qid"] for e in with_distance], "version": FACTS_VERSION}
    chosen = with_distance[0] if with_distance else (entities[0] if entities else
             {"qid": None, "name_en": None, "name_ko": None, "wiki_title": None, "distance": None})
    return {**chosen, "ambiguous": None, "version": FACTS_VERSION}


class StarLookup:
    """hip:<번호> → 임시 항목. 별자리 선의 별은 모양 데이터로, 그 밖은 Wikidata 조회(캐시)로.

    positions: 히파르코스 번호 → (적경, 적위, 등급, 색지수) — sky_catalog.load_star_index
    fetch:     (SPARQL 문자열) → 행 목록. 실패하면 예외 — StarLookupError로 바꿔 올린다 (캐시하지 않음)
    거리를 확인할 수 없거나 엔티티가 모호한 별은 None — 내 세계에 담을 수 없다 (거리를 지어내지 않는다).
    """

    def __init__(self, figure_index: dict, positions: dict, cache_dir: Path, fetch: Callable, ref_year: int):
        self.figure_index, self.positions, self.cache_dir, self.fetch, self.ref_year = (
            figure_index, positions, cache_dir, fetch, ref_year)

    def facts(self, hip: int) -> dict:
        path = self.cache_dir / f"hip_{hip}.json"
        if path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("version") == FACTS_VERSION:
                return cached                               # 이전 형식은 다시 조회해 덮어쓴다
        try:
            facts = star_facts(self.fetch(wikidata_star_query(hip)))
        except Exception as e:                              # 네트워크 · Wikidata 장애
            raise StarLookupError(f"Wikidata 조회 실패: {type(e).__name__}") from e
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(facts, ensure_ascii=False))
        return facts

    def __call__(self, item_id: str) -> dict | None:
        found = star_item(item_id, self.figure_index, self.ref_year)
        m = STAR_ID.match(item_id or "")
        if found is not None or not m:
            return found
        hip = int(m.group(1))
        if hip not in self.positions:
            return None
        facts = self.facts(hip)
        if not facts.get("distance"):
            return None
        ra, dec, mag, bv = self.positions[hip]
        d = facts["distance"]
        return {
            "id": item_id, "group": "star", "kind": "항성", "adhoc": True, "ref_year": self.ref_year,
            "name": facts.get("name_ko") or facts.get("name_en") or f"HIP {hip}", "name_en": facts.get("name_en"),
            "wiki_title": facts.get("wiki_title"), "ra_deg": ra, "dec_deg": dec,
            "distance": {"km": d["km"], "ly": d["ly"], "basis": d["basis"], "reference": "지구에서 천체까지",
                         "approximate": False, "method": d.get("method"), "km_min": None, "km_max": None, "n_values": 1},
            "attrs": {"히파르코스 번호": f"HIP {hip}", "겉보기 등급": round(mag, 2), "색지수(B−V)": round(bv, 2),
                      "맨눈 관측": mag <= 6.0},
            "sources": [{"name": "Wikidata", "url": f"https://www.wikidata.org/wiki/{facts['qid']}" if facts.get("qid")
                         else "https://www.wikidata.org/", "used_for": "거리 · 이름 (가까운 별은 연주시차로 교차 검증)"},
                        {"name": "d3-celestial", "url": "https://github.com/ofrohn/d3-celestial", "used_for": "좌표 · 등급 · 색지수"}],
        }
