// 휴대폰 아래 시트 — 배치 분류 · 걸림 높이 · 다음 걸림 높이 · 끌기 보조 · 3D 해상도 · 시야 맞춤
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import { bodyPixelRatio, classifyLayout, defaultSnap, fitBodyView, nextSnap, peekOpacity, rubberBand, SHEET_QUERY, SNAPS,
         snapHeights, SPLIT_QUERY, stepSnap, velocityOf } from "../../web/js/sheet.js";

const SN = { peek: 230, half: 464, full: 772 };

test("배치 분류 — 시트 판정이 먼저", () => {
  assert.equal(classifyLayout({ sheet: true, split: false }), "sheet");
  assert.equal(classifyLayout({ sheet: true, split: true }), "sheet");
  assert.equal(classifyLayout({ sheet: false, split: true }), "split");
  assert.equal(classifyLayout({ sheet: false, split: false }), "desktop");
  assert.equal(SHEET_QUERY, "(max-width: 650px)");                 // style.css의 휴대폰 미디어 쿼리와 같은 기준
  assert.match(SPLIT_QUERY, /min-width: 651px/);
  assert.deepEqual(SNAPS, ["peek", "half", "full"]);
});

test("걸림 높이 — 390×844", () => {
  const s = snapHeights({ H: 844 });
  assert.equal(s.full, 772);
  assert.equal(s.half, 464);
  assert.equal(s.peek, 253);                                         // 엿보기 머리글을 못 재면 30%
  assert.deepEqual(snapHeights({ H: 844, peekContent: 210, safeBottom: 20 }), { peek: 230, half: 464, full: 772 });
});

test("걸림 높이 — 범위 자르기 · 알림 띠", () => {
  assert.equal(snapHeights({ H: 844, peekContent: 40 }).peek, 132);   // 최소 132
  assert.equal(snapHeights({ H: 844, peekContent: 600 }).peek, 354);  // 최대 42%
  assert.equal(snapHeights({ H: 844, noticeH: 60 }).full, 712);       // 알림 띠만큼 낮게
  assert.equal(snapHeights({ H: 844, noticeH: 400 }).full, 506);      // 최소 60%
  assert.equal(snapHeights({ H: 2000 }).full, 1880);                  // 최대 94%
  const s = snapHeights({ H: 844, peekContent: 340 });                // half는 peek과 80 이상 떨어진다
  assert.ok(s.half - s.peek >= 80 && s.full - s.half >= 80);
});

test("걸림 높이 — 낮은 화면(눕힌 작은 휴대폰)은 half 없이", () => {
  const s = snapHeights({ H: 320 });
  assert.equal(s.half, null);
  assert.ok(s.peek < s.full);
  assert.equal(s.full, 248);
});

test("기본 걸림 높이 — 3D가 있으면 peek, 그 밖은 half", () => {
  assert.equal(defaultSnap({ kind: "item", has3d: true }), "peek");
  assert.equal(defaultSnap({ kind: "item", has3d: false }), "half");
  assert.equal(defaultSnap({ kind: "catalog" }), "half");
});

test("다음 걸림 높이 — 설계 문서 4.4절 사례", () => {
  const cases = [
    ["peek", 250, 0, "peek"],
    ["peek", 300, 0.8, "half"],     // 투영 444
    ["half", 470, 2.0, "full"],     // 투영 830
    ["full", 700, -0.2, "full"],    // 투영 664 — full에 더 가깝다
    ["full", 760, -0.6, "half"],    // 가장 가까운 곳은 full이지만 빠르게 튕겼다
    ["peek", 200, -1.2, "closed"],
    ["peek", 120, 0, "closed"],     // 120 < 230 × 0.6
    ["half", 470, 0, "half"],
  ];
  for (const [from, visible, velocity, want] of cases) assert.equal(nextSnap({ from, visible, velocity, snaps: SN }), want, `${from} ${visible} ${velocity}`);
  const noHalf = { ...SN, half: null };
  assert.equal(nextSnap({ from: "half", visible: 470, velocity: 0, snaps: noHalf }), "peek");
  assert.equal(nextSnap({ from: "peek", visible: 560, velocity: 0, snaps: noHalf }), "full");
});

test("다음 걸림 높이 — 닫을 수 없으면 peek에서 멈춘다 · 끝에서 튕기면 그대로", () => {
  assert.equal(nextSnap({ from: "peek", visible: 100, velocity: -2, snaps: SN, closable: false }), "peek");
  assert.equal(nextSnap({ from: "full", visible: 780, velocity: 1.5, snaps: SN }), "full");
  assert.equal(nextSnap({ from: "peek", visible: 232, velocity: 0.6, snaps: SN }), "half");   // 빠른 위 튕김은 한 칸 위로
});

