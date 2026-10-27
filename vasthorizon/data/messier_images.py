"""메시에 천체 사진 — NASA 'Hubble's Messier Catalog' 페이지의 대표 사진과 출처 표기를 모은다.

| 항목     | 내용                                                                                  |
|----------|---------------------------------------------------------------------------------------|
| 출처     | https://science.nasa.gov/mission/hubble/science/explore-the-night-sky/hubble-messier-catalog/ |
| 사진     | 페이지의 대표 이미지(og:image)를 받아 긴 변 512px JPEG로 줄인다 (요청 크기를 무시하는 사진이 있어 직접 줄임) |
| 출처 표기 | 첫 그림의 credit 문구를 그대로 둔다 (예: "NASA, ESA, J. Hester and A. Loll (Arizona State University)") |
| 이용 조건 | NASA가 만든 자료는 미국 정부 저작물(공공). ESA · NOIRLab 등 다른 기관이 함께 표기된 사진은 그 기관의 조건(대개 CC BY 4.0)에 따라 출처 표기를 반드시 함께 보여 준다 |

결과: web/data/messier/M{n}.jpg + credits.json ({"M1": {"credit", "page", "image"}}). 페이지가 없거나 사진이 없으면 빠진다.
고해상도: web/data/messier/hd/M{n}.jpg — 같은 사진(credits.json의 image)을 긴 변 1024px로. 지도에서 가까이 갈 때만 내려받는다(details.js).
출처 표기는 credits.json 하나를 함께 쓴다.
사진은 시야와 방향 정보가 없어, 하늘에서는 카탈로그 크기에 맞춰 보여 줄 뿐 방향(북쪽)은 맞추지 않는다.
"""

from __future__ import annotations

import html
import io
import json
import os
import re
from collections.abc import Callable
from pathlib import Path

PAGE = "https://science.nasa.gov/mission/hubble/science/explore-the-night-sky/hubble-messier-catalog/messier-{n}/"
OG_IMAGE = re.compile(r'<meta property="og:image" content="([^"]+)"')
CREDIT = re.compile(r'<div class="hds-credits">(.*?)</div>', re.S)
WIDTH = 512
HD_WIDTH = 1024
HUBBLE_ASSET = re.compile(r"https://assets\.science\.nasa\.gov/content/dam/science/missions/hubble/[^\s\"'<>()?]+?\.(?:jpe?g|png)", re.I)
NEW_IMAGE = re.compile(r"new[_\- ]?image", re.I)    # 사진에 빨간 "New Image" 띠가 박힌 변형 (..._NewImage.jpg)


def has_banner(url: str) -> bool:
    return bool(NEW_IMAGE.search(url.rsplit("/", 1)[-1]))


def pick_image(text: str, og: str) -> str:
    """og:image가 'New Image' 띠 변형이면 같은 페이지의 띠 없는 허블 이미지(파일명 앞부분이 같은 것 우선)로 바꾼다. 못 찾으면 og 그대로."""
    if not has_banner(og):
        return og
    seen, clean = set(), []
    for url in HUBBLE_ASSET.findall(html.unescape(text)):
        if url not in seen and not has_banner(url):
            seen.add(url)
            clean.append(url)
    if not clean:
        return og
    stem = NEW_IMAGE.split(og.rsplit("/", 1)[-1])[0].lower()
    same = [u for u in clean if stem and u.rsplit("/", 1)[-1].lower().startswith(stem)]
    return (same or clean)[0]


def to_jpeg(data: bytes, size: int = WIDTH) -> bytes:
    """JPEG · PNG · WebP → 긴 변 size px 이하의 JPEG (Pillow(requirements.txt))."""
    from PIL import Image
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((size, size))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=82, optimize=True, progressive=True)
    return out.getvalue()


def parse_page(text: str) -> dict | None:
    """페이지 HTML → {image, credit}. 대표 사진이나 출처 표기가 없으면 None — 출처 없는 사진은 쓰지 않는다."""
    og = OG_IMAGE.search(text)
    credit = CREDIT.search(text)
    if not og or not credit:
        return None
    clean = html.unescape(re.sub(r"<[^>]+>", "", credit.group(1))).strip()
    if not clean:
        return None
    return {"image": pick_image(text, og.group(1).split("?")[0]), "credit": re.sub(r"\s+", " ", clean)}


