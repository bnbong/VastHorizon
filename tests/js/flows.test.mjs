// 요청 흐름 테스트 — deferred Promise로 응답 순서를 직접 정한다 (디자인 v2 리뷰 P2).
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import { clearHistoryFlow, requestGate, runLatest } from "../../web/js/flows.js";

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
const tick = () => new Promise((r) => setTimeout(r, 0));

// 서랍 하나의 출력 영역을 흉내 낸다
function panel() {
  const ui = { out: null, busy: false, log: [] };
  const alive = { value: true };
  const run = (gate, d, label) => runLatest(gate, () => alive.value, {
    work: () => d.promise,
    onStart: () => { ui.busy = true; ui.out = `loading:${label}`; },
    onSuccess: (r) => { ui.out = `result:${r}`; ui.log.push(`ok:${r}`); },
    onError: (e) => { ui.out = `error:${e.message}`; ui.log.push(`err:${e.message}`); },
    onSettled: () => { ui.busy = false; },
  });
  return { ui, alive, run };
}

test("first → second 요청, second → first 응답: 최종 결과는 second", async () => {
  const { ui, run } = panel();
  const gate = requestGate();
  const first = deferred(), second = deferred();
  const p1 = run(gate, first, "first");
  const p2 = run(gate, second, "second");
  second.resolve("second");
  await p2;
  assert.equal(ui.out, "result:second");
  first.resolve("first");
  await p1;
  assert.equal(ui.out, "result:second");               // 늦게 온 first 가 덮어쓰지 않는다
  assert.deepEqual(ui.log, ["ok:second"]);
});

test("이전 요청의 실패가 최신 성공 결과를 덮어쓰지 않는다", async () => {
  const { ui, run } = panel();
  const gate = requestGate();
  const first = deferred(), second = deferred();
  const p1 = run(gate, first, "first");
  const p2 = run(gate, second, "second");
  second.resolve("second");
  await p2;
  first.reject(new Error("timeout"));
  await p1;
  assert.equal(ui.out, "result:second");
});

test("먼저 끝난 이전 요청이 새 요청의 로딩 상태를 풀지 않는다", async () => {
  const { ui, run } = panel();
  const gate = requestGate();
  const first = deferred(), second = deferred();
  const p1 = run(gate, first, "first");
  const p2 = run(gate, second, "second");
  first.resolve("first");                              // 이전 요청이 먼저 끝남
  await p1;
  assert.equal(ui.busy, true);                          // 새 요청은 아직 로딩 중
  assert.equal(ui.out, "loading:second");
  second.resolve("second");
  await p2;
  assert.deepEqual([ui.busy, ui.out], [false, "result:second"]);
});

test("서랍을 떠나면 최신 요청이어도 반영하지 않는다 (서랍 세대 보호 유지)", async () => {
  const { ui, alive, run } = panel();
  const gate = requestGate();
  const only = deferred();
  const p = run(gate, only, "only");
  alive.value = false;                                 // 다른 서랍으로
  only.resolve("late");
  await p;
  assert.deepEqual([ui.out, ui.busy], ["loading:only", true]);   // 떠난 서랍은 건드리지 않는다
});

// ── 대화 기록 삭제 ──

function chat({ request, alive = () => true }) {
  const ui = { log: ["질문", "답변"], error: null, busy: false };
  const history = requestGate();
  const clear = clearHistoryFlow({
    request, historyGate: history, alive,
    onBusy: (b) => { ui.busy = b; },
    onCleared: () => { ui.log = []; ui.error = null; },
    onFailed: (e) => { ui.error = `대화 기록을 지우지 못했습니다 — ${e.message}`; },
  });
  return { ui, clear, history };
}

test("DELETE 성공: 화면 기록 제거", async () => {
  const { ui, clear } = chat({ request: async () => null });
  assert.equal(await clear(), true);
  assert.deepEqual(ui.log, []);
});

test("DELETE 실패: 기록 유지 · 오류 표시 · 다시 시도 가능", async () => {
  let fail = true;
  const { ui, clear } = chat({ request: async () => { if (fail) throw new Error("network"); } });
  assert.equal(await clear(), false);
  assert.deepEqual(ui.log, ["질문", "답변"]);
  assert.match(ui.error, /지우지 못했습니다/);
  assert.equal(ui.busy, false);
  fail = false;
  assert.equal(await clear(), true);                   // 재시도
  assert.deepEqual([ui.log, ui.error], [[], null]);
});

test("삭제 요청 중 중복 삭제를 막는다", async () => {
  const d = deferred();
  let calls = 0;
  const { clear } = chat({ request: () => { calls += 1; return d.promise; } });
  const p1 = clear();
  assert.equal(await clear(), false);                  // 진행 중 — 무시
  d.resolve();
  await p1;
  assert.equal(calls, 1);
});

test("삭제 요청 중 서랍을 바꾸면 새 서랍을 건드리지 않는다", async () => {
  const d = deferred();
  const alive = { value: true };
  const { ui, clear } = chat({ request: () => d.promise, alive: () => alive.value });
  const p = clear();
  alive.value = false;
  d.resolve();
  await p;
  assert.deepEqual(ui.log, ["질문", "답변"]);          // 떠난 서랍의 기록 객체도 그대로 (새 서랍은 별개)
});

test("기록 조회 시작 → 삭제 성공 → 이전 조회 응답: 지운 기록이 되살아나지 않는다", async () => {
  const { ui, clear, history } = chat({ request: async () => null });
  const loading = deferred();
  const isLatest = history.start();                    // loadHistory 시작
  const shown = loading.promise.then((turns) => { if (isLatest()) ui.log = turns; });
  await clear();                                       // 삭제가 먼저 끝남 — history 관문 무효
  loading.resolve(["질문", "답변"]);                   // 삭제 전 기록이 늦게 도착
  await shown;
  await tick();
  assert.deepEqual(ui.log, []);
});
