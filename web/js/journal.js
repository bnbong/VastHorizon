// 알아간 빛의 기록 — 내 세계는 날마다 지워지지 않고 쌓인다. Three.js · DOM에 의존하지 않는다 (node로 시험).
//
// - 기록: [{ id, name, km, ra, dec, group, at, mag?, seen? }] — km가 없으면(거리 미확인) 기록에는 남고 지도 · 가장 먼 빛에는 넣지 않는다
//   mag(겉보기 등급)는 오늘 밤 내 빛이 쓰고 새로 담는 기록에만 있다. seen은 두 눈으로 본 날 (seen.js)
// - 오늘의 여정: at(그 사람의 현지 날짜)이 오늘인 기록
// - 지우기는 사람이 직접 고를 때만 (resetWorld)

import { cleanSeen } from "./seen.js";

export const WORLD_KEY = "vh-world";

// 현지 날짜 "YYYY-MM-DD" — UTC로 자르면 한국에서는 오전 9시에 날짜가 바뀐다
export function localDate(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// 저장된 기록을 되살린다. 예전 형식({ date, km, name, visited })도 날짜와 관계없이 그대로 잇는다
export function restoreVisited(saved, today) {
  const list = Array.isArray(saved?.visited) ? saved.visited : [];
  const seen = new Set();
  const out = [];
  for (const v of list) {
    if (!v?.id || seen.has(v.id)) continue;
    seen.add(v.id);
    const entry = { ...v, km: v.km > 0 ? v.km : null, at: v.at ?? saved.date ?? today };
    // 두 눈으로 본 날 — 정리한 결과가 비면 키를 아예 두지 않는다 (예전 기록과 왕복 비교가 그대로 같게)
    const eyes = "seen" in v ? cleanSeen(v.seen) : null;
    if (eyes) entry.seen = eyes;
    else delete entry.seen;
    out.push(entry);
  }
  return out;
}

export function serialize(visited) {
  return JSON.stringify({ v: 2, visited });
}

export function entryOf(item, today) {
  return { id: item.id, name: item.name, km: item.distance_km > 0 ? item.distance_km : null,
           ra: item.ra_deg ?? null, dec: item.dec_deg ?? null, group: item.group ?? null, at: today,
           mag: Number.isFinite(item.attrs?.["겉보기 등급"]) ? item.attrs["겉보기 등급"] : null };
}

// 가장 먼 빛 — 거리를 아는 기록 중 가장 먼 것. 없으면 지평선
export function reachOf(visited, horizonKm) {
  let best = { km: horizonKm, name: "지평선", id: null };
  for (const v of visited) if (v.km > best.km) best = { km: v.km, name: v.name, id: v.id };
  return best;
}

export const todays = (visited, today) => visited.filter((v) => v.at === today);

// 가장 최근에 알아간 것부터
export const recent = (visited, n = visited.length) => visited.slice(-n).reverse();
