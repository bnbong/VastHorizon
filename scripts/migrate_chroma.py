"""Chroma 저장소 이전 — 한 저장소(data/chroma) → 컬렉션별 저장소(data/chroma/<컬렉션>/).

    python -m scripts.migrate_chroma --dry-run   # 옮길 컬렉션과 건수만 확인
    python -m scripts.migrate_chroma             # 이전 실행

- 벡터 · 본문 · 메타데이터 · 컬렉션 식별 정보(임베딩 모델 · 차원)를 그대로 복사한다 — 재임베딩 없음.
- 기존 저장소는 지우지 않고 data/chroma_legacy_<시각>/ 으로 옮겨 보관한다. 확인 뒤 직접 지우면 된다.
- 복사 후 컬렉션마다 건수 · ID 집합 · 벡터 일치를 검증한다. 하나라도 어긋나면 실패로 끝내고
  새 저장소만 지운다 — 기존 저장소는 처음부터 건드리지 않는다.
이유는 vasthorizon/store/chroma.py의 '컬렉션별 저장소 분리'를 참고.

절차 (Windows는 Chroma가 연 파일을 프로세스가 끝날 때까지 잠근다)
1. 자식 프로세스가 기존 저장소를 읽어 data/chroma_migrating/<컬렉션>/ 에 복사 · 검증하고 종료한다.
2. 저장소를 한 번도 열지 않은 부모 프로세스가 폴더 이름을 바꾼다.
   data/chroma → data/chroma_legacy_<시각>, data/chroma_migrating → data/chroma
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import chromadb
import numpy as np

from vasthorizon.config import get_settings
from vasthorizon.store import chroma

BATCH = 200


def legacy_layout(path) -> bool:
    return (path / "chroma.sqlite3").exists()


def read_all(collection) -> dict:
    out = {"ids": [], "documents": [], "metadatas": [], "embeddings": []}
    offset = 0
    while True:
        got = collection.get(include=["documents", "metadatas", "embeddings"], limit=BATCH, offset=offset)
        if not got["ids"]:
            return out
        for key in out:
            out[key].extend(list(got[key]))
        offset += len(got["ids"])


def copy_collection(src, dst_db: chromadb.ClientAPI) -> int:
    data = read_all(src)
    dst = dst_db.create_collection(src.name, metadata=src.metadata, configuration=chroma.COLLECTION_CONFIG)
    for start in range(0, len(data["ids"]), BATCH):
        sl = slice(start, start + BATCH)
        dst.upsert(ids=data["ids"][sl], documents=data["documents"][sl], metadatas=data["metadatas"][sl],
                   embeddings=[list(map(float, v)) for v in data["embeddings"][sl]])
    verify(data, dst)
    return len(data["ids"])


def verify(src_data: dict, dst) -> None:
    got = read_all(dst)
    if sorted(got["ids"]) != sorted(src_data["ids"]):
        raise RuntimeError(f"{dst.name}: ID 집합이 다릅니다 ({len(got['ids'])} vs {len(src_data['ids'])})")
    src_vec = dict(zip(src_data["ids"], src_data["embeddings"]))
    for cid, vec in zip(got["ids"], got["embeddings"]):
        if not np.allclose(np.asarray(vec), np.asarray(src_vec[cid]), atol=1e-6):
            raise RuntimeError(f"{dst.name}: 벡터가 다릅니다 ({cid})")


def copy_all(root: Path, dest: Path, dry_run: bool) -> int:
    """자식 프로세스 — 기존 저장소(root)를 읽어 dest/<컬렉션>/ 에 복사 · 검증한다."""
    legacy_db = chromadb.PersistentClient(path=str(root))
    names = [c.name for c in legacy_db.list_collections()]
    targets = [n for n in names if chroma.base_name(n) == n]           # 임시 · 백업 컬렉션은 옮기지 않는다
    for n in names:
        print(f"  {n}: {legacy_db.get_collection(n).count()}건{' (옮김)' if n in targets else ' (건너뜀)'}")
    if dry_run:
        return 0
    for name in targets:
        n = copy_collection(legacy_db.get_collection(name), chromadb.PersistentClient(path=str(dest / name)))
        print(f"[ OK ] {name}: {n}건 복사 · 검증 (건수 · ID · 벡터 일치)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--copy-to", help=argparse.SUPPRESS)          # 자식 프로세스용
    args = parser.parse_args(argv)

    root = get_settings().paths.chroma_dir
    if not legacy_layout(root):
        print(f"이미 컬렉션별 저장소입니다 ({root}). 할 일이 없습니다.")
        return 0
    if args.copy_to or args.dry_run:
        return copy_all(root, Path(args.copy_to or root), args.dry_run)

    staging = root.with_name("chroma_migrating")
    shutil.rmtree(staging, ignore_errors=True)
    child = subprocess.run([sys.executable, "-m", "scripts.migrate_chroma", "--copy-to", str(staging)])
    if child.returncode != 0:
        shutil.rmtree(staging, ignore_errors=True)
        print("[FAIL] 복사 · 검증 실패 — 기존 저장소는 그대로입니다.")
        return 1
    legacy = root.with_name(f"chroma_legacy_{datetime.now():%Y%m%d_%H%M%S}")
    root.rename(legacy)
    staging.rename(root)
    print(f"이전 완료 → {root}/<컬렉션>/")
    print(f"기존 저장소는 {legacy} 에 보관했습니다. 서비스 확인 뒤 지워도 됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
