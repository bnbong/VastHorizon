"""편지 공유 — 캐시 적중만 공유 · 같은 내용은 같은 id · 사용자 문장 미저장 · OG 태그 · 미리보기 이미지 · 만료 정리 · 한도.

LLM을 부르지 않는다 — 가짜 응답을 서버 응답 캐시에 직접 넣고 공유한다.
"""

from __future__ import annotations

import dataclasses
import io
import json
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

from tests.test_api import ITEMS, FakeAsk, healthy
from tests.test_cost import STAR
from vasthorizon import config as config_module
from vasthorizon import sharecard
from vasthorizon.api import app as app_module
from vasthorizon.api.services import Services
from vasthorizon.cache import ResponseCache, text_hash
from vasthorizon.config import CacheConfig, ShareConfig, get_settings
from vasthorizon.share import DAY, ShareStore, ShareUnavailableError, content_hash, echoes, share_id

BASE = "https://vh.example.com"
HEIGHT_PX = sharecard.HEIGHT
LETTER = {
    "item_id": "Q3415", "item_name": "베가", "letter": "안녕, 지구의 친구야. 나는 베가야 [근거 1]. 내 빛은 25년 전에 출발했어. 잘 지내.",
    "status": "cited", "notice": None, "warnings": [], "cached": False, "matched_age": None, "age_gap_ly": None,
    "departure": {"light_years": 25.0, "light_time": "25년", "year": 2001, "year_label": "2001년", "era": "21세기",
                  "year_range": None, "summary": "빛이 걸리는 시간 25년 — 2001년 무렵(21세기) 출발"},
    "cited": [{"number": 1, "kind": "외부 문서", "source_type": "위키백과", "title": "베가", "section": "",
               "url": "https://ko.wikipedia.org/wiki/베가", "excerpt": "베가는 거문고자리의 가장 밝은 별이다."}],
}
SECRET = "오늘 팀장님께 혼나서 마음이 무겁다"          # 저장되면 안 되는 사용자 문장
PERSPECTIVE = {
    "status": "cited", "answer": "보이저 1호는 1977년에 떠나 지금도 신호를 보냅니다 [근거 1]. 먼 길도 이어집니다.",
    "crisis": False, "themes": ["끈기"], "items": [{"id": "Q48469", "name": "보이저 1호"}], "disclaimer": "안내",
    "support": [], "notice": None, "warnings": [], "cached": False,
    "cited": [{"number": 1, "kind": "외부 문서", "source_type": "NASA", "title": "Voyager 1", "section": "",
               "url": "https://science.nasa.gov/mission/voyager/", "excerpt": "..."}],
}


class ShareApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = [1_800_000_000.0]
        self.store = ShareStore(Path(self.tmp.name) / "share", days=180, clock=lambda: self.now[0])
        self.cache = ResponseCache(None)
        self.items = [*ITEMS, STAR]
        s = dataclasses.replace(get_settings(), cache=CacheConfig(enabled=True),
                                share=ShareConfig(public_base=BASE, per_ip_per_minute=20))
        with mock.patch.object(config_module, "get_settings", return_value=s):
            app = app_module.create_app(Services(items=self.items, ask=FakeAsk(), health=healthy, cache=self.cache,
                                                 share=self.store), web_dir=None)
        self.c = TestClient(app, raise_server_exceptions=False)
        self.fingerprint = app_module.cache_fingerprint(self.items, 2026)

    def put(self, namespace: str, parts, value: dict) -> None:
        self.cache.put(namespace, [self.fingerprint, parts], value, 7)

    def share_letter(self, **body):
        return self.c.post("/api/share", json={"kind": "letter", **(body or {"item_id": "Q3415"})})

    # ── 만들기 ──
    def test_cache_hit_creates_stable_id(self):
        self.put("letter", ["Q3415"], LETTER)
        first = self.share_letter()
        self.assertEqual(first.status_code, 201)
        body = first.json()
        self.assertRegex(body["id"], r"^[0-9a-f]{16}$")
        self.assertEqual(body["url"], f"{BASE}/api/l/{body['id']}")
        self.assertEqual(body["image_url"], f"{BASE}/api/l/{body['id']}.png")
        self.assertEqual(body["tall_image_url"], f"{BASE}/api/l/{body['id']}/tall.png")
        self.assertEqual(body["tall_image_height"], sharecard.TALL_MIN)        # 짧은 편지 — 2:3
        again = self.share_letter()
        by_age = self.share_letter(age=25)                                     # 나이 25 → 같은 별 · 같은 편지
        self.assertEqual((again.status_code, by_age.status_code), (200, 200))
        self.assertEqual({again.json()["id"], by_age.json()["id"]}, {body["id"]})
        self.assertEqual(again.json()["created"], body["created"])
        self.assertTrue(self.store.image_path(body["id"]).exists())          # 미리보기 이미지를 미리 그려 둔다
        self.assertTrue(self.store.image_path(body["id"], "tall").exists())  # 세로형 카드도 (카카오톡이 바로 가져간다)

    def test_cache_miss_is_404(self):
        r = self.share_letter()
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {"code": "share_not_ready", "message": "편지를 다시 받은 뒤 공유해 주세요."})
        r = self.c.post("/api/share", json={"kind": "perspective", "text": "처음 보내는 문장"})
        self.assertEqual(r.json()["code"], "share_not_ready")
        self.assertEqual(self.store.count(), 0)

    def test_refuses_crisis_and_unchecked(self):
        for status in ("crisis", "unchecked", "rejected"):
            self.put("perspective", [text_hash(status), None], {**PERSPECTIVE, "status": status,
                                                                 "crisis": status == "crisis"})
            r = self.c.post("/api/share", json={"kind": "perspective", "text": status})
            self.assertEqual((r.status_code, r.json()["code"]), (409, "share_refused"), status)
        self.put("letter", ["Q3415"], {**LETTER, "status": "rejected"})
        self.assertEqual(self.share_letter().status_code, 409)
        # 코드로 판정되는 위기 표현 — 캐시를 보기 전에 거절
        r = self.c.post("/api/share", json={"kind": "perspective", "text": "죽고 싶다"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.store.count(), 0)

    def test_perspective_does_not_store_user_text(self):
        self.put("perspective", [text_hash(SECRET), "persistence"], PERSPECTIVE)
        r = self.c.post("/api/share", json={"kind": "perspective", "text": SECRET, "theme": "persistence"})
        self.assertEqual(r.status_code, 201)
        sid = r.json()["id"]
        raw = (Path(self.tmp.name) / "share" / f"{sid}.json").read_text(encoding="utf-8")
        for fragment in (SECRET, "팀장님", text_hash(SECRET)):
            self.assertNotIn(fragment, raw)
        record = self.c.get(f"/api/l/{sid}.json").json()
        self.assertEqual((record["kind"], record["text"], record["themes"]), ("perspective", PERSPECTIVE["answer"], ["끈기"]))
        self.assertEqual(record["title"], "마음 한 줄에 닿은 우주의 사실")
        self.assertEqual(record["cited"], [{"number": 1, "title": "Voyager 1", "source_type": "NASA",
                                            "url": "https://science.nasa.gov/mission/voyager/"}])
        self.assertNotIn(SECRET, self.c.get(f"/api/l/{sid}").text)

    def test_perspective_refused_when_answer_echoes_user_text(self):
        answer = f"‘{SECRET}’라는 마음에 보이저 1호 이야기를 [근거 1] 전합니다."      # 사용자 문장을 그대로 되풀이
        self.put("perspective", [text_hash(SECRET), None], {**PERSPECTIVE, "answer": answer})
        r = self.c.post("/api/share", json={"kind": "perspective", "text": SECRET})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json(), {"code": "share_refused", "message": "적어 주신 문장이 답에 들어 있어 공유할 수 없습니다"})
        self.assertEqual(self.store.count(), 0)
        # 14자까지 겹치는 건 괜찮다
        short = "보이저 1호는 지금도   먼 길을"                                        # 공백 정규화 뒤 16자
        self.put("perspective", [text_hash(short), None], PERSPECTIVE)
        self.assertEqual(self.c.post("/api/share", json={"kind": "perspective", "text": short}).status_code, 201)

    def test_full_store_is_503(self):
        self.store.max_records = 1
        self.put("perspective", [text_hash(SECRET), None], PERSPECTIVE)
        self.assertEqual(self.c.post("/api/share", json={"kind": "perspective", "text": SECRET}).status_code, 201)
        self.put("letter", ["Q3415"], LETTER)
        r = self.share_letter()
        self.assertEqual((r.status_code, r.json()["code"]), (503, "share_unavailable"))
        # 이미 있는 공유는 상한과 상관없이 다시 공유된다
        self.assertEqual(self.c.post("/api/share", json={"kind": "perspective", "text": SECRET}).status_code, 200)

    def test_reshare_renews_expiry(self):
        sid = self.shared()
        first = self.store.get(sid)
        image = self.store.image_path(sid).read_bytes()
        self.now[0] += 100 * DAY
        r = self.share_letter()
        self.assertEqual((r.status_code, r.json()["id"], r.json()["created"]), (200, sid, first["created"]))
        renewed = self.store.get(sid)
        self.assertEqual(renewed["expires"], self.now[0] + 180 * DAY)
        self.assertEqual(self.store.image_path(sid).read_bytes(), image)            # 이미지는 그대로
        self.now[0] += 150 * DAY                                                    # 처음 기준이면 만료됐을 때
        self.assertIsNotNone(self.store.get(sid))

    def test_rate_limit_per_minute(self):
        codes = [self.share_letter().status_code for _ in range(21)]      # 캐시 미스(404)도 한도를 센다
        self.assertEqual(codes[:20], [404] * 20)
        self.assertEqual(codes[20], 429)
        r = self.share_letter()
        self.assertEqual(r.json()["message"], "잠시 뒤 다시 시도해 주세요.")
        self.assertIn("Retry-After", r.headers)
        # AI 한도와 별개 — 같은 주소의 조회는 그대로 된다
        self.assertEqual(self.c.get("/api/items").status_code, 200)

    # ── 보기 ──
    def shared(self) -> str:
        self.put("letter", ["Q3415"], LETTER)
        return self.share_letter().json()["id"]

    def test_html_has_og_tags_with_absolute_urls(self):
        sid = self.shared()
        r = self.c.get(f"/api/l/{sid}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/html"))
        page = r.text
        self.assertIn('<html lang="ko">', page)
        self.assertEqual(r.headers["x-robots-tag"], "noindex, nofollow")
        self.assertEqual(r.headers["cache-control"], "public, max-age=600")
        meta = dict(re.findall(r'<meta (?:property|name)="([^"]+)" content="([^"]*)"', page))
        self.assertEqual(meta["og:type"], "article")
        self.assertEqual(meta["og:title"], "베가에서 온 빛의 편지")
        self.assertEqual(meta["og:description"], "안녕, 지구의 친구야. 나는 베가야.")     # 앞 두 문장, [근거 N] 없이
        self.assertLessEqual(len(meta["og:description"]), 120)
        self.assertEqual(meta["og:image"], f"{BASE}/api/l/{sid}.png")
        self.assertEqual(meta["og:url"], f"{BASE}/api/l/{sid}")
        self.assertEqual((meta["og:image:width"], meta["og:image:height"]), ("1200", "630"))
        self.assertEqual(meta["og:site_name"], "VastHorizon")
        self.assertEqual(meta["twitter:card"], "summary_large_image")
        self.assertIn("noindex", meta["robots"])
        self.assertIn(f'href="{BASE}/?letter={sid}"', page)
        self.assertIn("VastHorizon에서 내 편지 받기", page)
        # 버튼 — 살구색 블록 · 남보라 글자 · 각진 모서리. style 속성이 큰따옴표에서 끊기지 않는다
        button = re.search(r'<a href="[^"]*\?letter=[^"]*" style="([^"]*)">VastHorizon에서 내 편지 받기</a>', page)
        self.assertIsNotNone(button)
        for decl in ("display:inline-block", "background:#F3DAD5", "color:#222454", "text-decoration:none",
                     "padding:14px 22px", "border-radius:0"):
            self.assertIn(decl, button.group(1))
        self.assertIn('<div style="margin-top:24px;text-align:center"><a href', page)
        for style in re.findall(r'style="([^"]*)"', page):                          # 어느 style도 글꼴 이름에서 끊기지 않는다
            self.assertFalse(style.rstrip().endswith("font-family:"), style)
        self.assertIn('href="https://ko.wikipedia.org/wiki/베가"', page)
        self.assertNotIn("<link rel=\"stylesheet\"", page)                  # 외부 CSS 없이

    def test_html_escapes_record_text(self):
        self.put("letter", ["Q3415"], {**LETTER, "letter": "<script>alert(1)</script> 편지.",
                                       "cited": [{**LETTER["cited"][0], "url": "javascript:alert(1)"}]})
        sid = self.share_letter().json()["id"]
        page = self.c.get(f"/api/l/{sid}").text
        self.assertNotIn("<script>", page)
        self.assertNotIn("javascript:", page)

    def test_missing_id_is_404(self):
        r = self.c.get("/api/l/0123456789ab")
        self.assertEqual(r.status_code, 404)
        self.assertIn("이 편지는 만료되었거나 없는 주소입니다", r.text)
        self.assertEqual(self.c.get("/api/l/0123456789ab.json").json()["code"], "share_not_found")
        self.assertEqual(self.c.get("/api/l/0123456789ab.png").status_code, 404)
        self.assertEqual(self.c.get("/api/l/..%2F..%2Fetc").status_code, 404)

    def test_cache_age_not_beyond_expiry(self):
        sid = self.shared()
        self.now[0] += 180 * DAY - 120                                              # 2분 남았다
        for suffix in ("", ".json", ".png", "/tall.png"):
            r = self.c.get(f"/api/l/{sid}{suffix}")
            self.assertEqual(r.status_code, 200, suffix)
            self.assertEqual(r.headers["cache-control"], "public, max-age=120", suffix)
            self.assertEqual(r.headers["x-robots-tag"], "noindex, nofollow", suffix)

    def test_json_returns_record(self):
        sid = self.shared()
        r = self.c.get(f"/api/l/{sid}.json")
        self.assertEqual(r.headers["cache-control"], "public, max-age=3600")
        self.assertEqual(r.headers["x-robots-tag"], "noindex, nofollow")
        record = r.json()
        stored = json.loads((Path(self.tmp.name) / "share" / f"{sid}.json").read_text(encoding="utf-8"))
        self.assertEqual(record, stored)
        self.assertEqual((record["id"], record["kind"], record["item_id"], record["item_name"], record["eyebrow"]),
                         (sid, "letter", "Q3415", "베가", "별"))
        self.assertEqual(record["departure"]["year"], 2001)
        self.assertEqual(record["text"], LETTER["letter"])

    def test_png_is_1200x630(self):
        sid = self.shared()
        self.store.image_path(sid).unlink()                                   # 요청할 때 다시 그린다
        r = self.c.get(f"/api/l/{sid}.png")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "image/png")
        self.assertEqual(r.headers["cache-control"], "public, max-age=86400")
        self.assertEqual(r.headers["x-robots-tag"], "noindex, nofollow")
        self.assertEqual(Image.open(io.BytesIO(r.content)).size, (1200, 630))
        self.assertTrue(self.store.image_path(sid).exists())                 # 디스크에 둔다
        self.assertEqual(self.c.get(f"/api/l/{sid}.png").content, r.content)

    def test_tall_png_short_letter_is_1080x1620(self):
        sid = self.shared()
        self.store.image_path(sid, "tall").unlink()                           # 요청할 때 다시 그린다
        r = self.c.get(f"/api/l/{sid}/tall.png")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "image/png")
        self.assertEqual(r.headers["cache-control"], "public, max-age=86400")
        self.assertEqual(r.headers["x-robots-tag"], "noindex, nofollow")
        self.assertEqual(Image.open(io.BytesIO(r.content)).size, (1080, 1620))
        self.assertTrue(self.store.image_path(sid, "tall").exists())         # 디스크에 <id>-tall.png로
        self.assertEqual(self.store.image_path(sid, "tall").name, f"{sid}-tall.png")
        self.assertEqual(self.c.get(f"/api/l/{sid}/tall.png").content, r.content)
        self.assertEqual(self.c.get("/api/l/0123456789ab/tall.png").status_code, 404)

    def test_tall_png_long_letter_shrinks_or_truncates_at_1920(self):
        self.put("letter", ["Q3415"], {**LETTER, "letter": ("빛은 아주 먼 길을 건너 여기에 닿았습니다 [근거 1]. " * 200)[:3000]})
        body = self.share_letter().json()
        self.assertEqual(body["tall_image_height"], sharecard.TALL_MAX)
        r = self.c.get(f"/api/l/{body['id']}/tall.png")
        self.assertEqual(r.headers["content-type"], "image/png")
        self.assertEqual(Image.open(io.BytesIO(r.content)).size, (1080, 1920))
        lay = sharecard.tall_layout(self.store.get(body["id"]))
        self.assertLess(lay["body_size"], sharecard.TALL_BODY_SIZES[0])      # 글자를 줄였다
        self.assertEqual(lay["body_size"], 28)
        self.assertTrue(lay["truncated"])                                     # 3,000자는 28px로도 넘친다 — 잘라 '…'
        self.assertTrue(lay["lines"][-1].endswith("…"))

    def test_health_reports_share_count(self):
        self.shared()
        self.assertEqual(self.c.get("/api/health").json()["share"], {"count": 1})

    # ── 만료 ──
    def test_expired_share_is_swept(self):
        sid = self.shared()
        orphan = self.store.image_path("ffffffffffff")
        orphan.write_bytes(b"png")                                            # 기록 없는 이미지
        self.store.image_path("ffffffffffff", "tall").write_bytes(b"png")     # 기록 없는 세로형 카드
        self.now[0] += 179 * DAY
        self.assertEqual(self.store.sweep(), 2)                               # 아직 만료 전 — 고아 이미지만
        self.assertIsNotNone(self.store.get(sid))
        self.now[0] += 2 * DAY
        self.assertEqual(self.store.sweep(), 3)                               # 기록 + 미리보기 이미지 + 세로형 카드
        self.assertFalse(any(Path(self.tmp.name, "share").iterdir()))
        self.assertEqual(self.c.get(f"/api/l/{sid}").status_code, 404)

    def test_expired_share_not_served_before_sweep(self):
        sid = self.shared()
        self.now[0] += 181 * DAY
        self.assertEqual(self.c.get(f"/api/l/{sid}.json").status_code, 404)
        self.assertEqual(self.share_letter().status_code, 201)              # 다시 공유하면 새로 만든다

    def test_sweep_keeps_record_renewed_after_read(self):
        sid = self.shared()
        self.now[0] += 181 * DAY
        real_read = self.store._read
        renewed = []

        def read_then_renew(share_id):                  # sweep이 만료를 읽은 바로 뒤 다른 요청이 다시 공유한다
            out = real_read(share_id)
            if not renewed and threading.current_thread().name == "sweeper-test":
                renewed.append(True)
                self.share_letter()
            return out

        with mock.patch.object(self.store, "_read", side_effect=read_then_renew):
            t = threading.Thread(target=self.store.sweep, name="sweeper-test")
            t.start()
            t.join(10)
        self.assertTrue(renewed)
        self.assertIsNotNone(self.store.get(sid))                                    # 늘어난 기록은 지우지 않는다
        self.assertEqual(self.store.count(), 1)

    def test_count_tracked_in_memory(self):
        sid = self.shared()
        self.assertEqual(self.store.count(), 1)
        with mock.patch.object(Path, "glob", side_effect=AssertionError("count는 파일을 세지 않는다")):
            self.assertEqual(self.store.count(), 1)
        self.now[0] += 181 * DAY
        self.assertIsNone(self.store.get(sid))
        self.assertEqual(self.store.count(), 0)
        reopened = ShareStore(Path(self.tmp.name) / "share", days=180, clock=lambda: self.now[0] - 181 * DAY)
        self.assertEqual(reopened.count(), 0)

    def test_id_collision_gets_longer_id(self):
        self.put("letter", ["Q3415"], LETTER)
        content = app_module.letter_record(LETTER, "별")
        full = content_hash(content)
        squatter = {"id": full[:16], "kind": "letter", "text": "다른 편지", "created": "x", "expires": self.now[0] + DAY}
        (Path(self.tmp.name) / "share").mkdir(parents=True, exist_ok=True)
        (Path(self.tmp.name) / "share" / f"{full[:16]}.json").write_text(json.dumps(squatter), encoding="utf-8")
        r = self.share_letter()
        self.assertEqual((r.status_code, r.json()["id"]), (201, full[:18]))
        self.assertEqual(self.store.get(full[:16])["text"], "다른 편지")                  # 기존 기록은 그대로
        self.assertEqual(self.share_letter().json()["id"], full[:18])                 # 다시 공유해도 같은 긴 id

    def test_sweep_on_start(self):
        sid = self.shared()
        self.now[0] += 200 * DAY
        ShareStore(Path(self.tmp.name) / "share", days=180, clock=lambda: self.now[0])
        self.assertFalse((Path(self.tmp.name) / "share" / f"{sid}.json").exists())


