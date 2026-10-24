"""NASA NSSDCA 마스터 카탈로그 — 탐사선 · 위성 미션 설명(영문). (두 번째 출처 종류)

COSPAR ID로 https://nssdc.gsfc.nasa.gov/nmc/spacecraft/display.action?id=<ID> 의
'Description' 절을 읽는다. 미국 정부 저작물이라 공개 이용이 가능하다.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone

import requests

from vasthorizon.data.docs import Document
from vasthorizon.http import http

PAGE = "https://nssdc.gsfc.nasa.gov/nmc/spacecraft/display.action?id={cospar}"
SOURCE_TYPE = "NASA"
LICENSE = "미국 정부 저작물 (NASA NSSDCA, 공개)"

_TITLE = re.compile(r"<h1>(.*?)</h1>", re.S)
_DESCRIPTION = re.compile(r"<h2>Description</h2>(.*?)</div>", re.S)


def parse_description(page_html: str) -> tuple[str, str] | None:
    """(제목, 설명 평문). 설명 절이 없으면 None."""
    title, body = _TITLE.search(page_html), _DESCRIPTION.search(page_html)
    if not title or not body:
        return None
    text = re.sub(r"<\s*/?\s*p\s*/?>", "\n\n", body.group(1))
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return html.unescape(title.group(1)).strip(), text


def fetch(cospar: str, max_chars: int) -> Document | None:
    url = PAGE.format(cospar=cospar)
    try:
        page = http().get(url).text
    except requests.HTTPError:
        return None
    parsed = parse_description(page)
    if not parsed or not parsed[1]:
        return None
    title, text = parsed
    return Document(
        doc_id=f"nssdca:{cospar}", title=f"{title} (NASA NSSDCA)", url=url, permalink=url,
        text=text[:max_chars], source_type=SOURCE_TYPE, license=LICENSE,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), truncated=len(text) > max_chars,
    )
