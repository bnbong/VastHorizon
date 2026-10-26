// 두 눈으로 본 빛 (seen.js) — 알아간 빛 기록의 seen 필드 규칙과 하위 호환
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";

import { entryOf, restoreVisited, serialize } from "../../web/js/journal.js";
import { cleanSeen, markSeen, SEEN_MAX, seenCount, seenIds, seenSummary, seenToday, unmarkSeen } from "../../web/js/seen.js";

const base = () => [
  { id: "Q2", name: "지구", km: null, ra: null, dec: null, group: "solar_system", at: "2026-10-20" },
  { id: "Q3427", name: "베가", km: 2.37e14, ra: 279.2347, dec: 38.7837, group: "star", at: "2026-10-20" },
];

test("markSeen은 새 배열을 돌려주고 원래 배열을 바꾸지 않는다 · 위치는 소수 첫째 자리까지", () => {
  const v = base();
  const snapshot = JSON.stringify(v);
  const out = markSeen(v, "Q3427", "2026-10-27", { name: "내 위치", lat: 37.5665, lon: 126.978 });
  assert.notEqual(out, v);
  assert.equal(JSON.stringify(v), snapshot);
  assert.deepEqual(out[1].seen, [{ at: "2026-10-27", place: { name: "내 위치", lat: 37.6, lon: 127 } }]);
  assert.equal(out[0], v[0]);
  assert.equal(seenToday(out[1], "2026-10-27"), true);
});

test("같은 날 두 번이면 같은 배열 · 기록 하나, 없는 천체도 같은 배열", () => {
  const once = markSeen(base(), "Q3427", "2026-10-27");
  assert.equal(markSeen(once, "Q3427", "2026-10-27"), once);
  assert.equal(once[1].seen.length, 1);
  assert.equal(markSeen(once, "Q404", "2026-10-27"), once);
});

test("다른 날은 날짜순으로 쌓인다", () => {
  let v = markSeen(base(), "Q3427", "2026-10-27", { name: "서울" });
  v = markSeen(v, "Q3427", "2026-10-29");
  v = markSeen(v, "Q3427", "2026-10-28");
  assert.deepEqual(v[1].seen.map((s) => s.at), ["2026-10-27", "2026-10-28", "2026-10-29"]);
  assert.deepEqual(v[1].seen[0].place, { name: "서울" });
  assert.deepEqual(seenSummary(v[1]), { count: 3, last: "10.29", text: "직접 본 날 3번 · 마지막 10.29" });
});

test("unmarkSeen은 오늘 기록만 지우고, 마지막 기록을 지우면 seen 키가 사라진다", () => {
  let v = markSeen(markSeen(base(), "Q3427", "2026-10-26"), "Q3427", "2026-10-27");
  v = unmarkSeen(v, "Q3427", "2026-10-27");
  assert.deepEqual(v[1].seen.map((s) => s.at), ["2026-10-26"]);
  assert.equal(unmarkSeen(v, "Q3427", "2026-10-27"), v);
  v = unmarkSeen(v, "Q3427", "2026-10-26");
  assert.equal("seen" in v[1], false);
  assert.deepEqual(v, base());
});

test("cleanSeen — 배열이 아닌 값 · 잘못된 날짜 · 중복을 걸러 내고, 최근 50개만", () => {
  assert.equal(cleanSeen("2026-10-27"), null);
  assert.equal(cleanSeen([]), null);
  assert.equal(cleanSeen([{ at: "어제" }, null, { at: "2026-1-2" }]), null);
  assert.deepEqual(cleanSeen([{ at: "2026-10-28" }, { at: "2026-10-27", place: { lat: "x" } }, { at: "2026-10-28" }]),
                   [{ at: "2026-10-27" }, { at: "2026-10-28" }]);
  const many = Array.from({ length: 60 }, (_, i) => ({ at: `2026-${String(1 + Math.floor(i / 28)).padStart(2, "0")}-${String(1 + (i % 28)).padStart(2, "0")}` }));
  const out = cleanSeen(many);
  assert.equal(out.length, SEEN_MAX);
  assert.equal(out[out.length - 1].at, many[many.length - 1].at);
  assert.equal(out[0].at, many[10].at);
});

test("restoreVisited — seen이 없는 예전 기록은 그대로, 있으면 정리해서 보존하고 왕복해도 같다", () => {
  const old = restoreVisited({ v: 2, visited: base() }, "2026-10-27");
  assert.deepEqual(old, base());
  assert.ok(old.every((v) => !("seen" in v)));
  const saved = { v: 2, visited: [base()[0], { ...base()[1], seen: [{ at: "2026-10-28" }, { at: "bad" }, { at: "2026-10-27" }, { at: "2026-10-28" }] },
                                  { id: "Q12980", name: "폴라리스", km: 4.1e15, at: "2026-10-20", seen: "x" }] };
  const v = restoreVisited(saved, "2026-10-29");
  assert.deepEqual(v[1].seen, [{ at: "2026-10-27" }, { at: "2026-10-28" }]);
  assert.equal("seen" in v[2], false);
  assert.deepEqual(restoreVisited(JSON.parse(serialize(v)), "2026-10-30"), v);
});

test("seenCount는 지구를 세지 않는다 · seenIds", () => {
  let v = markSeen(base(), "Q3427", "2026-10-27");
  v = markSeen(v, "Q2", "2026-10-27");
  assert.equal(seenCount(v), 1);
  assert.deepEqual([...seenIds(v)].sort(), ["Q2", "Q3427"]);
  assert.equal(seenCount(base()), 0);
});

test("entryOf — 겉보기 등급이 있으면 mag로, 없으면 null", () => {
  assert.equal(entryOf({ id: "Q3427", name: "베가", distance_km: 2.37e14, ra_deg: 279.2, dec_deg: 38.8, group: "star",
                         attrs: { "겉보기 등급": 0.03 } }, "2026-10-27").mag, 0.03);
  assert.equal(entryOf({ id: "Q193", name: "토성", group: "solar_system", attrs: {} }, "2026-10-27").mag, null);
  assert.equal(entryOf({ id: "hip:1", name: "HIP 1", group: "star" }, "2026-10-27").mag, null);
});

test("cleanSeen — 실제 달력 날짜만 (2월 30일 · 13월 · 평년 2월 29일은 버리고 윤년 2월 29일은 남긴다), 연말 · 연초 순서", async () => {
  const { isCalendarDay } = await import("../../web/js/seen.js");
  assert.equal(isCalendarDay("2026-02-30"), false);
  assert.equal(isCalendarDay("2026-13-01"), false);
  assert.equal(isCalendarDay("2026-02-29"), false);
  assert.equal(isCalendarDay("2028-02-29"), true);
  assert.equal(isCalendarDay("2026-12-31"), true);
  assert.deepEqual(cleanSeen([{ at: "2027-01-01" }, { at: "2026-02-30" }, { at: "2026-12-31" }, { at: "2028-02-29" }, { at: "2026-02-29" }]).map((s) => s.at),
                   ["2026-12-31", "2027-01-01", "2028-02-29"]);
  // 연말에 남긴 뒤 새해에 다시 — 날짜순으로 쌓인다
  let v = markSeen(base(), "Q3427", "2026-12-31");
  v = markSeen(v, "Q3427", "2027-01-01");
  assert.deepEqual(v[1].seen.map((s) => s.at), ["2026-12-31", "2027-01-01"]);
  assert.deepEqual(seenSummary(v[1]), { count: 2, last: "01.01", text: "직접 본 날 2번 · 마지막 01.01" });
});