class ShareUnitTest(unittest.TestCase):
    def test_share_id_depends_on_content(self):
        a = {"kind": "letter", "text": "편지"}
        self.assertEqual(share_id(a), share_id(dict(a)))
        self.assertNotEqual(share_id(a), share_id({**a, "text": "다른 편지"}))

    def test_echoes(self):
        self.assertTrue(echoes("가나다라마바사아자차카타파하가", "앞 가나다라마바사아자차카타파하가 뒤"))
        self.assertFalse(echoes("가나다라마바사아자차카타파하", "가나다라마바사아자차카타파하"))      # 14자
        self.assertTrue(echoes("오늘   팀장님께 혼나서\n마음이 무겁다", "오늘 팀장님께 혼나서 마음이 [근거 1] 무겁다는 말"))
        self.assertFalse(echoes(None, "무엇이든"))

    def test_png_notes_omitted_glyphs(self):
        record = {"id": "0" * 16, "eyebrow": "별", "title": "베가에서 온 빛의 편지", "text": "안녕, 나는 베가야.", "cited": []}
        self.assertFalse(sharecard.omitted(record["title"] + record["text"], sharecard.SANS))
        self.assertTrue(sharecard.omitted("뷁 😀", sharecard.SANS))
        self.assertEqual(sharecard.drawable(sharecard.OMITTED_NOTE, sharecard.SANS), sharecard.OMITTED_NOTE)
        plain_png = sharecard.share_image(record)
        lost_png = sharecard.share_image({**record, "text": "안녕, 나는 뷁 베가야."})
        self.assertNotEqual(plain_png, lost_png)
        a = Image.open(io.BytesIO(plain_png)).convert("RGB")
        b = Image.open(io.BytesIO(lost_png)).convert("RGB")
        # 안내 줄만큼 카드가 위로 26px 더 올라간다 — 카드 왼쪽 위 모서리 픽셀로 확인
        paper = (0xFF, 0xF9, 0xF3)
        top_a = next(y for y in range(HEIGHT_PX) if a.getpixel((70, y)) == paper)
        top_b = next(y for y in range(HEIGHT_PX) if b.getpixel((70, y)) == paper)
        self.assertEqual(top_a - top_b, 26)

    def test_tall_layout_grows_with_body(self):
        record = {"id": "0" * 16, "eyebrow": "별", "title": "베가에서 온 빛의 편지", "cited": []}
        short = sharecard.tall_layout({**record, "text": "안녕, 나는 **베가**야 [근거 1]."})
        self.assertEqual((short["height"], short["body_size"], short["truncated"]), (sharecard.TALL_MIN, 34, False))
        self.assertEqual(short["lines"], ["안녕, 나는 베가야."])                    # 굵게 · 근거 표시는 걷어 낸다
        mid = sharecard.tall_layout({**record, "text": "별빛은 먼 길을 건너 왔습니다. " * 40})
        self.assertGreater(mid["height"], sharecard.TALL_MIN)
        self.assertLessEqual(mid["height"], sharecard.TALL_MAX)
        self.assertFalse(mid["truncated"])
        self.assertEqual(sum(1 for line in mid["lines"] if line), len(mid["lines"]))
        self.assertTrue(all(" " not in line[:1] for line in mid["lines"]))        # 어절 단위 — 줄이 공백으로 시작하지 않는다
        self.assertEqual(Image.open(io.BytesIO(sharecard.share_tall_image({**record, "text": "별빛은 먼 길을 건너 왔습니다. " * 40}))).size,
                         (1080, mid["height"]))

    def test_tall_title_large_and_in_upper_third(self):
        lay = sharecard.tall_layout({"id": "0" * 16, "eyebrow": "별", "title": "베가에서 온 빛의 편지", "text": "안녕.", "cited": []})
        self.assertGreaterEqual(lay["title_size"], 56)
        width = sharecard._measure().textlength(lay["title_lines"][0], font=sharecard._font(sharecard.SERIF, lay["title_size"]))
        self.assertGreater(width, sharecard.TALL_WIDTH / 2)                    # 화면 폭의 2/3 가까이
        self.assertLessEqual(width, sharecard.TALL_TITLE_SPAN)
        card_h = lay["height"] - sharecard.TALL_CARD_TOP - sharecard.TALL_BOTTOM
        title_end = 80 + 36 + 28 + lay["title_line_h"] * len(lay["title_lines"])
        self.assertLess(title_end, card_h / 3)

    def test_description_two_sentences_within_limit(self):
        self.assertEqual(sharecard.description("첫 문장이다 [근거 1, 2]. 둘째 문장! 셋째 문장."), "첫 문장이다. 둘째 문장!")
        long = "가" * 300 + "."
        self.assertEqual(len(sharecard.description(long)), 120)
        self.assertTrue(sharecard.description(long).endswith("…"))

    def test_cite_line_prefers_outside_document(self):
        cited = [{"number": 1, "title": "베가", "source_type": "항목 메타데이터"},
                 {"number": 2, "title": "2001년", "source_type": "위키백과"}]
        self.assertEqual(sharecard.cite_line(cited), "근거 · 위키백과 「2001년」 외 1건")
        self.assertEqual(sharecard.cite_line(cited[:1]), "근거 · 항목 메타데이터 「베가」")

    def test_fonts_cover_ks_x_1001(self):
        charset = sharecard.font_charset()
        self.assertEqual(sum(1 for ch in charset if "가" <= ch <= "힣"), 2350)
        for name in (sharecard.SERIF, sharecard.SANS, sharecard.SANS_BOLD):
            path = sharecard.FONT_DIR / name
            self.assertLess(path.stat().st_size, 2 * 1024 * 1024, name)
            text = "베가에서 온 빛의 편지 · 「근거」 2001년 — 우주…"
            self.assertEqual(sharecard.drawable(text, name), text, name)
        self.assertTrue((sharecard.FONT_DIR / "LICENSE-NotoSerifKR.txt").exists())
        self.assertTrue((sharecard.FONT_DIR / "LICENSE-Pretendard.txt").exists())

    def test_share_config(self):
        self.assertEqual(get_settings().share.days, 180)
        try:
            with mock.patch.dict(os.environ, {"VH_CONFIG": "config.deploy.toml", "VH_PUBLIC_BASE": "https://x.example/"}):
                get_settings.cache_clear()
                s = get_settings()
                self.assertEqual(s.share.public_base, "https://x.example")
                self.assertEqual(s.share.dir, config_module.PROJECT_ROOT / "data" / "deploy" / "share")
                self.assertEqual(s.share.per_ip_per_minute, 20)
        finally:
            get_settings.cache_clear()
        self.assertEqual(get_settings().share.public_base, "https://vasthorizon.bnbong.com")


if __name__ == "__main__":
    unittest.main()
