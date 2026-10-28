"""은하 중심 블랙홀 목록 — 근거(Wikidata 연결 · 위키 문서 문장)가 있는 은하만 web/data/blackholes.json으로.

    python -m scripts.build_blackholes
    python -m scripts.build_blackholes --allow-missing   # 문서 캐시에 없는 대상이 있어도 만든다 (문서 근거만 있는 은하는 빠진다)

입력: data/items.json (메시에 은하 · 우리 은하 · 궁수자리 A*), data/cache/docs/wiki/*.json (위키 문서),
vasthorizon/data/enrich.json (고정 인용문), Wikidata SPARQL.
화면은 이 파일에 있는 은하에만 가르강튀아 모습(상상도)을 띄우고, 근거 문장과 출처를 함께 보여 준다.

다음 경우 파일을 바꾸지 않고 종료 코드 1로 끝난다.
  - 대상 항목의 위키 문서가 문서 캐시에 없다 (먼저 python -m scripts.collect_docs --own --group messier · milky_way)
  - enrich.json의 고정 인용문이 문서 본문에 없다
"""

from __future__ import annotations

import argparse
import json

from vasthorizon.config import PROJECT_ROOT
from vasthorizon.data.black_holes import SPARQL, fixed_quotes, missing_documents, select
from vasthorizon.data.docs.wikipedia import LICENSE
from vasthorizon.data.enrich import enrichment
from vasthorizon.data.item_text import item_category
from vasthorizon.http import http

GALAXY_WORDS = ("은하", "LINER")


def targets_of(items: list[dict]) -> tuple[list[dict], set[str]]:
    """(대상 항목 — 카탈로그 순서, 블랙홀 자체인 항목 QID).
    대상: 메시에 은하 + 우리 은하(범주 '은하') + 블랙홀 자체인 항목(궁수자리 A*, 범주 '블랙홀')."""
    targets, selves = [], set()
    for it in items:
        if it["group"] == "messier" and any(w in (it.get("kind") or "") for w in GALAXY_WORDS):
            targets.append(it)
        elif it["group"] == "milky_way":
            category = item_category(it)
            if category == "블랙홀":
                selves.add(it["id"])
            if category in ("은하", "블랙홀"):
                targets.append(it)
    return targets, selves


def load_docs() -> dict[str, dict]:
    docs = {}
    for f in (PROJECT_ROOT / "data" / "cache" / "docs" / "wiki").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        docs[d["title"]] = d
    return docs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-missing", action="store_true",
                        help="문서 캐시에 없는 대상이 있어도 만든다 (문서 근거만 있는 은하는 빠진다)")
    args = parser.parse_args(argv)

    data = json.loads((PROJECT_ROOT / "data" / "items.json").read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) else data
    targets, selves = targets_of(items)
    docs = load_docs()

    missing = missing_documents(targets, docs)
    if missing and not args.allow_missing:
        print(f"[FAIL] 문서 캐시(data/cache/docs/wiki)에 없는 대상 {len(missing)}건 — web/data/blackholes.json을 바꾸지 않습니다.")
        for m in missing:
            print(f"  - {m}")
        print("  python -m scripts.collect_docs --own --group messier (· milky_way)로 먼저 받거나 --allow-missing을 붙이세요.")
        return 1
    fixed, errors = fixed_quotes(enrichment(), docs, LICENSE)
    if errors:
        print("[FAIL] 고정 인용문 확인 실패 — web/data/blackholes.json을 바꾸지 않습니다.")
        for e in errors:
            print(f"  - {e}")
        return 1

    ids = " ".join(f"wd:{g['id']}" for g in targets if g["id"] not in selves)
    res = http().get("https://query.wikidata.org/sparql", params={"query": SPARQL.format(ids=ids), "format": "json"}, timeout=90)
    res.raise_for_status()
    wikidata = {}
    for b in res.json()["results"]["bindings"]:
        wikidata[b["g"]["value"].rsplit("/", 1)[-1]] = {"qid": b["bh"]["value"].rsplit("/", 1)[-1], "label": b["bhLabel"]["value"]}
    chosen = select(targets, docs, wikidata, fixed=fixed, selves=selves, catalog_ids={it["id"] for it in items})
    out = PROJECT_ROOT / "web" / "data" / "blackholes.json"
    out.write_text(json.dumps({"note": "가르강튀아 모습은 일반상대론으로 빛의 경로를 계산한 상상도이며, 실제 크기 · 모습이 아닙니다.",
                               "galaxies": chosen}, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in chosen:
        print(f"  {c['code'] or '-':<5} {c['name']:<12} {c['black_hole'] or '-':<8} {'Wikidata' if c['wikidata'] else '':<9} {(c['quote'] or '')[:60]}")
    print(f"은하 {len(chosen)}곳 · web/data/blackholes.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
