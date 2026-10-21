"""질문 하나를 처리하는 전체 흐름 — 수집 → 색인 → RAG 그래프.

    1. 문서 수집 (F2003 · F2004)   — 같은 질문 · 이미 수집한 문서는 캐시
    2. 문서 색인 (F2005)           — 이 항목의 연결 문서만, 바뀐 청크만 임베딩
    3. retrieve → generate (F2006 · F2007 · F2008)

진행 상태는 progress 콜백으로 알린다 (F2012). 단계마다 상태 · 소요 시간을 stages에 남긴다.

| 단계 실패                         | 처리                                                    |
|-----------------------------------|---------------------------------------------------------|
| 수집 일부 실패                    | 경고로 남기고 이미 연결된 문서로 계속 (collector가 처리) |
| 색인 — 문서 문제(DocIndexError)   | 경고로 남기고 기존 색인으로 계속                        |
| 색인 — 임베딩 API 일시 장애       | 경고로 남기고 기존 색인으로 계속 (없으면 항목 근거만)   |
| 색인 — 임베딩 모델 불일치         | 멈춘다. 호환되지 않는 벡터로 검색하지 않는다             |
| 검색 — 일시 장애                  | 항목 근거만으로 답변 (retrieval이 처리)                 |
경고에는 장애 종류만 쓰고, 키 · 주소 · 요청 내용은 넣지 않는다. (NF2004)
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from vasthorizon.collect.collector import CollectResult, Collector
from vasthorizon.llm import TRANSIENT_API_ERRORS, describe_api_error
from vasthorizon.rag.graph import build_graph
from vasthorizon.rag.retrieval import Evidence
from vasthorizon.store.doc_index import DocIndex, DocIndexError, DocIndexReport

Progress = Callable[[str], None]


@dataclass
class Stage:
    status: str                 # ok · partial · failed · skipped
    seconds: float = 0.0


@dataclass
class AnswerResult:
    question: str
    answer: str
    status: str                                 # cited · not_found · rejected (graph.py 답변 검증 정책)
    cited: list[Evidence]                       # 답변에 인용된 근거만 (화면 표시용)
    evidences: list[Evidence]                   # 검색된 근거 전체 (검증 · 비교용)
    attempts: int = 1
    issues: list[str] = field(default_factory=list)
    collect: CollectResult | None = None
    index: DocIndexReport | None = None
    stages: dict[str, Stage] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_citations(self) -> bool:
        return bool(self.cited)

    @property
    def not_found(self) -> bool:
        return self.status == "not_found"

    @property
    def timings(self) -> dict[str, float]:
        return {name: stage.seconds for name, stage in self.stages.items()}


def ask(item: dict, question: str, history: list[dict] | None = None, progress: Progress | None = None,
        collect: bool = True, search_type: str | None = None,
        collector: Collector | None = None, doc_index: DocIndex | None = None, graph=None) -> AnswerResult:
    progress = progress or (lambda msg: None)
    warnings: list[str] = []
    stages: dict[str, Stage] = {}
    collect_result = index_report = None

    if not collect:
        stages["collect"] = stages["index"] = Stage("skipped")
    else:
        t = time.perf_counter()
        progress("관련 문서를 찾는 중")
        collect_result = (collector or Collector()).collect(item, question, progress)
        warnings += collect_result.warnings
        stages["collect"] = Stage("ok" if collect_result.complete else "partial", time.perf_counter() - t)

        t = time.perf_counter()
        if not collect_result.docs:
            stages["index"] = Stage("skipped")
        else:
            progress(f"문서 {len(collect_result.docs)}건을 색인하는 중")
            try:
                index_report = (doc_index or DocIndex()).ensure(
                    item, collect_result.docs, collect_result.links, collect_result.missing)
                stages["index"] = Stage("ok" if index_report.complete else "partial", time.perf_counter() - t)
            except DocIndexError as e:
                warnings.append(str(e))
                stages["index"] = Stage("failed", time.perf_counter() - t)
            except TRANSIENT_API_ERRORS as e:
                warnings.append(f"새 문서 색인 실패(임베딩 API {describe_api_error(e)}) — 이미 색인된 근거로 답합니다.")
                stages["index"] = Stage("failed", time.perf_counter() - t)
            # EmbeddingMismatchError 등 계속하면 안 되는 오류는 그대로 올린다

    t = time.perf_counter()
    progress("근거를 모아 답변을 쓰는 중")
    state = (graph or build_graph()).invoke({
        "item": item, "question": question, "history": history or [], "search_type": search_type,
        "warnings": [],
    })
    stages["retrieve"] = Stage({"ok": "ok", "empty": "ok", "failed": "failed"}[state["doc_search"]])
    stages["answer"] = Stage("ok" if state["status"] != "rejected" else "failed", time.perf_counter() - t)
    warnings += state.get("warnings", [])
    if state["status"] == "rejected":
        warnings.append("답변이 인용 규칙을 두 번 어겨 내보내지 않았습니다.")

    return AnswerResult(
        question=question, answer=state["answer"], status=state["status"], cited=state["cited"],
        evidences=state["evidences"], attempts=state.get("attempts", 1), issues=state.get("issues", []),
        collect=collect_result, index=index_report, stages=stages, warnings=warnings,
    )
