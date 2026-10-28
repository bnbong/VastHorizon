// 오늘 밤 내 빛 — 내 세계에 담은 빛 가운데 오늘 밤 이 자리에서 볼 수 있는 것과 가장 좋은 시간대.
// DOM · Three.js에 의존하지 않는다 (node로 시험 — tests/js/tonight.test.mjs).
//
// - 위치: 담은 기록의 적경 · 적위(별 · 메시에), 별자리 모양 데이터(별자리), ephemeris.solarSystem(태양 · 달 · 행성),
//   solarbodies의 모행성(갈릴레이 위성 · 타이탄) · 태양 중심 위치(왜행성 · 소행성 · 혜성)
// - 밝기: 겉보기 등급 → 맨눈 · 불빛이 적은 곳에서 맨눈 · 쌍안경 · 망원경 (메시에 천체는 퍼진 빛이라 더 엄격하게)
// - 밤: 태양 고도를 브라우저에서 계산한다. 밝은 천체일수록 덜 어두운 하늘에서도 보인다 (−6° · −12° · −18°)
// - 시간대: 지금부터 다음 새벽까지 10분 간격으로 고도를 훑어, 가장 높이 뜨는 때 앞뒤 1시간을 권한다

import { altAz, compass, localSiderealDeg, radecToEq, eqToRadec } from "./astro.js";
import { BODIES, centuriesJ2000, heliocentric, solarSystem } from "./ephemeris.js";
import { bodyInfo, epochAge, MOON_ORBITS, skyFromHeliocentric } from "./solarbodies.js";
import { MILKY_WAY_ID } from "./facts.js";

const DEG = Math.PI / 180;
const MIN_MS = 60_000;
export const MIN_ALT = 10, GOOD_ALT = 25, STEP_MIN = 10, BEST_HALF_MS = 3600_000, STEADY_DEG = 5, ZENITH_DEG = 75;
export const SUN_LIMIT = { bright: -6, normal: -12, faint: -18 };
export const SUNSET_DEG = -0.833;                       // 일몰 · 일출 — 태양 윗가장자리 + 대기 굴절
export const TIER_LIMIT = { star: { eye: 5.0, darkEye: 6.0, binocular: 9.0 }, messier: { eye: 2.0, darkEye: 4.5, binocular: 9.5 } };
export const COUNTED_TIERS = ["eye", "dark-eye", "binocular"];
export const TIER_LABEL = { eye: "맨눈", "dark-eye": "불빛이 적은 곳에서 맨눈", binocular: "쌍안경", telescope: "망원경" };
const SCAN_HOURS = 36;
const FIGURE_SHARE = 0.6;                               // 별자리 — 모양의 별 60% 이상이 고도 10° 위면 보인다
const MOON_NEAR_DEG = 15;
const BRIGHT_MAG = 1.5;
const SATELLITE_REASON = "인공위성은 지나가는 시각이 날마다 달라 아직 안내하지 못해요";
const NO_PLACE_REASON = "하늘에서의 위치를 아직 계산하지 못해요";
// 갈릴레이 위성은 쌍안경으로 모행성 곁의 점으로 보이고, 타이탄은 망원경이 있어야 한다
const MOON_TIER = { jupiter: "binocular", saturn: "telescope" };
// 그 밖의 위성 — 모행성 곁에 붙은 작은 점이라 위치를 계산하지 않는다
const SMALL_MOONS = new Set(["phobos", "deimos", "enceladus", "triton", "charon"]);
const SMALL_MOON_REASON = "모행성 곁의 작은 위성이라 큰 망원경이 있어야 보여요";
// 궁수자리 A* — 위키백과 「궁수자리 A*」: 가시광선 대역에서 먼지와 가스에 의해 +25 등급까지 소광되어 관측할 수 없다
const BLACK_HOLE_REASON = "가시광선은 먼지와 가스에 가려 보이지 않아요 · 전파와 적외선으로 관측해요";

