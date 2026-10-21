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

    def __post_init__(self) -> None:
        self._by_id = {it["id"]: it for it in self.items}

    def item(self, item_id: str) -> dict:
        try:
            return self._by_id[item_id]
        except KeyError:
            raise ItemNotFoundError(item_id) from None


def check_health(items_loaded: int) -> HealthResponse:
    """키 · 색인 상태를 점검해 화면 안내로 바꾼다 (F2012). 키 값은 보지도 내보내지도 않는다."""
    from vasthorizon.config import get_gms_key, get_settings
    from vasthorizon.store import chroma

    settings = get_settings()
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
    elif items_indexed != items_loaded:
        notices.append(Notice(code="index_outdated", level="warning",
                              message=f"항목 {items_loaded}건 중 {items_indexed}건만 색인되어 있습니다. "
                                      "python -m scripts.index_items 로 다시 맞춰 주세요."))
    if docs_indexed == 0:
        notices.append(Notice(code="docs_index_empty", level="info",
                              message="문서 색인이 비어 있습니다. 첫 질문은 문서 수집 · 색인 때문에 오래 걸릴 수 있습니다."))
    return HealthResponse(ready=has_key and items_indexed > 0 and items_loaded > 0, gms_key=has_key,
                          items_loaded=items_loaded, items_indexed=items_indexed, docs_indexed=docs_indexed,
                          notices=notices)


def default_services() -> Services:
    from vasthorizon.data.catalog import load_items
    from vasthorizon.rag.pipeline import ask

    try:
        items = load_items()
    except FileNotFoundError:
        items = []
    return Services(items=items, ask=ask, health=lambda: check_health(len(items)))
