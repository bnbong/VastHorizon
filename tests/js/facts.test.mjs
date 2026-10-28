// 천체 카드의 핵심 사실 한 문장 — 항목 메타데이터만으로 (LLM 없음)
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import { CENTER_REF, MILKY_WAY_ID, distanceLabel, heroFact, josa, placeNote } from "../../web/js/facts.js";

const LY = 9460730472580.8;
const text = (f) => f && `${f.before}${f.em}${f.after}`;

test("조사 — 받침에 따라", () => {
  assert.equal(josa("달", "을", "를"), "을");
  assert.equal(josa("베가", "을", "를"), "를");
  assert.equal(josa("M31", "은", "는"), "은(는)");
});

test("별 · 메시에 — 빛이 건너온 시간과 출발한 해", () => {
  const vega = { name: "베가", group: "star", kind: "항성", distance_km: 25.02 * LY, attrs: {} };
  const f = heroFact(vega, { refYear: 2026 });
  assert.equal(text(f), "지금 눈에 닿은 빛은 약 25년을 건너왔어요.");
  assert.equal(f.em, "약 25년");
  assert.match(f.detail, /약 25 광년이기 때문입니다/);
  assert.match(f.detail, /2001년 무렵에 출발한 빛/);
  const m31 = { name: "안드로메다 은하", group: "messier", distance: { km: 2.4e19 }, attrs: {} };
  assert.equal(heroFact(m31, { refYear: 2026 }).em, "약 254만 년");
});

test("태양계 — 빛이 그 천체를 떠난 시간", () => {
  const moon = { name: "달", group: "solar_system", kind: "위성", distance_km: 394538.6, attrs: { "평균 반지름(km)": 1737.1 } };
  const f = heroFact(moon);
  assert.equal(text(f), "이 빛은 약 1.3초 전에 달을 떠났어요.");
  assert.match(f.detail, /약 394,539 km/);
  assert.match(f.detail, /1,737 km/);
  assert.equal(text(heroFact({ name: "태양", group: "solar_system", distance_km: 148945933.6, attrs: {} })), "이 빛은 약 8.3분 전에 태양을 떠났어요.");
});

test("인공물 — 궤도 고도 · 빛으로 걸리는 거리 · 발사 연도", () => {
  const iss = { name: "국제우주정거장", group: "human_made", distance_km: 419.5, distance: { km: 419.5, reference: "지표면 위 궤도 고도" },
                attrs: { "공전 주기(분)": 92.97, "발사일": "1998-11-20" } };
  const f = heroFact(iss);
  assert.equal(text(f), "지금 약 420 km 높이에서 지구를 돌고 있어요.");
  assert.match(f.detail, /약 93분/);
  assert.match(f.detail, /약 15바퀴/);
  const voyager = { name: "보이저 1호", group: "human_made", distance_km: 25826939401.7, attrs: { "발사일": "1977-09-05" } };
  assert.equal(text(heroFact(voyager)), "빛의 속도로도 약 24시간이 걸리는 곳에 있어요.");
  assert.match(heroFact(voyager).detail, /1977년에 발사/);
  assert.equal(text(heroFact({ name: "어떤 위성", group: "human_made", attrs: { "발사일": "2022-08-05" } })), "2022년에 지구를 떠났어요.");
});

test("별자리 — 모양을 이루는 별의 거리, 없으면 가장 밝은 별", () => {
  const orion = { name: "오리온자리", group: "constellation", kind: "별자리", attrs: { "가장 밝은 별": "리겔 (0.18등급)", "관측 계절": "겨울" } };
  const figure = { stars: [{ name: "리겔", distance_ly: 863 }, { name: "벨라트릭스", distance_ly: 250 }, { name: "알니람", distance_ly: 1340 }, { name: "x", distance_ly: null }] };
  const f = heroFact(orion, { figure });
  assert.equal(text(f), "이 모양을 이루는 별 중 가장 먼 별은 약 1340 광년 떨어져 있어요.");
  assert.match(f.detail, /별 3개/);
  assert.match(f.detail, /벨라트릭스는 약 250 광년/);
  assert.equal(text(heroFact(orion)), "이 별자리에서 가장 밝은 별은 리겔이에요.");
});

test("거리를 모르면 종류 문장 · 근거가 없으면 null — 거리는 지어내지 않는다", () => {
  assert.equal(text(heroFact({ name: "HIP 1", group: "star", kind: "항성", distance_km: null, attrs: {} })), "HIP 1은(는) 항성이에요.");
  assert.equal(text(heroFact({ name: "프록시마", group: "star", kind: "적색 왜성", attrs: {} })), "프록시마는 적색 왜성이에요.");
  assert.equal(heroFact({ name: "무엇", group: "star", attrs: {} }), null);
  assert.equal(heroFact(null), null);
});