// 눈으로는 볼 수 없는 빛의 이유 — 우리 은하 그룹에서 우리 은하가 아닌 것(궁수자리 A*). 그 밖은 null.
// 서랍의 '오늘 두 눈으로 봤어요'를 두지 않는 근거 (main.js seenSlotHtml)
export function invisibleReason(v) {
  return v?.group === "milky_way" && v.id !== MILKY_WAY_ID ? BLACK_HOLE_REASON : null;
}

// ── 태양과 밤 ────────────────────────────────────────────────────────────

// 태양 고도 (도) — 행성 전부를 계산하지 않도록 지구의 태양 중심 위치만 뒤집는다 (solarSystem의 태양과 같은 값)
export function sunAltDeg(date, lat, lon) {
  const earth = heliocentric("earth", centuriesJ2000(date));
  const { ra, dec } = eqToRadec(earth.map((v) => -v));
  return altAz(ra, dec, lat, localSiderealDeg(date, lon)).alt;
}

// f(date)가 threshold를 지나는 시각 — 두 끝의 부호가 같으면 null. 이분법으로 1분 정밀도까지 (가운데 값)
export function crossing(fromMs, toMs, f, threshold) {
  let a = fromMs, b = toMs;
  const fa = f(new Date(a)) - threshold, fb = f(new Date(b)) - threshold;
  if (fa === 0) return a;
  if (Math.sign(fa) === Math.sign(fb)) return null;
  let sa = Math.sign(fa);
  while (b - a > MIN_MS) {
    const m = (a + b) / 2, fm = f(new Date(m)) - threshold;
    if (Math.sign(fm) === sa) a = m;
    else b = m;
  }
  return Math.round((a + b) / 2);
}

// f가 threshold를 지나는 다음 시각 (from부터 hours 안, 10분 간격으로 찾고 그 안에서 좁힌다). dir: "down" · "up" · 생략하면 아무쪽
function nextCrossing(fromMs, hours, f, threshold, dir) {
  const step = STEP_MIN * MIN_MS, end = fromMs + hours * 3600_000;
  let prev = f(new Date(fromMs)) - threshold;
  for (let t = fromMs + step; t <= end; t += step) {
    const cur = f(new Date(t)) - threshold;
    const down = prev >= 0 && cur < 0, up = prev < 0 && cur >= 0;
    if ((down && dir !== "up") || (up && dir !== "down")) return crossing(t - step, t, f, threshold);
    prev = cur;
  }
  return null;
}

// 관측 밤 하나 — 해가 진 동안(일몰~일출). 지금이 밤이면 그 밤(새벽이면 남은 시간), 낮이면 다가오는 밤.
// 모든 박명 기준 · 일몰 · 일출을 이 밤 하나에 묶는다 (새벽에 밝은 빛은 '지금 새벽', 어두운 빛은 '다음 저녁'으로 섞이지 않게)
//   { start, end(일출), sunset(이 밤의 일몰 — 이미 졌으면 지난 일몰), daytimeNow(해가 떠 있음), dawn(밤의 후반 · 해가 올라오는 중) } · 해가 지지 않으면 null
export function observingNight(nowMs, place) {
  const sun = (d) => sunAltDeg(d, place.lat, place.lon);
  const alt = sun(new Date(nowMs));
  const dark = alt < SUNSET_DEG;
  const start = dark ? nowMs : nextCrossing(nowMs, SCAN_HOURS, sun, SUNSET_DEG, "down");
  if (start == null) return null;
  const end = nextCrossing(start, SCAN_HOURS, sun, SUNSET_DEG, "up") ?? start + 24 * 3600_000;
  const sunset = dark ? nextCrossing(nowMs - 24 * 3600_000, 24, sun, SUNSET_DEG, "down") : start;
  const dawn = dark && sun(new Date(nowMs + STEP_MIN * MIN_MS)) > alt;
  return { start, end, sunset, daytimeNow: !dark, dawn };
}

