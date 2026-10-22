"""관점 전환 서가 색인 (F2010) — 서가 문서(한국어 위키) → cosmos_perspective 컬렉션.

    python -m scripts.index_perspective             # 서가 문서를 받아(캐시 우선) 바뀐 청크만 반영
    python -m scripts.index_perspective --rebuild   # 임시 컬렉션에서 전체 재구축 후 교체
    python -m scripts.index_perspective --list      # 주제별 서가 문서 목록 (외부 호출 없음)

서가 문서 목록은 vasthorizon/data/perspective_library.py 에 있다.
"""

from __future__ import annotations

import argparse
import sys

from vasthorizon.data.perspective_library import THEMES
from vasthorizon.features.perspective import library_name, sync_library
from vasthorizon.llm import MissingApiKeyError
from vasthorizon.store import chroma
from vasthorizon.store.doc_index import DocIndexError


def main(argv: list[str] | None = None, embedding=None, db=None, collector=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true", help="임시 컬렉션에서 전체 재구축 후 교체한다")
    parser.add_argument("--list", action="store_true", help="주제별 서가 문서를 보여준다")
    args = parser.parse_args(argv)

    if args.list:
        for theme in THEMES.values():
            print(f"{theme.key:8} {theme.label:16} {' · '.join(theme.titles)}")
        return 0
    try:
        report, failures = sync_library(embedding, db, collector, rebuild=args.rebuild)
    except (MissingApiKeyError, chroma.EmbeddingMismatchError, DocIndexError) as e:
        print(f"[FAIL] {e} — 기존 서가 색인을 그대로 둡니다.")
        return 1
    for f in failures:
        print(f"[WARN] {f.message()}")
    print(f"서가 문서 {report.docs}개 · 청크 {report.chunks}개 "
          f"(임베딩 {report.embedded} · 메타데이터 갱신 {report.meta_updated} · 변경 없음 {report.unchanged} · "
          f"삭제 {report.deleted})")
    count = chroma.collection_count(library_name(), db)
    ok = not failures and count == report.chunks          # 못 받은 문서가 있으면 기존 청크가 남아 수가 다르다
    print(f"[{' OK ' if ok else 'WARN'}] {library_name()} 색인 {count}개")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
