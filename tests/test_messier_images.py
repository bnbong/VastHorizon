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
from vasthorizon.data.messier_images import HD_WIDTH, build, build_hd, parse_page, pick_image, to_jpeg

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

    def test_to_jpeg_hd_width(self):
        img = Image.open(io.BytesIO(to_jpeg(png_bytes(2000, 1400), HD_WIDTH)))
        self.assertEqual((img.format, img.size), ("JPEG", (1024, 717)))


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


class HdTest(unittest.TestCase):
    def test_build_width_asks_and_shrinks(self):
        urls = []

        def get(url):
            urls.append(url)
            return Resp(text=PAGE_HTML) if "messier-1/" in url else Resp(content=png_bytes(2000, 1400), ctype="image/png")

        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp), get, numbers=[1], log=lambda m: None, width=HD_WIDTH)
            self.assertTrue(urls[-1].endswith("?w=1024"))
            self.assertEqual(max(Image.open(Path(tmp) / "M1.jpg").size), 1024)

    def test_build_hd_uses_credit_image_and_skips_done(self):
        logs, urls = [], []

        def get(url):
            urls.append(url)
            if url.startswith("https://x/m2"):
                raise ConnectionError("down")
            return Resp(content=png_bytes(2000, 1400), ctype="image/png")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "credits.json").write_text(json.dumps({"M1": {"credit": "NASA", "page": "p", "image": "https://x/m1.jpg"},
                                                          "M2": {"credit": "NASA", "page": "p", "image": "https://x/m2.jpg"}}), encoding="utf-8")
            done = build_hd(out, get, log=logs.append)
            self.assertEqual(list(done), ["M1"])
            self.assertEqual(urls, ["https://x/m1.jpg?w=1024", "https://x/m2.jpg?w=1024"])   # 같은 사진 — 페이지는 다시 읽지 않는다
            self.assertEqual(Image.open(out / "hd" / "M1.jpg").size, (1024, 717))
            self.assertFalse((out / "M1.jpg").exists())                                       # 512 사진은 건드리지 않는다
            self.assertTrue(any("M2: ConnectionError" in m for m in logs))
            urls.clear()
            build_hd(out, get, log=logs.append)
            self.assertEqual(urls, ["https://x/m2.jpg?w=1024"])                               # 이미 받은 사진은 다시 받지 않는다
            self.assertEqual(list((out / "hd").glob("*.tmp")), [])                           # 임시 파일은 남지 않는다

    def test_build_hd_refetches_empty_or_broken_file(self):
        urls = []
        get = lambda url: urls.append(url) or Resp(content=png_bytes(2000, 1400), ctype="image/png")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "credits.json").write_text(json.dumps({"M1": {"credit": "NASA", "page": "p", "image": "https://x/m1.jpg"},
                                                          "M2": {"credit": "NASA", "page": "p", "image": "https://x/m2.jpg"}}), encoding="utf-8")
            (out / "hd").mkdir()
            (out / "hd" / "M1.jpg").write_bytes(b"")                    # 0바이트 — 끊긴 다운로드
            (out / "hd" / "M2.jpg").write_bytes(b"<html>")              # JPEG가 아니다
            done = build_hd(out, get, log=lambda m: None)
            self.assertEqual(sorted(urls), ["https://x/m1.jpg?w=1024", "https://x/m2.jpg?w=1024"])
            self.assertEqual(sorted(done), ["M1", "M2"])
            self.assertTrue(all((out / "hd" / f"{k}.jpg").read_bytes()[:2] == b"\xff\xd8" for k in done))


class BuiltFilesTest(unittest.TestCase):
    def test_every_photo_has_credit(self):
        folder = PROJECT_ROOT / "web" / "data" / "messier"
        credits = json.loads((folder / "credits.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(credits), 80)
        photos = {p.stem for p in folder.glob("M*.jpg")}
        self.assertEqual(photos, set(credits))
        self.assertTrue(all(c["credit"].strip() and c["page"].startswith("https://science.nasa.gov/") for c in credits.values()))

    def test_every_hd_photo_has_credit(self):
        folder = PROJECT_ROOT / "web" / "data" / "messier"
        credits = json.loads((folder / "credits.json").read_text(encoding="utf-8"))
        hd = {p.stem for p in (folder / "hd").glob("M*.jpg")}
        self.assertLessEqual(hd, set(credits))                    # 고해상도 사진도 출처 표기(credits.json)가 있는 것만


if __name__ == "__main__":
    unittest.main()
