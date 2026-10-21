"""수집 캐시 (NF2002) — data/cache/ 아래 JSON 파일.

세 가지 기록을 분리한다. 실패한 단계는 어디에도 '완료'로 남지 않아 다음 실행에서 이어서 처리된다.

| 기록            | 위치                              | 키            | 저장 조건                    |
|-----------------|-----------------------------------|---------------|------------------------------|
| 검색 결과       | search/<출처>/<검색어 해시>.json   | 검색어        | 검색 API가 정상 응답했을 때만 |
| 문서 본문       | docs/<출처>/<문서 키>.json         | 문서 ID       | 본문이 비어 있지 않을 때만    |
| 항목 수집 기록  | items/<QID>.json                   | 항목          | —                            |
|   · questions   |   질문 → 검색어 · 후보별 선별 판정 | 항목 + 질문   | 프롬프트가 성공했을 때만      |
|   · docs        |   연결 문서                        | 항목 + 문서   | 본문을 받았을 때만            |

예전 형식(v1) 정리 — 읽을 때 자동으로, 또는 repair()로 한 번에
- v1 수집 기록의 queries(실패도 '완료'로 남았을 수 있음)는 버리고, 질문별 검색어만 남긴다.
  선별 판정은 없으므로 다음 실행에서 다시 선별한다.
- 정상 응답 표시(status=ok)가 없는 빈 검색 결과는 오류로 생겼을 수 있어 캐시 미스로 본다.
- 본문이 빈 문서 캐시는 지우고 다시 받는다.
- 본문 캐시가 없는 연결 문서는 연결을 유지한다 — 캐시 유실은 연결 해제가 아니다.
  (연결 해제는 Collector.unlink로만 한다)
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from vasthorizon.config import get_settings
from vasthorizon.data.atomic import atomic_write_text
from vasthorizon.data.docs import Candidate, Document

MANIFEST_VERSION = 2


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip()


def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def usable(doc: Document | None) -> bool:
    """본문이 실제로 있는 문서인가. 짧아도 비어 있지만 않으면 된다."""
    return doc is not None and bool(doc.text and doc.text.strip())


def migrate_manifest(data: dict) -> dict:
    """v1 → v2. v1의 '처리한 검색어' 기록은 실패도 완료로 남았을 수 있어 버린다."""
    if data.get("version") == MANIFEST_VERSION:
        return data
    questions = {}
    for question, value in (data.get("questions") or {}).items():
        queries = value if isinstance(value, list) else (value or {}).get("queries")
        if isinstance(queries, list):
            questions[question] = {"queries": queries, "judged": {}, "status": "incomplete", "at": None}
    return {"item_id": data["item_id"], "version": MANIFEST_VERSION,
            "questions": questions, "docs": data.get("docs") or {}}


class CollectCache:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_settings().paths.cache_dir

    def _read(self, path: Path) -> dict | None:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def _write(self, path: Path, data: dict) -> None:
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1))

    # 검색 결과 — 정상 응답만
    def _search_path(self, source: str, query: str) -> Path:
        return self.root / "search" / source / f"{_key(normalize_query(query))}.json"

    def get_search(self, source: str, query: str) -> list[Candidate] | None:
        data = self._read(self._search_path(source, query))
        if not data:
            return None
        if data.get("status") != "ok" and not data["candidates"]:
            return None                       # 예전 형식의 빈 결과 — 오류였을 수 있어 다시 검색
        return [Candidate(**c) for c in data["candidates"]]

    def put_search(self, source: str, query: str, candidates: list[Candidate]) -> None:
        self._write(self._search_path(source, query), {
            "query": normalize_query(query), "status": "ok", "fetched_at": now(),
            "candidates": [c.to_dict() for c in candidates],
        })

    # 문서 본문 — 비어 있지 않은 것만
    def _doc_path(self, doc_id: str) -> Path:
        source, _, key = doc_id.partition(":")
        return self.root / "docs" / source / f"{re.sub(r'[^0-9A-Za-z_-]', '_', key)}.json"

    def get_doc(self, doc_id: str) -> Document | None:
        path = self._doc_path(doc_id)
        data = self._read(path)
        if not data:
            return None
        doc = Document.from_dict(data)
        if not usable(doc):
            path.unlink(missing_ok=True)      # 빈 본문 캐시는 무효 — 다시 받게 한다
            return None
        return doc

    def put_doc(self, doc: Document) -> None:
        if not usable(doc):
            raise ValueError(f"빈 본문은 캐시하지 않습니다: {doc.doc_id}")
        self._write(self._doc_path(doc.doc_id), doc.to_dict())

    # 위키 제목 → 문서 ID (항목 자체 문서를 제목으로 다시 찾을 때 본문 요청을 건너뛰기 위해)
    def _title_path(self, source: str, title: str) -> Path:
        return self.root / "titles" / source / f"{_key(title)}.json"

    def get_title(self, source: str, title: str) -> str | None:
        data = self._read(self._title_path(source, title))
        return data["doc_id"] if data else None

    def put_title(self, source: str, title: str, doc_id: str) -> None:
        self._write(self._title_path(source, title), {"title": title, "doc_id": doc_id})

    # 항목 수집 기록
    def _manifest_path(self, item_id: str) -> Path:
        return self.root / "items" / f"{item_id}.json"

    def get_manifest(self, item_id: str) -> dict:
        data = self._read(self._manifest_path(item_id))
        if not data:
            return {"item_id": item_id, "version": MANIFEST_VERSION, "questions": {}, "docs": {}}
        return migrate_manifest(data)

    def put_manifest(self, manifest: dict) -> None:
        self._write(self._manifest_path(manifest["item_id"]), manifest)

    # 기존 캐시 점검 · 복구
    def repair(self) -> dict:
        """예전 형식 · 실패 흔적을 한 번에 정리한다. 정리한 건수를 돌려준다."""
        report = {"migrated_manifests": 0, "removed_empty_docs": 0,
                  "removed_unverified_searches": 0, "missing_linked_docs": 0}
        for path in (self.root / "docs").rglob("*.json"):
            data = self._read(path)
            if not data or not str(data.get("text", "")).strip():
                path.unlink()
                report["removed_empty_docs"] += 1
        for path in (self.root / "search").rglob("*.json"):
            data = self._read(path)
            if data and data.get("status") != "ok" and not data.get("candidates"):
                path.unlink()
                report["removed_unverified_searches"] += 1
        for path in (self.root / "items").glob("*.json"):
            raw = self._read(path)
            manifest = migrate_manifest(raw)
            if manifest is not raw:
                report["migrated_manifests"] += 1
            # 캐시가 없는 연결 문서는 세기만 한다 — 연결 정보는 지우지 않고, 다음 수집 · 색인 때 다시 받는다
            report["missing_linked_docs"] += sum(1 for doc_id in manifest["docs"] if self.get_doc(doc_id) is None)
            self.put_manifest(manifest)
        return report
