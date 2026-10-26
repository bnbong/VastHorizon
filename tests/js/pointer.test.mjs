// 하늘 가리키기 (pointer.js) — W3C DeviceOrientation 각도 → 고도 · 방위, 목표 안내, 정렬 판정
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";

import { alignStep, alphaFromCompass, altAzToEnu, azDelta, declinationDeg, deviceBasis, enuToAltAz, fistsText, followOffset, guide,
         guideText, lightLine, project, screenBasis, smoothBasis } from "../../web/js/pointer.js";

const LY = 9460730472580.8;
const close = (got, want, tol, label) => assert.ok(Math.abs(got - want) <= tol, `${label}: ${got} (기대 ${want} ± ${tol})`);
const closeAz = (got, want, tol, label) => close(((got - want + 540) % 360) - 180, 0, tol, label);
const pointing = (a, b, g, th = 0) => enuToAltAz(screenBasis(deviceBasis(a, b, g), th).forward);

test("자세 아홉 가지 — 가리키는 방향(기기 −z)의 고도 · 방위 (±0.01°)", () => {
  const cases = [
    [[0, 0, 0], -90, null], [[0, 90, 0], 0, 0], [[90, 90, 0], 0, 270], [[30, 90, 0], 0, 330], [[0, 135, 0], 45, 0],
    [[0, 45, 0], -45, 0], [[0, 0, 90], 0, 270], [[0, 0, -90], 0, 90], [[67.8, 131, 0], 41, 292.2],
  ];
  for (const [[a, b, g], alt, az] of cases) {
    const p = pointing(a, b, g);
    close(p.alt, alt, 0.01, `α${a} β${b} γ${g} 고도`);
    if (az != null) closeAz(p.az, az, 0.01, `α${a} β${b} γ${g} 방위`);
  }
});

test("화면 회전 — θ = 90°이면 위쪽이 기기 x축, 가리키는 방향은 회전과 상관없다", () => {
  const b = deviceBasis(20, 70, 10);
  const s0 = screenBasis(b, 0), s90 = screenBasis(b, 90);
  s90.up.forEach((v, i) => close(v, b.x[i], 1e-12, "up = x"));
  s90.forward.forEach((v, i) => close(v, s0.forward[i], 1e-12, "forward"));
});

test("나침반 방위 → α", () => {
  assert.equal(alphaFromCompass(0), 0);
  assert.equal(alphaFromCompass(90), 270);
});

test("원형 저역 필터 — 359°와 1° 사이에서 0° 근처로 수렴하고 180°로 튀지 않는다", () => {
  let x = 359;
  for (let i = 0; i < 50; i++) {
    x = followOffset(x, i % 2 ? 359 : 1, 100, 500);
    assert.ok(x < 5 || x > 355, `${x}`);
  }
  x = followOffset(359, 1, 1e6, 2000);
  close(x, 1, 1e-6, "충분히 지나면 측정값");
  assert.equal(followOffset(null, 42, 16), 42);
});

test("목표 안내 — 북쪽 수평을 볼 때 동쪽 목표는 90° 오른쪽, 남쪽 목표는 등 뒤", () => {
  const b = screenBasis(deviceBasis(0, 90, 0), 0);
  const east = guide(b, altAzToEnu(0, 90));
  close(east.sep, 90, 1e-9, "sep");
  close(east.angle, 0, 1e-9, "angle");
  assert.equal(east.behind, false);
  assert.equal(guide(b, altAzToEnu(0, 180)).behind, true);
  close(guide(b, altAzToEnu(30, 0)).angle, 90, 1e-9, "위쪽 목표");
  close(azDelta(292.2, 0), -67.8, 1e-9, "베가는 왼쪽으로 68°");
});

test("정렬 판정 — 7°에 400ms는 near, 600ms는 aligned(한 번만 fired), 10°는 유지, 13°에 far", () => {
  let s = alignStep(null, 7, 0);
  assert.equal(s.phase, "near");
  s = alignStep(s, 7, 400);
  assert.equal(s.phase, "near");
  s = alignStep(s, 7, 600);
  assert.equal(s.phase, "aligned");
  assert.equal(s.fired, true);
  s = alignStep(s, 7, 700);
  assert.equal(s.fired, false);
  s = alignStep(s, 10, 800);
  assert.equal(s.phase, "aligned");
  s = alignStep(s, 13, 900);
  assert.equal(s.phase, "far");
  assert.equal(alignStep(null, 10, 0).phase, "far");                      // 8°~12°에서 처음 시작하면 아직 far
});

test("화면 투영 — 정면의 별은 가운데, 화각 밖 · 등 뒤는 null", () => {
  const b = screenBasis(deviceBasis(0, 90, 0), 0);
  const size = { width: 390, height: 844, vfov: 60 };
  const c = project(b, altAzToEnu(0, 0), size);
  close(c.x, 195, 1e-9, "x");
  close(c.y, 422, 1e-9, "y");
  assert.ok(project(b, altAzToEnu(0, 1), size).x > 195);           // 조금 동쪽은 오른쪽
  assert.equal(project(b, altAzToEnu(0, 60), size), null);
  assert.equal(project(b, altAzToEnu(0, 180), size), null);
});

