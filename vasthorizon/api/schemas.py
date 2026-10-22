"""요청 · 응답 형식 (F2013). FastAPI가 이 정의로 /docs에 API 문서를 만든다.

화면에 내보내지 않는 것 (NF2004): API 키, 프롬프트 전문, 오류 추적 정보(스택 트레이스), 외부 요청 주소.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AnswerStatus = Literal["cited", "not_found", "rejected"]
StageStatus = Literal["ok", "partial", "failed", "skipped"]


# ── 상태 점검 ─────────────────────────────────────────────────────────────

class Notice(BaseModel):
    code: str = Field(description="안내 종류 — missing_key · index_missing · docs_index_empty …")
    level: Literal["info", "warning", "error"]
    message: str


class HealthResponse(BaseModel):
    ready: bool = Field(description="질문을 받을 수 있는 상태인가 (키 설정 + 항목 색인 있음)")
    gms_key: bool = Field(description="GMS 키가 설정됐는가 (값은 노출하지 않는다)")
    items_loaded: int
    items_indexed: int
    docs_indexed: int
    notices: list[Notice] = []


# ── 항목 ──────────────────────────────────────────────────────────────────

class ItemSummary(BaseModel):
    id: str
    name: str
    name_en: str | None = None
    group: str
    group_ko: str
    kind: str | None = None
    distance_ly: float | None = None
    distance_km: float | None = None
    ra_deg: float | None = None
    dec_deg: float | None = None


class SourceRef(BaseModel):
    name: str
    url: str
    used_for: str | None = None


class ItemDetail(ItemSummary):
    wiki_title: str
    attrs: dict
    distance: dict | None = None
    position_au: list[float] | None = None
    position_proxy: dict | None = None
    sources: list[SourceRef] = []


# ── 질문 · 답변 ───────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$",
                            description="브라우저가 만든 세션 ID — 항목별 대화 기록을 구분한다")
    item_id: str = Field(pattern=r"^Q\d+$")
    question: str = Field(min_length=1, max_length=500)
    search_type: Literal["similarity", "mmr"] | None = Field(None, description="비우면 설정값")


class CitedEvidence(BaseModel):
    number: int = Field(description="답변 본문의 [근거 N]과 같은 번호")
    kind: str = Field(description="항목 메타데이터 · 외부 문서")
    source_type: str = Field(description="항목 메타데이터 · 위키백과 · NASA")
    title: str
    section: str = ""
    url: str = Field(description="원문 출처")
    excerpt: str = Field(description="근거 본문 앞부분")


class StageInfo(BaseModel):
    status: StageStatus
    seconds: float


class AnswerResponse(BaseModel):
    item_id: str
    item_name: str
    question: str
    answer: str
    status: AnswerStatus = Field(description="cited: 인용 번호 검증 통과 (의미 일치까지 보장하지는 않음) · "
                                             "not_found: 문서에서 확인되지 않음 · rejected: 인용 규칙 위반으로 차단")
    cited: list[CitedEvidence]
    notice: str | None = Field(None, description="인용된 근거가 없을 때 등 화면 안내")
    warnings: list[str] = []
    stages: dict[str, StageInfo] = {}
    recorded: bool = Field(True, description="대화 기록에 남았는가 — 답변하는 동안 기록이 지워졌으면 false")


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    status: AnswerStatus | None = None
    cited: list[CitedEvidence] = []


class HistoryResponse(BaseModel):
    item_id: str
    turns: list[HistoryTurn]


class ErrorResponse(BaseModel):
    code: str
    message: str


# ── 조건 기반 탐색 (F2011) ────────────────────────────────────────────────

class ExploreRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="자연어 조건 — 예: 맨눈으로 볼 수 있는 은하")


class ExploreCardOut(BaseModel):
    item_id: str
    name: str
    group: str
    kind: str
    reason: str = Field(description="조건과 맞는 메타데이터 속성")


class ExploreResponse(BaseModel):
    query: str
    applied: list[str] = Field(description="조건을 해석해 적용한 필터 — 사용자가 해석 결과를 확인한다")
    cards: list[ExploreCardOut]
    candidates: int
    status: Literal["ok", "no_match", "failed"]
    notice: str | None = None
    warnings: list[str] = []


# ── 빛의 편지 (F2010) ─────────────────────────────────────────────────────

class LetterRequest(BaseModel):
    item_id: str | None = Field(None, pattern=r"^Q\d+$", description="편지를 받을 천체")
    age: int | None = Field(None, ge=1, le=120, description="나이 — 나이만큼 먼 별을 찾는다")


class DepartureOut(BaseModel):
    light_years: float
    light_time: str
    year: int | None = None
    year_label: str | None = None
    era: str | None = None
    year_range: list[int] | None = None
    summary: str


class LetterResponse(BaseModel):
    item_id: str
    item_name: str
    departure: DepartureOut
    letter: str
    status: AnswerStatus
    cited: list[CitedEvidence]
    notice: str | None = None
    matched_age: int | None = Field(None, description="나이로 찾은 경우 입력한 나이")
    age_gap_ly: float | None = Field(None, description="나이와 별까지 거리(광년)의 차이")
    warnings: list[str] = []
