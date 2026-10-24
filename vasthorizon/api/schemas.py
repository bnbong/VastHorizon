"""요청 · 응답 형식. FastAPI가 이 정의로 /docs에 API 문서를 만든다.

화면에 내보내지 않는 것: API 키, 프롬프트 전문, 오류 추적 정보(스택 트레이스), 외부 요청 주소.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AnswerStatus = Literal["cited", "not_found", "rejected"]
StageStatus = Literal["ok", "partial", "failed", "skipped"]


# ── 상태 점검 ─────────────────────────────────────────────────────────────

class Notice(BaseModel):
    code: str = Field(description="안내 종류 — missing_key · index_missing · docs_index_empty …")
    level: Literal["info", "warning", "error"]
    message: str


class UsageToday(BaseModel):
    day: str = Field(description="집계 날짜 (한국 시각)")
    calls: int = Field(description="LLM 호출 수 (실패 포함)")
    input_tokens: int
    output_tokens: int = Field(description="출력 토큰 (추론 포함)")
    reasoning_tokens: int
    cache_read_tokens: int = Field(description="프롬프트 캐시에서 읽은 입력 토큰")
    cost_usd: float = Field(description="설정 가격표로 계산한 추정 비용 ($)")
    budget_usd: float | None = Field(None, description="하루 예산 ($) — 없으면 예산 제한 없음")
    cache_hits: int = Field(description="서버 응답 캐시 적중 수 (LLM 호출 없음)")


class ShareInfo(BaseModel):
    count: int = Field(description="보관 중인 공유 링크 수")


class HealthResponse(BaseModel):
    ready: bool = Field(description="질문을 받을 수 있는 상태인가 (키 설정 + 항목 색인 있음)")
    gms_key: bool = Field(description="LLM 키(GMS_KEY 또는 CLAUDE_API_KEY)가 설정됐는가 (값은 노출하지 않는다, 필드 이름은 호환을 위해 유지)")
    items_loaded: int
    items_indexed: int
    docs_indexed: int
    notices: list[Notice] = []
    usage: UsageToday | None = Field(None, description="오늘(한국 시각) LLM 사용량 · 추정 비용 — 기록이 꺼져 있으면 없음")
    share: ShareInfo | None = Field(None, description="편지 공유 — 공유 저장소가 없으면 없음")


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
    wiki_title: str | None = Field(None, description="자체 위키 문서 — 별자리 선의 별은 없을 수 있다")
    attrs: dict
    distance: dict | None = None
    position_au: list[float] | None = None
    position_proxy: dict | None = None
    sources: list[SourceRef] = []


# ── 질문 · 답변 ───────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$",
                            description="브라우저가 만든 세션 ID — 항목별 대화 기록을 구분한다")
    item_id: str = Field(pattern=r"^(Q\d+|hip:\d+)$", description="카탈로그 항목(Q…) 또는 별자리 선의 별(hip:…)")
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
    cached: bool = Field(False, description="서버 응답 캐시에서 꺼낸 응답인가 (LLM을 부르지 않았다)")


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


# ── 조건 기반 탐색 ────────────────────────────────────────────────

class ExploreRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="자연어 조건 — 예: 맨눈으로 볼 수 있는 은하")


class ExploreCardOut(BaseModel):
    item_id: str
    name: str
    group: str
    kind: str
    reason: str = Field(description="조건과 맞는 메타데이터 속성")
    source_url: str | None = Field(None, description="카드 설명의 근거 URL (조건 탐색의 결정적 경로 — 블랙홀 · 고리 · 탐사선 방문 등)")


class ExploreMention(BaseModel):
    item_id: str
    name: str
    group: str
    kind: str = ""


class ExploreResponse(BaseModel):
    query: str
    applied: list[str] = Field(description="조건을 해석해 적용한 필터 — 사용자가 해석 결과를 확인한다")
    cards: list[ExploreCardOut]
    candidates: int
    status: Literal["ok", "no_match", "failed", "ask"] = Field(description="ask: 특정 천체에 대한 사실 질문 — mentioned의 천체에게 묻는다")
    mentioned: list[ExploreMention] = Field([], description="질문에 이름이 나온 카탈로그 천체 — 그 천체에게 직접 물을 수 있다")
    notice: str | None = None
    warnings: list[str] = []
    cached: bool = Field(False, description="서버 응답 캐시에서 꺼낸 응답인가 (LLM을 부르지 않았다)")


# ── 빛의 편지 ─────────────────────────────────────────────────────

class LetterRequest(BaseModel):
    item_id: str | None = Field(None, pattern=r"^(Q\d+|hip:\d+)$", description="편지를 받을 천체")
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
    cached: bool = Field(False, description="서버 응답 캐시에서 꺼낸 응답인가 (LLM을 부르지 않았다)")


# ── 별자리 펼치기 ──────────────────────────────────────────────────

class FigureStar(BaseModel):
    hip: int = Field(description="히파르코스 번호")
    name: str
    item_id: str | None = Field(None, description="카탈로그 항목이면 그 ID")
    ra_deg: float
    dec_deg: float
    mag: float = Field(description="겉보기 등급")
    distance_ly: float | None = Field(None, description="실제 거리 — 화면에서 별을 펼칠 위치")
    distance_basis: str | None = None


class FigureStats(BaseModel):
    stars: int
    known: int = Field(description="거리가 알려진 별 수")
    nearest_hip: int | None = None
    farthest_hip: int | None = None
    spread_ly: float | None = None
    ratio: float | None = Field(None, description="가장 먼 별 거리 ÷ 가장 가까운 별 거리")


class FigureResponse(BaseModel):
    item_id: str
    name: str
    lines: list[list[int]] = Field(description="별자리 선 — 히파르코스 번호를 잇는 순서")
    stars: list[FigureStar]
    stats: FigureStats
    licenses: dict[str, str]


class UnfoldResponse(BaseModel):
    item_id: str
    name: str
    stats: FigureStats
    explanation: str
    status: AnswerStatus
    cited: list[CitedEvidence]
    notice: str | None = None
    warnings: list[str] = []
    cached: bool = Field(False, description="서버 응답 캐시에서 꺼낸 응답인가 (LLM을 부르지 않았다)")


# ── 오늘 밤 나의 하늘 ──────────────────────────────────────────────

class SkyRequest(BaseModel):
    lat: float = Field(ge=-90, le=90, description="위도 (북위 +)")
    lon: float = Field(ge=-180, le=180, description="경도 (동경 +)")
    at: datetime | None = Field(None, description="관측 시각 — 비우면 지금, 시간대가 없으면 한국 시간")
    guide: bool = Field(True, description="false면 위치 계산만 (LLM 호출 없음)")


class SkyObjectOut(BaseModel):
    name: str
    item_id: str | None = None
    group: str
    alt_deg: float = Field(description="고도 — 지평선 0도, 머리 위 90도")
    az_deg: float = Field(description="방위 — 북 0도, 동 90도")
    direction: str


class SkyResponse(BaseModel):
    lat: float
    lon: float
    at: datetime
    sun_alt_deg: float
    is_night: bool
    constellations: list[SkyObjectOut]
    planets: list[SkyObjectOut]
    guide: str | None = None
    status: Literal["cited", "not_found", "rejected", "daytime", "empty", "skipped"]
    cited: list[CitedEvidence] = []
    notice: str | None = None
    warnings: list[str] = []


# ── 관점 전환 ──────────────────────────────────────────────────────

class ThemeOut(BaseModel):
    key: str
    label: str = Field(description="감정 버튼 문구")
    titles: list[str] = Field(description="이 주제의 서가 문서")


class SupportLine(BaseModel):
    name: str
    number: str
    hours: str


class PerspectiveRequest(BaseModel):
    text: str | None = Field(None, max_length=300, description="지금 내 마음 한 줄")
    theme: str | None = Field(None, description="감정 버튼 — GET /api/perspective/themes 의 key")


class RelatedItem(BaseModel):
    id: str
    name: str


class PerspectiveResponse(BaseModel):
    status: Literal["cited", "not_found", "rejected", "crisis", "unchecked"] = Field(
        description="crisis: 위기 — 상담 창구 안내 · unchecked: 위기 여부를 확인하지 못해 답변하지 않음")
    answer: str
    crisis: bool = Field(description="true면 화면은 상담 창구 안내를 가장 먼저 크게 보여준다")
    themes: list[str] = []
    cited: list[CitedEvidence] = []
    items: list[RelatedItem] = Field([], description="이어서 둘러볼 천체")
    disclaimer: str
    support: list[SupportLine]
    notice: str | None = None
    warnings: list[str] = []
    cached: bool = Field(False, description="서버 응답 캐시에서 꺼낸 응답인가 (LLM을 부르지 않았다)")


# ── 편지 공유 ─────────────────────────────────────────────────────────────

class ShareRequest(BaseModel):
    kind: Literal["letter", "perspective"]
    item_id: str | None = Field(None, pattern=r"^(Q\d+|hip:\d+)$", description="letter — 편지를 받은 천체")
    age: int | None = Field(None, ge=1, le=120, description="letter — 나이로 받은 편지면 그 나이")
    text: str | None = Field(None, max_length=300, description="perspective — 보낸 마음 한 줄 (캐시 키를 만드는 데만 쓰고 저장하지 않는다)")
    theme: str | None = Field(None, max_length=40, description="perspective — 감정 버튼 key")


class ShareResponse(BaseModel):
    id: str = Field(description="내용 해시 앞 16자 — 같은 편지는 같은 id (해시 앞부분이 겹치면 2자씩 더 길다)")
    url: str = Field(description="공유 링크 (미리보기 카드가 있는 페이지)")
    image_url: str = Field(description="미리보기 이미지 1200×630 PNG")
    tall_image_url: str = Field(description="편지 전체를 담은 세로형 카드 PNG (이미지로 저장 · 카카오톡 피드)")
    tall_image_height: int = Field(description="세로형 카드의 높이 px (폭 1080, 높이 1620~1920)")
    created: str = Field(description="처음 공유한 시각 (UTC, ISO 8601)")


# ── 천체 소개 (읽고 나서 내 세계에 담기) ─────────────────────────────────────

class IntroSection(BaseModel):
    heading: str = Field(description="소개 · 관측 역사 등 — 문서의 절 제목")
    text: str = Field(description="문서 본문 발췌 (문장 단위로 자름, LLM이 만들지 않음)")


class IntroResponse(BaseModel):
    item_id: str
    status: Literal["ok", "unavailable"]
    sections: list[IntroSection] = []
    title: str | None = Field(None, description="발췌한 문서 제목")
    url: str | None = None
    license: str | None = None
    source_type: str | None = None
    notice: str | None = None
