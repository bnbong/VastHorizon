"""항목 메타데이터 수집 — 5개 그룹을 모아 data/items.json으로 저장한다.

    python -m scripts.collect_items              # data/raw 캐시가 있으면 재사용
    python -m scripts.collect_items --refresh    # 외부 출처에서 다시 받기
    python -m scripts.collect_items --epoch 2026-10-21   # Horizons 위치 기준일 지정

검증(최소 건수 · QID 중복 · 좌표 · 거리 · 출처)을 통과해야만 data/items.json을 교체한다.
실패하면 종료 코드 1로 끝나고 기존 카탈로그는 그대로 남는다.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from datetime import date

from vasthorizon.data import sources
from vasthorizon.data.catalog import CatalogValidationError, save_items
from vasthorizon.data.enrich import enrich_items
from vasthorizon.data.items import constellations, human_made, messier, solar_system, stars
from vasthorizon.data.items.common import GROUPS, Item


def epoch_arg(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"날짜 형식이 아닙니다 (YYYY-MM-DD): {value}") from None


def collect_all(epoch: str, refresh: bool) -> list[Item]:
    solar, bodies = solar_system.collect(epoch, refresh)
    print(f"  태양계        {len(solar):>4}건")
    human = human_made.collect(epoch, bodies, refresh)
    print(f"  인류의 발자취 {len(human):>4}건")
    star = stars.collect(refresh)
    print(f"  별            {len(star):>4}건")
    deep = messier.collect(refresh)
    print(f"  메시에 천체   {len(deep):>4}건")
    cons = constellations.collect(star, refresh)
    print(f"  별자리        {len(cons):>4}건")

    # 같은 QID가 두 그룹에 걸치면 먼저 나온 그룹을 남긴다 — 청크 ID 충돌 방지
    items: list[Item] = []
    seen: set[str] = set()
    for item in solar + human + star + deep + cons:
        if item.id in seen:
            print(f"  [중복 제외] {item.id} {item.name} ({GROUPS[item.group]})")
            continue
        seen.add(item.id)
        items.append(item)
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="캐시를 무시하고 다시 수집한다")
    parser.add_argument("--epoch", type=epoch_arg, default=date.today().isoformat(),
                        help="Horizons 위치 기준일 (YYYY-MM-DD)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print(f"Horizons 위치 기준일: {args.epoch}")
    sources.SNAPSHOTS.clear()
    try:
        items = collect_all(args.epoch, args.refresh)
    except Exception as e:  # 수집 실패 — 기존 카탈로그를 건드리지 않는다
        print(f"[FAIL] 수집 중 오류: {type(e).__name__}: {e}")
        return 1

    counts = Counter(it.group for it in items)
    meta = {
        "collected_at": date.today().isoformat(),
        "horizons_epoch": args.epoch,
        "counts": {GROUPS[g]: counts[g] for g in GROUPS},
        "total": len(items),
        "source_snapshots": dict(sorted(sources.SNAPSHOTS.items())),
        "time_policy": (
            "Horizons 위치는 horizons_epoch 기준으로 계산한다. "
            "SATCAT 운용 상태 · 고도 · 재진입은 내려받은 스냅샷 시점의 값이며 과거 기준일로 재구성하지 않는다. "
            "기준일보다 늦게 재진입한 위성은 '기준일 상태 미상'으로 표시한다."
        ),
    }
    try:
        # 보강(블랙홀 · 고리 · 탐사선 방문 · 서울 관측)은 enrich.json에 있어 다시 수집해도 사라지지 않는다
        path = save_items(enrich_items([it.to_dict() for it in items]), meta)
    except CatalogValidationError as e:
        print(f"[FAIL] 검증 실패 — 기존 카탈로그를 유지합니다.")
        for err in e.errors[:20]:
            print(f"  - {err}")
        return 1

    estimated = [k for k, v in sources.SNAPSHOTS.items() if v.get("estimated")]
    no_distance = [it.name for it in items if it.group != "constellation" and it.distance is None]
    approx = sum(1 for it in items if it.distance and it.distance.approximate)
    print(f"\n총 {len(items)}건 → {path}")
    print(f"근삿값 거리: {approx}건 · 거리 정보 없음 (별자리 제외): {len(no_distance)}건")
    if estimated:
        print(f"[WARN] 수집 시각이 추정값인 캐시 {len(estimated)}개 — --refresh로 다시 받으면 정확해집니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
