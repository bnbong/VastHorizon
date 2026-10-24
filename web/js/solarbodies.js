// 태양계 천체의 크기 · 모양 · 하늘 위치 — Three.js에 의존하지 않는다 (node로 시험 — tests/js/solarbodies.test.mjs).
//
// - 서랍 안 근접 3D 뷰(bodyview.js)가 쓰는 표: 천체마다 평균 반지름 · 모양 · 표면 무늬 종류 · 세 축 크기.
//   반지름은 항목 데이터(Wikidata)에 없거나 오래된 값이 있어 공개 값을 여기 적는다 (출처는 줄마다).
// - 하늘 위 표시(sky.js)가 쓰는 계산:
//   · 왜행성 · 소행성 · 혜성 · 아로코트 — 항목의 position_au(Horizons, 태양 중심 · ICRF 적도 좌표)에서 그날 지구 위치를 뺀다.
//     position_au는 수집 기준일(예: 2026-10-21)의 위치라, 다른 날에는 그 천체가 움직인 만큼 어긋난다.
//   · 목성의 갈릴레이 위성 · 토성의 타이탄 — 원 궤도 근사. 기준 시각의 위상은 Horizons 위치(항목 position_au의 모행성 기준 벡터),
//     공전 반지름 · 주기는 공개 값. 이심률 · 궤도 경사 · 위성끼리의 섭동은 넣지 않는다.

import { BODIES, centuriesJ2000, heliocentric } from "./ephemeris.js";

const DEG = Math.PI / 180;
export const AU_KM = 149597870.7;
// 그 천체를 떠난 빛이 1 AU를 오는 데 걸리는 시간 (일)
const LIGHT_DAY_PER_AU = 499.004784 / 86400;

