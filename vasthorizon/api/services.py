"""API가 쓰는 서비스 묶음 — 항목 목록 · 질의 함수 · 대화 기록 · 상태 점검 · 특화 기능.

테스트는 가짜 질의 함수와 항목을 넣은 Services로 앱을 만든다 (외부 호출 없음).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from vasthorizon.api.schemas import HealthResponse, Notice, UsageToday
from vasthorizon.api.sessions import SessionStore


class ItemNotFoundError(LookupError):
    pass


@dataclass
class Services:
    items: list[dict]
    ask: Callable                               # rag.pipeline.ask 와 같은 서명
    health: Callable[[], HealthResponse]
    sessions: SessionStore = field(default_factory=SessionStore)
    explore: Callable | None = None             # features.explore.explore(query) 와 같은 서명
    letter: Callable | None = None              # (item) → features.light_letter.LetterResult
    ref_year: int = 2026                        # 카탈로그 수집 연도 — 빛의 출발 연도 기준
    figures: dict = field(default_factory=dict)  # 항목 ID → 별자리 모양 (data/constellations.json)
    unfold: Callable | None = None              # (item, figure) → features.constellation.UnfoldResult
    sky_guide: Callable | None = None           # (view) → features.sky.SkyGuide
    perspective: Callable | None = None         # (text, theme) → features.perspective.PerspectiveResult
    sky_stars: list = field(default_factory=list)  # 맨눈 별 [적경, 적위, 등급, 색지수] (data/sky_stars.json)
    intro: Callable | None = None               # (item) → features.intro.item_intro 결과
    stars: Callable | None = None               # (item_id) → 별 임시 항목 hip:… | None (features/star_items.StarLookup)
    map_cache: dict | None = None               # /api/map 응답 — 항목이 바뀌지 않으므로 한 번만 계산
    cache: object | None = None                 # 서버 응답 캐시 (cache.ResponseCache) — 없으면 캐시하지 않는다
    usage: object | None = None                 # LLM 사용량 기록 (usage.UsageLog) — 하루 예산 · 상태 점검에 쓴다
    share: object | None = None                 # 편지 공유 저장소 (share.ShareStore) — 없으면 공유하지 않는다 (503)

    def __post_init__(self) -> None:
        self._by_id = {it["id"]: it for it in self.items}

    def item(self, item_id: str) -> dict:
        found = self._by_id.get(item_id) or (self.stars(item_id) if self.stars else None)
        if found is None:
            raise ItemNotFoundError(item_id)
        return found


def usage_today(usage, budget_usd: float = 0.0) -> UsageToday | None:
    """오늘 사용량 요약 — 토큰 수와 추정 비용만 (키 · 프롬프트는 없다)."""
    if usage is None:
        return None
    t = usage.today()
    return UsageToday(day=t.day, calls=t.calls, input_tokens=t.input_tokens, output_tokens=t.output_tokens,
                      reasoning_tokens=t.reasoning_tokens, cache_read_tokens=t.cache_read_tokens,
                      cost_usd=round(t.cost_usd, 4), budget_usd=budget_usd or None, cache_hits=t.cache_hits)


def check_health(items: list[dict], ref_year: int, usage=None) -> HealthResponse:
    """키 · 색인 상태를 점검해 화면 안내로 바꾼다. 키 값은 보지도 내보내지도 않는다.

    카탈로그와 항목 색인이 같은 데이터인지도 본다 — 카탈로그에서 다시 만든 텍스트 해시와
    색인에 저장된 text_hash를 비교한다 (임베딩 호출 없음).
    """
    from vasthorizon.config import get_llm_key, get_settings, key_name
    from vasthorizon.data.constellation_figures import figures_path
    from vasthorizon.store import chroma
    from vasthorizon.store.item_index import index_drift

    settings = get_settings()
    items_loaded = len(items)
    has_key = get_llm_key() is not None                 # 설정한 제공자(GMS · Claude)의 키
    items_indexed = chroma.collection_count(settings.collections.items)
    docs_indexed = chroma.collection_count(settings.collections.docs)
    notices = []
    if not has_key:
        notices.append(Notice(code="missing_key", level="error",
                              message=f"AI 서비스 키({key_name()})가 설정되지 않아 질문에 답할 수 없습니다. "
                                      "서버의 .env 설정을 확인해 주세요."))
    if items_loaded == 0:
        notices.append(Notice(code="catalog_missing", level="error",
                              message="항목 카탈로그가 없습니다. python -m scripts.collect_items 를 실행해 주세요."))
    if items_indexed == 0:
        notices.append(Notice(code="index_missing", level="error",
                              message="항목 색인이 없습니다. python -m scripts.index_items 를 실행해 주세요."))
    elif items_loaded:
        drift = index_drift(items, ref_year, settings.collections.items)
        if not drift.consistent:
            notices.append(Notice(
                code="index_outdated", level="warning",
                message=f"항목 색인이 카탈로그와 다릅니다 (누락 {len(drift.missing)} · 변경 {len(drift.stale)} · "
                        f"초과 {len(drift.extra)}건). python -m scripts.index_items 로 다시 맞춰 주세요."))
    if not figures_path().exists():
        notices.append(Notice(code="figures_missing", level="info",
                              message="별자리 모양 데이터가 없어 별자리 펼치기 · 하늘 안내가 일부 제한됩니다. "
                                      "python -m scripts.collect_constellations 를 실행해 주세요."))
    if chroma.collection_count(settings.collections.perspective) == 0:
        notices.append(Notice(code="perspective_missing", level="info",
                              message="관점 전환 서가 색인이 없어 관점 전환을 쓸 수 없습니다. "
                                      "python -m scripts.index_perspective 를 실행해 주세요."))
    if docs_indexed == 0:
        notices.append(Notice(code="docs_index_empty", level="info",
                              message="문서 색인이 비어 있습니다. 첫 질문은 문서 수집 · 색인 때문에 오래 걸릴 수 있습니다."))
    return HealthResponse(ready=has_key and items_indexed > 0 and items_loaded > 0, gms_key=has_key,
                          items_loaded=items_loaded, items_indexed=items_indexed, docs_indexed=docs_indexed,
                          notices=notices, usage=usage_today(usage, settings.limits.daily_cost_usd))


def default_services() -> Services:
    from datetime import date

    from vasthorizon.data.catalog import load_catalog
    from vasthorizon.data.constellation_figures import load_figures, load_sky_stars
    from vasthorizon.features.constellation import unfold
    from vasthorizon.features.explore import explore
    from vasthorizon.features.intro import item_intro
    from vasthorizon.features.light_letter import write_letter
    from vasthorizon.features.perspective import perspective
    from vasthorizon.features.sky import sky_guide
    from vasthorizon.config import PROJECT_ROOT, get_settings
    from vasthorizon.data import sources
    from vasthorizon.data.sky_catalog import load_star_index
    from vasthorizon.features.star_items import StarLookup, star_index
    from vasthorizon.rag.pipeline import ask
    from vasthorizon.cache import default_cache
    from vasthorizon.share import default_share
    from vasthorizon.usage import default_log

    try:
        catalog = load_catalog()
        items, ref_year = catalog["items"], int(catalog["meta"]["collected_at"][:4])
    except FileNotFoundError:
        items, ref_year = [], date.today().year
    figures = load_figures()
    stars = star_index(figures)
    usage = default_log()
    return Services(items=items, ask=ask, health=lambda: check_health(items, ref_year, usage),
                    cache=default_cache(), usage=usage, share=default_share(),
                    explore=lambda query: explore(query, items=items),
                    letter=lambda item: write_letter(item, ref_year), ref_year=ref_year, figures=figures,
                    stars=StarLookup(stars, load_star_index(PROJECT_ROOT / "web" / "data"),
                                     get_settings().paths.cache_dir / "stars", sources.sparql, ref_year),
                    sky_stars=load_sky_stars(),
                    unfold=lambda item, figure: unfold(item, figure, ref_year),
                    sky_guide=lambda view: sky_guide(view, items, ref_year),
                    perspective=lambda text, theme: perspective(text, theme, items), intro=item_intro)
