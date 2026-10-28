// 하늘 가리키기 — 휴대폰 방향 센서(DeviceOrientation)의 각도를 하늘의 고도 · 방위로 바꾸고, 목표 천체까지 안내한다.
// DOM · Three.js에 의존하지 않는다 (node로 시험 — tests/js/pointer.test.mjs).
//
// 좌표계 (W3C DeviceOrientation)
//   지구: X 동쪽 · Y 북쪽 · Z 위쪽 (ENU). 벡터는 [동, 북, 위] 배열
//   기기: 화면을 세로로 둔 상태에서 x 오른쪽 · y 위쪽 · z 화면에서 사용자 쪽
//   회전: Z-X'-Y'' 순서 — R = Rz(α) · Rx(β) · Ry(γ), R의 열이 기기 x · y · z 축을 ENU로 나타낸 벡터
// 가리키는 방향은 휴대폰 뒷면이 향하는 쪽(기기 −z) — 화면을 보면서 휴대폰을 하늘로 들어 올리는 자세

import { compass, lightTime } from "./astro.js";

const DEG = Math.PI / 180;
export const ALIGN_ENTER = 8, ALIGN_EXIT = 12, ALIGN_DWELL_MS = 500, SMOOTH_TAU_MS = 150, VFOV = 60;
const GUIDE_MIN_DEG = 5;

const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const scale = (a, k) => a.map((v) => v * k);
const add = (a, b) => a.map((v, i) => v + b[i]);
const sub = (a, b) => a.map((v, i) => v - b[i]);
const unit = (a) => { const n = Math.hypot(...a); return n ? scale(a, 1 / n) : a; };
const mod360 = (x) => ((x % 360) + 360) % 360;
const wrap180 = (x) => mod360(x + 180) - 180;

// 기기 축의 ENU 벡터 { x, y, z } — 회전 행렬 R의 세 열
export function deviceBasis(alphaDeg, betaDeg, gammaDeg) {
  const ca = Math.cos(alphaDeg * DEG), sa = Math.sin(alphaDeg * DEG);
  const cb = Math.cos(betaDeg * DEG), sb = Math.sin(betaDeg * DEG);
  const cg = Math.cos(gammaDeg * DEG), sg = Math.sin(gammaDeg * DEG);
  return {
    x: [ca * cg - sa * sb * sg, sa * cg + ca * sb * sg, -cb * sg],
    y: [-sa * cb, ca * cb, sb],
    z: [ca * sg + sa * sb * cg, sa * sg - ca * sb * cg, cb * cg],
  };
}

// 화면 기준 축 { right, up, forward } — 화면 회전 θ(screen.orientation.angle)를 반영한다. forward는 회전과 상관없다
export function screenBasis(basis, screenAngleDeg = 0) {
  const c = Math.cos(screenAngleDeg * DEG), s = Math.sin(screenAngleDeg * DEG);
  return {
    right: add(scale(basis.x, c), scale(basis.y, -s)),
    up: add(scale(basis.y, c), scale(basis.x, s)),
    forward: scale(basis.z, -1),
  };
}

// ENU 단위 벡터 → { alt, az } (방위: 북 0° → 동 90°, astro.altAz와 같은 규칙)
export function enuToAltAz([e, n, u]) {
  return { alt: Math.asin(Math.max(-1, Math.min(1, u))) / DEG, az: mod360(Math.atan2(e, n) / DEG) };
}

export function altAzToEnu(alt, az) {
  const a = alt * DEG, z = az * DEG;
  return [Math.cos(a) * Math.sin(z), Math.cos(a) * Math.cos(z), Math.sin(a)];
}

// iOS webkitCompassHeading(자북 기준 시계 방향) → 북쪽 기준 α
export function alphaFromCompass(headingDeg) {
  return mod360(360 - headingDeg);
}

// 원형 저역 필터 — 0°/360° 경계에서 튀지 않게 차이를 −180~180°로 접어 따라간다
export function followOffset(prevDeg, measuredDeg, dtMs, tauMs = 2000) {
  if (prevDeg == null || !Number.isFinite(prevDeg)) return mod360(measuredDeg);
  const k = 1 - Math.exp(-Math.max(0, dtMs) / tauMs);
  return mod360(prevDeg + k * wrap180(measuredDeg - prevDeg));
}