// 모양: sphere(구) · ellipsoid(세 축 타원체) · lumpy(울퉁불퉁한 덩어리) · top(팽이 — 적도 융기) · contact(두 덩이가 붙은 눈사람) · comet(핵 + 코마)
// surface: 근접 뷰 셰이더의 표면 무늬 (bodyview.js SURFACES)
// axesKm: 세 축 지름 (km) — 구가 아닌 천체만. lobes: 두 덩이 천체의 덩이별 세 축 지름
// spinSec: 근접 뷰에서 한 바퀴 도는 시간 (실제 자전 주기가 아니다 — 하우메아만 실제로 빨리 돌아 짧게)
export const BODY_TABLE = {
  // 지구 — NASA Earth Fact Sheet, 부피 평균 반지름 6,371.0 km
  Q2: { key: "earth", radiusKm: 6371.0, shape: "sphere", surface: "earth" },
  // 화성의 위성 — 위키백과 「포보스 (위성)」(평균 반지름 11.08 km, 25.9 × 22.6 × 18.3 km) · 「데이모스 (위성)」(6.2 km, 15 × 12.2 × 11 km)
  Q7547: { key: "phobos", radiusKm: 11.08, shape: "lumpy", surface: "phobos", axesKm: [25.9, 22.6, 18.3] },
  Q7548: { key: "deimos", radiusKm: 6.2, shape: "lumpy", surface: "deimos", axesKm: [15, 12.2, 11] },
  // 갈릴레이 위성 — NASA Planetary Fact Sheet (Jovian Satellite) · 위키백과
  Q3123: { key: "io", radiusKm: 1821.6, shape: "sphere", surface: "io" },
  Q3143: { key: "europa", radiusKm: 1560.8, shape: "sphere", surface: "europa" },
  Q3169: { key: "ganymede", radiusKm: 2634.1, shape: "sphere", surface: "ganymede" },
  Q3134: { key: "callisto", radiusKm: 2410.3, shape: "sphere", surface: "callisto" },
  // 토성 · 해왕성 · 명왕성의 위성 — 위키백과 「타이탄 (위성)」(2,574.7 km) · 「엔셀라두스」(252.1 km) · 「트리톤 (위성)」(1,353.4 km)
  //   · 「카론 (위성)」(606.0 km, 뉴허라이즌스)
  Q2565: { key: "titan", radiusKm: 2574.7, shape: "sphere", surface: "titan" },
  Q3303: { key: "enceladus", radiusKm: 252.1, shape: "sphere", surface: "enceladus" },
  Q3359: { key: "triton", radiusKm: 1353.4, shape: "sphere", surface: "triton" },
  Q6604: { key: "charon", radiusKm: 606.0, shape: "sphere", surface: "charon" },
  // 왜행성 — 위키백과 「명왕성」(1,188.3 km, 뉴허라이즌스) · 「세레스 (왜행성)」(469.7 km) · 「에리스 (왜행성)」(1,163 km)
  //   · 「마케마케 (왜행성)」(715 km)
  Q339: { key: "pluto", radiusKm: 1188.3, shape: "sphere", surface: "pluto" },
  Q596: { key: "ceres", radiusKm: 469.7, shape: "sphere", surface: "ceres" },
  Q611: { key: "eris", radiusKm: 1163, shape: "sphere", surface: "eris" },
  Q604: { key: "makemake", radiusKm: 715, shape: "sphere", surface: "makemake" },
  // 하우메아 — 세 축 2,322 × 1,704 × 1,026 km (Ortiz et al. 2017, Nature 550). 평균 반지름은 같은 부피의 구로 계산 (약 798 km)
  Q601: { key: "haumea", radiusKm: 798, shape: "ellipsoid", surface: "haumea", axesKm: [2322, 1704, 1026], spinSec: 4 },
  // 소행성 — 위키백과 「4 베스타」(262.7 km, 572.6 × 557.2 × 446.4 km) · NASA OSIRIS-REx 「베누」(평균 반지름 245 m, 565 × 535 × 508 m)
  //   · JAXA 하야부사2 「류구」(적도 지름 1,004 m · 극 지름 875 m, 평균 반지름 약 448 m) · 위키백과 「99942 아포피스」(평균 지름 약 340 m)
  Q3030: { key: "vesta", radiusKm: 262.7, shape: "lumpy", surface: "vesta", axesKm: [572.6, 557.2, 446.4] },
  Q11558: { key: "bennu", radiusKm: 0.245, shape: "top", surface: "bennu", axesKm: [0.565, 0.535, 0.508] },
  Q1385178: { key: "ryugu", radiusKm: 0.448, shape: "top", surface: "ryugu", axesKm: [1.004, 1.004, 0.875] },
  Q118931: { key: "apophis", radiusKm: 0.17, shape: "lumpy", surface: "apophis", axesKm: [0.45, 0.34, 0.3] },
  // 아로코트 — 위키백과 「486958 아로코트」 전체 36 × 20 × 10 km, 큰 덩이 약 22 × 20 × 7 km · 작은 덩이 약 15 × 15 × 10 km (뉴허라이즌스)
  Q18325885: { key: "arrokoth", radiusKm: null, shape: "contact", surface: "arrokoth", axesKm: [36, 20, 10],
               lobes: [[22, 20, 7], [15, 15, 10]] },
  // 혜성 핵 — 위키백과 「핼리 혜성」(15 × 8 × 8 km, 땅콩 모양) · ESA 로제타 「67P」(큰 덩이 4.1 × 3.3 × 1.8 km, 작은 덩이 2.6 × 2.3 × 1.8 km)
  Q23054: { key: "halley", radiusKm: null, shape: "comet", surface: "comet", axesKm: [15, 8, 8] },
  Q844672: { key: "67p", radiusKm: null, shape: "comet", surface: "comet", axesKm: [4.1, 3.3, 1.8],
             lobes: [[4.1, 3.3, 1.8], [2.6, 2.3, 1.8]] },
};

