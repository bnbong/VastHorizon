// 휴대폰 아래 시트 · 천체 3D 오버레이의 계산 — 배치 분류, 걸림 높이, 손을 뗀 뒤 다음 걸림 높이, 3D 해상도 · 시야. DOM에 의존하지 않는다 (node로 시험).
//
// - 배치(layout): desktop(오른쪽 서랍) · sheet(폭 650px 이하, 아래 시트) · split(눕힌 휴대폰, 오른쪽 서랍 + 왼쪽 3D).
//   CSS의 @media (max-width: 650px)와 같은 판정 문자열을 main.js가 matchMedia로 평가해 .app[data-layout]에 적는다
// - 걸림 높이(snap): 시트가 멈출 수 있는 보이는 높이 V(화면 아래 → 시트 윗변, px). closed · peek · half · full
// - 속도(velocity)는 px/ms, 위로 올리는 방향이 양수다
// - 시트 제어기(포인터 · 터치 처리, transform 적용)는 sheetui.js, 이 파일은 계산만

export const SNAPS = ["peek", "half", "full"];
export const SHEET_QUERY = "(max-width: 650px)";
export const SPLIT_QUERY = "(min-width: 651px) and (max-height: 500px) and (pointer: coarse)";

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

// 배치 — main.js는 matchMedia 결과를 넣는다. 시트 판정이 먼저다 (작은 휴대폰을 눕혀도 폭 650 이하면 시트)
export function classifyLayout({ sheet, split }) {
  return sheet ? "sheet" : split ? "split" : "desktop";
}

// 걸림 높이 (px, 정수)
//   full — 화면 높이에서 알림 띠와 머리(메뉴 단추 아래끝 66px + 여유)를 뺀 높이. 화면의 60~94%
//   peek — 엿보기 머리글을 잰 높이 + 안전 영역. 못 재면 화면의 30%. 132px ~ 화면의 42%
//   half — 화면의 55%. peek · full과 80px 이상 떨어지게. 그럴 자리가 없으면(낮은 화면) null
export const TOP_GAP = 72;
export const SNAP_GAP = 80;
export function snapHeights({ H, noticeH = 0, safeBottom = 0, peekContent = null }) {
  const full = Math.round(clamp(H - noticeH - TOP_GAP, H * 0.6, H * 0.94));
  const want = peekContent == null ? Math.round(H * 0.3) : peekContent + safeBottom;
  const peek = Math.round(Math.min(clamp(want, 132, Math.round(H * 0.42)), full - SNAP_GAP / 2));
  const lo = peek + SNAP_GAP, hi = full - SNAP_GAP;
  const half = lo > hi ? null : Math.round(clamp(Math.round(H * 0.55), lo, hi));
  return { peek, half, full };
}

// 내용 종류별 처음 걸림 높이 — 3D가 있는 천체는 3D가 크게 보이게 peek, 그 밖은 half
export function defaultSnap({ kind, has3d }) {
  return has3d ? "peek" : "half";
}

// 손을 뗀 뒤 멈출 걸림 높이 — 지금 높이에 속도를 180ms만큼 더한 자리와 가장 가까운 곳. 빠르게 튕기면 한 칸 더.
// closable이면 peek 아래로 충분히 내리거나 빠르게 내려 던졌을 때 "closed"
export const PROJECT_MS = 180, FLICK = 0.5, CLOSE_RATIO = 0.6, CLOSE_FLICK = 1.1;
export function nextSnap({ from, visible, velocity, snaps, closable = true }) {
  const projected = visible + velocity * PROJECT_MS;
  if (closable && (projected < snaps.peek * CLOSE_RATIO || (velocity <= -CLOSE_FLICK && visible < snaps.peek))) return "closed";
  const names = SNAPS.filter((n) => snaps[n] != null);
  let nearest = names[0];
  for (const n of names) if (Math.abs(snaps[n] - projected) < Math.abs(snaps[nearest] - projected)) nearest = n;
  if (Math.abs(velocity) >= FLICK && nearest === from) {
    const i = names.indexOf(nearest) + (velocity > 0 ? 1 : -1);
    if (i >= 0 && i < names.length) nearest = names[i];
  }
  return nearest;
}

