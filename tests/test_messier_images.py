"""메시에 사진 수집 (12번) — 페이지 해석 · 출처 없는 사진 제외 · 404와 장애 구분 · 축소. 외부 호출 없음.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from vasthorizon.config import PROJECT_ROOT
from vasthorizon.data.messier_images import build, parse_page, pick_image, to_jpeg

PAGE_HTML = """<html><head><meta property="og:image" content="https://science.nasa.gov/wp-content/uploads/m1.webp?x=1" />
</head><body><figure><img src="m1.webp"></figure><figcaption><div class="hds-credits">NASA, ESA, J. Hester &amp; A. Loll</div>
</figcaption><div class="hds-credits">두 번째 그림의 출처</div></body></html>"""


def png_bytes(w=1280, h=900):
    out = io.BytesIO()
    Image.new("RGB", (w, h), (30, 40, 60)).save(out, "PNG")
    return out.getvalue()


class Resp:
    def __init__(self, status=200, text="", content=b"", ctype="text/html"):
        self.status_code, self.text, self.content, self.headers = status, text, content, {"content-type": ctype}


class HttpError(Exception):
    def __init__(self, status):
        super().__init__(status)
        self.response = Resp(status)


class ParseTest(unittest.TestCase):
    def test_first_credit_and_image_without_query(self):
        self.assertEqual(parse_page(PAGE_HTML), {"image": "https://science.nasa.gov/wp-content/uploads/m1.webp",
                                                 "credit": "NASA, ESA, J. Hester & A. Loll"})

    def test_no_credit_or_image_is_none(self):
        self.assertIsNone(parse_page('<meta property="og:image" content="x.jpg">'))      # 출처 없는 사진은 쓰지 않는다
        self.assertIsNone(parse_page('<div class="hds-credits">NASA</div>'))
        self.assertIsNone(parse_page('<meta property="og:image" content="x.jpg"><div class="hds-credits"> </div>'))

    def test_to_jpeg_shrinks_long_side(self):
        img = Image.open(io.BytesIO(to_jpeg(png_bytes())))
        self.assertEqual((img.format, max(img.size)), ("JPEG", 512))


BASE = "https://assets.science.nasa.gov/content/dam/science/missions/hubble/galaxies/m4/"


class BannerTest(unittest.TestCase):
    def test_new_image_replaced_by_same_stem_final(self):
        og = BASE + "potw1_NewImage.jpg"
        text = f'<img src="{BASE}other_FINAL.jpg"><img src="{BASE}potw1_NewImage.jpg"><img src="{BASE}potw1_FINAL.jpg?w=300">'
        self.assertEqual(pick_image(text, og), BASE + "potw1_FINAL.jpg")

    def test_falls_back_to_any_clean_hubble_image(self):
        og = BASE + "potw1_new-image.png"
        text = f'<img src="{BASE}x_FINAL_2026.jpg"><img src="https://example.com/y.jpg">'
        self.assertEqual(pick_image(text, og), BASE + "x_FINAL_2026.jpg")

    def test_no_alternative_keeps_og(self):
        og = BASE + "potw1_New_Image.jpg"
        self.assertEqual(pick_image(f'<img src="{og}">', og), og)

    def test_clean_og_untouched(self):
        og = BASE + "a.jpg"
        self.assertEqual(pick_image(f'<img src="{BASE}b_FINAL.jpg">', og), og)

    def test_parse_page_uses_alternative_and_build_warns_without(self):
        og = BASE + "p_NewImage.jpg"
        tpl = '<meta property="og:image" content="%s?x=1"><div class="hds-credits">NASA</div>%s'
        self.assertEqual(parse_page(tpl % (og, f'<a href="{BASE}p_FINAL.jpg">'))["image"], BASE + "p_FINAL.jpg")
        logs = []
        get = lambda url: Resp(text=tpl % (og, "")) if "messier-" in url else Resp(content=png_bytes(), ctype="image/png")
        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp), get, numbers=[4], log=logs.append)
        self.assertTrue(any("띠 없는 대안" in m for m in logs))


class BuildTest(unittest.TestCase):
    def test_build_skips_missing_and_keeps_going(self):
        logs = []

        def get(url):
            if "messier-1/" in url:
                return Resp(text=PAGE_HTML)
            if "messier-2/" in url:
                raise HttpError(404)                       # 허블 목록에 없는 천체
            if "messier-3/" in url:
                raise ConnectionError("down")              # 장애 — 다음 실행에서 다시
            return Resp(content=png_bytes(), ctype="image/png")

        with tempfile.TemporaryDirectory() as tmp:
            credits = build(Path(tmp), get, numbers=[1, 2, 3], log=logs.append)
            self.assertEqual(list(credits), ["M1"])
            self.assertTrue((Path(tmp) / "M1.jpg").exists())
            saved = json.loads((Path(tmp) / "credits.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["M1"]["credit"], "NASA, ESA, J. Hester & A. Loll")
            self.assertTrue(any("M2: 페이지 없음" in m for m in logs))
            self.assertTrue(any("M3: ConnectionError — 다음 실행에서 다시" in m for m in logs))
            calls = []
            build(Path(tmp), lambda url: calls.append(url) or Resp(404), numbers=[1], log=logs.append)
            self.assertEqual(calls, [])                    # 이미 받은 사진은 다시 받지 않는다


class BuiltFilesTest(unittest.TestCase):
    def test_every_photo_has_credit(self):
        folder = PROJECT_ROOT / "web" / "data" / "messier"
        credits = json.loads((folder / "credits.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(credits), 80)
        photos = {p.stem for p in folder.glob("M*.jpg")}
        self.assertEqual(photos, set(credits))
        self.assertTrue(all(c["credit"].strip() and c["page"].startswith("https://science.nasa.gov/") for c in credits.values()))


if __name__ == "__main__":
    unittest.main()
