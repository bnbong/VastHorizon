"""은하 중심 블랙홀 — 화면에서 가르강튀아 모습(일반상대론으로 계산한 상상도)을 띄울 은하를 고른다.

지어내지 않는다. 다음 둘 중 하나로 근거가 있는 은하만 고른다.
  - Wikidata: 은하가 블랙홀(Q589의 하위 분류) 항목을 부분(P527)으로 갖거나, 블랙홀이 그 은하의 일부(P361)
    2단계까지 본다 — 우리 은하(Q321) → 은하중심(Q649112) → 궁수자리 A*(Q237284)
  - 서비스가 색인한 한국어 위키 문서: 은하의 중심(핵)에 초대질량 블랙홀이 있다고 사실로 서술한 문장
    ("생겨날 가능성", "나타나지 않으며" 같은 가정 · 부정 문장은 근거로 쓰지 않는다)
결과(web/data/blackholes.json)에는 근거 문장과 출처를 함께 남겨 화면에 그대로 보여 준다.

고정 인용문 — 문서에서 고른 문장이 가정 문장이거나 Wikidata 값과 숫자가 어긋나면(우리 은하 · 궁수자리 A*)
enrich.json 항목에 quote와 quote_doc({title, url, permalink})를 적어 그것을 쓴다.
문서 캐시에 그 문서가 있으면 인용문이 본문에 실제로 들어 있는지 확인한다 (지어낸 인용이 들어가지 않게).

| 결과 필드  | 뜻                                                                     |
|------------|------------------------------------------------------------------------|
| code       | 메시에 번호 — 메시에 천체가 아니면 null (우리 은하 · 궁수자리 A*)       |
| center_id  | 중심 블랙홀이 카탈로그 항목이면 그 QID — 화면이 그 항목을 연다 (우리 은하) |
| self       | 블랙홀 자체인 항목 — 은하 사진 없이 블랙홀이 곧 근접 모습 (궁수자리 A*)  |
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
  {{ ?g wdt:P527 ?bh }} UNION {{ ?bh wdt:P361 ?g }} UNION {{ ?g wdt:P527/wdt:P527 ?bh }} UNION {{ ?bh wdt:P361/wdt:P361 ?g }}
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


def _normalize(text: str) -> str:
    return " ".join((text or "").split())


def missing_documents(targets: list[dict], docs_by_title: dict[str, dict]) -> list[str]:
    """대상 항목 중 문서 캐시에 자기 위키 문서가 없는 것 — '이름 (문서 제목)' 목록.
    문서가 없으면 문서 근거만 있는 은하가 결과에서 조용히 빠진다 (예: M84 · M104)."""
    return [f"{t['name']} ({t.get('wiki_title')})" for t in targets
            if not t.get("wiki_title") or t["wiki_title"] not in docs_by_title]


def fixed_quotes(enrich: dict[str, dict], docs_by_title: dict[str, dict],
                 default_license: str | None = None) -> tuple[dict[str, dict], list[str]]:
    """enrich.json에 고정한 인용문 — (항목 QID → {"quote", "doc"}, 오류 목록).
    문서 캐시에 그 문서가 있으면 인용문이 본문에 들어 있는지 확인하고, 없으면 오류로 남긴다."""
    fixed, errors = {}, []
    for qid, entry in enrich.items():
        quote, ref = entry.get("quote"), entry.get("quote_doc")
        if not quote or not ref:
            continue
        cached = docs_by_title.get(ref.get("title") or "")
        if cached is not None and _normalize(quote) not in _normalize(cached.get("text")):
            errors.append(f"{entry.get('name') or qid}: 고정 인용문이 「{ref.get('title')}」 문서 본문에 없습니다")
            continue
        fixed[qid] = {"quote": quote,
                      "doc": {"title": ref["title"], "url": ref["url"], "permalink": ref.get("permalink"),
                              "license": (cached or {}).get("license") or default_license}}
    return fixed, errors


def select(galaxies: list[dict], docs_by_title: dict[str, dict], wikidata: dict[str, dict],
           fixed: dict[str, dict] | None = None, selves: set[str] = frozenset(),
           catalog_ids: set[str] = frozenset()) -> list[dict]:
    """galaxies: 대상 카탈로그 항목(메시에 은하 · 우리 은하 · 블랙홀 자체 항목), docs_by_title: 위키 문서
    (title → {text, url, permalink, license}), wikidata: 은하 QID → {qid, label}, fixed: 고정 인용문 (fixed_quotes),
    selves: 블랙홀 자체인 항목 QID, catalog_ids: 카탈로그 QID (중심 블랙홀이 항목이면 center_id).
    근거가 하나라도 있는 항목만, 카탈로그 순서대로."""
    fixed = fixed or {}
    out = []
    for g in galaxies:
        is_self = g["id"] in selves
        if g["id"] in fixed:
            sentence, doc = fixed[g["id"]]["quote"], fixed[g["id"]]["doc"]
        else:
            doc = docs_by_title.get(g.get("wiki_title") or "")
            sentence = central_black_hole_sentence(doc["text"]) if doc else None
            doc = {"title": doc["title"], "url": doc["url"], "permalink": doc.get("permalink"),
                   "license": doc.get("license")} if sentence else None
        # 블랙홀 자체인 항목은 자기 Wikidata 항목이 근거다
        wd = {"qid": g["id"], "label": g["name"]} if is_self else wikidata.get(g["id"])
        if not sentence and not wd:
            continue
        entry = {
            "id": g["id"], "name": g["name"], "code": (g.get("attrs") or {}).get("메시에 번호"),
            "black_hole": black_hole_name(sentence, wd and wd["label"]),
            "quote": sentence,
            "doc": doc,
            "wikidata": {"qid": wd["qid"], "url": f"https://www.wikidata.org/wiki/{wd['qid']}"} if wd else None,
        }
        if is_self:
            entry["self"] = True
        elif wd and wd["qid"] in catalog_ids:
            entry["center_id"] = wd["qid"]
        out.append(entry)
    return out
