"""한국어 위키백과 검색 · 본문 수집.

- 검색: generator=search 한 번으로 제목 · 요약(앞 2문장) · 길이 · 동음이의 여부를 함께 받는다
- 본문: TextExtracts 평문. '각주' · '외부 링크' 같은 꼬리 절은 지운다
- 예절(NF2006): 공용 HTTP 클라이언트(User-Agent 연락처 · 호출 간격 · 재시도), maxlag 준수

오류 처리
- 응답 본문의 error는 SourceError로 올린다. 정상적인 '검색 결과 0건' · '문서 없음'과 구분한다.
- 일시적 오류(maxlag · ratelimited · readonly)는 Retry-After(없으면 5초)만큼 기다려 2번까지 다시 시도한다.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

from vasthorizon.data.docs import Candidate, Document, SourceError
from vasthorizon.http import http

TRANSIENT_ERRORS = {"maxlag", "ratelimited", "readonly"}
MAX_API_RETRIES = 2
_sleep = time.sleep          # 테스트에서 바꿔 끼운다

API = "https://ko.wikipedia.org/w/api.php"
SOURCE_TYPE = "위키백과"
LICENSE = "CC BY-SA 4.0 — 한국어 위키백과 기여자"

# 이 절부터 문서 끝까지는 근거로 쓰지 않는다
TAIL_SECTIONS = ("같이 보기", "각주", "내용주", "참고 문헌", "참고문헌", "외부 링크", "출처", "더 읽어보기")
_HEADING = re.compile(r"^(=+)\s*(.+?)\s*\1\s*$")


def page_url(title: str) -> str:
    return "https://ko.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))


def _params(**kw) -> dict:
    return {"format": "json", "formatversion": 2, "maxlag": 5, **kw}


def _get(params: dict) -> dict:
    """API 호출. 응답의 error를 확인하고, 일시적 오류는 기다렸다가 다시 시도한다."""
    for attempt in range(MAX_API_RETRIES + 1):
        resp = http().get(API, params=params)
        data = resp.json()
        error = data.get("error")
        if not error:
            return data
        code = error.get("code", "unknown")
        if code in TRANSIENT_ERRORS and attempt < MAX_API_RETRIES:
            retry_after = resp.headers.get("Retry-After", "")
            _sleep(float(retry_after) if retry_after.isdigit() else 5.0)
            continue
        raise SourceError(SOURCE_TYPE, code, error.get("info", ""))
    raise RuntimeError("unreachable")


def search(query: str, limit: int) -> list[Candidate]:
    data = _get(_params(
        action="query", generator="search", gsrsearch=query, gsrlimit=limit, gsrnamespace=0,
        prop="extracts|info|pageprops", exintro=1, explaintext=1, exsentences=2, exlimit=limit,
        ppprop="disambiguation",
    ))
    pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
    return [
        Candidate(
            doc_id=f"wiki:{p['pageid']}", title=p["title"], summary=(p.get("extract") or "").strip(),
            url=page_url(p["title"]), source_type=SOURCE_TYPE, length=p.get("length", 0),
            disambiguation="disambiguation" in (p.get("pageprops") or {}),
        )
        for p in pages if not p.get("missing")
    ]


def fetch(title: str, max_chars: int) -> Document | None:
    """문서 본문. 리다이렉트를 따라가고, 없는 문서면 None.

    문서는 있는데 본문이 비어 있으면 SourceError — 성공한 근거 문서로 캐시되지 않게 한다.
    """
    data = _get(_params(
        action="query", titles=title, redirects=1, prop="extracts|revisions",
        explaintext=1, rvprop="ids|timestamp",
    ))
    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing") or pages[0].get("invalid"):
        return None
    page = pages[0]
    text = clean_extract(page.get("extract") or "")
    if not text.strip():
        raise SourceError(SOURCE_TYPE, "empty-extract", f"본문이 비어 있습니다: {page['title']}")
    truncated = len(text) > max_chars
    revid = (page.get("revisions") or [{}])[0].get("revid")
    return Document(
        doc_id=f"wiki:{page['pageid']}", title=page["title"], url=page_url(page["title"]),
        permalink=f"https://ko.wikipedia.org/w/index.php?oldid={revid}" if revid else page_url(page["title"]),
        text=text[:max_chars], source_type=SOURCE_TYPE, license=LICENSE,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), truncated=truncated,
    )


def clean_extract(text: str) -> str:
    """꼬리 절을 지우고 빈 줄을 정리한다. 절 제목(== 역사 ==)은 청킹 단서로 남긴다."""
    lines = []
    for line in text.splitlines():
        heading = _HEADING.match(line.strip())
        if heading and heading.group(2) in TAIL_SECTIONS:
            break
        if line.strip():
            lines.append(line.strip())

    # 내용 없는 절 제목 — 다음 줄이 같거나 더 높은 수준의 제목이거나 끝이면 지운다
    kept = []
    for i, line in enumerate(lines):
        heading = _HEADING.match(line)
        if heading:
            nxt = _HEADING.match(lines[i + 1]) if i + 1 < len(lines) else None
            if i + 1 == len(lines) or (nxt and len(nxt.group(1)) <= len(heading.group(1))):
                continue
            kept.append("")                       # 절 앞에 빈 줄 — 청킹 경계 단서
        kept.append(line)
    return "\n".join(kept).strip()
