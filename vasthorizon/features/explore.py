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

이름 질의 ("베가", "베텔게우스와 시리우스")
- 질문이 카탈로그 천체 이름만으로 이루어져 있으면 LLM을 부르지 않고 그 천체를 카드로 돌려준다 (status="ok").
  카드가 곧 그 천체로 이어지므로 mentioned는 비운다 (화면에 '이 천체에게 질문하기'를 내지 않는다).
  조건 선별 결과가 비었어도 이름이 나왔으면 마찬가지다. 선별 카드가 있으면 이름이 나온 천체를 맨 앞에 둔다.

성군 · 별 묶음 ("여름 삼각형", "오리온의 허리띠")
- 카탈로그에는 성군 항목이 없다. 별칭 표(data/asterisms.py)로 구성 천체를 찾아 mentioned에 넣는다 (LLM 없음).
- 표에 없는 묶음은 필터 추출 응답의 members(구성 천체 이름)를 카탈로그 이름과 대조해 카드로 더한다.
  카탈로그에 없는 이름은 버린다.

상태 구분
- 항목 색인이 없거나 비어 있음 → IndexMissingError (준비 오류, LLM 호출 없음)
- 색인은 있지만 조건에 맞는 후보가 없거나, 후보 중 조건에 맞는 것이 없음 → status="no_match"
  (질문에 나온 천체 · 묶음의 구성 천체가 있으면 그것을 카드로 돌려주고 status="ok")
- 선별 응답을 읽지 못함 → status="failed" (이름이 나온 천체가 있으면 그 카드와 경고로 status="ok")
- 특정 천체에 대한 사실 질문 → status="ask" (mentioned에 그 천체)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import chromadb
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from vasthorizon.config import get_settings
from vasthorizon.data.asterisms import asterism_aliases, asterism_members
from vasthorizon.data.item_text import CATEGORIES, display_name, year_text
from vasthorizon.data.items.common import GROUPS
from vasthorizon.llm import API_ERRORS
from vasthorizon.rag.llm_json import JsonReplyError, invoke_json, json_chat_model, optional_field, string_list
from vasthorizon.rag.prompts import explore_filter_messages, explore_select_messages
from vasthorizon.rag.retrieval import IndexMissingError
from vasthorizon.store import chroma
from vasthorizon.store.search import search

MAX_RESULTS = 8
MAX_MEMBERS = 12                              # LLM이 적은 묶음 구성 천체 이름 (더 많으면 자른다)
SEASONS = ("봄", "여름", "가을", "겨울")
LLM_ERRORS = (JsonReplyError, *API_ERRORS)   # GMS · Claude 어느 쪽이든


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
    members: list[str] = field(default_factory=list)   # 카탈로그에 없는 성군 · 묶음의 구성 천체 이름 (LLM)

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
        members=string_list(data, "members", MAX_MEMBERS) if data.get("members") is not None else [],
    )


@dataclass
class ExploreCard:
    item_id: str
    name: str
    group: str
    kind: str
    reason: str                  # 조건과 맞는 메타데이터 속성 (LLM이 후보 메타데이터에서 고른 문장 · 이름 일치는 코드 문구)


@dataclass
class ExploreResult:
    query: str
    applied: list[str]           # 적용한 조건 (사람이 읽는 문장)
    cards: list[ExploreCard]
    candidates: int              # 필터 · 의미 검색으로 모은 후보 수
    status: str                  # ok · no_match · failed · ask
    warnings: list[str] = field(default_factory=list)
    mentioned: list[dict] = field(default_factory=list)   # 질문에 이름이 나온 천체 [{id, name, group, kind, via?}]


# ── 질문에 나온 천체 이름 ──────────────────────────────────────────────────

_JOSA = ("에서", "까지", "보다", "에게", "한테", "으로", "이란", "이야", "은", "는", "이", "가", "의", "에", "을", "를",
         "과", "와", "도", "로", "만", "란", "야")
_WORD = "가-힣A-Za-z0-9"
# 이름 사이 · 뒤에 와도 '이름만 있는 질문'으로 보는 낱말 (조사는 _JOSA)
_FILLER = {"그리고", "및", "랑", "이랑", "하고", "알려줘", "보여줘", "찾아줘", "보여", "찾아"}
NAME_REASON = "질문에 나온 이름과 일치합니다."
MEMBER_REASON = "질문한 별 묶음을 이루는 천체입니다."


