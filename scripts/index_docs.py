"""외부 문서 색인 (F2005 · F2016) — 수집한 문서를 청킹해 cosmos_docs에 넣는다.

서비스에서는 질문이 들어온 항목만 그때 색인한다. 이 CLI는 확인 · 사전 색인 · 재구축용이다.

    python -m scripts.index_docs --item "보이저 1호"            # 이미 수집한 문서를 청킹 · 색인
    python -m scripts.index_docs --item "보이저 1호" --dry-run  # 임베딩 없이 청크 수 · 글자 수만 확인
    python -m scripts.index_docs --demo                         # 시연용 대표 항목의 자체 문서를 수집 · 색인 (LLM 없음)
    python -m scripts.index_docs --reindex                      # 이미 색인된 항목을 현재 청크 설정으로 다시 맞춤
    python -m scripts.index_docs --rebuild                      # 임베딩 모델 변경 등 — 임시 컬렉션에서 전체 재구축 후 교체
    python -m scripts.index_docs --stats                        # 컬렉션 현황

--rebuild는 기존 컬렉션을 현재 모델로 열지 않고 색인된 항목 목록만 읽는다.
재구축 · 검증이 끝나야 교체하므로, 실패해도 기존 문서 색인은 그대로 남는다. cosmos_items는 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import sys

from vasthorizon.collect.collector import Collector
from vasthorizon.config import get_settings
from vasthorizon.data.catalog import load_items
from vasthorizon.data.domain import DEMO_ITEMS
from vasthorizon.llm import MissingApiKeyError
from vasthorizon.store import chroma
from vasthorizon.store.chunking import chunk_document
from vasthorizon.store.doc_index import DocIndex, DocIndexError, indexed_item_ids, rebuild_docs


def find_item(items: list[dict], name: str) -> dict | None:
    exact = [it for it in items if it["name"] == name]
    return exact[0] if exact else next((it for it in items if name in it["name"]), None)


def print_report(item: dict, report) -> None:
    print(f"  {item['name']}: 문서 {report.docs}건 → 청크 {report.chunks}개 {report.by_source} · "
          f"재임베딩 {report.embedded} · 메타데이터 갱신 {report.meta_updated} · "
          f"변경 없음 {report.unchanged} · 삭제 {report.deleted}")
    if report.invalid:
        print(f"    [WARN] 본문이 없는 문서 {report.invalid} — 기존 청크를 보존했습니다")
    if report.missing:
        print(f"    [WARN] 본문 캐시가 없는 문서 {report.missing} — 기존 청크를 보존했습니다")


def dry_run(item: dict, collector: Collector) -> int:
    linked = collector.linked(item["id"])
    cfg = get_settings().chunking
    total_chunks = total_chars = 0
    for doc in linked.docs:
        chunks = chunk_document(doc, cfg.chunk_size, cfg.chunk_overlap)
        chars = sum(len(c.text) for c in chunks)
        total_chunks, total_chars = total_chunks + len(chunks), total_chars + chars
        print(f"  [{doc.source_type}] {doc.title}: 청크 {len(chunks)}개 · {chars:,}자")
    print(f"청크 설정 {cfg.chunk_size}/{cfg.chunk_overlap} → 청크 {total_chunks}개 · 임베딩 대상 {total_chars:,}자")
    if linked.missing:
        print(f"[WARN] 본문 캐시가 없는 문서 {linked.missing}")
    return 0


def run_rebuild(items_by_id: dict[str, dict], collector: Collector, embedding=None, db=None) -> int:
    settings = get_settings()
    name = settings.collections.docs
    ids = indexed_item_ids(name, db)                       # 현재 모델로 열지 않고 읽는다
    if not ids:
        print(f"컬렉션 {name}에 색인된 항목이 없습니다 — --item · --demo 로 색인하세요.")
        return 0
    try:
        embedding = embedding or chroma.default_embedding()
    except MissingApiKeyError as e:
        print(f"[FAIL] {e} — 기존 문서 색인을 그대로 둡니다.")
        return 1
    targets = []
    for item_id in ids:
        if item_id not in items_by_id:
            print(f"  [WARN] 카탈로그에 없는 항목 {item_id} — 재구축에서 뺍니다")
            continue
        linked = collector.linked(item_id)
        targets.append((items_by_id[item_id], linked.docs, linked.links, linked.missing))
    try:
        reports = rebuild_docs(targets, name, embedding, settings.chunking.chunk_size,
                               settings.chunking.chunk_overlap, db)
    except Exception as e:  # 검증 실패 · 임베딩 장애 — 기존 컬렉션은 보존된다
        print(f"[FAIL] 재구축 실패 — 기존 문서 색인을 그대로 둡니다: {type(e).__name__}: {e}")
        return 1
    print(f"컬렉션: {name} (재구축 후 교체) · 청크 설정 {settings.chunking.chunk_size}/{settings.chunking.chunk_overlap}")
    for (item, *_), report in zip(targets, reports):
        print_report(item, report)
    return 0


def main(argv: list[str] | None = None, embedding=None, db=None, collector=None) -> int:
    """embedding · db · collector는 테스트에서 가짜 임베딩 · 격리된 Chroma · 문서 캐시를 넣기 위한 인자다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--item", help="항목 이름 (일부만 써도 된다)")
    parser.add_argument("--dry-run", action="store_true", help="임베딩 없이 청크 수만 확인한다")
    parser.add_argument("--demo", action="store_true", help="시연용 대표 항목의 자체 문서를 수집 · 색인한다")
    parser.add_argument("--reindex", action="store_true", help="이미 색인된 항목을 현재 청크 설정으로 다시 맞춘다")
    parser.add_argument("--rebuild", action="store_true", help="임시 컬렉션에서 전체 재구축 후 교체한다")
    parser.add_argument("--stats", action="store_true", help="컬렉션 현황을 출력한다")
    args = parser.parse_args(argv)

    items = load_items()
    by_id = {it["id"]: it for it in items}
    collector = collector or Collector()

    if args.item and args.dry_run:
        item = find_item(items, args.item)
        return dry_run(item, collector) if item else print(f"[FAIL] 항목을 찾을 수 없습니다: {args.item}") or 1
    if args.rebuild:
        return run_rebuild(by_id, collector, embedding, db)

    name = get_settings().collections.docs
    if args.stats and chroma.collection_count(name, db) == 0:
        print(f"컬렉션 {name}이 비어 있습니다.")
        return 0
    try:
        index = DocIndex(embedding=embedding, db=db)
    except (MissingApiKeyError, chroma.EmbeddingMismatchError) as e:
        print(f"[FAIL] {e}")
        return 1

    if args.stats:
        print(f"컬렉션 {name}: {index.stats()}")
        return 0

    if args.item:
        targets = [find_item(items, args.item)]
        if targets[0] is None:
            print(f"[FAIL] 항목을 찾을 수 없습니다: {args.item}")
            return 1
    elif args.demo:
        targets = [find_item(items, n) for n in DEMO_ITEMS]
        for item in targets:
            collector.prefetch_own(item)                     # 자체 문서 확보 — LLM 호출 없음
    elif args.reindex:
        targets = [by_id[i] for i in index.indexed_items() if i in by_id]
    else:
        parser.print_help()
        return 1

    print(f"컬렉션: {name} · 청크 설정 {index.chunking.chunk_size}/{index.chunking.chunk_overlap}")
    failed = 0
    for item in targets:
        linked = collector.linked(item["id"])
        try:
            report = index.ensure(item, linked.docs, linked.links, linked.missing)
            print_report(item, report)
            failed += not report.complete
        except DocIndexError as e:
            print(f"  [WARN] {e} — python -m scripts.collect_docs 로 먼저 수집하세요.")
            failed += 1
        except Exception as e:  # 임베딩 API 장애 등 — 이미 반영된 청크는 남고, 다시 실행하면 이어서 처리
            print(f"  [FAIL] {item['name']}: {type(e).__name__}: {e}")
            failed += 1
    print(f"현황: {index.stats()}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
