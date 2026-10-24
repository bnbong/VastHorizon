// 서랍 뒤로 가기 스택 — 쌓기 · 꺼내기 · 깊이 제한 · 같은 화면 판단
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import { advance, popView, pushView, sameView, STACK_LIMIT, viewKey } from "../../web/js/drawerstack.js";

const item = (id) => ({ kind: "item", id });

test("쌓기 — 맨 위와 같은 화면은 다시 쌓지 않는다", () => {
  let s = pushView([], item("Q2"));
  s = pushView(s, item("Q2"));
  assert.equal(s.length, 1);
  s = pushView(s, { kind: "letter", body: { item_id: "Q2" } });
  s = pushView(s, item("Q2"));
  assert.deepEqual(s.map((v) => v.kind), ["item", "letter", "item"]);
  const before = [item("Q1")];
  pushView(before, item("Q3"));
  assert.equal(before.length, 1, "원래 배열은 바꾸지 않는다");
});

test("꺼내기 — 맨 위부터, 비어 있으면 null", () => {
  const s = pushView(pushView([], { kind: "catalog", group: "star", q: "베" }), item("Q3"));
  const a = popView(s);
  assert.deepEqual(a.view, item("Q3"));
  const b = popView(a.stack);
  assert.deepEqual(b.view, { kind: "catalog", group: "star", q: "베" });
  assert.deepEqual(b.stack, []);
  assert.deepEqual(popView([]), { stack: [], view: null });
});

test("깊이 제한 — 20개를 넘으면 가장 오래된 화면부터 버린다", () => {
  assert.equal(STACK_LIMIT, 20);
  let s = [];
  for (let i = 0; i < 25; i++) s = pushView(s, item(`Q${i}`));
  assert.equal(s.length, 20);
  assert.equal(s[0].id, "Q5");
  assert.equal(s[19].id, "Q24");
  assert.equal(pushView(s, item("Q99"), 3).length, 3);
});

test("같은 화면 — 필드 순서와 밑줄 필드는 따지지 않는다", () => {
  assert.ok(sameView({ kind: "catalog", q: "", group: "all" }, { group: "all", kind: "catalog", q: "" }));
  assert.ok(sameView({ kind: "item", id: "hip:1", _hint: { mag: 3 } }, item("hip:1")));
  assert.ok(!sameView({ kind: "explore", query: "은하" }, { kind: "explore", query: "별" }));
  assert.equal(viewKey(null), "");
});

test("화면 바꾸기 — 지금 화면을 스택에 올리고, 같은 화면이면 그대로", () => {
  let nav = { stack: [], current: null };
  nav = advance(nav, item("Q2"));
  assert.deepEqual(nav, { stack: [], current: item("Q2") });
  nav = advance(nav, item("Q2"));
  assert.equal(nav.stack.length, 0);
  nav = advance(nav, { kind: "letter", body: { item_id: "Q2" } });
  assert.deepEqual(nav.stack, [item("Q2")]);
  assert.equal(nav.current.kind, "letter");
});
