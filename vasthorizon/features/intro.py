"""천체 소개 — 항목 자체 위키 문서의 첫 부분과 역사 · 관측 절. (디자인 v2 — 읽고 나서 내 세계에 담기)

천체를 누르면 바로 '내 세계'에 넣지 않고, 먼저 그 천체의 이야기를 보여 준다. 사용자가 다 읽고 담기를 누르면 넓어진다.
소개 글은 LLM이 만들지 않는다 — 수집 캐시의 한국어 위키 문서에서 그대로 발췌하고 출처 · 이용 조건을 함께 보낸다.

| 절        | 고르는 방법                                                           |
|-----------|-----------------------------------------------------------------------|
| 소개      | 문서 첫머리(첫 절 제목 전)                                             |
| 이야기    | 제목에 역사 · 발견 · 명칭 · 이름 · 어원 · 신화 · 관측이 들어간 첫 절    |

각 절은 문장 단위로 잘라 INTRO_CHARS · STORY_CHARS 안에 맞춘다 (문장 중간에서 끊지 않는다).
"""

from __future__ import annotations

import re

from vasthorizon.collect.collector import Collector, StepFailure

INTRO_CHARS = 700
STORY_CHARS = 600
STORY_HEADING = re.compile(r"역사|발견|명칭|이름|어원|신화|관측|탐사|임무")
_HEADING = re.compile(r"^\s*(=+)\s*(.+?)\s*\1\s*$")
_SENTENCE_END = re.compile(r"(?<=[다요음함됨임]\.)\s+|(?<=[.!?])\s+(?=[가-힣A-Z0-9\"“(])")


def clip_sentences(text: str, limit: int) -> str:
    """limit 글자 안에서 문장 단위로 자른다. 첫 문장이 limit보다 길면 그 문장 하나를 말줄임으로."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    out = ""
    for sentence in _SENTENCE_END.split(text):
        if len(out) + len(sentence) + 1 > limit:
            break
        out = f"{out} {sentence}".strip()
    return out or text[:limit].rstrip() + "…"


def split_sections(text: str) -> list[tuple[str, str]]:
    """(절 제목, 본문) 목록. 첫머리는 제목 ''. 하위 절은 위 절에 이어 붙인다."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m and len(m.group(1)) == 2:                 # == 절 == 만 새 절, === 하위 절 === 은 본문으로
            sections.append((m.group(2), []))
        elif not m and line.strip():
            sections[-1][1].append(line.strip())
    return [(h, " ".join(body)) for h, body in sections if body]


def item_intro(item: dict, collector: Collector | None = None) -> dict:
    if not item.get("wiki_title"):
        return {"status": "unavailable", "sections": [],
                "notice": "이 별은 한국어 위키 문서가 없어 기본 정보만 보여 드립니다. 물어보면 관련 문서를 찾아 답합니다."}
    failures: list[StepFailure] = []
    doc = (collector or Collector()).fetch_wiki(item["wiki_title"], failures)
    if doc is None:
        return {"status": "unavailable", "sections": [],
                "notice": "이 천체의 문서를 지금 받을 수 없어 기본 정보만 보여 드립니다."}
    sections = split_sections(doc.text)
    out = []
    lead = next((body for heading, body in sections if heading == ""), "")
    if lead:
        out.append({"heading": "소개", "text": clip_sentences(lead, INTRO_CHARS)})
    story = next(((h, body) for h, body in sections if h and STORY_HEADING.search(h)), None)
    if story:
        out.append({"heading": story[0], "text": clip_sentences(story[1], STORY_CHARS)})
    return {"status": "ok" if out else "unavailable", "sections": out, "title": doc.title, "url": doc.url,
            "license": doc.license, "source_type": doc.source_type,
            "notice": None if out else "문서에 소개할 본문이 없어 기본 정보만 보여 드립니다."}
