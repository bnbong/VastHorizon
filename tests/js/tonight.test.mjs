// 오늘 밤 내 빛 (tonight.js) — 서울 2026-10-27 21:00의 하늘. 기대값은 이 저장소의 astro.js · ephemeris.js로 계산하고
// 실제 하늘과 맞는지 손으로 검토한 값이다 (일몰 17시 39분 무렵, 이날 새벽에 보름달이 지났다).
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { solarSystem } from "../../web/js/ephemeris.js";
import { altAz, localSiderealDeg } from "../../web/js/astro.js";
import { COUNTED_TIERS, crossing, directionWord, emptyState, eveningMonth, eveningText, hourText, itemLine, laterText, nightWindow,
         plan, rangeText, SUN_LIMIT, sunAltDeg, sunLimitOf, targetsOf, tierOf, tonightList, whenText } from "../../web/js/tonight.js";

const TZ = "Asia/Seoul";
const PLACE = { lat: 37.5665, lon: 126.978 };
const NOW = new Date("2026-10-27T21:00:00+09:00");
const at = (hhmm, day = "2026-10-27") => new Date(`${day}T${hhmm}:00+09:00`).getTime();
const near = (got, want, tol, label) => assert.ok(Math.abs(got - want) <= tol, `${label}: ${got} (기대 ${want} ± ${tol})`);
const nearMin = (got, want, tolMin, label) => near(got / 60000, want / 60000, tolMin, label);

const figures = new Map(Object.values(JSON.parse(readFileSync(new URL("../../data/constellations.json", import.meta.url))).figures)
  .map((f) => [f.item_id, { stars: Object.values(f.stars) }]));

const V = {
  earth: { id: "Q2", name: "지구", km: null, ra: null, dec: null, group: "solar_system", at: "2026-10-20" },
  sun: { id: "Q525", name: "태양", km: 1.5e8, ra: null, dec: null, group: "solar_system", at: "2026-10-20" },
  vega: { id: "Q3427", name: "베가", km: 2.37e14, ra: 279.2347, dec: 38.7837, group: "star", at: "2026-10-20" },
  polaris: { id: "Q12980", name: "폴라리스", km: 4.1e15, ra: 37.95, dec: 89.26, group: "star", at: "2026-10-20" },
  betelgeuse: { id: "Q12124", name: "베텔게우스", km: 6.0e15, ra: 88.7929, dec: 7.4071, group: "star", at: "2026-10-21" },
  orion: { id: "Q8860", name: "오리온자리", km: null, ra: 83, dec: 6, group: "constellation", at: "2026-10-21" },
  m31: { id: "Q2469", name: "안드로메다 은하", km: 2.4e19, ra: 10.6847, dec: 41.2688, group: "messier", at: "2026-10-22" },
  saturn: { id: "Q193", name: "토성", km: 1.3e9, ra: null, dec: null, group: "solar_system", at: "2026-10-22" },
  jupiter: { id: "Q319", name: "목성", km: 6.3e8, ra: null, dec: null, group: "solar_system", at: "2026-10-22" },
  antares: { id: "Q12166", name: "안타레스", km: 5.3e15, ra: 247.35, dec: -26.43, group: "star", at: "2026-10-23" },
  phobos: { id: "Q7547", name: "포보스 (위성)", km: 7.8e7, ra: null, dec: null, group: "solar_system", at: "2026-10-23" },
  hubble: { id: "Q2513", name: "허블 우주 망원경", km: 540, ra: null, dec: null, group: "human_made", at: "2026-10-23" },
};
// 지도 점의 겉보기 등급 (data/items.json의 '겉보기 등급')
const points = new Map([["Q3427", { mag: 0.03 }], ["Q12980", { mag: 1.97 }], ["Q12124", { mag: 0.45 }], ["Q2469", { mag: 3.44 }],
                        ["Q12166", { mag: 1.06 }]]);
const list = (visited, now = NOW, place = PLACE) => tonightList({ visited, place, now, points, figures, timeZone: TZ });
const ALL = list(Object.values(V));
const item = (r, name) => r.items.find((x) => x.name === name);

