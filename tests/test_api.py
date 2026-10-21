"""API 테스트 (F2009 · F2012 · F2013) — 가짜 질의 함수 · 항목으로 앱을 만든다. 외부 호출 없음.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import contextlib
import json
import unittest

from fastapi.testclient import TestClient

from vasthorizon.api.app import create_app
from vasthorizon.api.schemas import HealthResponse, Notice
from vasthorizon.api.services import Services
from vasthorizon.llm import MissingApiKeyError
from vasthorizon.rag.pipeline import AnswerResult, Stage
from vasthorizon.rag.retrieval import Evidence, IndexMissingError
from vasthorizon.store.chroma import EmbeddingMismatchError

SESSION = "test-session-01"
ITEMS = [
    {"id": "Q48469", "name": "보이저 1호", "name_en": "Voyager 1", "group": "human_made", "kind": "우주 탐사선",
     "wiki_title": "보이저 1호", "attrs": {"국가": "미국"}, "distance": {"km": 2.5e10, "ly": 0.0027},
     "ra_deg": None, "dec_deg": None, "sources": [{"name": "Wikidata", "url": "https://www.wikidata.org/wiki/Q48469"}]},
    {"id": "Q8860", "name": "오리온자리", "name_en": "Orion", "group": "constellation", "kind": "별자리",
     "wiki_title": "오리온자리", "attrs": {}, "distance": None, "ra_deg": 83.0, "dec_deg": 5.0, "sources": []},
]


def evidence(n: int) -> Evidence:
    return Evidence(number=n, chunk_id=f"c{n}", kind="외부 문서", source_type="위키백과", title="태양권계면",
                    section="경계", url="https://ko.wikipedia.org/wiki/x", text="[태양권계면 > 경계]\n" + "본문 " * 200)


class FakeAsk:
    def __init__(self, status="cited", error: Exception | None = None):
        self.status, self.error = status, error
        self.calls: list[dict] = []

    def __call__(self, item, question, history=None, progress=None, search_type=None):
        self.calls.append({"item": item["id"], "question": question, "history": history, "search_type": search_type})
        if progress:
            progress("관련 문서를 찾는 중")
            progress("근거를 모아 답변을 쓰는 중")
        if self.error:
            raise self.error
        cited = [evidence(2)] if self.status == "cited" else []
        return AnswerResult(question=question, answer=f"{question}에 대한 답 [근거 2]", status=self.status,
                            cited=cited, evidences=[evidence(1), evidence(2)],
                            stages={"collect": Stage("ok", 1.234), "answer": Stage("ok", 2.0)},
                            warnings=["새 문서 색인 실패(임베딩 API 연결 오류) — 이미 색인된 근거로 답합니다."])


def healthy() -> HealthResponse:
    return HealthResponse(ready=True, gms_key=True, items_loaded=2, items_indexed=2, docs_indexed=10)


class ApiTestBase(unittest.TestCase):
    def client(self, ask=None, health=healthy) -> TestClient:
        self.ask = ask or FakeAsk()
        app = create_app(Services(items=ITEMS, ask=self.ask, health=health), web_dir=None)
        return TestClient(app, raise_server_exceptions=False)

    def post_ask(self, client, item_id="Q48469", question="태양계를 벗어났나?", **extra):
        return client.post("/api/ask", json={"session_id": SESSION, "item_id": item_id, "question": question, **extra})


class ItemsApiTest(ApiTestBase):
    def test_list_and_filter(self):
        c = self.client()
        self.assertEqual(len(c.get("/api/items").json()), 2)
        self.assertEqual([i["id"] for i in c.get("/api/items", params={"group": "constellation"}).json()], ["Q8860"])
        self.assertEqual([i["name"] for i in c.get("/api/items", params={"q": "voyager"}).json()], ["보이저 1호"])

    def test_detail_and_404(self):
        c = self.client()
        body = c.get("/api/items/Q48469").json()
        self.assertEqual((body["group_ko"], body["distance_ly"], body["sources"][0]["name"]), ("인류의 발자취", 0.0027, "Wikidata"))
        r = c.get("/api/items/Q404")
        self.assertEqual((r.status_code, r.json()["code"]), (404, "item_not_found"))


class AskApiTest(ApiTestBase):
    def test_answer_shape(self):
        body = self.post_ask(self.client()).json()
        self.assertEqual((body["status"], body["notice"]), ("cited", None))
        self.assertEqual(body["cited"][0]["number"], 2)
        self.assertLessEqual(len(body["cited"][0]["excerpt"]), 200)
        self.assertFalse(body["cited"][0]["excerpt"].startswith("["))              # 머리말은 뺀 본문
        self.assertEqual(body["stages"]["collect"], {"status": "ok", "seconds": 1.23})
        self.assertIn("연결 오류", body["warnings"][0])

    def test_no_citation_notices(self):
        self.assertEqual(self.post_ask(self.client(FakeAsk("not_found"))).json()["notice"],
                         "문서에서 확인되지 않아 인용된 근거가 없습니다.")
        rejected = self.post_ask(self.client(FakeAsk("rejected"))).json()
        self.assertIn("규칙", rejected["notice"])
        self.assertEqual(rejected["cited"], [])

    def test_search_type_passed(self):
        c = self.client()
        self.post_ask(c, search_type="mmr")
        self.assertEqual(self.ask.calls[0]["search_type"], "mmr")

    def test_invalid_request(self):
        c = self.client()
        for bad in ({"question": ""}, {"session_id": "짧음"}, {"item_id": "abc"}, {"question": "x" * 501}):
            r = c.post("/api/ask", json={"session_id": SESSION, "item_id": "Q48469", "question": "q", **bad})
            self.assertEqual((r.status_code, r.json()["code"]), (422, "invalid_request"), bad)
        self.assertEqual(self.ask.calls, [])


# ── F2009 항목별 대화 기록 ─────────────────────────────────────────────────

class HistoryApiTest(ApiTestBase):
    def test_history_kept_per_item(self):
        c = self.client()
        self.post_ask(c, "Q48469", "첫 질문")
        self.post_ask(c, "Q8860", "오리온 질문")
        self.post_ask(c, "Q48469", "두 번째 질문")
        voyager = c.get("/api/history/Q48469", params={"session_id": SESSION}).json()["turns"]
        orion = c.get("/api/history/Q8860", params={"session_id": SESSION}).json()["turns"]
        self.assertEqual([t["content"] for t in voyager if t["role"] == "user"], ["첫 질문", "두 번째 질문"])
        self.assertEqual([t["content"] for t in orion if t["role"] == "user"], ["오리온 질문"])
        self.assertEqual(voyager[1]["cited"][0]["number"], 2)
        # 세 번째 질문에는 보이저 1호의 이전 대화만 넘어간다 — 다른 항목 대화가 섞이지 않는다
        self.assertEqual([h["content"] for h in self.ask.calls[2]["history"]],
                         ["첫 질문", "첫 질문에 대한 답 [근거 2]"])

    def test_sessions_isolated_and_clear(self):
        c = self.client()
        self.post_ask(c)
        other = c.get("/api/history/Q48469", params={"session_id": "another-session"}).json()["turns"]
        self.assertEqual(other, [])
        self.assertEqual(c.delete("/api/history/Q48469", params={"session_id": SESSION}).status_code, 204)
        self.assertEqual(c.get("/api/history/Q48469", params={"session_id": SESSION}).json()["turns"], [])


# ── F2012 진행 상태 · 오류 안내 ────────────────────────────────────────────

def sse_events(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


class StreamAndErrorTest(ApiTestBase):
    def stream(self, client, item_id="Q48469"):
        return client.post("/api/ask/stream", json={"session_id": SESSION, "item_id": item_id, "question": "질문"})

    def test_stream_progress_then_result(self):
        events = sse_events(self.stream(self.client()).text)
        self.assertEqual([e for e, _ in events], ["progress", "progress", "result"])
        self.assertEqual(events[0][1]["message"], "관련 문서를 찾는 중")
        self.assertEqual(events[-1][1]["status"], "cited")

    def test_stream_unknown_item_is_404_before_streaming(self):
        r = self.stream(self.client(), "Q404")
        self.assertEqual((r.status_code, r.json()["code"]), (404, "item_not_found"))

    def test_errors_mapped_without_internals(self):
        cases = {
            MissingApiKeyError(): (503, "missing_key"),
            IndexMissingError("항목 색인(cosmos_items)이 없습니다. python -m scripts.index_items 를 실행하세요."): (503, "index_missing"),
            EmbeddingMismatchError("임베딩 모델 불일치 — 컬렉션 A, 현재 설정 B"): (503, "index_incompatible"),
            RuntimeError("secret=sk-abc123 at C:\\path\\file.py line 9"): (500, "internal"),
        }
        for error, (status, code) in cases.items():
            with self.subTest(code=code):
                c = self.client(FakeAsk(error=error))
                # 알 수 없는 오류의 자세한 내용은 서버 로그에만 남는다
                logs = self.assertLogs("vasthorizon.api.app", "ERROR") if code == "internal" else contextlib.nullcontext()
                with logs:
                    r = self.post_ask(c)
                    last = sse_events(self.stream(c).text)[-1]             # 스트림에서도 같은 안내
                self.assertEqual((r.status_code, r.json()["code"]), (status, code))
                self.assertNotIn("sk-abc123", r.text)
                self.assertNotIn("Traceback", r.text)
                self.assertNotIn("file.py", r.text)
                self.assertEqual((last[0], last[1]["code"]), ("error", code))
                self.assertNotIn("sk-abc123", json.dumps(last[1]))

    def test_health_notices(self):
        def broken():
            return HealthResponse(ready=False, gms_key=False, items_loaded=2, items_indexed=0, docs_indexed=0,
                                  notices=[Notice(code="missing_key", level="error", message="키 없음")])
        body = self.client(health=broken).get("/api/health").json()
        self.assertFalse(body["ready"])
        self.assertEqual(body["notices"][0]["code"], "missing_key")
        self.assertNotIn("GMS_KEY=", json.dumps(body))

    def test_real_health_check_hides_key(self):
        from unittest import mock
        from vasthorizon.api import services as svc_module
        with mock.patch("vasthorizon.config.get_gms_key", return_value=None), \
                mock.patch("vasthorizon.store.chroma.collection_count", return_value=0):
            health = svc_module.check_health(items_loaded=424)
        codes = {n.code for n in health.notices}
        self.assertEqual(codes, {"missing_key", "index_missing", "docs_index_empty"})
        self.assertFalse(health.ready)

    def test_openapi_documents_schemas(self):
        spec = self.client().get("/openapi.json").json()
        self.assertIn("AnswerResponse", spec["components"]["schemas"])
        self.assertIn("/api/ask/stream", spec["paths"])


if __name__ == "__main__":
    unittest.main()
