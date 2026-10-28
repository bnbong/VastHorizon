"""빛의 편지 (대표 기능) — "지금 당신에게 닿은 이 빛이 출발했을 때, 지구에서는…"

근거
1. 항목 메타데이터 (거리 · 빛이 걸리는 시간 · 출발 시점)
2. 빛이 출발한 해의 한국어 위키 연도 문서 (예: 「1587년」의 사건 · 탄생 · 사망)

데이터 일관성 — 출발 연도 계산 · 근거 1 · 연도 문서를 모두 같은 (카탈로그 항목, 기준 연도)에서 만든다.
근거 1을 색인(cosmos_items)에서 가져오지 않는 이유: 카탈로그가 갱신됐는데 색인이 아직이면
계산한 출발 연도와 근거의 거리가 어긋난 채 모델에 들어가고, 인용 번호 검증으로는 이를 잡을 수 없다.

거리별 처리
| 거리                       | 편지                                              |
|----------------------------|---------------------------------------------------|
| 없음 · 지표 고도(위성)     | 쓸 수 없음 — LetterUnavailableError               |
| 우리 은하 그룹             | 쓸 수 없음 — 한 점의 빛이 아니거나(우리 은하) 눈에 닿는 빛이 없다(궁수자리 A*) |
| 1광년 미만 (태양계 · 탐사선) | 몇 분 · 몇 시간 전에 출발한 빛 (연도 문서 없음)   |
| 1광년 ~ 10만 광년          | 출발 연도 · 범위 + 그 해의 연도 문서              |
| 10만 광년 이상 (은하)       | 인류 문명 이전에 출발한 빛 (연도 문서 없음)       |

출발 연도는 거리(중앙값)로 계산한 근삿값이다. 출처마다 거리가 다르면 연도 범위도 함께 알린다.
편지는 질의응답과 같은 인용 검증 · 재생성 정책을 따른다 (rag/graph.py generate_validated).

확장 — 당신의 나이만큼 먼 별: 나이(광년)와 거리가 가장 가까운 별을 찾는다.
그 별빛이 출발한 해 ≈ 태어난 해라서, 태어난 해의 연도 문서가 근거가 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel

from vasthorizon.collect.collector import Collector, StepFailure
from vasthorizon.data.item_text import departure_year, korean_era, korean_number, light_time_text, year_text
from vasthorizon.data.items.common import LY_KM, REF_SURFACE_ALTITUDE
from vasthorizon.rag.graph import default_chat_model, generate_validated
from vasthorizon.rag.prompts import letter_messages
from vasthorizon.features.evidence import catalog_evidence
from vasthorizon.rag.retrieval import KIND_DOC, Evidence

HISTORY_LIMIT_LY = 100_000          # 이보다 멀면 연도가 아니라 "몇 만 년 전"으로 쓴다
YEAR_DOC_CHARS = 2500               # 현대 연도 문서는 1만 자가 넘어서 앞부분만 쓴다
MAX_AGE = 120


class LetterUnavailableError(ValueError):
    """이 항목으로는 빛의 편지를 쓸 수 없다 (거리 정보 없음 등)."""


@dataclass
class Departure:
    light_years: float
    light_time: str                  # 빛이 걸리는 시간 ("약 439년", "약 8.3분")
    year: int | None = None          # 출발한 해 (1광년 ~ 10만 광년만)
    year_label: str | None = None    # "1587년" · "기원전 75년"
    era: str | None = None
    year_range: tuple[int, int] | None = None     # 출처별 거리 범위로 계산한 출발 연도 범위

    def summary(self) -> str:
        if self.year is None:
            if self.light_years >= HISTORY_LIMIT_LY:
                return f"빛이 걸리는 시간 {self.light_time} — 약 {korean_number(self.light_years)}년 전, 인류 문명 이전에 출발"
            return f"빛이 걸리는 시간 {self.light_time} — 지금 보는 빛은 그만큼 전에 출발"
        text = f"빛이 걸리는 시간 {self.light_time} — {self.year_label} 무렵({self.era}) 출발"
        if self.year_range and self.year_range[0] != self.year_range[1]:
            text += f", 출처별 거리 차이로 {year_text(self.year_range[0])} ~ {year_text(self.year_range[1])} 사이"
        return text


@dataclass
class LetterResult:
    item: dict
    departure: Departure
    letter: str
    status: str                       # cited · not_found · rejected
    cited: list[Evidence]
    evidences: list[Evidence]
    attempts: int = 1
    warnings: list[str] = field(default_factory=list)


def compute_departure(item: dict, ref_year: int) -> Departure:
    if item.get("group") == "milky_way":
        raise LetterUnavailableError("우리 은하와 그 중심의 블랙홀은 눈에 닿는 한 점의 빛이 아니라 빛의 편지를 쓸 수 없습니다.")
    dist = item.get("distance")
    if not dist:
        raise LetterUnavailableError(f"{item['name']}은(는) 거리 정보가 없어 빛의 편지를 쓸 수 없습니다.")
    if dist.get("reference") == REF_SURFACE_ALTITUDE:
        raise LetterUnavailableError(f"{item['name']}은(는) 지구 궤도를 도는 위성이라 빛의 여정이 짧아 편지를 쓸 수 없습니다.")
    ly = dist["km"] / LY_KM
    departure = Departure(light_years=ly, light_time=light_time_text(dist["km"]))
    if 1 <= ly < HISTORY_LIMIT_LY:
        departure.year = departure_year(ly, ref_year)
        departure.year_label = year_text(departure.year)
        departure.era = korean_era(departure.year)
        if dist.get("km_min") and dist.get("km_max"):
            far, near = departure_year(dist["km_max"] / LY_KM, ref_year), departure_year(dist["km_min"] / LY_KM, ref_year)
            departure.year_range = (far, near)
    return departure


def year_evidence(year_label: str, collector: Collector, failures: list[StepFailure]) -> Evidence | None:
    """그 해의 위키 연도 문서. 받지 못하면 None (편지는 항목 근거만으로 쓴다)."""
    doc = collector.fetch_wiki(year_label, failures)
    if doc is None:
        return None
    return Evidence(number=0, chunk_id=f"year:{doc.doc_id}", kind=KIND_DOC, source_type=doc.source_type,
                    title=doc.title, section="", url=doc.url, text=f"[{doc.title}]\n{doc.text[:YEAR_DOC_CHARS]}")


def write_letter(item: dict, ref_year: int, llm: BaseChatModel | None = None,
                 collector: Collector | None = None) -> LetterResult:
    # 계산값 · 근거 1 · 연도 문서를 모두 같은 (item, ref_year)에서 만든다
    departure = compute_departure(item, ref_year)
    evidences, warnings = [catalog_evidence(item, ref_year)], []

    if departure.year_label:
        failures: list[StepFailure] = []
        year_ev = year_evidence(departure.year_label, collector or Collector(), failures)
        if year_ev:
            year_ev.number = 2
            evidences.append(year_ev)
        else:
            warnings.append(f"「{departure.year_label}」 문서를 받지 못해 그 해의 사건 없이 편지를 씁니다.")

    result = generate_validated(default_chat_model(llm), letter_messages(item, departure.summary(), evidences), evidences,
                                purpose="letter")
    warnings += result["notes"]                  # 언어 혼입 등 — 답은 내보내되 알린다
    if result["status"] == "rejected":
        warnings.append("편지가 인용 규칙을 두 번 어겨 내보내지 않았습니다.")
    return LetterResult(item=item, departure=departure, letter=result["answer"], status=result["status"],
                        cited=result["cited"], evidences=evidences, attempts=result["attempts"], warnings=warnings)


def star_for_age(items: list[dict], age: float) -> tuple[dict, float]:
    """나이(광년)와 거리가 가장 가까운 별과 그 차이(광년)."""
    if not 1 <= age <= MAX_AGE:
        raise LetterUnavailableError(f"나이는 1세에서 {MAX_AGE}세 사이로 입력해 주세요.")
    stars = [it for it in items if it["group"] == "star" and it.get("distance")]
    if not stars:
        raise LetterUnavailableError("거리 정보가 있는 별이 없습니다.")
    best = min(stars, key=lambda it: abs(it["distance"]["km"] / LY_KM - age))
    return best, abs(best["distance"]["km"] / LY_KM - age)
