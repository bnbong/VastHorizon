"""로컬 임베딩 모델만 미리 내려받는다 — Docker 이미지를 만들 때, 소스를 COPY하기 전에 실행한다.

    python scripts/prefetch_model.py config.deploy.toml            # 설정의 모델을 FASTEMBED_CACHE_PATH에 받아 둔다
    python scripts/prefetch_model.py config.deploy.toml --dry-run  # 받을 모델 이름만 출력 (fastembed를 불러오지 않음)

vasthorizon 패키지에 의존하지 않는다 (표준 라이브러리 tomllib + fastembed). 그래서 Dockerfile에서 설정 파일과
이 파일만 먼저 넣고 모델을 받으면, 소스가 바뀌어도 모델 레이어(2.2GB)는 캐시에서 그대로 쓴다.
기본값은 vasthorizon/config.py의 LLMConfig와 같아야 한다 (설정에 값이 없을 때 실행 중에 쓰는 모델과 맞추기 위해).
"""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

DEFAULT_EMBEDDING_PROVIDER = "gms"
DEFAULT_LOCAL_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"


def model_to_prefetch(config_path: Path) -> str | None:
    """설정에서 받아 둘 로컬 임베딩 모델 이름. 로컬 임베딩을 쓰지 않으면 None."""
    with config_path.open("rb") as f:
        llm = tomllib.load(f).get("llm", {})
    if llm.get("embedding_provider", DEFAULT_EMBEDDING_PROVIDER) != "local":
        return None
    return llm.get("local_embedding_model", DEFAULT_LOCAL_EMBEDDING_MODEL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path, help="설정 파일 (예: config.deploy.toml)")
    parser.add_argument("--dry-run", action="store_true", help="받을 모델 이름만 출력하고 끝낸다")
    args = parser.parse_args(argv)
    model = model_to_prefetch(args.config)
    if model is None:
        print("로컬 임베딩을 쓰지 않는 설정이라 내려받을 모델이 없습니다.")
        return 0
    if args.dry_run:
        print(model)
        return 0
    from fastembed import TextEmbedding
    TextEmbedding(model_name=model)
    print(f"로컬 임베딩 모델 준비 완료: {model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
