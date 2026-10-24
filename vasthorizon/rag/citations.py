"""근거 번호 처리 — 인용 해석과 답변 검증을 분리한다.

인용 해석 (resolve_citations)
- 답변 본문의 [근거 N] 표기를 찾아 인용된 근거를 모은다.
- 번호는 다시 매기지 않는다 — 본문의 [근거 3]과 화면의 '근거 3'이 그대로 이어지게.

답변 검증 (citation_issue) — 통과하지 못한 답변은 정상 답변으로 내보내지 않는다
- 근거 목록에 없는 번호를 인용함 → 위반 (번호만 지우면 근거 없는 주장이 숨겨지므로 지우지 않는다)
- 사실 답변인데 유효한 인용이 하나도 없음 → 위반
- '문서에서 확인되지 않는다'는 답변은 인용이 없어도 된다 (인용이 있다면 유효해야 한다)

한계 — 이 검증은 번호가 근거 목록에 있는지(형식)만 본다.
주장과 근거의 내용이 실제로 맞는지(의미)는 보장하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_CITE = re.compile(r"\[근거\s*(\d+(?:\s*[,，]\s*\d+)*)\]")


@dataclass
class CitedAnswer:
    text: str                                   # 답변 본문 ('[근거 1, 3]'만 '[근거 1][근거 3]'으로 정리)
    cited: list = field(default_factory=list)   # 유효하게 인용된 근거 (번호 순)
    invalid_numbers: list[int] = field(default_factory=list)   # 근거 목록에 없는 번호 — 본문에 그대로 남긴다

    @property
    def has_citations(self) -> bool:
        return bool(self.cited)


def _numbers(group: str) -> list[int]:
    return [int(n) for n in re.findall(r"\d+", group)]


def resolve_citations(answer: str, evidences: list) -> CitedAnswer:
    by_number = {ev.number: ev for ev in evidences}
    used: set[int] = set()
    invalid: set[int] = set()

    def rewrite(match: re.Match) -> str:
        nums = _numbers(match.group(1))
        used.update(n for n in nums if n in by_number)
        invalid.update(n for n in nums if n not in by_number)
        return "".join(f"[근거 {n}]" for n in nums)

    text = _CITE.sub(rewrite, answer).strip()
    text = re.sub(r"(\[근거 \d+\])(?:\s*\1)+", r"\1", text)       # '[근거 2] [근거 2]' → '[근거 2]'
    return CitedAnswer(text=text, cited=[by_number[n] for n in sorted(used)], invalid_numbers=sorted(invalid))


def citation_issue(answer: CitedAnswer, not_found: bool) -> str | None:
    """답변이 인용 규칙을 어겼으면 그 내용을, 통과하면 None을 돌려준다."""
    if answer.invalid_numbers:
        return f"근거 목록에 없는 번호 {answer.invalid_numbers}를 인용했다"
    if not answer.has_citations and not not_found:
        return "사실을 말하면서 근거 번호를 하나도 붙이지 않았다"
    return None