// 벡터 평활화 — 가리키는 방향과 위쪽을 따로 따라가고, 위쪽을 다시 가리키는 방향에 수직으로 맞춘다. right = forward × up
export function smoothBasis(prev, next, dtMs, tauMs = SMOOTH_TAU_MS) {
  if (!prev) return next;
  const k = 1 - Math.exp(-Math.max(0, dtMs) / tauMs);
  const forward = unit(add(prev.forward, scale(sub(next.forward, prev.forward), k)));
  let up = unit(add(prev.up, scale(sub(next.up, prev.up), k)));
  up = unit(sub(up, scale(forward, dot(up, forward))));
  return { right: cross(forward, up), up, forward };
}

// 방위 보정 — 모든 축을 위쪽(ENU z) 둘레로 돌려 방위만 deg만큼 더한다 (나침반 기준 · 자기 편각 · 나침반 맞추기)
//   방위 az → az + deg. 고도는 그대로다. { right, up, forward } · { x, y, z } 어느 쪽이든 같은 열쇠로 돌려준다
export function rotateAz(basis, deg) {
  if (!deg) return basis;
  const c = Math.cos(deg * DEG), s = Math.sin(deg * DEG);
  const rot = ([e, n, u]) => [e * c + n * s, -e * s + n * c, u];
  return Object.fromEntries(Object.entries(basis).map(([k, v]) => [k, rot(v)]));
}

// 이벤트의 방위 출처 — ios(webkitCompassHeading, 자북 기준) · absolute(deviceorientationabsolute 또는 absolute: true) · relative(기준 없음)
export function compassSource(e) {
  const h = e?.webkitCompassHeading;
  if (Number.isFinite(h) && h >= 0) {
    const acc = e.webkitCompassAccuracy;
    return { kind: "ios", heading: h, accuracy: Number.isFinite(acc) && acc >= 0 ? acc : null };
  }
  if (e?.type === "deviceorientationabsolute" || e?.absolute === true) return { kind: "absolute", heading: null, accuracy: null };
  return { kind: "relative", heading: null, accuracy: null };
}

// 글 안내 — "남서쪽(225°)을 바라보고, 팔을 쭉 뻗은 주먹 4개 높이(약 40°)를 올려다보세요."
export function lookText(alt, az) {
  const dir = `${compass(az)}쪽(${Math.round(((az % 360) + 360) % 360)}°)`;
  if (alt < 0) return `${dir} 지평선 아래에 있어 지금은 보이지 않아요.`;
  if (alt >= 75) return `${dir}에서 거의 머리 위(약 ${Math.round(alt)}°)를 올려다보세요.`;
  const fists = fistsText(alt);
  return fists === "지평선 바로 위" ? `${dir}을 바라보고, 지평선 바로 위(약 ${Math.round(alt)}°)를 살펴보세요.`
    : `${dir}을 바라보고, 팔을 쭉 뻗은 ${fists} 높이(약 ${Math.round(alt / 10) * 10}°)를 올려다보세요.`;
}

// 목표까지 — 각거리 sep(도), 화면 화살표 각도 angle(도, 오른쪽 0 · 위 90), 등 뒤에 있는가
export function guide(basis, targetEnu) {
  const tx = dot(targetEnu, basis.right), ty = dot(targetEnu, basis.up), tz = dot(targetEnu, basis.forward);
  return { sep: Math.acos(Math.max(-1, Math.min(1, tz))) / DEG, angle: Math.atan2(ty, tx) / DEG, behind: tz < 0 };
}

// 글 안내 — "오른쪽으로 40° · 위로 20°". 5° 미만인 축은 생략하고, 둘 다 생략되면 "거의 다 왔어요"
export function guideText(dAz, dAlt) {
  const parts = [];
  if (Math.abs(dAz) >= GUIDE_MIN_DEG) parts.push(`${dAz > 0 ? "오른쪽" : "왼쪽"}으로 ${Math.round(Math.abs(dAz))}°`);
  if (Math.abs(dAlt) >= GUIDE_MIN_DEG) parts.push(`${dAlt > 0 ? "위" : "아래"}로 ${Math.round(Math.abs(dAlt))}°`);
  return parts.length ? parts.join(" · ") : "거의 다 왔어요";
}

