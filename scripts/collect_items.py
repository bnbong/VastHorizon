"""항목 메타데이터 수집 — 6개 그룹을 모아 data/items.json으로 저장한다.

    python -m scripts.collect_items              # data/raw 캐시가 있으면 재사용
    python -m scripts.collect_items --refresh    # 외부 출처에서 다시 받기
    python -m scripts.collect_items --epoch 2026-10-21   # Horizons 위치 기준일 지정
    python -m scripts.collect_items --only milky_way     # 그 그룹만 새로 모아 기존 카탈로그에 바꿔 끼운다

검증(최소 건수 · QID 중복 · 좌표 · 거리 · 출처)을 통과해야만 data/items.json을 교체한다.
실패하면 종료 코드 1로 끝나고 기존 카탈로그는 그대로 남는다.

--only GROUP — 전체 수집은 모든 출처를 새로 받고 기준일도 바뀌어 카탈로그 전체가 흔들린다. 그룹 하나만 넣을 때 쓴다.
  - 기존 항목 중 다른 그룹은 그대로 두고, 그 그룹 항목만 새로 모은 것으로 바꾼다 (QID가 겹치면 기존 항목을 남긴다)
  - meta의 collected_at · horizons_epoch · time_policy는 그대로, counts · total은 다시 센다
  - source_snapshots는 이번에 쓴 원본을 합치고, partial_collections에 {그룹: 수집일}을 남긴다
  - 위치 기준일은 기존 카탈로그의 horizons_epoch를 쓴다 (다른 --epoch를 주면 실패)
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from datetime import date

from vasthorizon.data import sources
from vasthorizon.data.catalog import CatalogValidationError, load_catalog, save_items
from vasthorizon.data.enrich import enrich_items
from vasthorizon.data.items import constellations, human_made, messier, milky_way, solar_system, stars
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
    galaxy = milky_way.collect(refresh)
    print(f"  우리 은하     {len(galaxy):>4}건")
    cons = constellations.collect(star, refresh)
    print(f"  별자리        {len(cons):>4}건")

    # 같은 QID가 두 그룹에 걸치면 먼저 나온 그룹을 남긴다 — 청크 ID 충돌 방지
    items: list[Item] = []
    seen: set[str] = set()
    for item in solar + human + star + deep + galaxy + cons:
        if item.id in seen:
            print(f"  [중복 제외] {item.id} {item.name} ({GROUPS[item.group]})")
            continue
        seen.add(item.id)
        items.append(item)
    return items


def collect_group(group: str, epoch: str, refresh: bool) -> list[Item]:
    """그룹 하나만 모은다 (--only). 인류의 발자취는 태양계 위치, 별자리는 별 목록이 함께 필요하다."""
    if group == "solar_system":
        return solar_system.collect(epoch, refresh)[0]
    if group == "human_made":
        return human_made.collect(epoch, solar_system.collect(epoch, refresh)[1], refresh)
    if group == "star":
        return stars.collect(refresh)
    if group == "messier":
        return messier.collect(refresh)
    if group == "milky_way":
        return milky_way.collect(refresh)
    if group == "constellation":
        return constellations.collect(stars.collect(refresh), refresh)
    raise ValueError(f"알 수 없는 그룹: {group}")


def replace_group(existing: list[dict], group: str, collected: list[dict]) -> list[dict]:
    """기존 항목에서 그 그룹만 새 항목으로 바꾼다. QID가 다른 그룹 항목과 겹치면 기존 쪽을 남긴다. 그룹 순서(GROUPS)를 따른다."""
    kept = [it for it in existing if it["group"] != group]
    seen = {it["id"] for it in kept}
    added = []
    for it in collected:
        if it["id"] in seen:
            print(f"  [중복 제외] {it['id']} {it['name']} — 기존 항목을 남깁니다")
            continue
        seen.add(it["id"])
        added.append(it)
    order = {g: i for i, g in enumerate(GROUPS)}
    return sorted(kept + added, key=lambda it: order.get(it["group"], len(order)))   # 안정 정렬 — 그룹 안 순서는 그대로


def run_only(group: str, epoch: str | None, refresh: bool) -> int:
    try:
        catalog = load_catalog()
    except (FileNotFoundError, ValueError) as e:
        print(f"[FAIL] 기존 카탈로그를 읽지 못했습니다: {e}")
        return 1
    old_meta = {k: v for k, v in catalog.get("meta", {}).items() if k != "licenses"}
    base_epoch = old_meta.get("horizons_epoch") or date.today().isoformat()
    if epoch and epoch != base_epoch:
        print(f"[FAIL] --only는 기존 카탈로그의 위치 기준일({base_epoch})을 씁니다. --epoch {epoch}는 전체 수집에서만 쓸 수 있습니다.")
        return 1

    print(f"그룹만 수집: {group} ({GROUPS[group]}) · Horizons 위치 기준일: {base_epoch}")
    sources.SNAPSHOTS.clear()
    try:
        collected = collect_group(group, base_epoch, refresh)
    except Exception as e:  # 수집 실패 — 기존 카탈로그를 건드리지 않는다
        print(f"[FAIL] 수집 중 오류: {type(e).__name__}: {e}")
        return 1
    print(f"  {GROUPS[group]} {len(collected)}건")

    items = replace_group(catalog["items"], group, [it.to_dict() for it in collected])
    counts = Counter(it["group"] for it in items)
    meta = {
        **old_meta,
        "counts": {GROUPS[g]: counts[g] for g in GROUPS},
        "total": len(items),
        "source_snapshots": dict(sorted({**old_meta.get("source_snapshots", {}), **sources.SNAPSHOTS}.items())),
        "partial_collections": {**old_meta.get("partial_collections", {}), group: date.today().isoformat()},
    }
    try:
        path = save_items(enrich_items(items), meta)
    except CatalogValidationError as e:
        print(f"[FAIL] 검증 실패 — 기존 카탈로그를 유지합니다.")
        for err in e.errors[:20]:
            print(f"  - {err}")
        return 1
    print(f"\n총 {len(items)}건 → {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="캐시를 무시하고 다시 수집한다")
    parser.add_argument("--epoch", type=epoch_arg, default=None,
                        help="Horizons 위치 기준일 (YYYY-MM-DD, 기본: 오늘 · --only면 기존 카탈로그의 기준일)")
    parser.add_argument("--only", choices=list(GROUPS), help="이 그룹만 새로 모아 기존 카탈로그에 바꿔 끼운다")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.only:
        return run_only(args.only, args.epoch, args.refresh)
    args.epoch = args.epoch or date.today().isoformat()

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
