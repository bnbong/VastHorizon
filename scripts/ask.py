"""질문 하나를 끝까지 실행해 답변과 근거를 확인하는 CLI. (F2006 · F2007 · F2008 · F2014 검증용)

    python -m scripts.ask --item "보이저 1호" --question "보이저 1호는 태양계를 벗어났나?"
    python -m scripts.ask --item "보이저 1호" --question "…" --no-collect   # 수집 없이 기존 색인만
    python -m scripts.ask --item "보이저 1호" --question "…" --search-type mmr
    python -m scripts.ask --item "보이저 1호" --question "…" --compare      # 유사도 vs MMR 근거 비교 (답변 생성 없음)
    python -m scripts.ask --graph                                           # LangGraph 구조 출력 (Mermaid)
"""

from __future__ import annotations

import argparse
import sys

from vasthorizon.config import get_settings
from vasthorizon.data.catalog import load_items
from vasthorizon.llm import MissingApiKeyError
from vasthorizon.rag.graph import build_graph
from vasthorizon.rag.pipeline import ask
from vasthorizon.rag.retrieval import IndexMissingError, retrieve_evidence


def find_item(items: list[dict], name: str) -> dict | None:
    exact = [it for it in items if it["name"] == name]
    return exact[0] if exact else next((it for it in items if name in it["name"]), None)


def print_evidence_list(title: str, evidences) -> None:
    print(f"\n{title}")
    for ev in evidences:
        score = f" ({ev.score:.2f})" if ev.score is not None else ""
        print(f"  {ev.label()}{score}")


def compare(item: dict, question: str) -> None:
    cfg = get_settings().retrieval
    print(f"Top-k {cfg.top_k_docs} · MMR fetch_k {cfg.mmr_fetch_k} · lambda {cfg.mmr_lambda}")
    sim = retrieve_evidence(item, question, search_type="similarity").evidences
    mmr = retrieve_evidence(item, question, search_type="mmr").evidences
    print_evidence_list("유사도 검색", sim)
    print_evidence_list("MMR 검색", mmr)
    sim_ids, mmr_ids = {e.chunk_id for e in sim}, {e.chunk_id for e in mmr}
    print(f"\n겹치는 근거 {len(sim_ids & mmr_ids)}개 · MMR에만 {len(mmr_ids - sim_ids)}개")
    print(f"서로 다른 문서 수 — 유사도 {len({e.title for e in sim})}개, MMR {len({e.title for e in mmr})}개")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--item")
    parser.add_argument("--question")
    parser.add_argument("--no-collect", action="store_true", help="문서 수집 · 색인 없이 기존 색인만 쓴다")
    parser.add_argument("--search-type", choices=["similarity", "mmr"], help="설정값 대신 쓸 검색 방식")
    parser.add_argument("--compare", action="store_true", help="유사도 · MMR 근거 목록을 비교한다")
    parser.add_argument("--graph", action="store_true", help="LangGraph 구조를 Mermaid로 출력한다")
    args = parser.parse_args(argv)

    if args.graph:
        print(build_graph().get_graph().draw_mermaid())
        return 0
    if not (args.item and args.question):
        parser.print_help()
        return 1
    item = find_item(load_items(), args.item)
    if not item:
        print(f"[FAIL] 항목을 찾을 수 없습니다: {args.item}")
        return 1

    try:
        if args.compare:
            compare(item, args.question)
            return 0
        result = ask(item, args.question, progress=lambda m: print(f"  … {m}"),
                     collect=not args.no_collect, search_type=args.search_type)
    except (MissingApiKeyError, IndexMissingError) as e:
        print(f"[FAIL] {e}")
        return 1

    print(f"\n{item['name']} — {args.question}\n")
    print(result.answer)
    if result.has_citations:
        print_evidence_list(f"답변에 사용한 근거 {len(result.cited)}건", result.cited)
        for ev in result.cited:
            print(f"    원문: {ev.url}")
    else:
        print("\n[안내] 답변에 인용된 근거가 없습니다.")
    status = {"cited": "인용 번호 검증 통과", "not_found": "문서에서 확인되지 않음", "rejected": "인용 규칙 위반으로 차단"}
    print(f"\n답변 상태: {status[result.status]} (시도 {result.attempts}회)"
          + (f" · 위반: {result.issues}" if result.issues else ""))
    print(f"검색된 근거 {len(result.evidences)}건 중 {len(result.cited)}건 인용 · 단계 "
          + ", ".join(f"{k} {s.status} {s.seconds:.1f}s" for k, s in result.stages.items()))
    for w in result.warnings:
        print(f"[WARN] {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
