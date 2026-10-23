// 태양계 천체의 크기 · 모양 표와 하늘 위치 계산 (solarbodies.js) — 항목 데이터(data/items.json, JPL Horizons 2026-10-21)와 대조.
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { centuriesJ2000, eclipticToEquatorial, heliocentric } from "../../web/js/ephemeris.js";
import { AU_KM, axisRatios, BODY_TABLE, bodyInfo, epochDate, isIrregular, MOON_ORBITS, moonOffsetAu, moonSky, shapeOf,
         sizeCaption, skyFromHeliocentric } from "../../web/js/solarbodies.js";

const items = JSON.parse(readFileSync(new URL("../../data/items.json", import.meta.url), "utf8")).items;
const solar = new Map(items.filter((i) => i.group === "solar_system").map((i) => [i.id, i]));
const EPOCH = epochDate("2026-10-21");
const sub = (a, b) => a.map((v, i) => v - b[i]);
const norm = (v) => Math.hypot(...v);
const angleDeg = (a, b) => Math.acos(Math.min(1, a.reduce((s, v, i) => s + v * b[i], 0) / norm(a) / norm(b))) * 180 / Math.PI;

// 서랍 근접 뷰가 새로 맡는 23건
const NEW_23 = ["Q2", "Q7547", "Q7548", "Q3123", "Q3143", "Q3169", "Q3134", "Q2565", "Q3303", "Q3359", "Q6604", "Q339", "Q596", "Q611",
                "Q601", "Q604", "Q3030", "Q11558", "Q1385178", "Q118931", "Q18325885", "Q23054", "Q844672"];

test("position_au는 태양 중심 · ICRF 적도 좌표 — ephemeris.js의 지구 위치와 같은 좌표계", () => {
  const earthItem = solar.get("Q2").position_au;
  const earth = heliocentric("earth", centuriesJ2000(EPOCH));
  assert.ok(norm(sub(earthItem, earth)) < 2e-4, `차이 ${norm(sub(earthItem, earth))} AU`);
  // 황도 좌표였다면 적도로 돌려야 맞을 텐데, 돌리면 오히려 크게 어긋난다
  assert.ok(norm(sub(eclipticToEquatorial(earthItem), earth)) > 0.1);
});

test("왜행성 · 소행성 · 혜성 — 기준일에는 Horizons 지구 중심 방향과 0.02도 안", () => {
  const earthItem = solar.get("Q2").position_au;
  for (const id of ["Q339", "Q596", "Q611", "Q601", "Q604", "Q3030", "Q11558", "Q1385178", "Q118931", "Q18325885", "Q23054", "Q844672"]) {
    const p = solar.get(id).position_au;
    const got = skyFromHeliocentric(p, EPOCH), want = sub(p, earthItem);
    assert.ok(angleDeg(got.dir, want) < 0.02, `${id} ${angleDeg(got.dir, want).toFixed(4)}도`);
    assert.ok(Math.abs(got.distanceAu * AU_KM / solar.get(id).distance.km - 1) < 1e-3, `${id} 거리`);
    assert.ok(got.ra >= 0 && got.ra < 360 && Math.abs(got.dec) <= 90);
  }
});

test("다른 날에는 지구만 움직인다 — 명왕성 방향이 반년 사이 시차만큼(약 1.6도 안) 바뀐다", () => {
  const p = solar.get("Q339").position_au;
  const a = skyFromHeliocentric(p, EPOCH), b = skyFromHeliocentric(p, new Date("2027-04-21T00:00:00Z"));
  const d = angleDeg(a.dir, b.dir);
  assert.ok(d > 0.5 && d < 2 * Math.atan(1 / 35) * 180 / Math.PI, `${d.toFixed(3)}도`);
});

test("위성 원 궤도 — 기준 시각에는 Horizons 위성 − 모행성 벡터와 0.5도 · 공전 반지름 2.5% 안", () => {
  for (const [id, orbit] of Object.entries(MOON_ORBITS)) {
    const parent = orbit.parent === "jupiter" ? "Q319" : "Q193";
    const want = sub(solar.get(id).position_au, solar.get(parent).position_au);
    const got = moonOffsetAu(orbit, solar.get(id).position_au, solar.get(parent).position_au, EPOCH, EPOCH);
    assert.ok(angleDeg(got, want) < 0.5, `${id} ${angleDeg(got, want).toFixed(3)}도`);
    assert.ok(Math.abs(norm(want) * AU_KM / orbit.aKm - 1) < 0.025, `${id} 반지름`);
  }
});

test("위성 원 궤도 — 한 주기 뒤 제자리, 반 주기 뒤 반대편", () => {
  const orbit = MOON_ORBITS.Q3123, io = solar.get("Q3123").position_au, jup = solar.get("Q319").position_au;
  const at = (days) => moonOffsetAu(orbit, io, jup, EPOCH, new Date(EPOCH.getTime() + days * 86400000));
  assert.ok(angleDeg(at(0), at(orbit.periodDays)) < 1e-4);
  assert.ok(Math.abs(angleDeg(at(0), at(orbit.periodDays / 2)) - 180) < 1e-4);
});

