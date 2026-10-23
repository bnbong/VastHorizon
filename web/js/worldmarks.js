// 알아간 빛의 표식과 내 세계 지도의 글 — Three.js · DOM에 의존하지 않는다 (node로 시험).
//
// 표식 (design-proposal/DESIGN_HANDOFF.md 5절) — 하늘 · 천체 목록 · 서랍 · 내 세계에서 같은 모양
//   알아감        : 살구색 채운 원 안의 ✦ · 약한 후광 · 어두운 남보라 이름표 · '나'와 실선
//   아직 만나지 않음: 빈 점선 원 · 연결선 없음 · 이름은 기본으로 숨김
//   현재 선택      : 알아간 표식 바깥의 흰 1px 고리

import { distanceText, measure } from "./astro.js";
import { todays } from "./journal.js";

// 표식 상태 — knownIds: Set (알아간 천체 ID), selectedId: 지금 고른 천체
export function markState(id, knownIds, selectedId = null) {
  return { known: !!id && knownIds.has(id), selected: !!id && id === selectedId };
}

// 표식 HTML — 목록 · 서랍 같은 DOM 자리에 (지도 · 하늘의 3D 표식도 같은 클래스를 쓴다)
export function markHtml(known) {
  return known ? '<span class="known-mark" aria-hidden="true">✦</span>' : '<span class="unknown-mark" aria-hidden="true"></span>';
}

// 오늘 새로 알아간 빛의 수 — 기록의 날짜(at, 그 사람의 현지 날짜)가 오늘인 것
export function todayNewCount(visited, today) {
  return todays(visited, today).length;
}

// 내 세계 지도의 머리글 — 눈썹 · 두 줄 제목(둘째 줄은 살구색) · 범례. 알아간 빛이 없으면 기다리는 문장
export function worldHeading(visited, today) {
  const count = visited.length, fresh = todayNewCount(visited, today);
  const n = (x) => x.toLocaleString("ko-KR");
  return {
    kicker: `오늘 새로 알아간 빛 ${n(fresh)}`,
    lines: count ? ["내 세계는 오늘,", "여기까지 닿았습니다."] : ["첫 번째 빛을", "기다리고 있어요."],
    known: `알아간 빛 ${n(count)}개`,
    unknown: "아직 만나지 않은 빛",
    empty: count === 0,
  };
}

// 요약 카드의 큰 숫자 — "약 254만" + "광년". 지평선처럼 가까운 거리는 측정값 그대로 ("4.7" + "km")
export function farthestParts(km) {
  if (!(km > 0)) return { value: "0", unit: "km" };
  if (km < 1e4) return measure(km);
  const text = distanceText(km), cut = text.lastIndexOf(" ");
  return { value: text.slice(0, cut), unit: text.slice(cut + 1) };
}

// 이름표를 달 천체 — 많아지면 겹치지 않게 가장 최근 max개와 지금 고른 천체만. 나머지는 표식만 (마우스를 올리면 이름)
export function labelledIds(visited, selectedId = null, max = 10) {
  const ids = new Set(visited.slice(-max).map((v) => v.id));
  if (selectedId && visited.some((v) => v.id === selectedId)) ids.add(selectedId);
  return ids;
}

// 지도의 점선 원이 보이는 정도 0~1 — 카메라 거리가 그 점의 반지름(지도 단위)의 from배 이하면 1, to배 이상이면 0.
// 기본 시점(가장 먼 알아간 빛 반지름의 2.8배 거리)에서는 '나' 가까이 몰린 원(예: 1광일 안쪽)이 숨고, 확대하면 나타난다
export function nearFade(camDist, radius, from = 6, to = 8) {
  const k = camDist / Math.max(radius, 1e-6);
  return k <= from ? 1 : k >= to ? 0 : 1 - (k - from) / (to - from);
}