// 관측 밤 안에서 태양이 기준(limitDeg)보다 낮은 구간 — { start, end, sunset, sunrise, daytimeNow, dawn }.
// 이 밤에 그만큼 어두워지지 않으면(이미 새벽이 밝아 오는 중) start · end가 null
export function nightWindow(nowMs, place, limitDeg, obs = observingNight(nowMs, place)) {
  if (!obs) return { start: null, end: null, sunset: null, sunrise: null, daytimeNow: true, dawn: false };
  const sun = (d) => sunAltDeg(d, place.lat, place.lon);
  const hours = (from) => (obs.end - from) / 3600_000 + STEP_MIN / 60;
  let start = sun(new Date(obs.start)) < limitDeg ? obs.start : nextCrossing(obs.start, hours(obs.start), sun, limitDeg, "down");
  if (start != null && start >= obs.end) start = null;
  const end = start == null ? null : Math.min(obs.end, nextCrossing(start, hours(start), sun, limitDeg, "up") ?? obs.end);
  return { start, end, sunset: obs.sunset, sunrise: obs.end, daytimeNow: obs.daytimeNow, dawn: obs.dawn };
}

// 위치의 시간대 — 기본 위치(서울)는 Asia/Seoul, 받은 위치('내 위치')는 이 기기의 시간대. place.timeZone이 있으면 그것
export const SEOUL_TZ = "Asia/Seoul";
export function zoneOf(place) {
  if (place?.timeZone) return place.timeZone;
  if (!place || place.name === "서울") return SEOUL_TZ;
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || SEOUL_TZ; } catch { return SEOUL_TZ; }
}

// ── 대상 ─────────────────────────────────────────────────────────────────

// 밝기 등급 → 보는 방법. 등급을 모르면 쌍안경
export function tierOf({ group, mag }) {
  if (mag == null || !Number.isFinite(Number(mag))) return "binocular";
  const m = Number(mag), lim = group === "messier" ? TIER_LIMIT.messier : TIER_LIMIT.star;
  return m <= lim.eye ? "eye" : m <= lim.darkEye ? "dark-eye" : m <= lim.binocular ? "binocular" : "telescope";
}

// 하늘이 얼마나 어두워야 하는가 — 달 · 밝은 행성(수성~토성) · 1.5등급보다 밝은 별은 시민박명, 나머지 맨눈은 항해박명, 그 밖은 천문박명
const BRIGHT_BODIES = new Set(["moon", "mercury", "venus", "mars", "jupiter", "saturn"]);   // 천왕성 · 해왕성은 등급대로
export function sunLimitOf(target) {
  if (target.kind === "body" && !target.parent && BRIGHT_BODIES.has(target.body)) return "bright";
  if (target.mag != null && target.mag <= BRIGHT_MAG && target.tier === "eye") return "bright";
  return target.tier === "eye" ? "normal" : "faint";
}

const BODY_BY_NAME = new Map(Object.entries(BODIES).map(([key, b]) => [b.name, key]));