@lru_cache(maxsize=4096)
def _name_pattern(name: str) -> re.Pattern:
    """이름 앞은 낱말 경계, 뒤는 경계나 조사 — '달'이 '달라'에, '태양'이 '태양계'에 걸리지 않게. 띄어쓰기는 무시."""
    body = r"\s*".join(re.escape(ch) for ch in name if not ch.isspace())
    josa = "|".join(_JOSA)
    return re.compile(rf"(?<![{_WORD}])({body})(?=$|[^{_WORD}]|(?:{josa})(?:$|[^{_WORD}]))", re.IGNORECASE)


def _mention(it: dict, via: str | None = None) -> dict:
    out = {"id": it["id"], "name": display_name(it["name"]), "group": it["group"], "kind": it.get("kind") or ""}
    if via:
        out["via"] = via
    return out


def _find_names(query: str, items: list[dict], asterisms: bool = True) -> list[tuple[tuple[int, int], list[dict]]]:
    """질문에서 찾은 이름 자리와 그 자리가 가리키는 천체 — 질문에 나온 순서로.

    카탈로그 이름은 천체 하나, 성군 별칭(asterisms=True)은 카탈로그에 있는 구성 천체 여럿을 가리킨다.
    긴 이름부터 찾고, 겹치는 자리는 한 번만 쓴다.
    """
    names: list[tuple[str, list[dict]]] = [
        (name, [_mention(it)]) for it in items for name in {display_name(it["name"]), it.get("name_en") or ""}
        if name.strip()]
    if asterisms and items:
        by_name = {display_name(it["name"]): it for it in items}
        for alias, group in asterism_aliases():
            members = [_mention(by_name[m], via=group) for m in asterism_members(group) if m in by_name]
            if members:
                names.append((alias, members))
    names.sort(key=lambda x: -len(x[0].replace(" ", "")))
    found: list[tuple[tuple[int, int], list[dict]]] = []
    for name, targets in names:
        for m in _name_pattern(name).finditer(query):
            span = m.span(1)
            if any(a < span[1] and span[0] < b for (a, b), _ in found):
                continue
            if len(targets) == 1 and any(t["id"] == targets[0]["id"] for _, ts in found for t in ts):
                continue                              # 같은 천체의 한국어 · 영어 이름이 함께 나온 경우
            found.append((span, targets))
    return sorted(found, key=lambda x: x[0][0])


