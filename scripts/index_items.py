"""항목 메타데이터 색인 — data/items.json → cosmos_items 컬렉션.

    python -m scripts.index_items                    # 바뀐 항목만 반영 (텍스트 → 재임베딩, 메타데이터 → 갱신)
    python -m scripts.index_items --dry-run          # 임베딩 없이 색인 텍스트만 확인 (토큰 사용 없음)
    python -m scripts.index_items --show 플레이아데스  # 특정 항목의 색인 텍스트 출력
    python -m scripts.index_items --rebuild          # 임시 컬렉션에서 전체 재구축 후 교체

컬렉션을 건드리기 전에 카탈로그 검증과 API 키 확인을 먼저 끝낸다.
--rebuild는 실패해도 기존 컬렉션이 그대로 남는다 (vasthorizon/store/chroma.py 교체 정책 참고).
끝까지 성공하고 건수가 맞을 때만 완성 표식을 남긴다 (같은 파일의 '완성 표식'). 이때 색인한 카탈로그 내용의 해시(catalog_hash)도 남긴다.
"""

from __future__ import annotations

import argparse
import sys

from vasthorizon.config import get_settings
from vasthorizon.data.catalog import load_catalog, validate_items
from vasthorizon.data.enrich import enrich_items
from vasthorizon.llm import MissingApiKeyError
from vasthorizon.store import chroma
from vasthorizon.store.item_index import IndexingError, catalog_hash, prepare, rebuild_items, sync_items


def main(argv: list[str] | None = None, embedding=None, db=None) -> int:
    """embedding · db는 테스트에서 가짜 임베딩 · 격리된 Chroma를 넣기 위한 인자다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="임베딩 없이 텍스트만 만든다")
    parser.add_argument("--show", metavar="이름", help="이름에 이 문자열이 들어간 항목의 색인 텍스트를 출력한다")
    parser.add_argument("--rebuild", action="store_true", help="임시 컬렉션에서 전체 재구축 후 교체한다")
    args = parser.parse_args(argv)

    # 1. 카탈로그 — 컬렉션을 건드리기 전에 검증한다
    try:
        catalog = load_catalog()
    except (FileNotFoundError, ValueError) as e:
        print(f"[FAIL] 카탈로그를 읽을 수 없습니다: {e}")
        return 1
    items = catalog.get("items", [])
    errors = validate_items(items)
    if errors:
        print("[FAIL] 카탈로그 검증 실패 — 색인을 변경하지 않습니다.")
        for err in errors[:10]:
            print(f"  - {err}")
        return 1
    # 보강(vasthorizon/data/enrich.json · 서울 관측 계산)을 합쳐 색인한다. 카탈로그 파일은 여기서 고치지 않는다 —
    # 화면(항목 상세)도 같은 속성을 보도록 파일에 반영하는 일은 python -m scripts.enrich_items 가 한다
    enriched = enrich_items(items)
    if enriched != items:
        changed = sum(a != b for a, b in zip(enriched, items))
        print(f"[WARN] data/items.json에 보강이 반영되지 않은 항목 {changed}건 — 색인에는 합쳐 넣습니다. "
              "python -m scripts.enrich_items 로 파일에도 반영하세요.")
    items = enriched
    ref_year = int(catalog["meta"]["collected_at"][:4])
    name = get_settings().collections.items

    if args.show or args.dry_run:
        prepared = prepare(items, ref_year)
        shown = [p for p in prepared if args.show in p[2]["name"]] if args.show else prepared[:3]
        for cid, text, meta in shown:
            print(f"── {cid} ({meta['group_ko']}) ──\n{text}\n")
        lengths = sorted(len(t) for _, t, _ in prepared)
        print(f"항목 {len(prepared)}건 · 텍스트 길이 중앙값 {lengths[len(lengths) // 2]}자 · 최대 {lengths[-1]}자")
        return 0

    # 2. 임베딩 설정 · API 키 — 역시 컬렉션 변경 전에 확인한다
    try:
        embedding = embedding or chroma.default_embedding()
    except MissingApiKeyError as e:
        print(f"[FAIL] {e} — 색인을 변경하지 않습니다.")
        return 1
    db = chroma.db_for(name, db)

    # 3. 색인
    try:
        if args.rebuild:
            report = rebuild_items(items, name, embedding, ref_year, db)
        else:
            chroma.mark_incomplete(name, db)            # 도중에 끝나면 표식 없는 색인으로 남는다
            report = sync_items(items, chroma.open_collection(name, embedding, db), embedding, ref_year)
    except (chroma.EmbeddingMismatchError, IndexingError) as e:
        print(f"[FAIL] {e}")
        return 1
    except Exception as e:  # 임베딩 API 장애 등 — 재구축이면 기존 컬렉션은 보존된다
        print(f"[FAIL] 색인 중 오류: {type(e).__name__}: {e}")
        return 1

    print(f"컬렉션: {name}{' (재구축 후 교체)' if args.rebuild else ''}")
    print(f"  로드한 항목       {report.loaded:>4}건")
    print(f"  재임베딩          {len(report.embedded):>4}건 (텍스트 변경)")
    print(f"  메타데이터 갱신   {len(report.meta_updated):>4}건 (임베딩 없음)")
    print(f"  변경 없음         {report.unchanged:>4}건")
    print(f"  삭제              {len(report.deleted):>4}건")
    print(f"  색인된 청크       {report.indexed:>4}건")
    count = chroma.collection_count(name, db)
    if count != report.loaded:
        print(f"[FAIL] 로드한 항목 {report.loaded}건과 색인된 청크 {count}건이 다릅니다.")
        return 1
    chroma.mark_complete(name, db, catalog_hash=catalog_hash(items, ref_year))   # deploy_init이 카탈로그 변경을 알아챈다
    print(f"[ OK ] 로드 {report.loaded}건 = 색인 {count}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
