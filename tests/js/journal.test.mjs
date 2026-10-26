import test from "node:test";
import assert from "node:assert/strict";

import { entryOf, localDate, reachOf, recent, restoreVisited, serialize, todays } from "../../web/js/journal.js";

const H = 4.65;

test("지난 날짜의 기록도 지워지지 않는다 (예전 형식 포함) — 다음날 0개로 돌아가던 문제", () => {
  const old = { date: "2026-10-20", km: 9e13, name: "시리우스", visited: [{ id: "Q8864", name: "시리우스", km: 8.1e13 }] };
  const v = restoreVisited(old, "2026-10-23");
  assert.equal(v.length, 1);
  assert.equal(v[0].at, "2026-10-20");
  assert.equal(todays(v, "2026-10-23").length, 0);
  const again = restoreVisited(JSON.parse(serialize(v)), "2026-10-24");
  assert.deepEqual(again, v);
});

test("현지 날짜 — UTC가 아니라 그 사람의 시계 기준", () => {
  assert.equal(localDate(new Date(2026, 9, 23, 8, 30)), "2026-10-23");   // 한국 오전 8시 30분 = UTC 전날
  assert.equal(localDate(new Date(2026, 0, 5, 23, 59)), "2026-01-05");
});

test("거리 미확인 기록은 남되 가장 먼 빛에는 들지 않는다", () => {
  const v = [entryOf({ id: "hip:1", name: "HIP 1", distance_km: null, group: "star" }, "2026-10-23"),
             entryOf({ id: "Q1", name: "달", distance_km: 384400, group: "solar_system" }, "2026-10-23")];
  assert.equal(v[0].km, null);
  assert.deepEqual(reachOf(v, H), { km: 384400, name: "달", id: "Q1" });
  assert.deepEqual(reachOf([v[0]], H), { km: H, name: "지평선", id: null });
});

test("가까운 천체를 나중에 알아가도 가장 먼 빛은 그대로, 기록은 늘어난다", () => {
  const v = [{ id: "a", name: "안드로메다", km: 2.4e19, at: "d" }, { id: "b", name: "달", km: 384400, at: "d" }];
  assert.equal(reachOf(v, H).name, "안드로메다");
  assert.deepEqual(recent(v, 1).map((x) => x.id), ["b"]);
});

test("되살릴 때 중복 · 깨진 기록은 걸러 낸다", () => {
  const v = restoreVisited({ visited: [{ id: "a", km: 1 }, { id: "a", km: 1 }, null, { name: "id 없음" }, { id: "b", km: -3 }] }, "t");
  assert.deepEqual(v.map((x) => [x.id, x.km, x.at]), [["a", 1, "t"], ["b", null, "t"]]);
  assert.deepEqual(restoreVisited(null, "t"), []);
});

test("두 눈으로 본 날(seen) — 예전 기록은 키 없이 그대로, 있으면 정리해 왕복 보존 · 새 기록은 겉보기 등급(mag)도", () => {
  const old = [{ id: "a", name: "베가", km: 2.4e14, at: "2026-10-20" }];
  const v = restoreVisited({ v: 2, visited: [...old, { id: "b", name: "토성", km: 1.3e9, at: "2026-10-21", seen: [{ at: "2026-10-27" }, { at: "x" }] }] }, "t");
  assert.deepEqual(v[0], old[0]);
  assert.deepEqual(v[1].seen, [{ at: "2026-10-27" }]);
  assert.deepEqual(restoreVisited(JSON.parse(serialize(v)), "t"), v);
  assert.equal(entryOf({ id: "Q3427", name: "베가", distance_km: 2.37e14, group: "star", attrs: { "겉보기 등급": 0.03 } }, "t").mag, 0.03);
  assert.equal(entryOf({ id: "Q193", name: "토성", group: "solar_system" }, "t").mag, null);
});
