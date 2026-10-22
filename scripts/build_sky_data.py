"""하늘 데이터 만들기 — d3-celestial 별 · 성운 · 은하수를 web/data/ 의 작은 파일로.

    python -m scripts.build_sky_data             # data/raw 캐시가 있으면 재사용
    python -m scripts.build_sky_data --refresh   # 출처에서 다시 받기
"""

from __future__ import annotations

import argparse
import json

from vasthorizon.config import PROJECT_ROOT
from vasthorizon.data.sky_catalog import build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="출처에서 다시 받기")
    args = parser.parse_args(argv)
    out = PROJECT_ROOT / "web" / "data"
    meta = build(out, refresh=args.refresh)
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    for f in sorted(out.iterdir()):
        print(f"  {f.name}: {f.stat().st_size / 1024:,.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
