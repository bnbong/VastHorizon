"""항목별 대화 기록 (F2009) — (세션, 항목)마다 따로 유지하고, 대화 단위로 요청을 제어한다.

대화 = (session_id, item_id). 세션 ID는 브라우저가 만들어 보낸다.

요청 처리 정책
- 한 대화에는 한 번에 한 질문만 처리한다. 처리 중에 같은 대화로 질문이 오면
  ConversationBusyError(HTTP 409)로 거절한다. 다른 대화는 서로 기다리지 않는다.
- 질문은 begin()으로 시작해 그 시점의 기록(history)을 받고, finish()로 기록을 남긴다.
  예외가 나면 abort()로 처리 중 표시만 푼다 — 어떤 경우에도 다음 요청이 막히지 않는다.

삭제 정책 — 세대 번호
- 대화마다 세대 번호가 있다. clear()는 기록을 지우고 세대를 올린다.
- 삭제 전에 시작한 질문(이전 세대)은 끝나도 기록을 남기지 않는다 — finish()가 False를 돌려준다.
  답변 자체는 화면에 돌려주되, 기록되지 않았다고 알린다.
- 세대가 바뀌면 이전 세대의 처리 중 표시는 새 질문을 막지 않는다 — 삭제 직후 바로 새 질문을 할 수 있다.

보관
- 서버 메모리에만 둔다. 오래된 세션부터 지우고, 대화마다 최근 MAX_TURNS개만 남긴다.
- 서버를 다시 시작하면 기록은 사라진다 (개인 대화를 디스크에 남기지 않는다).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field

MAX_SESSIONS = 200
MAX_TURNS = 40          # 질문 · 답변 각각을 한 턴으로 센다


class ConversationBusyError(RuntimeError):
    """같은 대화의 이전 질문을 아직 처리하는 중이다."""


@dataclass
class _Conversation:
    log: list[dict] = field(default_factory=list)
    generation: int = 0
    active: int | None = None          # 처리 중인 질문의 세대 (없으면 None)


@dataclass(frozen=True)
class Ticket:
    """begin()이 돌려주는 질문 처리권. 시작 시점의 세대와 기록을 담는다."""

    session_id: str
    item_id: str
    generation: int
    history: tuple[dict, ...]


class SessionStore:
    def __init__(self, max_sessions: int = MAX_SESSIONS, max_turns: int = MAX_TURNS) -> None:
        self._sessions: OrderedDict[str, dict[str, _Conversation]] = OrderedDict()
        self._lock = threading.Lock()
        self.max_sessions, self.max_turns = max_sessions, max_turns

    def _conversation(self, session_id: str, item_id: str, create: bool) -> _Conversation | None:
        items = self._sessions.get(session_id)
        if items is None:
            if not create:
                return None
            items = self._sessions[session_id] = {}
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)
        self._sessions.move_to_end(session_id)
        if item_id not in items and create:
            items[item_id] = _Conversation()
        return items.get(item_id)

    def history(self, session_id: str, item_id: str) -> list[dict]:
        with self._lock:
            conv = self._conversation(session_id, item_id, create=False)
            return [dict(t) for t in conv.log] if conv else []

    def begin(self, session_id: str, item_id: str) -> Ticket:
        """질문 처리를 시작한다. 같은 대화(같은 세대)가 처리 중이면 ConversationBusyError."""
        with self._lock:
            conv = self._conversation(session_id, item_id, create=True)
            if conv.active == conv.generation:
                raise ConversationBusyError(f"{session_id}/{item_id}")
            conv.active = conv.generation
            return Ticket(session_id, item_id, conv.generation, tuple(dict(t) for t in conv.log))

    def finish(self, ticket: Ticket, *turns: dict) -> bool:
        """기록을 남기고 처리 중 표시를 푼다. 시작 뒤에 기록이 지워졌으면 남기지 않고 False."""
        with self._lock:
            conv = self._conversation(ticket.session_id, ticket.item_id, create=False)
            if conv is None:                                  # 세션이 밀려나 사라졌다
                return False
            if conv.active == ticket.generation:
                conv.active = None
            if conv.generation != ticket.generation:
                return False
            conv.log.extend(turns)
            del conv.log[:-self.max_turns]
            return True

    def abort(self, ticket: Ticket) -> None:
        """기록 없이 처리 중 표시만 푼다 (예외로 끝난 질문)."""
        with self._lock:
            conv = self._conversation(ticket.session_id, ticket.item_id, create=False)
            if conv is not None and conv.active == ticket.generation:
                conv.active = None

    def clear(self, session_id: str, item_id: str) -> None:
        """기록을 지우고 세대를 올린다. 진행 중인 이전 세대 질문은 끝나도 기록되지 않는다."""
        with self._lock:
            conv = self._conversation(session_id, item_id, create=False)
            if conv is not None:
                conv.log.clear()
                conv.generation += 1
