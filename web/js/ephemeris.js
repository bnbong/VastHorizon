// 태양 · 달 · 행성의 그날 위치 — 브라우저에서 계산한다 (서버 하늘 계산은 기준일 ±3일만, 달은 계산하지 않는다).
// Three.js에 의존하지 않는다 (node로 시험 — tests/js/ephemeris.test.mjs 가 JPL Horizons 값과 대조).
//
// | 천체     | 방법                                                                 | 정확도 (출처가 밝힌 값)        |
// |----------|----------------------------------------------------------------------|-------------------------------|
// | 행성     | JPL "Approximate Positions of the Planets" 케플러 궤도 요소 (1800~2050년) | 수 분각                        |
// | 태양     | 지구-달 질량 중심의 위치를 뒤집는다                                     | 약 1분각                       |
// | 달       | 천문 연감(Astronomical Almanac)의 저정밀 식 + J2000 세차 보정          | 경도 약 0.3도 · 거리 약 0.2%  |
//
// 위상 · 밝은 부분의 방향은 따로 계산하지 않는다 — 화면이 천체를 실제 태양 방향의 빛으로 비추면 저절로 맞는다.
// 밝기 비율(illum)은 시험과 툴팁용이다.

const DEG = Math.PI / 180;
const AU_KM = 149597870.7;
const OBLIQUITY = 23.43928 * DEG;          // J2000 황도 경사
export const EARTH_RADIUS_KM = 6378.14;

// JPL 궤도 요소 [a(AU), e, I, L, ϖ(근일점 경도), Ω(승교점 경도)] 와 세기당 변화 — 황도 J2000
const ELEMENTS = {
  mercury: [[0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593],
            [0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081]],
  venus:   [[0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255],
            [0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418]],
  earth:   [[1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0],
            [0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0]],
  mars:    [[1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891],
            [0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343]],
  jupiter: [[5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909],
            [-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106]],
  saturn:  [[9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448],
            [-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794]],
  uranus:  [[19.18916464, 0.04725744, 0.77263783, 313.23810451, 170.95427630, 74.01692503],
            [-0.00196176, -0.00004397, -0.00242939, 428.48202785, 0.40805281, 0.04240589]],
  neptune: [[30.06992276, 0.00859048, 1.77004347, -55.12002969, 44.96476227, 131.78422574],
            [0.00026291, 0.00005105, 0.00035372, 218.45945325, -0.32241464, -0.00508664]],
};

// 천체 — 화면 이름 · 반지름(km) · 자전축(적경, 적위 — IAU) · 대략의 겉보기 등급
export const BODIES = {
  sun:     { name: "태양", radiusKm: 696000, pole: [286.13, 63.87], mag: -26.7 },
  moon:    { name: "달", radiusKm: 1737.4, pole: [270.0, 66.54], mag: -12 },
  mercury: { name: "수성", radiusKm: 2439.7, pole: [281.01, 61.42], mag: 0 },
  venus:   { name: "금성", radiusKm: 6051.8, pole: [272.76, 67.16], mag: -4.2 },
  mars:    { name: "화성", radiusKm: 3389.5, pole: [317.68, 52.89], mag: 0.5 },
  jupiter: { name: "목성", radiusKm: 69911, pole: [268.06, 64.50], mag: -2.4 },
  saturn:  { name: "토성", radiusKm: 58232, pole: [40.59, 83.54], mag: 0.6, rings: [74500, 136780] },
  uranus:  { name: "천왕성", radiusKm: 25362, pole: [257.31, -15.18], mag: 5.7 },
  neptune: { name: "해왕성", radiusKm: 24622, pole: [299.36, 43.46], mag: 7.8 },
};

export function centuriesJ2000(date) {
  return (date.getTime() / 86400000 + 2440587.5 - 2451545.0) / 36525;
}

const mod360 = (x) => ((x % 360) + 360) % 360;

// 황도 → 적도 (J2000)
export function eclipticToEquatorial([x, y, z]) {
  const c = Math.cos(OBLIQUITY), s = Math.sin(OBLIQUITY);
  return [x, y * c - z * s, y * s + z * c];
}

// 행성의 태양 중심 위치 (적도 J2000, AU)
export function heliocentric(key, T) {
  const [base, rate] = ELEMENTS[key];
  const [a, e, I, L, peri, node] = base.map((v, i) => v + rate[i] * T);
  const w = peri - node;                                  // 근일점 인수
  let M = mod360(L - peri);
  if (M > 180) M -= 360;
  // 케플러 방정식 (도 단위)
  const eDeg = e / DEG;
  let E = M + eDeg * Math.sin(M * DEG);
  for (let i = 0; i < 8; i++) {
    const dE = (M - (E - eDeg * Math.sin(E * DEG))) / (1 - e * Math.cos(E * DEG));
    E += dE;
    if (Math.abs(dE) < 1e-7) break;
  }
  const xp = a * (Math.cos(E * DEG) - e), yp = a * Math.sqrt(1 - e * e) * Math.sin(E * DEG);
  const cw = Math.cos(w * DEG), sw = Math.sin(w * DEG), cO = Math.cos(node * DEG), sO = Math.sin(node * DEG);
  const cI = Math.cos(I * DEG), sI = Math.sin(I * DEG);
  const ecl = [
    (cw * cO - sw * sO * cI) * xp + (-sw * cO - cw * sO * cI) * yp,
    (cw * sO + sw * cO * cI) * xp + (-sw * sO + cw * cO * cI) * yp,
    (sw * sI) * xp + (cw * sI) * yp,
  ];
  return eclipticToEquatorial(ecl);
}

