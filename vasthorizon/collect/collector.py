"""외부 문서 수집.

흐름 — 항목 1개 + 질문 1개
  0. 항목 자체 문서(위키 문서 · NASA 미션 설명)를 먼저 확보한다. 어떤 제외 규칙보다 우선한다.
     단, 본문이 아예 없는 문서는 근거가 아니므로 연결하지 않고 실패로 알린다.
  1. 검색어 — 항목 이름은 항상 포함. 프롬프트 1의 결과는 (항목, 질문)별로 기록해 같은 질문에 재사용한다.
  2. 검색 — 검색어마다 검색 결과 캐시를 먼저 본다. 같은 검색어는 검색 API를 다시 부르지 않는다.
  3. 규칙 거르기 — 이미 연결 · 중복 · 동음이의 문서 · 요약이 너무 짧음
  4. 선별 — 아직 연결되지 않은 후보를 프롬프트 2로 판정한다. 판정은 (항목, 질문)별로 기록해
     같은 질문은 다시 묻지 않고, 새 질문은 같은 후보라도 새로 판정한다. 본문은 아직 받지 않는다.
  5. 본문 — 선별된 문서만 받는다. 같은 문서는 캐시에서 읽는다.

실패 처리
- 검색 · 선별 · 본문 수집 · 항목 문서의 실패는 StepFailure로 모으고, 완료 기록을 남기지 않는다.
  (검색 실패는 검색 캐시에, 선별 실패는 판정 기록에, 본문 실패는 연결 문서에 남지 않는다)
- 그래서 장애가 풀린 뒤 같은 질문을 다시 실행하면 실패한 단계부터 이어서 처리된다.
- 성공한 외부 호출(검색 결과 · 판정 · 본문)은 캐시에서 재사용한다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import requests
from langchain_core.language_models import BaseChatModel

from vasthorizon.collect.cache import CollectCache, normalize_query, now, usable
from vasthorizon.config import get_settings
from vasthorizon.data.docs import Candidate, Document, SourceError, nssdca, wikipedia
from vasthorizon.data.item_text import display_name
from vasthorizon.llm import API_ERRORS
from vasthorizon.rag.llm_json import JsonReplyError, invoke_json, json_chat_model, string_list
from vasthorizon.rag.prompts import query_messages, select_messages

log = logging.getLogger(__name__)

ROLE_OWN = "항목 문서"
ROLE_RELATED = "관련 문서"
SELECTED, REJECTED = "selected", "rejected"

# 외부 출처 · LLM 장애로 보는 예외 — 이 경우 단계 실패로 기록하고 계속 진행한다
SOURCE_ERRORS = (requests.RequestException, SourceError)
LLM_ERRORS = (JsonReplyError, *API_ERRORS)   # GMS · Claude 어느 쪽이든

Progress = Callable[[str], None]


@dataclass
class Decision:
    doc_id: str
    title: str
    query: str
    decision: str          # 색인 · 제외 · 기존 · 보류(실패로 다음 실행에 다시 처리)
    reason: str


@dataclass
class StepFailure:
    step: str              # 항목 문서 · 검색어 추출 · 검색 · 선별 · 본문
    target: str
    reason: str

    def message(self) -> str:
        return f"{self.step} 실패 ({self.target}): {self.reason} — 다시 실행하면 이어서 처리합니다."


@dataclass
class CollectResult:
    item_id: str
    question: str
    queries: list[str] = field(default_factory=list)            # 이번에 쓴 검색어 전체
    searched_queries: list[str] = field(default_factory=list)   # 검색 API를 실제로 부른 검색어
    cached_queries: list[str] = field(default_factory=list)     # 검색 결과 캐시에서 읽은 검색어
    decisions: list[Decision] = field(default_factory=list)
    new_docs: list[Document] = field(default_factory=list)      # 이번에 새로 연결한 문서
    docs: list[Document] = field(default_factory=list)          # 이 항목에 연결된 전체 문서 (색인 대상)
    links: dict[str, dict] = field(default_factory=dict)        # 문서 ID → 역할 · 검색어 · 연결 시각
    missing: list[str] = field(default_factory=list)            # 연결됐지만 본문을 얻지 못한 문서 (색인 시 보존)
    llm_calls: int = 0
    question_cached: bool = False                               # 같은 질문의 검색어를 재사용함
    failures: list[StepFailure] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.failures

    @property
    def warnings(self) -> list[str]:
        return [f.message() for f in self.failures]


@dataclass
class LinkedDocs:
    """항목에 연결된 문서. missing은 연결은 그대로지만 본문을 얻지 못한 문서 ID다."""

    docs: list[Document] = field(default_factory=list)
    links: dict[str, dict] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    failures: list[StepFailure] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing


class Collector:
    def __init__(self, cache: CollectCache | None = None, llm: BaseChatModel | None = None,
                 wiki=wikipedia, nasa=nssdca) -> None:
        self.cache = cache or CollectCache()
        self._llm = llm
        self.wiki, self.nasa = wiki, nasa
        self.cfg = get_settings().collect

    @property
    def llm(self) -> BaseChatModel:
        if self._llm is None:
            self._llm = json_chat_model()
        return self._llm

    # ── 0. 항목 자체 문서 ─────────────────────────────────────────────────

    def own_documents(self, item: dict, manifest: dict, progress: Progress,
                      failures: list[StepFailure]) -> list[Document]:
        """항목 자체 문서. 길이 · 선별 규칙은 적용하지 않지만, 본문이 없는 문서는 연결하지 않는다."""
        docs = []
        # 별자리 선의 별(임시 항목)은 한국어 위키 문서가 없을 수 있다 — 그때는 검색으로만 모은다
        doc = self._wiki_by_title(item["wiki_title"], "항목 문서", failures) if item.get("wiki_title") else None
        if doc:
            docs.append(doc)
        cospar = item.get("attrs", {}).get("COSPAR ID")
        if cospar:
            nasa = self._nasa(cospar, failures)
            if nasa:
                docs.append(nasa)
        for d in docs:
            if d.doc_id not in manifest["docs"]:
                progress(f"항목 문서 수집: {d.title}")
                self._link(manifest, d, ROLE_OWN, query=None)
        return docs

    def prefetch_own(self, item: dict) -> tuple[list[Document], list[str]]:
        """항목 자체 문서만 미리 받아 둔다 — LLM 호출 없음. 첫 질문의 응답 시간을 줄인다."""
        manifest = self.cache.get_manifest(item["id"])
        failures: list[StepFailure] = []
        docs = self.own_documents(item, manifest, lambda msg: None, failures)
        self.cache.put_manifest(manifest)
        return docs, [f.message() for f in failures]

    # ── 전체 흐름 ─────────────────────────────────────────────────────────

    def collect(self, item: dict, question: str, progress: Progress | None = None) -> CollectResult:
        progress = progress or (lambda msg: None)
        manifest = self.cache.get_manifest(item["id"])
        result = CollectResult(item_id=item["id"], question=question)
        before = set(manifest["docs"])

        own = self.own_documents(item, manifest, progress, result.failures)
        own_ids = {d.doc_id for d in own}

        # 1. 검색어
        record = self._question_record(item, question, manifest, result, progress)
        queries = [display_name(item["name"])] + (record["queries"] if record else [])
        result.queries = list(dict.fromkeys(normalize_query(q) for q in queries if q.strip()))

        # 2 · 3. 검색 + 규칙 거르기
        pending: list[tuple[Candidate, str]] = []
        seen: set[str] = set()
        for query in result.queries:
            candidates = self._search(query, result, progress)
            for cand in candidates or []:
                if cand.doc_id in seen:
                    continue
                seen.add(cand.doc_id)
                if cand.doc_id in own_ids:
                    self._decide(result, cand, query, "색인", "항목 자체 문서 — 선별 규칙보다 우선")
                elif cand.doc_id in manifest["docs"]:
                    self._decide(result, cand, query, "기존", "이미 연결된 문서")
                elif cand.disambiguation:
                    self._decide(result, cand, query, "제외", "동음이의 문서")
                elif len(cand.summary) < self.cfg.min_summary_chars:
                    self._decide(result, cand, query, "제외", "요약이 너무 짧음")
                else:
                    pending.append((cand, query))

        # 4. 선별 — 이 질문으로 아직 판정하지 않은 후보만 프롬프트 2에 보낸다
        judged = record["judged"] if record else {}
        unjudged = [c for c, _ in pending if c.doc_id not in judged]
        if unjudged:
            progress(f"후보 {len(unjudged)}건 선별 중")
            picked = self._select(item, question, unjudged, result)
            if picked is not None:                       # 실패하면 판정을 남기지 않는다
                for c in unjudged:
                    judged[c.doc_id] = SELECTED if c.doc_id in picked else REJECTED

        # 5. 본문
        for cand, query in pending:
            verdict = judged.get(cand.doc_id)
            if verdict is None:
                self._decide(result, cand, query, "보류", "선별 실패 — 다음 실행에서 다시 선별")
                continue
            if verdict == REJECTED:
                self._decide(result, cand, query, "제외", "선별 프롬프트에서 제외")
                continue
            progress(f"문서 수집: {cand.title}")
            doc = self.cache.get_doc(cand.doc_id) or self._wiki_by_title(cand.title, "본문", result.failures)
            if doc is None:
                self._decide(result, cand, query, "보류", "본문 수집 실패 — 다음 실행에서 다시 수집")
            elif len(doc.text) < self.cfg.min_doc_chars:
                self._decide(result, cand, query, "제외", "본문이 너무 짧음")
            else:
                self._link(manifest, doc, ROLE_RELATED, query)
                self._decide(result, cand, query, "색인", "선별됨")

        if record is not None:
            record["status"] = "complete" if result.complete else "incomplete"
            record["at"] = now()
        self.cache.put_manifest(manifest)

        linked = self._resolve_links(manifest, result.failures)
        result.docs, result.links, result.missing = linked.docs, linked.links, linked.missing
        result.new_docs = [d for d in result.docs if d.doc_id not in before]
        state = "수집 완료" if result.complete else f"일부 실패 {len(result.failures)}건"
        progress(f"{state} — 새 문서 {len(result.new_docs)}건, 연결 문서 {len(result.docs)}건")
        return result

    # ── 연결 문서 ─────────────────────────────────────────────────────────

    def linked(self, item_id: str) -> "LinkedDocs":
        """이미 연결된 문서 — 수집 없이 색인만 다시 할 때 쓴다. 캐시가 없는 문서는 다시 받아 복구한다."""
        manifest = self.cache.get_manifest(item_id)
        failures: list[StepFailure] = []
        linked = self._resolve_links(manifest, failures)
        linked.failures = failures
        return linked

    def fetch_wiki(self, title: str, failures: list[StepFailure]) -> Document | None:
        """제목으로 위키 문서 하나를 받는다 (캐시 우선). 항목에 연결하지 않는다 — 빛의 편지 연도 문서 등."""
        return self._wiki_by_title(title, "문서", failures)

    def unlink(self, item_id: str, doc_id: str) -> bool:
        """문서 연결을 명시적으로 푼다. 다음 색인 동기화에서 이 문서의 청크가 지워진다."""
        manifest = self.cache.get_manifest(item_id)
        if manifest["docs"].pop(doc_id, None) is None:
            return False
        self.cache.put_manifest(manifest)
        return True

    def _resolve_links(self, manifest: dict, failures: list[StepFailure]) -> "LinkedDocs":
        """연결된 문서의 본문을 캐시에서 읽는다. 캐시가 없으면 연결 정보로 다시 받는다.

        끝내 본문을 얻지 못한 문서는 missing으로 돌려준다. 연결 정보는 지우지 않는다 —
        캐시 유실을 '연결 해제'로 오인해 색인에서 청크가 삭제되는 일을 막기 위해서다.
        """
        result = LinkedDocs()
        for doc_id, link in manifest["docs"].items():
            doc = self.cache.get_doc(doc_id) or self._restore(doc_id, link, failures)
            if doc is None:
                result.missing.append(doc_id)
                continue
            result.docs.append(doc)
            result.links[doc_id] = link
        return result

    def _restore(self, doc_id: str, link: dict, failures: list[StepFailure]) -> Document | None:
        source, _, key = doc_id.partition(":")
        if source == "nssdca":
            doc = self._nasa(key, failures)
        else:
            doc = self._wiki_by_title(link.get("title", ""), "본문 복구", failures)
        if doc is None or doc.doc_id != doc_id:
            if doc is not None:     # 제목이 다른 문서로 바뀐 경우 — 다른 ID로 연결하지 않는다
                failures.append(StepFailure("본문 복구", link.get("title", doc_id), "문서 ID가 바뀌었습니다"))
            return None
        return doc

    # ── 단계별 도우미 ─────────────────────────────────────────────────────

    def _question_record(self, item: dict, question: str, manifest: dict,
                         result: CollectResult, progress: Progress) -> dict | None:
        """(항목, 질문) 기록 — 검색어 · 선별 판정. 검색어 추출이 실패하면 기록을 만들지 않는다."""
        key = normalize_query(question)
        if not key:
            return None
        record = manifest["questions"].get(key)
        if record is not None:
            result.question_cached = True
            return record
        progress("검색어를 뽑는 중")
        result.llm_calls += 1
        try:
            data = invoke_json(self.llm, query_messages(item, question, self.cfg.max_queries), purpose="ask.query")
            queries = string_list(data, "queries", self.cfg.max_queries)
        except LLM_ERRORS as e:
            result.failures.append(StepFailure("검색어 추출", question, type(e).__name__))
            return None
        record = {"queries": queries, "judged": {}, "status": "incomplete", "at": now()}
        manifest["questions"][key] = record
        return record

    def _select(self, item: dict, question: str, candidates: list[Candidate],
                result: CollectResult) -> set[str] | None:
        """선택된 후보 ID. 응답이 스키마와 다르거나 호출이 실패하면 None — 빈 선택과 구분한다."""
        result.llm_calls += 1
        try:
            data = invoke_json(self.llm, select_messages(item, question, candidates, self.cfg.max_selected),
                               purpose="ask.select")
            picked = string_list(data, "selected", len(candidates))
        except LLM_ERRORS as e:
            result.failures.append(StepFailure("선별", f"후보 {len(candidates)}건", type(e).__name__))
            return None
        valid = {c.doc_id for c in candidates}
        return set([p for p in picked if p in valid][:self.cfg.max_selected])   # 후보 밖 ID · 초과분은 버린다

    def _search(self, query: str, result: CollectResult, progress: Progress) -> list[Candidate] | None:
        """후보 목록. 정상적인 0건은 []로 캐시하고, 실패는 None으로 돌려주며 캐시하지 않는다."""
        cached = self.cache.get_search(wikipedia.SOURCE_TYPE, query)
        if cached is not None:
            result.cached_queries.append(query)
            return cached
        progress(f"위키백과 검색: {query}")
        result.searched_queries.append(query)
        try:
            found = self.wiki.search(query, self.cfg.candidates_per_query)
        except SOURCE_ERRORS as e:
            result.failures.append(StepFailure("검색", query, _reason(e)))
            return None
        self.cache.put_search(wikipedia.SOURCE_TYPE, query, found)
        return found

    def _wiki_by_title(self, title: str, step: str, failures: list[StepFailure]) -> Document | None:
        doc_id = self.cache.get_title(wikipedia.SOURCE_TYPE, title)
        if doc_id and (doc := self.cache.get_doc(doc_id)):
            return doc
        try:
            doc = self.wiki.fetch(title, self.cfg.max_doc_chars)
        except SOURCE_ERRORS as e:
            failures.append(StepFailure(step, title, _reason(e)))
            return None
        if doc is None:
            failures.append(StepFailure(step, title, "문서가 없습니다"))
            return None
        if not usable(doc):
            failures.append(StepFailure(step, title, "본문이 비어 있습니다"))
            return None
        self.cache.put_doc(doc)
        self.cache.put_title(wikipedia.SOURCE_TYPE, title, doc.doc_id)
        return doc

    def _nasa(self, cospar: str, failures: list[StepFailure]) -> Document | None:
        """NASA 미션 설명. 설명 절이 없는 탐사선이 많아 '없음'은 실패로 보지 않는다."""
        if doc := self.cache.get_doc(f"nssdca:{cospar}"):
            return doc
        try:
            doc = self.nasa.fetch(cospar, self.cfg.max_doc_chars)
        except SOURCE_ERRORS as e:
            failures.append(StepFailure("항목 문서", f"NASA {cospar}", _reason(e)))
            return None
        if not usable(doc):
            return None
        self.cache.put_doc(doc)
        return doc

    def _link(self, manifest: dict, doc: Document, role: str, query: str | None) -> None:
        manifest["docs"].setdefault(doc.doc_id, {
            "title": doc.title, "url": doc.url, "source_type": doc.source_type,
            "role": role, "query": query, "added_at": now(),
        })

    @staticmethod
    def _decide(result: CollectResult, cand: Candidate, query: str, decision: str, reason: str) -> None:
        result.decisions.append(Decision(cand.doc_id, cand.title, query, decision, reason))


def _reason(e: Exception) -> str:
    if isinstance(e, SourceError):
        return e.code
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return f"HTTP {e.response.status_code}"
    return type(e).__name__
