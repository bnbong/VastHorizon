// 두 눈으로 본 빛 — 담은 빛을 실제 하늘에서 직접 본 날을 기록한다. DOM에 의존하지 않는다 (node로 시험 — tests/js/seen.test.mjs).
//
// - 기록은 알아간 빛 기록(world.visited, localStorage "vh-world")의 항목에 선택 필드로 붙는다:
//   seen: [{ at: "2026-10-27", place?: { name, lat?, lon? } }] — 날짜는 그 사람의 현지 날짜, 시각은 남기지 않는다
// - 하루에 한 번만. 되돌리기는 그날 기록만 지운다
// - 위치는 소수 첫째 자리(약 11km)까지만 남긴다. 위치를 받지 못했으면 이름만

export const SEEN_MAX = 50;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

const round1 = (x) => Math.round(x * 10) / 10;

// 실제 달력 날짜인가 — 형식이 맞아도 2026-02-30 · 2026-13-01 같은 값은 버린다 (윤년의 2월 29일은 남는다)
export function isCalendarDay(day) {
  if (typeof day !== "string" || !DAY.test(day)) return false;
  const [y, m, d] = day.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
}

function cleanPlace(p) {
  if (!p || typeof p !== "object") return null;
  const out = {};
  if (typeof p.name === "string" && p.name) out.name = p.name;
  if (Number.isFinite(p.lat) && Number.isFinite(p.lon)) { out.lat = round1(p.lat); out.lon = round1(p.lon); }
  return Object.keys(out).length ? out : null;
}

// 저장된 seen 정리 — 배열이 아니면 버리고, 실제 달력 날짜가 아닌 원소 · 같은 날짜(먼저 것을 남긴다)를 걸러, 날짜순으로 최근 50개만.
// 결과가 비면 null (그때는 seen 키를 아예 두지 않는다)
export function cleanSeen(raw) {
  if (!Array.isArray(raw)) return null;
  const days = new Set();
  const out = [];
  for (const s of raw) {
    if (!s || !isCalendarDay(s.at) || days.has(s.at)) continue;
    days.add(s.at);
    const place = cleanPlace(s.place);
    out.push(place ? { at: s.at, place } : { at: s.at });
  }
  out.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0));
  return out.length ? out.slice(-SEEN_MAX) : null;
}

export function seenToday(entry, today) {
  return !!entry?.seen?.some((s) => s.at === today);
}

// 오늘 두 눈으로 봤다고 남긴다 — 새 배열. 이미 오늘 기록이 있거나 그 천체가 기록에 없으면 같은 배열을 그대로
export function markSeen(visited, id, today, place = null) {
  const i = visited.findIndex((v) => v.id === id);
  if (i < 0 || seenToday(visited[i], today)) return visited;
  const p = cleanPlace(place);
  const seen = cleanSeen([...(visited[i].seen ?? []), p ? { at: today, place: p } : { at: today }]);
  const out = visited.slice();
  out[i] = { ...visited[i], seen };
  return out;
}

// 오늘 기록만 지운다 (실수 되돌리기). 마지막 기록이면 seen 키가 사라진다
export function unmarkSeen(visited, id, today) {
  const i = visited.findIndex((v) => v.id === id);
  if (i < 0 || !seenToday(visited[i], today)) return visited;
  const { seen, ...rest } = visited[i];
  const left = seen.filter((s) => s.at !== today);
  const out = visited.slice();
  out[i] = left.length ? { ...rest, seen: left } : rest;
  return out;
}

// 한 번이라도 직접 본 천체 수 (지구 제외)
export function seenCount(visited, earthId = "Q2") {
  return visited.filter((v) => v.id !== earthId && v.seen?.length).length;
}

export function seenIds(visited) {
  return new Set(visited.filter((v) => v.seen?.length).map((v) => v.id));
}

// 서랍 아래 한 줄 — { count, last: "10.27", text: "직접 본 날 3번 · 마지막 10.27" } (기록이 없으면 count 0 · text "")
export function seenSummary(entry) {
  const list = entry?.seen ?? [];
  if (!list.length) return { count: 0, last: null, text: "" };
  const last = list[list.length - 1].at.slice(5).replace("-", ".");
  return { count: list.length, last, text: `직접 본 날 ${list.length}번 · 마지막 ${last}` };
}