// 담은 기록 → 추적 대상. 지구는 빼고, 태양은 언제나 뺀다
//   ctx: { points: Map(id → 지도 점), figures: Map(item_id → { stars }), starMag(hip), earthId }
export function targetsOf(visited, { points = new Map(), figures = new Map(), starMag = () => null, earthId = "Q2" } = {}) {
  const out = [];
  for (const v of visited ?? []) {
    if (!v?.id || v.id === earthId) continue;
    const base = { id: v.id, name: v.name, group: v.group ?? null, km: v.km ?? null };
    const point = points.get(v.id);
    const known = (x) => (x == null || !Number.isFinite(Number(x)) ? null : Number(x));
    const info = bodyInfo(v.id);
    const bodyKey = info?.planet ? info.key : BODY_BY_NAME.get(v.name);
    if (bodyKey === "sun") continue;
    let t;
    if (bodyKey) {
      t = { ...base, kind: "body", body: bodyKey, mag: BODIES[bodyKey].mag };
      t.tier = tierOf({ group: "solar_system", mag: t.mag });
    } else if (MOON_ORBITS[v.id]) {
      const parent = MOON_ORBITS[v.id].parent;
      t = { ...base, kind: "body", body: parent, parent, mag: null, tier: MOON_TIER[parent] ?? "telescope" };
    } else if (SMALL_MOONS.has(info?.key)) {
      t = { ...base, kind: "none", mag: null, tier: "never", reason: SMALL_MOON_REASON };
    } else if (v.group === "human_made") {
      t = { ...base, kind: "none", mag: null, tier: "never", reason: SATELLITE_REASON };
    } else if (v.group === "constellation") {
      const stars = (figures.get(v.id)?.stars ?? []).filter((s) => s.ra_deg != null && s.dec_deg != null);
      const mags = stars.map((s) => known(s.mag)).filter((m) => m != null);
      const mag = mags.length ? Math.min(...mags) : null;
      t = { ...base, kind: "constellation", stars: stars.map((s) => radecToEq(s.ra_deg, s.dec_deg)),
            ra: v.ra ?? null, dec: v.dec ?? null, mag, tier: mag == null ? "eye" : tierOf({ group: "star", mag }) };
      if (!stars.length && v.ra == null) t = { ...t, kind: "none", tier: "never", reason: NO_PLACE_REASON };
    } else if (v.group === "milky_way" && v.ra != null && v.dec != null) {
      // 우리 은하 — 은하 중심 방향. 위키백과 「우리 은하」: 은하수는 밝은 띠로 보이고 은하 중심부가 있는 궁수자리 방향에서 가장 밝다.
      // 등급이 없어 tierOf를 쓰지 않는다(쓰면 쌍안경). 궁수자리 A*는 가시광선으로 보이지 않는다
      const reason = invisibleReason(v);
      t = { ...base, kind: "fixed", ra: v.ra, dec: v.dec, mag: null, tier: reason ? "never" : "dark-eye", ...(reason ? { reason } : {}) };
    } else if (v.ra != null && v.dec != null) {
      const hip = String(v.id).startsWith("hip:") ? Number(String(v.id).slice(4)) : null;
      const mag = known(v.mag) ?? known(point?.mag) ?? (hip != null ? known(starMag(hip)) : null);
      t = { ...base, kind: "fixed", ra: v.ra, dec: v.dec, mag, tier: tierOf({ group: v.group, mag }) };
    } else if (point?.position_au && point?.epoch) {
      t = { ...base, kind: "helio", positionAu: point.position_au, epoch: point.epoch, mag: null, tier: "telescope" };
    } else {
      t = { ...base, kind: "none", mag: null, tier: "never",
            reason: info && !info.planet ? "이 천체는 하늘에서의 위치를 아직 계산하지 않아요" : NO_PLACE_REASON };
    }
    t.sunLimit = sunLimitOf(t);
    out.push(t);
  }
  return out;
}

// ── 위치 ─────────────────────────────────────────────────────────────────

// 같은 시각의 태양 · 달 · 행성은 한 번만 계산해 모든 대상이 함께 쓴다
function systemAt(date, cache) {
  const key = date.getTime();
  if (!cache) return solarSystem(date);
  if (!cache.has(key)) cache.set(key, solarSystem(date));
  return cache.get(key);
}

