"""테스트 공용 가짜 객체 — 외부 API · 토큰을 쓰지 않는다."""

from __future__ import annotations

import hashlib

from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage


class FakeChat:
    """응답을 차례로 돌려주고 받은 메시지를 기록하는 가짜 채팅 모델."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.received: list[list] = []

    def invoke(self, messages):
        self.received.append(messages)
        if not self.replies:
            raise AssertionError("예상하지 못한 LLM 호출")
        return AIMessage(self.replies.pop(0))


class FakeEmbedding(Embeddings):
    """결정적 가짜 임베딩. 호출 횟수 · 임베딩한 텍스트 수를 세고, fail_on_call번째 호출에서 실패할 수 있다."""

    def __init__(self, size: int | None = 16, model: str = "fake-a", vector_len: int | None = None,
                 fail_on_call: int | None = None):
        self.size, self.model = size, model
        self.vector_len = vector_len or size
        self.fail_on_call = fail_on_call
        self.calls = 0
        self.texts = 0

    def _vec(self, text: str) -> list[float]:
        digest = hashlib.sha256(f"{self.model}:{text}".encode()).digest()
        return [b / 255 for b in (digest * 4)[:self.vector_len]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.fail_on_call == self.calls:
            raise RuntimeError("임베딩 API 장애 (모의)")
        self.texts += len(texts)
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def catalog_has(qid: str) -> bool:
    """공용 카탈로그(data/items.json)에 그 항목이 있는가 — 실제 데이터에 기대는 테스트의 skip 조건.

    우리 은하 그룹(Q321 · Q237284)은 코드보다 데이터(python -m scripts.collect_items --only milky_way)가 늦게 들어온다.
    데이터가 들어오기 전에는 카탈로그 검증(그룹 milky_way 0건)이 실패하므로 그 테스트를 건너뛴다.
    """
    from vasthorizon.data.catalog import load_items
    try:
        return any(it.get("id") == qid for it in load_items())
    except (FileNotFoundError, KeyError, ValueError):
        return False


MILKY_WAY_IN_CATALOG = catalog_has("Q321") and catalog_has("Q237284")
SKIP_UNTIL_MILKY_WAY = "data/items.json에 우리 은하(Q321) · 궁수자리 A*(Q237284)가 아직 없다 — collect_items --only milky_way 뒤에 돈다"
