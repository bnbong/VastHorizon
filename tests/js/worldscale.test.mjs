// 내 세상이 얼마나 넓은가 — 세상 안 천체, 비유 계산
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import {
  analogies, countByGroup, growthText, groupLine, insideWorld, knownAndUnknown, lengthText, namesLine, newlyInside, powerText, sandModelKm, volumeRatio,
} from "../../web/js/worldscale.js";

const LY = 9460730472580.8;
const POINTS = [
  { name: "국제우주정거장", group: "human_made", km: 420 }, { name: "달", group: "solar_system", km: 384400 },
  { name: "태양", group: "solar_system", km: 1.496e8 }, { name: "보이저 1호", group: "human_made", km: 2.58e10 },
  { name: "시리우스", group: "star", km: 8.6 * LY }, { name: "베텔게우스", group: "star", km: 548 * LY },
  { name: "안드로메다 은하", group: "messier", km: 2.54e6 * LY }, { name: "지구", group: "solar_system", km: 0 },
];

test("세상 안 · 새로 들어온 천체 — 거리순, 지구(0)는 빼고", () => {
  assert.deepEqual(insideWorld(POINTS, 2e8).map((p) => p.name), ["국제우주정거장", "달", "태양"]);
  assert.deepEqual(newlyInside(POINTS, 2e8, 600 * LY).map((p) => p.name), ["보이저 1호", "시리우스", "베텔게우스"]);
  const counts = countByGroup(insideWorld(POINTS, 600 * LY));
  assert.deepEqual(counts, { human_made: 2, solar_system: 2, star: 2 });
  assert.equal(groupLine(counts), "태양계 천체 2 · 탐사선 · 위성 2 · 별 2");
  assert.equal(namesLine(insideWorld(POINTS, 600 * LY)), "국제우주정거장, 달, 태양 외 3개");
  assert.equal(namesLine([]), "");
});

test("모래알 모형 — 지구 지름 12,742km를 1mm로: 베텔게우스(548광년)까지는 약 40.7만 km, 달까지보다 멀다", () => {
  const model = sandModelKm(548 * LY);
  assert.ok(Math.abs(model - 406884) < 500, model);
  const a = analogies(548 * LY);
  assert.equal(a[1].value, "40.7만 km");
  assert.equal(a[1].note, "지구에서 달까지보다 멉니다");
  assert.equal(a[0].value, "약 548년");
});

test("부피 비 · 배율 · 길이 표기", () => {
  assert.ok(Math.abs(volumeRatio(4.654) - 1) < 0.01);
  assert.equal(powerText(1234), "1,234배");
  assert.equal(powerText(3.2e45), "10⁴⁵배");
  assert.equal(growthText(10, 25), "2.5배");
  assert.equal(growthText(10, 4000), "400배");
  assert.equal(growthText(4.65, 384400), "10⁴배");               // 1만 배 이상은 10의 거듭제곱으로
  assert.equal(lengthText(0.0005), "50 cm");
  assert.equal(lengthText(2.3e-6), "2.3 mm");
  assert.equal(lengthText(3.2e9), "32억 km");
});

test("지평선 세상에는 비유가 빛으로 하나뿐", () => {
  assert.equal(analogies(4.65).length, 1);
});

test("거리 안에 있다고 내 세상이 아니다 — 알아간 천체 / 아직 알아가지 않은 천체", () => {
  const pts = POINTS.map((p, i) => ({ ...p, id: `Q${i}` }));
  const { known, unknown } = knownAndUnknown(pts, new Set(["Q5"]), 600 * LY);       // 베텔게우스만 알게 됨
  assert.deepEqual(known.map((p) => p.name), ["베텔게우스"]);
  assert.deepEqual(unknown.map((p) => p.name), ["국제우주정거장", "달", "태양", "보이저 1호", "시리우스"]);
  assert.match(analogies(548 * LY)[2].note, /알아가지 않은/);
  assert.doesNotMatch(analogies(548 * LY)[2].note, /확률|정해지지/);   // 배움의 은유를 물리 주장처럼 말하지 않는다
});

test("화면 문구 — 아직 모른다는 것을 천체가 '확률' · '정해지지 않은' 상태라고 말하지 않는다", async () => {
  const { readFile } = await import("node:fs/promises");
  for (const f of ["main.js", "map.js", "worldscale.js"]) {
    const src = await readFile(new URL(`../../web/js/${f}`, import.meta.url), "utf-8");
    const ui = src.split("\n").filter((l) => !l.trim().startsWith("//")).join("\n");   // 주석은 빼고 화면에 나가는 코드만
    assert.doesNotMatch(ui, /확률로 남은|정해지지 않은 가능성|label probable/, f);
  }
});