// 방위 차이 (목표 − 지금, −180~180)
export const azDelta = (targetAz, nowAz) => wrap180(targetAz - nowAz);

// 화면 투영 — 가리키는 방향을 화면 가운데로, 세로 화각 vfov. 뒤쪽이거나 화면 밖이면 null
export function project(basis, v, { width, height, vfov = VFOV }) {
  const z = dot(v, basis.forward);
  if (z <= 0) return null;
  const F = (height / 2) / Math.tan((vfov / 2) * DEG);
  const x = width / 2 + (dot(v, basis.right) / z) * F, y = height / 2 - (dot(v, basis.up) / z) * F;
  return x < 0 || x > width || y < 0 || y > height ? null : { x, y };
}

// 정렬 판정 (이력 현상) — 8° 안에 들어오면 near, 8° 안에 이어서 500ms 머물면 aligned. 12° 밖으로 나가야 far로 돌아간다.
// near 동안 8°~12°로 벗어나면 머무름 시간을 다시 센다(since: null) — 8° 안에 있던 시간만 센다.
// fired는 aligned로 바뀐 그 한 번만 true (소리 · 진동 · 연출을 한 번만)
export function alignStep(state, sep, nowMs) {
  const s = state ?? { phase: "far", since: null, fired: false };
  if (sep > ALIGN_EXIT) return { phase: "far", since: null, fired: false };
  if (s.phase === "aligned") return { phase: "aligned", since: s.since, fired: false };
  const inside = sep <= ALIGN_ENTER;
  if (s.phase === "near") {
    if (!inside) return { phase: "near", since: null, fired: false };
    const since = s.since ?? nowMs;
    if (nowMs - since >= ALIGN_DWELL_MS) return { phase: "aligned", since: nowMs, fired: true };
    return { phase: "near", since, fired: false };
  }
  return inside ? { phase: "near", since: nowMs, fired: false } : { phase: "far", since: null, fired: false };
}

// 자기 편각 (도, 동편 +) — 한국 · 일본 주변(위도 30~46°, 경도 122~146°)만 격자 값을 쌍선형 보간한다. 밖이면 null
// 출처: NOAA NCEI 「Magnetic Field Calculators」 WMM-2025, 2026-10-27 기준 (격자 4° × 6°, 소수 첫째 자리)
const DECL_LATS = [30, 34, 38, 42, 46], DECL_LONS = [122, 128, 134, 140, 146];
const DECL_GRID = [
  [-6.3, -6.9, -6.8, -6.0, -4.7],
  [-7.4, -8.1, -8.1, -7.3, -6.0],
  [-8.4, -9.2, -9.3, -8.6, -7.4],
  [-9.5, -10.4, -10.5, -9.9, -8.6],
  [-10.7, -11.6, -11.7, -11.0, -9.8],
];
export function declinationDeg(lat, lon) {
  const at = (axis, v) => {
    if (v < axis[0] || v > axis[axis.length - 1]) return null;
    const i = Math.min(axis.length - 2, axis.findIndex((x, j) => v <= axis[j + 1]));
    return { i, t: (v - axis[i]) / (axis[i + 1] - axis[i]) };
  };
  const a = at(DECL_LATS, lat), b = at(DECL_LONS, lon);
  if (!a || !b) return null;
  const g = DECL_GRID;
  const top = g[a.i][b.i] * (1 - b.t) + g[a.i][b.i + 1] * b.t;
  const bottom = g[a.i + 1][b.i] * (1 - b.t) + g[a.i + 1][b.i + 1] * b.t;
  return top * (1 - a.t) + bottom * a.t;
}

// 팔을 뻗은 주먹 하나는 약 10° — "주먹 4개"
export function fistsText(altDeg) {
  const n = Math.round(altDeg / 10);
  return n < 1 ? "지평선 바로 위" : `주먹 ${n}개`;
}

// 정렬했을 때의 한 줄 — "지금 눈에 닿는 이 빛은 약 25년 전에 떠났습니다"
export function lightLine(km) {
  return km > 0 ? `지금 눈에 닿는 이 빛은 ${lightTime(km)} 전에 떠났습니다` : "이 빛이 떠난 때는 아직 확인되지 않았어요";
}

