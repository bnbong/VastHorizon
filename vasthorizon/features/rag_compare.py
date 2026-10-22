"""RAG 전후 비교 (F2015) — 같은 질문을 근거 없이 · 근거와 함께 답하게 하고 나란히 기록한다.

| 쪽       | 방법                                                             |
|----------|------------------------------------------------------------------|
| RAG 없이 | 같은 모델 · 말투 · 길이, 근거 문서 없이 (prompts.BASELINE_SYSTEM) |
| RAG      | 서비스 질의응답 전체 — 문서 수집 · 색인 · 검색 · 인용 검증 (pipeline.ask) |

질문은 기획안 7장 '근거가 필요한 질문'이다 — 근거 없이 답하면 틀리기 쉬운 질문.
결과는 data/eval/rag_comparison.json 에 남기고, 판정(맞음 · 틀림 · 확인 불가와 그 사유)은 사람이 근거와 대조해
docs/05_rag_comparison.md 에 적는다. 자동 지표(인용 수 · 수치 포함 · 확인되지 않음 표현)는 판정의 보조다.

결과 형식 (schema 2)
- 문항마다 실행 정보(run)를 둔다 — 실행 ID · 시각 · 모델 · 검색 · 청킹 설정 · 프롬프트 지문 · 코드 버전.
  같은 조건이면 conditions_id 가 같다. 부분 재실행으로 합쳐도 기존 문항의 실행 정보는 그대로 남는다.
- 문항은 (번호, 버전)으로 구분한다. 질문을 고치면 버전을 올려, 고치기 전 결과와 섞이지 않게 한다.
- 실행 정보가 없는 이전 형식의 문항은 run=None 그대로 둔다 (현재 설정으로 추정해 채우지 않는다).
(F2015 리뷰 P2)
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from langchain_core.language_models import BaseChatModel

from vasthorizon.config import PROJECT_ROOT, get_settings
from vasthorizon.rag.graph import default_chat_model, is_not_found
from vasthorizon.rag.prompts import ANSWER_SYSTEM, BASELINE_SYSTEM, baseline_messages

SCHEMA = 2

# 기획안 7장 — (번호, 문항 버전, 기준 항목 이름, 질문). 항목은 질의응답의 범위(근거 1 · 문서 수집 대상)를 정한다.
# 6번 v1 "내 생일에 태양은 정말 내 '별자리'에 있었나?"는 생일 날짜 · 기준이 없어 답할 수 없는 질문이었다
# (RAG 답: "생일 날짜와 기준으로 삼는 별자리가 제시되지 않아 판단할 수 없습니다"). v2는 날짜 · 기준을 담은 일반 개념 질문.
QUESTIONS = [
    (1, 1, "아리랑 1호", "아리랑 1호는 지금도 지구를 돌고 있나?"),
    (2, 1, "제임스 웹 우주망원경", "제임스 웹 망원경은 허블처럼 지구를 도나?"),
    (3, 1, "보이저 1호", "보이저 1호는 태양계를 벗어났나?"),
    (4, 1, "플레이아데스 성단", "지금 보는 플레이아데스의 빛은 언제 출발했나?"),
    (5, 1, "오리온자리", "오리온자리 별들은 서로 가까이 모여 있나?"),
    (6, 2, "태양", "점성술의 양자리 날짜(3월 21일~4월 19일)에 태양은 실제로 양자리 앞에 있나?"),
    (7, 1, "알타이르", "견우성과 직녀성은 실제로 얼마나 떨어져 있나?"),
    (8, 1, "오리온자리", "천상열차분야지도는 무엇을 담은 유물인가?"),
]

_NUMBER = re.compile(r"\d[\d,.]*")
_CITE = re.compile(r"\[근거\s*\d")
_CITE_FULL = re.compile(r"\[근거\s*[\d,\s]+\]")


def metrics(answer: str) -> dict:
    """판정 보조 지표 — 인용 수 · 수치 개수 · '확인되지 않음' 표현 · 길이."""
    body = _CITE_FULL.sub("", answer)              # 수치는 본문에서만 — [근거 N]의 번호는 세지 않는다
    return {"citations": len(_CITE.findall(answer)), "numbers": len(_NUMBER.findall(body)),
            "not_found": is_not_found(answer), "chars": len(answer)}


# ── 실행 정보 ─────────────────────────────────────────────────────────────

def code_version() -> str | None:
    """git 커밋 (작업 중 변경이 있으면 +dirty). git을 쓸 수 없으면 None — 추정하지 않는다."""
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT, capture_output=True,
                             text=True, timeout=5, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=PROJECT_ROOT,
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return f"{sha}+dirty" if dirty else sha
    except (OSError, subprocess.SubprocessError):
        return None


def run_info(run_id: str | None = None, started_at: str | None = None) -> dict:
    """이번 실행의 비교 조건. conditions_id 는 결과에 영향을 주는 조건만으로 만든다 (시각 · 코드 버전 제외)."""
    s = get_settings()
    conditions = {
        "chat_model": s.llm.chat_model,
        "embedding_model": s.llm.embedding_model,
        "retrieval": {"search_type": s.retrieval.search_type, "top_k": s.retrieval.top_k_docs,
                      "fetch_k": s.retrieval.mmr_fetch_k, "lambda": s.retrieval.mmr_lambda},
        "chunking": {"size": s.chunking.chunk_size, "overlap": s.chunking.chunk_overlap},
        "prompts": hashlib.sha256((BASELINE_SYSTEM + "\n" + ANSWER_SYSTEM).encode("utf-8")).hexdigest()[:12],
    }
    return {"run_id": run_id or uuid.uuid4().hex[:8],
            "started_at": started_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "code_version": code_version(), **conditions,
            "conditions_id": hashlib.sha256(json.dumps(conditions, sort_keys=True).encode()).hexdigest()[:10]}


# ── 비교 ──────────────────────────────────────────────────────────────────

def baseline_answer(item_name: str, question: str, llm: BaseChatModel | None = None) -> dict:
    t = time.perf_counter()
    reply = default_chat_model(llm).invoke(baseline_messages(item_name, question))
    return {"answer": reply.content, "seconds": round(time.perf_counter() - t, 2), "metrics": metrics(reply.content)}


def rag_answer(item: dict, question: str, ask: Callable) -> dict:
    t = time.perf_counter()
    result = ask(item, question)
    return {"answer": result.answer, "raw_answer": getattr(result, "raw_answer", None) or result.answer,
            "status": result.status, "seconds": round(time.perf_counter() - t, 2),
            "cited": [{"number": ev.number, "title": ev.title, "section": ev.section, "kind": ev.kind,
                       "source_type": ev.source_type, "url": ev.url, "excerpt": ev.text[:300]} for ev in result.cited],
            "warnings": result.warnings, "metrics": metrics(result.answer)}


def compare_one(number: int, item: dict, question: str, ask: Callable, llm: BaseChatModel | None = None,
                version: int = 1, run: dict | None = None) -> dict:
    return {"number": number, "question_version": version, "item_id": item["id"], "item_name": item["name"],
            "question": question, "run": run,
            "baseline": baseline_answer(item["name"], question, llm), "rag": rag_answer(item, question, ask)}


def run_all(items: list[dict], ask: Callable, llm: BaseChatModel | None = None,
            only: set[int] | None = None, progress: Callable[[str], None] | None = None, run: dict | None = None) -> dict:
    progress = progress or print
    run = run or run_info()
    by_name = {it["name"]: it for it in items}
    rows = []
    for number, version, name, question in QUESTIONS:
        if only and number not in only:
            continue
        progress(f"[{number} v{version}] {name} — {question}")
        rows.append(compare_one(number, by_name[name], question, ask, llm, version=version, run=run))
    return {"schema": SCHEMA, "rows": rows}


def row_key(row: dict) -> tuple[int, int]:
    return row["number"], row.get("question_version", 1)


def merge_results(old: dict | None, new: dict) -> dict:
    """부분 재실행 병합 — 같은 (번호, 버전)만 새 결과로 바꾸고, 나머지 문항은 실행 정보째 그대로 둔다.

    질문 버전이 다르면 다른 문항이다 — 고치기 전 결과를 덮어쓰지 않고 함께 남긴다.
    이전 형식(schema 1)의 문항은 실행 정보가 없으므로 run=None 으로 둔다.
    """
    rows = {}
    for row in (old or {}).get("rows", []):
        row = dict(row)
        row.setdefault("question_version", 1)
        row.setdefault("run", None)                  # 이전 형식 — 추정해 채우지 않는다
        rows[row_key(row)] = row
    for row in new["rows"]:
        rows[row_key(row)] = row
    return {"schema": SCHEMA, "rows": [rows[k] for k in sorted(rows)]}


def conditions_summary(rows: list[dict]) -> dict:
    """화면 표시용 — 결과에 섞인 실행 조건들. mixed 가 참이면 서로 다른 조건(또는 실행 정보 없음)이 섞였다."""
    groups: dict[str, dict] = {}
    unknown = []
    for row in rows:
        run = row.get("run")
        if not run:
            unknown.append(row["number"])
            continue
        g = groups.setdefault(run["conditions_id"], {"run": run, "numbers": [], "run_ids": set()})
        g["numbers"].append(row["number"])
        g["run_ids"].add(run["run_id"])
    return {"groups": list(groups.values()), "unknown": unknown, "mixed": len(groups) + bool(unknown) > 1}
