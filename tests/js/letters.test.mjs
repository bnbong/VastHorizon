// 받은 편지 보관함 — 더하기 · 중복 방지 · 최대 50개 · 정렬 · 직렬화
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import {
  addLetter, djb2, excerptOf, findLetter, firstSentence, letterDate, letterItemIds, letterKey, LETTERS_KEY, LETTERS_MAX, makeEntry,
  plainText, removeLetter, restoreLetters, serializeLetters, setShare, sharedView, sortLetters,
} from "../../web/js/letters.js";

const letter = (id, text, at) => makeEntry({ kind: "letter", item_id: id, item_name: id, title: `${id}의 빛`, text, req: { item_id: id } }, at);

test("저장소 키와 최대 개수", () => {
  assert.equal(LETTERS_KEY, "vh-letters");
  assert.equal(LETTERS_MAX, 50);
});

test("본문 앞 120자 — 굵게 · 근거 표시는 걷어 내고, 잘리면 말줄임표", () => {
  assert.equal(plainText("**베가**의 빛이 [근거 1, 2] 출발했습니다.\n그 해에"), "베가의 빛이 출발했습니다. 그 해에");
  const long = "가".repeat(200);
  const e = excerptOf(long);
  assert.equal(e.length, 121);
  assert.ok(e.endsWith("…"));
  assert.equal(excerptOf("짧은 편지"), "짧은 편지");
  assert.equal(makeEntry({ kind: "letter", text: long }, "2026-10-25T00:00:00Z").text.length, 121);
});

test("더하기 — 최근 것이 앞에, 새 배열을 돌려준다", () => {
  const a = letter("Q1", "첫 편지입니다.", "2026-10-20T10:00:00Z");
  const b = letter("Q2", "둘째 편지입니다.", "2026-10-21T10:00:00Z");
  const list0 = [];
  const list1 = addLetter(list0, a);
  const list2 = addLetter(list1, b);
  assert.equal(list0.length, 0);
  assert.deepEqual(list2.map((e) => e.item_id), ["Q2", "Q1"]);
  // 오래된 편지를 나중에 더해도 날짜 순서
  const c = letter("Q3", "오래된 편지.", "2026-10-01T10:00:00Z");
  assert.deepEqual(addLetter(list2, c).map((e) => e.item_id), ["Q2", "Q1", "Q3"]);
});

test("중복 방지 — 같은 편지는 한 번만, 자리 · 날짜는 그대로 두고 비어 있던 공유 정보만 채운다", () => {
  const a = letter("Q1", "같은 편지입니다.", "2026-10-20T10:00:00Z");
  const b = letter("Q2", "다른 편지입니다.", "2026-10-21T10:00:00Z");
  let list = addLetter(addLetter([], a), b);
  const again = { ...letter("Q1", "같은 편지입니다.", "2026-10-25T10:00:00Z"), shareId: "abc", url: "https://x/api/l/abc" };
  list = addLetter(list, again);
  assert.equal(list.length, 2);
  const q1 = list.find((e) => e.item_id === "Q1");
  assert.equal(q1.at, "2026-10-20T10:00:00Z");
  assert.equal(q1.shareId, "abc");
  // 같은 공유 ID면 본문이 달라 보여도 같은 편지
  list = addLetter(list, { ...letter("Q9", "딥링크로 받은 편지", "2026-10-26T00:00:00Z"), shareId: "abc" });
  assert.equal(list.length, 2);
});

test("열쇠 — 공유 ID가 있으면 그것, 없으면 본문 전체 해시 (앞 40자가 같아도 다른 편지)", () => {
  const head = "안녕, 지구의 친구야. 나는 베가야. 내 빛은 25년 전에 출발했어. 그때 너의 세상은";
  const a = letter("Q1", `${head} 아직 작았지.`, "2026-10-20T10:00:00Z");
  const b = letter("Q1", `${head} 이미 넓었지.`, "2026-10-21T10:00:00Z");
  assert.notEqual(a.key, b.key);
  assert.equal(addLetter(addLetter([], a), b).length, 2);
  assert.equal(letterKey({ kind: "letter", text: "x", shareId: "abc" }), "share|abc");
  assert.equal(makeEntry({ kind: "letter", text: "x", shareId: "abc" }).key, "share|abc");
  // 본문 해시는 표시 기호 · 공백과 상관없이 같다 — 120자 넘는 본문도 전체로
  assert.equal(letterKey({ kind: "letter", text: "**베가**의 빛 [근거 1]" }), letterKey({ kind: "letter", text: "베가의  빛" }));
  const long = "가".repeat(200);
  assert.notEqual(makeEntry({ kind: "letter", text: long }).key, makeEntry({ kind: "letter", text: `${long}나` }).key);
  assert.equal(makeEntry({ kind: "letter", text: long }).text.length, 121);
  assert.equal(djb2(""), (5381).toString(36));
  assert.equal(djb2("abc"), djb2("abc"));
  // 공유 전에 남긴 기록과 공유 링크로 다시 받은 같은 편지는 하나로 (열쇠는 달라도 본문 해시가 같다)
  const local = letter("Q1", "같은 편지입니다.", "2026-10-20T10:00:00Z");
  const viaLink = makeEntry({ kind: "letter", item_id: "Q1", text: "같은 편지입니다.", shareId: "zz" }, "2026-10-26T00:00:00Z");
  const merged = addLetter([local], viaLink);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].shareId, "zz");
  assert.equal(merged[0].at, "2026-10-20T10:00:00Z");
});

