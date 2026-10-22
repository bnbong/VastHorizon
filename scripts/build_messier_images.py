"""메시에 천체 사진 받기 — NASA 'Hubble's Messier Catalog'의 대표 사진(가로 512px)과 출처 표기.

    python -m scripts.build_messier_images      # 이미 받은 사진은 건너뛴다
"""

from __future__ import annotations

from vasthorizon.config import PROJECT_ROOT
from vasthorizon.data.messier_images import build
from vasthorizon.http import http


def main() -> int:
    credits = build(PROJECT_ROOT / "web" / "data" / "messier", http().get)
    print(f"사진 {len(credits)}장 · web/data/messier/credits.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
