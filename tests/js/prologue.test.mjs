// 프롤로그 — 사실을 말하는 장면은 모두 출처가 있고, 글자 나누기가 낱말을 깨지 않는다
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import { acceptsRequest, BEATS, createScope, decideStep, FINAL_GUARD_MS, keyAction, lemniscate, splitGlyphs } from "../../web/js/prologue.js";

test("사실을 말하는 장면은 모두 출처가 있다 (위로를 지어내지 않는다)", () => {
  for (const b of BEATS) {
    if (!b.fact) continue;
    assert.ok(b.sources?.length, b.lines.join(" "));
    for (const s of b.sources) assert.ok(s.label && (!s.url || s.url.startsWith("https://")), s.label);
  }
  assert.ok(BEATS.at(-1).final);
  assert.equal(BEATS.filter((b) => b.fact).length, 6);
});

test("양자 장면은 과장하지 않는다 — 숨은 변수와 벨 부등식, 노벨상 출처", () => {
  const q = BEATS.find((b) => b.fx === "cloud");
  assert.match(q.fact, /숨은 변수/);
  assert.match(q.fact, /벨 부등식/);
  assert.doesNotMatch(q.fact, /의식|마음이 만든/);
  assert.ok(q.sources.some((s) => s.url.includes("nobelprize.org/prizes/physics/2022")));
});

test("글자 나누기 — 글자마다 지연, 낱말은 한 덩어리 (줄은 낱말 사이에서만)", () => {
  const html = splitGlyphs(["약 465억 광년."], 10);
  assert.equal((html.match(/class="pl-g"/g) || []).length, 8);           // 약 · 465억 · 광년. = 1 + 4 + 3
  assert.equal((html.match(/class="pl-w"/g) || []).length, 3);
  assert.match(html, /--d:70ms/);                                      // 마지막 글자 (8번째)
  assert.match(splitGlyphs(["<b>"]), /&lt;/);
});

test("다음 장면 결정 — 다음 · 자동 · 점 · 건너뛰기, 마지막 장면은 막 들어온 연타로 끝나지 않는다", () => {
  const n = BEATS.length, last = n - 1;
  assert.deepEqual(decideStep(0, "next"), { type: "show", index: 1 });
  assert.deepEqual(decideStep(-1, "next"), { type: "show", index: 0 });
  assert.deepEqual(decideStep(3, "auto"), { type: "show", index: 4 });
  assert.deepEqual(decideStep(2, { goto: 5 }), { type: "show", index: 5 });
  assert.deepEqual(decideStep(5, { goto: 5 }), { type: "none" });                // 지금 장면을 다시 그리지 않는다
  assert.deepEqual(decideStep(0, { goto: 99 }), { type: "show", index: last });   // 범위 밖은 끝으로 묶는다
  assert.deepEqual(decideStep(4, "skip"), { type: "finish" });
  assert.deepEqual(decideStep(last, "next", { sinceShown: 200 }), { type: "none" });
  assert.deepEqual(decideStep(last, "next", { sinceShown: FINAL_GUARD_MS }), { type: "finish" });
  assert.deepEqual(decideStep(0, "아무거나"), { type: "none" });
  // 연타 열 번 — 정해 둔 장면에서 이어 세면 마지막 장면에 멈춘다 (시작하기를 건너뛰지 않는다)
  let at = 0;
  for (let k = 0; k < 10; k++) {
    const step = decideStep(at, "next", { sinceShown: 0 });
    assert.notEqual(step.type, "finish");
    if (step.type === "show") at = step.index;
  }
  assert.equal(at, last);
});

test("자동 넘김은 아직 그리지 않은 요청이 있으면 받지 않는다 — 다음 · 점 · 건너뛰기는 그대로", () => {
  assert.equal(acceptsRequest("auto", null), true);
  assert.equal(acceptsRequest("auto", undefined), true);
  assert.equal(acceptsRequest("auto", 3), false);
  assert.equal(acceptsRequest("auto", 0), false);                   // 0번 장면도 정해 둔 요청이다
  assert.equal(acceptsRequest("next", 3), true);
  assert.equal(acceptsRequest("skip", 3), true);
  assert.equal(acceptsRequest({ goto: 2 }, 3), true);
});

