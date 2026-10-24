"""공유 카드 — 공유 링크(/api/l/<id>)의 HTML 페이지와 1200×630 미리보기 이미지(PNG), 편지 전체를 담은 세로형 카드(PNG).

카카오톡 · 슬랙은 링크의 og:title · og:description · og:image(절대 주소)를 읽어 카드로 보여 준다.
페이지는 외부 CSS · 글꼴 없이 인라인 스타일만 쓴다 (미리보기 수집기 · 느린 회선에서도 바로 보이게).

이미지 글꼴: vasthorizon/assets/fonts/ — scripts/build_fonts.py가 KS X 1001 완성형 2,350자 + ASCII + 기본 문장 부호로
서브셋한 Noto Serif KR(제목) · VastHorizon Sans(Pretendard 서브셋, 본문). 글꼴에 없는 글자는 그리지 않는다 (drawable) —
제목 · 본문에서 글자를 뺐으면 카드 아래에 OMITTED_NOTE를 작게 적는다.
로고는 scripts/build_icons.py의 도형(web/js/logo.js와 같은 점)을 그대로 쓴다.

세로형 카드(share_tall_image, /api/l/<id>/tall.png): 폭 1080, 높이는 본문 길이에 맞춰 1620(2:3)~1920. 이미지로 저장 ·
카카오톡 피드 썸네일에 쓴다 — 채팅 폭으로 줄여도 읽히게 눈썹 · 제목을 카드 위쪽 1/3 안에 크게 둔다.
본문이 1920에도 넘치면 글자를 34 → 30 → 28px로 줄이고, 그래도 넘치면 '…'으로 자르고 TRUNCATED_NOTE를 적는다.
"""

from __future__ import annotations

import html
import io
import random
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
SERIF = "NotoSerifKR-Regular.ttf"
SANS = "VHSans-Regular.ttf"
SANS_BOLD = "VHSans-SemiBold.ttf"

# 색 (web/tokens/colors.css)
NIGHT = "#222454"        # 남보라 — 배경
VIOLET = "#4b3b7a"       # 보라 — 배경 그라데이션 끝
PAPER = "#FFF9F3"        # 종이색 카드
INK = "#282345"          # 카드 글
MUTED = "#6f6585"        # 눈썹 · 근거 줄
PEACH = "#F3DAD5"        # 살구 — 버튼 · 로고
WIDTH, HEIGHT = 1200, 630
TALL_WIDTH, TALL_MIN, TALL_MAX = 1080, 1620, 1920
TALL_BODY_SIZES = (34, 30, 28)  # 본문 글자 — 1920에 안 들어가면 차례로 줄인다
SITE_LABEL = "vasthorizon.bnbong.com"
TRUNCATED_NOTE = "편지 전체는 링크에서 읽을 수 있습니다"
INTERNAL_SOURCES = ("항목 메타데이터", "카탈로그", "계산")
OMITTED_NOTE = "일부 글자는 카드에 표시되지 않았습니다"

_CITE = re.compile(r"\s*\[근거\s*(\d+(?:\s*[,，]\s*\d+)*)\]")
_SENTENCE = re.compile(r"(?<=[.!?。？！])\s+")
_SPACES = re.compile(r"\s+")

PUNCTUATION = ("‐‑–—―‘’‚“”„•…‰′″※‼₩€℃™←↑→↓↔⇒∼≈≠≤≥∞√・、。〈〉《》「」『』【】〔〕〜～"
               "！？（），．：；ㆍ①②③④⑤⑥⑦⑧⑨⑩")


