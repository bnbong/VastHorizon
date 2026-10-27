"""메시에 천체 사진 받기 — NASA 'Hubble's Messier Catalog'의 대표 사진(가로 512px)과 출처 표기.

    python -m scripts.build_messier_images        # 이미 받은 사진은 건너뛴다
    python -m scripts.build_messier_images --hd   # 이어서 같은 사진의 고해상도(가로 1024px)를 web/data/messier/hd에
"""

from __future__ import annotations

import argparse

from vasthorizon.config import PROJECT_ROOT
from vasthorizon.data.messier_images import build, build_hd
from vasthorizon.http import http


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hd", action="store_true", help="고해상도 사진(긴 변 1024px)도 만든다 (지도에서 가까이 갈 때 쓴다)")
    args = parser.parse_args(argv)
    out = PROJECT_ROOT / "web" / "data" / "messier"
    credits = build(out, http().get)
    print(f"사진 {len(credits)}장 · web/data/messier/credits.json")
    if args.hd:
        done = build_hd(out, http().get)
        print(f"고해상도 사진 {len(done)}장 · {sum(done.values()) // 1024}KB · web/data/messier/hd")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