def build(out_dir: Path, get: Callable[[str], object], numbers=range(1, 111), log=print, width: int = WIDTH) -> dict:
    """get(url) → requests.Response 같은 것 (status_code · text · content). 이미 받은 사진은 다시 받지 않는다. width: 긴 변 px"""
    out_dir.mkdir(parents=True, exist_ok=True)
    credits_path = out_dir / "credits.json"
    credits = json.loads(credits_path.read_text(encoding="utf-8")) if credits_path.exists() else {}
    for n in numbers:
        key = f"M{n}"
        if key in credits and (out_dir / f"{key}.jpg").exists():
            continue
        page = PAGE.format(n=n)
        try:
            resp = get(page)
            found = parse_page(resp.text) if resp.status_code == 200 else None
            if not found:
                log(f"  {key}: 사진 또는 출처 표기 없음 — 건너뜀")
                continue
            if has_banner(found["image"]):
                log(f"  {key}: 띠 없는 대안 사진을 찾지 못함 — og:image 그대로 씀 ({found['image']})")
            img = get(f"{found['image']}?w={width}")
            if img.status_code != 200 or not img.headers.get("content-type", "").startswith("image/"):
                log(f"  {key}: 사진을 받지 못함 ({img.status_code} {img.headers.get('content-type')}) — 건너뜀")
                continue
            jpeg = to_jpeg(img.content, width)
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 404:                                    # 허블 메시에 목록에 없는 천체 (주로 산개 성단)
                log(f"  {key}: 페이지 없음 — 건너뜀")
            else:                                                # 네트워크 장애 — 다음 실행에서 이어서
                log(f"  {key}: {type(e).__name__} — 다음 실행에서 다시")
            continue
        (out_dir / f"{key}.jpg").write_bytes(jpeg)
        credits[key] = {"credit": found["credit"], "page": page, "image": found["image"]}
        credits_path.write_text(json.dumps(credits, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        log(f"  {key}: {len(jpeg) // 1024}KB · {found['credit']}")
    return credits


def is_jpeg(path: Path) -> bool:
    """다 쓴 JPEG인가 — 비어 있지 않고 JPEG 머리(FF D8)로 시작한다. 중간에 끊긴 파일은 다시 받는다."""
    try:
        with path.open("rb") as f:
            return f.read(2) == b"\xff\xd8"
    except OSError:
        return False


def build_hd(out_dir: Path, get: Callable[[str], object], width: int = HD_WIDTH, log=print) -> dict:
    """credits.json에 있는 사진마다 같은 원본(image)을 긴 변 width px로 받아 out_dir/hd/M{n}.jpg에 둔다.
    출처 표기는 credits.json을 그대로 쓰므로 새로 적지 않는다. 이미 받은(온전한 JPEG) 사진은 다시 받지 않는다.
    .tmp에 다 쓴 뒤 이름을 바꿔, 중간에 끊겨도 반쪽 파일이 남지 않는다. 반환: {"M1": 바이트 수}"""
    credits = json.loads((out_dir / "credits.json").read_text(encoding="utf-8"))
    hd_dir = out_dir / "hd"
    hd_dir.mkdir(parents=True, exist_ok=True)
    done = {}
    for key, c in sorted(credits.items(), key=lambda kv: int(kv[0][1:])):
        path = hd_dir / f"{key}.jpg"
        if path.exists() and path.stat().st_size > 0 and is_jpeg(path):
            done[key] = path.stat().st_size
            continue
        try:
            img = get(f"{c['image']}?w={width}")
            if img.status_code != 200 or not img.headers.get("content-type", "").startswith("image/"):
                log(f"  {key}: 사진을 받지 못함 ({img.status_code} {img.headers.get('content-type')}) — 건너뜀")
                continue
            jpeg = to_jpeg(img.content, width)
        except Exception as e:                                   # 네트워크 장애 — 다음 실행에서 이어서
            log(f"  {key}: {type(e).__name__} — 다음 실행에서 다시")
            continue
        tmp = path.with_suffix(".jpg.tmp")
        tmp.write_bytes(jpeg)
        os.replace(tmp, path)
        done[key] = len(jpeg)
        log(f"  {key}: {len(jpeg) // 1024}KB")
    return done
