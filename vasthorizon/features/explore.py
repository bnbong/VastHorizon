"""조건 기반 항목 탐색.

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

규칙 해석 · 결정적 경로 (LLM 절약 · 정렬)
- 질의를 먼저 동의어 표(explore_rules.py)로 해석한다. 모든 낱말이 표로 해석되면 필터 추출 LLM을 부르지 않는다.
  일부만 해석되면 LLM 필터 결과에 표의 해석을 합친다 (LLM이 비운 필드만 채운다).
- 표로 완전히 해석된 질의는 데이터만으로 결과가 정해진다 (블랙홀 유무 · 가장 가까운 별 · 맨눈 은하 …).
  이때는 선별 LLM도 부르지 않고, 필터에 맞는 항목을 카탈로그 전체에서 모아 정렬한 뒤 카드 설명을 메타데이터로 만든다.
- 정렬(sort_by)은 의미 검색 상위 후보가 아니라 필터에 맞는 카탈로그 전체에서 한다 ("가장 가까운 별"의 정답이 후보 밖에 있던 문제).
  "별"에는 태양도 들어간다 — 태양이 1위이면 2위 카드에 "태양 다음으로 가까운 별"이라고 적는다.

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
from vasthorizon.data.item_text import CATEGORIES, display_name, korean_number, year_text
from vasthorizon.data.items.common import GROUPS
from vasthorizon.data.items.constellations import SEOUL_LAT
from vasthorizon.features.explore_rules import RuleParse, parse_rules
from vasthorizon.llm import API_ERRORS
from vasthorizon.rag.llm_json import JsonReplyError, invoke_json, json_chat_model, optional_field, string_list
from vasthorizon.rag.prompts import explore_filter_messages, explore_select_messages
from vasthorizon.rag.retrieval import IndexMissingError
from vasthorizon.store import chroma
from vasthorizon.store.search import search

try:                                    # 구조화 작업용 가벼운 모델 (vasthorizon/llm.py) — 없으면 기존 JSON 모델
    from vasthorizon.llm import fast_llm as _fast_llm
except ImportError:                     # pragma: no cover - llm.py에 아직 없을 때
    _fast_llm = None


def _default_llm() -> BaseChatModel:
    return _fast_llm() if _fast_llm is not None else json_chat_model()

MAX_RESULTS = 8
MAX_MEMBERS = 12                              # LLM이 적은 묶음 구성 천체 이름 (더 많으면 자른다)
SEASONS = ("봄", "여름", "가을", "겨울")
SORT_KEYS = ("distance", "brightness", "size")
DEFAULT_ORDER = {"distance": "asc", "brightness": "asc", "size": "desc"}   # 가까운 · 밝은 · 큰 순
MAX_LIMIT = 20                                # 정렬 결과 상위 N의 상한
SUN_ID = "Q525"
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
    has_black_hole: bool | None = None        # 중심 초대질량 블랙홀 (vasthorizon/data/enrich.json)
    has_rings: bool | None = None             # 고리 (NASA 행성 자료표)
    visited_by_probe: bool | None = None      # 탐사선이 방문했는가
    visible_from_korea: bool | None = None    # 서울에서 지평선 위로 떠오르는가 (별자리는 전체가)
    kinds: list[str] | None = None            # 세부 종류 ("소행성" · "혜성") — 규칙 해석만 채운다
    sort_by: str | None = None                # distance · brightness · size
    order: str | None = None                  # asc · desc
    limit: int | None = None                  # 정렬 결과 상위 N
    asks_fact: bool = False                   # 조건 탐색이 아니라 특정 천체에 대한 사실 질문인가
    members: list[str] = field(default_factory=list)   # 카탈로그에 없는 성군 · 묶음의 구성 천체 이름 (LLM)

    def where(self) -> dict | None:
        """Chroma 메타데이터 조건식. 조건이 없으면 None."""
        clauses = []
        if self.categories:
            clauses.append({"category": {"$in": self.categories}})
        if self.kinds:
            clauses.append({"kind": {"$in": self.kinds}})
        for key, value in (("group", self.group), ("naked_eye", self.naked_eye), ("korean", self.korean),
                           ("season", self.season), ("ecliptic", self.ecliptic), ("black_hole", self.has_black_hole),
                           ("rings", self.has_rings), ("visited", self.visited_by_probe),
                           ("seoul_visible", self.visible_from_korea)):
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
            out.append(f"종류: {' · '.join(self.kinds or self.categories)}")
        elif self.group:                      # 종류가 있으면 분류는 겹치므로 보이지 않는다 ("종류: 별자리" · "분류: 별자리")
            out.append(f"분류: {GROUPS[self.group]}")
        for label, value in (("맨눈 관측", self.naked_eye), ("한국 관련", self.korean), ("황도 별자리", self.ecliptic),
                             ("중심 블랙홀", self.has_black_hole), ("고리", self.has_rings),
                             ("탐사선 방문", self.visited_by_probe), ("서울에서 관측", self.visible_from_korea)):
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
        if self.sort_by:
            words = {("distance", "asc"): "가까운 순", ("distance", "desc"): "먼 순", ("brightness", "asc"): "밝은 순",
                     ("brightness", "desc"): "어두운 순", ("size", "desc"): "큰 순", ("size", "asc"): "작은 순"}
            out.append(f"정렬: {words[(self.sort_by, self.order or DEFAULT_ORDER[self.sort_by])]}"
                       + (f" · 상위 {self.limit}" if self.limit else ""))
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
    sort_by = optional_field(data, "sort_by", (str,))
    if sort_by is not None and sort_by not in SORT_KEYS:
        raise JsonReplyError(f"알 수 없는 sort_by: {sort_by}")
    order = optional_field(data, "order", (str,))
    if order is not None and order not in ("asc", "desc"):
        raise JsonReplyError(f"알 수 없는 order: {order}")
    limit = optional_field(data, "limit", (int,))
    if limit is not None and not 1 <= limit <= MAX_LIMIT:
        raise JsonReplyError(f"limit은 1~{MAX_LIMIT}이어야 합니다: {limit}")
    kinds = string_list(data, "kinds", 8) if data.get("kinds") is not None else None
    return Filters(
        semantic_query=semantic.strip()[:200] or query, categories=categories, group=group, season=season,
        naked_eye=optional_field(data, "naked_eye", (bool,)), korean=optional_field(data, "korean", (bool,)),
        ecliptic=optional_field(data, "ecliptic", (bool,)),
        distance_ly_min=nums["distance_ly_min"], distance_ly_max=nums["distance_ly_max"],
        departure_year_min=int(nums["departure_year_min"]) if nums["departure_year_min"] is not None else None,
        departure_year_max=int(nums["departure_year_max"]) if nums["departure_year_max"] is not None else None,
        has_black_hole=optional_field(data, "has_black_hole", (bool,)),
        has_rings=optional_field(data, "has_rings", (bool,)),
        visited_by_probe=optional_field(data, "visited_by_probe", (bool,)),
        visible_from_korea=optional_field(data, "visible_from_korea", (bool,)),
        kinds=kinds or None, sort_by=sort_by, order=(order or DEFAULT_ORDER[sort_by]) if sort_by else None,
        limit=limit if sort_by else None,
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
    source_url: str | None = None   # 설명의 근거 URL (결정적 경로) — 설명 문장에는 출처 이름만 쓴다


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


def uses_llm(query: str, items: list[dict]) -> bool:
    """explore()가 LLM을 부르는 질의인가 — API가 이것으로 예산 · 호출 한도를 쓸지 정한다.

    이름만 있는 질의("베가")와, 이름 없이 동의어 표로 완전히 해석되는 질의("고리가 있는 행성")는 LLM 0회다.
    explore()의 0-1 · 0-2 분기와 같은 조건이어야 한다.
    """
    if names_only(query, items):
        return False
    return not (parse_rules(query).complete and not mentioned_items(query, items))


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


# ── 정렬 · 결정적 경로 ───────────────────────────────────────────────────

def _size_key(rows: list[tuple[str, str, dict]], filters: Filters) -> str:
    """크기 정렬에 쓸 값 하나 — 반지름(km)과 면적(제곱도)은 단위가 달라 한 열로 섞지 않는다.

    별자리를 찾는 질의면 면적, 그 밖에는 반지름(태양계 천체). 반지름이 있는 항목이 하나도 없을 때만 면적으로.
    """
    if filters.categories == ["별자리"] or filters.group == "constellation":
        return "area_sqdeg"
    return "radius_km" if any(r[2].get("radius_km") is not None for r in rows) else "area_sqdeg"


def _sort_value(meta: dict, sort_by: str, size_key: str = "radius_km") -> float | None:
    if sort_by == "distance":
        return meta.get("distance_ly")
    if sort_by == "brightness":
        return meta.get("magnitude")                       # 겉보기 등급 — 작을수록 밝다
    return meta.get(size_key)                              # 크기 — _size_key가 고른 값 하나만


def _catalog_rows(name: str, db, where: dict | None) -> list[tuple[str, str, dict]]:
    """필터에 맞는 항목 전체 (의미 검색 없음) — 정렬 · 결정적 경로용. (항목 ID, 색인 텍스트, 메타데이터)"""
    got = chroma.db_for(name, db).get_collection(name).get(where=where, include=["documents", "metadatas"])
    return [(m["item_id"], doc or "", m) for doc, m in zip(got["documents"], got["metadatas"]) if m]


def rank_rows(rows: list[tuple[str, str, dict]], filters: Filters) -> list[tuple[str, str, dict]]:
    """정렬 기준이 있으면 그 값으로 (값이 없는 항목은 뺀다), 없으면 밝은 순 → 가까운 순 → 이름 순."""
    if filters.sort_by:
        size_key = _size_key(rows, filters) if filters.sort_by == "size" else "radius_km"
        keyed = [(v, r) for r in rows if (v := _sort_value(r[2], filters.sort_by, size_key)) is not None]
        keyed.sort(key=lambda x: (x[0], x[1][2]["name"]), reverse=filters.order == "desc")
        return [r for _, r in keyed]
    inf = float("inf")

    def value(meta: dict, key: str) -> float:          # 없거나 None인 값은 뒤로
        v = meta.get(key)
        return inf if v is None else v
    return sorted(rows, key=lambda r: (value(r[2], "magnitude"), value(r[2], "distance_ly"), r[2]["name"]))


def _distance_phrase(meta: dict) -> str:
    ly = meta.get("distance_ly")
    if ly is None:
        return ""
    return f"약 {korean_number(ly)}광년" if ly >= 0.1 else f"약 {korean_number(meta['distance_km'])}km"


def _rank_phrase(filters: Filters, rank: int, ranked: list[tuple[str, str, dict]]) -> str:
    adj = {("distance", "asc"): "가까운", ("distance", "desc"): "먼", ("brightness", "asc"): "밝은",
           ("brightness", "desc"): "어두운", ("size", "desc"): "큰", ("size", "asc"): "작은"}[(filters.sort_by, filters.order)]
    noun = filters.categories[0] if filters.categories and len(filters.categories) == 1 else "천체"
    if rank == 0:
        return f"카탈로그의 {noun} 가운데 가장 {adj} {noun}"
    if rank == 1 and ranked[0][0] == SUN_ID and filters.sort_by == "distance" and filters.order == "asc":
        return f"태양 다음으로 {adj} {noun}"
    return f"{rank + 1}번째로 {adj} {noun}"


def _split_source(source: str) -> tuple[str, str | None]:
    """메타데이터의 근거 '출처 이름 URL'을 (이름, URL)로. URL이 없으면 (전체, None)."""
    name, _, url = source.rpartition(" ")
    return (name, url) if name and url.startswith(("http://", "https://")) else (source, None)


def fact_sources(meta: dict, filters: Filters) -> list[tuple[str, str | None]]:
    """결정적 경로 카드 설명의 근거 [(출처 이름, URL)] — 필터에 쓴 보강 속성(블랙홀 · 고리 · 탐사선 방문)의 출처."""
    raw = []
    if filters.has_black_hole:
        raw.append(meta.get("black_hole_source", ""))
    if filters.has_rings is not None:
        raw.append(meta.get("rings_source", ""))
    if filters.visited_by_probe:
        raw.append(meta.get("visit_source", ""))
    return [_split_source(s) for s in dict.fromkeys(s for s in raw if s)]


def fact_reason(meta: dict, filters: Filters, rank: int = 0, ranked: list | None = None) -> str:
    """결정적 경로의 카드 설명 — 조건과 맞는 메타데이터 속성과 근거 출처 이름 (LLM 없음, 지어내지 않는다).
    근거 URL은 설명에 넣지 않는다 — 카드의 source_url로 따로 보낸다 (fact_sources)."""
    parts = []
    if filters.sort_by:
        parts.append(_rank_phrase(filters, rank, ranked or []))
    if filters.has_black_hole:
        name, mass = meta.get("black_hole_name", ""), meta.get("black_hole_mass")
        what = "초대질량 블랙홀" if name in ("", "초대질량 블랙홀") else f"{name} 블랙홀"
        parts.append(f"중심에 {what}" + (f"(질량 {mass})" if mass else ""))
    elif filters.has_black_hole is False:
        parts.append("카탈로그에 중심 블랙홀 기록 없음")
    if filters.has_rings is not None:
        moons = f" · 알려진 위성 {meta['moons']}개" if isinstance(meta.get("moons"), int) else ""
        parts.append(("고리가 있음" if meta.get("rings") else "고리가 없음") + moons)
    if filters.visited_by_probe:
        parts.append(f"탐사선 방문: {meta.get('visit', '')}")
    elif filters.visited_by_probe is False:
        parts.append("카탈로그에 탐사선 방문 기록 없음")
    if filters.visible_from_korea is not None:
        whole = meta["group"] == "constellation"
        if meta.get("seoul_visible"):
            parts.append("서울에서 별자리 전체를 볼 수 있음" if whole else
                         f"서울(북위 {SEOUL_LAT:.1f}°)에서 지평선 위로 떠오름")
        else:
            parts.append("서울에서는 전체를 볼 수 없음" if whole else "서울에서는 지평선 위로 떠오르지 않음")
    if filters.naked_eye is not None:
        mag = f" · 겉보기 등급 {meta['magnitude']:g}" if meta.get("magnitude") is not None else ""
        parts.append(("맨눈 관측 가능" if meta.get("naked_eye") else "맨눈으로는 보이지 않음") + mag)
    if filters.season:
        parts.append(f"{filters.season}철 저녁 하늘의 별자리")
    if filters.ecliptic:
        parts.append("태양이 지나는 길(황도) 위의 별자리")
    if filters.korean:
        parts.append("한국 관련 항목")
    if filters.sort_by == "brightness" and meta.get("magnitude") is not None and filters.naked_eye is None:
        parts.append(f"겉보기 등급 {meta['magnitude']:g}")
    if filters.sort_by == "size":
        if meta.get("radius_km") is not None:
            parts.append(f"평균 반지름 약 {korean_number(meta['radius_km'])}km")
        elif meta.get("area_sqdeg") is not None:
            parts.append(f"면적 {meta['area_sqdeg']:g}제곱도")
    if filters.sort_by == "distance" or filters.distance_ly_min is not None or filters.distance_ly_max is not None:
        if (where := _distance_phrase(meta)):
            parts.append(f"지구에서 {where}")
    if not parts:
        parts.append(meta.get("kind") or meta.get("category") or "")
    out = " · ".join(p for p in parts if p)
    cited = [name for name, _ in fact_sources(meta, filters)]
    if cited:
        out += " · 근거: " + ", ".join(cited)
    return out


def _parse_with_rules(llm: BaseChatModel, query: str, rule: RuleParse, warnings: list[str]) -> Filters:
    """필터 추출 LLM + 규칙 해석 합치기. LLM이 비운 필드만 규칙 값으로 채운다. LLM이 실패하면 규칙 해석만 쓴다."""
    try:
        data = invoke_json(llm, explore_filter_messages(query))
        if not isinstance(data, dict):
            raise JsonReplyError("필터 응답이 객체가 아닙니다.")
        merged = dict(data)
        for key, value in rule.data.items():
            if merged.get(key) is None:
                merged[key] = value
        return parse_filters(merged, query)
    except LLM_ERRORS:
        if rule.data:
            warnings.append("조건 일부만 해석해 찾았습니다. 해석하지 못한 조건은 의미 검색으로만 반영했습니다.")
            return parse_filters(rule.data, query)
        warnings.append("조건을 필터로 해석하지 못해 의미 검색만 했습니다. 숫자 · 계절 같은 조건은 덜 정확할 수 있습니다.")
        return Filters(semantic_query=query)


def _meta_card(cid: str, meta: dict, reason: str, source_url: str | None = None) -> ExploreCard:
    return ExploreCard(item_id=cid, name=display_name(meta["name"]), group=meta["group"],
                       kind=meta.get("kind", ""), reason=reason, source_url=source_url)


def explore(query: str, llm: BaseChatModel | None = None, embedding: Embeddings | None = None,
            db: chromadb.ClientAPI | None = None, max_results: int = MAX_RESULTS,
            items: list[dict] | None = None, rules: bool = True) -> ExploreResult:
    """rules=False면 동의어 표를 쓰지 않는다 (필터 추출 · 선별을 늘 LLM으로 — 비교 · 시험용)."""
    settings = get_settings()
    name = settings.collections.items
    # 0. 색인 준비 상태 — 없거나 비어 있으면 '조건 불일치'가 아니라 준비 오류다 (LLM 호출 전에 확인)
    if chroma.collection_count(name, db) == 0:
        raise IndexMissingError("항목 색인이 없어 조건 탐색을 할 수 없습니다. python -m scripts.index_items 를 실행하세요.")
    warnings: list[str] = []
    items = items or []
    mentioned = mentioned_items(query, items)
    # 0-1. 이름만 있는 질문 ("베가", "여름 삼각형") — 조건이 없으니 LLM 없이 그 천체를 카드로
    if mentioned and names_only(query, items):
        return ExploreResult(query=query, applied=[], cards=_name_cards(mentioned, []), candidates=0, status="ok")

    # 0-2. 규칙 해석 — 질의 전체가 표로 해석되면 결과가 데이터만으로 정해진다 (LLM 0회).
    #      이름이 나온 질의는 사실 질문인지 LLM이 판단해야 하므로 결정적 경로로 보내지 않는다
    rule = parse_rules(query) if rules else RuleParse()
    if rule.complete and not mentioned:
        filters = parse_filters(rule.data, query)
        with chroma.LOCK:
            rows = _catalog_rows(name, db, filters.where())
        ranked = rank_rows(rows, filters)
        # LLM을 쓰지 않는 경로라 카드를 더 보여 줘도 비용이 없다 — 정렬 없는 목록은 MAX_LIMIT까지
        limit = filters.limit or (max_results if filters.sort_by else max(max_results, MAX_LIMIT))
        cards = [_meta_card(cid, meta, fact_reason(meta, filters, i, ranked),
                            next((url for _, url in fact_sources(meta, filters) if url), None))
                 for i, (cid, _, meta) in enumerate(ranked[:limit])]
        if len(ranked) > limit and not filters.sort_by:
            warnings.append(f"조건에 맞는 항목 {len(ranked)}건 가운데 {limit}건을 보여 줍니다. 조건을 더하면 좁힐 수 있습니다.")
        return ExploreResult(query=query, applied=filters.describe(), cards=cards, candidates=len(ranked),
                             status="ok" if cards else "no_match", warnings=warnings)

    # 1. 조건 → 필터 (특정 천체에 대한 사실 질문인지도 함께 판단)
    llm = llm or _default_llm()
    embedding = embedding or chroma.default_embedding()
    filters = _parse_with_rules(llm, query, rule, warnings)
    if filters.asks_fact and mentioned:
        return ExploreResult(query=query, applied=[], cards=[], candidates=0, status="ask", warnings=warnings,
                             mentioned=mentioned)
    # 1-1. 카탈로그에 없는 성군 · 묶음 — LLM이 적은 구성 천체 이름을 카탈로그와 대조 (없는 이름은 버린다)
    front = _name_cards(mentioned, member_items(filters.members, items, {m["id"] for m in mentioned}))

    # 2. 후보 — 정렬 질의는 필터에 맞는 카탈로그 전체를 정렬한 상위 N, 아니면 필터 + 의미 검색 (store/search.py)
    k = settings.retrieval.item_candidates
    with chroma.LOCK:
        if filters.sort_by:
            rows = rank_rows(_catalog_rows(name, db, filters.where()), filters)[:k]
        else:
            rows = [(h.metadata["item_id"], h.text, h.metadata)
                    for h in search(name, filters.semantic_query, embedding, db, k=k, where=filters.where()).hits]
    candidates = [(cid, text) for cid, text, _ in rows]
    if not candidates:
        return ExploreResult(query=query, applied=filters.describe(), cards=front, candidates=0,
                             status="ok" if front else "no_match", warnings=warnings, mentioned=mentioned)

    # 3. 후보 메타데이터만 보고 선별
    limit = min(filters.limit or max_results, max_results) if filters.sort_by else max_results
    try:
        data = invoke_json(llm, explore_select_messages(query, candidates, limit))
        picked = _selected(data, {cid for cid, _ in candidates}, limit)
    except LLM_ERRORS:
        warnings.append("후보를 조건과 대조하지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
        return ExploreResult(query=query, applied=filters.describe(), cards=front, candidates=len(candidates),
                             status="ok" if front else "failed", warnings=warnings, mentioned=mentioned)
    if filters.sort_by:                           # 선별은 조건만 확인한다 — 순서는 정렬 결과를 따른다
        order = {cid: i for i, (cid, _, _) in enumerate(rows)}
        picked.sort(key=lambda x: order[x[0]])

    # 이름이 나온 천체 · 묶음 구성 천체를 맨 앞에, 선별 카드는 그 뒤에 (중복 제거)
    meta = {cid: m for cid, _, m in rows}
    taken = {c.item_id for c in front}
    cards = front + [ExploreCard(item_id=cid, name=meta[cid]["name"], group=meta[cid]["group"],
                                 kind=meta[cid].get("kind", ""), reason=reason) for cid, reason in picked
                     if cid not in taken]
    cards = cards[:max(max_results, len(front))]
    return ExploreResult(query=query, applied=filters.describe(), cards=cards, candidates=len(candidates),
                         status="ok" if cards else "no_match", warnings=warnings, mentioned=mentioned)
