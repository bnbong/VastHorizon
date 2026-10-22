// 달의 일주시차 — 지구 중심 위치를 관측자 기준으로 (12-2 리뷰 P2)
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import { centuriesJ2000, EARTH_RADIUS_KM, moonGeocentric, topocentric } from "../../web/js/ephemeris.js";

const AU_KM = 149597870.7;
const altDeg = (dir) => Math.asin(dir[1]) * 180 / Math.PI;
const sceneAt = (alt, az = 0) => {
  const a = alt * Math.PI / 180, z = az * Math.PI / 180;
  return [Math.cos(a) * Math.sin(z), Math.sin(a), -Math.cos(a) * Math.cos(z)];
};
const moonKm = Math.hypot(...moonGeocentric(centuriesJ2000(new Date("2026-10-21T00:00:00Z")))) * AU_KM;

test("리뷰 재현 — 지구 중심 고도 +0.30도인 달은 관측자에게 약 −0.625도 (지평선 아래)", () => {
  const topo = topocentric(sceneAt(0.3), moonKm);
  assert.ok(Math.abs(altDeg(topo.dir) - -0.6253) < 0.003, altDeg(topo.dir));
  assert.ok(Math.abs(topo.distanceKm - moonKm) < 100);        // 지평선 근처는 거리가 거의 그대로 (관측자가 시선과 거의 수직으로 떨어져 있다)
});

test("천정의 달 — 방향은 그대로, 거리만 지구 반지름만큼 가깝다", () => {
  const topo = topocentric([0, 1, 0], moonKm);
  assert.ok(Math.abs(altDeg(topo.dir) - 90) < 1e-9);
  assert.ok(Math.abs(topo.distanceKm - (moonKm - EARTH_RADIUS_KM)) < 1e-6);
});

test("관측 위치에 따라 달라진다 — 같은 지구 중심 방향도 고도에 따라 시차가 다르다, 행성은 거의 그대로", () => {
  const low = altDeg(topocentric(sceneAt(10, 120), moonKm).dir), high = altDeg(topocentric(sceneAt(60, 120), moonKm).dir);
  assert.ok(10 - low > 0.8 && 10 - low < 1.0, low);         // 고도가 낮을수록 시차가 크다
  assert.ok(60 - high > 0.4 && 60 - high < 0.5, high);
  const jupiter = altDeg(topocentric(sceneAt(10, 120), 5 * AU_KM).dir);
  assert.ok(Math.abs(jupiter - 10) < 0.001);
});
