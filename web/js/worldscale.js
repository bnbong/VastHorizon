// 내 세상이 얼마나 넓은가 — 와닿게 하는 계산. Three.js에 의존하지 않는다 (node로 시험).
//
// - 세상 안: 카탈로그 천체 중 지구로부터 거리가 내 세상의 반지름 안인 것 (우주 지도 점의 km)
// - 비유: 지어낸 수치 없이 계산만 — 빛으로 걸리는 시간, 지구를 지름 1mm 모래알로 줄인 모형, 처음 세상(지평선 4.7km)과의 부피 비
//   기준값: 지구 평균 지름 12,742km (위키백과 「지구」), 빛의 속도 299,792.458km/s (정의값)

import { horizonKm, lightTime } from "./astro.js";

export const EARTH_DIAMETER_KM = 12742;
const LY_KM = 9460730472580.8;
const MOON_KM = 384400;
const SUN_KM = 149597870.7;

const GROUP_WORD = { solar_system: "태양계 천체", human_made: "탐사선 · 위성", star: "별", messier: "성운 · 성단 · 은하" };

// 내 세상 안의 천체 — 거리가 있는 지도 점 중 km ≤ 반지름. 가까운 순
export function insideWorld(points, worldKm) {
  return points.filter((p) => p.km > 0 && p.km <= worldKm).sort((a, b) => a.km - b.km);
}

// 내가 알아간 천체 / 그 거리 안에서 아직 알아가지 않은 천체 — 거리 안에 있다고 내 세상이 아니다. 알아간 것만 내 세상
// (개인이 아직 모른다는 배움의 은유다. 천체의 물리적 상태가 정해지지 않았다는 뜻이 아니다)
export function knownAndUnknown(points, knownIds, reachKm) {
  const within = insideWorld(points, reachKm);
  return { known: within.filter((p) => knownIds.has(p.id)), unknown: within.filter((p) => !knownIds.has(p.id)) };
}

// 이번에 새로 거리 안에 들어온 천체 — (이전 거리, 새 거리]
export function newlyInside(points, fromKm, toKm) {
  return points.filter((p) => p.km > fromKm && p.km <= toKm).sort((a, b) => a.km - b.km);
}

export function countByGroup(points) {
  const counts = {};
  for (const p of points) counts[p.group] = (counts[p.group] ?? 0) + 1;
  return counts;
}

// "달, 태양, 화성 외 12개" — 가까운 것부터 이름 몇 개
export function namesLine(points, max = 3) {
  if (!points.length) return "";
  const names = points.slice(0, max).map((p) => p.name);
  return points.length > max ? `${names.join(", ")} 외 ${points.length - max}개` : names.join(", ");
}

export function groupLine(counts) {
  return Object.entries(GROUP_WORD).filter(([g]) => counts[g]).map(([g, word]) => `${word} ${counts[g]}`).join(" · ");
}

// 길이를 사람이 읽는 말로 (모형 크기용) — mm · cm · m · km · 만 km · 억 km
export function lengthText(km) {
  const n = (v, d = 1) => (+v.toFixed(d)).toLocaleString("ko-KR");
  if (km < 1e-5) return `${n(km * 1e6)} mm`;
  if (km < 1e-3) return `${n(km * 1e5)} cm`;
  if (km < 1) return `${n(km * 1e3, 0)} m`;
  if (km < 1e4) return `${n(km, km < 10 ? 1 : 0)} km`;
  if (km < 1e8) return `${n(km / 1e4)}만 km`;
  return `${n(km / 1e8)}억 km`;
}

// 지구를 지름 1mm 모래알로 줄인 모형에서 이 반지름의 길이
export function sandModelKm(km) {
  return (km / EARTH_DIAMETER_KM) * 1e-6;
}

function sandCompare(modelKm) {
  if (modelKm > SUN_KM) return "지구에서 태양까지보다 멉니다";
  if (modelKm > MOON_KM) return "지구에서 달까지보다 멉니다";
  if (modelKm > EARTH_DIAMETER_KM * Math.PI) return "실제 지구를 한 바퀴 도는 것보다 깁니다";
  if (modelKm > 400) return "서울에서 부산까지보다 깁니다";
  return null;
}

// 처음 세상(지평선)과의 부피 비
export function volumeRatio(km) {
  return Math.pow(km / horizonKm(), 3);
}

const SUP = "⁰¹²³⁴⁵⁶⁷⁸⁹";
export function powerText(x) {
  if (x < 1e4) return `${Math.round(x).toLocaleString("ko-KR")}배`;
  const e = Math.floor(Math.log10(x));
  return `10${[...String(e)].map((d) => SUP[d]).join("")}배`;
}

// 와닿게 하는 비유 세 가지 — [{ label, value, note }]
export function analogies(km) {
  const model = sandModelKm(km);
  const out = [{ label: "빛으로", value: lightTime(km), note: km >= LY_KM ? "지금 보는 빛은 그만큼 옛날에 떠난 빛입니다" : null }];
  if (km > horizonKm() * 1.01) {
    out.push({ label: "지구를 1mm 모래알로 줄이면", value: lengthText(model), note: sandCompare(model) });
    out.push({ label: "그 거리까지의 공간은 처음 세상보다", value: powerText(volumeRatio(km)), note: "모두 알아간 것은 아닙니다. 아직 알아가지 않은 곳이 훨씬 많습니다" });
  }
  return out;
}

// 넓어진 배율 (반지름) — "+1,234배"
export function growthText(fromKm, toKm) {
  const r = toKm / fromKm;
  return r < 1e4 ? `${(+r.toPrecision(r < 10 ? 2 : 3)).toLocaleString("ko-KR")}배` : powerText(r);
}
