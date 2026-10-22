"""별자리 펼치기 (F2010) — 별자리는 지구에서만 보이는 모양이다.

화면은 별자리 선을 이루는 별들을 실제 거리 위치로 펼치고, 설명은 그 거리 차이를 근거와 함께 알려준다.

근거 (모두 카탈로그 · 별자리 모양 데이터에서 만든다 — 화면에 그리는 거리와 설명의 거리가 같다)
1. 별자리 항목 텍스트 (약어 · 관측 계절 · 가장 밝은 별 …)
2. 별 거리표 — 선을 이루는 별의 거리 (Wikidata 값을 연주시차로 검증, d3-celestial로 별 연결)
3. 별자리 자체의 한국어 위키 문서 앞부분 (캐시 우선, 받지 못하면 빼고 쓴다)

설명은 질의응답과 같은 인용 검증 · 재생성 정책을 따른다 (rag/graph.py generate_validated).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel

from vasthorizon.collect.collector import Collector, StepFailure
from vasthorizon.data.constellation_figures import figure_stats
from vasthorizon.data.item_text import korean_number
from vasthorizon.features.evidence import catalog_evidence, computed_evidence, doc_excerpt_evidence
from vasthorizon.rag.graph import default_chat_model, generate_validated
from vasthorizon.rag.prompts import unfold_messages
from vasthorizon.rag.retrieval import Evidence

TABLE_STARS = 15            # 거리표에 넣는 별 수 (밝은 순) — 가장 가까운 · 먼 별은 항상 넣는다
OWN_DOC_CHARS = 2000
FIGURE_SOURCE_URL = "https://github.com/ofrohn/d3-celestial"


class FigureUnavailableError(LookupError):
    """이 항목은 별자리 모양 데이터가 없다 (별자리가 아니거나 데이터 미수집)."""


@dataclass
class UnfoldResult:
    item: dict
    figure: dict
    stats: dict
    explanation: str
    status: str                       # cited · not_found · rejected
    cited: list[Evidence]
    evidences: list[Evidence]
    attempts: int = 1
    warnings: list[str] = field(default_factory=list)


def figure_for(item: dict, figures: dict) -> dict:
    if item["group"] != "constellation":
        raise FigureUnavailableError(f"{item['name']}은(는) 별자리가 아닙니다.")
    figure = figures.get(item["id"])
    if figure is None:
        raise FigureUnavailableError(f"{item['name']}의 별자리 모양 데이터가 없습니다. "
                                     "python -m scripts.collect_constellations 를 실행해 주세요.")
    return figure


def _star_line(star: dict) -> str:
    return f"- {star['name']} (HIP {star['hip']}): 약 {korean_number(star['distance_ly'])}광년, 겉보기 등급 {star['mag']:g}"


def star_table(figure: dict, stats: dict) -> list[str]:
    """거리표 — 밝은 별 TABLE_STARS개 + 가장 가까운 · 먼 별, 거리순."""
    known = [s for s in figure["stars"].values() if s.get("distance_ly")]
    picked = {s["hip"]: s for s in sorted(known, key=lambda s: s["mag"])[:TABLE_STARS]}
    for key in ("nearest", "farthest"):
        if stats.get(key):
            picked[stats[key]["hip"]] = stats[key]
    lines = [f"{figure['name']}의 선을 이루는 별 {stats['stars']}개 중 거리가 알려진 별 {stats['known']}개"]
    if stats.get("nearest"):
        near, far = stats["nearest"], stats["farthest"]
        lines.append(f"가장 가까운 별: {near['name']} 약 {korean_number(near['distance_ly'])}광년 · "
                     f"가장 먼 별: {far['name']} 약 {korean_number(far['distance_ly'])}광년 · "
                     f"차이 약 {korean_number(stats['spread_ly'])}광년"
                     + (f" (약 {stats['ratio']:g}배)" if stats.get("ratio") else ""))
    lines += [_star_line(s) for s in sorted(picked.values(), key=lambda s: s["distance_ly"])]
    return lines


def unfold(item: dict, figure: dict, ref_year: int, llm: BaseChatModel | None = None,
           collector: Collector | None = None) -> UnfoldResult:
    stats = figure_stats(figure)
    warnings: list[str] = []
    if stats["known"] < 2:
        raise FigureUnavailableError(f"{item['name']}은(는) 거리가 알려진 별이 부족해 펼쳐 볼 수 없습니다.")

    evidences = [catalog_evidence(item, ref_year, number=1),
                 computed_evidence(2, f"{item['name']} 별 거리표", star_table(figure, stats),
                                   chunk_id=f"figure:{item['id']}", url=FIGURE_SOURCE_URL)]
    failures: list[StepFailure] = []
    doc = (collector or Collector()).fetch_wiki(item["wiki_title"], failures)
    if doc is not None:
        evidences.append(doc_excerpt_evidence(3, doc, OWN_DOC_CHARS))
    else:
        warnings.append(f"「{item['wiki_title']}」 문서를 받지 못해 거리 데이터만으로 설명합니다.")

    result = generate_validated(default_chat_model(llm), unfold_messages(item, evidences), evidences)
    if result["status"] == "rejected":
        warnings.append("설명이 인용 규칙을 두 번 어겨 내보내지 않았습니다.")
    return UnfoldResult(item=item, figure=figure, stats=stats, explanation=result["answer"],
                        status=result["status"], cited=result["cited"], evidences=evidences,
                        attempts=result["attempts"], warnings=warnings)
