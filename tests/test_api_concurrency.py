"""API 동시성 테스트 — 서비스 초기화 · 대화 단위 처리 · 처리 중 기록 삭제.

threading.Event / Barrier로 실행 순서를 고정해 매번 같은 결과가 나오게 한다.
가짜 질의 함수만 쓰며 외부 API · 운영 데이터는 쓰지 않는다.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import json
import threading
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from tests.test_api import ITEMS, SESSION, FakeAsk, healthy, sse_events
from vasthorizon.api import app as app_module
from vasthorizon.api.app import create_app
from vasthorizon.api.services import Services
from vasthorizon.api.sessions import ConversationBusyError, SessionStore

TIMEOUT = 5


class GatedAsk(FakeAsk):
    """gate()로 지정한 질문은 release 될 때까지 멈춘다. 시작 여부는 started로 알 수 있다."""

    def __init__(self):
        super().__init__()
        self.started: dict[str, threading.Event] = {}
        self.release: dict[str, threading.Event] = {}
        self.fail: set[str] = set()

    def gate(self, question: str) -> None:
        self.started[question], self.release[question] = threading.Event(), threading.Event()

    def __call__(self, item, question, history=None, progress=None, search_type=None):
        if question in self.started:
            self.started[question].set()
            assert self.release[question].wait(TIMEOUT), "release 대기 시간 초과"
        if question in self.fail:
            self.calls.append({"item": item["id"], "question": question, "history": history})
            raise RuntimeError("질의 실패 (모의)")
        return super().__call__(item, question, history, progress, search_type)


def body(session=SESSION, item="Q48469", question="질문") -> dict:
    return {"session_id": session, "item_id": item, "question": question}


class ConcurrencyBase(unittest.TestCase):
    def setUp(self):
        self.ask = GatedAsk()
        self.client = TestClient(create_app(Services(items=ITEMS, ask=self.ask, health=healthy), web_dir=None),
                                 raise_server_exceptions=False)

    def in_thread(self, fn, *args) -> tuple[threading.Thread, dict]:
        out: dict = {}
        thread = threading.Thread(target=lambda: out.setdefault("response", fn(*args)))
        thread.start()
        return thread, out

    def start_gated(self, question: str, stream: bool = False, **kw):
        """질문을 별도 스레드로 보내고, 처리 함수 안에 들어갈 때까지 기다린다."""
        self.ask.gate(question)
        path = "/api/ask/stream" if stream else "/api/ask"
        thread, out = self.in_thread(lambda: self.client.post(path, json=body(question=question, **kw)))
        self.assertTrue(self.ask.started[question].wait(TIMEOUT))
        return thread, out

    def finish(self, question: str, thread: threading.Thread) -> None:
        self.ask.release[question].set()
        thread.join(TIMEOUT)
        self.assertFalse(thread.is_alive())

    def turns(self, item="Q48469", session=SESSION) -> list[dict]:
        return self.client.get(f"/api/history/{item}", params={"session_id": session}).json()["turns"]


# ── [P1] 1. 첫 동시 요청에서도 Services는 한 번만 만든다 ─────────────────────

class ServiceInitTest(unittest.TestCase):
    def test_concurrent_first_requests_share_one_service(self):
        created = []
        barrier = threading.Barrier(2)

        def factory():
            created.append(1)
            time.sleep(0.2)                      # 생성 중에 다른 요청이 들어올 틈을 만든다
            return Services(items=ITEMS, ask=FakeAsk(), health=healthy)

        with mock.patch.object(app_module, "default_services", side_effect=factory):
            client = TestClient(create_app(services=None, web_dir=None))
            results = {}

            def send(name, path, item):
                barrier.wait(TIMEOUT)
                results[name] = client.post(path, json=body(item=item, question=name))

            threads = [threading.Thread(target=send, args=("normal", "/api/ask", "Q48469")),
                       threading.Thread(target=send, args=("stream", "/api/ask/stream", "Q8860"))]
            for t in threads:
                t.start()
            for t in threads:
                t.join(TIMEOUT)

            self.assertEqual(len(created), 1)
            self.assertEqual({r.status_code for r in results.values()}, {200})
            voyager = client.get("/api/history/Q48469", params={"session_id": SESSION}).json()["turns"]
            orion = client.get("/api/history/Q8860", params={"session_id": SESSION}).json()["turns"]
            self.assertEqual(len(voyager) + len(orion), 4)          # 질문 · 답변 2쌍 모두 유지


# ── [P2] 2. 같은 대화는 한 번에 한 질문, 다른 대화는 독립 ─────────────────────

class ConversationPolicyTest(ConcurrencyBase):
    def test_same_conversation_rejected_while_busy(self):
        thread, out = self.start_gated("first")
        second = self.client.post("/api/ask", json=body(question="second"))
        self.assertEqual((second.status_code, second.json()["code"]), (409, "conversation_busy"))
        stream = self.client.post("/api/ask/stream", json=body(question="second"))
        self.assertEqual((stream.status_code, stream.json()["code"]), (409, "conversation_busy"))
        self.finish("first", thread)
        self.assertEqual(out["response"].status_code, 200)

    def test_other_conversations_run_independently(self):
        thread, _ = self.start_gated("first")
        other_item = self.client.post("/api/ask", json=body(item="Q8860", question="orion"))
        other_session = self.client.post("/api/ask", json=body(session="other-session-1", question="other"))
        self.assertEqual((other_item.status_code, other_session.status_code), (200, 200))
        self.finish("first", thread)

    def test_next_question_sees_previous_answer(self):
        thread, _ = self.start_gated("first")
        self.finish("first", thread)
        self.client.post("/api/ask", json=body(question="second"))
        second_call = next(c for c in self.ask.calls if c["question"] == "second")
        self.assertEqual([h["content"] for h in second_call["history"]], ["first", "first에 대한 답 [근거 2]"])
        self.assertEqual([t["content"] for t in self.turns() if t["role"] == "user"], ["first", "second"])

    def test_failure_releases_conversation(self):
        self.ask.fail.add("boom")
        with self.assertLogs("vasthorizon.api.app", "ERROR"):
            failed = self.client.post("/api/ask", json=body(question="boom"))
            failed_stream = sse_events(self.client.post("/api/ask/stream", json=body(question="boom")).text)
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed_stream[-1][0], "error")
        ok = self.client.post("/api/ask", json=body(question="after"))
        self.assertEqual(ok.status_code, 200)
        self.assertEqual([t["content"] for t in self.turns() if t["role"] == "user"], ["after"])


# ── [P2] 3. 처리 중 기록 삭제 — 이전 질문은 기록되지 않는다 ───────────────────

class ClearWhileRunningTest(ConcurrencyBase):
    def setUp(self):
        super().setUp()
        self.client.post("/api/ask", json=body(item="Q8860", question="orion"))       # 다른 대화 기록

    def test_clear_during_normal_request(self):
        thread, out = self.start_gated("old")
        self.assertEqual(self.client.delete("/api/history/Q48469", params={"session_id": SESSION}).status_code, 204)
        new = self.client.post("/api/ask", json=body(question="new"))                # 삭제 직후 새 질문 가능
        self.assertEqual((new.status_code, new.json()["recorded"]), (200, True))
        self.finish("old", thread)
        old = out["response"].json()
        self.assertEqual((out["response"].status_code, old["recorded"]), (200, False))
        self.assertIn("기록에 남지 않습니다", old["warnings"][-1])
        self.assertEqual([t["content"] for t in self.turns() if t["role"] == "user"], ["new"])
        self.assertEqual(len(self.turns(item="Q8860")), 2)                              # 다른 대화는 그대로

    def test_clear_during_stream_request(self):
        thread, out = self.start_gated("old", stream=True)
        self.client.delete("/api/history/Q48469", params={"session_id": SESSION})
        self.finish("old", thread)
        result = sse_events(out["response"].text)[-1]
        self.assertEqual((result[0], result[1]["recorded"]), ("result", False))
        self.assertEqual(self.turns(), [])
        self.assertEqual(len(self.turns(item="Q8860")), 2)


# ── SessionStore 단위 ─────────────────────────────────────────────────────

class SessionStoreTest(unittest.TestCase):
    def test_generation_and_release(self):
        store = SessionStore()
        t1 = store.begin("s", "Q1")
        with self.assertRaises(ConversationBusyError):
            store.begin("s", "Q1")
        store.clear("s", "Q1")
        t2 = store.begin("s", "Q1")                         # 새 세대는 이전 세대 처리 중 표시에 막히지 않는다
        self.assertFalse(store.finish(t1, {"role": "user", "content": "old"}))
        self.assertTrue(store.finish(t2, {"role": "user", "content": "new"}))
        self.assertEqual([t["content"] for t in store.history("s", "Q1")], ["new"])
        t3 = store.begin("s", "Q1")
        store.abort(t3)
        store.begin("s", "Q1")                              # abort 뒤 다시 시작할 수 있다

    def test_turns_trimmed(self):
        store = SessionStore(max_turns=4)
        for i in range(5):
            store.finish(store.begin("s", "Q1"), {"role": "user", "content": str(i)}, {"role": "assistant", "content": "a"})
        self.assertEqual(len(store.history("s", "Q1")), 4)


if __name__ == "__main__":
    unittest.main()
