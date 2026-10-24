"""파비콘 · 앱 아이콘 · 공유 이미지 만들기 — web/js/logo.js의 로고 도형을 그대로 옮겨 Pillow로 그린다.

    .venv/bin/python -m scripts.build_icons

만드는 파일 (web/ 아래):
    favicon.svg            남보라 둥근 사각 위 로고 — 작은 크기에서 보이게 선을 굵히고 여백을 걷어 낸 구도
    favicon.ico            16 · 32 · 48 (크기마다 선 굵기를 따로 맞춘 그림)
    apple-touch-icon.png   180×180 (가장자리까지 채운 사각 — iOS가 모서리를 깎는다)
    icon-192.png · icon-512.png   manifest 아이콘 — maskable 안전 영역(가운데 지름 80% 원) 안에 로고
    manifest.json          웹 앱 manifest (.webmanifest는 Nginx 기본 mime.types에 없어 .json으로)
    data/brand/og-2026-10.jpg     공유 이미지 1200×630 — docs/images/brand/vasthorizon-thumbnail-v2.png를 잘라서

SVG 래스터 라이브러리(cairosvg 등)에 기대지 않으려고 도형을 다각형으로 펴서 SVG와 PNG를 같은 점으로 그린다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
THUMBNAIL = ROOT / "docs" / "images" / "brand" / "vasthorizon-thumbnail-v2.png"
OG_IMAGE = WEB / "data" / "brand" / "og-2026-10.jpg"

NIGHT = "#222454"     # --night (web/tokens/colors.css)
PEACH = "#f3dad5"     # --peach — 궤적 · 출발점 · 별
HORIZON = "#d3cfd5"   # .logo-horizon의 rgba(255,250,245,.8)을 남보라 위에 합성한 불투명 색 (ICO · PNG에 투명도를 남기지 않는다)

NAME = "VastHorizon"
DESCRIPTION = "3D 하늘에서 천체를 고르면 수집한 문서에 근거해서만 답하는 우주 지식 서비스"

# ── 로고 도형 (web/js/logo.js와 같은 값) ──────────────────────────────────────
TRAIL = [(325, 965), (890, 615), (975, 620), (1024, 436)]
WIDTHS = [(0, 5), (0.1, 11), (0.2, 16), (0.3, 19), (0.45, 20), (0.6, 19), (0.75, 16.5), (0.9, 11.5), (1, 3)]
HORIZON_FROM, HORIZON_TO = (110, 1010), (1140, 1010)
HORIZON_OUTER = (525, 427)       # 바깥 타원 반지름 (rx, ry)
HORIZON_INNER = (526.5, 399)     # 안쪽 타원 — 가운데 두께 427 - 399 = 28
STAR = {"cx": 1035, "cy": 392, "arms": (116, 106, 111, 106)}
DOT = {"cx": 307, "cy": 973, "r": 23}
GAP = 16                         # 궤적이 지평선을 가로지를 때 호에 생기는 틈


def _bezier(p, t):
    u = 1 - t
    return tuple(u * u * u * p[0][i] + 3 * u * u * t * p[1][i] + 3 * u * t * t * p[2][i] + t * t * t * p[3][i] for i in (0, 1))


def _bezier_d(p, t):
    u = 1 - t
    return tuple(3 * u * u * (p[1][i] - p[0][i]) + 6 * u * t * (p[2][i] - p[1][i]) + 3 * t * t * (p[3][i] - p[2][i]) for i in (0, 1))


def _trail_width(t: float) -> float:
    i = max(1, next(k for k, (at, _) in enumerate(WIDTHS) if at >= t))
    (t0, w0), (t1, w1) = WIDTHS[i - 1], WIDTHS[i]
    return w0 + (w1 - w0) * (t - t0) / (t1 - t0)


def trail_outline(bold: float, steps: int = 64) -> list[tuple[float, float]]:
    """궤적 — 중심선 양옆으로 굵기의 절반씩. 점 쪽 · 별 쪽 끝의 가는 굵기는 덜 굵혀 뾰족함을 남긴다."""
    left, right = [], []
    for i in range(steps + 1):
        t = i / steps
        x, y = _bezier(TRAIL, t)
        dx, dy = _bezier_d(TRAIL, t)
        n = math.hypot(dx, dy) or 1
        h = _trail_width(t) * bold / 2
        left.append((x - dy / n * h, y + dx / n * h))
        right.append((x + dy / n * h, y - dx / n * h))
    return left + right[::-1]


def _arc(p0, p1, rx, ry, sweep: int, steps: int) -> list[tuple[float, float]]:
    """SVG 타원호(회전 0, large-arc 0)를 점으로 — 끝점 표기를 중심 표기로 바꿔 각도를 나눈다."""
    x1p, y1p = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) * (1 if sweep else -1)   # large-arc 0 — 부호는 (large-arc != sweep)
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    cx, cy = cxp + (p0[0] + p1[0]) / 2, cyp + (p0[1] + p1[1]) / 2
    a0 = math.atan2((y1p - cyp) / ry, (x1p - cxp) / rx)
    a1 = math.atan2((-y1p - cyp) / ry, (-x1p - cxp) / rx)
    da = a1 - a0
    if sweep and da < 0:
        da += 2 * math.pi
    elif not sweep and da > 0:
        da -= 2 * math.pi
    return [(cx + rx * math.cos(a0 + da * k / steps), cy + ry * math.sin(a0 + da * k / steps)) for k in range(steps + 1)]


def horizon_outline(bold: float, steps: int = 96) -> list[tuple[float, float]]:
    """지평선 호 — 바깥 타원과 납작한 안쪽 타원이 양 끝에서 만나는 초승달. 굵히면 안쪽 타원을 더 납작하게."""
    thick = (HORIZON_OUTER[1] - HORIZON_INNER[1]) * bold
    outer = _arc(HORIZON_FROM, HORIZON_TO, *HORIZON_OUTER, sweep=1, steps=steps)
    inner = _arc(HORIZON_TO, HORIZON_FROM, HORIZON_INNER[0], HORIZON_OUTER[1] - thick, sweep=0, steps=steps)
    return outer + inner[1:-1]


def star_outline(bold: float, steps: int = 16) -> list[tuple[float, float]]:
    """4각 별 — 안으로 오목한 네 변. 굵히면 가운데를 더 도톰하게 (logo.js의 miniLogoSvg처럼 k · w를 키운다)."""
    grow = 1 + 0.3 * (bold - 1)   # 작은 크기에서는 별 자체도 키운다 — 16px에서 점 하나로 뭉개지지 않게
    cx, cy, arms = STAR["cx"], STAR["cy"], [a * grow for a in STAR["arms"]]
    k, w = 0.2 + 0.06 * (bold - 1), 4 + 10 * (bold - 1)
    dirs = [(0, -1), (1, 0), (0, 1), (-1, 0)]
    tip = lambda i: (cx + dirs[i][0] * arms[i], cy + dirs[i][1] * arms[i])  # noqa: E731
    pts = []
    for i in range(4):
        j = (i + 1) % 4
        (ax, ay), (bx, by) = dirs[i], dirs[j]
        c1 = (cx + ax * arms[i] * k + bx * w, cy + ay * arms[i] * k + by * w)
        c2 = (cx + bx * arms[j] * k + ax * w, cy + by * arms[j] * k + ay * w)
        seg = [tip(i), c1, c2, tip(j)]
        pts += [_bezier(seg, s / steps) for s in range(steps)]
    return pts


def logo_shapes(bold: float) -> dict:
    return {
        "horizon": horizon_outline(bold),
        "trail": trail_outline(bold),
        "star": star_outline(bold),
        "dot": (DOT["cx"], DOT["cy"], DOT["r"] * (1 + 0.7 * (bold - 1))),
        "gap": GAP * bold,
    }


def _bounds(shapes: dict) -> tuple[float, float, float, float]:
    pts = shapes["horizon"] + shapes["trail"] + shapes["star"]
    x, y, r = shapes["dot"]
    xs, ys = [p[0] for p in pts] + [x - r, x + r], [p[1] for p in pts] + [y - r, y + r]
    return min(xs), min(ys), max(xs), max(ys)


def square_box(shapes: dict, fill: float) -> tuple[float, float, float]:
    """로고 너비 · 높이 중 긴 쪽이 정사각형 한 변의 fill 비율이 되게 — (왼쪽, 위, 한 변)."""
    x0, y0, x1, y1 = _bounds(shapes)
    side = max(x1 - x0, y1 - y0) / fill
    return (x0 + x1) / 2 - side / 2, (y0 + y1) / 2 - side / 2, side


# ── SVG ──────────────────────────────────────────────────────────────────────
def _d(points) -> str:
    return "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in points) + "Z"


def favicon_svg(bold: float = 2.6, fill: float = 0.84, radius: float = 0.22) -> str:
    shapes = logo_shapes(bold)
    left, top, side = square_box(shapes, fill)
    x, y, r = shapes["dot"]
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{left:.1f} {top:.1f} {side:.1f} {side:.1f}">',
        f'  <rect x="{left:.1f}" y="{top:.1f}" width="{side:.1f}" height="{side:.1f}" rx="{side * radius:.1f}" fill="{NIGHT}"/>',
        f'  <path d="{_d(shapes["horizon"])}" fill="{HORIZON}"/>',
        f'  <path d="{_d(shapes["trail"])}" fill="{PEACH}" stroke="{NIGHT}" stroke-width="{shapes["gap"] * 2:.1f}" stroke-linejoin="round" paint-order="stroke"/>',
        f'  <circle cx="{x}" cy="{y}" r="{r:.1f}" fill="{PEACH}"/>',
        f'  <path d="{_d(shapes["star"])}" fill="{PEACH}"/>',
        "</svg>",
    ]
    return "\r\n".join(lines) + "\r\n"


# ── PNG ──────────────────────────────────────────────────────────────────────
def render(size: int, bold: float, fill: float, radius: float = 0.0, scale: int = 8) -> Image.Image:
    """size×size 그림 — scale배로 크게 그린 뒤 줄여 가장자리를 부드럽게. radius 0이면 가장자리까지 채운 사각."""
    shapes = logo_shapes(bold)
    left, top, side = square_box(shapes, fill)
    big = size * scale
    k = big / side
    tf = lambda pts: [((px - left) * k, (py - top) * k) for px, py in pts]  # noqa: E731

    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if radius:
        draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=round(big * radius), fill=NIGHT)
    else:
        draw.rectangle((0, 0, big, big), fill=NIGHT)
    draw.polygon(tf(shapes["horizon"]), fill=HORIZON)
    trail = tf(shapes["trail"])
    gap = max(1, round(shapes["gap"] * 2 * k))
    draw.line(trail + trail[:1], fill=NIGHT, width=gap, joint="curve")   # 지평선에 생기는 틈
    draw.polygon(trail, fill=PEACH)
    x, y, r = shapes["dot"]
    cx, cy = (x - left) * k, (y - top) * k
    draw.ellipse((cx - r * k, cy - r * k, cx + r * k, cy + r * k), fill=PEACH)
    draw.polygon(tf(shapes["star"]), fill=PEACH)
    return img.resize((size, size), Image.LANCZOS)


def og_image(src: Path = THUMBNAIL, out: Path = OG_IMAGE, size=(1200, 630), top_share: float = 0.4) -> Path:
    """썸네일을 1200×630으로 — 너비를 맞춘 뒤 남는 높이를 위 4 : 아래 6으로 잘라 로고 위 여백을 지킨다."""
    img = Image.open(src).convert("RGB")
    h = round(img.height * size[0] / img.width)
    img = img.resize((size[0], h), Image.LANCZOS)
    cut = h - size[1]
    y0 = round(cut * top_share)
    img = img.crop((0, y0, size[0], y0 + size[1]))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=85, optimize=True, progressive=True)
    return out


def manifest() -> dict:
    icon = lambda src, size, purpose: {"src": src, "sizes": f"{size}x{size}", "type": "image/png", "purpose": purpose}  # noqa: E731
    return {
        "name": NAME,
        "short_name": NAME,
        "description": DESCRIPTION,
        "lang": "ko",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": NIGHT,
        "theme_color": NIGHT,
        "icons": [
            {"src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
            icon("/icon-192.png", 192, "any"),
            icon("/icon-512.png", 512, "any"),
            icon("/icon-192.png", 192, "maskable"),
            icon("/icon-512.png", 512, "maskable"),
        ],
    }


def main() -> int:
    (WEB / "favicon.svg").write_bytes(favicon_svg().encode("utf-8"))

    # 작은 크기일수록 선을 더 굵히고 여백을 줄인다
    ico = {16: render(16, 3.4, 0.92, 0.18), 32: render(32, 2.6, 0.88, 0.2), 48: render(48, 2.2, 0.86, 0.22)}
    ico[48].save(WEB / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)], append_images=[ico[16], ico[32]])

    # 가장자리까지 채운 사각 — 로고 너비는 maskable 안전 원(지름 80%) 안에 들도록
    render(180, 1.8, 0.7).convert("RGB").save(WEB / "apple-touch-icon.png", optimize=True)
    render(192, 1.8, 0.62).convert("RGB").save(WEB / "icon-192.png", optimize=True)
    render(512, 1.4, 0.62).convert("RGB").save(WEB / "icon-512.png", optimize=True)

    text = json.dumps(manifest(), ensure_ascii=False, indent=2)
    (WEB / "manifest.json").write_bytes((text.replace("\n", "\r\n") + "\r\n").encode("utf-8"))

    og = og_image()
    print(f"아이콘 7개 · {og.relative_to(ROOT)} ({og.stat().st_size // 1024}KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
