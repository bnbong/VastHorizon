"""외부 문서 수집 — 확인 · 사전 수집용 CLI.

    # 질문 하나로 전체 흐름 확인 — 검색어 · 후보별 색인/제외 · 연결 문서를 출력 (LLM 2회 이하)
    python -m scripts.collect_docs --item "보이저 1호" --question "보이저 1호는 태양계를 벗어났나?"

    # 모든 항목의 자체 문서(위키 문서 · NASA 미션 설명)를 미리 받아 둔다 (LLM 호출 없음)
    python -m scripts.collect_docs --own
    python -m scripts.collect_docs --own --group human_made --limit 10

    # 기존 캐시 점검 · 복구 — 예전 형식 수집 기록 변환, 빈 본문 · 확인 안 된 빈 검색 결과 삭제
    python -m scripts.collect_docs --repair-cache
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from vasthorizon.collect.cache import CollectCache
from vasthorizon.collect.collector import Collector
from vasthorizon.data.catalog import load_items
from vasthorizon.llm import MissingApiKeyError


def find_item(items: list[dict], name: str) -> dict | None:
    exact = [it for it in items if it["name"] == name]
    if exact:
        return exact[0]
    partial = [it for it in items if name in it["name"]]
    return partial[0] if partial else None


def run_question(items: list[dict], name: str, question: str) -> int:
    item = find_item(items, name)
    if not item:
        print(f"[FAIL] 항목을 찾을 수 없습니다: {name}")
        return 1
    try:
        result = Collector().collect(item, question, progress=lambda msg: print(f"  … {msg}"))
    except MissingApiKeyError as e:
        print(f"[FAIL] {e}")
        return 1

    print(f"\n항목: {item['name']} ({item['id']})\n질문: {question}")
    print(f"검색어: {result.queries}{' (같은 질문 — 재사용)' if result.question_cached else ''}")
    print(f"  검색 API 호출: {result.searched_queries}")
    print(f"  검색 캐시 사용: {result.cached_queries}")
    print("\n후보 판정")
    for d in result.decisions:
        print(f"  [{d.decision}] {d.title} — {d.reason} (검색어: {d.query})")
    print(f"\n이 항목에 연결된 문서 {len(result.docs)}건 (새로 {len(result.new_docs)}건)")
    for doc in result.docs:
        print(f"  - [{doc.source_type}] {doc.title} · {len(doc.text):,}자 · {doc.url}")
    print(f"\nLLM 호출 {result.llm_calls}회 · {'완료' if result.complete else '일부 실패 — 다시 실행하면 이어서 처리'}")
    for w in result.warnings:
        print(f"[WARN] {w}")
    return 0


def run_repair() -> int:
    report = CollectCache().repair()
    print("수집 캐시 점검 · 복구")
    print(f"  예전 형식 수집 기록 변환     {report['migrated_manifests']}건")
    print(f"  빈 본문 문서 캐시 삭제       {report['removed_empty_docs']}건")
    print(f"  확인 안 된 빈 검색 결과 삭제 {report['removed_unverified_searches']}건")
    print(f"  본문 캐시가 없는 연결 문서   {report['missing_linked_docs']}건 (연결 유지 — 다음 수집 · 색인 때 다시 받음)")
    return 0


def run_own(items: list[dict], group: str | None, limit: int | None) -> int:
    targets = [it for it in items if not group or it["group"] == group][:limit]
    collector = Collector()
    sources, missing = Counter(), []
    for i, item in enumerate(targets, 1):
        docs, warnings = collector.prefetch_own(item)
        sources.update(d.source_type for d in docs)
        if not any(d.source_type == "위키백과" for d in docs):
            missing.append(item["name"])
        if i % 25 == 0 or i == len(targets):
            print(f"  {i}/{len(targets)} 항목 처리")
    print(f"\n항목 {len(targets)}건의 자체 문서: {dict(sources)}")
    if missing:
        print(f"[WARN] 위키 문서를 받지 못한 항목 {len(missing)}건: {missing[:10]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--item", help="항목 이름 (일부만 써도 된다)")
    parser.add_argument("--question", help="질문")
    parser.add_argument("--own", action="store_true", help="모든 항목의 자체 문서를 미리 받는다 (LLM 없음)")
    parser.add_argument("--group", help="--own 대상 그룹 (solar_system · human_made · star · messier · milky_way · constellation)")
    parser.add_argument("--limit", type=int, help="--own 대상 수 제한")
    parser.add_argument("--repair-cache", action="store_true",
                        help="예전 형식 기록 · 빈 본문 · 확인 안 된 빈 검색 결과를 정리한다")
    args = parser.parse_args(argv)

    if args.repair_cache:
        return run_repair()
    items = load_items()
    if args.own:
        return run_own(items, args.group, args.limit)
    if args.item and args.question:
        return run_question(items, args.item, args.question)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
