// 프롤로그 — 사실을 말하는 장면은 모두 출처가 있고, 글자 나누기가 낱말을 깨지 않는다
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import { BEATS, splitGlyphs } from "../../web/js/prologue.js";

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