test("T1 태양 경계 시각 — 일몰 · 시민 · 항해 · 천문박명 끝, 새벽 항해박명 시작 (±2분)", () => {
  const noon = at("14:00");
  const sun = (d) => sunAltDeg(d, PLACE.lat, PLACE.lon);
  nearMin(crossing(at("17:00"), at("18:00"), sun, -0.833), at("17:39"), 2, "일몰");
  nearMin(nightWindow(noon, PLACE, SUN_LIMIT.bright).start, at("18:06"), 2, "시민박명 끝");
  nearMin(nightWindow(noon, PLACE, SUN_LIMIT.normal).start, at("18:37"), 2, "항해박명 끝");
  nearMin(nightWindow(noon, PLACE, SUN_LIMIT.faint).start, at("19:07"), 2, "천문박명 끝");
  nearMin(nightWindow(NOW.getTime(), PLACE, SUN_LIMIT.normal).end, at("05:54", "2026-10-28"), 2, "새벽 항해박명 시작");
  nearMin(nightWindow(noon, PLACE, SUN_LIMIT.normal).sunset, at("17:39"), 2, "낮에 연 화면의 일몰");
  assert.equal(crossing(at("12:00"), at("13:00"), sun, -0.833), null);      // 부호가 바뀌지 않으면 null
});

test("T2 베가 — 21시 고도 41.0° · 방위 292.2° 서쪽, 가장 좋은 때는 지금, 21시~22시, 0시 무렵 10° 아래로", () => {
  const v = item(ALL, "베가");
  near(v.now.alt, 41.0, 0.3, "고도");
  near(v.now.az, 292.2, 0.3, "방위");
  assert.equal(directionWord(v.now.az, v.now.alt), "서쪽");
  assert.equal(v.best.at, NOW.getTime());
  assert.equal(rangeText(v.best.from, v.best.to, { timeZone: TZ }), "21시~22시");
  nearMin(v.lastUp, at("00:05", "2026-10-28"), 10, "고도 10° 아래로");
  assert.equal(v.sunLimit, "bright");
});

test("T3 낮(14시)에 계산 — 밝은 베가는 시민박명 끝 직후 18:10 표본, 고도 73.5° · 방위 280.7°. 항해박명 기준이면 18:40 · 67.6°", () => {
  const r = list([V.earth, V.vega], new Date(at("14:00")));
  assert.equal(r.night.daytimeNow, true);
  const v = r.items[0];
  assert.equal(v.best.at, at("18:10"));
  near(v.best.alt, 73.5, 0.3, "고도");
  near(v.best.az, 280.7, 0.3, "방위");
  assert.equal(directionWord(v.best.az, v.best.alt), "서쪽");
  const [t] = targetsOf([V.vega], { points });
  const normal = plan({ ...t, sunLimit: "normal" }, PLACE, at("14:00"), { timeZone: TZ });
  assert.equal(normal.best.at, at("18:40"));
  near(normal.best.alt, 67.6, 0.3, "항해박명 기준 고도");
});

test("T4 폴라리스 — 고도 38.0° 북쪽, 밤새 같은 자리", () => {
  const v = item(ALL, "폴라리스");
  near(v.now.alt, 38.0, 0.3, "고도");
  near(v.now.az, 0.8, 0.5, "방위");
  assert.equal(directionWord(v.now.az, v.now.alt), "북쪽");
  assert.equal(v.steady, true);
  assert.match(itemLine(v, { timeZone: TZ }), /밤새 같은 자리$/);
});

test("T5 베텔게우스 — 21시에는 지평선 아래, 22:40에 떠오르고 04:00에 59.8°, 저녁 보조 문구는 23시 50분 동쪽 낮게", () => {
  const v = item(ALL, "베텔게우스");
  near(v.now.alt, -7.9, 0.5, "21시 고도");
  assert.equal(v.now.up, false);
  assert.equal(v.firstUp, at("22:40"));
  assert.equal(v.best.at, at("04:00", "2026-10-28"));
  near(v.best.alt, 59.8, 0.5, "가장 높은 고도");
  assert.equal(rangeText(v.best.from, v.best.to, { timeZone: TZ }), "3시~5시");
  assert.equal(v.evening.at, at("23:50"));
  near(v.evening.alt, 25.6, 0.5, "저녁 고도");
  assert.equal(eveningText(v, { timeZone: TZ }), "자정 전에는 23시 50분 무렵 동쪽 낮게");
});