def font_charset() -> str:
    """서브셋에 남기는 글자 — scripts/build_fonts.py가 쓴다."""
    chars = [chr(c) for c in range(0x20, 0x7F)]                       # ASCII
    chars += [chr(c) for c in range(0xA0, 0x100)]                     # 라틴 1 보충 (· ° ± × ² ³ 등)
    chars += [chr(c) for c in range(0x391, 0x3AA)] + [chr(c) for c in range(0x3B1, 0x3CA)]   # 그리스 문자 (α 켄타우리 등)
    chars += [chr(c) for c in range(0x3131, 0x318F)]                  # 한글 호환 자모
    # 완성형 2,350자 = EUC-KR 두 바이트로 바뀌는 음절. 파이썬 euc-kr 코덱은 나머지 음절도 8바이트 조합형(KS X 1001 부속서)으로
    # 바꾸므로 길이로 가른다
    for code in range(0xAC00, 0xD7A4):
        if len(chr(code).encode("euc-kr")) == 2:
            chars.append(chr(code))
    chars += list(PUNCTUATION)
    return "".join(dict.fromkeys(chars))


# ── 글 정리 ───────────────────────────────────────────────────────────────

def plain(text: str) -> str:
    """[근거 N] 표시를 걷어 내고 공백을 한 칸으로."""
    return _SPACES.sub(" ", _CITE.sub("", text or "")).strip()


def description(text: str, limit: int = 120) -> str:
    """og:description — 본문 앞 두 문장, limit자 안."""
    sentences = [s for s in _SENTENCE.split(plain(text)) if s]
    out = " ".join(sentences[:2])
    if len(out) > limit:
        out = out[:limit - 1].rstrip() + "…"
    return out


def _safe_url(url: str) -> str | None:
    return url if isinstance(url, str) and url.startswith(("https://", "http://")) else None


def _body_html(text: str) -> str:
    """본문 — 줄바꿈으로 문단을 나누고 [근거 N]을 근거 목록으로 가는 작은 번호로."""
    def cite(m: re.Match) -> str:
        nums = re.findall(r"\d+", m.group(1))
        links = ", ".join(f'<a href="#c{n}" style="color:{MUTED};text-decoration:none">{n}</a>' for n in nums)
        return f'<sup style="font-size:.7em;margin-left:1px">[{links}]</sup>'
    paragraphs = [p.strip() for p in re.split(r"\n+", text or "") if p.strip()]
    return "".join(f'<p style="margin:0 0 1em">{_CITE.sub(cite, html.escape(p))}</p>' for p in paragraphs)


# ── HTML ─────────────────────────────────────────────────────────────────

# style="…" 안에 들어간다 — 큰따옴표를 쓰면 속성이 거기서 끝나 뒤의 선언(패딩 · 밑줄 없음 등)이 사라진다
_FONT_STACK = "'Noto Serif KR', 'Pretendard', 'Apple SD Gothic Neo', 'Malgun Gothic', serif"
_SANS_STACK = "'Pretendard', 'Apple SD Gothic Neo', 'Malgun Gothic', system-ui, sans-serif"