def _dedupe(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    return [r for r in rows if not (r["id"] in seen or seen.add(r["id"]))]


def mentioned_items(query: str, items: list[dict], limit: int = 3) -> list[dict]:
    """질문에 이름(한국어 · 영어)이 나온 카탈로그 천체. 긴 이름부터, 겹치는 자리는 한 번만, 질문에 나온 순서로. LLM 없음.

    성군 이름("여름 삼각형")은 별칭 표로 구성 천체를 찾는다 — 그 천체에는 via(성군 대표 이름)가 붙는다.
    limit는 질문에 나온 이름 자리의 수다 (성군 하나는 구성 천체 여럿으로 펼쳐진다).
    """
    return _dedupe([t for _, targets in _find_names(query, items)[:limit] for t in targets])


def names_only(query: str, items: list[dict]) -> bool:
    """질문이 카탈로그 천체 · 성군 이름(과 조사 · 접속어)만으로 이루어져 있는가 — 조건어가 없으면 True."""
    found = _find_names(query, items)
    if not found:
        return False
    rest = list(query)
    for (a, b), _ in found:
        rest[a:b] = " " * (b - a)
    return all(w in _JOSA or w in _FILLER for w in re.findall(rf"[{_WORD}]+", "".join(rest)))


def _josa(word: str, with_final: str, without_final: str) -> str:
    """받침 유무로 조사를 고른다 (한글이 아니면 받침 없음으로 본다)."""
    last = word.strip()[-1:]
    has_final = "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 != 0
    return with_final if has_final else without_final


def mention_reason(m: dict) -> str:
    """이름 일치 카드의 이유 문구 — 코드가 만든다 (LLM 없음)."""
    via = m.get("via")
    if not via:
        return NAME_REASON
    if m["group"] == "constellation":
        return f"{via}{_josa(via, '이', '가')} 있는 별자리입니다."
    return f"{via}{_josa(via, '을', '를')} 이루는 별입니다."


def member_items(members: list[str], items: list[dict], exclude: set[str] = frozenset()) -> list[dict]:
    """LLM이 적은 묶음 구성 천체 이름을 카탈로그 이름과 대조한다. 카탈로그에 없는 이름은 버린다."""
    out = []
    for member in members:
        found = _find_names(member, items, asterisms=False)
        if found:
            out.extend(found[0][1])
    return [m for m in _dedupe(out) if m["id"] not in exclude]


def _name_cards(mentioned: list[dict], members: list[dict]) -> list["ExploreCard"]:
    return ([ExploreCard(item_id=m["id"], name=m["name"], group=m["group"], kind=m["kind"], reason=mention_reason(m))
             for m in mentioned]
            + [ExploreCard(item_id=m["id"], name=m["name"], group=m["group"], kind=m["kind"], reason=MEMBER_REASON)
               for m in members])


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
    items = items or []
    mentioned = mentioned_items(query, items)
    # 0-1. 이름만 있는 질문 ("베가", "여름 삼각형") — 조건이 없으니 LLM 없이 그 천체를 카드로
    if mentioned and names_only(query, items):
        return ExploreResult(query=query, applied=[], cards=_name_cards(mentioned, []), candidates=0, status="ok")

    # 1. 조건 → 필터 (특정 천체에 대한 사실 질문인지도 함께 판단)
    try:
        filters = parse_filters(invoke_json(llm, explore_filter_messages(query)), query)
    except LLM_ERRORS:
        filters = Filters(semantic_query=query)
        warnings.append("조건을 필터로 해석하지 못해 의미 검색만 했습니다. 숫자 · 계절 같은 조건은 덜 정확할 수 있습니다.")
    if filters.asks_fact and mentioned:
        return ExploreResult(query=query, applied=[], cards=[], candidates=0, status="ask", warnings=warnings,
                             mentioned=mentioned)
    # 1-1. 카탈로그에 없는 성군 · 묶음 — LLM이 적은 구성 천체 이름을 카탈로그와 대조 (없는 이름은 버린다)
    front = _name_cards(mentioned, member_items(filters.members, items, {m["id"] for m in mentioned}))

    # 2. 필터 + 의미 검색 → 후보 (검증된 검색 — store/search.py)
    with chroma.LOCK:
        hits = search(settings.collections.items, filters.semantic_query, embedding, db,
                      k=settings.retrieval.item_candidates, where=filters.where()).hits
    candidates = [(h.metadata["item_id"], h.text) for h in hits]
    if not candidates:
        return ExploreResult(query=query, applied=filters.describe(), cards=front, candidates=0,
                             status="ok" if front else "no_match", warnings=warnings, mentioned=mentioned)

    # 3. 후보 메타데이터만 보고 선별
    try:
        data = invoke_json(llm, explore_select_messages(query, candidates, max_results))
        picked = _selected(data, {cid for cid, _ in candidates}, max_results)
    except LLM_ERRORS:
        warnings.append("후보를 조건과 대조하지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
        return ExploreResult(query=query, applied=filters.describe(), cards=front, candidates=len(candidates),
                             status="ok" if front else "failed", warnings=warnings, mentioned=mentioned)

    # 이름이 나온 천체 · 묶음 구성 천체를 맨 앞에, 선별 카드는 그 뒤에 (중복 제거)
    meta = {h.metadata["item_id"]: h.metadata for h in hits}
    taken = {c.item_id for c in front}
    cards = front + [ExploreCard(item_id=cid, name=meta[cid]["name"], group=meta[cid]["group"],
                                 kind=meta[cid].get("kind", ""), reason=reason) for cid, reason in picked
                     if cid not in taken]
    cards = cards[:max(max_results, len(front))]
    return ExploreResult(query=query, applied=filters.describe(), cards=cards, candidates=len(candidates),
                         status="ok" if cards else "no_match", warnings=warnings, mentioned=mentioned)
