// 읽어 주기 — 한국어 음성 우선순위 · 문장 나누기 · 서버 음성(Google TTS)에서 기기 음성으로 넘어가는 판정
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import { AUDIO_CACHE_MAX, CHUNK_MAX, pickVoice, QUOTA_NOTE, QUOTA_NOTES, quotaNote, serverPause, shouldFallback, silentWav, SPEECH_PITCH, SPEECH_RATE, speakableText,
         speechChunks, VOICE_HINT, voiceScore } from "../../web/js/tts.js";

const v = (name, lang = "ko-KR", localService = true) => ({ name, lang, localService });

test("한국어 음성이 없으면 null", () => {
  assert.equal(pickVoice([]), null);
  assert.equal(pickVoice(undefined), null);
  assert.equal(pickVoice([v("Samantha", "en-US"), v("Kyoko", "ja-JP")]), null);
  assert.equal(voiceScore(v("Yuna", "en-US")), -1);
});

test("우선순위 — Yuna > Sora > Google 한국의 > Microsoft SunHi · Heami > 그 밖의 한국어", () => {
  const other = v("Korean Voice");
  const ms = v("Microsoft Heami - Korean (Korean)");
  const google = v("Google 한국의", "ko-KR", false);
  const sora = v("Sora");
  const yuna = v("Yuna");
  const order = [other, ms, google, sora, yuna];
  for (let i = 0; i < order.length; i += 1) {
    assert.equal(pickVoice(order.slice(0, i + 1)), order[i], order[i].name);
    assert.equal(pickVoice(order.slice(0, i + 1).reverse()), order[i], `${order[i].name} (거꾸로)`);
  }
  assert.equal(pickVoice([v("Samantha", "en-US"), v("Microsoft SunHi Online (Natural) - Korean (Korea)", "ko-KR", false), ms]).name,
               "Microsoft SunHi Online (Natural) - Korean (Korea)");
});

test("Yuna — 프리미엄 > 향상됨 > 기본, 기기 안 음성(localService)이 앞", () => {
  const plain = v("Yuna");
  const enhanced = v("Yuna (Enhanced)");
  const premium = v("Yuna (Premium)");
  const remote = v("Yuna", "ko-KR", false);
  assert.equal(pickVoice([remote, plain]), plain);
  assert.equal(pickVoice([plain, enhanced]), enhanced);
  assert.equal(pickVoice([enhanced, premium, plain]), premium);
  assert.equal(pickVoice([v("Yuna (향상됨)"), plain]).name, "Yuna (향상됨)");
  assert.equal(pickVoice([v("Google 한국의", "ko-KR", false), remote]), remote);    // 원격 Yuna도 Google보다 앞
});

test("lang 표기 — ko-KR · ko_KR · ko", () => {
  for (const lang of ["ko-KR", "ko_KR", "ko", "KO-kr"]) assert.equal(pickVoice([v("x", lang)])?.lang, lang);
  assert.equal(pickVoice([v("x", "kok-IN")]), null);
});

test("발화 — 숫자 사이 천 단위 쉼표는 지운다", () => {
  assert.equal(speakableText("3,780만 년"), "3780만 년");
  assert.equal(speakableText("1,234,567"), "1234567");
  assert.equal(speakableText("299,792.458"), "299792.458");
  assert.equal(speakableText("3，780만"), "3780만");
  assert.equal(speakableText("1,2는 그대로"), "1,2는 그대로");
  assert.equal(speakableText("1,2345"), "1,2345");
  assert.deepEqual(speechChunks("3,780만 년 전, 빛이 출발했어."), ["3780만 년 전, 빛이 출발했어."]);
  assert.deepEqual(speechChunks("3,780만 년 전, 빛이 출발했어.", 8), ["3780만 년 전,", "빛이 출발했어."]);   // 긴 문장은 문장 쉼표에서만 나뉜다
});

test("발화 — [근거 N] · ** 를 걷어 내고 문장 단위로", () => {
  assert.equal(speakableText("**베가**의 빛이 [근거 1, 2] 출발했어."), "베가의 빛이 출발했어.");
  assert.deepEqual(speechChunks("안녕, 지구의 친구야. 나는 **베가**야 [근거 1]. 내 빛은 25년 전에 출발했어!\n\n잘 지내?  고마워"),
                   ["안녕, 지구의 친구야.", "나는 베가야.", "내 빛은 25년 전에 출발했어!", "잘 지내?", "고마워"]);
  assert.deepEqual(speechChunks(""), []);
  assert.deepEqual(speechChunks(" [근거 3] . "), []);                        // 글자 없는 조각은 버린다
});

