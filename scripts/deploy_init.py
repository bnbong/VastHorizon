"""배포 서버의 첫 준비 — 색인이 없으면 만든다. 서버를 띄우기 전에 한 번 실행한다 (Docker 진입점에서 자동).

    VH_CONFIG=config.deploy.toml python -m scripts.deploy_init            # 없는 색인만 만든다 (이미 있으면 바로 끝)
    VH_CONFIG=config.deploy.toml python -m scripts.deploy_init --rebuild  # 임베딩 모델을 바꿨을 때 전부 다시

저장소(GitHub)에는 색인(data/chroma)이 없다. 배포 서버는 설정한 임베딩(로컬 모델)으로 직접 만든다.
  1. 항목 색인 (data/items.json 424건) — 임베딩만, LLM 호출 없음
  2. 관점 전환 서가 색인 — 한국어 위키 문서를 받아(캐시 우선) 임베딩
문서 색인(cosmos_docs)은 비워 둔다. 질문할 때 그 천체의 문서를 모아 색인한다 (첫 질문은 조금 오래 걸린다).
키 값은 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import sys

from vasthorizon.config import get_settings
from vasthorizon.store import chroma


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true", help="항목 · 서가 색인을 모두 다시 만든다")
    parser.add_argument("--prefetch-model", action="store_true",
                        help="로컬 임베딩 모델만 내려받고 끝낸다 (Docker 이미지를 만들 때 — 첫 실행을 빠르게)")
    args = parser.parse_args(argv)
    s = get_settings()
    if args.prefetch_model:
        if s.llm.embedding_provider != "local":
            print("로컬 임베딩을 쓰지 않는 설정이라 내려받을 모델이 없습니다.")
            return 0
        from vasthorizon.llm import embeddings
        dim = len(embeddings().embed_query("우주"))
        print(f"로컬 임베딩 모델 준비 완료: {s.llm.local_embedding_model} ({dim}차원)")
        return 0
    print(f"설정 {s.config_path.name} · 제공자 {s.llm.provider} · 임베딩 {s.llm.embedding_provider} · 색인 {s.paths.chroma_dir}")

    from scripts import index_items, index_perspective
    status = 0
    if args.rebuild or chroma.collection_count(s.collections.items) == 0:
        print("항목 색인을 만듭니다…")
        status |= index_items.main(["--rebuild"] if args.rebuild else [])
    else:
        print(f"항목 색인 있음 ({chroma.collection_count(s.collections.items)}건)")
    if args.rebuild or chroma.collection_count(s.collections.perspective) == 0:
        print("관점 전환 서가 색인을 만듭니다…")
        status |= index_perspective.main(["--rebuild"] if args.rebuild else [])
    else:
        print(f"관점 전환 서가 색인 있음 ({chroma.collection_count(s.collections.perspective)}청크)")
    return status


if __name__ == "__main__":
    sys.exit(main())
