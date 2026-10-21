"""VastHorizon API 서버 (F2009 · F2012 · F2013).

    uvicorn vasthorizon.api.app:app --port 8000
    → http://localhost:8000/docs  (요청 · 응답 형식 문서)

| 메서드 · 경로                         | 역할                                             |
|---------------------------------------|--------------------------------------------------|
| GET  /api/health                      | 키 · 색인 상태와 화면 안내 (F2012)               |
| GET  /api/items                       | 항목 목록 (그룹 · 이름 필터)                     |
| GET  /api/items/{item_id}             | 항목 상세                                        |
| POST /api/ask                         | 질문 → 근거 기반 답변 (F2007 · F2008)            |
| POST /api/ask/stream                  | 같은 질문을 진행 상태와 함께 SSE로 (F2012)       |
| GET  /api/history/{item_id}           | 항목별 대화 기록 (F2009)                         |
| DELETE /api/history/{item_id}         | 항목별 대화 기록 지우기                          |

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
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from vasthorizon.api.schemas import (
    AnswerResponse, AskRequest, CitedEvidence, ErrorResponse, HealthResponse, HistoryResponse, HistoryTurn,
    ItemDetail, ItemSummary, SourceRef, StageInfo,
)
from vasthorizon.api.services import ItemNotFoundError, Services, default_services
from vasthorizon.api.sessions import ConversationBusyError, Ticket
from vasthorizon.config import PROJECT_ROOT
from vasthorizon.data.items.common import GROUPS
from vasthorizon.llm import MissingApiKeyError
from vasthorizon.rag.retrieval import IndexMissingError
from vasthorizon.store.chroma import EmbeddingMismatchError

log = logging.getLogger(__name__)
WEB_DIR = PROJECT_ROOT / "web"
EXCERPT_CHARS = 200

NO_CITATION = "답변에 인용된 근거가 없습니다."
NOT_FOUND_NOTICE = "문서에서 확인되지 않아 인용된 근거가 없습니다."
REJECTED_NOTICE = "근거 번호 규칙을 지키는 답변을 만들지 못해 답변 대신 안내를 표시합니다."
NOT_RECORDED_NOTICE = "답변하는 동안 대화 기록이 지워져, 이 답변은 기록에 남지 않습니다."


# ── 오류 → 안내 (F2012 · NF2004) ───────────────────────────────────────────

def error_payload(error: Exception) -> tuple[int, ErrorResponse]:
    if isinstance(error, ItemNotFoundError):
        return 404, ErrorResponse(code="item_not_found", message="선택한 항목을 찾을 수 없습니다.")
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
    for known in (ItemNotFoundError, ConversationBusyError, MissingApiKeyError, IndexMissingError,
                  EmbeddingMismatchError):
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

    if web_dir and web_dir.exists():                    # 3D 프론트엔드 (9번 작업에서 추가)
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


app = create_app()
