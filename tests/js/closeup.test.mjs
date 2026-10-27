// 가까이서 본 모습의 크기와 거리 — 지도의 근접 모습 · 카메라 비행이 같은 표 (closeup.js)
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import {
  BH_FILL, FILL, HD_COOLDOWN, HD_INTERVAL, HD_LIMIT, HD_RANGE, HdSwap, NEAR, SIZE, STAR_FILL, bhFade, bhViewDistance, closeupFill, closeupNear, closeupSize, hasCloseup, insetFrame, viewDistance,
} from "../../web/js/closeup.js";

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} ≈ ${b}`);
const tan = (fov) => Math.tan((fov * Math.PI) / 360);
// 거리 d에서 크기 size가 화면(세로 h px, 화각 fov)에 차지하는 화소
const px = (size, d, fov, h) => (size / d) * (h / (2 * tan(fov)));

const M31 = { group: "messier", placement: "sky", kind: "나선 은하", code: "M31" };
const M42 = { group: "messier", placement: "sky", kind: "발광 성운", code: "M42" };
const VEGA = { group: "star", placement: "sky" };

test("근접 모습이 있는 천체 — 하늘에 놓인 별 · 메시에만", () => {
  assert.ok(hasCloseup(M31) && hasCloseup(VEGA));
  assert.ok(!hasCloseup({ group: "solar_system", placement: "sky" }));
  assert.ok(!hasCloseup({ group: "star", placement: "illustrative" }));
  assert.ok(!hasCloseup(null));
});

test("크기 · 나타나는 거리 — 사진 은하 5 · 사진 기타 3.5 · 별 1.5 · 사진 없는 성단/성운 3.2", () => {
  assert.equal(closeupSize(M31, true), SIZE.photo);
  assert.equal(closeupSize({ ...M31, kind: "LINER형 은하핵" }, true), SIZE.photo);
  close(closeupSize(M42, true), 3.5);
  assert.equal(closeupSize(M42, false), SIZE.cluster);
  assert.equal(closeupSize(VEGA), SIZE.star);
  assert.equal(closeupSize({ group: "human_made", placement: "sky" }), null);
  assert.deepEqual([closeupNear(VEGA), closeupNear(M31, true), closeupNear(M42, false)], [NEAR.star, NEAR.photo, NEAR.deep]);
});

test("줌 거리 — 가로 화면은 높이의 45%, 세로 화면은 폭의 45%", () => {
  const d = viewDistance(5, 55, 1440 / 900);
  close(px(5, d, 55, 900), 900 * FILL);
  close(d, 5 / (2 * tan(55) * 0.45));
  const aspect = 390 / 844, dp = viewDistance(5, 55, aspect);
  close(px(5, dp, 55, 844) / 390, FILL);           // 세로 화면 — 폭 390px 기준
  assert.ok(dp > d);
  close(viewDistance(5, 55, 1, 0.9) * 2, viewDistance(5, 55, 1, 0.45));
});

test("줌 거리에서 근접 모습은 완전히 또렷하다 (details.js 페이드: near − d ≥ near × 0.4)", () => {
  for (const aspect of [1440 / 900, 390 / 844]) {
    for (const [p, photo] of [[M31, true], [M42, true], [M42, false], [VEGA, false]]) {
      const d = viewDistance(closeupSize(p, photo), 55, aspect, closeupFill(p)), near = closeupNear(p, photo);
      assert.ok(near - d >= near * 0.4, `${p.code ?? "별"} ${aspect.toFixed(2)}: d=${d.toFixed(1)}, near=${near}`);
    }
  }
});

test("별은 별 전용 채움 비율 — 원반(사각형의 30%)이 짧은 변의 4분의 1 남짓", () => {
  assert.equal(closeupFill(VEGA), STAR_FILL);
  assert.equal(closeupFill(M31), FILL);
  assert.ok(STAR_FILL * 0.3 >= 0.25 && STAR_FILL <= 1);
  const d = viewDistance(SIZE.star, 55, 390 / 844, closeupFill(VEGA));
  close(px(SIZE.star, d, 55, 844) * 0.3 / 390, STAR_FILL * 0.3);
});

test("비킨 시야 — 남은 영역의 짧은 변 기준, 서랍 · 시트가 없으면 그대로", () => {
  assert.deepEqual(insetFrame({ width: 1440, height: 900, fov: 55 }), { fov: 55, aspect: 1440 / 900 });
  // 휴대폰 시트(아래 300px): 가상 높이 1144에 화각을 맞추고 남은 영역 390 × 544의 가운데
  const f = insetFrame({ width: 390, height: 844, fov: 55, insetY: 300 });
  close(f.aspect, 390 / 544);
  const d = viewDistance(5, f.fov, f.aspect);
  close(px(5, d, 55, 844 + 300) / 390, FILL);
  // 데스크톱 서랍(오른쪽 452px): 배율은 그대로, 남은 영역 988 × 900
  const g = insetFrame({ width: 1440, height: 900, fov: 55, insetX: 452 });
  close(g.fov, 55);
  close(g.aspect, 988 / 900);
  // 화면보다 큰 비킴은 걸지 않는다 (scene.js applyInset과 같은 조건)
  assert.deepEqual(insetFrame({ width: 300, height: 600, fov: 55, insetX: 400 }), { fov: 55, aspect: 0.5 });
});

test("블랙홀 — 줌 거리에서는 0, 더 들어간 블랙홀 거리에서는 1, 그 사이는 단조롭게", () => {
  for (const frame of [{ fov: 55, aspect: 1.6 }, { fov: 55, aspect: 390 / 844 }]) {
    const g = viewDistance(SIZE.photo, frame.fov, frame.aspect), b = bhViewDistance(frame, g);
    assert.ok(b < g * 0.61);
    close(b, Math.min(viewDistance(SIZE.bh, frame.fov, frame.aspect, BH_FILL), g * 0.6));
    assert.equal(bhFade(g, g, b), 0);
    assert.equal(bhFade(g * 2, g, b), 0);
    assert.equal(bhFade(b, g, b), 1);
    let last = 0;
    for (let d = g; d >= b; d -= (g - b) / 20) {
      const f = bhFade(d, g, b);
      assert.ok(f >= last - 1e-12 && f >= 0 && f <= 1);
      last = f;
    }
  }
  assert.ok(HD_RANGE >= 1.5);
});

test("데스크톱 서랍(1440×900, 시야를 552px 비킴) — 남은 888×900의 짧은 변(888) 기준, 배율은 그대로", () => {
  const f = insetFrame({ width: 1440, height: 900, fov: 55, insetX: 552 });
  assert.equal(f.fov, 55);
  close(f.aspect, 888 / 900);
  const d = viewDistance(SIZE.photo, f.fov, f.aspect);
  close(px(SIZE.photo, d, 55, 900), 888 * FILL);
  close(d, 10.82, 0.01);                                         // Playwright 실측(rs/zoom.mjs)과 같은 거리
  const s = viewDistance(SIZE.star, f.fov, f.aspect, STAR_FILL);
  close(px(SIZE.star, s, 55, 900), 888 * STAR_FILL);
});

// 가짜 로더 — 요청을 모아 두고 시험이 ok/fail을 부른다. 판정 간격 · 쿨다운은 기본값(HD_INTERVAL · HD_COOLDOWN)
function fakeSwap(limit = 2) {
  const log = [], pending = new Map();
  const swap = new HdSwap({
    limit,
    load: (it, ok, fail) => { log.push(`load ${it.code}`); pending.set(it.code, { ok, fail }); },
    apply: (it, tex) => { it.map = tex; log.push(`apply ${it.code}`); },
    revert: (it) => { it.map = `${it.code}-512`; log.push(`revert ${it.code}`); },
    discard: (tex) => log.push(`discard ${tex}`),
  });
  // 시계 — 부를 때마다 판정 간격만큼 흐른다
  let now = 0;
  const tick = (want, opts) => { now += HD_INTERVAL; swap.tick(now, want, opts); };
  const wait = (ms) => { now += ms; };
  return { swap, log, pending, tick, wait };
}
const galaxies = (...codes) => codes.map((code) => ({ code, map: `${code}-512` }));

test("고해상도 교체 — 받기 전에는 512, 받으면 바꾸고, 실패하면 512 그대로 다시 요청하지 않는다", () => {
  const { log, pending, tick } = fakeSwap();
  const [a, b] = galaxies("M31", "M87");
  tick([a]);
  tick([a]);                                                      // 받는 중에는 다시 요청하지 않는다
  assert.equal(a.hd, "loading");
  assert.equal(a.map, "M31-512");
  pending.get("M31").ok("M31-hd");
  assert.deepEqual([a.hd, a.map], ["loaded", "M31-hd"]);
  tick([a, b]);
  pending.get("M87").fail();
  assert.deepEqual([b.hd, b.map], ["failed", "M87-512"]);
  tick([a, b]);
  assert.deepEqual(log, ["load M31", "apply M31", "load M87"]);
  pending.get("M87").ok("late");                                  // 실패로 정한 뒤 늦게 온 텍스처는 버린다
  assert.equal(b.map, "M87-512");
  assert.ok(log.includes("discard late"));
  assert.ok(HD_LIMIT >= 2);
});

test("고해상도 교체 — 판정은 HD_INTERVAL마다, 요청은 한 번에 한 건 (받은 뒤 다음)", () => {
  const { swap, log, pending, tick } = fakeSwap(8);
  const [a, b, c] = galaxies("M31", "M32", "M110");
  swap.tick(0, [a, b, c]);
  pending.get("M31").ok("M31-hd");
  swap.tick(HD_INTERVAL - 1, [a, b, c]);                          // 간격이 차지 않았다 — b를 아직 요청하지 않는다
  assert.deepEqual(log, ["load M31", "apply M31"]);
  swap.tick(HD_INTERVAL, [a, b, c]);
  assert.deepEqual(log, ["load M31", "apply M31", "load M32"]);
  tick([a, b, c]); tick([a, b, c]);
  assert.deepEqual(log, ["load M31", "apply M31", "load M32"]);   // b를 받는 중 — 다음 요청은 기다린다
  pending.get("M32").ok("M32-hd");
  tick([a, b, c]);
  assert.deepEqual(log, ["load M31", "apply M31", "load M32", "apply M32", "load M110"]);
});

test("고해상도 교체 — 상한이 차면 새로 받지 않고, 자리는 절두체 밖 · 범위 밖(keep 아님)인 것 중 가장 오래 안 쓴 것만 비운다", () => {
  const { log, pending, tick } = fakeSwap(2);
  const [a, b, c] = galaxies("M31", "M32", "M110");
  for (const it of [a, b]) { tick([it]); pending.get(it.code).ok(`${it.code}-hd`); }
  tick([a, b, c], { keep: () => true });                          // 둘 다 화면 안 — c는 512 그대로
  assert.equal(c.hd, undefined);
  assert.ok(!log.includes("load M110"));
  tick([a, c], { keep: (it) => it !== b });                       // b가 화면 밖 · 범위 밖으로 — b를 비우고 c를 받는다
  assert.deepEqual([b.map, b.hd], ["M32-512", null]);
  pending.get("M110").ok("M110-hd");
  assert.deepEqual([a.map, b.map, c.map], ["M31-hd", "M32-512", "M110-hd"]);
  assert.ok(log.includes("revert M32") && !log.includes("revert M31"));
});

test("고해상도 교체 — 상한을 넘는 후보가 여럿이어도 되돌림 → 재요청을 되풀이하지 않는다 (처녀자리 은하단)", () => {
  const limit = 8, { log, pending, tick } = fakeSwap(limit);
  const virgo = galaxies("M87", "M84", "M86", "M89", "M90", "M88", "M91", "M58", "M59", "M60", "M49", "M61", "M85", "M98", "M99", "M100");
  for (let i = 0; i < 400; i++) {                                 // 100초 — 16개가 모두 화면 안 · 범위 안
    tick(virgo, { keep: () => true, selected: virgo[0] });
    for (const [code, { ok }] of pending) { pending.delete(code); ok(`${code}-hd`); }
  }
  assert.equal(log.filter((l) => l.startsWith("load")).length, limit);
  assert.equal(log.filter((l) => l.startsWith("revert")).length, 0);
  assert.deepEqual(virgo.slice(0, limit).map((it) => it.hd), Array(limit).fill("loaded"));   // 우선순위 순 앞의 8개
  assert.ok(virgo.slice(limit).every((it) => !it.hd && it.map === `${it.code}-512`));
  // 일부가 화면 밖으로 나가도 나머지 후보가 화면 안에 남아 있으면, 비운 자리는 한 번씩만 채우고 다시 비우지 않는다
  const out = new Set(virgo.slice(0, 3));
  for (let i = 0; i < 400; i++) {
    tick(virgo.filter((it) => !out.has(it)), { keep: (it) => !out.has(it) });
    for (const [code, { ok }] of pending) { pending.delete(code); ok(`${code}-hd`); }
  }
  assert.equal(log.filter((l) => l.startsWith("revert")).length, 3);
  assert.equal(log.filter((l) => l.startsWith("load")).length, limit + 3);
});

test("고해상도 교체 — 되돌린 것은 쿨다운 동안 다시 요청하지 않는다", () => {
  const { log, pending, tick, wait } = fakeSwap(1);
  const [a, b] = galaxies("M31", "M32");
  tick([a]); pending.get("M31").ok("M31-hd");
  tick([b], { keep: (it) => it === b });                          // a가 화면 밖 — a를 비우고 b를 받는다
  pending.get("M32").ok("M32-hd");
  assert.equal(a.hd, null);
  tick([a], { keep: (it) => it === a });                          // a가 곧바로 다시 화면 안 — b는 keep 아님이지만 a는 쿨다운
  assert.equal(log.filter((l) => l === "load M31").length, 1);
  assert.equal(b.hd, "loaded");
  wait(HD_COOLDOWN);
  tick([a], { keep: (it) => it === a });                          // 쿨다운이 지나면 다시 받는다
  assert.equal(log.filter((l) => l === "load M31").length, 2);
  assert.ok(HD_COOLDOWN >= 5000);
});

test("고해상도 교체 — 고른 천체가 먼저, 자리가 없으면 화면 안의 것을 비워서라도 받는다 (쿨다운도 넘는다)", () => {
  const { log, pending, tick } = fakeSwap(2);
  const [a, b, sel] = galaxies("M84", "M86", "M87");
  for (const it of [a, b]) { tick([it]); pending.get(it.code).ok(`${it.code}-hd`); }
  tick([sel, a, b], { keep: () => true, selected: sel });         // 모두 화면 안 — 우선순위가 가장 낮은 b를 비운다
  assert.equal(sel.hd, "loading");
  assert.deepEqual([a.hd, b.hd], ["loaded", null]);
  pending.get("M87").ok("M87-hd");
  for (let i = 0; i < 100; i++) tick([sel, a, b], { keep: () => true, selected: sel });   // 비운 b가 고른 천체를 밀어내지 않는다
  assert.deepEqual([sel.hd, a.hd, b.hd], ["loaded", "loaded", null]);
  assert.equal(log.filter((l) => l.startsWith("load")).length, 3);
  // 우선순위 — 후보 여럿 중 고른 천체를 먼저 요청한다
  const f = fakeSwap(8), [x, y, s2] = galaxies("M58", "M59", "M60");
  f.tick([s2, x, y], { selected: s2 });
  assert.deepEqual(f.log, ["load M60"]);
  // 쿨다운 중이어도 고른 천체는 받는다
  const g = fakeSwap(1), [p, q] = galaxies("M98", "M99");
  g.tick([p]); g.pending.get("M98").ok("M98-hd");
  g.tick([q]); g.pending.get("M99").ok("M99-hd");                 // p를 비웠다 (쿨다운)
  g.tick([p, q], { keep: () => true, selected: p });
  assert.equal(p.hd, "loading");
});
