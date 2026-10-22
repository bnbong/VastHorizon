"""하늘 데이터 — 화면의 모든 점을 실제 천체로. d3-celestial(BSD-3-Clause)을 웹용 작은 파일로 바꾼다.

| 파일 (web/data/)     | 내용                                              | 크기     | 내려받는 때            |
|----------------------|---------------------------------------------------|----------|------------------------|
| stars_bright.bin     | 히파르코스 별 8등급까지 41,411개 (밝은 순)          | 약 0.5MB | 처음                   |
| stars_faint.bin      | 8등급보다 어두운 별 76,805개 (12등급대까지)         | 약 0.9MB | 확대해 화각이 좁아질 때 |
| dsos.json            | 성운 · 성단 · 은하 15,809개 (NGC · IC · 메시에 등)  | 약 0.8MB | 확대할 때              |
| milkyway.bin         | 은하수 밝기 지도 (적경 · 적위 격자, 0~255)          | 약 0.25MB | 처음                  |

별 레코드 (12바이트, 리틀 엔디언) — 머리 8바이트("VHS1" + 개수 uint32) 뒤에 이어진다.
| 필드 | 형식   | 값                              |
|------|--------|---------------------------------|
| hip  | uint32 | 히파르코스 번호                 |
| ra   | uint16 | 적경 / 360 × 65536 (약 20초각)  |
| dec  | int16  | 적위 / 90 × 32767               |
| mag  | int16  | 겉보기 등급 × 100               |
| bv   | int16  | 색지수(B−V) × 1000 (없으면 0.6) |

은하수 — d3-celestial mw.json의 윤곽 5단계(ol1 가장 넓고 옅음 → ol5 가장 밝은 중심)를
격자 칸마다 '몇 단계 안에 드는지'로 세어 밝기로 바꾼다. 윤곽은 하늘을 한 바퀴 감는 띠라
평면 다각형 채우기로는 깨진다. 그래서 칸마다 남극(바깥으로 확인됨)에서 그 칸까지 같은 적경선을
올라가며 윤곽을 몇 번 넘는지(짝홀)로 안팎을 정한다.

성운 · 성단 · 은하의 크기는 장축 × 단축(각분)만 있고 기울기(위치각)가 출처에 없다. 화면은 장축 지름의 원으로 그린다.
암흑 성운(dn)의 mag 값은 불투명도 등급(1~6)이라 등급으로 쓰지 않는다 — 화면의 한계 등급 표시에서 빠진다.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

from vasthorizon.data import sources

MAGIC = b"VHS1"
RECORD = struct.Struct("<IHhhh")
BRIGHT_LIMIT = 8.0
DEFAULT_BV = 0.6
MW_WIDTH, MW_HEIGHT = 720, 360           # 0.5도 격자
LICENSE = "d3-celestial (© 2015 Olaf Frohn, BSD-3-Clause) — 히파르코스 · NGC/IC · 은하수 윤곽"

# 성운 · 성단 · 은하 종류 (d3-celestial type → 한국어)
DSO_TYPES = {
    "g": "은하", "s": "나선 은하", "s0": "렌즈형 은하", "sd": "왜소 나선 은하", "e": "타원 은하", "i": "불규칙 은하",
    "gg": "은하군", "oc": "산개 성단", "gc": "구상 성단", "en": "발광 성운", "bn": "밝은 성운", "rn": "반사 성운",
    "dn": "암흑 성운", "pn": "행성상 성운", "snr": "초신성 잔해", "sfr": "별 생성 영역",
}


def ra_of(lon: float) -> float:
    """d3-celestial 경도(−180~180) → 적경(0~360)."""
    return lon % 360.0


# ── 별 ────────────────────────────────────────────────────────────────────

def star_rows(features: list[dict]) -> list[tuple[int, float, float, float, float]]:
    """(hip, 적경, 적위, 등급, 색지수) — 밝은 순."""
    rows = []
    for f in features:
        lon, dec = f["geometry"]["coordinates"]
        try:
            bv = float(f["properties"].get("bv"))
        except (TypeError, ValueError):
            bv = DEFAULT_BV
        rows.append((int(f["id"]), ra_of(lon), float(dec), float(f["properties"]["mag"]), bv))
    rows.sort(key=lambda r: r[3])
    return rows


def encode_stars(rows: list[tuple[int, float, float, float, float]]) -> bytes:
    out = bytearray(MAGIC + struct.pack("<I", len(rows)))
    for hip, ra, dec, mag, bv in rows:
        out += RECORD.pack(hip, round(ra / 360 * 65536) % 65536, round(dec / 90 * 32767),
                           round(mag * 100), max(-32768, min(32767, round(bv * 1000))))
    return bytes(out)


def decode_stars(data: bytes) -> list[tuple[int, float, float, float, float]]:
    if data[:4] != MAGIC:
        raise ValueError("별 파일 형식이 아닙니다")
    (count,) = struct.unpack_from("<I", data, 4)
    rows = []
    for i in range(count):
        hip, ra, dec, mag, bv = RECORD.unpack_from(data, 8 + i * RECORD.size)
        rows.append((hip, ra / 65536 * 360, dec / 32767 * 90, mag / 100, bv / 1000))
    return rows


# ── 성운 · 성단 · 은하 ─────────────────────────────────────────────────────

def _dim(text: str) -> tuple[float, float] | None:
    try:
        parts = [float(x) for x in str(text).split("x") if x.strip()]
    except ValueError:
        return None
    if not parts:
        return None
    return parts[0], parts[1] if len(parts) > 1 else parts[0]


def dso_rows(features: list[dict], messier: list[dict]) -> list[list]:
    """[이름, 종류, 적경, 적위, 등급|None, 장축(각분)|None, 단축|None, 메시에 번호|""] — 밝은 순(등급 없는 것은 뒤).

    성운 목록에는 메시에 천체 대부분이 NGC 이름으로 실려 있다 (M1 → "NGC 1952").
    메시에 목록의 desig로 NGC 이름 → 메시에 번호를 이어, 화면에서 카탈로그 항목(메시에 번호)과 연결한다.
    """
    messier_of = {}
    for m in messier:
        number = m["properties"]["name"].replace(" ", "")              # "M1"
        messier_of[number] = number
        if m["properties"].get("desig"):
            messier_of.setdefault(m["properties"]["desig"], number)    # "NGC 1952" → "M1"
    rows = []
    for f in features:
        p = f["properties"]
        lon, dec = f["geometry"]["coordinates"]
        try:
            mag = round(float(p.get("mag")), 1)
        except (TypeError, ValueError):
            mag = None
        if p.get("type") == "dn":
            mag = None                                   # 암흑 성운의 숫자(1~6)는 밝기 등급이 아니라 불투명도 등급이다
        dim = _dim(p.get("dim", ""))
        name = f["id"].replace(" ", "") if f["id"].startswith("M ") else f["id"]
        rows.append([name, p.get("type") or "", round(ra_of(lon), 3), round(float(dec), 3), mag,
                     round(dim[0], 2) if dim else None, round(dim[1], 2) if dim else None,
                     messier_of.get(name, "")])
    rows.sort(key=lambda r: (r[4] is None, r[4] if r[4] is not None else 99))
    return rows


# ── 은하수 ────────────────────────────────────────────────────────────────

def _edges(rings: list[list[list[float]]]) -> np.ndarray:
    """윤곽 → 선분 [lon1, lat1, lon2, lat2]. 경도는 선분마다 가까운 쪽으로 풀어 0~360 밖도 허용한다."""
    segs = []
    for ring in rings:
        pts = [(ra_of(lon), lat) for lon, lat in ring]
        for (a_lon, a_lat), (b_lon, b_lat) in zip(pts, pts[1:] + pts[:1]):
            d = (b_lon - a_lon + 540) % 360 - 180
            segs.append((a_lon, a_lat, a_lon + d, b_lat))
    return np.array(segs, dtype=np.float64)


def inside_mask(rings: list[list[list[float]]], width: int, height: int) -> np.ndarray:
    """격자 칸 중심이 윤곽 안에 있으면 True. 남극에서 적경선을 따라 올라가며 넘는 횟수의 짝홀."""
    edges = _edges(rings)
    # 칸 중심이 꼭짓점 경도(소수 셋째 자리)와 정확히 겹치면 이웃 선분 두 개가 둘 다 세어 짝홀이 뒤집힌다 — 살짝 비켜 둔다
    lons = (np.arange(width) + 0.5) / width * 360 + 1.234e-6
    lats = 90 - (np.arange(height) + 0.5) / height * 180            # 위쪽 행이 북쪽
    crossings = np.zeros((height, width), dtype=np.int32)
    for lon1, lat1, lon2, lat2 in edges:
        lo, hi = min(lon1, lon2), max(lon1, lon2)
        if hi - lo < 1e-9:
            continue
        for shift in (-360, 0, 360):                                  # 0/360 경계를 넘는 선분
            cols = np.nonzero((lons >= lo + shift) & (lons < hi + shift))[0]
            if not len(cols):
                continue
            t = (lons[cols] - shift - lon1) / (lon2 - lon1)
            lat_at = lat1 + t * (lat2 - lat1)                       # 그 적경선에서 선분의 적위
            # 선분이 칸보다 아래(남쪽)에 있으면 남극 → 칸 사이에서 넘는다
            crossings[:, cols] += (lat_at[None, :] < lats[:, None])
    return crossings % 2 == 1


def milkyway_grid(features: list[dict], width: int = MW_WIDTH, height: int = MW_HEIGHT) -> np.ndarray:
    """칸마다 0~255 밝기. 단계(ol1~ol5) 안에 들 때마다 밝아지고, 가장자리는 살짝 흐린다."""
    level = np.zeros((height, width), dtype=np.float32)
    for f in sorted(features, key=lambda f: f["id"]):
        for polygon in f["geometry"]["coordinates"]:
            level += inside_mask(polygon, width, height)
    # 가로(적경)는 이어지게, 세로는 가장자리 복제로 3×3 상자 흐림 두 번
    for _ in range(2):
        padded = np.pad(level, ((1, 1), (0, 0)), mode="edge")
        level = sum(np.roll(padded, dx, axis=1)[1 + dy:height + 1 + dy] for dx in (-1, 0, 1) for dy in (-1, 0, 1)) / 9
    return np.clip(level / 5 * 255, 0, 255).astype(np.uint8)


def encode_milkyway(grid: np.ndarray) -> bytes:
    h, w = grid.shape
    return b"VHM1" + struct.pack("<HH", w, h) + grid.tobytes()


# ── 만들기 ────────────────────────────────────────────────────────────────

def build(out_dir: Path, refresh: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    stars = star_rows(sources.d3_file("stars.14.json", refresh)["features"])
    bright = [r for r in stars if r[3] <= BRIGHT_LIMIT]
    faint = [r for r in stars if r[3] > BRIGHT_LIMIT]
    (out_dir / "stars_bright.bin").write_bytes(encode_stars(bright))
    (out_dir / "stars_faint.bin").write_bytes(encode_stars(faint))

    dsos = dso_rows(sources.d3_file("dsos.14.json", refresh)["features"], sources.d3_file("messier.json", refresh)["features"])
    (out_dir / "dsos.json").write_text(json.dumps({"fields": ["name", "type", "ra", "dec", "mag", "major", "minor", "messier"],
                                                   "types": DSO_TYPES, "rows": dsos}, ensure_ascii=False,
                                                  separators=(",", ":")), encoding="utf-8")

    grid = milkyway_grid(sources.d3_file("mw.json", refresh)["features"])
    (out_dir / "milkyway.bin").write_bytes(encode_milkyway(grid))

    meta = {"license": LICENSE, "source": "https://github.com/ofrohn/d3-celestial",
            "stars": {"bright": len(bright), "faint": len(faint), "bright_limit": BRIGHT_LIMIT,
                      "faintest": max(r[3] for r in stars)},
            "dsos": len(dsos), "milkyway": {"width": grid.shape[1], "height": grid.shape[0]}}
    (out_dir / "sky_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def load_star_index(path: Path) -> dict[int, tuple[float, float, float, float]]:
    """히파르코스 번호 → (적경, 적위, 등급, 색지수). 서버가 아무 별이나 항목으로 만들 때 쓴다."""
    index = {}
    for name in ("stars_bright.bin", "stars_faint.bin"):
        f = path / name
        if f.exists():
            for hip, ra, dec, mag, bv in decode_stars(f.read_bytes()):
                index.setdefault(hip, (ra, dec, mag, bv))
    return index