// 하늘에서 이미 3D로 그리는 천체(solar.js) — 근접 뷰에서도 그 셰이더(BODY_FRAG)를 그대로 쓴다. 반지름은 ephemeris.js BODIES
const SKY_BODIES = { Q525: "sun", Q405: "moon", Q308: "mercury", Q313: "venus", Q111: "mars", Q319: "jupiter",
                     Q193: "saturn", Q324: "uranus", Q332: "neptune" };

// 항목 ID → 근접 뷰 정보 { key, radiusKm, shape, surface, axesKm?, lobes?, spinSec, planet? } (태양계 천체가 아니면 null)
export function bodyInfo(id) {
  const planet = SKY_BODIES[id];
  if (planet) return { key: planet, radiusKm: BODIES[planet].radiusKm, shape: "sphere", surface: planet, planet: true, spinSec: 10 };
  const b = BODY_TABLE[id];
  return b ? { spinSec: 10, ...b } : null;
}

// 모양 분류 — 구 · 타원체가 아니면 지오메트리를 노이즈로 일그러뜨린다
export function shapeOf(id) {
  return bodyInfo(id)?.shape ?? null;
}

export function isIrregular(shape) {
  return shape === "lumpy" || shape === "top" || shape === "contact" || shape === "comet";
}

// 세 축 비율 — 가장 긴 축을 1로. 구는 [1, 1, 1]
export function axisRatios(info) {
  if (!info?.axesKm) return [1, 1, 1];
  const m = Math.max(...info.axesKm);
  return info.axesKm.map((v) => v / m);
}

const fmt = (v, digits = 0) => v.toLocaleString("ko-KR", { maximumFractionDigits: digits, minimumFractionDigits: 0 });

// 크기 한 줄 — "평균 반지름 약 1,561 km" · "평균 반지름 약 245 m" · 반지름이 없으면 세 축 크기
export function sizeCaption(info) {
  if (!info) return "";
  const dims = (axes) => {
    const meters = Math.max(...axes) < 2;
    return `${axes.map((v) => (meters ? fmt(v * 1000) : fmt(v, 1))).join(" × ")} ${meters ? "m" : "km"}`;
  };
  if (info.radiusKm == null) {
    if (info.shape === "comet" && info.lobes) return `크기 큰 덩이 약 ${dims(info.lobes[0])}, 작은 덩이 약 ${dims(info.lobes[1])}`;
    return `크기 약 ${dims(info.axesKm)}`;
  }
  const r = info.radiusKm;
  const radius = r < 1 ? `${fmt(r * 1000)} m` : `${fmt(r, r < 100 ? 1 : 0)} km`;
  return `평균 반지름 약 ${radius}${info.axesKm ? ` · 크기 ${dims(info.axesKm)}` : ""}`;
}

// ── 하늘 위치 ─────────────────────────────────────────────────────────────

// 수집 기준일 문자열(YYYY-MM-DD) → 그날 0시. Horizons의 기준 시각은 0시 TDB로, UTC와 약 69초 차이는 무시한다
export function epochDate(epoch) {
  return new Date(`${epoch}T00:00:00Z`);
}

// 기준일 위치를 그대로 쓰는 소천체(왜행성 · 소행성 · 혜성 · 아로코트)가 얼마나 오래된 위치인가.
// 이 날수를 넘으면 툴팁에 어긋날 수 있다고 덧붙이고, 숨김 날수를 넘으면 하늘에 그리지 않는다 (데이터를 다시 모을 때까지)
export const EPOCH_WARN_DAYS = 90;
export const EPOCH_HIDE_DAYS = 365;

// 기준일(YYYY-MM-DD) · 그날 → { days (기준일에서 지난 날수, 앞뒤 모두), note (툴팁에 덧붙일 말, 없으면 ""), hidden }
export function epochAge(epoch, date) {
  const days = Math.floor(Math.abs(date.getTime() - epochDate(epoch).getTime()) / 86400000);
  return {
    days,
    note: days > EPOCH_WARN_DAYS ? `기준일에서 ${days}일 지나 위치가 어긋날 수 있습니다` : "",
    hidden: days > EPOCH_HIDE_DAYS,
  };
}

