"""조건 기반 항목 탐색 (F2011).

    자연어 조건 ─(LLM: 필터 추출)→ 메타데이터 필터 + 의미 검색어
               ─(cosmos_items 검색, 필터 적용)→ 후보 N건
               ─(LLM: 후보 메타데이터만 보고 선별)→ 조건에 맞는 항목 카드

- 숫자 · 참거짓 조건(거리 · 빛의 출발 연도 · 맨눈 관측 · 계절 …)은 의미 검색이 약하다.
  ("맨눈으로 볼 수 있는 은하"에 '눈'이 들어간 9등급 은하가 1위로 나오는 식)
  그래서 LLM이 조건을 메타데이터 필터로 바꾸고, 검색 단계에서 필터로 먼저 거른다.
- 감성 표현은 검증 가능한 속성으로만 바꾼다. 취향 추천으로 흐르지 않게 하려는 장치다.
- 선별 단계에서 후보에 없는 ID는 버린다. 선별이 실패하면 결과 대신 실패를 알린다.

특정 천체에 대한 사실 질문 ("안드로메다 은하 가운데 블랙홀 이름은?")
- 조건 탐색은 조건으로 천체 목록을 찾는 기능이라, 이런 질문은 조건으로 바꿀 수 없어 '찾지 못함'이 됐다.
- 질문에 나온 카탈로그 천체 이름을 코드로 찾고(mentioned_items, LLM 없음), 필터 추출 응답의 asks_fact로
  '그 천체에 대한 사실 질문'인지 함께 판단한다 (추가 LLM 호출 없음).
- 사실 질문이면 검색하지 않고 status="ask" — 화면은 그 천체에게 같은 질문을 하는 버튼을 보여 준다 (질의응답 · 근거).
- 조건 탐색이어도 이름이 나왔으면 mentioned로 함께 돌려준다 ("안드로메다 은하보다 가까운 은하").

상태 구분
- 항목 색인이 없거나 비어 있음 → IndexMissingError (준비 오류, LLM 호출 없음)
- 색인은 있지만 조건에 맞는 후보가 없거나, 후보 중 조건에 맞는 것이 없음 → status="no_match"
- 선별 응답을 읽지 못함 → status="failed"
- 특정 천체에 대한 사실 질문 → status="ask" (mentioned에 그 천체)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import chromadb
import openai
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from vasthorizon.config import get_settings
from vasthorizon.data.item_text import CATEGORIES, display_name, year_text
from vasthorizon.data.items.common import GROUPS
from vasthorizon.rag.llm_json import JsonReplyError, invoke_json, json_chat_model, optional_field, string_list
from vasthorizon.rag.prompts import explore_filter_messages, explore_select_messages
from vasthorizon.rag.retrieval import IndexMissingError
from vasthorizon.store import chroma
from vasthorizon.store.search import search

MAX_RESULTS = 8
SEASONS = ("봄", "여름", "가을", "겨울")
LLM_ERRORS = (JsonReplyError, openai.APIError)


@dataclass
class Filters:
    semantic_query: str
    categories: list[str] | None = None       # 은하 · 성운 · 탐사선 … (item_text.CATEGORIES)
    group: str | None = None
    naked_eye: bool | None = None
    korean: bool | None = None
    season: str | None = None
    ecliptic: bool | None = None
    distance_ly_min: float | None = None
    distance_ly_max: float | None = None
    departure_year_min: int | None = None
    departure_year_max: int | None = None
    asks_fact: bool = False                   # 조건 탐색이 아니라 특정 천체에 대한 사실 질문인가

    def where(self) -> dict | None:
        """Chroma 메타데이터 조건식. 조건이 없으면 None."""
        clauses = []
        if self.categories:
            clauses.append({"category": {"$in": self.categories}})
        for key, value in (("group", self.group), ("naked_eye", self.naked_eye), ("korean", self.korean),
                           ("season", self.season), ("ecliptic", self.ecliptic)):
            if value is not None:
                clauses.append({key: {"$eq": value}})
        for key, low, high in (("distance_ly", self.distance_ly_min, self.distance_ly_max),
                               ("light_departure_year", self.departure_year_min, self.departure_year_max)):
            if low is not None:
                clauses.append({key: {"$gte": low}})
            if high is not None:
                clauses.append({key: {"$lte": high}})
        if not clauses:
            return None
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

    def describe(self) -> list[str]:
        """화면에 보여줄 적용 조건 — 사용자가 해석 결과를 확인할 수 있게."""
        out = []
        if self.categories:
            out.append(f"종류: {' · '.join(self.categories)}")
        if self.group:
            out.append(f"분류: {GROUPS[self.group]}")
        for label, value in (("맨눈 관측", self.naked_eye), ("한국 관련", self.korean), ("황도 별자리", self.ecliptic)):
            if value is not None:
                out.append(f"{label}: {'예' if value else '아니오'}")
        if self.season:
            out.append(f"관측 계절: {self.season}")
        if self.distance_ly_min is not None or self.distance_ly_max is not None:
            out.append(f"거리: {self.distance_ly_min or 0:g} ~ {self.distance_ly_max if self.distance_ly_max is not None else '∞'} 광년")
        if self.departure_year_min is not None or self.departure_year_max is not None:
            low = year_text(self.departure_year_min) if self.departure_year_min is not None else "…"
            high = year_text(self.departure_year_max) if self.departure_year_max is not None else "…"
            out.append(f"빛이 출발한 해: {low} ~ {high}")
        return out


def parse_filters(data: dict, query: str) -> Filters:
    """LLM이 낸 필터를 검증한다. 타입이 틀리거나 허용되지 않은 값이면 JsonReplyError."""
    semantic = optional_field(data, "semantic_query", (str,)) or query
    categories = None
    if data.get("categories") is not None:
        categories = string_list(data, "categories", len(CATEGORIES))
        unknown = [c for c in categories if c not in CATEGORIES]
        if unknown:
            raise JsonReplyError(f"알 수 없는 categories: {unknown}")
        categories = categories or None
    group = optional_field(data, "group", (str,))
    if group is not None and group not in GROUPS:
        raise JsonReplyError(f"알 수 없는 group: {group}")
    season = optional_field(data, "season", (str,))
    if season is not None and season not in SEASONS:
        raise JsonReplyError(f"알 수 없는 season: {season}")
    nums = {k: optional_field(data, k, (int, float)) for k in
            ("distance_ly_min", "distance_ly_max", "departure_year_min", "departure_year_max")}
    for low, high in (("distance_ly_min", "distance_ly_max"), ("departure_year_min", "departure_year_max")):
        if nums[low] is not None and nums[high] is not None and nums[low] > nums[high]:
            raise JsonReplyError(f"{low}가 {high}보다 큽니다.")
    return Filters(
        semantic_query=semantic.strip()[:200] or query, categories=categories, group=group, season=season,
        naked_eye=optional_field(data, "naked_eye", (bool,)), korean=optional_field(data, "korean", (bool,)),
        ecliptic=optional_field(data, "ecliptic", (bool,)),
        distance_ly_min=nums["distance_ly_min"], distance_ly_max=nums["distance_ly_max"],
        departure_year_min=int(nums["departure_year_min"]) if nums["departure_year_min"] is not None else None,
        departure_year_max=int(nums["departure_year_max"]) if nums["departure_year_max"] is not None else None,
        asks_fact=bool(optional_field(data, "asks_fact", (bool,))),
    )


@dataclass
class ExploreCard:
    item_id: str
    name: str
    group: str
    kind: str
    reason: str                  # 조건과 맞는 메타데이터 속성 (LLM이 후보 메타데이터에서 고른 문장)


@dataclass
class ExploreResult:
    query: str
    applied: list[str]           # 적용한 조건 (사람이 읽는 문장)
    cards: list[ExploreCard]
    candidates: int              # 필터 · 의미 검색으로 모은 후보 수
    status: str                  # ok · no_match · failed · ask
    warnings: list[str] = field(default_factory=list)
    mentioned: list[dict] = field(default_factory=list)   # 질문에 이름이 나온 천체 [{id, name, group, kind}]


# ── 질문에 나온 천체 이름 ──────────────────────────────────────────────────

_JOSA = ("에서", "까지", "보다", "에게", "한테", "으로", "이란", "이야", "은", "는", "이", "가", "의", "에", "을", "를",
         "과", "와", "도", "로", "만", "란", "야")
_WORD = "가-힣A-Za-z0-9"


def _name_pattern(name: str) -> re.Pattern:
    """이름 앞은 낱말 경계, 뒤는 경계나 조사 — '달'이 '달라'에, '태양'이 '태양계'에 걸리지 않게. 띄어쓰기는 무시."""
    body = r"\s*".join(re.escape(ch) for ch in name if not ch.isspace())
    josa = "|".join(_JOSA)
    return re.compile(rf"(?<![{_WORD}])({body})(?=$|[^{_WORD}]|(?:{josa})(?:$|[^{_WORD}]))", re.IGNORECASE)


def mentioned_items(query: str, items: list[dict], limit: int = 3) -> list[dict]:
    """질문에 이름(한국어 · 영어)이 나온 카탈로그 천체. 긴 이름부터, 겹치는 자리는 한 번만, 질문에 나온 순서로. LLM 없음."""
    names = [(name, it) for it in items for name in {display_name(it["name"]), it.get("name_en") or ""} if name.strip()]
    names.sort(key=lambda x: -len(x[0].replace(" ", "")))
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, dict]] = []
    for name, it in names:
        for m in _name_pattern(name).finditer(query):
            span = m.span(1)
            if any(a < span[1] and span[0] < b for a, b in taken) or any(f["id"] == it["id"] for _, f in found):
                continue
            taken.append(span)
            found.append((span[0], {"id": it["id"], "name": display_name(it["name"]), "group": it["group"],
                                    "kind": it.get("kind") or ""}))
    return [f for _, f in sorted(found, key=lambda x: x[0])][:limit]


def _selected(data: dict, valid: set[str], limit: int) -> list[tuple[str, str]]:
    """선별 응답 검증 — [{"id", "reason"}] 배열. 후보 밖 ID · 중복은 버린다."""
    rows = data.get("selected")
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise JsonReplyError("'selected'는 객체 배열이어야 합니다.")
    picked, seen = [], set()
    for row in rows:
        cid, reason = row.get("id"), row.get("reason", "")
        if not isinstance(cid, str) or not isinstance(reason, str):
            raise JsonReplyError("'selected' 원소의 id · reason은 문자열이어야 합니다.")
        if cid in valid and cid not in seen:
            seen.add(cid)
            picked.append((cid, reason.strip()))
    return picked[:limit]


def explore(query: str, llm: BaseChatModel | None = None, embedding: Embeddings | None = None,
            db: chromadb.ClientAPI | None = None, max_results: int = MAX_RESULTS,
            items: list[dict] | None = None) -> ExploreResult:
    settings = get_settings()
    # 0. 색인 준비 상태 — 없거나 비어 있으면 '조건 불일치'가 아니라 준비 오류다 (LLM 호출 전에 확인)
    if chroma.collection_count(settings.collections.items, db) == 0:
        raise IndexMissingError("항목 색인이 없어 조건 탐색을 할 수 없습니다. python -m scripts.index_items 를 실행하세요.")
    llm = llm or json_chat_model()
    embedding = embedding or chroma.default_embedding()
    warnings: list[str] = []
    mentioned = mentioned_items(query, items or [])

    # 1. 조건 → 필터 (특정 천체에 대한 사실 질문인지도 함께 판단)
    try:
        filters = parse_filters(invoke_json(llm, explore_filter_messages(query)), query)
    except LLM_ERRORS:
        filters = Filters(semantic_query=query)
        warnings.append("조건을 필터로 해석하지 못해 의미 검색만 했습니다. 숫자 · 계절 같은 조건은 덜 정확할 수 있습니다.")
    if filters.asks_fact and mentioned:
        return ExploreResult(query=query, applied=[], cards=[], candidates=0, status="ask", warnings=warnings,
                             mentioned=mentioned)

    # 2. 필터 + 의미 검색 → 후보 (검증된 검색 — store/search.py)
    with chroma.LOCK:
        hits = search(settings.collections.items, filters.semantic_query, embedding, db,
                      k=settings.retrieval.item_candidates, where=filters.where()).hits
    candidates = [(h.metadata["item_id"], h.text) for h in hits]
    if not candidates:
        return ExploreResult(query=query, applied=filters.describe(), cards=[], candidates=0,
                             status="no_match", warnings=warnings, mentioned=mentioned)

    # 3. 후보 메타데이터만 보고 선별
    try:
        data = invoke_json(llm, explore_select_messages(query, candidates, max_results))
        picked = _selected(data, {cid for cid, _ in candidates}, max_results)
    except LLM_ERRORS:
        warnings.append("후보를 조건과 대조하지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
        return ExploreResult(query=query, applied=filters.describe(), cards=[], candidates=len(candidates),
                             status="failed", warnings=warnings, mentioned=mentioned)

    meta = {h.metadata["item_id"]: h.metadata for h in hits}
    cards = [ExploreCard(item_id=cid, name=meta[cid]["name"], group=meta[cid]["group"],
                         kind=meta[cid].get("kind", ""), reason=reason) for cid, reason in picked]
    return ExploreResult(query=query, applied=filters.describe(), cards=cards, candidates=len(candidates),
                         status="ok" if cards else "no_match", warnings=warnings, mentioned=mentioned)
