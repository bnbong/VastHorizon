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