// 그 시각의 적경 · 적위 { ra, dec } — 계산할 수 없으면 null
export function positionAt(target, date, cache = null) {
  switch (target.kind) {
    case "fixed": return { ra: target.ra, dec: target.dec };
    case "body": {
      const b = systemAt(date, cache).find((x) => x.key === target.body);
      return b ? { ra: b.ra, dec: b.dec, distanceKm: b.distanceKm } : null;
    }
    case "helio": {
      if (epochAge(target.epoch, date).hidden) return null;   // 1년 넘은 위치는 쓰지 않는다
      const s = skyFromHeliocentric(target.positionAu, date);
      return { ra: s.ra, dec: s.dec };
    }
    case "constellation": {
      if (!target.stars?.length) return target.ra != null ? { ra: target.ra, dec: target.dec } : null;
      // 별 단위 벡터의 평균 방향 — 하늘의 별자리 이름표 자리와 같은 방식 (sky.js)
      const sum = target.stars.reduce((s, v) => [s[0] + v[0], s[1] + v[1], s[2] + v[2]], [0, 0, 0]);
      const n = Math.hypot(...sum);
      return n ? eqToRadec(sum.map((x) => x / n)) : null;
    }
    default: return null;
  }
}

// 그 시각의 고도 · 방위 · 보이는가 (지평선 위 10°). 별자리는 모양의 별 60% 이상이 10° 위일 때 보인다
export function altAzOf(target, date, place, cache = null, lst = localSiderealDeg(date, place.lon)) {
  const pos = positionAt(target, date, cache);
  if (!pos) return null;
  const { alt, az } = altAz(pos.ra, pos.dec, place.lat, lst);
  if (target.kind === "constellation" && target.stars?.length) {
    const high = target.stars.filter((v) => {
      const { ra, dec } = eqToRadec(v);
      return altAz(ra, dec, place.lat, lst).alt >= MIN_ALT;
    }).length;
    return { alt, az, up: high / target.stars.length >= FIGURE_SHARE };
  }
  return { alt, az, up: alt >= MIN_ALT };
}

// ── 시각 표기 ────────────────────────────────────────────────────────────

const clockFormats = new Map();
function clockOf(ms, timeZone) {
  const key = timeZone ?? "";
  if (!clockFormats.has(key)) {
    clockFormats.set(key, new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "numeric", hourCycle: "h23",
                                                              ...(timeZone ? { timeZone } : {}) }));
  }
  const parts = clockFormats.get(key).formatToParts(new Date(ms));
  const get = (type) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return { h: get("hour") % 24, m: get("minute") };
}

// "21시" · "21시 30분" — 그 위치의 시간대(zoneOf)로. timeZone이 없으면 이 기기의 시간대
export function hourText(ms, { timeZone } = {}) {
  const { h, m } = clockOf(ms, timeZone);
  return m ? `${h}시 ${m}분` : `${h}시`;
}

// 30분 단위로 시작은 내림, 끝은 올림 — "21시~23시" · "21시 30분~22시"
export function rangeText(fromMs, toMs, { timeZone } = {}) {
  const HALF = 30 * MIN_MS;
  const floorMin = (ms) => ms - (ms % MIN_MS);
  const a = floorMin(fromMs) - (clockOf(fromMs, timeZone).m % 30) * MIN_MS;
  const bm = clockOf(toMs, timeZone).m % 30, bRaw = floorMin(toMs);
  let b = bm === 0 && bRaw === toMs ? bRaw : bRaw + (30 - bm) * MIN_MS;
  if (b <= a) b = a + HALF;
  return `${hourText(a, { timeZone })}~${hourText(b, { timeZone })}`;
}

// 방향 — "남서쪽". 머리 위 근처에서는 방위가 크게 흔들려 "머리 위"
export function directionWord(az, alt) {
  return alt >= ZENITH_DEG ? "머리 위" : `${compass(az)}쪽`;
}

// ── 대상 하나의 오늘 밤 ──────────────────────────────────────────────────

const angleBetween = (a, b) => {
  const u = radecToEq(a.ra, a.dec), v = radecToEq(b.ra, b.dec);
  return Math.acos(Math.max(-1, Math.min(1, u[0] * v[0] + u[1] * v[1] + u[2] * v[2]))) / DEG;
};

