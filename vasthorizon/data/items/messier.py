"""🌌 메시에 천체 — 성운 · 성단 · 은하 110개.

Wikidata의 메시에 목록 번호(P528, 목록 = 메시에 목록)로 모은다.
거리는 출처마다 값이 여러 개라서 중앙값과 최소~최대 범위를 함께 둔다.
"""

from __future__ import annotations

from collections import defaultdict

from vasthorizon.data import sources
from vasthorizon.data.items.common import Item, distance_from_values

MESSIER_CATALOG = "Q14530"

QUERY = f"""
SELECT ?item ?code ?title ?en ?ra ?dec ?mag ?typeLabel ?conLabel ?distM WHERE {{
  ?item p:P528 [ ps:P528 ?code ; pq:P972 wd:{MESSIER_CATALOG} ] .
  ?a schema:about ?item ; schema:isPartOf <https://ko.wikipedia.org/> ; schema:name ?title .
  OPTIONAL {{ ?item rdfs:label ?en FILTER(lang(?en) = "en") }}
  OPTIONAL {{ ?item wdt:P6257 ?ra }} OPTIONAL {{ ?item wdt:P6258 ?dec }}
  OPTIONAL {{ ?item wdt:P1215 ?mag }}
  OPTIONAL {{ ?item wdt:P31 ?type . ?type rdfs:label ?typeLabel FILTER(lang(?typeLabel) = "ko") }}
  OPTIONAL {{ ?item wdt:P59 ?con . ?con rdfs:label ?conLabel FILTER(lang(?conLabel) = "ko") }}
  OPTIONAL {{ ?item p:P2583/psn:P2583/wikibase:quantityAmount ?distM }}
}}
"""

# 너무 일반적인 분류는 종류 표시에서 뒤로 미룬다
GENERIC_TYPES = {"천체", "성단", "은하", "성운", "딥스카이 천체"}


def _messier_number(code: str) -> int:
    return int("".join(ch for ch in code if ch.isdigit()))


def collect(refresh: bool = False) -> list[Item]:
    rows = sources.cached("messier_wikidata", lambda: sources.sparql(QUERY), refresh)

    merged: dict[str, dict] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        rec = merged[sources.qid(row["item"])]
        for key, value in row.items():
            rec[key].add(value)

    items = []
    for qid, rec in merged.items():
        number = _messier_number(min(rec["code"]))
        title = min(rec["title"])
        types = sorted(rec.get("typeLabel", []), key=lambda t: (t in GENERIC_TYPES, t))
        mags = [float(v) for v in rec.get("mag", [])]
        dist = distance_from_values([float(v) / 1000 for v in rec.get("distM", [])], "wikidata")
        attrs = {
            "메시에 번호": f"M{number}",
            "별자리": min(rec["conLabel"]) if rec.get("conLabel") else None,
            "겉보기 등급": min(mags) if mags else None,
            "맨눈 관측": bool(mags) and min(mags) <= 6,
            "분류": ", ".join(types[:3]) or None,
        }
        items.append(Item(
            id=qid, group="messier", name=title, wiki_title=title,
            name_en=min(rec["en"]) if rec.get("en") else None,
            kind=types[0] if types else "딥스카이 천체", distance=dist,
            ra_deg=float(min(rec["ra"])) if rec.get("ra") else None,
            dec_deg=float(min(rec["dec"])) if rec.get("dec") else None,
            attrs={k: v for k, v in attrs.items() if v not in (None, "")},
            sources=[{"name": "Wikidata", "url": sources.SOURCE_URLS["Wikidata"].format(id=qid)}],
        ))
    items.sort(key=lambda it: _messier_number(it.attrs["메시에 번호"]))
    return items
