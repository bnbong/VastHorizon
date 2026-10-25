"""VastHorizon API 서버.

    uvicorn vasthorizon.api.app:app --port 8000
    → http://localhost:8000/docs  (요청 · 응답 형식 문서)

| 메서드 · 경로                         | 역할                                             |
|---------------------------------------|--------------------------------------------------|
| GET  /api/health                      | 키 · 색인 상태와 화면 안내                       |
| GET  /api/items                       | 항목 목록 (그룹 · 이름 필터)                     |
| GET  /api/items/{item_id}             | 항목 상세                                        |
| GET  /api/items/{item_id}/intro       | 천체 소개 — 자체 위키 문서 첫머리 · 역사 절 발췌   |
| POST /api/ask                         | 질문 → 근거 기반 답변                            |
| POST /api/ask/stream                  | 같은 질문을 진행 상태와 함께 SSE로               |
| GET  /api/history/{item_id}           | 항목별 대화 기록                                 |
| DELETE /api/history/{item_id}         | 항목별 대화 기록 지우기                          |
| POST /api/explore                     | 자연어 조건으로 항목 찾기                        |
| POST /api/light-letter                | 빛의 편지 — 천체 또는 나이로                     |
| GET  /api/map                         | 3D 우주 지도 — 항목별 방향 · 거리 · 배치 방식    |
| GET  /api/constellations              | 별자리 88개의 선과 별 (천구 · 펼치기 화면)       |
| GET  /api/constellations/{id}/figure  | 별자리 선과 별들의 실제 거리 (3D 펼치기용)       |
| POST /api/constellations/{id}/unfold  | 별자리 펼치기 설명 — 근거 인용                   |
| POST /api/sky                         | 오늘 밤 나의 하늘 — 위치 계산 + 안내             |
| GET  /api/perspective/themes          | 관점 전환 감정 버튼 (주제 · 서가 문서)           |
| POST /api/perspective                 | 관점 전환 — 위기 표현이면 상담 창구 안내 먼저    |
| POST /api/share                       | 편지 공유 — 캐시에 있는 편지 · 마음 한 줄만 링크로 |
| GET  /api/l/{id}                      | 공유 링크 — 미리보기(OG) 태그가 있는 HTML         |
| GET  /api/l/{id}.json · .png          | 공유 기록 그대로 · 1200×630 미리보기 이미지       |
| GET  /api/l/{id}/tall.png             | 편지 전체를 담은 세로형 카드 (1080×1620~1920)    |
| GET  /api/l/{id}/audio.mp3            | 편지를 읽은 MP3 (Google TTS) — 못 쓰면 503 · 502, 화면은 기기 음성으로 |
| GET  / · /index.html                  | 화면 — [share] kakao_js_key가 있으면 vh-kakao-key meta에 넣어서 |

오류 응답은 {"code", "message"} 형식이다. 스택 트레이스 · 키 · 프롬프트는 내보내지 않는다.

동시성 정책
- 서비스 초기화: 첫 요청에서 한 번만 만든다 (잠금으로 보호). 모든 요청이 같은 Services를 쓴다.
- 대화(세션 + 항목)마다 한 번에 한 질문 — 처리 중이면 409 conversation_busy (sessions.py 참고).
  일반 질문과 SSE가 같은 begin · finish 절차를 쓴다. SSE는 스트림을 열기 전에 검사한다.
- 처리 중 기록 삭제: 그 질문의 답변은 돌려주되 recorded=false — 지운 기록에 다시 섞이지 않는다.

비용 정책 (LLM을 부르는 처리기)
0. 코드로 바로 정해지는 응답은 캐시 · 예산 · 한도 앞에서 돌려준다 — 마음 한 줄의 위기 표현(상담 창구 안내),
   이름만 있는 · 동의어 표로 완전히 해석되는 조건 탐색(LLM 0회, explore.uses_llm). 예산을 다 써도 된다.
1. 서버 응답 캐시(cache.py)를 먼저 본다. 적중하면 LLM · 호출 한도 · 하루 예산을 쓰지 않고 cached=true로 돌려준다.
   질문(ask)은 대화 기록이 없을 때만 캐시한다 — 이전 대화에 기대는 질문은 같은 문장이라도 답이 다르다.
2. 캐시에 없으면 spend_ai: 하루 예산([limits] daily_cost_usd, usage.py 기록 기준) → 호출 한도(limits.py) 순서로 검사.
3. 실패 · 근거 부족 · 경고가 있는 결과는 캐시하지 않는다 (다음 요청에서 다시 만든다).
4. 실시간 근거(오늘 UTC 기준 위치 · 거리)가 들어간 답은 ask_live_days와 다음 UTC 자정 중 이른 때에 만료된다.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import queue
import threading
import hashlib
from pathlib import Path

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from vasthorizon.api.schemas import (
    AnswerResponse, AskRequest, CitedEvidence, DepartureOut, ErrorResponse, ExploreCardOut, ExploreMention, ExploreRequest,
    ExploreResponse, FigureResponse, FigureStar, FigureStats, HealthResponse, HistoryResponse, HistoryTurn,
    IntroResponse, IntroSection,
    ItemDetail, ItemSummary, LetterRequest, LetterResponse, PerspectiveRequest, PerspectiveResponse,
    RelatedItem, ShareInfo, ShareRequest, ShareResponse, SkyObjectOut, SkyRequest, SkyResponse, SourceRef,
    StageInfo, SupportLine, ThemeOut, TtsInfo, UnfoldResponse,
)
from vasthorizon.api.services import ItemNotFoundError, Services, default_services
from vasthorizon import usage as usage_log
from vasthorizon.cache import normalize_text, text_hash
from vasthorizon.features.star_items import StarLookupError
from vasthorizon.api.sessions import ConversationBusyError, Ticket
from vasthorizon.config import PROJECT_ROOT
from vasthorizon.rag.prompts import PROMPT_VERSIONS
from vasthorizon.data.constellation_figures import LICENSES, figure_stats
from vasthorizon.data.items.common import GROUPS
from vasthorizon.features.constellation import FigureUnavailableError, figure_for
from vasthorizon.features.explore import uses_llm
from vasthorizon.data.perspective_library import THEMES
from vasthorizon.features.light_letter import LetterUnavailableError, star_for_age
from vasthorizon.features.perspective import PerspectiveInputError, keyword_crisis
from vasthorizon.features.sky import SkyInputError, compute_sky
from vasthorizon.features.space_map import constellation_list, map_points
from vasthorizon.llm import MissingApiKeyError
from vasthorizon.rag.retrieval import IndexMissingError
from vasthorizon.share import (
    ShareNotReadyError, ShareRefusedError, ShareUnavailableError, echoes, letter_record, perspective_record,
)
from vasthorizon.store.chroma import EmbeddingMismatchError
from vasthorizon.tts import TtsError, TtsQuotaError, TtsUnavailableError, record_text
from vasthorizon.webmeta import inject_kakao_key, valid_kakao_key

log = logging.getLogger(__name__)
WEB_DIR = PROJECT_ROOT / "web"

# Windows는 레지스트리 설정에 따라 .js를 text/plain으로 알려 주는데, 브라우저는 그 모듈 스크립트를 거부한다.
# 정적 파일의 형식을 운영체제 설정과 관계없이 고정한다.
for _ext, _type in ((".js", "text/javascript"), (".mjs", "text/javascript"), (".css", "text/css"), (".json", "application/json"),
                    (".bin", "application/octet-stream"), (".glb", "model/gltf-binary"), (".wasm", "application/wasm")):
    mimetypes.add_type(_type, _ext)
EXCERPT_CHARS = 200

NO_CITATION = "답변에 인용된 근거가 없습니다."
NOT_FOUND_NOTICE = "문서에서 확인되지 않아 인용된 근거가 없습니다."
REJECTED_NOTICE = "근거 번호 규칙을 지키는 답변을 만들지 못해 답변 대신 안내를 표시합니다."
NOT_RECORDED_NOTICE = "답변하는 동안 대화 기록이 지워져, 이 답변은 기록에 남지 않습니다."
# SSE 하트비트 간격(초). 이벤트 사이가 이보다 길면 주석 줄(: keepalive)을 보낸다.
# Cloudflare는 원본이 100초 동안 바이트를 보내지 않으면 끊고, Nginx proxy_read_timeout도 이벤트 사이 간격에 걸린다.
KEEPALIVE_SECONDS = 15.0
# 공유 링크 만들기의 하루 한도 — 분당 한도([share] per_ip_per_minute)가 주된 제한이고, 이 값은 메모리 상한용
SHARE_PER_IP_PER_DAY = 2000
SHARE_GLOBAL_PER_DAY = 50000
# 읽어 주기 합성의 하루 한도 — 분당 한도([tts] per_ip_per_minute)와 글자 수 원장([tts] daily_chars)이 주된 제한, 이 값은 메모리 상한용
TTS_PER_IP_PER_DAY = 500
TTS_GLOBAL_PER_DAY = 20000
TTS_QUOTA_MESSAGES = {                          # TtsQuotaError.reason → 안내
    "month": "이달 읽어 주기 한도를 다 썼어요 — 기기 음성으로 읽어 드립니다",
    "day": "오늘 읽어 주기 한도를 다 썼어요 — 기기 음성으로 읽어 드립니다",
    "cooldown": "서버 읽어 주기를 잠시 쉬고 있어요 — 기기 음성으로 읽어 드립니다",
}
TTS_QUOTA_MESSAGE = TTS_QUOTA_MESSAGES["month"]
TTS_UNAVAILABLE_MESSAGE = "지금은 서버 읽어 주기를 쓸 수 없어요 — 기기 음성으로 읽어 드립니다"


# ── 오류 → 안내 ───────────────────────────────────────────

def error_payload(error: Exception) -> tuple[int, ErrorResponse]:
    if isinstance(error, StarLookupError):
        return 503, ErrorResponse(code="star_lookup_failed", message="별 정보를 Wikidata에서 받아 오지 못했습니다. 잠시 뒤 다시 눌러 주세요.")
    if isinstance(error, ItemNotFoundError):
        return 404, ErrorResponse(code="item_not_found", message="선택한 항목을 찾을 수 없습니다.")
    if isinstance(error, LetterUnavailableError):
        return 422, ErrorResponse(code="letter_unavailable", message=str(error))
    if isinstance(error, FigureUnavailableError):
        return 422, ErrorResponse(code="figure_unavailable", message=str(error))
    if isinstance(error, PerspectiveInputError):
        return 422, ErrorResponse(code="invalid_request", message=str(error))
    if isinstance(error, SkyInputError):
        return 422, ErrorResponse(code="invalid_request", message=str(error))
    if isinstance(error, ShareNotReadyError):
        return 404, ErrorResponse(code="share_not_ready", message="편지를 다시 받은 뒤 공유해 주세요.")
    if isinstance(error, ShareRefusedError):
        return 409, ErrorResponse(code="share_refused", message=error.message or "이 응답은 공유할 수 없습니다.")
    if isinstance(error, ShareUnavailableError):
        return 503, ErrorResponse(code="share_unavailable", message="지금은 공유 링크를 만들 수 없습니다. 잠시 뒤 다시 시도해 주세요.")
    if isinstance(error, ConversationBusyError):
        return 409, ErrorResponse(code="conversation_busy",
                                  message="이 항목의 이전 질문에 아직 답하는 중입니다. 답변이 끝난 뒤 다시 질문해 주세요.")
    if isinstance(error, MissingApiKeyError):
        from vasthorizon.config import key_name
        return 503, ErrorResponse(code="missing_key", message=f"AI 서비스 키({key_name()})가 설정되지 않아 답할 수 없습니다.")
    if isinstance(error, IndexMissingError):
        return 503, ErrorResponse(code="index_missing", message=str(error))
    if isinstance(error, EmbeddingMismatchError):
        return 503, ErrorResponse(code="index_incompatible",
                                  message="색인과 현재 임베딩 설정이 맞지 않습니다. 관리자가 색인을 재구축해야 합니다.")
    log.exception("처리하지 못한 오류")       # 자세한 내용은 서버 로그에만 남긴다
    return 500, ErrorResponse(code="internal", message="처리 중 문제가 생겼습니다. 잠시 뒤 다시 시도해 주세요.")


# ── 변환 ──────────────────────────────────────────────────────────────────

def summary(item: dict) -> ItemSummary:
    dist = item.get("distance") or {}
    return ItemSummary(id=item["id"], name=item["name"], name_en=item.get("name_en"), group=item["group"],
                       group_ko=GROUPS[item["group"]], kind=item.get("kind"), distance_ly=dist.get("ly"),
                       distance_km=dist.get("km"), ra_deg=item.get("ra_deg"), dec_deg=item.get("dec_deg"))


def detail(item: dict) -> ItemDetail:
    return ItemDetail(**summary(item).model_dump(), wiki_title=item["wiki_title"], attrs=item.get("attrs", {}),
                      distance=item.get("distance"), position_au=item.get("position_au"),
                      position_proxy=item.get("position_proxy"),
                      sources=[SourceRef(name=s["name"], url=s["url"], used_for=s.get("used_for"))
                               for s in item.get("sources", [])])


def cited_evidence(ev) -> CitedEvidence:
    body = ev.text.split("\n", 1)[1] if ev.text.startswith("[") and "\n" in ev.text else ev.text
    return CitedEvidence(number=ev.number, kind=ev.kind, source_type=ev.source_type, title=ev.title,
                         section=ev.section, url=ev.url, excerpt=body.strip()[:EXCERPT_CHARS])


def stats_out(stats: dict) -> FigureStats:
    return FigureStats(stars=stats["stars"], known=stats["known"],
                       nearest_hip=stats["nearest"]["hip"] if stats.get("nearest") else None,
                       farthest_hip=stats["farthest"]["hip"] if stats.get("farthest") else None,
                       spread_ly=stats.get("spread_ly"), ratio=stats.get("ratio"))


def generated_notice(status: str, cited: list) -> str | None:
    """특화 기능(편지 · 펼치기 · 하늘 안내)의 생성 결과 안내."""
    if status == "rejected":
        return REJECTED_NOTICE
    return None if cited else NO_CITATION


def sky_object(obj) -> SkyObjectOut:
    return SkyObjectOut(name=obj.name, item_id=obj.item_id, group=obj.group, alt_deg=obj.alt_deg,
                        az_deg=obj.az_deg, direction=obj.direction)


# 응답 캐시의 판 — 아래 값이 바뀌면 캐시 키가 달라져 예전 응답을 쓰지 않는다
CACHE_VERSION = 1
PROMPT_FILES = ("vasthorizon/rag/prompts.py", "vasthorizon/data/domain.py", "vasthorizon/data/perspective_library.py")


def cache_fingerprint(items: list[dict], ref_year: int) -> str:
    """모델 · effort · 프롬프트 파일 · 프롬프트 판(PROMPT_VERSIONS) · 항목 카탈로그의 해시."""
    from vasthorizon.config import get_settings
    cfg = get_settings().llm
    h = hashlib.sha256(json.dumps([CACHE_VERSION, cfg.provider, cfg.chat_model, cfg.anthropic_model, cfg.anthropic_fast_model,
                                   cfg.answer_effort, cfg.fast_effort, ref_year,
                                   PROMPT_VERSIONS]).encode())
    for name in PROMPT_FILES:
        path = PROJECT_ROOT / name
        h.update(path.read_bytes() if path.exists() else b"")
    h.update(json.dumps(items, ensure_ascii=False, sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def cacheable_answer(result) -> bool:
    """질의응답 결과를 캐시해도 되는가 — 근거 검증을 통과했고 수집 · 색인 · 검색이 모두 정상이며 경고가 없을 때만."""
    return (result.status in ("cited", "not_found") and not result.warnings
            and all(s.status in ("ok", "skipped") for s in result.stages.values()))


def has_live_evidence(result) -> bool:
    """근거에 '오늘 기준' 값(실시간 위치 · 거리, features/live_position.py — 기준일은 UTC)이 들어갔는가."""
    return any(ev.chunk_id.startswith("live:") for ev in result.evidences)


def answer_response(item: dict, result) -> AnswerResponse:
    if result.status == "rejected":
        notice = REJECTED_NOTICE
    elif not result.cited:
        notice = NOT_FOUND_NOTICE if result.status == "not_found" else NO_CITATION
    else:
        notice = None
    return AnswerResponse(
        item_id=item["id"], item_name=item["name"], question=result.question, answer=result.answer,
        status=result.status, cited=[cited_evidence(ev) for ev in result.cited], notice=notice,
        warnings=result.warnings,
        stages={name: StageInfo(status=s.status, seconds=round(s.seconds, 2)) for name, s in result.stages.items()},
    )


# ── 앱 ───────────────────────────────────────────────────────────────────

def create_app(services: Services | None = None, web_dir: Path | None = WEB_DIR) -> FastAPI:
    app = FastAPI(title="VastHorizon API", version="0.1",
                  description="근거와 함께 세상을 넓혀가는 우주 지식 서비스 — RAG 기반 질의응답 API")
    app.state.services = services
    init_lock = threading.Lock()

    def svc() -> Services:
        """첫 요청에서 한 번만 만든다. 동시에 들어온 첫 요청들도 같은 Services를 받는다."""
        if app.state.services is None:
            with init_lock:
                if app.state.services is None:
                    app.state.services = default_services()
        return app.state.services

    async def handle_error(request, error: Exception):
        status, body = error_payload(error)
        return JSONResponse(status_code=status, content=body.model_dump())

    # 예상한 오류는 개별 처리기로, 그 밖의 오류는 최상위 처리기로 (500 · 일반 안내 문구)
    for known in (ItemNotFoundError, ConversationBusyError, LetterUnavailableError, FigureUnavailableError,
                  SkyInputError, PerspectiveInputError, MissingApiKeyError, IndexMissingError, EmbeddingMismatchError,
                  ShareNotReadyError, ShareRefusedError, ShareUnavailableError):
        app.add_exception_handler(known, handle_error)
    app.add_exception_handler(Exception, handle_error)

    @app.exception_handler(RequestValidationError)
    async def handle_invalid(request, error: RequestValidationError):
        fields = sorted({".".join(str(p) for p in e["loc"][1:]) for e in error.errors()})
        return JSONResponse(status_code=422, content=ErrorResponse(
            code="invalid_request", message=f"요청 형식이 올바르지 않습니다: {', '.join(fields)}").model_dump())

    errors = {status: {"model": ErrorResponse} for status in (404, 409, 422, 429, 500, 502, 503)}

    # 공개 배포 — AI(LLM)를 실제로 부르는 처리기만 예산을 쓴다 (spend_ai). 경로 · 메서드로 세지 않는다:
    # 하늘 계산(guide=false) · 조회는 예산과 무관하게 늘 된다. 다른 주소의 프런트엔드(Cloudflare Pages 등)에는 CORS
    from vasthorizon.api.limits import RateLimitedError, RateLimiter, Verdict, client_key
    from vasthorizon.config import get_settings
    settings = get_settings()
    limiter = RateLimiter(settings.limits) if settings.limits.enabled else None
    app.state.limiter = limiter

    def spend_ai(request: Request) -> None:
        """AI 호출 한 번 — 하루 예산 · 한도를 넘으면 LLM을 부르기 전에 429. 요청 형식 검사를 통과한 뒤에만 센다.
        캐시 적중은 여기까지 오지 않는다 (예산 · 한도를 쓰지 않는다)."""
        budget, usage = settings.limits.daily_cost_usd, svc().usage
        if budget > 0 and usage is not None and usage.today_cost() >= budget:
            raise RateLimitedError(Verdict(False, usage_log.seconds_until_tomorrow(), "budget"))
        if limiter is None:
            return
        verdict = limiter.check(client_key(request))
        if not verdict.allowed:
            raise RateLimitedError(verdict)

    fingerprint: dict[str, str] = {}

    def cache_parts(parts) -> list | None:
        services = svc()
        if services.cache is None:
            return None
        if "value" not in fingerprint:
            fingerprint["value"] = cache_fingerprint(services.items, services.ref_year)
        return [fingerprint["value"], parts]

    def cache_get(namespace: str, parts) -> dict | None:
        """저장한 응답. 적중하면 사용량 기록에 캐시 적중 한 줄을 남긴다 (LLM 호출 없음)."""
        key = cache_parts(parts)
        hit = svc().cache.get(namespace, key) if key is not None else None
        if hit is not None and svc().usage is not None:
            with usage_log.feature(namespace):
                svc().usage.record_cache_hit(namespace)
        return hit

    def cache_put(namespace: str, parts, response, days: float, day_boundary: bool = False) -> None:
        """day_boundary=True면 days와 다음 UTC 자정 중 이른 때에 만료 (실시간 근거의 기준일이 UTC)."""
        key = cache_parts(parts)
        if key is not None and days > 0:
            svc().cache.put(namespace, key, response.model_dump(mode="json"), days, day_boundary=day_boundary)

    @app.exception_handler(RateLimitedError)
    async def handle_limited(request, error: RateLimitedError):
        return JSONResponse(status_code=429, headers={"Retry-After": str(error.verdict.retry_after), "Cache-Control": "no-store"},
                            content=ErrorResponse(code="rate_limited", message=str(error)).model_dump())
    if settings.server.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.server.cors_origins),
                           allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"], max_age=600)

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        services = svc()
        report = services.health()
        if services.share is not None:
            report = report.model_copy(update={"share": ShareInfo(count=services.share.count())})
        if services.tts is not None:
            report = report.model_copy(update={"tts": TtsInfo(**services.tts.status())})
        return report

    @app.get("/api/items", response_model=list[ItemSummary])
    def items(group: str | None = Query(None, description=" · ".join(GROUPS)),
              q: str | None = Query(None, max_length=50, description="이름 · 영문 이름 검색")) -> list[ItemSummary]:
        found = svc().items
        if group:
            found = [it for it in found if it["group"] == group]
        if q:
            needle = q.lower()
            found = [it for it in found if needle in it["name"].lower() or needle in (it.get("name_en") or "").lower()]
        return [summary(it) for it in found]

    @app.get("/api/items/{item_id}", response_model=ItemDetail, responses=errors)
    def item_detail(item_id: str) -> ItemDetail:
        return detail(svc().item(item_id))

    def begin(req: AskRequest) -> tuple[dict, Ticket]:
        """항목 확인 → 대화 처리권 받기. 없는 항목 · 처리 중인 대화는 여기서 404 · 409."""
        services = svc()
        item = services.item(req.item_id)
        return item, services.sessions.begin(req.session_id, req.item_id)

    def prepare_ask(req: AskRequest, request: Request) -> tuple[dict, Ticket, list | None, AnswerResponse | None]:
        """항목 · 처리권 → 캐시 조회 → (없으면) 예산 · 한도. 돌려주는 값: 항목 · 처리권 · 캐시 키 · 캐시 응답.
        대화 기록이 있는 질문은 캐시하지 않는다 (키 None)."""
        item, ticket = begin(req)
        try:
            parts = None if ticket.history else [item["id"], normalize_text(req.question), req.search_type]
            hit = cache_get("ask", parts) if parts is not None else None
            if hit is None:
                spend_ai(request)
                return item, ticket, parts, None
            hit.update(question=req.question, cached=True, recorded=True)
            return item, ticket, parts, AnswerResponse(**hit)
        except BaseException:
            svc().sessions.abort(ticket)
            raise

    def run_ask(req: AskRequest, item: dict, ticket: Ticket, parts: list | None = None, progress=None) -> AnswerResponse:
        """처리권(ticket)을 받은 질문을 끝까지 처리한다. 성공 · 실패 모두 처리 중 표시를 푼다."""
        sessions = svc().sessions
        try:
            history = [{"role": t["role"], "content": t["content"]} for t in ticket.history]
            with usage_log.feature("ask"):
                result = svc().ask(item, req.question, history=history, progress=progress, search_type=req.search_type)
            response = answer_response(item, result)
            if parts is not None and cacheable_answer(result):
                live = has_live_evidence(result)              # 오늘(UTC) 값 — 날짜가 바뀌면 다시 만든다
                cache_put("ask", parts, response, settings.cache.ask_live_days if live else settings.cache.ask_days,
                          day_boundary=live)
        except BaseException:
            sessions.abort(ticket)
            raise
        return record_turn(req, ticket, response)

    def record_turn(req: AskRequest, ticket: Ticket, response: AnswerResponse) -> AnswerResponse:
        sessions = svc().sessions
        response.recorded = sessions.finish(
            ticket,
            {"role": "user", "content": req.question},
            {"role": "assistant", "content": response.answer, "status": response.status,
             "cited": [c.model_dump() for c in response.cited]},
        )
        if not response.recorded:
            response.warnings.append(NOT_RECORDED_NOTICE)
        return response

    @app.post("/api/ask", response_model=AnswerResponse, responses=errors)
    def ask(req: AskRequest, request: Request) -> AnswerResponse:
        item, ticket, parts, hit = prepare_ask(req, request)
        if hit is not None:
            return record_turn(req, ticket, hit)
        return run_ask(req, item, ticket, parts)

    @app.post("/api/ask/stream", responses=errors,
              description="SSE 이벤트: progress {message} → result {AnswerResponse} 또는 error {code, message}. "
                          "없는 항목 · 처리 중인 대화는 스트림을 열기 전에 404 · 409. 캐시에 있는 답은 progress 없이 result만")
    def ask_stream(req: AskRequest, request: Request) -> StreamingResponse:
        item, ticket, parts, hit = prepare_ask(req, request)
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        if hit is not None:
            data = record_turn(req, ticket, hit).model_dump()
            return StreamingResponse(iter([f"event: result\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"]),
                                     media_type="text/event-stream", headers=headers)
        events: queue.Queue = queue.Queue()

        def worker() -> None:
            try:
                result = run_ask(req, item, ticket, parts,
                                 progress=lambda msg: events.put(("progress", {"message": msg})))
                events.put(("result", result.model_dump()))
            except Exception as e:  # 오류도 이벤트로 알린다 — 내용은 error_payload가 정리
                events.put(("error", error_payload(e)[1].model_dump()))
            finally:
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()

        def stream():
            while True:
                try:
                    event = events.get(timeout=KEEPALIVE_SECONDS)
                except queue.Empty:  # 임베딩 · 답변 생성처럼 긴 단계 — 연결이 끊기지 않게 주석 줄을 보낸다
                    yield ": keepalive\n\n"
                    continue
                if event is None:
                    return
                name, data = event
                yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)

    @app.get("/api/history/{item_id}", response_model=HistoryResponse, responses=errors)
    def history(item_id: str, session_id: str = Query(min_length=8, max_length=64)) -> HistoryResponse:
        svc().item(item_id)
        turns = svc().sessions.history(session_id, item_id)
        return HistoryResponse(item_id=item_id, turns=[HistoryTurn(**t) for t in turns])

    @app.delete("/api/history/{item_id}", status_code=204, responses=errors,
                description="기록을 지운다. 처리 중이던 질문은 답변은 돌려주되 기록하지 않는다 (recorded=false). "
                            "삭제 직후 새 질문은 바로 할 수 있다.")
    def clear_history(item_id: str, session_id: str = Query(min_length=8, max_length=64)) -> None:
        svc().item(item_id)
        svc().sessions.clear(session_id, item_id)

    @app.get("/api/items/{item_id}/intro", response_model=IntroResponse, responses=errors,
             description="천체를 내 세계에 담기 전에 읽는 소개 — 자체 위키 문서에서 발췌 (LLM 호출 없음, 캐시 우선)")
    def item_intro(item_id: str) -> IntroResponse:
        services = svc()
        r = services.intro(services.item(item_id))
        return IntroResponse(item_id=item_id, status=r["status"], sections=[IntroSection(**x) for x in r["sections"]],
                             title=r.get("title"), url=r.get("url"), license=r.get("license"),
                             source_type=r.get("source_type"), notice=r.get("notice"))

    @app.post("/api/explore", response_model=ExploreResponse, responses=errors)
    def explore(req: ExploreRequest, request: Request) -> ExploreResponse:
        # 이름만 있는 질문("베가") · 동의어 표로 완전히 해석되는 조건("고리가 있는 행성")은 LLM을 부르지 않는다 —
        # 예산 · 한도를 쓰지 않고, 데이터만으로 정해지므로 캐시하지도 않는다
        uses_ai = uses_llm(req.query, svc().items)
        parts = [normalize_text(req.query)]
        if uses_ai:
            hit = cache_get("explore", parts)
            if hit is not None:
                return ExploreResponse(**{**hit, "query": req.query, "cached": True})
            spend_ai(request)
        with usage_log.feature("explore"):
            result = svc().explore(req.query)
        notice = {"no_match": "조건에 맞는 항목을 찾지 못했습니다. 조건을 조금 넓혀 보세요.",
                  "failed": "조건과 대조하지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
                  "ask": "조건으로 찾는 질문이 아니라 특정 천체에 대한 질문입니다. 그 천체에게 물으면 문서 근거와 함께 답합니다.",
                  }.get(result.status)
        response = ExploreResponse(
            query=result.query, applied=result.applied, candidates=result.candidates, status=result.status,
            notice=notice, warnings=result.warnings,
            cards=[ExploreCardOut(item_id=c.item_id, name=c.name, group=c.group, kind=c.kind, reason=c.reason,
                                  source_url=c.source_url) for c in result.cards],
            mentioned=[ExploreMention(item_id=m["id"], name=m["name"], group=m["group"], kind=m.get("kind", ""))
                       for m in getattr(result, "mentioned", [])])
        if uses_ai and result.status != "failed" and not result.warnings:
            cache_put("explore", parts, response, settings.cache.explore_days)
        return response

    @app.post("/api/light-letter", response_model=LetterResponse, responses=errors,
              description="item_id 또는 age 중 하나만 보낸다. age면 나이(광년)와 거리가 가장 가까운 별의 편지")
    def light_letter(req: LetterRequest, request: Request) -> LetterResponse:
        if (req.item_id is None) == (req.age is None):
            raise LetterUnavailableError("천체(item_id)나 나이(age) 중 하나만 보내 주세요.")
        services = svc()
        gap = None
        if req.age is not None:
            item, gap = star_for_age(services.items, req.age)
        else:
            item = services.item(req.item_id)
        matched = dict(matched_age=req.age, age_gap_ly=round(gap, 2) if gap is not None else None)
        parts = [item["id"]]                         # 나이로 찾은 별도 같은 항목이면 같은 편지
        hit = cache_get("letter", parts)
        if hit is not None:
            return LetterResponse(**{**hit, **matched, "cached": True})
        spend_ai(request)
        with usage_log.feature("letter"):
            result = services.letter(item)
        d = result.departure
        notice = generated_notice(result.status, result.cited)
        response = LetterResponse(
            item_id=item["id"], item_name=item["name"], letter=result.letter, status=result.status,
            cited=[cited_evidence(ev) for ev in result.cited], notice=notice, warnings=result.warnings,
            **matched,
            departure=DepartureOut(light_years=d.light_years, light_time=d.light_time, year=d.year,
                                   year_label=d.year_label, era=d.era,
                                   year_range=list(d.year_range) if d.year_range else None, summary=d.summary()))
        if result.status in ("cited", "not_found") and not result.warnings:
            cache_put("letter", parts, response, settings.cache.letter_days)
        return response

    @app.get("/api/map", description="3D 우주 지도 — 방향(적도 좌표 단위 벡터) · 거리(km) · 배치 방식. LLM 호출 없음")
    def space_map() -> dict:
        services = svc()
        if services.map_cache is None:
            services.map_cache = {**map_points(services.items), "ref_year": services.ref_year}
        return services.map_cache

    @app.get("/api/constellations", description="별자리 88개의 선과 별 · 맨눈 별 [적경, 적위, 등급, 색지수] — 천구 · 펼치기 화면용")
    def constellations() -> dict:
        services = svc()
        return {"constellations": constellation_list(services.figures), "sky_stars": services.sky_stars,
                "licenses": LICENSES}

    @app.get("/api/constellations/{item_id}/figure", response_model=FigureResponse, responses=errors)
    def constellation_figure(item_id: str) -> FigureResponse:
        services = svc()
        figure = figure_for(services.item(item_id), services.figures)
        stars = sorted(figure["stars"].values(), key=lambda s: s["mag"])
        return FigureResponse(
            item_id=item_id, name=figure["name"], lines=figure["lines"], stats=stats_out(figure_stats(figure)),
            stars=[FigureStar(**{k: s.get(k) for k in FigureStar.model_fields}) for s in stars],
            licenses=LICENSES)

    @app.post("/api/constellations/{item_id}/unfold", response_model=UnfoldResponse, responses=errors)
    def constellation_unfold(item_id: str, request: Request) -> UnfoldResponse:
        services = svc()
        item = services.item(item_id)
        figure = figure_for(item, services.figures)
        hit = cache_get("unfold", [item_id])
        if hit is not None:
            return UnfoldResponse(**{**hit, "cached": True})
        spend_ai(request)
        with usage_log.feature("unfold"):
            result = services.unfold(item, figure)
        response = UnfoldResponse(
            item_id=item_id, name=item["name"], stats=stats_out(result.stats), explanation=result.explanation,
            status=result.status, cited=[cited_evidence(ev) for ev in result.cited],
            notice=generated_notice(result.status, result.cited), warnings=result.warnings)
        if result.status in ("cited", "not_found") and not result.warnings:
            cache_put("unfold", [item_id], response, settings.cache.unfold_days)
        return response

    @app.post("/api/sky", response_model=SkyResponse, responses=errors,
              description="위치 · 시각의 하늘에 뜬 별자리와 행성. guide=false면 계산만 (LLM 호출 없음)")
    def sky(req: SkyRequest, request: Request) -> SkyResponse:
        services = svc()
        view = compute_sky(services.items, services.figures, req.lat, req.lon, req.at)
        body = dict(lat=view.lat, lon=view.lon, at=view.at, sun_alt_deg=view.sun_alt_deg, is_night=view.is_night,
                    constellations=[sky_object(o) for o in view.constellations],
                    planets=[sky_object(o) for o in view.planets])
        if not req.guide:                               # 계산만 — AI 예산을 쓰지 않는다
            return SkyResponse(**body, status="skipped", warnings=view.notes)
        spend_ai(request)
        with usage_log.feature("sky"):
            result = services.sky_guide(view)
        notice = generated_notice(result.status, result.cited) if result.guide is not None else None
        return SkyResponse(**body, guide=result.guide, status=result.status,
                           cited=[cited_evidence(ev) for ev in result.cited], notice=notice,
                           warnings=result.warnings)

    @app.get("/api/perspective/themes", response_model=list[ThemeOut])
    def perspective_themes() -> list[ThemeOut]:
        return [ThemeOut(key=t.key, label=t.label, titles=list(t.titles)) for t in THEMES.values()]

    @app.post("/api/perspective", response_model=PerspectiveResponse, responses=errors,
              description="text(마음 한 줄) · theme(감정 버튼) 중 하나 이상. 위기 표현이면 답변 대신 상담 창구 안내")
    def perspective(req: PerspectiveRequest, request: Request) -> PerspectiveResponse:
        # 코드로 바로 판정되는 위기 표현 — 캐시 · 예산 · 한도보다 먼저 상담 창구 안내 (예산을 다 써도 막지 않는다)
        urgent = keyword_crisis(req.text)
        if urgent is not None:
            return perspective_response(urgent)
        parts = [text_hash(req.text) if req.text else None, req.theme]      # 사용자 문장은 해시로만 키에 쓴다
        hit = cache_get("perspective", parts)
        if hit is not None:
            return PerspectiveResponse(**{**hit, "cached": True})
        spend_ai(request)
        with usage_log.feature("perspective"):
            result = svc().perspective(req.text, req.theme)
        response = perspective_response(result)
        if result.status == "cited" and not result.warnings:        # 위기 · 확인 실패 · 근거 없음은 매번 다시 본다
            cache_put("perspective", parts, response, settings.cache.perspective_days)
        return response

    def perspective_response(result) -> PerspectiveResponse:
        crisis = result.status == "crisis"
        fixed = crisis or result.status in ("not_found", "unchecked")      # 정해진 안내 문구 — 인용 안내 없음
        notice = None if fixed else generated_notice(result.status, result.cited)
        response = PerspectiveResponse(
            status=result.status, answer=result.answer, crisis=crisis, themes=result.themes,
            cited=[cited_evidence(ev) for ev in result.cited],
            items=[RelatedItem(**it) for it in result.items], disclaimer=result.disclaimer,
            support=[SupportLine(**line) for line in result.support], notice=notice, warnings=result.warnings)
        return response

    # ── 편지 공유 ─────────────────────────────────────────────────────────
    # 캐시 적중만 공유한다 — 임의 내용을 대신 호스팅하지 않는다. AI 예산 · 한도는 쓰지 않고, 따로 IP당 분당 한도
    from vasthorizon import sharecard
    from vasthorizon.config import LimitsConfig
    share_limiter = RateLimiter(LimitsConfig(enabled=True, per_ip_per_minute=settings.share.per_ip_per_minute,
                                             per_ip_per_day=SHARE_PER_IP_PER_DAY, global_per_day=SHARE_GLOBAL_PER_DAY))
    app.state.share_limiter = share_limiter
    tts_limiter = RateLimiter(LimitsConfig(enabled=True, per_ip_per_minute=settings.tts.per_ip_per_minute,
                                           per_ip_per_day=TTS_PER_IP_PER_DAY, global_per_day=TTS_GLOBAL_PER_DAY))
    app.state.tts_limiter = tts_limiter
    public_base = settings.share.public_base

    def cached_response(namespace: str, parts) -> dict:
        """공유할 응답 — 서버 응답 캐시에 있어야 한다 (사용량 기록에 캐시 적중을 남기지 않는다)."""
        key = cache_parts(parts)
        hit = svc().cache.get(namespace, key) if key is not None else None
        if hit is None:
            raise ShareNotReadyError(namespace)
        return hit

    def share_links(record: dict) -> ShareResponse:
        sid = record["id"]
        return ShareResponse(id=sid, url=f"{public_base}/api/l/{sid}", image_url=f"{public_base}/api/l/{sid}.png",
                             tall_image_url=f"{public_base}/api/l/{sid}/tall.png",
                             tall_image_height=sharecard.tall_height(record),
                             audio_url=f"{public_base}/api/l/{sid}/audio.mp3" if tts_ready() else None,
                             created=record["created"])

    def tts_ready() -> bool:
        tts = svc().tts
        return tts is not None and tts.available

    @app.post("/api/share", status_code=201, response_model=ShareResponse, responses=errors,
              description="캐시에 있는 빛의 편지(item_id 또는 age) · 마음 한 줄(text · theme)을 공유 링크로. "
                          "캐시에 없으면 404 share_not_ready, 위기 안내 · 인용 규칙 위반은 409. 같은 내용이면 200과 기존 링크")
    def create_share(req: ShareRequest, request: Request, response: Response) -> ShareResponse:
        verdict = share_limiter.check(client_key(request))
        if not verdict.allowed:
            raise RateLimitedError(Verdict(False, verdict.retry_after, "share"))
        services = svc()
        store = services.share
        if store is None:
            raise ShareUnavailableError()
        if req.kind == "letter":
            if (req.item_id is None) == (req.age is None):
                raise LetterUnavailableError("천체(item_id)나 나이(age) 중 하나만 보내 주세요.")
            item = star_for_age(services.items, req.age)[0] if req.age is not None else services.item(req.item_id)
            content = letter_record(cached_response("letter", [item["id"]]), GROUPS.get(item.get("group"), "빛의 편지"))
        else:
            if req.text and keyword_crisis(req.text) is not None:          # 위기 표현 — 공유하지 않는다
                raise ShareRefusedError("crisis")
            # 사용자 문장은 캐시 키(해시)를 만드는 데만 쓴다 — 기록에는 답 · 주제 · 근거만
            content = perspective_record(cached_response("perspective", [text_hash(req.text) if req.text else None,
                                                                         req.theme]))
            if echoes(req.text, content["text"]):                          # 답이 사용자 문장을 되풀이 — 문장이 링크에 남는다
                raise ShareRefusedError("echo", "적어 주신 문장이 답에 들어 있어 공유할 수 없습니다")
        record, created = store.put(content)
        if created:
            # 미리보기 수집기 · 카카오톡이 오기 전에 이미지를 그려 둔다
            for variant, draw in (("", sharecard.share_image), ("tall", sharecard.share_tall_image)):
                try:
                    store.save_image(record["id"], draw(record), variant)
                except Exception:                           # 이미지는 요청할 때 다시 그린다 — 공유는 막지 않는다
                    log.exception("공유 이미지를 그리지 못했습니다")
        response.status_code = 201 if created else 200
        return share_links(record)

    def share_record(share_id: str) -> dict | None:
        store = svc().share
        return store.get(share_id) if store is not None else None

    def share_headers(record: dict, max_age: int) -> dict:
        """검색에 올리지 않고(X-Robots-Tag), 캐시는 만료 전까지만 — max-age = min(max_age, 남은 보관 시간)."""
        left = int(float(record.get("expires", 0)) - svc().share.clock())
        return {"Cache-Control": f"public, max-age={max(0, min(max_age, left))}", "X-Robots-Tag": "noindex, nofollow"}

    def share_missing() -> JSONResponse:
        return JSONResponse(status_code=404, content=ErrorResponse(
            code="share_not_found", message="이 편지는 만료되었거나 없는 주소입니다.").model_dump())

    # .json · .png를 먼저 — /api/l/{share_id}가 'abc.json'까지 받지 않게
    @app.api_route("/api/l/{share_id}.json", methods=["GET", "HEAD"], responses=errors,
                   description="저장한 공유 기록 그대로 (앱이 공유 링크를 열 때)")
    def share_json(share_id: str):
        record = share_record(share_id)
        if record is None:
            return share_missing()
        return JSONResponse(record, headers=share_headers(record, 3600))

    @app.api_route("/api/l/{share_id}.png", methods=["GET", "HEAD"], responses=errors,
                   description="1200×630 미리보기 이미지 (og:image). 처음 요청할 때 그려 디스크에 둔다")
    def share_png(share_id: str):
        return share_image_response(share_id, "", sharecard.share_image)

    @app.api_route("/api/l/{share_id}/tall.png", methods=["GET", "HEAD"], responses=errors,
                   description="편지 전체를 담은 세로형 카드 1080×(1620~1920) — 이미지로 저장 · 카카오톡 피드. "
                               "처음 요청할 때 그려 디스크에 둔다")
    def share_tall_png(share_id: str):
        return share_image_response(share_id, "tall", sharecard.share_tall_image)

    @app.api_route("/api/l/{share_id}/audio.mp3", methods=["GET", "HEAD"], responses=errors,
                   description="편지(제목 · 본문)를 Google Cloud TTS로 읽은 MP3. 처음 요청할 때 합성해 디스크에 둔다. "
                               "못 쓰면 503 tts_unavailable, 한도를 다 썼으면 503 tts_quota(reason · Retry-After), 합성 실패는 502 tts_failed "
                               "— 화면은 기기 음성(speechSynthesis)으로 읽는다. HEAD는 합성하지 않는다: 만들어 둔 MP3가 있으면 200, 없으면 202")
    def share_audio(share_id: str, request: Request):
        record = share_record(share_id)
        if record is None:
            return share_missing()
        tts = svc().tts
        if tts is None or not tts.available:
            return tts_error(503, "tts_unavailable", TTS_UNAVAILABLE_MESSAGE)
        text = record_text(record)
        data = tts.cached(text)
        if data is None and request.method == "HEAD":   # HEAD는 합성 · 한도를 건드리지 않는다 — 아직 없음
            return Response(status_code=202, headers={"Cache-Control": "no-store"})
        if data is None:                                # 캐시 적중은 한도에 세지 않는다
            verdict = tts_limiter.check(client_key(request))
            if not verdict.allowed:
                raise RateLimitedError(Verdict(False, verdict.retry_after, "tts"))
            try:
                with usage_log.feature("tts"):
                    data = tts.audio(text)
            except TtsQuotaError as e:
                return tts_error(503, "tts_quota", TTS_QUOTA_MESSAGES.get(e.reason, TTS_QUOTA_MESSAGE),
                                 {"Retry-After": str(e.retry_after)}, reason=e.reason)
            except TtsUnavailableError:                 # 꺼짐 · 읽을 글 없음 · 원장을 믿을 수 없음
                return tts_error(503, "tts_unavailable", TTS_UNAVAILABLE_MESSAGE)
            except TtsError:
                return tts_error(502, "tts_failed", "읽어 주기 음성을 만들지 못했어요 — 기기 음성으로 읽어 드립니다")
        return Response(data, media_type="audio/mpeg", headers=share_headers(record, 86400))

    def tts_error(status: int, code: str, message: str, headers: dict | None = None, reason: str | None = None) -> JSONResponse:
        content = ErrorResponse(code=code, message=message).model_dump()
        if reason:                                      # tts_quota — month · day · cooldown
            content["reason"] = reason
        return JSONResponse(status_code=status, headers={"Cache-Control": "no-store", **(headers or {})}, content=content)

    def share_image_response(share_id: str, variant: str, draw) -> Response:
        record = share_record(share_id)
        if record is None:
            return share_missing()
        store = svc().share
        path = store.image_path(share_id, variant)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            data = draw(record)
            try:
                store.save_image(share_id, data, variant)
            except OSError as e:
                log.warning("공유 이미지를 저장하지 못했습니다: %s", type(e).__name__)
        return Response(data, media_type="image/png", headers=share_headers(record, 86400))

    @app.api_route("/api/l/{share_id}", methods=["GET", "HEAD"], response_class=HTMLResponse,
                   description="공유 링크 — og:title · og:description · og:image가 있는 HTML. 없는 · 만료된 링크는 404 HTML")
    def share_html(share_id: str) -> HTMLResponse:
        record = share_record(share_id)
        if record is None:
            return HTMLResponse(sharecard.missing_page(public_base), status_code=404)
        return HTMLResponse(sharecard.share_page(record, public_base), headers=share_headers(record, 600))

    if web_dir and web_dir.exists():                    # 3D 프론트엔드 (9번 작업에서 추가)
        kakao_key = settings.share.kakao_js_key
        if kakao_key and not valid_kakao_key(kakao_key):
            log.warning("[share] kakao_js_key(KAKAO_JS_KEY)가 영문 · 숫자로만 된 키가 아니라 넣지 않습니다.")
        elif kakao_key:
            # 카카오 JavaScript 키는 저장소의 index.html에 적지 않는다 — 내보낼 때만 meta에 넣는다. 키가 없으면 StaticFiles 그대로
            index_path = web_dir / "index.html"

            @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
            @app.api_route("/index.html", methods=["GET", "HEAD"], include_in_schema=False)
            def index_page() -> HTMLResponse:
                html = inject_kakao_key(index_path.read_text(encoding="utf-8"), kakao_key)
                return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


app = create_app()
