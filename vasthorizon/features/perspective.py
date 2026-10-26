"""관점 전환 — 지금의 마음 한 줄을, 우주의 사실과 잇는다.

    마음 한 줄 / 감정 버튼
      ─① 코드: 위기 표현 검사 ───────────→ 위기면 상담 창구 안내 (LLM · 색인 · 예산 없이, keyword_crisis)
      ─② LLM: 위기 2차 확인 (글이 있을 때) ─→ 위기면 상담 창구 안내 · 확인 못 하면 unchecked
      ─③ 일반 입력 검증: 감정 버튼 값 · 서가 색인 준비 ─→ 여기서부터만 입력 · 준비 오류
      ─④ cosmos_perspective 검색 (주제의 서가 문서로 필터) → 근거 청크
      ─⑤ LLM: 근거 사실만으로 관점 넓히기 + 인용 검증 · 재생성 → 답변 + 이어서 볼 천체

위기 확인은 일반 기능의 입력 · 준비 상태와 분리한다 (관점 전환 리뷰 P1).
감정 버튼 값이 틀리거나 서가 색인이 없어도 위기 확인 ①②는 끝까지 실행된다.

안전
| 상황             | 동작                                                                 |
|------------------|----------------------------------------------------------------------|
| 모든 응답        | 고정 안내 "VastHorizon은 전문 심리상담을 대신하지 않습니다." + 상담 창구 |
| 위기 표현 (코드) | 서가 색인 · LLM 호출 전에 상담 창구 안내를 돌려준다                   |
| 위기 (LLM 분류)  | 우회적인 표현을 2차로 잡는다 — 답변을 만들지 않고 상담 창구 안내      |
|                  | crisis 값만 보고 판정한다. 주제 · 검색어 필드가 틀려도 위기 판정은 유지 |
| 2차 확인 실패    | 분류 모델을 쓸 수 없거나 crisis 값을 읽지 못함 → status="unchecked":  |
|                  | 답변을 만들지 않고, 감정 버튼 재시도와 상담 창구를 안내한다            |
|                  | ('위기 아님'과 '확인 못 함'을 섞지 않는다 — 확인 못 한 글에 답하지 않음) |
| 답변 규칙        | 진단 · 처방 · 조언 금지 · 근거 없는 위로 금지 · 사실은 근거로만        |

서가 문서는 항목별 문서 색인(cosmos_docs)과 섞지 않고 별도 컬렉션에 둔다.
항목 문서 재구축 · 연결 해제가 서가에 영향을 주지 않게 하기 위해서다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chromadb
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from vasthorizon.collect.collector import Collector, StepFailure
from vasthorizon.config import get_settings
from vasthorizon.data.domain import NOT_FOUND_SENTENCE
from vasthorizon.data.perspective_library import (
    CRISIS_MESSAGE, DISCLAIMER, LIBRARY_ITEM, SUPPORT_LINES, THEMES, is_crisis,
)
from vasthorizon.llm import MissingApiKeyError
from vasthorizon.rag.graph import default_chat_model, generate_validated
from vasthorizon.llm import API_ERRORS
from vasthorizon.rag.llm_json import JsonReplyError, invoke_json, json_chat_model, optional_field, string_list
from vasthorizon.rag.prompts import perspective_classify_messages, perspective_messages
from vasthorizon.rag.retrieval import KIND_DOC, Evidence, IndexMissingError
from vasthorizon.store import chroma
from vasthorizon.store.doc_index import DocIndexError, DocIndexReport, sync_item_docs
from vasthorizon.store.search import search

TOP_K = 4
MAX_TEXT = 300
MAX_THEMES = 2
ROLE_LIBRARY = "관점 전환 서가"
LLM_ERRORS = (JsonReplyError, *API_ERRORS)   # GMS · Claude 어느 쪽이든
CHECK_ERRORS = (*LLM_ERRORS, MissingApiKeyError)       # 2차 위기 확인을 끝내지 못한 경우
UNCHECKED_MESSAGE = ("지금은 마음 한 줄을 차분히 읽어 보지 못했어요. 잠시 뒤 다시 적어 주시거나, 감정 버튼으로 골라 주세요. "
                     "마음이 많이 힘들다면 아래 상담 창구가 24시간 열려 있습니다.")
LIBRARY_MISSING = "관점 전환 서가 색인이 없습니다. python -m scripts.index_perspective 를 실행하세요."


class PerspectiveInputError(ValueError):
    """마음 한 줄도, 감정 버튼도 없거나 알 수 없는 주제다."""


@dataclass
class PerspectiveResult:
    text: str
    status: str                       # cited · not_found · rejected · crisis · unchecked
    answer: str
    themes: list[str] = field(default_factory=list)
    cited: list[Evidence] = field(default_factory=list)
    evidences: list[Evidence] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)          # 이어서 볼 천체 {id, name}
    crisis_by: str | None = None      # keyword · classifier
    attempts: int = 0
    warnings: list[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER
    support: tuple = SUPPORT_LINES


def library_name() -> str:
    return get_settings().collections.perspective


# ── 서가 색인 ─────────────────────────────────────────────────────────────

def library_titles() -> list[str]:
    seen: dict[str, None] = {}
    for theme in THEMES.values():
        seen.update(dict.fromkeys(theme.titles))
    return list(seen)


def sync_library(embedding: Embeddings | None = None, db: chromadb.ClientAPI | None = None,
                 collector: Collector | None = None, rebuild: bool = False) -> tuple[DocIndexReport, list[StepFailure]]:
    """서가 문서를 받아(캐시 우선) cosmos_perspective와 맞춘다.

    받지 못한 문서의 기존 청크는 지우지 않는다 (항목 문서 색인과 같은 보호 규칙).
    rebuild는 모든 문서를 받은 뒤 임시 컬렉션에서 만들고 검증해 교체한다 — 하나라도 못 받으면 멈추고,
    어떤 실패에도 기존 서가 컬렉션은 그대로 남는다.
    """
    collector = collector or Collector()
    embedding = embedding or chroma.default_embedding()
    failures: list[StepFailure] = []
    docs = [d for d in (collector.fetch_wiki(t, failures) for t in library_titles()) if d is not None]
    if rebuild and failures:
        raise DocIndexError("서가 문서를 모두 받지 못해 재구축을 멈춥니다: " + ", ".join(f.message() for f in failures))
    themes_of = {t: [th.key for th in THEMES.values() if t in th.titles] for t in library_titles()}
    links = {d.doc_id: {"role": ROLE_LIBRARY, "query": " ".join(themes_of.get(d.title, []))} for d in docs}
    name, cfg = library_name(), get_settings().chunking
    db = chroma.db_for(name, db)
    with chroma.LOCK:
        if not rebuild:
            collection = chroma.open_collection(name, embedding, db)
            failed_titles = {f.target for f in failures}
            missing = [m["doc_id"] for m in collection.get(include=["metadatas"])["metadatas"]
                       if m.get("title") in failed_titles]
            report = sync_item_docs(LIBRARY_ITEM, docs, links, collection, embedding,
                                    cfg.chunk_size, cfg.chunk_overlap, missing)
        else:                     # 임시 컬렉션에서 만들고 검증한 뒤 교체 — 실패해도 기존 서가는 남는다
            staging = chroma.staging_name(name)
            chroma.drop_collection(staging, db)
            try:
                collection = chroma.open_collection(staging, embedding, db)
                report = sync_item_docs(LIBRARY_ITEM, docs, links, collection, embedding,
                                        cfg.chunk_size, cfg.chunk_overlap)
                if report.invalid or collection.count() != report.chunks:
                    raise DocIndexError(f"서가 재구축 검증 실패 — 본문 없음 {report.invalid}, "
                                        f"색인 {collection.count()}개 / 기대 {report.chunks}개")
            except BaseException:
                chroma.drop_collection(staging, db)
                raise
            chroma.swap_in(name, db)
    return report, failures


# ── 관점 전환 ─────────────────────────────────────────────────────────────

def crisis_signal(data: dict) -> bool:
    """2차 위기 판정 — crisis 값만 본다. 참거짓이 아니면 확인 실패(JsonReplyError)."""
    crisis = data.get("crisis")
    if not isinstance(crisis, bool):
        raise JsonReplyError("crisis 필드가 참거짓이 아닙니다")
    return crisis


def search_hints(data: dict, text: str) -> tuple[list[str], str]:
    """검색용 부가 정보 (주제 키 · 검색어). 위기가 아닐 때만 읽는다. 알 수 없는 주제 키는 버린다."""
    themes = [k for k in string_list(data, "themes", MAX_THEMES * 2) if k in THEMES][:MAX_THEMES]
    query = optional_field(data, "query", (str,)) or text
    return themes, query


def crisis_result(text: str, by: str) -> PerspectiveResult:
    return PerspectiveResult(text=text, status="crisis", answer=CRISIS_MESSAGE, crisis_by=by)


def keyword_crisis(text: str | None) -> PerspectiveResult | None:
    """① 코드 위기 검사만 — 색인 · LLM · 예산 없이 바로 판정한다. 위기 표현이면 상담 창구 안내 결과, 아니면 None.

    API(app.py)는 이것을 캐시 · 예산 · 호출 한도보다 먼저 부른다 — 예산을 다 쓴 뒤에도 위기 안내는 막지 않는다.
    """
    text = (text or "").strip()[:MAX_TEXT]
    return crisis_result(text, "keyword") if text and is_crisis(text) else None


def unchecked_result(text: str) -> PerspectiveResult:
    return PerspectiveResult(text=text, status="unchecked", answer=UNCHECKED_MESSAGE,
                             warnings=["위기 여부를 확인하지 못해 답변을 만들지 않았습니다."])


def related_items(themes: list[str], items: list[dict]) -> list[dict]:
    by_name = {it["name"]: it for it in items}
    picked: dict[str, dict] = {}
    for key in themes:
        for name in THEMES[key].items:
            if name in by_name:
                picked.setdefault(by_name[name]["id"], {"id": by_name[name]["id"], "name": name})
    return list(picked.values())


def perspective(text: str | None = None, theme: str | None = None, items: list[dict] | None = None,
                llm: BaseChatModel | None = None, json_llm: BaseChatModel | None = None,
                embedding: Embeddings | None = None, db: chromadb.ClientAPI | None = None) -> PerspectiveResult:
    text = (text or "").strip()[:MAX_TEXT]
    if not text and not theme:
        raise PerspectiveInputError("마음 한 줄을 적거나 감정 버튼을 골라 주세요.")

    # ① 코드 위기 검사 — 다른 어떤 처리보다 먼저 (감정 버튼 검증 · 색인 · LLM 없이)
    if (urgent := keyword_crisis(text)) is not None:
        return urgent

    # ② 2차 위기 확인 — 글이 있으면 서가 준비 상태와 관계없이 먼저. 버튼만 누른 경우 호출 없음
    warnings: list[str] = []
    found: list[str] = []
    query = text
    if text:
        try:
            data = invoke_json(json_llm or json_chat_model(), perspective_classify_messages(text, THEMES),
                               purpose="perspective.classify")
            crisis = crisis_signal(data)
        except CHECK_ERRORS:
            return unchecked_result(text)
        if crisis:
            return crisis_result(text, "classifier")          # 주제 · 검색어 필드는 보지 않는다
        try:
            found, query = search_hints(data, text)
        except JsonReplyError:
            warnings.append("마음 한 줄의 주제를 분류하지 못해 서가 전체에서 찾았습니다.")

    # ③ 일반 입력 · 준비 상태 — 위기 확인을 마친 뒤에만 오류를 낸다
    if theme is not None and theme not in THEMES:
        raise PerspectiveInputError(f"알 수 없는 주제입니다: {theme}")
    name = library_name()
    if chroma.collection_count(name, db) == 0:
        raise IndexMissingError(LIBRARY_MISSING)
    themes = list(dict.fromkeys([*([theme] if theme else []), *found]))[:MAX_THEMES]
    query = query or THEMES[theme].query
    titles = [t for key in themes for t in THEMES[key].titles] or library_titles()

    # ④ 서가 검색 — 주제의 문서로 범위를 좁힌다
    embedding = embedding or chroma.default_embedding()
    rcfg = get_settings().retrieval
    with chroma.LOCK:
        outcome = search(name, query, embedding, db, k=TOP_K, where={"title": {"$in": titles}},
                         search_type="mmr", fetch_k=rcfg.mmr_fetch_k, lambda_mult=rcfg.mmr_lambda)
    evidences = [Evidence(number=i, chunk_id=h.id, kind=KIND_DOC, source_type=h.metadata["source_type"],
                          title=h.metadata["title"], section=h.metadata.get("section", ""),
                          url=h.metadata.get("source_url", ""), text=h.text)
                 for i, h in enumerate(outcome.hits, 1)]
    related = related_items(themes, items or [])
    if not evidences:
        warnings.append("서가에서 이어 줄 문서를 찾지 못했습니다.")
        return PerspectiveResult(text=text, status="not_found", answer=NOT_FOUND_SENTENCE, themes=themes,
                                 items=related, warnings=warnings)

    # ⑤ 근거 사실만으로 관점 넓히기 — 질의응답과 같은 인용 검증 · 재생성
    # 버튼만 눌렀을 때는 사용자 글이 없다 — 라벨을 마음 한 줄처럼 넘기면 첫 문장이 어색해지므로 준비한 opening을 그대로 쓰게 한다
    # 이어 주는 결은 버튼이면 그 주제, 글이면 분류된 첫 주제의 것 (주제가 없으면 넘기지 않는다)
    bridge = THEMES[themes[0]].bridge if themes else None
    if text:
        messages = perspective_messages(text, evidences, bridge=bridge)
    else:
        messages = perspective_messages(f"(버튼) {THEMES[theme].label}", evidences, opening=THEMES[theme].opening,
                                        bridge=bridge)
    result = generate_validated(default_chat_model(llm), messages,
                                evidences, purpose="perspective.answer")
    warnings += result["notes"]                  # 언어 혼입 등 — 답은 내보내되 알린다
    if result["status"] == "rejected":
        warnings.append("답변이 인용 규칙을 두 번 어겨 내보내지 않았습니다.")
    return PerspectiveResult(text=text, status=result["status"], answer=result["answer"], themes=themes,
                             cited=result["cited"], evidences=evidences, items=related,
                             attempts=result["attempts"], warnings=warnings)
