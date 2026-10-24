"""배포 서버의 준비 — 색인이 없으면 만들고, 임베딩 모델이 바뀌었으면 다시 만든다. 서버를 띄우기 전에 실행한다 (Docker 진입점에서 자동).

    VH_CONFIG=config.deploy.toml python -m scripts.deploy_init                   # 없는 색인 만들기 + 모델이 바뀐 색인 다시 만들기
    VH_CONFIG=config.deploy.toml python -m scripts.deploy_init --rebuild         # 세 색인을 모두 강제로 다시
    VH_CONFIG=config.deploy.toml python -m scripts.deploy_init --prefetch-model  # 로컬 임베딩 모델만 내려받기 (컨테이너 없이 직접 실행할 때)

저장소(GitHub)에는 색인(data/chroma)이 없다. 배포 서버는 설정한 임베딩(로컬 모델)으로 직접 만든다.
  1. 항목 색인 (data/items.json 424건) — 임베딩만, LLM 호출 없음
  2. 관점 전환 서가 색인 — 한국어 위키 문서를 받아(캐시 우선) 임베딩
  3. 문서 색인(cosmos_docs) — 처음에는 비어 있고, 질문할 때 그 천체의 문서를 모아 색인한다.
     임베딩 모델이 바뀌면 이미 모은 문서를 캐시에서 꺼내 새 모델로 다시 색인한다 (문서를 다시 받지 않는다)
색인마다 만들 때의 임베딩 모델을 기록해 두므로(store/chroma.py), 지금 설정과 다르면 알아채고 다시 만든다.
항목 색인에는 색인한 카탈로그 내용의 해시(catalog_hash — data/items.json + enrich.json 보강 + 색인 텍스트 생성 코드의 결과)도
기록한다. 건수 · 모델이 같아도 해시가 다르거나 없으면(예전 색인) 항목 색인을 다시 만든다 — 새 메타데이터(고리 · 블랙홀 등)가 반영되게.
항목 · 서가 색인은 끝까지 성공했을 때만 완성 표식(index_complete · index_count)을 남긴다. 건수가 있어도 표식이 없거나
기록된 건수 · 카탈로그 건수와 다르면 도중에 끊긴 색인(메모리 부족으로 죽은 첫 실행 등)으로 보고 다시 만든다.
다시 만들기는 임시 컬렉션에서 끝까지 만든 뒤 바꿔 넣는다 — 실패하면 기존 색인이 남고, 이 스크립트는 1로 끝난다.
키 값은 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import sys

from vasthorizon.config import get_settings
from vasthorizon.llm import MissingApiKeyError
from vasthorizon.store import chroma


def stale_collections(names: list[str], embedding, db=None) -> list[str]:
    """비어 있지 않은데 지금 임베딩 설정과 맞지 않는 컬렉션 (모델 · 차원이 다르거나 식별 정보가 없는 예전 색인)."""
    identity = chroma.embedding_identity(embedding)
    stale = []
    for name in names:
        if chroma.collection_count(name, db) == 0:
            continue
        try:
            chroma.check_identity(chroma.db_for(name, db).get_collection(name), identity)
        except chroma.EmbeddingMismatchError:
            stale.append(name)
    return stale


def incomplete_reason(name: str, db=None, expected: int | None = None) -> str | None:
    """도중에 끊긴 색인이면 '200/424건' 같은 설명, 완성됐거나 비어 있으면 None.

    완성 표식이 없거나, 기록된 건수 · 기대 건수(항목 색인은 카탈로그 건수)가 실제 건수와 다르면 불완전하다.
    """
    count = chroma.collection_count(name, db)
    if count == 0:
        return None
    recorded = chroma.recorded_count(name, db)
    if recorded == count and expected in (None, count):
        return None
    target = expected if expected is not None else recorded
    return f"{count}/{target}건" if target is not None else f"{count}건, 완성 표식 없음"


def catalog_size() -> int | None:
    """data/items.json의 항목 수. 읽을 수 없으면 None (그때는 완성 표식만 본다)."""
    from vasthorizon.data.catalog import load_catalog
    try:
        return len(load_catalog().get("items", []))
    except (FileNotFoundError, ValueError):
        return None


def expected_catalog_hash() -> str | None:
    """지금 카탈로그(보강 포함)로 색인하면 남을 catalog_hash. 읽을 수 없으면 None (그때는 비교하지 않는다)."""
    from vasthorizon.data.catalog import load_catalog
    from vasthorizon.data.enrich import enrich_items
    from vasthorizon.store.item_index import catalog_hash
    try:
        catalog = load_catalog()
        return catalog_hash(enrich_items(catalog.get("items", [])), int(catalog["meta"]["collected_at"][:4]))
    except (FileNotFoundError, ValueError, KeyError):
        return None


def catalog_outdated(name: str, db=None, expected: str | None = None) -> bool:
    """비어 있지 않은 항목 색인의 catalog_hash가 지금 카탈로그와 다른가 (해시가 없는 예전 색인도 다르다고 본다)."""
    if expected is None or chroma.collection_count(name, db) == 0:
        return False
    return chroma.recorded_catalog_hash(name, db) != expected


def main(argv: list[str] | None = None, embedding=None, db=None, doc_collector=None, perspective_collector=None) -> int:
    """embedding · db · 수집기는 테스트에서 가짜 임베딩 · 격리된 Chroma · 캐시를 넣기 위한 인자다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true", help="항목 · 서가 · 문서 색인을 모두 다시 만든다")
    parser.add_argument("--prefetch-model", action="store_true",
                        help="로컬 임베딩 모델만 내려받고 끝낸다 (Docker 이미지는 scripts/prefetch_model.py로 받는다. 이 옵션은 컨테이너 없이 직접 실행할 때 모델만 미리 받는 용도)")
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

    from scripts import index_docs, index_items, index_perspective
    try:
        embedding = embedding or chroma.default_embedding()
    except MissingApiKeyError as e:
        print(f"[FAIL] {e}")
        return 1

    items, perspective, docs = s.collections.items, s.collections.perspective, s.collections.docs
    stale = stale_collections([items, perspective, docs], embedding, db)
    rebuild = {items, perspective, docs} if args.rebuild else set(stale)
    if stale:
        print(f"임베딩 모델이 바뀐 색인: {', '.join(stale)} — 지금 모델({chroma.embedding_identity(embedding)['embedding_model']})로 다시 만듭니다.")

    expected = {items: catalog_size(), perspective: None}
    catalog = expected_catalog_hash()
    if items not in rebuild and catalog_outdated(items, db, catalog):
        rebuild.add(items)
        print("항목 카탈로그 내용이 색인과 다릅니다 (catalog_hash) — 항목 색인을 다시 만듭니다.")

    def incomplete() -> dict[str, str]:
        return {n: r for n, e in expected.items() if (r := incomplete_reason(n, db, e))}

    partial = incomplete()
    failed = []

    def run(label: str, name: str, fn) -> None:
        count = chroma.collection_count(name, db)
        if count == 0:
            if name == docs:
                print(f"{label}: 비어 있음 — 질문할 때 그 천체의 문서를 모아 색인합니다")
                return
            print(f"{label}을(를) 만듭니다…")
            code = fn([])
        elif name in rebuild:
            print(f"{label}을(를) 다시 만듭니다… (기존 {count}건은 끝날 때까지 그대로)")
            code = fn(["--rebuild"])
        elif name in partial:
            print(f"{label}이 불완전합니다 ({partial[name]}) — 다시 만듭니다…")
            code = fn(["--rebuild"])
        else:
            print(f"{label} 있음 ({count}건)")
            return
        if code:
            failed.append(label)

    run("항목 색인", items, lambda a: index_items.main(a, embedding=embedding, db=db))
    run("관점 전환 서가 색인", perspective, lambda a: index_perspective.main(a, embedding=embedding, db=db, collector=perspective_collector))
    run("문서 색인", docs, lambda a: index_docs.main(a, embedding=embedding, db=db, collector=doc_collector))

    left = list(dict.fromkeys(stale_collections([items, perspective, docs], embedding, db) + list(incomplete())
                              + ([items] if catalog_outdated(items, db, catalog) else [])))
    if failed or left:
        print(f"[FAIL] 색인 준비 실패: {', '.join(failed or left)} — 기존 색인을 그대로 두고 서버를 띄우지 않습니다.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
