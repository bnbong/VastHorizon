"""문서 청킹 — 청크 크기와 중복 길이는 config.toml [chunking]에서 정한다.

출처 종류에 따라 자르는 경계를 달리한다.

| 출처      | 본문 구조                          | 우선 경계                        | 청크 머리말                     |
|-----------|------------------------------------|----------------------------------|---------------------------------|
| 위키백과  | '== 절 ==' 제목이 있는 한국어 문서 | 절 제목 → 문단 → 줄 → 문장 → 공백 | [문서 제목 > 절 > 하위 절]      |
| NASA      | 절 없는 영문 문단                  | 문단 → 줄 → 문장 → 공백          | [문서 제목]                     |

- 위키는 절이 의미 단위라 절 제목에서 먼저 자른다. 청크가 어느 절에서 왔는지 머리말로 붙여
  "목성 탐사"처럼 절 이름에만 있는 단서도 검색에 걸리게 한다.
- NASA 설명은 절이 없어 문단에서 먼저 자르고, 영문 문장 경계('. ')를 쓴다.
- 머리말은 청크 크기 계산에서 빠진다 (본문만 chunk_size 이하).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from vasthorizon.data.docs import Document

# 정규식 경계 — 절 제목은 다음 조각 앞에 붙고(lookahead), 문장 마침표는 앞 문장 끝에 남는다(lookbehind)
WIKI_SEPARATORS = [r"\n\n(?=== )", r"\n\n(?==== )", r"\n\n(?=====)", r"\n\n", r"\n", r"(?<=[.!?])\s+", r" ", ""]
PLAIN_SEPARATORS = [r"\n\n", r"\n", r"(?<=[.!?])\s+", r" ", ""]
_HEADING = re.compile(r"^(=+)\s*(.+?)\s*\1\s*$")


@dataclass
class Chunk:
    seq: int
    text: str           # 머리말 + 본문 — 임베딩 · 근거 표시에 쓰는 텍스트
    body: str           # 본문만
    section: str        # 절 경로 (위키) — 없으면 빈 문자열
    start: int          # 원문에서의 시작 위치


def splitter_for(doc: Document, chunk_size: int, chunk_overlap: int) -> RecursiveCharacterTextSplitter:
    separators = WIKI_SEPARATORS if doc.doc_id.startswith("wiki:") else PLAIN_SEPARATORS
    return RecursiveCharacterTextSplitter(
        separators=separators, is_separator_regex=True, chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        add_start_index=True, keep_separator="start", strip_whitespace=True,
    )


def section_paths(text: str) -> list[tuple[int, str]]:
    """(절이 시작하는 위치, 절 경로) 목록. '임무 과정 > 목성 탐사'처럼 상위 절부터 잇는다."""
    paths, stack, offset = [], [], 0
    for line in text.splitlines(keepends=True):
        heading = _HEADING.match(line.strip())
        if heading:
            level = len(heading.group(1))
            stack = [s for s in stack if s[0] < level] + [(level, heading.group(2))]
            paths.append((offset, " > ".join(name for _, name in stack)))
        offset += len(line)
    return paths


def _section_at(paths: list[tuple[int, str]], position: int) -> str:
    current = ""
    for start, path in paths:
        if start > position:
            break
        current = path
    return current


def _strip_headings(body: str) -> str:
    """청크 끝에 걸린 빈 절 제목 등은 머리말이 대신하므로 본문 앞 · 뒤 제목 줄만 정리한다."""
    lines = body.strip().splitlines()
    while lines and _HEADING.match(lines[-1].strip()):
        lines.pop()
    return "\n".join(lines).strip()


def chunk_document(doc: Document, chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    parts = splitter_for(doc, chunk_size, chunk_overlap).create_documents([doc.text])
    paths = section_paths(doc.text) if doc.doc_id.startswith("wiki:") else []
    chunks = []
    for part in parts:
        body = _strip_headings(part.page_content)
        if not body:
            continue
        start = part.metadata.get("start_index", 0)
        # 청크가 절 제목으로 시작하면 그 절의 경로를 쓴다 (제목 줄 바로 뒤 위치 기준)
        section = _section_at(paths, start + len(part.page_content) - len(part.page_content.lstrip()) + 1)
        header = f"[{doc.title}{' > ' + section if section else ''}]"
        chunks.append(Chunk(seq=len(chunks), text=f"{header}\n{body}", body=body, section=section, start=start))
    return chunks
