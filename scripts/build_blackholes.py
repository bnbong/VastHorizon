"""은하 중심 블랙홀 목록 — 근거(Wikidata 연결 · 위키 문서 문장)가 있는 메시에 은하만 web/data/blackholes.json으로.

    python -m scripts.build_blackholes

입력: data/items.json (메시에 항목), data/cache/docs/wiki/*.json (색인한 위키 문서), Wikidata SPARQL.
화면은 이 파일에 있는 은하에만 가르강튀아 모습(상상도)을 띄우고, 근거 문장과 출처를 함께 보여 준다.
"""

from __future__ import annotations

import json

from vasthorizon.config import PROJECT_ROOT
from vasthorizon.data.black_holes import SPARQL, select
from vasthorizon.http import http

GALAXY_WORDS = ("은하", "LINER")


def main() -> int:
    data = json.loads((PROJECT_ROOT / "data" / "items.json").read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) else data
    galaxies = [i for i in items if i["group"] == "messier" and any(w in (i.get("kind") or "") for w in GALAXY_WORDS)]
    docs = {}
    for f in (PROJECT_ROOT / "data" / "cache" / "docs" / "wiki").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        docs[d["title"]] = d
    ids = " ".join(f"wd:{g['id']}" for g in galaxies)
    res = http().get("https://query.wikidata.org/sparql", params={"query": SPARQL.format(ids=ids), "format": "json"}, timeout=90)
    res.raise_for_status()
    wikidata = {}
    for b in res.json()["results"]["bindings"]:
        wikidata[b["g"]["value"].rsplit("/", 1)[-1]] = {"qid": b["bh"]["value"].rsplit("/", 1)[-1], "label": b["bhLabel"]["value"]}
    chosen = select(galaxies, docs, wikidata)
    out = PROJECT_ROOT / "web" / "data" / "blackholes.json"
    out.write_text(json.dumps({"note": "가르강튀아 모습은 일반상대론으로 빛의 경로를 계산한 상상도이며, 실제 크기 · 모습이 아닙니다.",
                               "galaxies": chosen}, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in chosen:
        print(f"  {c['code']:<5} {c['name']:<12} {c['black_hole'] or '-':<8} {'Wikidata' if c['wikidata'] else '':<9} {(c['quote'] or '')[:60]}")
    print(f"은하 {len(chosen)}곳 · web/data/blackholes.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
