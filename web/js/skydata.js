// 하늘 데이터 — 실제 별 · 성운 · 은하수 파일 해석과 계산. Three.js에 의존하지 않는다 (node로 시험).
//
// 파일 형식은 서버 vasthorizon/data/sky_catalog.py 와 같다.
//   stars_*.bin  "VHS1" + 개수 uint32 + 레코드 12바이트 [hip uint32, ra uint16, dec int16, mag×100 int16, bv×1000 int16]
//   milkyway.bin "VHM1" + 너비 uint16 + 높이 uint16 + 밝기 uint8[] (위쪽 행이 북쪽, 왼쪽 열이 적경 0도)

import { altAz, altAzToScene, radecToEq } from "./astro.js";

const DEG = Math.PI / 180;

export function decodeStars(buffer) {
  const view = new DataView(buffer);
  const magic = String.fromCharCode(...new Uint8Array(buffer, 0, 4));
  if (magic !== "VHS1") throw new Error("별 파일 형식이 아닙니다");
  const count = view.getUint32(4, true);
  const hip = new Uint32Array(count), ra = new Float32Array(count), dec = new Float32Array(count);
  const mag = new Float32Array(count), bv = new Float32Array(count);
  for (let i = 0, o = 8; i < count; i++, o += 12) {
    hip[i] = view.getUint32(o, true);
    ra[i] = (view.getUint16(o + 4, true) / 65536) * 360;
    dec[i] = (view.getInt16(o + 6, true) / 32767) * 90;
    mag[i] = view.getInt16(o + 8, true) / 100;
    bv[i] = view.getInt16(o + 10, true) / 1000;
  }
  return { count, hip, ra, dec, mag, bv };
}

export function decodeMilkyway(buffer) {
  const view = new DataView(buffer);
  const magic = String.fromCharCode(...new Uint8Array(buffer, 0, 4));
  if (magic !== "VHM1") throw new Error("은하수 파일 형식이 아닙니다");
  const width = view.getUint16(4, true), height = view.getUint16(6, true);
  return { width, height, data: new Uint8Array(buffer, 8, width * height) };
}

// 화각(도) → 보이는 한계 등급. 75도(첫 화면) 6등급 · 30도 8등급 · 5도 12등급 — 확대할수록 어두운 별이 나타난다
export const LIMIT_MIN = 5.5, LIMIT_MAX = 12.5;
export function limitingMag(fovDeg) {
  const m = 6 + 1.52 * Math.log2(75 / Math.max(fovDeg, 0.1));
  return Math.max(LIMIT_MIN, Math.min(LIMIT_MAX, m));
}

// 적도 단위 벡터 → 지평(화면) 단위 벡터 회전 행렬 (행 우선 9개). 위도 · 지방 항성시마다 한 번 계산해 GPU에 넘긴다.
// 회전이므로 적도 좌표계의 세 축이 어디로 가는지만 구하면 된다 (astro.altAz와 같은 결과).
export function eqToHorizonMatrix(latDeg, lstDeg) {
  const col = ([ra, dec]) => {
    const { alt, az } = altAz(ra, dec, latDeg, lstDeg);
    return altAzToScene(alt, az);
  };
  const [x, y, z] = [col([0, 0]), col([90, 0]), col([0, 90])];
  return [x[0], y[0], z[0], x[1], y[1], z[1], x[2], y[2], z[2]];
}

// 우주 지도는 적도 좌표를 그대로 쓴다 (astro.eqToScene: [x, z, −y])
export const EQ_TO_MAP = [1, 0, 0, 0, 0, 1, 0, -1, 0];

export function applyMatrix(m, [x, y, z]) {
  return [m[0] * x + m[1] * y + m[2] * z, m[3] * x + m[4] * y + m[5] * z, m[6] * x + m[7] * y + m[8] * z];
}

// 회전의 역 = 전치
export function transpose(m) {
  return [m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8]];
}

// ── 하늘 방향 격자 — 누른 곳에서 가장 가까운 별 찾기 (11만 개를 모두 보지 않는다) ──

export class SkyGrid {
  constructor(cellDeg = 2) {
    this.cell = cellDeg;
    this.cols = Math.round(360 / cellDeg);
    this.rows = Math.round(180 / cellDeg);
    this.cells = new Map();
  }

  key(ra, dec) {
    const r = Math.min(this.rows - 1, Math.max(0, Math.floor((dec + 90) / this.cell)));
    const c = ((Math.floor(ra / this.cell) % this.cols) + this.cols) % this.cols;
    return r * this.cols + c;
  }