// 저녁 9시 무렵 남쪽 하늘에 높이 뜨는 달 — 서버 data/items/constellations.py evening_month 와 같은 근사식 (북반구 중위도)
export function eveningMonth(raDeg) {
  const month = ((((raDeg / 15 - 9) / 2 + 3.7) % 12) + 12) % 12;
  return Math.round(month) % 12 || 12;
}

// 표본 시각 — 범위의 시작이 지금이면 지금부터, 아니면 10분 눈금(정시 · 10분 · 20분 …)에서
function sampleTimes(night, nowMs, step) {
  if (night.start == null) return [];
  const s = step * MIN_MS;
  const out = night.start === nowMs ? [nowMs] : [];
  for (let t = Math.ceil(night.start / s) * s; t <= night.end; t += s) if (t !== nowMs || !out.length) out.push(t);
  return out;
}

// 대상 하나의 계획 — 오늘 밤 볼 수 있으면 { now, best, firstUp, lastUp, steady, evening, moonNote, sunLimit },
// 오늘 밤 내내 못 보면 { later: true, nextMonth }
//   opts: { step, cache(solarSystem 결과), nights({ bright, normal, faint } → nightWindow 결과), timeZone }
export function plan(target, place, nowMs, opts = {}) {
  const step = opts.step ?? STEP_MIN, cache = opts.cache ?? new Map();
  const limitKey = target.sunLimit ?? sunLimitOf(target);
  const limit = SUN_LIMIT[limitKey];
  const night = opts.nights?.[limitKey] ?? nightWindow(nowMs, place, limit);
  const nowDate = new Date(nowMs);
  const nowPos = altAzOf(target, nowDate, place, cache) ?? { alt: null, az: null, up: false };
  const sunNow = sunAltDeg(nowDate, place.lat, place.lon);
  const now = { alt: nowPos.alt, az: nowPos.az, up: !!nowPos.up && sunNow < limit };

  const samples = [];
  for (const t of sampleTimes(night, nowMs, step)) {
    const p = altAzOf(target, new Date(t), place, cache);
    if (p) samples.push({ at: t, ...p });
  }
  const seen = samples.filter((p) => p.up);
  const nextMonth = place.lat >= 0 ? monthOf(target, nowDate, cache) : null;
  // brightening: 이 밤에 이 대상이 바라는 만큼 어두워지지 않는다 (새벽이 밝아 오는 중)
  if (!seen.length) return { later: true, nextMonth, now, sunLimit: limitKey, brightening: night.start == null && !night.daytimeNow,
                                  setForNight: !!night.dawn };   // 새벽 — 이번 밤에는 이미 졌다 (다음 저녁은 새 관측 밤)

  // 가장 높이 뜨는 표본 (같으면 이른 것) · 그 표본을 포함하는 연속 구간과 앞뒤 1시간의 교집합
  const best = seen.reduce((a, b) => (b.alt > a.alt ? b : a));
  const i = samples.indexOf(best);
  let lo = i, hi = i;
  while (lo > 0 && samples[lo - 1].up) lo--;
  while (hi < samples.length - 1 && samples[hi + 1].up) hi++;
  const from = Math.max(samples[lo].at, best.at - BEST_HALF_MS), to = Math.min(samples[hi].at, best.at + BEST_HALF_MS);
  const alts = samples.map((p) => p.alt);
  const steady = Math.max(...alts) - Math.min(...alts) < STEADY_DEG;

  // 가장 좋은 때가 새벽(1시 이후)이면, 사람들이 주로 하늘을 보는 저녁(19~24시)에 25° 위로 보이는 때를 함께
  let evening = null;
  const bestHour = clockOf(best.at, opts.timeZone).h;
  if (!steady && bestHour >= 1 && bestHour < 12) {
    const eve = seen.filter((p) => { const h = clockOf(p.at, opts.timeZone).h; return h >= 19 && p.alt >= GOOD_ALT; });
    if (eve.length) {
      const e = eve.reduce((a, b) => (b.alt > a.alt ? b : a));
      evening = { at: e.at, alt: e.alt, az: e.az };
    }
  }

  // 달빛 — 가장 좋은 때에 밝은 달(밝은 비율 0.5 넘게)이 떠 있으면, 어두운 대상에 안내 한 줄 (시간대 계산은 그대로)
  let moonNote = false;
  if (target.tier === "dark-eye" || target.tier === "binocular") {
    const at = new Date(best.at);
    const moon = systemAt(at, cache).find((b) => b.key === "moon");
    const lst = localSiderealDeg(at, place.lon);
    if (moon && moon.illum > 0.5 && altAz(moon.ra, moon.dec, place.lat, lst).alt > 0) {
      const pos = positionAt(target, at, cache);
      moonNote = target.tier === "dark-eye" || (!!pos && angleBetween(pos, moon) < MOON_NEAR_DEG);
    }
  }

  return { now, best: { at: best.at, alt: best.alt, az: best.az, from, to },
           firstUp: seen[0].at, lastUp: seen[seen.length - 1].at, steady, evening, moonNote, sunLimit: limitKey };
}

