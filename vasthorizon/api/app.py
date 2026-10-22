"""VastHorizon API 서버 (F2009 · F2012 · F2013).

    uvicorn vasthorizon.api.app:app --port 8000
    → http://localhost:8000/docs  (요청 · 응답 형식 문서)

| 메서드 · 경로                         | 역할                                             |
|---------------------------------------|--------------------------------------------------|
| GET  /api/health                      | 키 · 색인 상태와 화면 안내 (F2012)               |
| GET  /api/items                       | 항목 목록 (그룹 · 이름 필터)                     |
| GET  /api/items/{item_id}             | 항목 상세                                        |
| GET  /api/items/{item_id}/intro       | 천체 소개 — 자체 위키 문서 첫머리 · 역사 절 발췌   |
| POST /api/ask                         | 질문 → 근거 기반 답변 (F2007 · F2008)            |
| POST /api/ask/stream                  | 같은 질문을 진행 상태와 함께 SSE로 (F2012)       |
| GET  /api/history/{item_id}           | 항목별 대화 기록 (F2009)                         |
| DELETE /api/history/{item_id}         | 항목별 대화 기록 지우기                          |
| POST /api/explore                     | 자연어 조건으로 항목 찾기 (F2011)                |
| POST /api/light-letter                | 빛의 편지 — 천체 또는 나이로 (F2010)             |
| GET  /api/map                         | 3D 우주 지도 — 항목별 방향 · 거리 · 배치 방식    |
| GET  /api/constellations              | 별자리 88개의 선과 별 (천구 · 펼치기 화면)       |
| GET  /api/constellations/{id}/figure  | 별자리 선과 별들의 실제 거리 (3D 펼치기용)       |
| POST /api/constellations/{id}/unfold  | 별자리 펼치기 설명 — 근거 인용 (F2010)           |
| POST /api/sky                         | 오늘 밤 나의 하늘 — 위치 계산 + 안내 (F2010)     |
| GET  /api/perspective/themes          | 관점 전환 감정 버튼 (주제 · 서가 문서)           |
| POST /api/perspective                 | 관점 전환 — 위기 표현이면 상담 창구 안내 먼저    |

오류 응답은 {"code", "message"} 형식이다. 스택 트레이스 · 키 · 프롬프트는 내보내지 않는다. (NF2004)

동시성 정책
- 서비스 초기화: 첫 요청에서 한 번만 만든다 (잠금으로 보호). 모든 요청이 같은 Services를 쓴다.
- 대화(세션 + 항목)마다 한 번에 한 질문 — 처리 중이면 409 conversation_busy (sessions.py 참고).
  일반 질문과 SSE가 같은 begin · finish 절차를 쓴다. SSE는 스트림을 열기 전에 검사한다.
- 처리 중 기록 삭제: 그 질문의 답변은 돌려주되 recorded=false — 지운 기록에 다시 섞이지 않는다.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from vasthorizon.api.schemas import (
    AnswerResponse, AskRequest, CitedEvidence, DepartureOut, ErrorResponse, ExploreCardOut, ExploreRequest,
    ExploreResponse, FigureResponse, FigureStar, FigureStats, HealthResponse, HistoryResponse, HistoryTurn,
    IntroResponse, IntroSection,
    ItemDetail, ItemSummary, LetterRequest, LetterResponse, PerspectiveRequest, PerspectiveResponse,
    RelatedItem, SkyObjectOut, SkyRequest, SkyResponse, SourceRef,
    StageInfo, SupportLine, ThemeOut, UnfoldResponse,
)
from vasthorizon.api.services import ItemNotFoundError, Services, default_services
from vasthorizon.api.sessions import ConversationBusyError, Ticket
from vasthorizon.config import PROJECT_ROOT
from vasthorizon.data.constellation_figures import LICENSES, figure_stats
from vasthorizon.data.items.common import GROUPS
from vasthorizon.features.constellation import FigureUnavailableError, figure_for
from vasthorizon.data.perspective_library import THEMES
from vasthorizon.features.light_letter import LetterUnavailableError, star_for_age
from vasthorizon.features.perspective import PerspectiveInputError
from vasthorizon.features.sky import SkyInputError, compute_sky
from vasthorizon.features.space_map import constellation_list, map_points
from vasthorizon.llm import MissingApiKeyError
from vasthorizon.rag.retrieval import IndexMissingError
from vasthorizon.store.chroma import EmbeddingMismatchError

log = logging.getLogger(__name__)
WEB_DIR = PROJECT_ROOT / "web"

# Windows는 레지스트리 설정에 따라 .js를 text/plain으로 알려 주는데, 브라우저는 그 모듈 스크립트를 거부한다.
# 정적 파일의 형식을 운영체제 설정과 관계없이 고정한다.
for _ext, _type in ((".js", "text/javascript"), (".mjs", "text/javascript"), (".css", "text/css"), (".json", "application/json")):
    mimetypes.add_type(_type, _ext)
EXCERPT_CHARS = 200

NO_CITATION = "답변에 인용된 근거가 없습니다."
NOT_FOUND_NOTICE = "문서에서 확인되지 않아 인용된 근거가 없습니다."
REJECTED_NOTICE = "근거 번호 규칙을 지키는 답변을 만들지 못해 답변 대신 안내를 표시합니다."
NOT_RECORDED_NOTICE = "답변하는 동안 대화 기록이 지워져, 이 답변은 기록에 남지 않습니다."


# ── 오류 → 안내 (F2012 · NF2004) ───────────────────────────────────────────

def error_payload(error: Exception) -> tuple[int, ErrorResponse]:
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
    if isinstance(error, ConversationBusyError):
        return 409, ErrorResponse(code="conversation_busy",
                                  message="이 항목의 이전 질문에 아직 답하는 중입니다. 답변이 끝난 뒤 다시 질문해 주세요.")
    if isinstance(error, MissingApiKeyError):
        return 503, ErrorResponse(code="missing_key", message="AI 서비스 키(GMS_KEY)가 설정되지 않아 답할 수 없습니다.")
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
                  SkyInputError, PerspectiveInputError, MissingApiKeyError, IndexMissingError, EmbeddingMismatchError):
        app.add_exception_handler(known, handle_error)
    app.add_exception_handler(Exception, handle_error)

    @app.exception_handler(RequestValidationError)
    async def handle_invalid(request, error: RequestValidationError):
        fields = sorted({".".join(str(p) for p in e["loc"][1:]) for e in error.errors()})
        return JSONResponse(status_code=422, content=ErrorResponse(
            code="invalid_request", message=f"요청 형식이 올바르지 않습니다: {', '.join(fields)}").model_dump())

    errors = {status: {"model": ErrorResponse} for status in (404, 409, 422, 500, 503)}

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return svc().health()

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

    def run_ask(req: AskRequest, item: dict, ticket: Ticket, progress=None) -> AnswerResponse:
        """처리권(ticket)을 받은 질문을 끝까지 처리한다. 성공 · 실패 모두 처리 중 표시를 푼다."""
        sessions = svc().sessions
        try:
            history = [{"role": t["role"], "content": t["content"]} for t in ticket.history]
            result = svc().ask(item, req.question, history=history, progress=progress, search_type=req.search_type)
            response = answer_response(item, result)
        except BaseException:
            sessions.abort(ticket)
            raise
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
    def ask(req: AskRequest) -> AnswerResponse:
        item, ticket = begin(req)
        return run_ask(req, item, ticket)

    @app.post("/api/ask/stream", responses=errors,
              description="SSE 이벤트: progress {message} → result {AnswerResponse} 또는 error {code, message}. "
                          "없는 항목 · 처리 중인 대화는 스트림을 열기 전에 404 · 409")
    def ask_stream(req: AskRequest) -> StreamingResponse:
        item, ticket = begin(req)
        events: queue.Queue = queue.Queue()

        def worker() -> None:
            try:
                result = run_ask(req, item, ticket, progress=lambda msg: events.put(("progress", {"message": msg})))
                events.put(("result", result.model_dump()))
            except Exception as e:  # 오류도 이벤트로 알린다 — 내용은 error_payload가 정리
                events.put(("error", error_payload(e)[1].model_dump()))
            finally:
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()

        def stream():
            while (event := events.get()) is not None:
                name, data = event
                yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

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
             description="천체를 내 세상에 담기 전에 읽는 소개 — 자체 위키 문서에서 발췌 (LLM 호출 없음, 캐시 우선)")
    def item_intro(item_id: str) -> IntroResponse:
        services = svc()
        r = services.intro(services.item(item_id))
        return IntroResponse(item_id=item_id, status=r["status"], sections=[IntroSection(**x) for x in r["sections"]],
                             title=r.get("title"), url=r.get("url"), license=r.get("license"),
                             source_type=r.get("source_type"), notice=r.get("notice"))

    @app.post("/api/explore", response_model=ExploreResponse, responses=errors)
    def explore(req: ExploreRequest) -> ExploreResponse:
        result = svc().explore(req.query)
        notice = {"no_match": "조건에 맞는 항목을 찾지 못했습니다. 조건을 조금 넓혀 보세요.",
                  "failed": "조건과 대조하지 못했습니다. 잠시 뒤 다시 시도해 주세요."}.get(result.status)
        return ExploreResponse(
            query=result.query, applied=result.applied, candidates=result.candidates, status=result.status,
            notice=notice, warnings=result.warnings,
            cards=[ExploreCardOut(item_id=c.item_id, name=c.name, group=c.group, kind=c.kind, reason=c.reason)
                   for c in result.cards])

    @app.post("/api/light-letter", response_model=LetterResponse, responses=errors,
              description="item_id 또는 age 중 하나만 보낸다. age면 나이(광년)와 거리가 가장 가까운 별의 편지")
    def light_letter(req: LetterRequest) -> LetterResponse:
        if (req.item_id is None) == (req.age is None):
            raise LetterUnavailableError("천체(item_id)나 나이(age) 중 하나만 보내 주세요.")
        services = svc()
        gap = None
        if req.age is not None:
            item, gap = star_for_age(services.items, req.age)
        else:
            item = services.item(req.item_id)
        result = services.letter(item)
        d = result.departure
        notice = generated_notice(result.status, result.cited)
        return LetterResponse(
            item_id=item["id"], item_name=item["name"], letter=result.letter, status=result.status,
            cited=[cited_evidence(ev) for ev in result.cited], notice=notice, warnings=result.warnings,
            matched_age=req.age, age_gap_ly=round(gap, 2) if gap is not None else None,
            departure=DepartureOut(light_years=d.light_years, light_time=d.light_time, year=d.year,
                                   year_label=d.year_label, era=d.era,
                                   year_range=list(d.year_range) if d.year_range else None, summary=d.summary()))

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
    def constellation_unfold(item_id: str) -> UnfoldResponse:
        services = svc()
        item = services.item(item_id)
        result = services.unfold(item, figure_for(item, services.figures))
        return UnfoldResponse(
            item_id=item_id, name=item["name"], stats=stats_out(result.stats), explanation=result.explanation,
            status=result.status, cited=[cited_evidence(ev) for ev in result.cited],
            notice=generated_notice(result.status, result.cited), warnings=result.warnings)

    @app.post("/api/sky", response_model=SkyResponse, responses=errors,
              description="위치 · 시각의 하늘에 뜬 별자리와 행성. guide=false면 계산만 (LLM 호출 없음)")
    def sky(req: SkyRequest) -> SkyResponse:
        services = svc()
        view = compute_sky(services.items, services.figures, req.lat, req.lon, req.at)
        body = dict(lat=view.lat, lon=view.lon, at=view.at, sun_alt_deg=view.sun_alt_deg, is_night=view.is_night,
                    constellations=[sky_object(o) for o in view.constellations],
                    planets=[sky_object(o) for o in view.planets])
        if not req.guide:
            return SkyResponse(**body, status="skipped", warnings=view.notes)
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
    def perspective(req: PerspectiveRequest) -> PerspectiveResponse:
        result = svc().perspective(req.text, req.theme)
        crisis = result.status == "crisis"
        fixed = crisis or result.status in ("not_found", "unchecked")      # 정해진 안내 문구 — 인용 안내 없음
        notice = None if fixed else generated_notice(result.status, result.cited)
        return PerspectiveResponse(
            status=result.status, answer=result.answer, crisis=crisis, themes=result.themes,
            cited=[cited_evidence(ev) for ev in result.cited],
            items=[RelatedItem(**it) for it in result.items], disclaimer=result.disclaimer,
            support=[SupportLine(**line) for line in result.support], notice=notice, warnings=result.warnings)

    if web_dir and web_dir.exists():                    # 3D 프론트엔드 (9번 작업에서 추가)
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


app = create_app()
