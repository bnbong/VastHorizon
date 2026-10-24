// 사운드 엔진의 순수 부분 — 음계 · 패드 파라미터 · 연타 보호 · 설정 파싱. 브라우저 API 없이 돈다.
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import {
  MAX_VOICES, MODES, PAD_MODES, PENTATONIC, SFX_DURATION, THROTTLE_MS,
  dbToGain, midiHz, noteHz, normalizeMode, parseSetting, pentaMidi, pickSparkleStep, serializeSetting,
  shouldThrottle, sound, voicesFull,
} from "../../web/js/sound.js";

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} ≉ ${b}`);

test("음정 — A4 = 440Hz, 근음 D4 ≈ 293.66Hz, 다섯 step마다 한 옥타브", () => {
  close(midiHz(69), 440);
  close(noteHz(0), 293.6647679, 1e-6);
  close(noteHz(5), noteHz(0) * 2);
  close(noteHz(-5), noteHz(0) / 2);
  assert.deepEqual([0, 1, 2, 3, 4].map((s) => pentaMidi(s) - pentaMidi(0)), PENTATONIC);
});

test("음수 step도 펜타토닉 안에 있다 (D E F# A B)", () => {
  const pcs = new Set([2, 4, 6, 9, 11]);           // D E F# A B의 음높이 클래스
  for (let s = -12; s <= 15; s++) assert.ok(pcs.has(pentaMidi(s) % 12), `step ${s}`);
  assert.equal(pentaMidi(-1), 59);                 // B3
  assert.equal(pentaMidi(-3), 54);                 // F#3
});

test("연타 보호 — 100ms 안의 재호출은 무시, 처음 호출과 경계 이후는 통과", () => {
  assert.equal(THROTTLE_MS, 100);
  assert.equal(shouldThrottle(undefined, 5), false);
  assert.equal(shouldThrottle(null, 5), false);
  assert.equal(shouldThrottle(1000, 1050), true);
  assert.equal(shouldThrottle(1000, 1099.9), true);
  assert.equal(shouldThrottle(1000, 1100), false);
  assert.equal(shouldThrottle(1000, 1030, 20), false);
});

test("동시 발음 한도는 6", () => {
  assert.equal(MAX_VOICES, 6);
  assert.equal(voicesFull(5), false);
  assert.equal(voicesFull(6), true);
});

test("설정 파싱 — 기본은 켜짐, \"off\"만 꺼짐, 직렬화는 왕복", () => {
  assert.equal(parseSetting(null), true);
  assert.equal(parseSetting(undefined), true);
  assert.equal(parseSetting("on"), true);
  assert.equal(parseSetting("garbage"), true);
  assert.equal(parseSetting("off"), false);
  assert.equal(parseSetting(" OFF "), false);
  for (const on of [true, false]) assert.equal(parseSetting(serializeSetting(on)), on);
});

test("패드 파라미터 — 세 모드 모두 조용하고 느리며, 모드마다 다르다", () => {
  assert.deepEqual(Object.keys(PAD_MODES).sort(), MODES.filter((m) => m !== "off").sort());
  for (const [name, p] of Object.entries(PAD_MODES)) {
    assert.ok(p.notes.length >= 2 && p.notes.length <= 3, name);
    assert.equal(p.waves.length, p.notes.length, name);
    for (const w of p.waves) assert.ok(["sine", "triangle"].includes(w), name);
    assert.ok(p.level > 0 && p.level <= 0.4, name);
    assert.ok(p.lfoHz > 0 && p.lfoHz <= 0.1, `${name} LFO는 10초보다 느리게`);
    assert.ok(p.lfoDepth < 0.5 && p.delaySend <= 0.5, name);
    assert.ok(p.cutoff - p.filterDepth > 200, `${name} 필터가 너무 닫히지 않게`);
    for (const s of p.notes) assert.ok(noteHz(s, p.rootMidi) < 500, `${name} 패드는 낮은 음`);
  }
  const sig = (p) => JSON.stringify([p.notes, p.cutoff, p.lfoHz]);
  assert.equal(new Set(Object.values(PAD_MODES).map(sig)).size, 3);
  assert.ok(PAD_MODES.prologue.cutoff < PAD_MODES.sky.cutoff && PAD_MODES.sky.cutoff < PAD_MODES.map.cutoff);
});

test("모드 정규화와 기타 값", () => {
  assert.equal(normalizeMode("sky"), "sky");
  assert.equal(normalizeMode("nope"), "off");
  assert.equal(normalizeMode(undefined), "off");
  close(dbToGain(-18), 0.12589254, 1e-6);
  assert.equal(pickSparkleStep(0), 9);
  assert.equal(pickSparkleStep(0.9999), 12);
  assert.equal(pickSparkleStep(1), 12);             // 범위 밖도 안전
  assert.ok(SFX_DURATION.sparkle <= 0.2 && SFX_DURATION.arrive === 2 && SFX_DURATION.collect === 0.8);
});

test("브라우저 API가 없어도 모든 메서드가 조용히 no-op", () => {
  assert.doesNotThrow(() => {
    sound.init();
    sound.unlock();
    sound.ambient("sky");
    sound.collect(); sound.sparkle(); sound.open(); sound.close(); sound.arrive(); sound.tick();
    sound.enabled = false;
    sound.enabled = true;
  });
  assert.equal(sound.enabled, true);
  assert.equal(sound.mode, "sky");
});