// 다시 만날 달 — 고정된 천체는 적경으로 (북반구 근사식), 움직이는 천체는 알 수 없어 null
function monthOf(target, date, cache) {
  if (target.kind === "body" || target.kind === "helio") return null;
  const pos = positionAt(target, date, cache);
  return pos ? eveningMonth(pos.ra) : null;
}

// ── 목록 ─────────────────────────────────────────────────────────────────

// 오늘 밤 내 빛 — { place, now, night, items, later, hard, firstUp, count }
//   items: 오늘 밤 볼 수 있는 빛 (지금 보이는 것부터 고도순, 나머지는 처음 떠오르는 순)
//   later: 오늘 밤에는 볼 수 없는 빛 (다시 만날 달) · hard: 망원경이 있어야 보이거나 아직 안내하지 못하는 빛
export function tonightList({ visited, place, now, points, figures, starMag, earthId = "Q2", step = STEP_MIN, timeZone = zoneOf(place) } = {}) {
  const nowMs = now instanceof Date ? now.getTime() : Number(now);
  const obs = observingNight(nowMs, place);
  const nights = Object.fromEntries(Object.entries(SUN_LIMIT).map(([k, v]) => [k, nightWindow(nowMs, place, v, obs)]));
  const cache = new Map();
  const items = [], later = [], hard = [];
  for (const t of targetsOf(visited, { points, figures, starMag, earthId })) {
    const head = { id: t.id, name: t.name, group: t.group, tier: t.tier, mag: t.mag, km: t.km, timeZone };   // 문구 함수가 같은 시간대로 적게
    if (!COUNTED_TIERS.includes(t.tier)) { hard.push({ ...head, reason: t.reason ?? null }); continue; }
    const p = plan(t, place, nowMs, { step, cache, nights, timeZone });
    if (p.later) later.push({ ...head, nextMonth: p.nextMonth, brightening: p.brightening, setForNight: p.setForNight });
    else items.push({ ...head, ...p });
  }
  const up = items.filter((x) => x.now.up).sort((a, b) => b.now.alt - a.now.alt);
  const rest = items.filter((x) => !x.now.up).sort((a, b) => a.firstUp - b.firstUp);
  const first = rest[0] ? { id: rest[0].id, name: rest[0].name, at: rest[0].firstUp } : null;
  return { place, timeZone, now: nowMs, night: nights.normal, items: [...up, ...rest], later, hard, firstUp: first, count: items.length };
}

// ── 문구 ─────────────────────────────────────────────────────────────────

// 지금 보이면 지금의 자리, 아니면 가장 좋은 때의 자리
const shownPos = (item) => (item.now?.up ? item.now : item.best);

// 언제 — "21시~22시가 가장 좋아요" · "밤새 같은 자리"
export function whenText(item, { timeZone = item?.timeZone } = {}) {
  if (item.steady) return "밤새 같은 자리";
  const range = rangeText(item.best.from, item.best.to, { timeZone });
  return `${range}${range.endsWith("분") ? "이" : "가"} 가장 좋아요`;      // "21시~22시가" · "2시 30분~4시 30분이"
}