test("T6 오리온자리 — 모양의 별 60%가 10° 위에 올라야 보인다 (21시에는 아직, 22시 10분~50분 사이에 떠오름)", () => {
  const v = item(ALL, "오리온자리");
  assert.equal(v.now.up, false);
  assert.ok(v.firstUp >= at("22:10") && v.firstUp <= at("22:50"), new Date(v.firstUp).toISOString());
  assert.ok(figures.get("Q8860").stars.length >= 7);
});

test("T7 안드로메다 은하 — 불빛이 적은 곳에서 맨눈, 21시 68.3°, 22:50에 86.3°로 머리 위", () => {
  const v = item(ALL, "안드로메다 은하");
  assert.equal(v.tier, "dark-eye");
  near(v.now.alt, 68.3, 0.3, "21시 고도");
  assert.equal(v.best.at, at("22:50"));
  near(v.best.alt, 86.3, 0.5, "가장 높은 고도");
  assert.equal(directionWord(v.best.az, v.best.alt), "머리 위");
});

test("T8 토성 — 21시 고도 46.1° · 방위 139.5° 남동쪽 (±1°)", () => {
  const v = item(ALL, "토성");
  near(v.now.alt, 46.1, 1, "고도");
  near(v.now.az, 139.5, 1, "방위");
  assert.equal(directionWord(v.now.az, v.now.alt), "남동쪽");
  assert.equal(v.sunLimit, "bright");
});

test("T9 목성 — 21시에는 지평선 아래(−35.7°), 새벽 3시에 21.5° 동쪽이라 오늘 밤 목록에 든다", () => {
  const v = item(ALL, "목성");
  near(v.now.alt, -35.7, 1, "21시 고도");
  assert.equal(v.now.up, false);
  const d = new Date(at("03:00", "2026-10-28"));
  const j = solarSystem(d).find((b) => b.key === "jupiter");
  const p = altAz(j.ra, j.dec, PLACE.lat, localSiderealDeg(d, PLACE.lon));
  near(p.alt, 21.5, 1, "3시 고도");
  assert.equal(directionWord(p.az, p.alt), "동쪽");
});

test("T10 달빛 — 21시 달 고도 33.3° · 밝은 비율 0.97, 안드로메다 은하에는 안내, 베가에는 없음", () => {
  const moon = solarSystem(NOW).find((b) => b.key === "moon");
  near(altAz(moon.ra, moon.dec, PLACE.lat, localSiderealDeg(NOW, PLACE.lon)).alt, 33.3, 0.5, "달 고도");
  near(moon.illum, 0.97, 0.01, "밝은 비율");
  assert.equal(item(ALL, "안드로메다 은하").moonNote, true);
  assert.equal(item(ALL, "베가").moonNote, false);
});

test("T11 태양 · 지구는 어디에도 나오지 않는다", () => {
  const names = [...ALL.items, ...ALL.later, ...ALL.hard].map((x) => x.name);
  assert.ok(!names.includes("태양") && !names.includes("지구"));
});

test("T12 인공위성 · 포보스 — 망원경 영역에만, 볼 수 있는 빛 수에는 세지 않는다", () => {
  const hard = ALL.hard.map((x) => x.id);
  assert.ok(hard.includes("Q7547") && hard.includes("Q2513"));
  assert.match(ALL.hard.find((x) => x.id === "Q2513").reason, /인공위성/);
  assert.equal(ALL.count, ALL.items.length);
  assert.ok(ALL.items.every((x) => COUNTED_TIERS.includes(x.tier)));
  assert.equal(ALL.count, 7);
});

