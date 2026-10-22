"""서비스 기능 공용 근거 — 카탈로그 데이터로 직접 만드는 근거.

계산값(출발 연도 · 별 거리 · 하늘 위치)을 쓰는 기능은 근거도 같은 카탈로그 데이터에서 만든다.
색인에서 가져오면 카탈로그가 갱신됐는데 색인이 아직일 때 계산값과 근거가 어긋날 수 있기 때문이다.
(8a 리뷰 — 빛의 편지 데이터 일관성)
"""

from __future__ import annotations

from vasthorizon.data.item_text import SOURCE_TYPE as ITEM_SOURCE
from vasthorizon.data.item_text import build_item_text
from vasthorizon.rag.retrieval import KIND_DOC, KIND_ITEM, Evidence

COMPUTED_SOURCE = "계산값 (카탈로그 좌표 · 거리)"


def catalog_evidence(item: dict, ref_year: int, number: int = 1) -> Evidence:
    """항목 텍스트 — 색인과 같은 함수(build_item_text)로 만들어 질의응답 근거와 표현이 같다."""
    wikidata = next((s["url"] for s in item.get("sources", []) if s["name"] == "Wikidata"), "")
    return Evidence(number=number, chunk_id=item["id"], kind=KIND_ITEM, source_type=ITEM_SOURCE,
                    title=item["name"], section="", url=wikidata, text=build_item_text(item, ref_year))


def computed_evidence(number: int, title: str, lines: list[str], chunk_id: str, url: str = "") -> Evidence:
    """코드가 카탈로그 데이터로 계산한 표 (별 거리표 · 하늘 위치표). 출처 종류에 계산값임을 밝힌다."""
    return Evidence(number=number, chunk_id=chunk_id, kind=KIND_ITEM, source_type=COMPUTED_SOURCE,
                    title=title, section="", url=url, text=f"[{title}]\n" + "\n".join(lines))


def doc_excerpt_evidence(number: int, doc, chars: int = 2000) -> Evidence:
    """수집 캐시의 위키 문서 앞부분 (항목 자체 문서 등)."""
    return Evidence(number=number, chunk_id=f"doc:{doc.doc_id}", kind=KIND_DOC, source_type=doc.source_type,
                    title=doc.title, section="", url=doc.url, text=f"[{doc.title}]\n{doc.text[:chars]}")