// 저녁 보조 문구 — "자정 전에는 23시 50분 무렵 동쪽 낮게"
export function eveningText(item, { timeZone = item?.timeZone } = {}) {
  const e = item.evening;
  if (!e) return "";
  return `자정 전에는 ${hourText(e.at, { timeZone })} 무렵 ${directionWord(e.az, e.alt)}${e.alt < 40 ? " 낮게" : ""}`;
}

// 한 줄 — "베가 · 서쪽 · 고도 41° · 21시~22시가 가장 좋아요"
export function itemLine(item, { timeZone = item?.timeZone } = {}) {
  const p = shownPos(item);
  return `${item.name} · ${directionWord(p.az, p.alt)} · 고도 ${Math.round(p.alt)}° · ${whenText(item, { timeZone })}`;
}

// 빈 상태와 낮 안내 — { key, text } (보여 줄 것이 없으면 key: null)
//   nothing: 담은 빛이 지구뿐 · all-hard: 모두 망원경 · none-tonight: 오늘 밤 내내 못 봄 · daytime: 낮에 열었음 · none-now: 지금은 지평선 아래
export function emptyState(result, { timeZone = result?.timeZone } = {}) {
  const { items = [], later = [], hard = [], night = {} } = result ?? {};
  if (!items.length && !later.length && !hard.length) {
    return { key: "nothing", text: "아직 담은 빛이 없어요. 하늘에서 빛 하나를 담으면 오늘 밤 어디를 보면 되는지 알려 드릴게요." };
  }
  if (!items.length && !later.length) {
    // 맨눈으로는 볼 수 없는 빛(tier "never" — 궁수자리 A* 등)이 섞이면 '망원경'만으로는 틀린 말이라 둘을 함께 적는다
    return { key: "all-hard", text: hard.some((x) => x.tier === "never")
      ? "담은 빛이 모두 망원경이 있어야 보이거나 맨눈으로는 볼 수 없는 빛이에요"
      : "담은 빛이 모두 망원경이 있어야 보이는 빛이에요" };
  }
  if (!items.length) {
    return { key: "none-tonight", text: night.dawn ? "새벽이 밝아 오고 있어 이번 밤에는 담은 빛을 보기 어려워요"
      : "오늘 밤에는 담은 빛이 지평선 아래나 낮 하늘에 있어요" };
  }
  if (night.daytimeNow) {
    const parts = [night.sunset ? `오늘 일몰 ${hourText(night.sunset, { timeZone })}` : null,
                   night.start ? `${hourText(ceil10(night.start), { timeZone })}부터 별이 보이기 시작해요` : null].filter(Boolean);
    return { key: "daytime", text: parts.join(" · ") };
  }
  if (!items.some((x) => x.now.up) && result.firstUp) {
    return { key: "none-now",
             text: `지금은 담은 빛이 지평선 아래에 있어요 · 가장 먼저 뜨는 것은 ${result.firstUp.name} ${hourText(result.firstUp.at, { timeZone })}` };
  }
  return { key: null, text: "" };
}

// 다시 만날 달 안내 — "안타레스는 7월 무렵 저녁 하늘에서 다시 만날 수 있어요" (남반구 · 움직이는 천체는 빈 문자열)
export function laterText(entry) {
  if (entry.brightening) return "하늘이 밝아지기 시작해 이번 밤에는 보기 어려워요";
  if (entry.setForNight) return "이번 밤에는 이미 졌어요 · 오늘 저녁에 다시 살펴보세요";
  return entry.nextMonth ? `${entry.nextMonth}월 무렵 저녁 하늘에서 다시 만날 수 있어요` : "";
}

const ceil10 = (ms) => Math.ceil(ms / (10 * MIN_MS)) * 10 * MIN_MS;
