import test from "node:test";
import assert from "node:assert/strict";

import { farthestParts, labelledIds, markHtml, markState, nearFade, todayNewCount, worldHeading } from "../../web/js/worldmarks.js";

const LY = 9460730472580.8;
const v = (id, at, km = null) => ({ id, name: id, km, at });

test("표식 상태 — 알아간 천체만 채운 표식, 선택은 따로", () => {
  const known = new Set(["Q405", "Q3427"]);
  assert.deepEqual(markState("Q405", known), { known: true, selected: false });
  assert.deepEqual(markState("Q2469", known, "Q2469"), { known: false, selected: true });
  assert.deepEqual(markState("Q3427", known, "Q3427"), { known: true, selected: true });
  assert.deepEqual(markState(null, known, null), { known: false, selected: false });
});

test("표식 HTML — 알아감은 ✦가 든 살구색 원, 아직 만나지 않음은 빈 점선 원 (서랍 · 목록 · 지도 같은 클래스)", () => {
  assert.match(markHtml(true), /class="known-mark"[^>]*>✦</);
  assert.match(markHtml(false), /class="unknown-mark"[^>]*><\/span>/);
});

test("오늘 새로 알아간 빛 — 기록의 현지 날짜가 오늘인 것만 센다", () => {
  const visited = [v("a", "2026-10-23"), v("b", "2026-10-24"), v("c", "2026-10-24")];
  assert.equal(todayNewCount(visited, "2026-10-24"), 2);
  assert.equal(todayNewCount(visited, "2026-10-25"), 0);
  assert.equal(todayNewCount([], "2026-10-24"), 0);
});

test("지도 머리글 — 알아간 빛이 있으면 '여기까지 닿았습니다', 없으면 기다리는 문장", () => {
  const h = worldHeading([v("a", "2026-10-20"), v("b", "2026-10-24")], "2026-10-24");
  assert.equal(h.kicker, "오늘 새로 알아간 빛 1");
  assert.deepEqual(h.lines, ["내 세계는 오늘,", "여기까지 닿았습니다."]);
  assert.equal(h.known, "알아간 빛 2개");
  assert.equal(h.empty, false);
  const e = worldHeading([], "2026-10-24");
  assert.equal(e.kicker, "오늘 새로 알아간 빛 0");
  assert.deepEqual(e.lines, ["첫 번째 빛을", "기다리고 있어요."]);
  assert.equal(e.known, "알아간 빛 0개");
  assert.equal(e.empty, true);
});

test("가장 먼 빛의 큰 숫자 — 값과 단위를 나눈다 (안드로메다 약 254만 광년, 지평선 4.7km)", () => {
  assert.deepEqual(farthestParts(2.537e6 * LY), { value: "약 254만", unit: "광년" });
  assert.deepEqual(farthestParts(25 * LY), { value: "약 25", unit: "광년" });
  assert.deepEqual(farthestParts(384400), { value: "약 384,400", unit: "km" });
  assert.deepEqual(farthestParts(4.65), { value: "4.7", unit: "km" });
});

test("이름표 — 많아지면 최근 max개와 지금 고른 천체만", () => {
  const visited = Array.from({ length: 14 }, (_, i) => v(`s${i}`, "2026-10-24"));
  const ids = labelledIds(visited, "s0", 10);
  assert.equal(ids.size, 11);
  assert.ok(ids.has("s0") && ids.has("s13") && ids.has("s4"));
  assert.ok(!ids.has("s3"));
  assert.equal(labelledIds(visited, "모르는 천체", 10).size, 10);    // 기록에 없는 선택은 더하지 않는다
  assert.equal(labelledIds(visited.slice(0, 3)).size, 3);
});

test("점선 원 — 멀리서 보면 '나' 가까이 몰린 원은 숨고, 다가가면 나타난다", () => {
  const oneLightDay = 38.9, vega = 75;               // mapRadius(1광일) · mapRadius(베가)
  const view = 134.6 * 2.8;                           // 안드로메다까지 알아간 기본 시점
  assert.equal(nearFade(view, oneLightDay), 0);
  assert.equal(nearFade(view, vega), 1);
  assert.equal(nearFade(30, oneLightDay), 1);         // 확대하면 보인다
  assert.equal(nearFade(7 * 10, 10), 0.5);            // 6배와 8배 사이는 차츰
});