def _page(head: str, card: str, base: str) -> str:
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta name="theme-color" content="{NIGHT}">
{head}
<link rel="icon" href="{html.escape(base)}/favicon.svg" type="image/svg+xml">
</head>
<body style="margin:0;min-height:100vh;background:{NIGHT};color:{INK};font-family:{html.escape(_FONT_STACK, quote=False)};\
-webkit-text-size-adjust:100%">
<main style="box-sizing:border-box;max-width:680px;margin:0 auto;padding:40px 16px 56px">
{card}
</main>
</body>
</html>
"""


def _button(href: str, label: str) -> str:
    """살구색 블록 버튼 — 각진 모서리 · 남보라 글자 · 밑줄 없음. 감싸는 div(_button_row)가 가운데에 둔다."""
    return (f'<a href="{html.escape(href)}" style="display:inline-block;box-sizing:border-box;background:{PEACH};'
            f'color:{NIGHT};font-family:{html.escape(_SANS_STACK, quote=False)};font-weight:600;font-size:16px;'
            f'line-height:1.4;text-decoration:none;padding:14px 22px;border-radius:0">{html.escape(label)}</a>')


def _button_row(href: str, label: str) -> str:
    return f'<div style="margin-top:24px;text-align:center">{_button(href, label)}</div>'


def _brand(base: str) -> str:
    return (f'<p style="margin:0 0 20px;font-family:{html.escape(_SANS_STACK, quote=False)};font-size:15px;'
            f'letter-spacing:.04em"><a href="{html.escape(base)}/" style="color:{PEACH};text-decoration:none">'
            f'VastHorizon</a></p>')


def share_page(record: dict, base: str) -> str:
    """공유 링크의 HTML — OG · 트위터 카드 태그와 종이색 편지 카드."""
    sid = record["id"]
    url, image = f"{base}/api/l/{sid}", f"{base}/api/l/{sid}.png"
    title, desc = record.get("title") or "VastHorizon", description(record.get("text", ""))
    meta = [("og:type", "article"), ("og:site_name", "VastHorizon"), ("og:title", title), ("og:description", desc),
            ("og:url", url), ("og:image", image), ("og:image:width", "1200"), ("og:image:height", "630"),
            ("og:image:alt", title), ("og:locale", "ko_KR")]
    twitter = [("twitter:card", "summary_large_image"), ("twitter:title", title), ("twitter:description", desc),
               ("twitter:image", image)]
    head = "\n".join([f"<title>{html.escape(title)} · VastHorizon</title>",
                      f'<meta name="description" content="{html.escape(desc)}">',
                      f'<link rel="canonical" href="{html.escape(url)}">']
                     + [f'<meta property="{k}" content="{html.escape(v)}">' for k, v in meta]
                     + [f'<meta name="{k}" content="{html.escape(v)}">' for k, v in twitter])

    sans = html.escape(_SANS_STACK, quote=False)
    departure = (record.get("departure") or {}).get("summary")
    sub = (f'<p style="margin:0 0 24px;font-family:{sans};font-size:14px;line-height:1.6;color:{MUTED}">'
           f'{html.escape(departure)}</p>') if departure else '<div style="height:12px"></div>'
    cites = []
    for c in record.get("cited") or []:
        link = _safe_url(c.get("url"))
        name = html.escape(c.get("title") or "")
        label = f'<a href="{html.escape(link)}" style="color:{INK}" rel="noopener">{name}</a>' if link else name
        kind = f' <span style="color:{MUTED}">· {html.escape(c.get("source_type") or "")}</span>' if c.get("source_type") else ""
        cites.append(f'<li id="c{int(c.get("number") or 0)}" style="margin:0 0 6px">'
                     f'<span style="color:{MUTED}">[{int(c.get("number") or 0)}]</span> {label}{kind}</li>')
    evidence = (f'<section style="margin-top:28px;padding-top:18px;border-top:1px solid #e7ddd6;font-family:{sans};'
                f'font-size:14px;line-height:1.6"><h2 style="margin:0 0 10px;font-size:13px;font-weight:600;'
                f'letter-spacing:.06em;color:{MUTED}">근거</h2><ol style="list-style:none;margin:0;padding:0">'
                f'{"".join(cites)}</ol></section>') if cites else ""
    card = f"""{_brand(base)}
<article style="background:{PAPER};color:{INK};padding:36px 28px 32px;box-shadow:0 18px 48px rgba(0,0,0,.35)">
<p style="margin:0 0 12px;font-family:{sans};font-size:13px;font-weight:600;letter-spacing:.08em;color:{MUTED}">\
{html.escape(record.get("eyebrow") or "VastHorizon")}</p>
<h1 style="margin:0 0 10px;font-size:28px;line-height:1.35;font-weight:400;word-break:keep-all">{html.escape(title)}</h1>
{sub}
<div style="font-size:17px;line-height:1.85;word-break:keep-all">{_body_html(record.get("text", ""))}</div>
{evidence}
</article>
{_button_row(f"{base}/?letter={sid}", "VastHorizon에서 내 편지 받기")}
<p style="margin:22px 0 0;text-align:center;font-family:{sans};font-size:12px;line-height:1.7;color:#b9b3cf">\
VastHorizon이 수집한 공개 문서에 근거해 쓴 글입니다. 근거 문서는 각 출처의 라이선스(위키백과 CC BY-SA 등)를 따릅니다.</p>"""
    return _page(head, card, base)


def missing_page(base: str) -> str:
    """없는 · 만료된 공유 링크 (404)."""
    message = "이 편지는 만료되었거나 없는 주소입니다"
    head = "\n".join([f"<title>{message} · VastHorizon</title>", '<meta property="og:site_name" content="VastHorizon">',
                      f'<meta property="og:title" content="{message}">'])
    card = f"""{_brand(base)}