// 키보드 · 손잡이용 한 칸 이동 — dir +1(올림) · -1(내림). 끝이면 그대로, peek 아래(닫기)로는 가지 않는다
export function stepSnap(from, dir, snaps) {
  const names = SNAPS.filter((n) => snaps[n] != null);
  let i = names.indexOf(from);
  if (i < 0) {                                  // 지금 높이가 없는 걸림 높이(낮은 화면의 half)면 그 값 근처에서
    const v = snaps[from] ?? 0;
    i = dir > 0 ? names.findIndex((n) => snaps[n] > v) - 1 : names.findIndex((n) => snaps[n] >= v);
    if (i < 0) i = dir > 0 ? -1 : names.length;
  }
  return names[clamp(i + Math.sign(dir), 0, names.length - 1)];
}

// 끄는 동안의 높이 — full보다 위로는 넘친 양의 25%만, 최대 24px까지. peek 아래로는 그대로 따라와 닫힐 것이 보이게 (0 아래로는 안 간다)
export function rubberBand(v, min, max) {
  if (v > max) return max + Math.min(24, (v - max) * 0.25);
  return Math.max(0, v);
}

// 포인터 표본 [{ t(ms), y(client px) }] → 속도(px/ms, 위로가 양수). 마지막 표본에서 100ms 안의 것만 쓴다
export function velocityOf(samples) {
  if (!samples || samples.length < 2) return 0;
  const last = samples[samples.length - 1];
  const recent = samples.filter((s) => last.t - s.t <= 100);
  if (recent.length < 2) return 0;
  const first = recent[0], dt = last.t - first.t;
  return dt > 0 ? (first.y - last.y) / dt : 0;
}

// 엿보기 머리글의 투명도 — peek에서 1, half(없으면 full)에 가까워질수록 0
export function peekOpacity(V, snaps) {
  const top = snaps.half ?? snaps.full;
  if (!(top > snaps.peek)) return V <= snaps.peek ? 1 : 0;
  return clamp((top - V) / (top - snaps.peek), 0, 1);
}

// 3D 오버레이의 픽셀 비율 — 화소 수 예산(budget) 안에서. 기기 비율 · 2 중 작은 값을 넘지 않고 0.25 단위로 내린다. 최소 min
export function bodyPixelRatio({ dpr, w, h, budget, min = 1 }) {
  const area = w * h;
  const cap = Math.min(dpr || 1, 2, area > 0 && budget ? Math.sqrt(budget / area) : Infinity);
  return Math.max(min, Math.floor(cap * 4) / 4);
}

// 3D 시야 맞춤 — 캔버스(W×H)는 그대로 두고, 시트에 가리지 않는 영역 [top, bottom]의 가운데에 천체가 오게 한다.
//   s = H/2 - yc (양수면 천체를 위로). 가상 높이 Hv = H + 2|s|의 시야에서 H만큼 잘라 보면(setViewOffset) 가운데가 yc에 온다 (scene.js applyInset과 같은 방식)
//   카메라 거리 — 반지름 extent인 천체가 화면에서 R = 0.40 × min(W, bottom - top) px로 보이게. fov는 도(°)
//   반환: { yc, s, Hv, view(setViewOffset 인자, s = 0이면 null), aspect, distance, visible(보이는 높이가 120px 이상) }
export const MIN_REGION = 120;
export function fitBodyView({ W, H, top, bottom, extent = 1, fov = 24 }) {
  const yc = (top + bottom) / 2;
  const s = Math.round(H / 2 - yc);
  const Hv = H + 2 * Math.abs(s);
  const view = s === 0 ? null : { fullWidth: W, fullHeight: Hv, x: 0, y: s > 0 ? 2 * s : 0, width: W, height: H };
  const R = 0.4 * Math.max(1, Math.min(W, bottom - top));
  const distance = (extent * Hv) / (2 * R * Math.tan((fov * Math.PI) / 360));
  return { yc, s, Hv, view, aspect: W / Hv, distance, visible: bottom - top >= MIN_REGION };
}