  // entries: 같은 길이의 ra · dec 배열과 묶어 둘 값(번호)
  add(ra, dec, ref) {
    const k = this.key(ra, dec);
    let list = this.cells.get(k);
    if (!list) this.cells.set(k, (list = []));
    list.push(ref);
  }

  // (ra, dec) 주변 radiusDeg 안의 후보 번호들
  near(ra, dec, radiusDeg) {
    const out = [];
    const r0 = Math.max(0, Math.floor((dec - radiusDeg + 90) / this.cell));
    const r1 = Math.min(this.rows - 1, Math.floor((dec + radiusDeg + 90) / this.cell));
    const c0 = Math.floor(ra / this.cell);
    for (let r = r0; r <= r1; r++) {
      // 그 행에서 극에 가장 가까운 적위 — 적경 1도의 폭이 cos(적위)로 좁아진다
      const edge = Math.max(Math.abs(r * this.cell - 90), Math.abs((r + 1) * this.cell - 90));
      const cos = Math.cos(Math.min(90, edge) * DEG);
      const span = cos < 0.05 ? this.cols : Math.ceil(radiusDeg / cos / this.cell) + 1;
      const cols = new Set();
      for (let dc = -Math.min(span, this.cols); dc <= Math.min(span, this.cols); dc++) {
        cols.add((((c0 + dc) % this.cols) + this.cols) % this.cols);
      }
      for (const c of cols) {
        const list = this.cells.get(r * this.cols + c);
        if (list) for (const ref of list) out.push(ref);
      }
    }
    return out;
  }
}

export function angularDeg(ra1, dec1, ra2, dec2) {
  const c = Math.sin(dec1 * DEG) * Math.sin(dec2 * DEG) + Math.cos(dec1 * DEG) * Math.cos(dec2 * DEG) * Math.cos((ra1 - ra2) * DEG);
  return Math.acos(Math.max(-1, Math.min(1, c))) / DEG;
}

// 별 고르기 — 반경 안에서 '가까움'과 '밝음'을 함께 본다 (어두운 별 옆의 밝은 별을 누르기 쉽게)
export function pickStar(stars, grid, ra, dec, radiusDeg, limit) {
  let best = -1, bestScore = Infinity;
  for (const i of grid.near(ra, dec, radiusDeg)) {
    if (stars.mag[i] > limit) continue;
    const d = angularDeg(ra, dec, stars.ra[i], stars.dec[i]);
    if (d > radiusDeg) continue;
    const score = d / radiusDeg - 0.12 * (limit - stars.mag[i]);
    if (score < bestScore) { bestScore = score; best = i; }
  }
  return best;
}

// 누른 방향(ra, dec)에서 고를 천체 — 별 묶음들에서 먼저, 없으면 성운 · 성단 · 은하.
// 거리는 모두 구면 각거리(angularDeg)로 잰다 — 적경 0/360도 경계와 극 근처에서도 같은 기준 (12-1 리뷰 P2)
//   parts: [{ stars, grid }]   dsos: { rows, grid } | null   dsoVisible(i): 지금 화면에 그려지는가
// 반환: { type: "star", part, index, away } | { type: "dso", index, away } | null   (away: 도)
export function pickSky(parts, dsos, ra, dec, radiusDeg, limit, dsoVisible = () => true) {
  let best = null;
  parts.forEach(({ stars, grid }, part) => {
    const i = pickStar(stars, grid, ra, dec, radiusDeg, limit);
    if (i < 0 || (best && parts[best.part].stars.mag[best.index] <= stars.mag[i])) return;   // 묶음끼리는 더 밝은 별
    best = { type: "star", part, index: i, away: angularDeg(ra, dec, stars.ra[i], stars.dec[i]) };
  });
  if (best || !dsos) return best;
  for (const i of dsos.grid.near(ra, dec, radiusDeg * 3)) {
    if (!dsoVisible(i)) continue;
    const [, , dra, ddec, , major] = dsos.rows[i];
    const away = angularDeg(ra, dec, dra, ddec);
    if (away > Math.max(radiusDeg, (major ?? 0) / 120)) continue;             // 반경 안, 또는 그 천체의 크기 안
    if (!best || away < best.away) best = { type: "dso", index: i, away };
  }
  return best;
}

// 화면 고르기 점수 — 작을수록 우선. maxPx 안의 점 대상은 거리 그대로,
// 화면에서 크게 보이는 원반(pickRadius > maxPx) 안이면 음수라 원반 뒤쪽 별 · 이름보다 앞선다. 고를 수 없으면 null (12-2 리뷰 P2)
export function pickScore(d, maxPx, pickRadius = 0) {
  if (pickRadius > maxPx && d <= pickRadius) return d / pickRadius - 1;
  return d <= maxPx ? d : null;
}