<article style="background:{PAPER};color:{INK};padding:40px 28px;box-shadow:0 18px 48px rgba(0,0,0,.35);text-align:center">
<h1 style="margin:0;font-size:22px;line-height:1.5;font-weight:400;word-break:keep-all">{message}</h1>
</article>
{_button_row(f"{base}/", "VastHorizon에서 내 편지 받기")}"""
    return _page(head, card, base)


# ── PNG ──────────────────────────────────────────────────────────────────

@lru_cache(maxsize=16)
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


@lru_cache(maxsize=4)
def _cmap(name: str) -> frozenset[int]:
    from fontTools.ttLib import TTFont
    with TTFont(str(FONT_DIR / name), lazy=True) as font:
        return frozenset(font.getBestCmap())


def drawable(text: str, font_name: str) -> str:
    """글꼴에 없는 글자(서브셋 밖)는 빼고 — 빈 네모로 그리지 않는다. 공백은 남긴다."""
    cmap = _cmap(font_name)
    return _SPACES.sub(" ", "".join(ch for ch in text if ch.isspace() or ord(ch) in cmap)).strip()


def omitted(text: str, font_name: str) -> bool:
    """drawable이 글자(공백 말고)를 하나라도 뺐는가."""
    cmap = _cmap(font_name)
    return any(not ch.isspace() and ord(ch) not in cmap for ch in text or "")


def _fit(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> str:
    """width 안에 들어가게 — 넘치면 뒤를 잘라 '…'."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int, max_lines: int) -> list[str]:
    """어절 단위로 줄을 나눈다 (한 어절이 너무 길면 글자 단위). max_lines를 넘치면 마지막 줄 끝에 '…'."""
    lines, line = [], ""
    for word in text.split(" "):
        candidate = f"{line} {word}" if line else word
        if draw.textlength(candidate, font=font) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = ""
        for ch in word:                                     # 너비보다 긴 어절 — 글자 단위로
            if draw.textlength(line + ch, font=font) > width and line:
                lines.append(line)
                line = ""
            line += ch
        if len(lines) > max_lines:
            break
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines, last = lines[:max_lines], lines[max_lines - 1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _background(seed: str, size: tuple[int, int] = (WIDTH, HEIGHT), count: int = 140) -> Image.Image:
    """남보라 → 보라 대각선 그라데이션 위 작은 별 점들 (같은 id면 같은 하늘)."""
    width, height = size
    down = Image.linear_gradient("L")                                  # 위 0 → 아래 255
    mask = ImageChops.add(down, down.rotate(90), scale=2)               # 왼쪽 위 0 → 오른쪽 아래 255
    mask = mask.resize((width, height), Image.BICUBIC)
    img = Image.composite(Image.new("RGB", (width, height), VIOLET), Image.new("RGB", (width, height), NIGHT), mask)
    stars = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(stars)
    rng = random.Random(seed)
    for _ in range(count):
        x, y = rng.uniform(0, width), rng.uniform(0, height)
        r = rng.choice((0.8, 1.0, 1.2, 1.6, 2.2))
        alpha = rng.randint(70, 220)
        color = (255, 250, 245, alpha) if rng.random() < 0.7 else (243, 218, 213, alpha)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)
    img.paste(stars, (0, 0), stars)
    return img