// 달의 지구 중심 위치 (적도, AU) — 천문 연감 저정밀 식
export function moonGeocentric(T) {
  const s = (a, b) => Math.sin((a + b * T) * DEG), c = (a, b) => Math.cos((a + b * T) * DEG);
  const lon = 218.32 + 481267.881 * T + 6.29 * s(135.0, 477198.87) - 1.27 * s(259.3, -413335.36)
    + 0.66 * s(235.7, 890534.22) + 0.21 * s(269.9, 954397.74) - 0.19 * s(357.5, 35999.05) - 0.11 * s(186.5, 966404.03);
  const lat = 5.13 * s(93.3, 483202.02) + 0.28 * s(228.2, 960400.89) - 0.28 * s(318.3, 6003.15) - 0.17 * s(217.6, -407332.21);
  const hp = 0.9508 + 0.0518 * c(135.0, 477198.87) + 0.0095 * c(259.3, -413335.36)
    + 0.0078 * c(235.7, 890534.22) + 0.0028 * c(269.9, 954397.74);
  const r = (EARTH_RADIUS_KM / Math.sin(hp * DEG)) / AU_KM;
  // 이 식의 경도는 '그날의 황도' 기준 — 행성 · 별(J2000)과 맞추려고 세차(세기당 약 1.397도)를 뺀다
  const l = (lon - 1.396971 * T) * DEG, b = lat * DEG;
  return eclipticToEquatorial([r * Math.cos(b) * Math.cos(l), r * Math.cos(b) * Math.sin(l), r * Math.sin(b)]);
}

// 관측자 기준 위치 — 지평(화면) 좌표의 지구 중심 방향 · 거리에서 관측자 위치를 뺀다 (12-2 리뷰 P2).
// 지평 좌표는 관측자의 '위쪽'이 y축이므로 관측자는 지구 중심에서 (0, 지구 반지름, 0)에 있다 (지구 편평도는 무시).
// 달은 지평선 근처에서 최대 약 1도(일주시차) 차이가 난다. 태양 · 행성은 거의 변하지 않는다.
export function topocentric(sceneDir, distanceKm) {
  const v = [sceneDir[0] * distanceKm, sceneDir[1] * distanceKm - EARTH_RADIUS_KM, sceneDir[2] * distanceKm];
  const d = Math.hypot(...v);
  return { dir: v.map((x) => x / d), distanceKm: d };
}

const sub = (a, b) => a.map((v, i) => v - b[i]);
const norm = (v) => Math.hypot(...v);
const unit = (v) => { const n = norm(v); return v.map((x) => x / n); };

// 그 시각의 태양 · 달 · 행성 — 지구 중심 방향(적도 단위 벡터) · 적경 · 적위 · 거리 · 시반지름 · 밝은 비율 · 태양 쪽 방향
export function solarSystem(date) {
  const T = centuriesJ2000(date);
  const earth = heliocentric("earth", T);
  const out = [];
  const add = (key, geo, helio) => {
    const d = norm(geo), dir = unit(geo);
    const toSun = unit(helio.map((v) => -v));                  // 천체에서 태양 쪽
    const phaseAngle = Math.acos(Math.max(-1, Math.min(1, -dir.reduce((s, v, i) => s + v * toSun[i], 0))));
    const body = BODIES[key];
    out.push({
      key, ...body, dir, distanceAu: d, distanceKm: d * AU_KM,
      ra: mod360(Math.atan2(dir[1], dir[0]) / DEG), dec: Math.asin(dir[2]) / DEG,
      angularRadiusDeg: Math.atan(body.radiusKm / (d * AU_KM)) / DEG,
      toSun, illum: key === "sun" ? 1 : (1 + Math.cos(phaseAngle)) / 2,
    });
  };
  add("sun", earth.map((v) => -v), [0, 0, 0].map((v, i) => -earth[i] * 1e-9));
  out[0].toSun = unit(earth.map((v) => -v));
  const moonGeo = moonGeocentric(T);
  add("moon", moonGeo, earth.map((v, i) => v + moonGeo[i]));
  for (const key of ["mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune"]) {
    const h = heliocentric(key, T);
    add(key, sub(h, earth), h);
  }
  return out;
}
