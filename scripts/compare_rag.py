"""RAG 전후 비교 실행 (F2015) — 기획안 7장 질문을 근거 없이 · 근거와 함께 답하게 하고 저장한다.

    python -m scripts.compare_rag              # 질문 8개 전부 (GMS 호출: 질문당 약 4~5회)
    python -m scripts.compare_rag --only 3 7   # 일부만 — 같은 (번호, 버전)만 바꾸고 나머지는 실행 정보째 둔다

전체 실행은 이전 결과를 data/eval/archive/ 에 보관한 뒤 새로 쓴다.

결과: data/eval/rag_comparison.json — Streamlit 검증 페이지의 'RAG 전후 비교' 탭이 읽는다.
판정과 해설은 docs/05_rag_comparison.md 에 사람이 적는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from vasthorizon.config import get_settings
from vasthorizon.data.atomic import atomic_write_text
from vasthorizon.data.catalog import load_items
from vasthorizon.features.rag_compare import merge_results, run_all
from vasthorizon.llm import MissingApiKeyError
from vasthorizon.rag.pipeline import ask


def result_path():
    return get_settings().paths.data_dir / "eval" / "rag_comparison.json"


def archive_path(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return path.parent / "archive" / f"{path.stem}_{stamp}.json"


def main(argv: list[str] | None = None, items: list[dict] | None = None, ask_fn=None, llm=None,
         path: Path | None = None) -> int:
    """items · ask_fn · llm · path 는 테스트에서 가짜 질의응답 · LLM · 임시 파일을 넣기 위한 인자다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=int, nargs="*", help="질문 번호 (기획안 7장)")
    args = parser.parse_args(argv)
    try:
        data = run_all(items if items is not None else load_items(), ask_fn or ask, llm=llm,
                       only=set(args.only) if args.only else None)
    except MissingApiKeyError as e:
        print(f"[FAIL] {e}")
        return 1
    path = path or result_path()
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if args.only:
        data = merge_results(old, data)           # 나머지 문항은 실행 정보째 그대로
    elif old is not None:                          # 전체 실행 — 이전 결과는 지우지 않고 보관본으로
        archived = archive_path(path)
        archived.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(archived, json.dumps(old, ensure_ascii=False, indent=1))
        print(f"이전 결과 보관 → {archived}")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1))
    for r in data["rows"]:
        b, g = r["baseline"]["metrics"], r["rag"]["metrics"]
        run = r.get("run") or {}
        print(f"[{r['number']} v{r.get('question_version', 1)}] 인용 {b['citations']}→{g['citations']} · "
              f"RAG 상태 {r['rag']['status']} · 실행 {run.get('run_id', '정보 없음')}")
    print(f"[ OK ] {len(data['rows'])}건 → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
