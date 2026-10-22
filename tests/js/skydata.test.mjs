// 하늘 데이터 — 이진 파일 해석 · 한계 등급 · 회전 행렬 · 별 고르기. 실제 web/data 파일로도 확인한다.
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { altAz, altAzToScene, localSiderealDeg, radecToEq } from "../../web/js/astro.js";
import {
  angularDeg, applyMatrix, decodeMilkyway, decodeStars, eqToHorizonMatrix, limitingMag, pickSky, pickStar, SkyGrid, transpose,
} from "../../web/js/skydata.js";

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} ≉ ${b}`);
const file = (name) => {
  const b = readFileSync(new URL(`../../web/data/${name}`, import.meta.url));
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
};

function starBuffer(rows) {
  const buf = new ArrayBuffer(8 + rows.length * 12), v = new DataView(buf);
  [..."VHS1"].forEach((c, i) => v.setUint8(i, c.charCodeAt(0)));
  v.setUint32(4, rows.length, true);
  rows.forEach(([hip, ra, dec, mag, bv], i) => {
    const o = 8 + i * 12;
    v.setUint32(o, hip, true);
    v.setUint16(o + 4, Math.round((ra / 360) * 65536) % 65536, true);
    v.setInt16(o + 6, Math.round((dec / 90) * 32767), true);
    v.setInt16(o + 8, Math.round(mag * 100), true);
    v.setInt16(o + 10, Math.round(bv * 1000), true);
  });
  return buf;
}

test("별 레코드 해석 — 적경 약 20초각, 등급 0.01 정밀도", () => {
  const s = decodeStars(starBuffer([[32349, 101.287, -16.716, -1.44, 0.009], [1, 0.0009, 1.089, 9.1, 0.482]]));
  assert.equal(s.count, 2);
  assert.deepEqual([...s.hip], [32349, 1]);
  close(s.ra[0], 101.287, 0.006);
  close(s.dec[0], -16.716, 0.003);
  close(s.mag[0], -1.44, 1e-6);
  close(s.bv[1], 0.482, 1e-6);
  assert.throws(() => decodeStars(new ArrayBuffer(8)), /형식/);
});

test("실제 하늘 데이터 — 밝은 별 41,411개 · 시리우스가 가장 밝다", () => {
  const s = decodeStars(file("stars_bright.bin"));
  assert.equal(s.count, 41411);
  assert.equal(s.hip[0], 32349);                  // 시리우스 (밝은 순 정렬)
  assert.ok(s.mag.every((m) => m <= 8.0));
  const faint = decodeStars(file("stars_faint.bin"));
  assert.equal(s.count + faint.count, 118216);
  assert.ok(faint.mag[0] > 8.0);
});

test("은하수 지도 — 은하 중심은 밝고 은하 북극은 비어 있다", () => {
  const mw = decodeMilkyway(file("milkyway.bin"));
  const at = (ra, dec) => mw.data[Math.floor(((90 - dec) / 180) * mw.height) * mw.width + Math.floor((ra / 360) * mw.width)];
  assert.ok(at(266.4, -28.9) > 80, "궁수자리 은하 중심");
  assert.equal(at(192.86, 27.13), 0, "은하 북극");
  assert.equal(at(37.95, 89.26), 0, "북극성");
});

test("한계 등급 — 75도 6등급 · 30도 약 8등급 · 5도 약 12등급, 범위 안", () => {
  close(limitingMag(75), 6);
  close(limitingMag(30), 8, 0.05);
  close(limitingMag(5), 11.94, 0.05);
  assert.equal(limitingMag(0.01), 12.5);
  assert.equal(limitingMag(170), 5.5);
  assert.ok(limitingMag(20) > limitingMag(40));
});

test("적도 → 지평 행렬은 altAz 계산과 같다 · 전치가 역변환", () => {
  const lst = localSiderealDeg(new Date("2026-10-22T21:00:00+09:00"), 126.98);
  const m = eqToHorizonMatrix(37.57, lst);
  for (const [ra, dec] of [[37.95, 89.26], [101.287, -16.716], [279.23, 38.78], [0, 0]]) {
    const { alt, az } = altAz(ra, dec, 37.57, lst);
    const want = altAzToScene(alt, az);
    const got = applyMatrix(m, radecToEq(ra, dec));
    want.forEach((w, i) => close(got[i], w, 1e-9));
    applyMatrix(transpose(m), got).forEach((v, i) => close(v, radecToEq(ra, dec)[i], 1e-9));
  }
});

test("격자에서 가까운 별 고르기 — 경계 · 극 근처 포함, 밝은 별을 우선", () => {
  const stars = { ra: [10, 10.4, 359.8, 0.3, 180, 37.95], dec: [20, 20.1, 5, 5, 89.5, 89.26], mag: [9, 2, 4, 6, 3, 2] };
  const grid = new SkyGrid(2);
  stars.ra.forEach((ra, i) => grid.add(ra, stars.dec[i], i));
  assert.equal(pickStar(stars, grid, 10.05, 20.0, 0.5, 12), 1, "가까운 9등급보다 조금 먼 2등급");
  assert.equal(pickStar(stars, grid, 10.05, 20.0, 0.5, 8), 1);
  assert.equal(pickStar(stars, grid, 0.05, 5, 0.5, 12), 2, "적경 0도 경계를 넘는다");
  assert.equal(pickStar(stars, grid, 100, 89.4, 1.0, 12) >= 4, true, "극 근처는 적경과 무관하게");
  assert.equal(pickStar(stars, grid, 200, -40, 0.5, 12), -1);
  close(angularDeg(0, 0, 90, 0), 90);
});

// 12-1 리뷰 P2 — 적경 0/360도 경계 · 극 근처에서도 구면 각거리로 고른다 (pickNear가 쓰는 pickSky 경로)
function dsoSet(rows) {
  const grid = new SkyGrid(2);
  rows.forEach(([, , ra, dec], i) => grid.add(ra, dec, i));
  return { rows, grid };
}
const noStars = [{ stars: { ra: [], dec: [], mag: [], hip: [] }, grid: new SkyGrid(2) }];

test("성운 선택 — 적경 경계 양쪽의 같은 각거리는 같은 결과 (리뷰 재현: 반경 0.12도)", () => {
  const radius = (12 * 10) / 1000;                                  // PICK_PX 12 · 화각 10도 · 높이 1000px
  const across = pickSky(noStars, dsoSet([["NGC X", "oc", 359.95, 0, 6, 1]]), 0.05, 0, radius, 8);
  const inside = pickSky(noStars, dsoSet([["NGC Y", "oc", 0.15, 0, 6, 1]]), 0.05, 0, radius, 8);
  assert.equal(across?.type, "dso");
  assert.equal(inside?.type, "dso");
  close(across.away, 0.1, 1e-6);
  close(inside.away, across.away, 1e-6);
  assert.equal(pickSky(noStars, dsoSet([["NGC Z", "oc", 359.8, 0, 6, 1]]), 0.05, 0, radius, 8), null);   // 0.25도는 반경 밖
});

test("별 선택 — 경계를 넘어도 반환 각거리가 실제 간격", () => {
  const stars = { ra: [359.95], dec: [0], mag: [3], hip: [7] };
  const grid = new SkyGrid(2);
  grid.add(359.95, 0, 0);
  const hit = pickSky([{ stars, grid }], null, 0.05, 0, 0.12, 8);
  assert.equal(hit.type, "star");
  close(hit.away, 0.1, 1e-6);                                       // 예전 식은 359.9도 × cos(0)으로 과대
});

test("극 근처 — 적경 차가 커도 실제로 가까우면 고른다, 가장 가까운 성운을 고른다", () => {
  const dsos = dsoSet([["far", "gc", 10, 89.9, 5, 1], ["near", "gc", 190, 89.95, 5, 1]]);
  const hit = pickSky(noStars, dsos, 100, 89.97, 0.2, 8);
  assert.equal(dsos.rows[hit.index][0], "near");
  close(hit.away, angularDeg(100, 89.97, 190, 89.95), 1e-9);
  assert.ok(hit.away < 0.06);
});

test("보이지 않는 성운은 고르지 않고, 별이 있으면 별이 먼저", () => {
  const dsos = dsoSet([["NGC X", "oc", 0, 0, 6, 1]]);
  assert.equal(pickSky(noStars, dsos, 0, 0, 0.1, 8, () => false), null);
  const stars = { ra: [0.02], dec: [0], mag: [5], hip: [9] };
  const grid = new SkyGrid(2);
  grid.add(0.02, 0, 0);
  assert.equal(pickSky([{ stars, grid }], dsos, 0, 0, 0.1, 8).type, "star");
});