def logo(size: int, color: str = PEACH, scale: int = 6) -> Image.Image:
    """살구색 로고(투명 배경) — scripts/build_icons.py의 도형. 지평선 호는 조금 옅게, 궤적이 지나는 자리는 틈."""
    from scripts.build_icons import logo_shapes, square_box
    shapes = logo_shapes(1.0)
    left, top, side = square_box(shapes, 1.0)
    big = size * scale
    k = big / side
    tf = lambda pts: [((px - left) * k, (py - top) * k) for px, py in pts]  # noqa: E731
    mask = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(tf(shapes["horizon"]), fill=205)                      # logo.js의 .logo-horizon (불투명도 .8)
    trail = tf(shapes["trail"])
    draw.line(trail + trail[:1], fill=0, width=max(1, round(shapes["gap"] * 2 * k)), joint="curve")
    draw.polygon(trail, fill=255)
    x, y, r = shapes["dot"]
    cx, cy = (x - left) * k, (y - top) * k
    draw.ellipse((cx - r * k, cy - r * k, cx + r * k, cy + r * k), fill=255)
    draw.polygon(tf(shapes["star"]), fill=255)
    out = Image.new("RGBA", (big, big), color)
    out.putalpha(mask)
    return out.resize((size, size), Image.LANCZOS)


def cite_line(cited: list[dict]) -> str:
    if not cited:
        return "근거 · VastHorizon이 수집한 공개 문서"
    # 바깥 문서(위키백과 · NASA 등)를 앞에 — 카탈로그 값(항목 메타데이터)만 있으면 그것을
    first = next((c for c in cited if c.get("source_type") not in INTERNAL_SOURCES), cited[0])
    kind = first.get("source_type") or "문서"
    more = f" 외 {len(cited) - 1}건" if len(cited) > 1 else ""
    return f"근거 · {kind} 「{first.get('title') or ''}」{more}"


def share_image(record: dict) -> bytes:
    """1200×630 PNG — 왼쪽 아래 종이색 카드(눈썹 · 제목 · 본문 5줄 · 근거 줄), 오른쪽 위 로고와 워드마크."""
    img = _background(record.get("id", ""))
    draw = ImageDraw.Draw(img)

    mark = logo(160)
    img.paste(mark, (WIDTH - 64 - 160, 44), mark)
    word_font = _font(SANS_BOLD, 30)
    word_w = draw.textlength("VastHorizon", font=word_font)
    draw.text((WIDTH - 64 - 80 - word_w / 2, 44 + 160 + 14), "VastHorizon", font=word_font, fill=PEACH)

    left, right, bottom = 64, 950, HEIGHT - 48
    pad, inner = 44, 950 - 64 - 88
    eyebrow_font, title_font = _font(SANS_BOLD, 22), _font(SERIF, 44)
    body_font, cite_font = _font(SANS, 26), _font(SANS, 20)
    eyebrow = drawable(record.get("eyebrow") or "VastHorizon", SANS_BOLD)
    raw_title, raw_body = record.get("title") or "VastHorizon", plain(record.get("text", ""))
    lost = omitted(raw_title, SERIF) or omitted(raw_body, SANS)       # 서브셋 밖 글자(확장 음절 · 이모지 등)를 뺐다
    title = drawable(raw_title, SERIF)
    for size in (44, 40, 36):                                       # 긴 이름은 조금 줄여 한 줄에
        title_font = _font(SERIF, size)
        if draw.textlength(title, font=title_font) <= inner:
            break
    title = _fit(draw, title, title_font, inner)
    body = wrap(draw, drawable(raw_body, SANS), body_font, inner, 5)
    cite = _fit(draw, drawable(cite_line(record.get("cited") or []), SANS), cite_font, inner)
    note_font = _font(SANS, 16)

    line_h = 40
    note_h = 26 if lost else 0
    height = pad + 30 + 16 + 58 + 20 + line_h * len(body) + 18 + 28 + note_h + pad - 10
    top = bottom - height
    draw.rectangle((left + 6, top + 8, right + 6, bottom + 8), fill=(20, 18, 48))      # 그림자
    draw.rectangle((left, top, right, bottom), fill=PAPER)
    x, y = left + pad, top + pad
    draw.text((x, y), eyebrow, font=eyebrow_font, fill=MUTED)
    y += 30 + 16
    draw.text((x, y), title, font=title_font, fill=INK)
    y += 58 + 20
    for line in body:
        draw.text((x, y), line, font=body_font, fill=INK)
        y += line_h
    y += 18
    draw.line((x, y - 8, x + 40, y - 8), fill=PEACH, width=2)
    draw.text((x, y), cite, font=cite_font, fill=MUTED)
    if lost:
        draw.text((x, y + 30), OMITTED_NOTE, font=note_font, fill=MUTED)

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ── 세로형 카드 (이미지로 저장 · 카카오톡 피드) ──────────────────────────────

