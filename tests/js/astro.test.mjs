// 3D 화면의 천문 계산 테스트 — 서버(features/sky.py)와 같은 값을 내는지.
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import { altAz, altAzToScene, compass, distanceText, eqToScene, localSiderealDeg, mapRadius, radecToEq } from "../../web/js/astro.js";

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} ≉ ${b}`);

test("북극성 고도는 위도와 같다 (서버 계산값과 일치)", () => {
  const lst = localSiderealDeg(new Date("2026-10-22T21:00:00+09:00"), 126.98);
  const { alt, az } = altAz(37.95, 89.26, 37.57, lst);
  close(alt, 37.936816501690046, 1e-9);           // features/sky.py 결과
  close(az, 0.8128613270462183, 1e-9);
});

test("남중한 별은 남쪽, 고도 90 − |위도 − 적위|", () => {
  const { alt, az } = altAz(100, -10, 37.5, 100);
  close(alt, 42.5);
  close(az, 180);
  assert.equal(compass(az), "남");
  assert.equal(compass(359), "북");
});

test("좌표 변환 — 천구 북극은 화면 위, 지평 좌표 북쪽은 −z", () => {
  assert.deepEqual(eqToScene(radecToEq(0, 90)).map((v) => Math.round(v) + 0), [0, 1, 0]);
  assert.deepEqual(altAzToScene(0, 0).map((v) => Math.round(v) + 0), [0, 0, -1]);
  assert.deepEqual(altAzToScene(0, 90).map((v) => Math.round(v) + 0), [1, 0, 0]);
});

test("로그 스케일 반지름은 거리 순서를 지킨다", () => {
  const kms = [420, 384400, 1.496e8, 2.58e10, 4.0e13, 2.4e19];
  const rs = kms.map(mapRadius);
  assert.deepEqual([...rs].sort((a, b) => a - b), rs);
  assert.equal(mapRadius(0), 0);
});

test("지도 척도 — 멀수록 고리 간격이 넓어진다 (1광초 · 1광분 · 1광일 · 1광년 · 1천 광년 · 100만 광년 · 우주의 끝)", () => {
  const LY = 9460730472580.8, C = 299792.458;
  const rs = [C, C * 60, C * 86400, LY, 1e3 * LY, 1e6 * LY, 465e8 * LY].map(mapRadius);
  const gaps = rs.slice(1).map((r, i) => r - rs[i]);
  assert.deepEqual([...gaps].sort((a, b) => a - b), gaps);          // 간격이 점점 커진다
  assert.ok(gaps.at(-1) > 2 * gaps[0] && gaps.at(-1) > 60, gaps.join(","));
  assert.ok(rs.at(-1) > 190 && rs.at(-1) < 200, rs.at(-1));       // 관측 가능한 우주의 끝 — 최대 줌아웃의 기준
});

test("거리 표기", () => {
  assert.equal(distanceText(420), "약 420 km");
  assert.equal(distanceText(4.15e15), "약 439 광년");
  assert.equal(distanceText(2.4e19), "약 254만 광년");
});

test("적도 벡터 ↔ 적경 · 적위 왕복", async () => {
  const { eqToRadec } = await import("../../web/js/astro.js");
  const { ra, dec } = eqToRadec(radecToEq(101.29, -16.72));
  close(ra, 101.29, 1e-9);
  close(dec, -16.72, 1e-9);
});

test("지평선 거리 · 빛의 여정 (서버 departure_year 와 같은 식)", async () => {
  const { horizonKm, lightJourney } = await import("../../web/js/astro.js");
  close(horizonKm(1.7), 4.654, 1e-3);
  const LY = 9460730472580.8;
  assert.equal(lightJourney(548 * LY, 2026), "1478년 무렵 출발한 빛");
  assert.equal(lightJourney(2100 * LY, 2026), "기원전 75년 무렵 출발한 빛");   // 2026 − 2100 = −74 → 기원전 75년
  assert.equal(lightJourney(0.5 * LY, 2026), null);
  assert.match(lightJourney(2.54e6 * LY, 2026), /인류 문명 이전/);
});

test("내 세상의 반지름 표기 — 단위 경계", async () => {
  const { measure } = await import("../../web/js/astro.js");
  const LY = 9460730472580.8;
  assert.deepEqual(measure(4.654), { value: "4.7", unit: "km" });
  assert.deepEqual(measure(384400), { value: "38.4만", unit: "km" });
  assert.deepEqual(measure(6.3e8), { value: "6.3억", unit: "km" });
  assert.deepEqual(measure(172 * 149597870.7), { value: "257.3억", unit: "km" });   // 보이저 1호 — 450억 km 미만은 억 km
  assert.deepEqual(measure(400 * 149597870.7), { value: "400", unit: "AU" });
  assert.deepEqual(measure(4.2 * LY), { value: "4.2", unit: "광년" });
  assert.deepEqual(measure(548 * LY), { value: "548", unit: "광년" });
  assert.deepEqual(measure(254e4 * LY), { value: "254만", unit: "광년" });
  assert.deepEqual(measure(465e8 * LY), { value: "465억", unit: "광년" });
});

test("지평선 길 — 지평선 0, 우주의 끝 1, 단조 증가", async () => {
  const { horizonScale, horizonKm, EDGE_KM } = await import("../../web/js/astro.js");
  close(horizonScale(horizonKm()), 0, 1e-9);
  close(horizonScale(EDGE_KM), 1, 1e-9);
  const xs = [10, 1e6, 1e12, 1e17, 1e22].map(horizonScale);
  assert.deepEqual([...xs].sort((a, b) => a - b), xs);
  assert.equal(horizonScale(1e30), 1);
});

test("내 세상 크기 문장 — 빛의 시간 · 지평선의 몇 배", async () => {
  const { lightTime, koreanBig, worldScaleLine, horizonKm } = await import("../../web/js/astro.js");
  const LY = 9460730472580.8;
  assert.equal(lightTime(384400), "약 1.3초");
  assert.equal(lightTime(1.496e8), "약 8.3분");
  assert.equal(lightTime(2.58e10), "약 24시간");
  assert.equal(lightTime(548 * LY), "약 548년");
  assert.equal(lightTime(254e4 * LY), "약 254만 년");
  assert.equal(koreanBig(1.1e16), "1.1경");
  assert.equal(koreanBig(2540000), "254만");
  assert.equal(worldScaleLine(horizonKm()), "아직 지평선 너머를 바라보지 않았습니다");
  assert.equal(worldScaleLine(548 * LY), "빛으로 약 548년 걸리는 거리 · 지평선의 1,110조 배");   // 5.18×10¹⁵ km ÷ 4.65 km
});
