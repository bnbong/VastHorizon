"""외부 문서 출처 — 한국어 위키백과 · NASA NSSDCA. (F2004 · F2016)

| 출처            | 문서                         | 출처 종류 표기 | 이용 조건                     |
|-----------------|------------------------------|----------------|-------------------------------|
| 한국어 위키백과 | 항목 문서 · 관련 개념 문서     | 위키백과       | CC BY-SA 4.0 (출처 · 라이선스 표기) |
| NASA NSSDCA     | 탐사선 · 위성 미션 설명(영문) | NASA           | 미국 정부 저작물 (공개)         |
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


class SourceError(RuntimeError):
    """외부 출처가 오류를 돌려줬을 때 — HTTP는 성공했지만 응답 본문에 error가 있는 경우 등.

    '검색 결과 0건' · '문서 없음' 같은 정상 응답과 구분한다. 수집기는 이 실패를 캐시하지 않는다.
    """

    def __init__(self, source: str, code: str, info: str = "") -> None:
        self.source, self.code = source, code
        super().__init__(f"{source} 오류 {code}: {info}".strip())


@dataclass
class Candidate:
    """검색 결과 후보 — 본문 없이 제목과 요약만 갖는다. 선별(프롬프트 2)에 쓴다."""

    doc_id: str
    title: str
    summary: str
    url: str
    source_type: str
    length: int = 0
    disambiguation: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Document:
    """색인할 문서 — 본문과 원문 출처를 갖는다."""

    doc_id: str                 # 출처 안에서 고유 — wiki:<pageid> · nssdca:<COSPAR>
    title: str
    url: str                    # 원문 주소
    permalink: str              # 수집한 판의 고정 주소 (위키 oldid)
    text: str
    source_type: str            # 위키백과 · NASA
    license: str
    fetched_at: str
    truncated: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Document":
        return cls(**data)
