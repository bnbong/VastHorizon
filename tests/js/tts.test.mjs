// 읽어 주기 — 한국어 음성 우선순위 · 문장 나누기
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import { CHUNK_MAX, pickVoice, SPEECH_PITCH, SPEECH_RATE, speakableText, speechChunks, VOICE_HINT, voiceScore } from "../../web/js/tts.js";

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
