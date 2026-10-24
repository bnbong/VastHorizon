"""web/index.html의 실행 설정 meta에 값을 끼워 넣는다 — 저장소의 index.html은 늘 빈 값으로 둔다.

- vh-kakao-key: 카카오 JavaScript 키 (카카오톡 공유). 키를 저장소에 적지 않고 내보낼 때 넣는다
    로컬 · Docker  FastAPI가 index.html을 내보낼 때 ([share] kakao_js_key, 환경변수 KAKAO_JS_KEY 우선)
    Nginx 호스트   release.yml의 deploy-web이 rsync 전에 복사본에서 바꾼다 (GitHub variable KAKAO_JS_KEY)
    Pages          scripts/build_static.py가 환경변수 VH_KAKAO_KEY로 바꾼다
표준 라이브러리만 쓴다 (scripts/build_static.py가 의존성 없이 불러 쓴다).
"""

from __future__ import annotations

import re

KAKAO_META = re.compile(r'<meta name="vh-kakao-key" content="[^"]*">')
KAKAO_KEY = re.compile(r"[A-Za-z0-9]{1,64}")          # 카카오 JavaScript 키는 32자 16진수 — 따옴표 · 꺾쇠가 섞일 수 없게


def valid_kakao_key(key: str | None) -> bool:
    return bool(key) and KAKAO_KEY.fullmatch(key) is not None


def inject_kakao_key(html: str, key: str | None) -> str:
    """vh-kakao-key meta의 content를 key로. 키가 비었거나 모양이 틀리면 · meta가 없으면 원본 그대로."""
    key = (key or "").strip()
    if not valid_kakao_key(key):
        return html
    return KAKAO_META.sub(f'<meta name="vh-kakao-key" content="{key}">', html, count=1)