test("키 — 초점이 버튼 · 링크 안이면 Esc만, 아니면 스페이스 · Enter · →가 다음", () => {
  for (const key of [" ", "Enter", "ArrowRight"]) {
    assert.equal(keyAction(key), "next", key);
    assert.equal(keyAction(key, { inControl: true }), null, key);   // .pl-sound · .pl-skip · .pl-start — 그 버튼만 눌린다
  }
  assert.equal(keyAction("Escape"), "skip");
  assert.equal(keyAction("Escape", { inControl: true }), "skip");
  assert.equal(keyAction("a"), null);
  assert.equal(keyAction("ArrowLeft"), null);
});

// 가짜 타이머 — 걸린 것과 지워진 것을 센다
function fakeTimers() {
  let next = 1;
  const t = { timeouts: new Map(), frames: new Map(), cleared: 0, canceled: 0 };
  t.setTimeout = (fn) => { const id = next++; t.timeouts.set(id, fn); return id; };
  t.clearTimeout = (id) => { if (t.timeouts.delete(id)) t.cleared++; };
  t.requestAnimationFrame = (fn) => { const id = next++; t.frames.set(id, fn); return id; };
  t.cancelAnimationFrame = (id) => { if (t.frames.delete(id)) t.canceled++; };
  t.flush = () => {
    const all = [...t.timeouts.values(), ...t.frames.values()];
    t.timeouts.clear(); t.frames.clear();
    all.forEach((fn) => fn(0));
  };
  return t;
}

test("취소 토큰 — 장면을 넘기면 그 장면의 타이머 · 프레임 · 리스너가 모두 거둬진다", () => {
  const timers = fakeTimers();
  const scope = createScope(timers);
  const calls = [];
  scope.timeout(() => calls.push("auto"), 6000);
  scope.frame(() => calls.push("counter"));
  const target = { on: 0, off: 0, addEventListener() { this.on++; }, removeEventListener() { this.off++; } };
  scope.listen(target, "click", () => calls.push("click"));
  assert.equal(scope.alive, true);
  scope.cancel();
  assert.equal(scope.alive, false);
  assert.equal(timers.cleared, 1);
  assert.equal(timers.canceled, 1);
  assert.equal(target.off, 1);
  // 취소 뒤에는 새로 걸리지 않고, 이미 떠난 콜백이 늦게 와도 불리지 않는다
  assert.equal(scope.timeout(() => calls.push("late"), 10), 0);
  scope.cancel();                                                        // 두 번 취소해도 괜찮다
  timers.flush();
  assert.deepEqual(calls, []);
});

test("취소 토큰 — 살아 있는 동안은 제때 불리고, 불린 것은 목록에서 빠진다", () => {
  const timers = fakeTimers();
  const scope = createScope(timers);
  const calls = [];
  scope.timeout(() => calls.push("a"), 10);
  scope.frame((now) => calls.push(`f${now}`));
  timers.flush();
  assert.deepEqual(calls, ["a", "f0"]);
  scope.cancel();
  assert.equal(timers.cleared + timers.canceled, 0);                     // 이미 불린 것은 지울 것이 없다
});

test("무한 기호 — 렘니스케이트 x = cos t/(1+sin²t), y = sin t cos t/(1+sin²t)", () => {
  const near = (a, b) => Math.abs(a - b) < 1e-12;
  const [x0, y0] = lemniscate(0);
  assert.ok(near(x0, 1) && near(y0, 0));
  const [x1, y1] = lemniscate(Math.PI / 2);
  assert.ok(near(x1, 0) && near(y1, 0));                                 // 가운데에서 교차한다
  const [x2] = lemniscate(Math.PI);
  assert.ok(near(x2, -1));
  for (let k = 0; k < 64; k++) {                                         // 2π마다 되풀이, 높이는 ±0.36 안
    const t = (k / 64) * Math.PI * 2, [a, b] = lemniscate(t), [c, d] = lemniscate(t + Math.PI * 2);
    assert.ok(near(a, c) && near(b, d));
    assert.ok(Math.abs(b) <= 0.36 && Math.abs(a) <= 1);
  }
});

test("구 장면에서 지구를 담는다 — 지구 장면은 하나, 관측 가능한 우주의 구", () => {
  const earth = BEATS.filter((b) => b.earth);
  assert.equal(earth.length, 1);
  assert.equal(earth[0].fx, "sphere");
  assert.match(earth[0].lines.join(" "), /바라보는 당신/);
});
