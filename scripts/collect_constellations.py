"""별자리 모양 데이터 수집 — data/constellations.json (별자리 펼치기 · 3D 시각화용).

    python -m scripts.collect_constellations            # data/raw 캐시가 있으면 재사용
    python -m scripts.collect_constellations --refresh

카탈로그(data/items.json)의 별자리 · 별 항목을 기준으로 만든다. 먼저 collect_items를 실행해야 한다.
"""

from __future__ import annotations

import argparse
import json
import sys

from vasthorizon.config import get_settings
from vasthorizon.data.atomic import atomic_write_text
from vasthorizon.data.catalog import load_items
from vasthorizon.data.constellation_figures import (
    LICENSES, collect_figures, collect_sky_stars, figure_stats, sky_stars_path,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)

    items = load_items()
    data = collect_figures([i for i in items if i["group"] == "star"],
                           [i for i in items if i["group"] == "constellation"], args.refresh)
    figures = data["figures"]
    if len(figures) < 80:
        print(f"[FAIL] 별자리 모양이 {len(figures)}개뿐입니다 — 기존 파일을 유지합니다.")
        return 1
    path = get_settings().paths.data_dir / "constellations.json"
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1))
    sky = collect_sky_stars(args.refresh)
    atomic_write_text(sky_stars_path(), json.dumps(
        {"fields": ["ra_deg", "dec_deg", "mag", "bv"], "license": LICENSES["d3-celestial"], "stars": sky},
        ensure_ascii=False, separators=(",", ":")))
    print(f"맨눈 별 {len(sky)}개 → {sky_stars_path()}")

    stars = [s for f in figures.values() for s in f["stars"].values()]
    known = sum(1 for s in stars if s["distance_ly"])
    print(f"별자리 {len(figures)}개 · 선을 이루는 별 {len(stars)}개 · 거리 확인 {known}개 · "
          f"좌표 미매칭 꼭짓점 {data['unmatched_vertices']}개 → {path}")
    orion = next(f for f in figures.values() if f["name"] == "오리온자리")
    stats = figure_stats(orion)
    print(f"오리온자리: 별 {stats['stars']}개, 가장 가까운 {stats['nearest']['name']} {stats['nearest']['distance_ly']}광년, "
          f"가장 먼 {stats['farthest']['name']} {stats['farthest']['distance_ly']}광년")
    return 0


if __name__ == "__main__":
    sys.exit(main())
