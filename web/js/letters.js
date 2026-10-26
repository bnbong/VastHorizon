// 받은 편지 보관함 — 빛의 편지 · 마음 한 줄을 받을 때마다 이 기기에 남긴다. DOM에 의존하지 않는다 (node로 시험).
//
// - 기록: [{ key, kind, item_id, item_name, title, text, at, shareId, url, imageUrl, imageHeight, req, read }] — 최근 것이 앞
//   read는 읽었는지 — 사람이 직접 받아 본 편지는 true, 열지 않은 채 보관함에 도착한 편지만 false (예전 기록은 true로 되살린다)
//   imageUrl · imageHeight는 공유한 편지의 세로형 카드(/api/l/<id>/tall.png)와 그 높이 — 이미지로 저장 · 카카오톡 피드에 쓴다
//   kind는 "letter"(빛의 편지) · "perspective"(마음 한 줄). text는 본문 앞 120자(굵게 · [근거 N] 표시는 걷어 낸다)
//   마음 한 줄은 사람이 적은 문장을 남기지 않는다 — req에는 고른 감정(theme)만
// - key: 공유 ID가 있으면 "share|<id>", 없으면 "<kind>|<본문 전체(plainText)의 djb2 해시>" — 앞부분이 같은 다른 편지와 섞이지 않게
//   hash에는 늘 본문 해시를 둔다 (공유 전에 남긴 기록과 공유 링크로 다시 받은 기록을 같은 편지로 본다)
// - 같은 편지(key · 같은 공유 ID · 같은 본문 해시)는 한 번만 — 다시 받으면 자리 · 날짜는 그대로, 비어 있던 공유 정보만 채운다
// - 최대 50개 — 넘치면 가장 오래된 것부터 버린다

export const LETTERS_KEY = "vh-letters";
export const LETTERS_MAX = 50;
export const EXCERPT_LEN = 120;
const KINDS = new Set(["letter", "perspective"]);