const sub = (a, b) => a.map((v, i) => v - b[i]);
const add = (a, b) => a.map((v, i) => v + b[i]);
const scale = (a, k) => a.map((v) => v * k);
const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (v) => Math.hypot(...v);
const unit = (v) => scale(v, 1 / norm(v));

// 지구 중심 벡터(적도 좌표, AU) → 방향 · 적경 · 적위 · 거리
function toSky(geo) {
  const d = norm(geo), dir = unit(geo);
  return { dir, ra: ((Math.atan2(dir[1], dir[0]) / DEG) % 360 + 360) % 360, dec: Math.asin(dir[2]) / DEG, distanceAu: d };
}

// 태양 중심 위치(ICRF 적도, AU) → 그날 지구에서 본 방향. 천체는 기준일 자리에 두고 지구만 그날 자리로 옮긴다
export function skyFromHeliocentric(positionAu, date) {
  return toSky(sub(positionAu, heliocentric("earth", centuriesJ2000(date))));
}

// 위성의 원 궤도 — 공전 반지름(km) · 항성 주기(일). 출처: NASA Planetary Fact Sheet (Jovian · Saturnian Satellite)
export const MOON_ORBITS = {
  Q3123: { parent: "jupiter", aKm: 421800, periodDays: 1.769138 },   // 이오
  Q3143: { parent: "jupiter", aKm: 671100, periodDays: 3.551181 },   // 유로파
  Q3169: { parent: "jupiter", aKm: 1070400, periodDays: 7.154553 },  // 가니메데
  Q3134: { parent: "jupiter", aKm: 1882700, periodDays: 16.689018 }, // 칼리스토
  Q2565: { parent: "saturn", aKm: 1221900, periodDays: 15.945421 },  // 타이탄
};

function polar([ra, dec]) {
  return [Math.cos(dec * DEG) * Math.cos(ra * DEG), Math.cos(dec * DEG) * Math.sin(ra * DEG), Math.sin(dec * DEG)];
}

// 위성의 모행성 기준 위치 (적도 좌표, AU) — 원 궤도 근사.
//   기준 시각 epoch의 Horizons 벡터(위성 − 모행성)를 모행성 적도면에 투영해 위상을 잡고, 항성 주기로 돌린다 (순행).
//   궤도면은 모행성 적도면으로 둔다 (갈릴레이 위성 · 타이탄의 궤도 경사는 0.5도 아래).
export function moonOffsetAu(orbit, moonAu, parentAu, epoch, date) {
  const pole = polar(BODIES[orbit.parent].pole);
  const v0 = sub(moonAu, parentAu);
  const e1 = unit(sub(v0, scale(pole, dot3(v0, pole))));
  const e2 = cross(pole, e1);
  const days = (date.getTime() - epoch.getTime()) / 86400000;
  const th = 2 * Math.PI * (days / orbit.periodDays);
  const a = orbit.aKm / AU_KM;
  return add(scale(e1, a * Math.cos(th)), scale(e2, a * Math.sin(th)));
}

// 그날 위성의 지구 중심 위치 — 모행성의 지구 중심 벡터(AU)에 위성 위치를 더한다.
// 빛이 오는 동안(목성 약 35분 · 토성 약 80분) 위성이 움직인 만큼 그 이전 시각의 위치를 쓴다
export function moonSky(orbit, moonAu, parentAu, epoch, date, parentGeoAu) {
  const lightDays = norm(parentGeoAu) * LIGHT_DAY_PER_AU;
  const seen = new Date(date.getTime() - lightDays * 86400000);
  const geo = add(parentGeoAu, moonOffsetAu(orbit, moonAu, parentAu, epoch, seen));
  return { ...toSky(geo), behind: norm(geo) > norm(parentGeoAu) };
}