test("너무 긴 문장은 쉼표에서 나누고, 어절은 자르지 않는다", () => {
  const clause = "아주 먼 별에서 출발한 빛이 오랫동안 우주를 건너";
  const long = `${Array(8).fill(clause).join(", ")}.`;
  const chunks = speechChunks(long);
  assert.ok(chunks.length > 1, chunks.length);
  for (const c of chunks) assert.ok(c.length <= CHUNK_MAX, c.length);
  assert.equal(chunks.join(" "), long);
});

test("말하기 속도 · 높이 · 음성 안내", () => {
  assert.equal(SPEECH_RATE, 0.92);
  assert.equal(SPEECH_PITCH, 0.95);
  assert.match(VOICE_HINT, /Yuna/);
  assert.match(VOICE_HINT, /손쉬운 사용/);
});

test("서버 음성 — 성공(2xx)만 그대로, 나머지는 기기 음성으로", () => {
  assert.equal(shouldFallback(200), false);
  assert.equal(shouldFallback(200, ""), false);
  assert.equal(shouldFallback(206, undefined), false);
  for (const [status, code] of [[503, "tts_unavailable"], [503, "tts_quota"], [502, "tts_failed"], [429, "rate_limited"],
                                [404, "share_not_found"], [0, ""], [0, undefined], [500, "internal"], [undefined, undefined]]) {
    assert.equal(shouldFallback(status, code), true, `${status} ${code}`);
  }
  assert.equal(shouldFallback(200, "tts_failed"), true);                 // 오류 코드가 있으면 성공 상태여도
});

test("서버 음성을 쉬는 시간 — 쓸 수 없음은 끝까지, 한도는 Retry-After만큼, 그 밖에는 바로 다시", () => {
  assert.equal(serverPause(503, "tts_unavailable"), Infinity);
  assert.equal(serverPause(503, "tts_quota", "120"), 120_000);
  assert.equal(serverPause(503, "tts_quota", null), 600_000);
  assert.equal(serverPause(503, "tts_quota", "abc"), 600_000);
  for (const [status, code] of [[502, "tts_failed"], [429, "rate_limited"], [0, ""], [404, "share_not_found"]]) {
    assert.equal(serverPause(status, code, "60"), 0, `${status} ${code}`);
  }
  assert.match(QUOTA_NOTE, /기기 음성/);
  assert.equal(AUDIO_CACHE_MAX, 8);
});

test("무음 WAV — RIFF 머리와 무음 표본", () => {
  const wav = silentWav(80);
  assert.equal(wav.length, 44 + 80);
  assert.equal(String.fromCharCode(...wav.slice(0, 4)), "RIFF");
  assert.equal(String.fromCharCode(...wav.slice(8, 12)), "WAVE");
  assert.equal(String.fromCharCode(...wav.slice(36, 40)), "data");
  const view = new DataView(wav.buffer);
  assert.equal(view.getUint32(4, true), 36 + 80);
  assert.equal(view.getUint32(24, true), 8000);
  assert.equal(view.getUint32(40, true), 80);
  assert.ok(wav.slice(44).every((b) => b === 128));
});

test("한도 안내 — 서버 message를 그대로, 없으면 reason별 문구, 그것도 없으면 이달 한도 문구", () => {
  assert.equal(quotaNote("day", "오늘 읽어 주기 한도를 다 썼어요 — 기기 음성으로 읽어 드립니다"),
               "오늘 읽어 주기 한도를 다 썼어요 — 기기 음성으로 읽어 드립니다");
  assert.equal(quotaNote("month", ""), QUOTA_NOTES.month);
  assert.equal(quotaNote("month", "  "), QUOTA_NOTE);
  assert.match(quotaNote("day"), /오늘/);
  assert.match(quotaNote("cooldown", null), /잠시 쉬고/);
  assert.equal(quotaNote("unknown"), QUOTA_NOTE);
  assert.equal(quotaNote(undefined, undefined), QUOTA_NOTE);
  for (const note of Object.values(QUOTA_NOTES)) assert.match(note, /기기 음성/);
});
