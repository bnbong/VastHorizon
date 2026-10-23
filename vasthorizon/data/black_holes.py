"""은하 중심 블랙홀 — 화면에서 가르강튀아 모습(일반상대론으로 계산한 상상도)을 띄울 은하를 고른다.

지어내지 않는다. 다음 둘 중 하나로 근거가 있는 은하만 고른다.
  - Wikidata: 은하가 블랙홀(Q589의 하위 분류) 항목을 부분(P527)으로 갖거나, 블랙홀이 그 은하의 일부(P361)
  - 서비스가 색인한 한국어 위키 문서: 은하의 중심(핵)에 초대질량 블랙홀이 있다고 사실로 서술한 문장
    ("생겨날 가능성", "나타나지 않으며" 같은 가정 · 부정 문장은 근거로 쓰지 않는다)
결과(web/data/blackholes.json)에는 근거 문장과 출처를 함께 남겨 화면에 그대로 보여 준다.
"""

from __future__ import annotations

import re

KINDS = ("초대질량", "초거대질량")
WHERE = ("중심", "핵")
EXISTS = ("발견", "존재", "에 있는", "위치")
HEDGES = ("가능성", "않", "없", "아닌", "대신", "만약", "생겨날", "가설")
_SENTENCE = re.compile(r"(?<=[.다])\s+")
_NAME = re.compile(r"([A-Z]+\s?\d+\*)")

SPARQL = """SELECT DISTINCT ?g ?bh ?bhLabel WHERE {{
  VALUES ?g {{ {ids} }}
  {{ ?g wdt:P527 ?bh }} UNION {{ ?bh wdt:P361 ?g }}
  ?bh wdt:P31/wdt:P279* wd:Q589 .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ko,en". }} }}"""


def central_black_hole_sentence(text: str) -> str | None:
    """중심(핵)의 초대질량 블랙홀을 사실로 서술한 문장. 존재를 직접 말하는 문장("발견", "있는")을 먼저. 없으면 None."""
    found = []
    for raw in _SENTENCE.split(text or ""):
        s = raw.strip()
        if "=" in s or "블랙홀" not in s:            # 절 제목이 섞인 조각은 건너뛴다
            continue
        if not any(k in s for k in KINDS) or not any(w in s for w in WHERE):
            continue
        if any(h in s for h in HEDGES):
            continue
        found.append(s)
    strong = [s for s in found if any(w in s for w in EXISTS)]
    return (strong or found or [None])[0]


def black_hole_name(sentence: str | None, wikidata_label: str | None) -> str | None:
    """M87* · M31* 같은 이름 — Wikidata 이름이 먼저, 없으면 근거 문장 안의 이름."""
    if wikidata_label:
        return wikidata_label
    m = _NAME.search(sentence or "")
    return m.group(1).replace(" ", "") if m else None


def select(galaxies: list[dict], docs_by_title: dict[str, dict], wikidata: dict[str, dict]) -> list[dict]:
    """galaxies: 메시에 카탈로그 항목, docs_by_title: 위키 문서(title → {text, url, permalink, license}),
    wikidata: 은하 QID → {qid, label}. 근거가 하나라도 있는 은하만, 카탈로그 순서대로."""
    out = []
    for g in galaxies:
        doc = docs_by_title.get(g.get("wiki_title") or "")
        sentence = central_black_hole_sentence(doc["text"]) if doc else None
        wd = wikidata.get(g["id"])
        if not sentence and not wd:
            continue
        out.append({
            "id": g["id"], "name": g["name"], "code": (g.get("attrs") or {}).get("메시에 번호"),
            "black_hole": black_hole_name(sentence, wd and wd["label"]),
            "quote": sentence,
            "doc": {"title": doc["title"], "url": doc["url"], "permalink": doc.get("permalink"), "license": doc.get("license")}
                   if sentence else None,
            "wikidata": {"qid": wd["qid"], "url": f"https://www.wikidata.org/wiki/{wd['qid']}"} if wd else None,
        })
    return out