test("T13 빈 상태 — 지구뿐이면 nothing, 안타레스뿐이면 none-tonight와 7월 무렵", () => {
  assert.equal(emptyState(list([V.earth])).key, "nothing");
  const r = list([V.earth, V.antares]);
  assert.equal(emptyState(r).key, "none-tonight");
  assert.equal(eveningMonth(247.35), 7);
  assert.equal(r.later[0].nextMonth, 7);
  assert.equal(laterText(r.later[0]), "7월 무렵 저녁 하늘에서 다시 만날 수 있어요");
  assert.equal(emptyState(list([V.earth, V.phobos])).key, "all-hard");
  assert.equal(emptyState(list([V.earth, V.betelgeuse]), { timeZone: TZ }).text,
               "지금은 담은 빛이 지평선 아래에 있어요 · 가장 먼저 뜨는 것은 베텔게우스 22시 40분");
  assert.equal(emptyState(list([V.earth, V.vega], new Date(at("14:00"))), { timeZone: TZ }).text,
               "오늘 일몰 17시 39분 · 18시 40분부터 별이 보이기 시작해요");
});

test("T14 정렬 — 지금 보이는 것을 고도순으로, 그 뒤 처음 떠오르는 순", () => {
  assert.deepEqual(ALL.items.map((x) => x.name),
                   ["안드로메다 은하", "토성", "베가", "폴라리스", "오리온자리", "베텔게우스", "목성"]);
  assert.equal(ALL.firstUp.name, "오리온자리");
});

test("T15 표기 — 30분 단위 내림 · 올림, '21시' · '21시 30분', 베가의 한 줄", () => {
  assert.equal(hourText(at("21:00"), { timeZone: TZ }), "21시");
  assert.equal(hourText(at("21:30"), { timeZone: TZ }), "21시 30분");
  assert.equal(rangeText(at("21:10"), at("22:40"), { timeZone: TZ }), "21시~23시");
  assert.equal(rangeText(at("21:40"), at("22:20"), { timeZone: TZ }), "21시 30분~22시 30분");
  assert.equal(rangeText(at("21:00"), at("21:00"), { timeZone: TZ }), "21시~21시 30분");
  assert.equal(itemLine(item(ALL, "베가"), { timeZone: TZ }), "베가 · 서쪽 · 고도 41° · 21시~22시가 가장 좋아요");
  assert.match(itemLine(item(ALL, "오리온자리"), { timeZone: TZ }), /30분이 가장 좋아요$/);
});

test("T16 남반구 — 다시 만날 달 안내를 하지 않는다", () => {
  const r = list([V.earth, { ...V.polaris }], NOW, { lat: -33.87, lon: 151.21 });
  assert.equal(r.items.length, 0);
  assert.equal(r.later[0].nextMonth, null);
  assert.equal(laterText(r.later[0]), "");
});

test("등급 규칙 · 박명 기준", () => {
  assert.equal(tierOf({ group: "star", mag: 5.0 }), "eye");
  assert.equal(tierOf({ group: "star", mag: 5.5 }), "dark-eye");
  assert.equal(tierOf({ group: "star", mag: 8 }), "binocular");
  assert.equal(tierOf({ group: "star", mag: 10 }), "telescope");
  assert.equal(tierOf({ group: "messier", mag: 1.6 }), "eye");
  assert.equal(tierOf({ group: "messier", mag: 5.8 }), "binocular");
  assert.equal(tierOf({ group: "star", mag: null }), "binocular");
  assert.equal(sunLimitOf({ kind: "body", tier: "eye", mag: 0.6 }), "bright");
  assert.equal(sunLimitOf({ kind: "fixed", tier: "eye", mag: 3 }), "normal");
  assert.equal(sunLimitOf({ kind: "fixed", tier: "binocular", mag: 7 }), "faint");
  // 하늘에서 누른 별(hip:) — 기록에 등급이 없으면 밝은 별 데이터에서
  const [hip] = targetsOf([{ id: "hip:91262", name: "HIP 91262", ra: 279.2, dec: 38.8, group: "star" }], { starMag: (h) => (h === 91262 ? 0.03 : null) });
  assert.equal(hip.mag, 0.03);
  // 갈릴레이 위성은 쌍안경, 타이탄은 망원경
  const [io, titan] = targetsOf([{ id: "Q3123", name: "이오 (위성)", group: "solar_system" }, { id: "Q2565", name: "타이탄 (위성)", group: "solar_system" }]);
  assert.equal(io.tier, "binocular");
  assert.equal(titan.tier, "telescope");
});