// JPL Horizons API로 받은 위성 − 모행성 벡터 (AU, ICRF 적도, 0시 TDB, CENTER 500@599 · 500@699) — 2026-10-24 조회
const HORIZONS_LATER = {
  Q3123: { "2027-03-01": [-2.436819e-3, -1.253881e-3, -6.376295e-4], "2031-01-01": [2.602714e-3, 9.510367e-4, 4.949972e-4] },
  Q3143: { "2027-03-01": [2.208035e-3, 3.478628e-3, 1.680300e-3], "2031-01-01": [4.413404e-3, -9.077939e-4, -3.575493e-4] },
  Q3169: { "2027-03-01": [1.721228e-3, 6.255327e-3, 3.028971e-3], "2031-01-01": [3.419198e-3, 5.640151e-3, 2.762916e-3] },
  Q3134: { "2027-03-01": [-7.356251e-3, -9.266344e-3, -4.476218e-3], "2031-01-01": [-6.862747e-3, -9.573686e-3, -4.610279e-3] },
  Q2565: { "2027-03-01": [-8.171191e-3, -1.673759e-3, 8.361536e-4], "2031-01-01": [-8.132101e-3, 2.023385e-3, 5.873832e-4] },
};

test("위성 원 궤도 — 몇 년 뒤에도 Horizons와 가깝다 (갈릴레이 위성 위치 오차 공전 반지름의 2% · 타이탄 8% 안)", () => {
  for (const [id, byDate] of Object.entries(HORIZONS_LATER)) {
    const orbit = MOON_ORBITS[id], parent = orbit.parent === "jupiter" ? "Q319" : "Q193";
    for (const [date, want] of Object.entries(byDate)) {
      const got = moonOffsetAu(orbit, solar.get(id).position_au, solar.get(parent).position_au, EPOCH, new Date(`${date}T00:00:00Z`));
      const err = norm(sub(got, want)) / norm(want);
      assert.ok(err < (id === "Q2565" ? 0.08 : 0.02), `${id} ${date} ${(err * 100).toFixed(1)}%`);
    }
  }
});

test("위성의 지구 중심 위치 — 모행성 방향에서 공전 반지름만큼의 각거리 안, 뒤쪽 판정", () => {
  const orbit = MOON_ORBITS.Q3134, jupGeo = sub(solar.get("Q319").position_au, solar.get("Q2").position_au);
  const s = moonSky(orbit, solar.get("Q3134").position_au, solar.get("Q319").position_au, EPOCH, EPOCH, jupGeo);
  const maxDeg = Math.atan(orbit.aKm / AU_KM / norm(jupGeo)) * 180 / Math.PI;
  assert.ok(angleDeg(s.dir, jupGeo) <= maxDeg * 1.001);
  assert.equal(typeof s.behind, "boolean");
});

test("근접 뷰 표 — 23건 모두 반지름(또는 세 축 크기)과 모양이 있다", () => {
  for (const id of NEW_23) {
    const b = bodyInfo(id);
    assert.ok(b, id);
    assert.ok(b.radiusKm > 0 || b.axesKm?.length === 3, `${id} 크기`);
    assert.ok(sizeCaption(b).length > 0);
    assert.ok(b.spinSec > 0);
  }
  for (const id of ["Q525", "Q405", "Q308", "Q313", "Q111", "Q319", "Q193", "Q324", "Q332"]) assert.equal(bodyInfo(id).planet, true, id);
  assert.equal(bodyInfo("Q3409"), null);                 // 태양계 천체가 아니다
});

test("반지름 표 — 항목에 Wikidata 평균 반지름이 있으면 3% 안에서 같다", () => {
  for (const [id, b] of Object.entries(BODY_TABLE)) {
    const wd = solar.get(id)?.attrs["평균 반지름(km)"];
    if (wd == null || b.radiusKm == null) continue;
    assert.ok(Math.abs(b.radiusKm / wd - 1) < 0.03, `${id} 표 ${b.radiusKm} · Wikidata ${wd}`);
  }
});

test("모양 분류 — 구가 아닌 천체 8건(+ 하우메아 타원체)", () => {
  const irregular = NEW_23.filter((id) => isIrregular(shapeOf(id)));
  assert.deepEqual(irregular.sort(), ["Q7547", "Q7548", "Q3030", "Q11558", "Q1385178", "Q118931", "Q18325885", "Q23054", "Q844672"].sort());
  assert.equal(shapeOf("Q11558"), "top");
  assert.equal(shapeOf("Q1385178"), "top");
  assert.equal(shapeOf("Q18325885"), "contact");
  assert.equal(shapeOf("Q23054"), "comet");
  assert.equal(shapeOf("Q601"), "ellipsoid");
  assert.equal(shapeOf("Q3143"), "sphere");
  assert.ok(bodyInfo("Q601").spinSec < bodyInfo("Q3143").spinSec);   // 하우메아는 빨리 돈다
  assert.deepEqual(axisRatios(bodyInfo("Q3143")), [1, 1, 1]);
  const [a, b, c] = axisRatios(bodyInfo("Q601"));
  assert.ok(a === 1 && b < a && c < b);
});

test("크기 한 줄 — km · m 단위와 천 단위 쉼표", () => {
  assert.equal(sizeCaption(bodyInfo("Q3143")), "평균 반지름 약 1,561 km");
  assert.equal(sizeCaption(bodyInfo("Q11558")), "평균 반지름 약 245 m · 크기 565 × 535 × 508 m");
  assert.equal(sizeCaption(bodyInfo("Q1385178")), "평균 반지름 약 448 m · 크기 1,004 × 1,004 × 875 m");
  assert.equal(sizeCaption(bodyInfo("Q7547")), "평균 반지름 약 11.1 km · 크기 25.9 × 22.6 × 18.3 km");
  assert.equal(sizeCaption(bodyInfo("Q18325885")), "크기 약 36 × 20 × 10 km");
  assert.match(sizeCaption(bodyInfo("Q844672")), /^크기 큰 덩이 약 4\.1 × 3\.3 × 1\.8 km, 작은 덩이 약 2\.6 × 2\.3 × 1\.8 km$/);
  assert.equal(sizeCaption(null), "");
});
