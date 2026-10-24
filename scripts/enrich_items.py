"""카탈로그 보강 반영 — vasthorizon/data/enrich.json(블랙홀 · 고리 · 위성 수 · 탐사선 방문)과
서울 관측 계산을 data/items.json에 합쳐 저장한다.

    python -m scripts.enrich_items            # 바뀐 항목이 있으면 저장
    python -m scripts.enrich_items --check    # 저장하지 않고 반영 여부만 확인 (반영 안 됐으면 종료 코드 1)

scripts.collect_items도 저장 전에 같은 보강을 거치므로, 다시 수집해도 보강이 사라지지 않는다.
enrich.json을 고친 뒤에는 이 스크립트 → python -m scripts.index_items 순서로 실행한다.
"""

from __future__ import annotations

import argparse
import sys

from vasthorizon.data.catalog import CatalogValidationError, load_catalog, save_items
from vasthorizon.data.enrich import enrich_items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="저장하지 않고 반영 여부만 확인한다")
    args = parser.parse_args(argv)
    try:
        catalog = load_catalog()
    except (FileNotFoundError, ValueError) as e:
        print(f"[FAIL] 카탈로그를 읽을 수 없습니다: {e}")
        return 1
    items = catalog.get("items", [])
    enriched = enrich_items(items)
    changed = sum(a != b for a, b in zip(enriched, items))
    if not changed:
        print(f"[ OK ] 보강이 이미 반영돼 있습니다 ({len(items)}건)")
        return 0
    if args.check:
        print(f"[FAIL] 보강이 반영되지 않은 항목 {changed}건")
        return 1
    try:
        path = save_items(enriched, {k: v for k, v in catalog["meta"].items() if k != "licenses"})
    except CatalogValidationError as e:
        print(f"[FAIL] 검증 실패 — 기존 카탈로그를 유지합니다: {e}")
        return 1
    print(f"[ OK ] 보강 반영 {changed}건 → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