_BOLD_MARK = re.compile(r"\*\*")
TALL_CARD_X, TALL_CARD_TOP, TALL_BOTTOM = 56, 168, 64     # 카드 왼쪽 여백 · 카드 위 (하늘 띠) · 카드 아래 여백
TALL_PAD = 64                                             # 카드 안 여백
TALL_INNER = TALL_WIDTH - 2 * TALL_CARD_X - 2 * TALL_PAD    # 840 — 글이 들어가는 폭
TALL_TITLE_BIG = (68, 62)                                 # 짧은 제목 — 한 줄이 화면 폭의 2/3 안이면 더 크게 (카카오 썸네일)
TALL_TITLE_SIZES = (56, 50, 46)                           # 그 밖의 제목 — 두 줄 안에 들어가게
TALL_TITLE_SPAN = TALL_WIDTH * 2 // 3                     # 720


def _tall_paragraphs(text: str) -> list[str]:
    """본문 문단 — 줄바꿈으로 나누고 [근거 N] · 굵게(**) 표시를 걷어 낸다."""
    out = []
    for p in re.split(r"\n+", text or ""):
        p = plain(_BOLD_MARK.sub("", p))
        if p:
            out.append(p)
    return out


def _measure() -> ImageDraw.ImageDraw:
    return ImageDraw.Draw(Image.new("RGB", (1, 1)))


def tall_layout(record: dict) -> dict:
    """세로형 카드의 배치 — 그리지 않고 높이 · 글자 크기 · 줄을 정한다 (POST /api/share가 높이를 알려 줄 때도 쓴다).

    본문 줄은 문자열, 문단 사이는 None. 높이는 TALL_MIN ~ TALL_MAX.
    """
    draw = _measure()
    raw_title = record.get("title") or "VastHorizon"
    paragraphs = _tall_paragraphs(record.get("text", ""))
    lost = omitted(raw_title, SERIF) or any(omitted(p, SANS) for p in paragraphs)
    title = drawable(raw_title, SERIF)
    big = [s for s in TALL_TITLE_BIG if draw.textlength(title, font=_font(SERIF, s)) <= TALL_TITLE_SPAN]
    for title_size in big[:1] or TALL_TITLE_SIZES:
        title_font = _font(SERIF, title_size)
        if len(wrap(draw, title, title_font, TALL_INNER, 99)) <= 2:
            break
    title_lines = wrap(draw, title, title_font, TALL_INNER, 2)
    title_line_h = round(title_size * 1.36)
    head_h = 80 + 36 + 28 + title_line_h * len(title_lines) + 36 + 48      # 눈썹 · 제목 · 살구색 줄
    cite_font = _font(SANS, 26)
    cite = _fit(draw, drawable(cite_line(record.get("cited") or []), SANS), cite_font, TALL_INNER)

    def footer(notes: int) -> int:                        # 본문 뒤 — 근거 줄 · 안내 줄 · 주소 · 아래 여백
        return 44 + 40 + notes * 36 + 56 + 30 + TALL_PAD

    def body_lines(size: int) -> list[str | None]:
        font = _font(SANS, size)
        lines: list[str | None] = []
        for p in paragraphs:
            if lines:
                lines.append(None)
            lines += wrap(draw, drawable(p, SANS), font, TALL_INNER, 10_000)
        return lines

    def body_h(lines: list[str | None], size: int) -> int:
        line_h = round(size * 1.6)
        return sum(line_h if line is not None else round(line_h * 0.5) for line in lines)

    fixed = TALL_CARD_TOP + head_h + TALL_BOTTOM
    notes = int(lost)
    for size in TALL_BODY_SIZES:
        lines = body_lines(size)
        if fixed + body_h(lines, size) + footer(notes) <= TALL_MAX:
            break
    truncated = fixed + body_h(lines, size) + footer(notes) > TALL_MAX
    if truncated:                                          # 28px로도 넘친다 — 들어가는 데까지 자르고 '…'
        notes += 1
        room = TALL_MAX - fixed - footer(notes)
        while lines and body_h(lines, size) > room:
            lines.pop()
        while lines and lines[-1] is None:
            lines.pop()
        if lines:
            font = _font(SANS, size)
            last = lines[-1]
            while last and draw.textlength(last + "…", font=font) > TALL_INNER:
                last = last[:-1]
            lines[-1] = last.rstrip() + "…"
    height = TALL_MAX if truncated else max(TALL_MIN, min(TALL_MAX, fixed + body_h(lines, size) + footer(notes)))
    return {"height": height, "title_lines": title_lines, "title_size": title_size, "title_line_h": title_line_h,
            "body_size": size, "lines": lines, "cite": cite, "lost": lost, "truncated": truncated,
            "eyebrow": drawable(record.get("eyebrow") or "VastHorizon", SANS_BOLD)}