test("한 칸 이동 — 끝에서는 그대로, half가 없으면 건너뛴다", () => {
  assert.equal(stepSnap("peek", 1, SN), "half");
  assert.equal(stepSnap("half", 1, SN), "full");
  assert.equal(stepSnap("full", 1, SN), "full");
  assert.equal(stepSnap("full", -1, SN), "half");
  assert.equal(stepSnap("peek", -1, SN), "peek");
  const noHalf = { ...SN, half: null };
  assert.equal(stepSnap("peek", 1, noHalf), "full");
  assert.equal(stepSnap("full", -1, noHalf), "peek");
});

test("끄는 동안의 높이 — full 위로는 25%만, 최대 24px", () => {
  assert.equal(rubberBand(500, 230, 772), 500);
  assert.equal(rubberBand(812, 230, 772), 782);
  assert.equal(rubberBand(1200, 230, 772), 796);
  assert.equal(rubberBand(100, 230, 772), 100);           // peek 아래는 그대로 따라온다
  assert.equal(rubberBand(-20, 230, 772), 0);
});

test("속도 — 최근 100ms의 표본, 위로가 양수", () => {
  assert.equal(velocityOf([]), 0);
  assert.equal(velocityOf([{ t: 0, y: 500 }]), 0);
  assert.equal(velocityOf([{ t: 0, y: 500 }, { t: 50, y: 450 }, { t: 100, y: 400 }]), 1);
  assert.equal(velocityOf([{ t: 0, y: 400 }, { t: 100, y: 500 }]), -1);
  // 오래된 표본은 빼고 — 마지막 100ms만 (멈췄다 뗀 손은 속도 0에 가깝다)
  assert.equal(velocityOf([{ t: 0, y: 0 }, { t: 300, y: 600 }, { t: 400, y: 600 }]), 0);
  assert.equal(velocityOf([{ t: 0, y: 0 }, { t: 400, y: 600 }]), 0);
});

test("엿보기 머리글 투명도", () => {
  assert.equal(peekOpacity(230, SN), 1);
  assert.equal(peekOpacity(464, SN), 0);
  assert.equal(peekOpacity(347, SN), 0.5);
  assert.equal(peekOpacity(100, SN), 1);
  assert.equal(peekOpacity(900, SN), 0);
  assert.equal(peekOpacity(501, { ...SN, half: null }), 0.5);   // half가 없으면 full까지
});

test("3D 해상도 상한 — 설계 문서 6.5절", () => {
  assert.equal(bodyPixelRatio({ dpr: 3, w: 390, h: 844, budget: 900000 }), 1.5);
  assert.equal(bodyPixelRatio({ dpr: 3, w: 390, h: 844, budget: 300000, min: 0.75 }), 0.75);
  assert.equal(bodyPixelRatio({ dpr: 1, w: 390, h: 844, budget: 900000 }), 1);
  assert.equal(bodyPixelRatio({ dpr: 3, w: 100, h: 100, budget: 900000 }), 2);          // 2를 넘지 않는다
  assert.equal(bodyPixelRatio({ dpr: 2, w: 2000, h: 2000, budget: 900000 }), 1);        // 최소 1
  assert.equal(bodyPixelRatio({ dpr: 2, w: 0, h: 0, budget: 900000 }), 2);
});

test("3D 시야 맞춤 — 설계 문서 6.2절", () => {
  const peek = fitBodyView({ W: 390, H: 844, top: 66, bottom: 614, extent: 1, fov: 24 });
  assert.equal(peek.s, 82);
  assert.equal(peek.Hv, 1008);
  assert.deepEqual(peek.view, { fullWidth: 390, fullHeight: 1008, x: 0, y: 164, width: 390, height: 844 });
  assert.equal(peek.aspect, 390 / 1008);
  assert.ok(peek.visible);
  // 가상 시야의 가운데(Hv/2)가 잘라 본 창에서는 yc에 온다
  assert.equal(peek.Hv / 2 - peek.view.y, peek.yc);
  // 반지름 1인 천체가 0.4 × min(W, 548) = 156px로 보이는 거리
  const R = (1 / (peek.distance * Math.tan((12 * Math.PI) / 180))) * (peek.Hv / 2);
  assert.ok(Math.abs(R - 156) < 1e-6);
  const half = fitBodyView({ W: 390, H: 844, top: 66, bottom: 380 });
  assert.equal(half.s, 199);
  const below = fitBodyView({ W: 390, H: 844, top: 400, bottom: 800 });   // 가운데보다 아래면 s < 0, 잘라 보는 자리는 맨 위
  assert.equal(below.s, -178);
  assert.equal(below.view.y, 0);
  assert.equal(below.Hv / 2 - below.view.y, below.yc);
  const center = fitBodyView({ W: 390, H: 844, top: 0, bottom: 844 });
  assert.equal(center.view, null);
  assert.equal(center.aspect, 390 / 844);
  assert.equal(fitBodyView({ W: 390, H: 844, top: 66, bottom: 72 }).visible, false);   // full — 3D가 거의 보이지 않는다
  const saturn = fitBodyView({ W: 390, H: 844, top: 66, bottom: 614, extent: 2.4 });
  assert.ok(Math.abs(saturn.distance / peek.distance - 2.4) < 1e-9);
});
