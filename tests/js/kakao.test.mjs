// 카카오톡으로 보내기 — 피드 메시지 내용 · 설명(앞 두 문장, 100자 안) · 딥링크 · 키가 없을 때
//     node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import test from "node:test";
import { available, DESC_MAX, feedDescription, feedMessage, letterLink, loadKakao, SDK_INTEGRITY, SDK_URL, TALL_MIN_HEIGHT,
         TALL_WIDTH } from "../../web/js/kakao.js";

test("SDK는 2.7 계열 · SRI 값", () => {
  assert.match(SDK_URL, /^https:\/\/t1\.kakaocdn\.net\/kakao_js_sdk\/2\.7\.\d+\/kakao\.min\.js$/);
  assert.match(SDK_INTEGRITY, /^sha384-[A-Za-z0-9+/]{64}$/);
});

test("설명 — 앞 두 문장, 굵게 · [근거 N]은 걷어 낸다", () => {
  const text = "**베가**의 빛이 [근거 1, 2] 출발했습니다. 그 해에 당신이 태어났어요. 세 번째 문장은 담지 않습니다.";
  assert.equal(feedDescription(text), "베가의 빛이 출발했습니다. 그 해에 당신이 태어났어요.");
  assert.equal(feedDescription("마침표 없는 한 문장"), "마침표 없는 한 문장");
  assert.equal(feedDescription(""), "");
});

test("설명 — 두 문장이 100자를 넘으면 첫 문장만, 첫 문장도 넘으면 잘라 말줄임표", () => {
  const a = `${"가".repeat(60)}.`;
  const b = `${"나".repeat(60)}.`;
  assert.equal(feedDescription(`${a} ${b}`), a);
  const long = feedDescription(`${"다".repeat(150)}. 끝.`);
  assert.ok(long.length <= DESC_MAX, long.length);
  assert.ok(long.endsWith("…"));
  for (const t of [`${a} ${b}`, "짧다. 짧다. 짧다.", "라".repeat(300)]) assert.ok(feedDescription(t).length <= DESC_MAX);
});

test("딥링크 — 앱 주소의 ?letter=<id>", () => {
  assert.equal(letterLink("ab12", "https://vasthorizon.bnbong.com"), "https://vasthorizon.bnbong.com/?letter=ab12");
  assert.equal(letterLink("a b", "http://localhost:8000/"), "http://localhost:8000/?letter=a%20b");
});

test("피드 메시지 — 제목 · 설명 · 세로형 카드(1080 × 실제 높이) · 편지 보기 버튼이 모두 딥링크로", () => {
  const m = feedMessage({ title: "베가의 빛", text: "**빛**이 출발했습니다 [근거 1]. 두 번째. 세 번째.", id: "x1",
                          imageUrl: "https://vasthorizon.bnbong.com/api/l/x1/tall.png", imageHeight: 1784,
                          origin: "https://vasthorizon.bnbong.com" });
  const url = "https://vasthorizon.bnbong.com/?letter=x1";
  assert.deepEqual(m, {
    objectType: "feed",
    content: { title: "베가의 빛", description: "빛이 출발했습니다. 두 번째.", imageUrl: "https://vasthorizon.bnbong.com/api/l/x1/tall.png",
               imageWidth: 1080, imageHeight: 1784, link: { mobileWebUrl: url, webUrl: url } },
    buttons: [{ title: "편지 보기", link: { mobileWebUrl: url, webUrl: url } }],
  });
  const fallback = feedMessage({ title: "", text: "a", id: "x", imageUrl: "", origin: "https://a.b" }).content;
  assert.equal(fallback.title, "VastHorizon의 편지");
  assert.deepEqual([fallback.imageWidth, fallback.imageHeight], [TALL_WIDTH, TALL_MIN_HEIGHT]);   // 높이를 모르면 2:3
});

test("키가 없으면(meta 없음) 쓸 수 없고, SDK를 부르지 않는다", async () => {
  assert.equal(available, false);
  assert.equal(await loadKakao(), false);
});