// 천체에 맞춘 한 줄 — 우리 은하 · 궁수자리 A*는 눈에 닿는 한 점의 빛이 아니다. 그 밖은 lightLine
//   우리 은하: 위키백과 「우리 은하」 '지구에서 보이는 형태' · 궁수자리 A*: Wikidata 전파원, 위키백과 가시광선 소광
const MILKY_WAY = "Q321";   // facts.js MILKY_WAY_ID와 같은 값 (이 모듈은 astro.js 말고는 기대지 않는다)
export function lightNoteFor({ id = null, group = null, km = null } = {}) {
  if (id === MILKY_WAY) return "은하수는 많은 별의 빛이 모인 띠예요 · 은하 중심부가 있는 궁수자리 방향에서 가장 밝아요";
  if (group === "milky_way" && km > 0) return `이 방향에서 오는 전파는 ${lightTime(km)} 전에 떠났어요 · 가시광선은 먼지에 가려 보이지 않아요`;
  return lightLine(km);
}

// ── 달의 위상 원반 (가리키기 화면의 기준점) ──
// 화면 좌표는 캔버스 규칙: x 오른쪽 · y 아래쪽, 각도는 라디안(x축 0, 시계 방향 +)

// 달에서 태양 쪽 — 화면에서 밝은 쪽이 향하는 각도.
//   태양이 화면 앞에 있으면(sunPx) 달 화면 좌표 → 태양 화면 좌표의 2D 방향.
//   없으면(등 뒤 · 화면 옆) 달 자리에서 태양 쪽으로 가는 대원의 접선을 화면에 투영한다 — 투영이 대원을 직선으로 옮기므로 앞의 방법과 같은 방향
export function moonLitAngle({ moonPx = null, sunPx = null, basis, moonEnu, sunEnu }) {
  if (moonPx && sunPx && (sunPx.x !== moonPx.x || sunPx.y !== moonPx.y)) return Math.atan2(sunPx.y - moonPx.y, sunPx.x - moonPx.x);
  const t = sub(sunEnu, scale(moonEnu, dot(moonEnu, sunEnu)));                 // 달 자리의 접선 — 태양 쪽
  const z = dot(moonEnu, basis.forward), tz = dot(t, basis.forward);
  if (Math.abs(z) < 1e-9) return Math.atan2(-dot(t, basis.up), dot(t, basis.right));
  const dx = (dot(t, basis.right) * z - dot(moonEnu, basis.right) * tz) / (z * z);
  const dy = -(dot(t, basis.up) * z - dot(moonEnu, basis.up) * tz) / (z * z);
  return Math.atan2(dy, dx);
}

// 밝은 부분의 모양 — 태양 쪽 반원(가장자리) + 명암 경계 타원(가로 반지름 r·|2·illum − 1| = r·|cos 위상각|).
//   볼록(illum > 0.5)이면 경계가 어두운 쪽으로 불룩하고, 초승 · 그믐(< 0.5)이면 밝은 쪽으로 파고든다
export function moonPhaseShape(illum) {
  const f = Math.max(0, Math.min(1, Number(illum) || 0));
  return { k: Math.abs(2 * f - 1), gibbous: f > 0.5 };
}

// 밝은 부분의 다각형 — 중심 (0, 0), 반지름 r, 밝은 쪽이 angle을 향한다. 꼭짓점 [x, y] 배열 (가장자리 n개 + 경계 n개)
export function moonLitPath(illum, angle, r = 1, n = 24) {
  const { k, gibbous } = moonPhaseShape(illum);
  const c = Math.cos(angle), s = Math.sin(angle);
  const put = (x, y) => [x * c - y * s, x * s + y * c];
  const pts = [];
  // 가장자리 — 태양 쪽 반원 (위 −90° → 0° → 아래 90°, 회전 전 기준)
  for (let i = 0; i <= n; i++) {
    const a = -Math.PI / 2 + (Math.PI * i) / n;
    pts.push(put(r * Math.cos(a), r * Math.sin(a)));
  }
  // 경계 — 아래에서 위로. 볼록이면 x < 0 쪽으로, 초승이면 x > 0 쪽으로
  for (let i = 1; i < n; i++) {
    const a = Math.PI / 2 - (Math.PI * i) / n;
    const x = k * r * Math.cos(a) * (gibbous ? -1 : 1);
    pts.push(put(x, r * Math.sin(a)));
  }
  return pts;
}
