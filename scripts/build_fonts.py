"""공유 카드(vasthorizon/sharecard.py)가 쓰는 한글 글꼴 만들기 — 받아서 서브셋한 TTF를 저장소에 넣는다.

    pip install fonttools brotli          # requirements.txt의 데이터 준비 도구
    .venv/bin/python -m scripts.build_fonts

받는 글꼴 (data/raw/fonts/에 한 번만 받는다)
    Noto Serif KR    Google Fonts (google/fonts 저장소의 가변 글꼴) — wght 400으로 고정해 명조 제목에
    Pretendard       orioncactus/pretendard v1.3.9의 TTF (Regular · SemiBold) — 고딕 본문 · 눈썹에

남기는 글자: KS X 1001 완성형 한글 2,350자 + ASCII + 라틴 1 보충 + 그리스 문자 + 한글 자모 + 기본 문장 부호
(sharecard.font_charset). 이 밖의 글자는 카드에 그리지 않는다 (sharecard.drawable).

만드는 파일 (vasthorizon/assets/fonts/)
    NotoSerifKR-Regular.ttf
    VHSans-Regular.ttf · VHSans-SemiBold.ttf     Pretendard에서 만든 서브셋
    LICENSE-NotoSerifKR.txt · LICENSE-Pretendard.txt   SIL Open Font License 1.1

Pretendard의 라이선스는 'Pretendard'를 예약 글꼴 이름(Reserved Font Name)으로 둔다. 서브셋은 OFL의 '수정본'이라
그 이름을 쓸 수 없어 글꼴 이름(name 표)을 'VastHorizon Sans'로 바꾼다. Noto Serif KR에는 예약 이름이 없다.
"""

from __future__ import annotations

import io
from pathlib import Path

import requests
from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

from vasthorizon.config import PROJECT_ROOT
from vasthorizon.sharecard import FONT_DIR, font_charset

RAW = PROJECT_ROOT / "data" / "raw" / "fonts"
NOTO_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifkr/NotoSerifKR%5Bwght%5D.ttf"
NOTO_LICENSE_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifkr/OFL.txt"
PRETENDARD_VERSION = "v1.3.9"
PRETENDARD_URL = ("https://cdn.jsdelivr.net/gh/orioncactus/pretendard@" + PRETENDARD_VERSION
                  + "/packages/pretendard/dist/public/static/alternative/Pretendard-{weight}.ttf")
PRETENDARD_LICENSE_URL = f"https://raw.githubusercontent.com/orioncactus/pretendard/{PRETENDARD_VERSION}/LICENSE"
SANS_FAMILY = "VastHorizon Sans"


def fetch(url: str, name: str) -> bytes:
    """받은 파일은 data/raw/fonts/에 두고 다시 받지 않는다."""
    path = RAW / name
    if not path.exists():
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
    return path.read_bytes()


def subset_font(font: TTFont, chars: str) -> TTFont:
    options = subset.Options()
    options.hinting = False                        # 카드는 큰 크기로만 그린다 — 힌팅을 걷어 크기를 줄인다
    options.layout_features = ["kern", "liga", "ccmp", "locl"]
    options.name_IDs = ["*"]
    options.notdef_outline = True
    sub = subset.Subsetter(options)
    sub.populate(unicodes=[ord(c) for c in chars])
    sub.subset(font)
    return font


def rename(font: TTFont, family: str, style: str) -> None:
    """name 표의 글꼴 이름을 family로 — 예약 글꼴 이름을 지운다 (저작권 · 라이선스 줄은 그대로)."""
    full, ps = f"{family} {style}", f"{family.replace(' ', '')}-{style}"
    values = {1: family, 2: style, 3: f"{ps};subset", 4: full, 6: ps, 16: family, 17: style}
    table = font["name"]
    for record in list(table.names):
        if record.nameID in (21, 22, 25):               # WWS · 가변 글꼴 접두사 — 원래 이름이 남지 않게
            table.removeNames(nameID=record.nameID)
    for record in table.names:
        if record.nameID in values:
            record.string = values[record.nameID]


def save(font: TTFont, name: str) -> Path:
    out = FONT_DIR / name
    out.parent.mkdir(parents=True, exist_ok=True)
    font.save(out)
    return out


def license_text(url: str, name: str) -> Path:
    text = fetch(url, name).decode("utf-8").replace("\r\n", "\n")
    out = FONT_DIR / name
    out.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    return out


def main() -> int:
    chars = font_charset()
    made = []

    noto = TTFont(io.BytesIO(fetch(NOTO_URL, "NotoSerifKR[wght].ttf")))
    noto = instancer.instantiateVariableFont(noto, {"wght": 400}, updateFontNames=True)
    made.append(save(subset_font(noto, chars), "NotoSerifKR-Regular.ttf"))

    for weight in ("Regular", "SemiBold"):
        font = TTFont(io.BytesIO(fetch(PRETENDARD_URL.format(weight=weight), f"Pretendard-{weight}.ttf")))
        rename(font, SANS_FAMILY, weight)
        made.append(save(subset_font(font, chars), f"VHSans-{weight}.ttf"))

    license_text(NOTO_LICENSE_URL, "LICENSE-NotoSerifKR.txt")
    license_text(PRETENDARD_LICENSE_URL, "LICENSE-Pretendard.txt")
    for path in made:
        print(f"{path.relative_to(PROJECT_ROOT)} ({path.stat().st_size // 1024}KB)")
    print(f"글자 {len(chars)}자 · 라이선스 2개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
