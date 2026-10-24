"""항목 카탈로그(data/items.json) 검증 · 읽기 · 쓰기.

저장은 검증을 통과한 결과만, 임시 파일을 거쳐 원자적으로 교체한다.
수집이 실패하거나 기록 중 오류가 나도 기존 정상 카탈로그는 그대로 남는다.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

from vasthorizon.config import get_settings
from vasthorizon.data.atomic import atomic_write_text

MIN_ITEMS = 100
GROUP_KEYS = ("solar_system", "human_made", "star", "messier", "constellation")
REQUIRED_FIELDS = ("id", "group", "name", "wiki_title")

LICENSES = {
    "Wikidata": "CC0 1.0",
    "한국어 위키백과": "CC BY-SA 4.0",
    "JPL Horizons": "미국 정부 저작물 (NASA/JPL, 공개)",
    "CelesTrak SATCAT": "무료 공개 데이터 (출처 표기)",
    "d3-celestial": "BSD-3-Clause (© 2015 Olaf Frohn)",
    # 보강 데이터(vasthorizon/data/enrich.json)의 출처 — 블랙홀 · 고리 · 위성 수 · 탐사선 방문
    "영어 위키백과": "CC BY-SA 4.0",
    "NASA NSSDCA": "미국 정부 저작물 (NASA, 공개)",
}


class CatalogValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"카탈로그 검증 실패 {len(errors)}건: " + "; ".join(errors[:5]))


def items_path() -> Path:
    return get_settings().paths.data_dir / "items.json"


def _finite_vector(v) -> bool:
    return isinstance(v, list) and len(v) == 3 and all(isinstance(c, (int, float)) and math.isfinite(c) for c in v)


def validate_items(items: list[dict], min_items: int = MIN_ITEMS) -> list[str]:
    """저장 전 필수 검증. 문제 목록을 돌려준다 (비어 있으면 통과)."""
    errors: list[str] = []
    if len(items) < min_items:
        errors.append(f"항목 {len(items)}건 — 최소 {min_items}건 필요")

    counts = Counter(it.get("group") for it in items)
    for group in GROUP_KEYS:
        if counts[group] == 0:
            errors.append(f"그룹 {group} 항목 0건")
    unknown = set(counts) - set(GROUP_KEYS)
    if unknown:
        errors.append(f"알 수 없는 그룹 {sorted(unknown)}")

    dup = [qid for qid, n in Counter(it.get("id") for it in items).items() if n > 1]
    if dup:
        errors.append(f"QID 중복 {dup[:5]}")

    for it in items:
        label = it.get("id") or "?"
        missing = [f for f in REQUIRED_FIELDS if not it.get(f)]
        if missing:
            errors.append(f"{label}: 필수 필드 누락 {missing}")

        dist = it.get("distance")
        if dist:
            km = dist.get("km")
            if not isinstance(km, (int, float)) or not math.isfinite(km) or km <= 0:
                errors.append(f"{label}: 거리 값이 유효하지 않음 ({km})")
            if dist.get("approximate") and not dist.get("method"):
                errors.append(f"{label}: 근삿값 거리에 계산 방법(method) 없음")
            if not dist.get("reference"):
                errors.append(f"{label}: 거리 기준(reference) 없음")

        ra, dec = it.get("ra_deg"), it.get("dec_deg")
        if ra is not None and not 0 <= ra < 360:
            errors.append(f"{label}: 적경 범위 벗어남 ({ra})")
        if dec is not None and not -90 <= dec <= 90:
            errors.append(f"{label}: 적위 범위 벗어남 ({dec})")

        pos = it.get("position_au")
        if pos is not None:
            if not _finite_vector(pos):
                errors.append(f"{label}: position_au가 유효한 3차원 벡터가 아님")
            if it.get("position_basis") != "horizons":
                errors.append(f"{label}: position_au의 근거(position_basis) 없음")
        proxy = it.get("position_proxy")
        if proxy is not None and (not _finite_vector(proxy.get("position_au")) or not proxy.get("method")):
            errors.append(f"{label}: position_proxy에 좌표 또는 방법(method) 없음")

        names = [s.get("name") for s in it.get("sources", [])]
        if not names:
            errors.append(f"{label}: 출처 없음")
        elif any(n not in LICENSES for n in names):
            errors.append(f"{label}: 이용 조건이 기록되지 않은 출처 {[n for n in names if n not in LICENSES]}")
        if pos is not None and "JPL Horizons" not in names:
            errors.append(f"{label}: Horizons 위치를 쓰지만 출처에 없음")
    return errors


def save_items(items: list[dict], meta: dict, path: Path | None = None) -> Path:
    """검증 후 원자적으로 저장한다. 검증에 실패하면 기존 파일을 건드리지 않고 예외를 낸다."""
    errors = validate_items(items)
    if errors:
        raise CatalogValidationError(errors)
    path = path or items_path()
    payload = {"meta": {**meta, "licenses": LICENSES}, "items": items}
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=1))
    return path


def load_catalog() -> dict:
    path = items_path()
    if not path.exists():
        raise FileNotFoundError(f"{path}가 없습니다. python -m scripts.collect_items 를 먼저 실행하세요.")
    return json.loads(path.read_text(encoding="utf-8"))


def load_items() -> list[dict]:
    return load_catalog()["items"]
