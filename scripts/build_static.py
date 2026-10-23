"""화면만 따로 배포할 때(Cloudflare Pages 등) — web/를 dist/로 복사하고 API 서버 주소를 넣는다.

    python scripts/build_static.py --api https://api.example.com    # dist/ 생성
    VH_API_BASE=https://api.example.com python scripts/build_static.py

Cloudflare Pages 설정: 빌드 명령 `python scripts/build_static.py`, 출력 폴더 `dist`, 환경변수 VH_API_BASE.
표준 라이브러리만 쓴다 (Pages 빌드 환경에서 의존성 설치 없이 실행).
API 서버에는 이 화면 주소를 VH_CORS_ORIGINS로 허용해 둔다.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
META = re.compile(r'<meta name="vh-api-base" content="[^"]*">')


def build(api: str, web: Path = ROOT / "web", out: Path = ROOT / "dist") -> Path:
    if not re.fullmatch(r"https?://[^\s\"<>]+", api):
        raise ValueError(f"API 주소는 http(s)://로 시작해야 합니다: {api!r}")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(web, out, ignore=shutil.ignore_patterns("_*.html", "__pycache__"))
    index = out / "index.html"
    html = index.read_text(encoding="utf-8")
    if not META.search(html):
        raise RuntimeError("index.html에 vh-api-base meta가 없습니다.")
    index.write_text(META.sub(f'<meta name="vh-api-base" content="{api.rstrip("/")}">', html, count=1), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=os.environ.get("VH_API_BASE", ""), help="API 서버 주소 (기본: 환경변수 VH_API_BASE)")
    parser.add_argument("--out", default=str(ROOT / "dist"))
    args = parser.parse_args(argv)
    if not args.api:
        print("API 서버 주소가 필요합니다: --api https://... 또는 환경변수 VH_API_BASE", file=sys.stderr)
        return 2
    out = build(args.api, out=Path(args.out))
    print(f"정적 화면 {out} · API {args.api.rstrip('/')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
