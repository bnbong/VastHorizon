"""항목 메타데이터 출처별 조회 함수.

| 출처              | 용도                              | 이용 조건            |
|-------------------|-----------------------------------|----------------------|
| Wikidata          | 항목 목록 · 속성 · 한국어 위키 연결 | CC0 1.0              |
| 한국어 위키백과   | 문서 존재 · 길이 확인              | CC BY-SA 4.0         |
| JPL Horizons      | 태양계 천체 · 탐사선 위치          | 미국 정부 저작물     |
| CelesTrak SATCAT  | 인공위성 궤도 · 운용 상태          | 무료 공개 · 출처 표기 |
| d3-celestial      | 별 · 별자리 좌표                   | BSD-3-Clause         |

원본 응답은 data/raw/에 캐시한다. 다시 실행해도 외부 호출이 반복되지 않는다.

캐시 파일마다 `<파일>.meta.json`에 수집 시각(fetched_at, UTC)을 남긴다.
기록이 없는 예전 캐시는 파일 수정 시각으로 추정하고 estimated=True로 표시한다.
이번 실행에서 쓴 원본의 수집 시각은 SNAPSHOTS에 모여 카탈로그 meta에 기록된다.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

from vasthorizon.config import get_settings
from vasthorizon.data.atomic import atomic_write_text
from vasthorizon.http import http

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
KOWIKI_API = "https://ko.wikipedia.org/w/api.php"
ENWIKI_API = "https://en.wikipedia.org/w/api.php"
HORIZONS_API = "https://ssd.jpl.nasa.gov/api/horizons.api"
SATCAT_CSV = "https://celestrak.org/pub/satcat.csv"
D3_CELESTIAL = "https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/{name}"

SOURCE_URLS = {
    "Wikidata": "https://www.wikidata.org/wiki/{id}",
    "한국어 위키백과": "https://ko.wikipedia.org/wiki/{title}",
    "JPL Horizons": "https://ssd.jpl.nasa.gov/horizons/",
    "CelesTrak SATCAT": "https://celestrak.org/satcat/search.php",
    "d3-celestial": "https://github.com/ofrohn/d3-celestial",
}


def raw_dir() -> Path:
    path = get_settings().paths.data_dir / "raw"
    path.mkdir(parents=True, exist_ok=True)
    return path


# 이번 실행에서 사용한 원본 데이터 → {"fetched_at", "estimated"(, "note")}
SNAPSHOTS: dict[str, dict] = {}


def _meta_path(path: Path) -> Path:
    return path.with_name(path.name + ".meta.json")


def _record_fetch(name: str, path: Path) -> dict:
    snapshot = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "estimated": False}
    atomic_write_text(_meta_path(path), json.dumps(snapshot))
    SNAPSHOTS[name] = snapshot
    return snapshot


def snapshot_of(name: str, path: Path) -> dict:
    """캐시 파일의 수집 시각. 기록이 없으면 파일 수정 시각으로 추정한다."""
    meta = _meta_path(path)
    if meta.exists():
        snapshot = json.loads(meta.read_text(encoding="utf-8"))
    else:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        snapshot = {"fetched_at": mtime.isoformat(timespec="seconds"), "estimated": True,
                    "note": "수집 시각 기록이 없는 기존 캐시 — 파일 수정 시각으로 추정"}
    SNAPSHOTS[name] = snapshot
    return snapshot


def cached(name: str, fetch: Callable[[], object], refresh: bool = False):
    """JSON으로 저장 가능한 결과를 data/raw/{name}.json에 캐시한다."""
    path = raw_dir() / f"{name}.json"
    if path.exists() and not refresh:
        snapshot_of(name, path)
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    atomic_write_text(path, json.dumps(data, ensure_ascii=False))
    _record_fetch(name, path)
    return data


def _chunks(seq: list, size: int) -> Iterable[list]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


# ── Wikidata ──────────────────────────────────────────────────────────────

def sparql(query: str) -> list[dict[str, str]]:
    """SPARQL 결과를 {변수: 값} 딕셔너리 목록으로 돌려준다."""
    data = http().get_json(
        WIKIDATA_SPARQL,
        params={"query": query, "format": "json"},
        headers={"Accept": "application/sparql-results+json"},
        timeout=120,
    )
    return [{k: v["value"] for k, v in row.items()} for row in data["results"]["bindings"]]


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def entities_by_titles(site: str, titles: list[str]) -> dict[str, dict]:
    """위키 문서 제목 → Wikidata 엔티티(QID · 한국어 위키 제목 · 영문 라벨)."""
    found: dict[str, dict] = {}
    for batch in _chunks(titles, 50):
        data = http().get_json(WIKIDATA_API, params={
            "action": "wbgetentities", "sites": site, "titles": "|".join(batch),
            "props": "sitelinks|labels", "sitefilter": "kowiki|enwiki", "languages": "ko|en",
            "format": "json",
        })
        if "error" in data:
            raise RuntimeError(f"Wikidata API 오류: {data['error'].get('info')}")
        for ent in data.get("entities", {}).values():
            if "missing" in ent:
                continue
            links = ent.get("sitelinks", {})
            title = links.get(site, {}).get("title")
            found[title] = {
                "qid": ent["id"],
                "kowiki": links.get("kowiki", {}).get("title"),
                "label_en": ent.get("labels", {}).get("en", {}).get("value"),
            }
    return found


# ── 한국어 위키백과 ─────────────────────────────────────────────────────────

def kowiki_page_info(titles: list[str], api: str = KOWIKI_API) -> dict[str, dict]:
    """문서 제목 → {resolved: 최종 제목, length: 바이트 길이, pageid}. 없는 문서는 빠진다.

    입력 제목마다 정규화 → 리다이렉트(연속 포함)를 끝까지 따라가 최종 문서에 연결한다.
    여러 별칭이 같은 문서로 가도 모든 별칭과 최종 제목이 같은 정보를 조회할 수 있다.
    """
    info: dict[str, dict] = {}
    for batch in _chunks(titles, 50):
        data = http().get_json(api, params={
            "action": "query", "titles": "|".join(batch), "prop": "info",
            "redirects": 1, "format": "json", "formatversion": 2,
        })
        q = data["query"]
        steps = {s["from"]: s["to"] for s in q.get("normalized", []) + q.get("redirects", [])}
        pages = {
            p["title"]: {"resolved": p["title"], "length": p["length"], "pageid": p["pageid"]}
            for p in q.get("pages", []) if not p.get("missing") and not p.get("invalid")
        }
        for original in batch:
            final = _follow(original, steps)
            if final in pages:
                info[original] = pages[final]
        info.update(pages)
    return info


def _follow(title: str, steps: dict[str, str]) -> str:
    seen = set()
    while title in steps and title not in seen:
        seen.add(title)
        title = steps[title]
    return title


# ── JPL Horizons ──────────────────────────────────────────────────────────

_VEC = re.compile(r"X =\s*(\S+)\s+Y =\s*(\S+)\s+Z =\s*(\S+)")


def horizons_vector(command: str, epoch: str) -> list[float] | None:
    """태양 중심 · ICRF 적도 좌표계 위치 벡터(AU). 궤도력이 없으면 None.

    ICRF 적도 좌표계를 쓰는 이유: 별 · 메시에 천체의 적경 · 적위와 같은 좌표계라
    3D 공간에 함께 배치할 수 있다.
    """
    next_day = _next_day(epoch)
    data = http().get_json(HORIZONS_API, params={
        "format": "json", "COMMAND": f"'{command}'", "OBJ_DATA": "NO", "MAKE_EPHEM": "YES",
        "EPHEM_TYPE": "VECTORS", "CENTER": "'500@10'", "REF_PLANE": "FRAME",
        "START_TIME": epoch, "STOP_TIME": next_day, "STEP_SIZE": "1d",
        "VEC_TABLE": "1", "OUT_UNITS": "AU-D",
    })
    match = _VEC.search(data.get("result", ""))
    if not match:
        return None
    return [float(v) for v in match.groups()]


def _next_day(epoch: str) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(epoch) + timedelta(days=1)).isoformat()


def horizons_position(command: str, epoch: str, refresh: bool = False) -> list[float] | None:
    """대상 · 기준일별로 캐시한 Horizons 위치. 선정 항목이 바뀌어도 캐시가 어긋나지 않는다."""
    slug = re.sub(r"[^0-9A-Za-z-]+", "_", command).strip("_")
    return cached(f"horizons_{epoch}_{slug}", lambda: horizons_vector(command, epoch), refresh)


# ── CelesTrak SATCAT ──────────────────────────────────────────────────────

def satcat_by_cospar(refresh: bool = False) -> tuple[dict[str, dict], dict]:
    """COSPAR ID(국제 식별 번호) → SATCAT 레코드, 그리고 스냅샷 정보.

    SATCAT 파일에는 데이터 기준 시점이 없다. 그래서 내려받은 시각(fetched_at)을
    스냅샷 시점으로 본다. 운용 상태 · 고도 · 재진입 여부는 이 시점의 값이며,
    과거 기준일의 상태로 재구성할 수 없다.
    """
    path = raw_dir() / "satcat.csv"
    if refresh or not path.exists():
        atomic_write_text(path, http().get(SATCAT_CSV, timeout=120).text)
        snapshot = _record_fetch("satcat", path)
    else:
        snapshot = snapshot_of("satcat", path)
    rows = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
    return {row["OBJECT_ID"]: row for row in rows}, snapshot


# ── d3-celestial ──────────────────────────────────────────────────────────

def d3_file(name: str, refresh: bool = False) -> dict:
    return cached(f"d3_{Path(name).stem}", lambda: http().get_json(D3_CELESTIAL.format(name=name)), refresh)