test("공유 기록(.json) 열기 — 근거 번호는 number, 예전 응답의 n도", () => {
  const rec = {
    id: "0123456789abcdef", kind: "letter", item_id: "Q3415", item_name: "베가", eyebrow: "별", title: "베가에서 온 빛의 편지",
    text: "나는 베가야 [근거 1]. 2001년에 떠났어 [근거 2].", departure: { light_years: 25, summary: "25년 전 출발" }, themes: [],
    cited: [{ number: 1, title: "베가", source_type: "위키백과", url: "https://ko.wikipedia.org/wiki/베가" },
            { number: 2, title: "2001년", source_type: "위키백과", url: "https://ko.wikipedia.org/wiki/2001년" }],
    created: "2026-10-25T00:00:00Z", expires: 1,
  };
  const view = sharedView(rec);
  assert.deepEqual(view.cited.map((c) => c.number), [1, 2]);
  assert.equal(view.cited[0].url, "https://ko.wikipedia.org/wiki/베가");
  assert.equal(view.kind, "letter");
  assert.equal(view.title, "베가에서 온 빛의 편지");
  assert.equal(view.departure.light_years, 25);
  assert.deepEqual(sharedView({ ...rec, cited: [{ n: 3, title: "t" }] }).cited, [{ number: 3, title: "t", url: "", source_type: "" }]);
  const mind = sharedView({ kind: "perspective", title: "", text: "답", cited: null });
  assert.deepEqual([mind.kind, mind.isLetter, mind.title, mind.cited], ["perspective", false, "마음 한 줄 곁의 사실", []]);
});

test("최대 50개 — 넘치면 가장 오래된 것부터 버린다", () => {
  let list = [];
  for (let i = 0; i < 60; i += 1) list = addLetter(list, letter(`Q${i}`, `편지 ${i}`, new Date(Date.UTC(2026, 0, 1, 0, i)).toISOString()));
  assert.equal(list.length, 50);
  assert.equal(list[0].item_id, "Q59");
  assert.equal(list.at(-1).item_id, "Q10");
  assert.equal(addLetter([], letter("Q1", "x", "2026-01-01T00:00:00Z"), 0).length, 0);
});

test("정렬 — 최근 것부터, 같은 시각이면 원래 순서", () => {
  const t = "2026-10-20T10:00:00Z";
  const list = [letter("A", "a", t), letter("B", "b", "2026-10-22T00:00:00Z"), letter("C", "c", t)];
  assert.deepEqual(sortLetters(list).map((e) => e.item_id), ["B", "A", "C"]);
});

test("직렬화 · 되살리기 — 왕복이 같고, 깨진 기록 · 중복 · 모르는 종류는 걸러 낸다", () => {
  const list = addLetter(addLetter([], letter("Q1", "하나.", "2026-10-20T10:00:00Z")),
    makeEntry({ kind: "perspective", item_id: null, title: "마음 한 줄", text: "작게 느껴질 때.", req: { theme: "small" } }, "2026-10-21T00:00:00Z"));
  const text = serializeLetters(list);
  assert.deepEqual(restoreLetters(text), list);
  assert.deepEqual(restoreLetters(JSON.parse(text)), list);
  const dirty = { letters: [list[0], list[0], null, { kind: "other", key: "k", at: "t" }, { kind: "letter", at: "t" }, list[1]] };
  assert.equal(restoreLetters(dirty).length, 2);
  assert.deepEqual(restoreLetters("깨진 JSON{"), []);
  assert.deepEqual(restoreLetters(null), []);
});

test("공유 정보 갱신 · 삭제 · 찾기", () => {
  const a = letter("Q1", "하나.", "2026-10-20T10:00:00Z");
  let list = addLetter([], a);
  list = setShare(list, a.key, { id: "xyz", url: "https://vasthorizon.bnbong.com/api/l/xyz" });
  assert.equal(findLetter(list, a.key).shareId, "xyz");
  assert.equal(findLetter(list, "없음"), null);
  assert.deepEqual(removeLetter(list, a.key), []);
});

test("편지를 받은 천체 · 첫 문장 · 날짜", () => {
  const list = [letter("Q1", "a", "2026-10-20T10:00:00Z"), makeEntry({ kind: "perspective", item_id: "Q2", text: "b" })];
  assert.deepEqual([...letterItemIds(list)], ["Q1"]);
  assert.equal(firstSentence("빛이 출발했습니다. 그 해에는"), "빛이 출발했습니다.");
  assert.equal(firstSentence("마침표 없는 문장"), "마침표 없는 문장");
  assert.equal(letterDate(new Date(2026, 9, 5, 23, 0).toISOString()), "2026.10.05");
  assert.equal(letterDate("엉망"), "");
});