// 화면 표시용 기호를 걷어 낸 본문 — **굵게** → 굵게, [근거 1, 2] → 지움, 줄바꿈 · 여러 칸은 한 칸으로
export function plainText(text) {
  return String(text ?? "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\s*\[근거\s*[\d,\s]+\]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

// 본문 앞 n자 — 잘렸으면 말줄임표를 붙인다
export function excerptOf(text, n = EXCERPT_LEN) {
  const t = plainText(text);
  return t.length > n ? `${t.slice(0, n).trimEnd()}…` : t;
}

// 첫 문장 — 목록에 한 줄로. 마침표가 없으면 그대로
export function firstSentence(text) {
  const t = plainText(text);
  const m = /^.+?[.!?。](?=\s|$)/.exec(t);
  return m ? m[0] : t;
}

// 앞 n문장 — 천체 서랍의 '도착한 편지' 발췌. 보관한 앞부분이 문장 중간에서 끊겼으면(…) 그대로 둔다
export function firstSentences(text, n = 2) {
  const t = plainText(text);
  const m = new RegExp(`^(?:.+?[.!?。](?=\\s|$)\\s*){1,${Math.max(1, n)}}`).exec(t);
  return m ? m[0].trim() : t;
}

// 간단한 문자열 해시(djb2, 32비트) — 36진수
export function djb2(s) {
  let h = 5381;
  const str = String(s ?? "");
  for (let i = 0; i < str.length; i += 1) h = ((h * 33) ^ str.charCodeAt(i)) >>> 0;
  return h.toString(36);
}

// 본문 전체의 해시 — 굵게 · 근거 표시 · 공백은 걷어 낸 뒤
export const textHash = (kind, text) => `${kind}|${djb2(plainText(text))}`;

// 같은 편지인지 가르는 열쇠 — 공유 ID, 없으면 종류 + 본문 전체 해시
export const letterKey = ({ kind, text, shareId = null }) => (shareId ? `share|${shareId}` : textHash(kind, text));

// 받은 편지 하나 — at은 ISO 시각 문자열. text는 본문 전체를 받아 해시를 만들고, 저장은 앞 120자만
// read: 사람이 직접 받아 본 편지면 true — 기본은 false(열지 않은 채 도착한 편지)
export function makeEntry({ kind, item_id = null, item_name = null, title = "", text = "", req = null, shareId = null, url = null,
                            imageUrl = null, imageHeight = null, read = false }, at = new Date().toISOString()) {
  return { key: letterKey({ kind, text, shareId }), hash: textHash(kind, text), kind, item_id, item_name, title: String(title ?? ""),
           text: excerptOf(text), at, shareId, url, imageUrl, imageHeight, req, read: !!read };
}

export const sameLetter = (a, b) => a.key === b.key || (!!a.shareId && a.shareId === b.shareId) || (!!a.hash && a.hash === b.hash);

// 서버의 공유 기록(GET /api/l/<id>.json) → 화면에 그릴 값. 근거 번호는 number (예전 응답의 n도 받는다)
export function sharedView(rec) {
  const kind = rec?.kind === "perspective" ? "perspective" : "letter";
  const isLetter = kind === "letter";
  return {
    kind, isLetter, item_id: rec?.item_id ?? null, item_name: rec?.item_name ?? null, text: String(rec?.text ?? ""),
    title: rec?.title || (isLetter ? `${rec?.item_name ?? ""}의 빛` : "마음 한 줄 곁의 사실"),
    departure: rec?.departure ?? null, created: rec?.created ?? null,
    cited: (Array.isArray(rec?.cited) ? rec.cited : []).map((c) => ({ number: c.number ?? c.n, title: c.title ?? "", url: c.url ?? "",
                                                                     source_type: c.source_type ?? "" })),
  };
}

// 최근 것부터 — 같은 시각이면 원래 순서 그대로
export function sortLetters(list) {
  return list.map((e, i) => [e, i]).sort((a, b) => (a[0].at < b[0].at ? 1 : a[0].at > b[0].at ? -1 : a[1] - b[1])).map(([e]) => e);
}

// 하나 더하기 — 새 배열을 돌려준다. 이미 있으면 비어 있던 공유 정보만 채운다 (다시 받아 읽었으면 읽음으로)
export function addLetter(list, entry, max = LETTERS_MAX) {
  const i = list.findIndex((e) => sameLetter(e, entry));
  if (i >= 0) {
    const old = list[i];
    const merged = { ...old, shareId: old.shareId ?? entry.shareId ?? null, url: old.url ?? entry.url ?? null,
                     imageUrl: old.imageUrl ?? entry.imageUrl ?? null, imageHeight: old.imageHeight ?? entry.imageHeight ?? null,
                     req: old.req ?? entry.req ?? null, read: !!old.read || !!entry.read };
    return list.map((e, k) => (k === i ? merged : e));
  }
  return sortLetters([entry, ...list]).slice(0, max);
}

// 공유 링크가 생겼을 때 — 그 편지의 shareId · url · 세로형 카드 주소와 높이를 고친다
export function setShare(list, key, { id, url, imageUrl, imageHeight }) {
  return list.map((e) => (e.key === key ? { ...e, shareId: id ?? e.shareId, url: url ?? e.url, imageUrl: imageUrl ?? e.imageUrl ?? null,
                                            imageHeight: imageHeight ?? e.imageHeight ?? null } : e));
}

export const removeLetter = (list, key) => list.filter((e) => e.key !== key);

export const findLetter = (list, key) => list.find((e) => e.key === key) ?? null;

// 저장된 기록을 되살린다 — 문자열(JSON) · 객체 모두. 깨진 기록 · 중복은 걸러 내고 최근 것부터 최대 50개
export function restoreLetters(saved, max = LETTERS_MAX) {
  let data = saved;
  if (typeof saved === "string") {
    try { data = JSON.parse(saved); } catch { data = null; }
  }
  const raw = Array.isArray(data?.letters) ? data.letters : [];
  let out = [];
  for (const e of raw) {
    if (!e || !KINDS.has(e.kind) || typeof e.key !== "string" || typeof e.at !== "string") continue;
    const entry = { key: e.key, hash: typeof e.hash === "string" ? e.hash : null, kind: e.kind, item_id: e.item_id ?? null,
                    item_name: e.item_name ?? null, title: String(e.title ?? ""), text: String(e.text ?? ""), at: e.at,
                    shareId: e.shareId ?? null, url: e.url ?? null, imageUrl: typeof e.imageUrl === "string" ? e.imageUrl : null,
                    imageHeight: Number.isInteger(e.imageHeight) && e.imageHeight > 0 ? e.imageHeight : null, req: e.req ?? null,
                    read: typeof e.read === "boolean" ? e.read : true };      // 읽음 표시 이전의 기록은 읽은 것으로 — 갑자기 '읽지 않음'이 쏟아지지 않게
    if (out.some((x) => sameLetter(x, entry))) continue;
    out.push(entry);
  }
  out = sortLetters(out);
  return out.slice(0, max);
}

export function serializeLetters(list) {
  return JSON.stringify({ v: 1, letters: list });
}

// 빛의 편지를 받은 천체 ID — 내 세계 지도의 ✉ 표식
export function letterItemIds(list) {
  return new Set(list.filter((e) => e.kind === "letter" && e.item_id).map((e) => e.item_id));
}

// ── 읽음 — 열지 않은 채 도착한 편지(read: false)를 메뉴 배지 · 지도 ✉ · 천체 서랍에 알린다 ──

// 그 편지를 읽은 것으로 — 새 배열. 이미 읽었거나 없는 열쇠면 같은 배열을 그대로 (저장할 필요가 없다)
export function markRead(list, key) {
  const i = list.findIndex((e) => e.key === key);
  if (i < 0 || list[i].read) return list;
  return list.map((e, k) => (k === i ? { ...e, read: true } : e));
}

// 읽지 않은 편지 수 — 빛의 편지 · 마음 한 줄 모두
export const unreadCount = (list) => list.filter((e) => !e.read).length;

// 그 천체의 읽지 않은 빛의 편지 수
export const unreadFor = (list, itemId) => list.filter((e) => !e.read && e.kind === "letter" && e.item_id === itemId).length;

// 읽지 않은 빛의 편지가 있는 천체 ID — 지도의 ✉ 표식을 또렷하게
export function unreadItemIds(list) {
  return new Set(list.filter((e) => !e.read && e.kind === "letter" && e.item_id).map((e) => e.item_id));
}

// 그 천체의 빛의 편지 하나 — 읽지 않은 것이 있으면 그중 가장 최근 것, 없으면 가장 최근 것 (목록은 최근 것이 앞)
export function letterFor(list, itemId) {
  if (!itemId) return null;
  const mine = list.filter((e) => e.kind === "letter" && e.item_id === itemId);
  return mine.find((e) => !e.read) ?? mine[0] ?? null;
}

// 목록의 날짜 "YYYY.MM.DD" — 그 사람의 현지 날짜
export function letterDate(at) {
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())}`;
}

// 짧은 날짜 — 올해면 "MM.DD", 다른 해면 "YYYY.MM.DD" (천체 서랍의 '도착한 편지 · 10.25')
export function letterDay(at, now = new Date()) {
  const full = letterDate(at);
  return full && full.slice(0, 4) === String(now.getFullYear()) ? full.slice(5) : full;
}
