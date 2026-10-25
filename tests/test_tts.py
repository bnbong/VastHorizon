"""편지 읽어 주기 — 조각 나누기 바이트 상한 · 글자 수 원장(월 · 일, 한국 시각) · 쿨다운 · 오디오 캐시 · Google 오류 분류.

Google은 부르지 않는다 — 가짜 합성기(synth)나 가짜 post를 넣는다.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from vasthorizon.config import get_settings
from vasthorizon.tts import (
    CHUNK_BYTES, COOLDOWN_SECONDS, REQUEST_BYTES, TtsError, TtsQuotaError, TtsService, TtsUnavailableError, chunks,
    record_text, seconds_until_next_month, sentences, speakable_text, synthesize, synthesize_text,
)
from vasthorizon.usage import KST, UsageLog

LETTER = "안녕, 지구의 친구야. 나는 **베가**야 [근거 1]. 내 빛은 25년 전에 출발했어!\n\n잘 지내?  고마워"


class FakeSynth:
    def __init__(self, error: Exception | None = None, fail_at: int | None = None):
        self.calls: list[str] = []
        self.error = error
        self.fail_at = fail_at

    def __call__(self, text: str) -> bytes:
        self.calls.append(text)
        if self.error is not None and (self.fail_at is None or len(self.calls) == self.fail_at):
            raise self.error
        return f"<mp3:{len(text)}>".encode()


class FakeResp:
    def __init__(self, status: int, body: dict | None = None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


class ChunkTest(unittest.TestCase):
    def test_thousands_commas_removed(self):
        self.assertEqual(speakable_text("3,780만 년"), "3780만 년")
        self.assertEqual(speakable_text("1,234,567"), "1234567")
        self.assertEqual(speakable_text("299,792.458"), "299792.458")
        self.assertEqual(speakable_text("3，780만"), "3780만")
        self.assertEqual(speakable_text("1,2는 그대로"), "1,2는 그대로")
        self.assertEqual(speakable_text("1,2345"), "1,2345")

    def test_sentence_comma_not_split_by_number(self):
        self.assertEqual(sentences("3,780만 년 전, 빛이 출발했어."), ["3780만 년 전, 빛이 출발했어."])

    def test_same_rules_as_web_tts(self):
        self.assertEqual(speakable_text("**베가**의 빛이 [근거 1, 2] 출발했어."), "베가의 빛이 출발했어.")
        self.assertEqual(sentences(LETTER), ["안녕, 지구의 친구야.", "나는 베가야.", "내 빛은 25년 전에 출발했어!", "잘 지내?", "고마워"])
        self.assertEqual(sentences(" [근거 3] . "), [])
        self.assertEqual(chunks(LETTER), ["안녕, 지구의 친구야. 나는 베가야. 내 빛은 25년 전에 출발했어! 잘 지내? 고마워"])
        self.assertEqual(chunks(""), [])

    def test_chunks_within_byte_limit(self):
        sentence = "아주 먼 별에서 출발한 빛이 오랫동안 우주를 건너 오늘 밤 너에게 닿았어."
        text = " ".join([sentence] * 200)                   # 한글 약 8,000자 · 2만 바이트 넘게
        parts = chunks(text)
        self.assertGreater(len(parts), 4)
        for p in parts:
            self.assertLessEqual(len(p.encode("utf-8")), CHUNK_BYTES)
            self.assertTrue(p.endswith("닿았어."), p[-10:])  # 문장 중간에서 자르지 않는다
        self.assertEqual(" ".join(parts), text)
        self.assertLess(CHUNK_BYTES, REQUEST_BYTES)

    def test_long_sentence_splits_at_comma_then_space_then_char(self):
        clause = "아주 먼 별에서 출발한 빛이 오랫동안 우주를 건너"
        long = ", ".join([clause] * 200) + "."
        parts = chunks(long, max_bytes=500)
        self.assertGreater(len(parts), 1)
        for p in parts:
            self.assertLessEqual(len(p.encode("utf-8")), 500)
        self.assertEqual(" ".join(parts), long)
        blob = "가" * 400                                     # 공백 없이 1,200바이트
        parts = chunks(blob, max_bytes=500)
        self.assertEqual("".join(parts), blob)
        for p in parts:
            self.assertLessEqual(len(p.encode("utf-8")), 500)

    def test_record_text_reads_title_then_body(self):
        self.assertEqual(record_text({"title": "베가에서 온 빛의 편지", "text": "안녕."}), "베가에서 온 빛의 편지.\n안녕.")
        self.assertEqual(record_text({"text": "안녕."}), "안녕.")


class SynthesizeTest(unittest.TestCase):
    KEY = "secret-key-123"

    def call(self, resp=None, error=None):
        def post(url, headers=None, json=None, timeout=None):
            self.sent = dict(url=url, headers=headers, json=json, timeout=timeout)
            if error is not None:
                raise error
            return resp
        return synthesize("안녕.", api_key=self.KEY, voice="ko-KR-Chirp3-HD-Aoede", speaking_rate=0.95, timeout=20, post=post)

    def test_request_body_and_audio(self):
        audio = self.call(FakeResp(200, {"audioContent": base64.b64encode(b"ID3mp3").decode()}))
        self.assertEqual(audio, b"ID3mp3")
        self.assertEqual(self.sent["url"], "https://texttospeech.googleapis.com/v1/text:synthesize")
        self.assertEqual(self.sent["headers"], {"X-Goog-Api-Key": self.KEY})      # 주소(?key=)에 넣지 않는다 — 로그에 남지 않게
        self.assertEqual(self.sent["timeout"], 20)
        self.assertEqual(self.sent["json"], {"input": {"text": "안녕."},
                                             "voice": {"languageCode": "ko-KR", "name": "ko-KR-Chirp3-HD-Aoede"},
                                             "audioConfig": {"audioEncoding": "MP3", "speakingRate": 0.95}})

    def test_429_and_403_are_quota(self):
        for status in (429, 403):
            with self.assertRaises(TtsQuotaError, msg=status) as ctx:
                self.call(FakeResp(status, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "key=" + self.KEY}}))
            self.assertNotIn(self.KEY, str(ctx.exception))

    def test_other_errors_hide_key(self):
        for resp, error in ((FakeResp(500), None), (FakeResp(200, {}), None),
                            (None, TimeoutError(f"https://x/?key={self.KEY} timed out"))):
            with self.assertRaises(TtsError) as ctx:
                self.call(resp, error)
            self.assertNotIsInstance(ctx.exception, TtsQuotaError)
            self.assertNotIn(self.KEY, str(ctx.exception))
            self.assertIsNone(ctx.exception.__cause__)            # 원래 예외(주소에 키)를 잇지 않는다

    def test_synthesize_text_joins_chunks(self):
        posted = []

        def post(url, headers=None, json=None, timeout=None):
            posted.append(json["input"]["text"])
            return FakeResp(200, {"audioContent": base64.b64encode(f"[{len(posted)}]".encode()).decode()})
        text = " ".join(["별빛이 오랫동안 우주를 건너 오늘 밤 너에게 닿았어."] * 300)
        audio, chars = synthesize_text(text, api_key="k", voice="v", speaking_rate=1.0, post=post)
        self.assertGreater(len(posted), 1)
        self.assertEqual(audio, b"".join(f"[{i + 1}]".encode() for i in range(len(posted))))
        self.assertEqual(chars, sum(len(p) for p in posted))


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "tts"
        self.clock = [1_800_000_000.0]
        self.when = [datetime(2026, 10, 25, 12, 0, tzinfo=KST)]

    def service(self, synth=None, **kw) -> TtsService:
        self.synth = synth or FakeSynth()
        kw.setdefault("api_key", "k")
        return TtsService(self.dir, synth=self.synth, clock=lambda: self.clock[0], now=lambda: self.when[0], **kw)

    def ledger(self) -> dict:
        return json.loads((self.dir / "ledger.json").read_text(encoding="utf-8"))

    def test_no_key_is_unavailable(self):
        tts = self.service(api_key="")
        self.assertFalse(tts.available)
        with self.assertRaises(TtsUnavailableError):
            tts.audio("안녕.")
        self.assertEqual(self.synth.calls, [])
        self.assertFalse(self.service(enabled=False).available)
        self.assertTrue(self.service().available)

    def test_cache_hit_skips_google(self):
        tts = self.service()
        self.assertIsNone(tts.cached(LETTER))
        first = tts.audio(LETTER)
        self.assertEqual(len(self.synth.calls), 1)
        self.assertEqual(tts.cached(LETTER), first)
        self.assertEqual(tts.audio(LETTER), first)
        self.assertEqual(len(self.synth.calls), 1)                 # 두 번째는 파일에서
        self.assertTrue(tts.audio_path(tts.cache_key(LETTER)).exists())
        self.assertRegex(tts.cache_key(LETTER), r"^[0-9a-f]{24}$")
        # 표시 기호만 다른 글은 같은 키, 음성 · 속도가 다르면 다른 키
        self.assertEqual(tts.cache_key(LETTER), tts.cache_key(LETTER.replace("**", "")))
        self.assertNotEqual(tts.cache_key(LETTER), self.service(voice="ko-KR-Neural2-A").cache_key(LETTER))
        self.assertNotEqual(tts.cache_key(LETTER), self.service(speaking_rate=1.0).cache_key(LETTER))

    def test_ledger_counts_chars_after_success(self):
        tts = self.service()
        tts.audio(LETTER)
        n = len(chunks(LETTER)[0])
        self.assertEqual(self.ledger(), {"month": "2026-10", "month_chars": n, "day": "2026-10-25", "day_chars": n})
        self.assertEqual(tts.status(), {"available": True, "month_chars": n, "monthly_chars": 900000, "day_chars": n,
                                        "cooldown": False, "ledger_ok": True})

    def test_daily_and_monthly_caps(self):
        tts = self.service(daily_chars=130, monthly_chars=250)
        text = "가" * 59 + "."                                     # 60자
        tts.audio(text)
        with self.assertRaises(TtsQuotaError) as ctx:              # 60 + 80 > 130
            tts.audio("라" * 79 + ".")
        self.assertEqual(ctx.exception.reason, "day")
        self.assertEqual(ctx.exception.retry_after, 12 * 3600 + 1)
        self.assertEqual(len(self.synth.calls), 1)                 # 넘기 전에 막는다 — Google을 부르지 않는다
        self.assertEqual(tts.audio(text), b"<mp3:60>")             # 캐시는 한도와 관계없이
        self.when[0] = datetime(2026, 10, 26, 0, 0, 1, tzinfo=KST)      # 한국 시각 다음 날 — 일 한도는 새로
        tts.audio("나" * 59 + ".")
        tts.audio("다" * 59 + ".")
        self.assertEqual(self.ledger(), {"month": "2026-10", "month_chars": 180, "day": "2026-10-26", "day_chars": 120})
        self.when[0] = datetime(2026, 10, 27, 9, 0, tzinfo=KST)
        with self.assertRaises(TtsQuotaError) as ctx:              # 180 + 80 > 250
            tts.audio("라" * 79 + ".")
        self.assertEqual(ctx.exception.reason, "month")
        self.assertEqual(ctx.exception.retry_after, seconds_until_next_month(self.when[0]))

    def test_month_rolls_over_in_kst(self):
        tts = self.service(monthly_chars=100)
        self.when[0] = datetime(2026, 10, 31, 23, 30, tzinfo=KST)
        tts.audio("가" * 89 + ".")
        # UTC로는 아직 10월 31일 15시 30분 — 한국 시각으로 11월 1일이면 새 달
        self.when[0] = datetime.fromisoformat("2026-10-31T15:30:00+00:00")
        tts.audio("나" * 89 + ".")
        self.assertEqual(self.ledger(), {"month": "2026-11", "month_chars": 90, "day": "2026-11-01", "day_chars": 90})
        self.assertEqual(seconds_until_next_month(datetime.fromisoformat("2026-11-30T23:59:00+09:00")), 61)

    def test_broken_ledger_blocks_synthesis(self):
        tts = self.service()
        self.dir.mkdir(parents=True, exist_ok=True)
        for broken in ("{not json", "[1, 2]", '{"month": "2026-10", "month_chars": "많이"}'):
            (self.dir / "ledger.json").write_text(broken, encoding="utf-8")
            with self.assertRaises(TtsUnavailableError), self.assertLogs("vasthorizon.tts", "WARNING"):
                tts.audio("안녕.")
            self.assertEqual((self.dir / "ledger.json").read_text(encoding="utf-8"), broken)   # 지우지 않는다
            with self.assertLogs("vasthorizon.tts", "WARNING"):
                self.assertFalse(tts.status()["ledger_ok"])
        self.assertEqual(self.synth.calls, [])
        (self.dir / "ledger.json").unlink()                                    # 사람이 확인하고 지우면 다시 0부터
        tts.audio("안녕.")
        self.assertEqual(self.ledger()["month_chars"], 3)

    def test_unwritable_ledger_blocks_before_google(self):
        tts = self.service()
        with mock.patch("vasthorizon.tts.atomic_write_text", side_effect=PermissionError("read-only")), \
                self.assertRaises(TtsUnavailableError), self.assertLogs("vasthorizon.tts", "WARNING"):
            tts.audio("안녕.")
        self.assertEqual(self.synth.calls, [])
        self.assertTrue(tts.status()["ledger_ok"])                             # 다음 요청에서 다시 써 본다
        self.assertEqual(tts.audio("안녕."), b"<mp3:3>")

    def test_failed_ledger_add_stops_later_synthesis(self):
        tts = self.service()
        real = __import__("vasthorizon.tts", fromlist=["atomic_write_text"]).atomic_write_text
        writes = []

        def flaky(path, text):                                                 # 합성 전 시험 쓰기는 되고, 합성 뒤 더하기는 실패
            writes.append(text)
            if len(writes) == 2:
                raise OSError("disk full")
            real(path, text)
        with mock.patch("vasthorizon.tts.atomic_write_text", side_effect=flaky), \
                self.assertLogs("vasthorizon.tts", "WARNING"):
            self.assertEqual(tts.audio("안녕."), b"<mp3:3>")                   # 합성한 오디오는 돌려준다
        self.assertFalse(tts.status()["ledger_ok"])
        with self.assertRaises(TtsUnavailableError):
            tts.audio("다른 편지.")
        self.assertEqual(len(self.synth.calls), 1)
        self.assertEqual(tts.audio("안녕."), b"<mp3:3>")                       # 만들어 둔 오디오는 그대로

    def test_google_quota_starts_cooldown(self):
        tts = self.service(synth=FakeSynth(TtsQuotaError("google 429", 600)))
        with self.assertRaises(TtsQuotaError) as ctx, self.assertLogs("vasthorizon.tts", "WARNING"):
            tts.audio("안녕.")
        self.assertEqual(ctx.exception.reason, "cooldown")
        self.assertTrue(tts.cooling())
        self.assertTrue(tts.status()["cooldown"])
        self.synth.error = None
        self.clock[0] += 60
        with self.assertRaises(TtsQuotaError) as ctx:              # 쉬는 동안은 Google을 부르지 않는다
            tts.audio("다른 편지.")
        self.assertEqual(ctx.exception.retry_after, int(COOLDOWN_SECONDS - 60))
        self.assertEqual(len(self.synth.calls), 1)
        self.clock[0] += COOLDOWN_SECONDS
        self.assertFalse(tts.cooling())
        self.assertEqual(tts.audio("다른 편지."), b"<mp3:6>")

    def test_other_error_no_cooldown_and_partial_chars_counted(self):
        text = " ".join(["별빛이 오랫동안 우주를 건너 오늘 밤 너에게 닿았어."] * 300)
        parts = chunks(text)
        tts = self.service(synth=FakeSynth(TtsError("google 500"), fail_at=2))
        with self.assertRaises(TtsError) as ctx, self.assertLogs("vasthorizon.tts", "WARNING"):
            tts.audio(text)
        self.assertNotIsInstance(ctx.exception, TtsQuotaError)
        self.assertFalse(tts.cooling())
        self.assertEqual(self.ledger()["month_chars"], len(parts[0]))   # 합성한 첫 조각은 Google이 센다
        self.assertIsNone(tts.cached(text))                            # 실패한 오디오는 두지 않는다
        tts._synth = FakeSynth(RuntimeError("boom"))
        with self.assertRaises(TtsError), self.assertLogs("vasthorizon.tts", "WARNING"):   # 그 밖의 예외도 TtsError로
            tts.audio("안녕.")

    def test_usage_log_records_tts(self):
        usage = UsageLog(None, now=lambda: self.when[0])
        tts = self.service(usage=usage)
        tts.audio(LETTER)
        today = usage.today()
        self.assertEqual(today.tts_chars, len(chunks(LETTER)[0]))
        self.assertEqual((today.calls, today.cost_usd), (0, 0.0))       # LLM 호출 · 비용에 넣지 않는다
        row = usage.record_tts(10, 0.5, error="TtsError", voice="v")
        self.assertEqual((row["kind"], row["chars"], row["cost_usd"], row["error"]), ("tts", 10, 0.0, "TtsError"))

    def test_concurrent_requests_synthesize_once(self):
        gate = threading.Event()

        class Slow(FakeSynth):
            def __call__(self, text):
                gate.wait(2)
                return super().__call__(text)
        tts = self.service(synth=Slow())
        results = []
        threads = [threading.Thread(target=lambda: results.append(tts.audio(LETTER))) for _ in range(4)]
        for t in threads:
            t.start()
        time.sleep(0.1)
        gate.set()
        for t in threads:
            t.join(5)
        self.assertEqual(len(results), 4)
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(len(self.synth.calls), 1)
        self.assertEqual(tts._key_locks, {})                            # 키 잠금은 다 쓰면 치운다

    def test_sweep_removes_old_audio(self):
        tts = self.service(days=30)
        tts.audio(LETTER)
        path = tts.audio_path(tts.cache_key(LETTER))
        tmp = self.dir / ".x.mp3.abc.tmp"
        tmp.write_bytes(b"")
        other = self.dir / "notes.txt"
        other.write_text("x")
        self.assertEqual(tts.sweep(), 0)
        old = time.time() - 31 * 86400
        os.utime(path, (old, old))
        os.utime(tmp, (old, old))
        self.assertEqual(tts.sweep(), 2)
        self.assertFalse(path.exists())
        self.assertTrue(other.exists() and (self.dir / "ledger.json").exists())

    def test_config(self):
        cfg = get_settings().tts
        self.assertFalse(cfg.enabled)
        self.assertEqual((cfg.voice, cfg.speaking_rate, cfg.days), ("ko-KR-Chirp3-HD-Aoede", 0.95, 30))
        self.assertEqual((cfg.monthly_chars, cfg.daily_chars, cfg.per_ip_per_minute, cfg.timeout), (900000, 60000, 10, 20))
        from vasthorizon import config as config_module
        try:
            with mock.patch.dict(os.environ, {"VH_CONFIG": "config.deploy.toml"}):
                get_settings.cache_clear()
                s = get_settings()
                self.assertTrue(s.tts.enabled)
                self.assertEqual(s.tts.dir, config_module.PROJECT_ROOT / "data" / "deploy" / "tts")
        finally:
            get_settings.cache_clear()

    def test_key_only_from_env(self):
        from vasthorizon import config as config_module
        with mock.patch.dict(os.environ, {"GOOGLE_TTS_API_KEY": "  abc  "}):
            self.assertEqual(config_module.get_tts_key(), "abc")
        with mock.patch.object(config_module, "load_dotenv"), mock.patch.dict(os.environ, {"GOOGLE_TTS_API_KEY": ""}):
            self.assertIsNone(config_module.get_tts_key())
        self.assertNotIn("api_key", {f for f in config_module.TtsConfig.__dataclass_fields__})


if __name__ == "__main__":
    unittest.main()
