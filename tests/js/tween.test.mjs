// 애니메이션 대기열 테스트 — 완료 콜백에서 등록한 다음 애니메이션이 이어지는지 (리뷰 P1).
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import { TweenQueue } from "../../web/js/tween.js";

function run(q, frames, dt = 100) {
  for (let i = 0; i < frames; i++) q.tick(dt);
}

test("완료 콜백에서 등록한 다음 애니메이션이 보존된다", () => {
  const q = new TweenQueue();
  const calls = { first: 0, second: 0, doneSecond: 0 };
  q.add(100, () => calls.first++, () => q.add(100, () => calls.second++, () => calls.doneSecond++));
  q.tick(100);                                     // 첫 애니메이션 끝 → 두 번째 등록
  assert.equal(calls.first, 1);
  assert.equal(q.size, 1);                         // 두 번째가 사라지지 않는다
  q.tick(100);
  assert.deepEqual(calls, { first: 1, second: 1, doneSecond: 1 });
  assert.equal(q.size, 0);
});

test("3단계 연쇄 — 각 단계와 마지막 완료가 한 번씩", () => {
  const q = new TweenQueue();
  const order = [];
  const stage = (name, next) => () => { order.push(name); next?.(); };
  q.add(200, () => {}, stage("A", () => q.add(200, () => {}, stage("B", () => q.add(200, () => {}, stage("C"))))));
  run(q, 10);
  assert.deepEqual(order, ["A", "B", "C"]);
  assert.equal(q.size, 0);
});

test("떠오르기 — 두 이동과 끝 안내가 각각 한 번 (MapMode.journey 와 같은 연쇄)", () => {
  const q = new TweenQueue();
  const counts = { first: 0, onWorld: 0, second: 0, onEdge: 0 };
  const flyTo = (ms, onStep, done) => q.add(ms, onStep, done);
  flyTo(3500, () => counts.first++, () => {
    counts.onWorld++;
    flyTo(4500, () => counts.second++, () => counts.onEdge++);
  });
  run(q, 100, 100);                               // 10초
  assert.equal(counts.onWorld, 1);
  assert.equal(counts.onEdge, 1);
  assert.ok(counts.first >= 35 && counts.second >= 45);
});

test("도중 모드 전환 — 이전 연출은 더 진행되지 않는다", () => {
  const q = new TweenQueue();
  let after = 0, edge = 0;
  q.add(300, () => {}, () => q.add(300, () => after++, () => edge++));
  q.tick(300);
  q.cancelAll();                                   // Stage.setMode
  run(q, 5);
  assert.deepEqual([after, edge], [0, 0]);
});

test("콜백 안에서 취소하면 같은 프레임의 다른 애니메이션도 멈추고, 취소 뒤 등록한 것은 남는다", () => {
  const q = new TweenQueue();
  let other = 0, fresh = 0;
  q.add(100, () => {}, () => { q.cancelAll(); q.add(100, () => fresh++); });
  q.add(500, () => other++);
  q.tick(100);
  assert.equal(other, 0);                          // 취소된 세대
  assert.equal(q.size, 1);
  q.tick(100);
  assert.equal(fresh, 1);
});

test("움직임 줄이기 — 즉시 끝 모습으로, 연쇄도 즉시 완료", () => {
  const q = new TweenQueue();
  const seen = [];
  q.add(3500, (k) => seen.push(k), () => q.add(4500, (k) => seen.push(k), () => seen.push("end"), { instant: true }), { instant: true });
  assert.deepEqual(seen, [1, 1, "end"]);
  assert.equal(q.size, 0);
});