// 색지수(B−V) → 별빛 색 (파랑 → 흰색 → 노랑 → 주황)
// 분광형 → 별의 색 — 분광형 첫 글자(O B A F G K M)의 대표 색지수로. 모르면 해와 비슷한 흰빛
const SPECTRAL_BV = { O: -0.32, B: -0.16, A: 0.05, F: 0.42, G: 0.66, K: 1.12, M: 1.6 };
export function spectralColor(spectral) {
  const letter = String(spectral ?? "").trim().toUpperCase().match(/^[OBAFGKM]/)?.[0];
  return starColor(letter ? SPECTRAL_BV[letter] : 0.6);
}

export function starColor(bv) {
  const stops = [[-0.4, [0.62, 0.72, 1]], [0, [0.85, 0.9, 1]], [0.6, [1, 0.97, 0.9]], [1.2, [1, 0.82, 0.6]], [2, [1, 0.65, 0.45]]];
  if (bv <= stops[0][0]) return stops[0][1];
  for (let i = 1; i < stops.length; i++) {
    if (bv <= stops[i][0]) {
      const [b0, c0] = stops[i - 1], [b1, c1] = stops[i];
      const k = (bv - b0) / (b1 - b0);
      return c0.map((v, j) => v + (c1[j] - v) * k);
    }
  }
  return stops[stops.length - 1][1];
}

// 첫 번째 빛 — 지금 하늘에 떠 있는 밝은 천체 중 아직 알아가지 않은 것 하나 (첫 하늘의 '첫 번째 빛 만나기')
//   candidates: [{ id, name, mag, alt }] — 하늘의 달 · 행성 · 카탈로그 별 · 메시에 천체 (alt: 고도, 도)
//   1) id가 있고 아직 알아가지 않은 것만. 태양은 뺀다 (맨눈으로 바라보면 안 된다)
//   2) 지평선 위 15도 이상을 먼저 — 낮게 뜬 빛은 건물 · 대기에 가려 실제로 찾기 어렵다. 없으면 지평선 위 전체에서
//   3) 그 안에서 겉보기 등급이 가장 밝은 것 (달 → 금성 · 목성 → 시리우스 …). 등급을 모르면 맨 뒤, 같으면 이름순
export function pickFirstLight(candidates, isKnown = () => false, minAltDeg = 15) {
  const open = candidates.filter((c) => c?.id && c.kind !== "sun" && c.alt > 0 && !isKnown(c.id));
  const mag = (c) => (Number.isFinite(Number(c.mag)) && c.mag !== null ? Number(c.mag) : Infinity);
  const order = (a, b) => mag(a) - mag(b) || String(a.name).localeCompare(String(b.name), "ko");
  const high = open.filter((c) => c.alt >= minAltDeg);
  return (high.length ? high : open).sort(order)[0] ?? null;
}

// 사람이 읽는 별 색 — 툴팁용
export function colorWord(bv) {
  if (bv < 0) return "푸른 흰색";
  if (bv < 0.3) return "흰색";
  if (bv < 0.8) return "노란 흰색";
  if (bv < 1.4) return "주황색";
  return "붉은색";
}

// 고개를 돌릴 방향 (적도 단위 벡터) — 지평선 위아래와 상관없이. 별자리는 선 별들의 중심, 그다음 카탈로그(별 · 메시에, eq)
// → 담은 별(observed: id → { ra, dec }) → 고른 항목의 적경 · 적위(sel) 순. 모르면 null (하늘 보기 lookAt의 anywhere — 카메라를 그대로 둔다)
// 태양 · 달 · 행성 · 왜행성처럼 그날 움직이는 천체는 sky.js가 따로 계산한다
export function lookEq(itemId, { constellations = [], catalog = [], observed = null, sel = null } = {}) {
  const unit = (v) => {
    const n = Math.hypot(...v);
    return n > 1e-9 ? v.map((x) => x / n) : null;
  };
  const con = constellations.find((c) => c.item_id === itemId);
  if (con?.stars?.length) {
    return unit(con.stars.reduce((acc, s) => radecToEq(s.ra_deg, s.dec_deg).map((x, i) => acc[i] + x), [0, 0, 0]));
  }
  const p = catalog.find((x) => x.id === itemId);
  if (p?.eq) return unit(p.eq);
  const v = observed?.get(itemId);
  if (v?.ra != null && v?.dec != null) return radecToEq(v.ra, v.dec);
  if (sel?.ra_deg != null && sel?.dec_deg != null) return radecToEq(sel.ra_deg, sel.dec_deg);
  return null;
}

export { radecToEq };
