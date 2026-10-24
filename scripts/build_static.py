"""화면만 따로 배포할 때(Cloudflare Pages 등) — web/를 dist/로 복사하고 API 서버 주소를 넣는다.

    python scripts/build_static.py --api https://api.example.com    # dist/ 생성
    VH_API_BASE=https://api.example.com python scripts/build_static.py
    VH_API_BASE=... VH_KAKAO_KEY=<카카오 JavaScript 키> python scripts/build_static.py   # 카카오톡 공유 켜기 (선택)

Cloudflare Pages 설정: 빌드 명령 `python scripts/build_static.py`, 출력 폴더 `dist`, 환경변수 VH_API_BASE (선택: VH_KAKAO_KEY).
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

if str(ROOT) not in sys.path:                    # python scripts/build_static.py로 실행해도 vasthorizon.webmeta(표준 라이브러리만)를 쓰게
    sys.path.insert(0, str(ROOT))
from vasthorizon.webmeta import inject_kakao_key, valid_kakao_key  # noqa: E402


def build(api: str, web: Path = ROOT / "web", out: Path = ROOT / "dist", kakao_key: str = "") -> Path:
    if not re.fullmatch(r"https?://[^\s\"<>]+", api):
        raise ValueError(f"API 주소는 http(s)://로 시작해야 합니다: {api!r}")
    kakao_key = (kakao_key or "").strip()
    if kakao_key and not valid_kakao_key(kakao_key):
        raise ValueError("카카오 JavaScript 키는 영문 · 숫자로만 되어 있어야 합니다 (VH_KAKAO_KEY).")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(web, out, ignore=shutil.ignore_patterns("_*.html", "__pycache__"))
    index = out / "index.html"
    html = index.read_text(encoding="utf-8")
    if not META.search(html):
        raise RuntimeError("index.html에 vh-api-base meta가 없습니다.")
    html = META.sub(f'<meta name="vh-api-base" content="{api.rstrip("/")}">', html, count=1)
    index.write_text(inject_kakao_key(html, kakao_key), encoding="utf-8")   # 키가 없으면 meta는 빈 값 그대로 (카카오톡 버튼을 숨긴다)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=os.environ.get("VH_API_BASE", ""), help="API 서버 주소 (기본: 환경변수 VH_API_BASE)")
    parser.add_argument("--out", default=str(ROOT / "dist"))
    parser.add_argument("--kakao-key", default=os.environ.get("VH_KAKAO_KEY", ""), help="카카오 JavaScript 키 (기본: 환경변수 VH_KAKAO_KEY, 없으면 카카오톡 공유를 끈다)")
    args = parser.parse_args(argv)
    if not args.api:
        print("API 서버 주소가 필요합니다: --api https://... 또는 환경변수 VH_API_BASE", file=sys.stderr)
        return 2
    out = build(args.api, out=Path(args.out), kakao_key=args.kakao_key)
    print(f"정적 화면 {out} · API {args.api.rstrip('/')} · 카카오톡 공유 {'켬' if args.kakao_key.strip() else '끔'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
