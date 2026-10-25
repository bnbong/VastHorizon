// 접기 상태 — 복원 · 접고 펴기 · 직렬화
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import { FOLD_KEY, restoreFold, serializeFold, withFold } from "../../web/js/fold.js";

test("저장소 키", () => {
  assert.equal(FOLD_KEY, "vh-fold");
});

test("복원 — 기본은 펼침, 깨진 값은 버린다", () => {
  assert.deepEqual(restoreFold(null), {});
  assert.deepEqual(restoreFold(""), {});
  assert.deepEqual(restoreFold("{깨진"), {});
  assert.deepEqual(restoreFold("[true]"), {});
  assert.deepEqual(restoreFold("42"), {});
  assert.deepEqual(restoreFold('{"first":true,"world":false,"other":true,"x":1}'), { first: true });
  assert.deepEqual(restoreFold('{"first":"true","world":true}'), { world: true });
});

test("접고 펴기 — 새 객체를 돌려주고 알 수 없는 키는 무시", () => {
  const a = {};
  const b = withFold(a, "first", true);
  assert.deepEqual(a, {});
  assert.deepEqual(b, { first: true });
  const c = withFold(b, "world", true);
  assert.deepEqual(c, { first: true, world: true });
  assert.deepEqual(withFold(c, "first", false), { world: true });
  assert.deepEqual(withFold(c, "nope", true), { first: true, world: true });
  assert.deepEqual(withFold(undefined, "world", true), { world: true });
});

test("직렬화 — 다시 읽으면 같은 상태", () => {
  const s = serializeFold({ first: true, world: true });
  assert.deepEqual(JSON.parse(s), { first: true, world: true });
  assert.deepEqual(restoreFold(s), { first: true, world: true });
  assert.equal(serializeFold({ first: false }), "{}");
});