test("지구 — 핵심 사실 아래에 지구에만 붙는 문단과 근거", () => {
  const earth = { id: "Q2", name: "지구", group: "solar_system", kind: "행성", distance_km: null, distance: null, attrs: {} };
  assert.equal(text(heroFact(earth)), "지구는 행성이에요.");      // 거리가 없어 '종류' 분기
  const note = placeNote(earth);
  assert.match(note.text, /약 4\.7 km 떨어진 지평선/);
  assert.match(note.text, /약 61억 km/);
  assert.match(note.text, /0\.12화소/);
  assert.doesNotMatch(note.text, /—/);
  assert.equal(note.source.url, "https://ko.wikipedia.org/wiki/창백한_푸른_점");
  assert.equal(placeNote({ id: "Q405", name: "달", group: "solar_system" }), null);
  assert.equal(placeNote(null), null);
});

// /api/items/{id}의 모양 (서버 계약: distance.reference "지구에서 우리 은하 중심까지", attrs "보이는 모습" · "관측")
const MILKY_WAY = { id: "Q321", name: "우리 은하", group: "milky_way", group_ko: "우리 은하", kind: "막대나선은하", distance_km: 26046 * LY,
  distance: { km: 26046 * LY, reference: "지구에서 우리 은하 중심까지" },
  attrs: { "보이는 모습": "천구를 가로지르는 밝은 띠(은하수)로 보이고, 은하 중심부가 있는 궁수자리 방향에서 가장 밝다" } };
const SGR_A = { id: "Q237284", name: "궁수자리 A*", group: "milky_way", group_ko: "우리 은하", kind: "초거대질량 블랙홀", distance_km: 26000 * LY,
  distance: { km: 26000 * LY }, attrs: { "관측": "가시광선은 지구와의 사이에 있는 먼지와 가스에 가려 보이지 않아 전파와 적외선으로 관측합니다" } };

test("우리 은하 — 은하 중심까지의 거리, 빛이 건너왔다는 말은 하지 않는다", () => {
  assert.equal(MILKY_WAY_ID, "Q321");
  assert.equal(CENTER_REF, "지구에서 우리 은하 중심까지");
  const f = heroFact(MILKY_WAY, { refYear: 2026 });
  assert.equal(text(f), "우리는 이 은하 안에 있어요. 은하 중심까지는 약 2.6만 광년이에요.");
  assert.equal(f.em, "약 2.6만 광년");
  assert.equal(f.detail, "밤하늘의 은하수가 이 은하를 안에서 본 모습입니다. 천구를 가로지르는 밝은 띠(은하수)로 보이고, 은하 중심부가 있는 궁수자리 방향에서 가장 밝다.");
  for (const s of [text(f), f.detail]) {
    assert.doesNotMatch(s, /건너왔어요/);
    assert.doesNotMatch(s, /우리 은하까지/);
    assert.doesNotMatch(s, /출발한 빛/);
  }
  assert.equal(heroFact({ ...MILKY_WAY, attrs: {} }).detail, "");   // 근거(보이는 모습)가 없으면 덧붙이지 않는다
});

test("궁수자리 A* — 지구에 닿은 전파가 건너온 시간과 관측 방법", () => {
  const f = heroFact(SGR_A, { refYear: 2026 });
  assert.equal(text(f), "지금 지구에 닿은 전파는 약 2.6만 년을 건너왔어요.");
  assert.match(f.detail, /^이 블랙홀까지의 거리가 약 2\.6만 광년이기 때문입니다\. 가시광선은 .*관측합니다\.$/);
  assert.doesNotMatch(text(f), /눈에 닿은 빛/);
  assert.equal(heroFact({ ...SGR_A, attrs: {} }).detail, "이 블랙홀까지의 거리가 약 2.6만 광년이기 때문입니다.");
});

test("거리 글 — 우리 은하는 '은하 중심까지', 그 밖은 distanceText 그대로", () => {
  assert.equal(distanceLabel(26046 * LY, { id: "Q321" }), "은하 중심까지 약 2.6만 광년");
  assert.equal(distanceLabel(26046 * LY, { reference: "지구에서 우리 은하 중심까지" }), "은하 중심까지 약 2.6만 광년");
  assert.equal(distanceLabel(26000 * LY, { id: "Q237284" }), "약 2.6만 광년");      // 궁수자리 A*는 그 천체까지의 거리
  assert.equal(distanceLabel(25.02 * LY), "약 25 광년");
  assert.equal(distanceLabel(null, { id: "Q321" }), "지구");                       // 거리가 없으면 distanceText와 같다
});
