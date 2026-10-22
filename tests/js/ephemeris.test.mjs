// 태양 · 달 · 행성 위치 — JPL Horizons 실제 값(2026-10-21 00:00 TDB, 태양 중심 ICRF, data/raw 캐시)과 대조.
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import { centuriesJ2000, heliocentric, moonGeocentric, solarSystem } from "../../web/js/ephemeris.js";

const EPOCH = new Date("2026-10-21T00:00:00Z");
// JPL Horizons 벡터 (AU, 태양 중심, 적도 ICRF) — vasthorizon 수집 캐시 solar_positions_2026-10-21.json
const HORIZONS = {
  earth: [0.8852218, 0.4181329, 0.1812468], moon: [0.8873299, 0.4166865, 0.1805992],
  mercury: [0.3416939, -0.156242, -0.1188775], venus: [0.6542534, 0.2975778, 0.0925114],
  mars: [-0.1416651, 1.4308157, 0.6601027], jupiter: [-3.6045803, 3.5554989, 1.6117263],
  saturn: [9.2314035, 1.8802602, 0.3790692], uranus: [8.860092, 15.89333, 6.835421],
  neptune: [29.8340804, 1.6093988, -0.0839865],
};
const sub = (a, b) => a.map((v, i) => v - b[i]);
const norm = (v) => Math.hypot(...v);
const angleDeg = (a, b) => Math.acos(Math.min(1, a.reduce((s, v, i) => s + v * b[i], 0) / norm(a) / norm(b))) * 180 / Math.PI;

test("행성의 지구 중심 방향 — Horizons와 0.1도 안 (궤도 요소 근사)", () => {
  const T = centuriesJ2000(EPOCH);
  const earth = heliocentric("earth", T);
  for (const key of ["mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune"]) {
    const want = sub(HORIZONS[key], HORIZONS.earth), got = sub(heliocentric(key, T), earth);
    assert.ok(angleDeg(want, got) < 0.1, `${key} ${angleDeg(want, got).toFixed(4)}도`);
    assert.ok(Math.abs(norm(got) / norm(want) - 1) < 0.005, `${key} 거리`);
  }
});

test("태양 방향 · 거리 — Horizons와 0.02도 안", () => {
  const sun = solarSystem(EPOCH).find((b) => b.key === "sun");
  const want = HORIZONS.earth.map((v) => -v);
  assert.ok(angleDeg(want, sun.dir) < 0.02, angleDeg(want, sun.dir));
  assert.ok(Math.abs(sun.distanceAu / norm(want) - 1) < 0.001);
  assert.ok(Math.abs(sun.angularRadiusDeg - 0.2685) < 0.003);       // 10월 말 시반지름 약 16.1′
});

test("달 방향 · 거리 — Horizons와 0.1도 · 0.5% 안 (저정밀 식 + 세차 보정)", () => {
  const want = sub(HORIZONS.moon, HORIZONS.earth);
  const got = moonGeocentric(centuriesJ2000(EPOCH));
  assert.ok(angleDeg(want, got) < 0.1, angleDeg(want, got));      // 보정 전에는 0.34도 (세차 26년분)
  assert.ok(Math.abs(norm(got) / norm(want) - 1) < 0.005, norm(got) / norm(want));
});

test("달의 위상 — 2024년 1월 보름(25일 17:54 UTC)은 거의 다 밝고, 그믐(11일 11:57 UTC)은 거의 어둡다", () => {
  const moon = (iso) => solarSystem(new Date(iso)).find((b) => b.key === "moon");
  assert.ok(moon("2024-01-25T17:54:00Z").illum > 0.99);
  assert.ok(moon("2024-01-11T11:57:00Z").illum < 0.01);
  const quarter = moon("2024-01-18T03:53:00Z").illum;              // 상현
  assert.ok(quarter > 0.4 && quarter < 0.6, quarter);
});

test("춘분(2026-03-20 14:46 UTC)의 태양은 적경 0 · 적위 0 근처 (J2000 좌표라 세차만큼 어긋남)", () => {
  // 춘분은 '그날의 적도' 기준이고 이 계산은 J2000 좌표(별 데이터와 같은 좌표)다 — 26년 세차(약 20″/년)만큼 적위가 남쪽으로
  const sun = solarSystem(new Date("2026-03-20T14:46:00Z")).find((b) => b.key === "sun");
  assert.ok(Math.abs(sun.dec + 0.145) < 0.03, sun.dec);
  assert.ok(Math.abs(360 - sun.ra - 0.33) < 0.05, sun.ra);           // 적경도 세차만큼(약 0.33도) 서쪽
});

test("시반지름 · 이름", () => {
  const all = Object.fromEntries(solarSystem(EPOCH).map((b) => [b.key, b]));
  assert.equal(all.jupiter.name, "목성");
  assert.ok(all.moon.angularRadiusDeg > 0.24 && all.moon.angularRadiusDeg < 0.28);
  assert.ok(all.jupiter.angularRadiusDeg * 3600 > 15 && all.jupiter.angularRadiusDeg * 3600 < 25);   // 지름 30~50″
  assert.ok(all.saturn.rings);
});