test("평활화 — 같은 자세면 그대로, 직교성 유지", () => {
  const a = screenBasis(deviceBasis(0, 90, 0), 0), b = screenBasis(deviceBasis(40, 100, 0), 0);
  const s = smoothBasis(a, b, 16);
  const dot = (p, q) => p.reduce((t, v, i) => t + v * q[i], 0);
  close(dot(s.forward, s.up), 0, 1e-12, "forward ⟂ up");
  close(dot(s.right, s.forward), 0, 1e-12, "right ⟂ forward");
  close(dot(s.right, s.up), 0, 1e-12, "right ⟂ up");
  smoothBasis(a, a, 16).forward.forEach((v, i) => close(v, a.forward[i], 1e-12, "같은 자세"));
  assert.equal(smoothBasis(null, b, 16), b);
  const far = smoothBasis(a, b, 1e6);
  far.forward.forEach((v, i) => close(v, b.forward[i], 1e-9, "충분히 지나면 새 자세"));
});

test("글 안내", () => {
  assert.equal(guideText(40, 20), "오른쪽으로 40° · 위로 20°");
  assert.equal(guideText(-68, -12), "왼쪽으로 68° · 아래로 12°");
  assert.equal(guideText(-3, -2), "거의 다 왔어요");
  assert.equal(fistsText(41), "주먹 4개");
  assert.equal(fistsText(3), "지평선 바로 위");
});

test("빛이 떠난 때 — 베가 약 25광년, 목성 약 6억 km", () => {
  assert.match(lightLine(25 * LY), /약 25년 전에 떠났습니다$/);
  assert.match(lightLine(6e8), /분 전에 떠났습니다$/);
  assert.equal(lightLine(null), "이 빛이 떠난 때는 아직 확인되지 않았어요");
});

test("자기 편각 — 서울은 −10° ~ −8° (WMM-2025), 표 밖은 null", () => {
  const d = declinationDeg(37.5665, 126.978);
  assert.ok(d >= -10 && d <= -8, `${d}`);
  close(declinationDeg(38, 134), -9.3, 1e-9, "격자 꼭짓점");
  assert.equal(declinationDeg(51.5, -0.1), null);
  assert.equal(declinationDeg(37.5, 150), null);
});

test("방위 보정 — 위쪽 둘레로 돌리면 방위만 더해지고 고도는 그대로", async () => {
  const { rotateAz } = await import("../../web/js/pointer.js");
  const b = screenBasis(deviceBasis(67.8, 131, 0), 0);
  const p0 = enuToAltAz(b.forward), p1 = enuToAltAz(rotateAz(b, -9).forward);
  close(p1.alt, p0.alt, 1e-9, "고도");
  closeAz(p1.az, p0.az - 9, 1e-9, "방위");
  assert.equal(rotateAz(b, 0), b);
  const r = rotateAz(b, 30);
  const dot = (p, q) => p.reduce((t, v, i) => t + v * q[i], 0);
  close(dot(r.right, r.up), 0, 1e-12, "직교 유지");
});

test("방위 출처 — iOS 나침반 · 절대 · 상대", async () => {
  const { compassSource } = await import("../../web/js/pointer.js");
  assert.deepEqual(compassSource({ type: "deviceorientation", webkitCompassHeading: 292.2, webkitCompassAccuracy: 10 }),
                   { kind: "ios", heading: 292.2, accuracy: 10 });
  assert.equal(compassSource({ type: "deviceorientation", webkitCompassHeading: 10, webkitCompassAccuracy: -1 }).accuracy, null);
  assert.equal(compassSource({ type: "deviceorientationabsolute", absolute: true }).kind, "absolute");
  assert.equal(compassSource({ type: "deviceorientation", absolute: true }).kind, "absolute");
  assert.equal(compassSource({ type: "deviceorientation", absolute: false }).kind, "relative");
});

test("iOS 경로 — 상대 α에 나침반 오프셋을 더하면 절대 방위가 된다", async () => {
  const { rotateAz, followOffset } = await import("../../web/js/pointer.js");
  // 실제로는 베가(292.2°)를 보고 있지만 α는 시작 기준 10°라 상대 방위는 350°
  const raw = screenBasis(deviceBasis(10, 131, 0), 0);
  const offset = followOffset(null, ((10 - alphaFromCompass(292.2)) % 360 + 360) % 360, 0);
  closeAz(enuToAltAz(rotateAz(raw, offset).forward).az, 292.2, 1e-9, "보정한 방위");
});

test("글 안내 — 남서쪽(225°), 주먹 4개 높이(약 40°)", async () => {
  const { lookText } = await import("../../web/js/pointer.js");
  assert.equal(lookText(41, 225), "남서쪽(225°)을 바라보고, 팔을 쭉 뻗은 주먹 4개 높이(약 40°)를 올려다보세요.");
  assert.match(lookText(-5, 90), /지평선 아래/);
  assert.match(lookText(86.3, 3), /머리 위/);
});

test("정렬 판정 — near 동안에는 8° 안에 머문 시간만 센다 (7°→10°로 500ms는 정렬 아님)", () => {
  let s = alignStep(null, 7, 0);
  s = alignStep(s, 10, 300);
  s = alignStep(s, 10, 500);
  assert.equal(s.phase, "near");
  s = alignStep(s, 10, 900);
  assert.equal(s.phase, "near");                       // 8° 밖에서 900ms가 지나도 정렬되지 않는다
  s = alignStep(s, 7, 1000);
  s = alignStep(s, 7, 1400);
  assert.equal(s.phase, "near");                       // 다시 들어온 1000ms부터 400ms
  s = alignStep(s, 7, 1500);
  assert.equal(s.phase, "aligned");
  assert.equal(s.fired, true);
  assert.equal(alignStep(alignStep(null, 7, 0), 13, 100).phase, "far");
});