def tall_height(record: dict) -> int:
    return tall_layout(record)["height"]


def share_tall_image(record: dict) -> bytes:
    """1080×(1620~1920) PNG — 위쪽 하늘에 로고 · 워드마크, 그 아래 종이색 카드(눈썹 · 제목 · 본문 전체 · 근거 줄 · 주소)."""
    lay = tall_layout(record)
    height = lay["height"]
    img = _background(record.get("id", ""), (TALL_WIDTH, height), 220)
    draw = ImageDraw.Draw(img)

    mark_size = 64
    mark = logo(mark_size)
    mark_x, mark_y = TALL_WIDTH - TALL_CARD_X - mark_size, 52
    img.paste(mark, (mark_x, mark_y), mark)
    word_font = _font(SANS_BOLD, 30)
    word_w = draw.textlength("VastHorizon", font=word_font)
    draw.text((mark_x - 18 - word_w, mark_y + mark_size / 2), "VastHorizon", font=word_font, fill=PEACH, anchor="lm")

    left, right = TALL_CARD_X, TALL_WIDTH - TALL_CARD_X
    top, bottom = TALL_CARD_TOP, height - TALL_BOTTOM
    draw.rectangle((left + 8, top + 10, right + 8, bottom + 10), fill=(20, 18, 48))     # 그림자
    draw.rectangle((left, top, right, bottom), fill=PAPER)

    x, y = left + TALL_PAD, top + 80
    draw.text((x, y), lay["eyebrow"], font=_font(SANS_BOLD, 28), fill=MUTED)
    y += 36 + 28
    title_font = _font(SERIF, lay["title_size"])
    for line in lay["title_lines"]:
        draw.text((x, y), line, font=title_font, fill=INK, stroke_width=1, stroke_fill=INK)   # 줄여 보여도 흐리지 않게 조금 굵게
        y += lay["title_line_h"]
    y += 36
    draw.line((x, y, x + 56, y), fill=PEACH, width=3)
    y += 48

    size = lay["body_size"]
    body_font, line_h = _font(SANS, size), round(size * 1.6)
    for line in lay["lines"]:
        if line is None:
            y += round(line_h * 0.5)
            continue
        draw.text((x, y), line, font=body_font, fill=INK)
        y += line_h

    y += 44
    note_font = _font(SANS, 22)
    draw.text((x, y), lay["cite"], font=_font(SANS, 26), fill=MUTED)
    y += 40
    for note, on in ((TRUNCATED_NOTE, lay["truncated"]), (OMITTED_NOTE, lay["lost"])):
        if on:
            draw.text((x, y), note, font=note_font, fill=MUTED)
            y += 36
    draw.text((x, bottom - TALL_PAD - 30), SITE_LABEL, font=_font(SANS, 22), fill=MUTED)

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