test("시간대 — 위치의 시간대로 계산 · 표기한다 (서울은 Asia/Seoul, 기기 시간대와 무관)", async () => {
  const { zoneOf } = await import("../../web/js/tonight.js");
  const seoul = { ...PLACE, name: "서울" };
  assert.equal(zoneOf(seoul), "Asia/Seoul");
  assert.equal(zoneOf({ ...PLACE, name: "내 위치", timeZone: "America/New_York" }), "America/New_York");
  const r = tonightList({ visited: [V.earth, V.vega, V.betelgeuse], place: seoul, now: NOW, points, figures });   // timeZone을 넘기지 않는다
  assert.equal(r.timeZone, "Asia/Seoul");
  const vega = r.items.find((x) => x.name === "베가");
  assert.equal(whenText(vega), "21시~22시가 가장 좋아요");
  assert.equal(itemLine(vega), "베가 · 서쪽 · 고도 41° · 21시~22시가 가장 좋아요");
  assert.equal(eveningText(r.items.find((x) => x.name === "베텔게우스")), "자정 전에는 23시 50분 무렵 동쪽 낮게");
  // 같은 순간을 뉴욕 시간대로 적으면 시각만 바뀐다 (계산은 같다)
  assert.equal(whenText(vega, { timeZone: "America/New_York" }), "8시~9시가 가장 좋아요");
});

test("관측 밤 하나 — 10-28 05:30 새벽에는 모든 빛을 지금 새벽에 묶고, 다음 저녁을 섞지 않는다", () => {
  const dawn = new Date("2026-10-28T05:30:00+09:00");
  const r = list([V.earth, V.vega, V.betelgeuse, V.m31, V.saturn, V.jupiter, V.polaris], dawn);
  const sunrise = at("06:51", "2026-10-28");
  assert.equal(r.night.daytimeNow, false);
  assert.equal(r.night.dawn, true);
  assert.ok(r.items.length >= 2);
  for (const x of r.items) assert.ok(x.firstUp <= sunrise && x.best.at <= sunrise, `${x.name} ${new Date(x.best.at).toISOString()}`);
  assert.deepEqual(r.items.map((x) => x.name).sort(), ["목성", "베텔게우스", "폴라리스"].sort());
  const m31 = r.later.find((x) => x.name === "안드로메다 은하");                 // 천문박명(05:22)이 지나 어두워지지 않는다
  assert.equal(laterText(m31), "하늘이 밝아지기 시작해 이번 밤에는 보기 어려워요");
  assert.equal(laterText(r.later.find((x) => x.name === "베가")), "이번 밤에는 이미 졌어요 · 오늘 저녁에 다시 살펴보세요");
  assert.notEqual(emptyState(r).key, "daytime");                                // 지난 일몰을 '오늘 일몰'로 적지 않는다
  // 새벽 항해박명(05:54)이 지나도 아직 해가 지기 전 밤 — 낮 안내(지난 일몰)를 하지 않는다
  assert.notEqual(emptyState(list([V.earth, V.jupiter], new Date("2026-10-28T06:05:00+09:00"))).key, "daytime");
  // 낮(14시)에는 다가오는 밤 — 일몰은 오늘 저녁
  nearMin(list([V.earth, V.vega], new Date(at("14:00"))).night.sunset, at("17:39"), 2, "오늘 저녁 일몰");
});

test("희미한 행성 — 천왕성 · 해왕성은 등급대로 어두운 하늘을 기다린다", () => {
  const [uranus, neptune, mars, io] = targetsOf([{ id: "Q324", name: "천왕성", group: "solar_system" }, { id: "Q332", name: "해왕성", group: "solar_system" },
    { id: "Q111", name: "화성", group: "solar_system" }, { id: "Q3123", name: "이오 (위성)", group: "solar_system" }]);
  assert.equal(uranus.tier, "dark-eye");
  assert.equal(uranus.sunLimit, "faint");
  assert.equal(neptune.tier, "binocular");
  assert.equal(neptune.sunLimit, "faint");
  assert.equal(mars.sunLimit, "bright");
  assert.equal(io.sunLimit, "faint");
});
