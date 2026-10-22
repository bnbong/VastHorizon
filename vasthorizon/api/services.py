"""API가 쓰는 서비스 묶음 — 항목 목록 · 질의 함수 · 대화 기록 · 상태 점검.

테스트는 가짜 질의 함수와 항목을 넣은 Services로 앱을 만든다 (외부 호출 없음).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from vasthorizon.api.schemas import HealthResponse, Notice
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

    def __post_init__(self) -> None:
        self._by_id = {it["id"]: it for it in self.items}

    def item(self, item_id: str) -> dict:
        try:
            return self._by_id[item_id]
        except KeyError:
            raise ItemNotFoundError(item_id) from None


def check_health(items: list[dict], ref_year: int) -> HealthResponse:
    """키 · 색인 상태를 점검해 화면 안내로 바꾼다 (F2012). 키 값은 보지도 내보내지도 않는다.

    카탈로그와 항목 색인이 같은 데이터인지도 본다 — 카탈로그에서 다시 만든 텍스트 해시와
    색인에 저장된 text_hash를 비교한다 (임베딩 호출 없음).
    """
    from vasthorizon.config import get_gms_key, get_settings
    from vasthorizon.store import chroma
    from vasthorizon.store.item_index import index_drift

    settings = get_settings()
    items_loaded = len(items)
    has_key = get_gms_key() is not None
    items_indexed = chroma.collection_count(settings.collections.items)
    docs_indexed = chroma.collection_count(settings.collections.docs)
    notices = []
    if not has_key:
        notices.append(Notice(code="missing_key", level="error",
                              message="AI 서비스 키(GMS_KEY)가 설정되지 않아 질문에 답할 수 없습니다. "
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
    if docs_indexed == 0:
        notices.append(Notice(code="docs_index_empty", level="info",
                              message="문서 색인이 비어 있습니다. 첫 질문은 문서 수집 · 색인 때문에 오래 걸릴 수 있습니다."))
    return HealthResponse(ready=has_key and items_indexed > 0 and items_loaded > 0, gms_key=has_key,
                          items_loaded=items_loaded, items_indexed=items_indexed, docs_indexed=docs_indexed,
                          notices=notices)


def default_services() -> Services:
    from datetime import date

    from vasthorizon.data.catalog import load_catalog
    from vasthorizon.features.explore import explore
    from vasthorizon.features.light_letter import write_letter
    from vasthorizon.rag.pipeline import ask

    try:
        catalog = load_catalog()
        items, ref_year = catalog["items"], int(catalog["meta"]["collected_at"][:4])
    except FileNotFoundError:
        items, ref_year = [], date.today().year
    return Services(items=items, ask=ask, health=lambda: check_health(items, ref_year), explore=explore,
                    letter=lambda item: write_letter(item, ref_year), ref_year=ref_year)
