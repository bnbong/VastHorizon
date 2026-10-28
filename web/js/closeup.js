// 가까이서 본 모습의 크기와 거리 — 지도의 근접 모습(details.js)과 카메라 비행(map.js select)이 같은 표를 쓴다.
// Three.js에 의존하지 않는다 (node로 시험).
//
//   크기   근접 모습 스프라이트 한 변 (지도 단위). 사진 은하 5 · 사진 기타 3.5 · 별 1.5 · 사진 없는 성단 · 성운 3.2
//   거리   스프라이트가 화면에서 보이는 영역의 짧은 변 FILL(45%)을 차지하는 자리
//   블랙홀 은하 중심의 가르강튀아 — 줌 직후에는 보이지 않고, 더 들어가면(flyInto · 손가락 확대) 떠오른다.
//          블랙홀 자체인 점(궁수자리 A*)은 은하 사진 없이 블랙홀이 바로 근접 모습

export const NEAR = { star: 26, photo: 70, deep: 45 };   // 이 거리 안에서 나타나기 시작한다 (지도 단위)
export const SIZE = { star: 1.5, photo: 5, cluster: 3.2, nebula: 3.2, bh: 2.4 };
export const FILL = 0.45;          // 근접 모습이 짧은 변에서 차지하는 비율
export const STAR_FILL = 0.9;      // 별은 원반이 사각형의 30%뿐이라 사각형을 짧은 변의 90%로 — 원반 ≈ 27%, 코로나 · 빛살은 화면 가장자리 가까이까지
export const BH_FILL = 0.5;        // 블랙홀 사각형이 짧은 변에서 차지하는 비율 (원반이 사각형의 80%쯤이라 보이는 크기는 40%쯤)
export const HD_RANGE = 2;         // 줌 거리의 이 배 안으로 들어오면 고해상도 사진(data/messier/hd)으로 바꾼다

// 블랙홀 자체인 지도 점 — 은하 사진 없이 블랙홀이 곧 근접 모습 (궁수자리 A*)
export const isBlackHolePoint = (p) => !!p && p.group === "milky_way" && p.placement === "sky" && /블랙홀/.test(p.kind ?? "");

// 근접 모습이 있는 천체인가 — 하늘에 놓인 별 · 메시에 천체 · 블랙홀 (details.js DetailLayer.items와 같은 판정)
export const hasCloseup = (p) => !!p && p.placement === "sky" && (p.group === "star" || p.group === "messier" || isBlackHolePoint(p));

// 근접 모습의 크기. photo: 그 메시에 천체의 사진이 있는가 (credits.json). 근접 모습이 없으면 null
export function closeupSize(p, photo = false) {
  if (!hasCloseup(p)) return null;
  if (isBlackHolePoint(p)) return SIZE.bh;
  if (p.group === "star") return SIZE.star;
  if (photo) return /은하|LINER/.test(p.kind ?? "") ? SIZE.photo : SIZE.photo * 0.7;
  return SIZE.cluster;
}

// 근접 모습이 짧은 변에서 차지할 비율 — 별은 STAR_FILL, 블랙홀 점은 BH_FILL, 나머지는 FILL
export const closeupFill = (p) => (p?.group === "star" ? STAR_FILL : isBlackHolePoint(p) ? BH_FILL : FILL);

export function closeupNear(p, photo = false) {
  if (isBlackHolePoint(p)) return NEAR.deep;
  return p.group === "star" ? NEAR.star : photo ? NEAR.photo : NEAR.deep;
}

// 크기 size인 것이 화면 짧은 변의 fill을 차지하는 카메라 거리. fov: 세로 화각(도), aspect: 가로/세로
export function viewDistance(size, fov, aspect = 1, fill = FILL) {
  const tan = Math.tan((fov * Math.PI) / 360);
  return size / (2 * tan * fill * Math.min(1, aspect));
}

// 서랍 · 시트로 비킨 시야(scene.js Stage.applyInset의 setViewOffset)를 실제로 보이는 영역의 화각 · 비율로 바꾼다.
// 가상 화면(w + x) × (h + y)에 화각을 맞추므로 화면 배율은 (h + y)/h배 커지고, 천체는 남은 영역 (w − x) × (h − y)의 가운데에 온다.
// 반환한 { fov, aspect }를 viewDistance에 넘기면 남은 영역의 짧은 변 기준 거리가 된다
export function insetFrame({ width, height, fov, insetX = 0, insetY = 0 }) {
  const x = insetX && width > insetX ? insetX : 0, y = insetY && height > insetY ? insetY : 0;   // applyInset과 같은 조건
  const w = width - x, h = height - y;
  const tan = (Math.tan((fov * Math.PI) / 360) * h) / (height + y);
  return { fov: y ? (Math.atan(tan) * 360) / Math.PI : fov, aspect: w / h };
}

// 블랙홀을 보러 더 들어간 거리 — 사각형(SIZE.bh)이 짧은 변의 BH_FILL을 차지하는 자리. 은하 줌 거리보다 늘 안쪽
export function bhViewDistance(frame, galaxyView = Infinity) {
  return Math.min(viewDistance(SIZE.bh, frame.fov, frame.aspect, BH_FILL), galaxyView * 0.6);
}

// 블랙홀이 떠오르는 정도 (0~1) — 은하 줌 거리(galaxyView)에서는 0, 블랙홀 거리(bhView)까지 들어가면 1.
// 화면 크기에 따라 두 거리가 함께 달라지므로(세로 화면은 멀리서 본다) 고정 거리 대신 둘 사이의 비율로 정한다
export function bhFade(d, galaxyView, bhView) {
  const start = bhView + (galaxyView - bhView) * 0.75, full = bhView * 1.1;
  if (d >= start) return 0;
  if (d <= full) return 1;
  const t = (start - d) / (start - full);
  return t * t * (3 - 2 * t);
}

// 고해상도 사진 교체 — 근접 모습이 몰린 곳(처녀자리 은하단의 메시에 은하 16개)에서도 받았다 되돌렸다를 되풀이하지 않게.
//   · 판정은 interval(250ms)마다 한 번, 요청은 한 번에 한 건 (받거나 실패한 뒤 다음)
//   · 받은 것이 limit장이면 새로 받지 않고 512 그대로 — 이미 받은 HD는 그대로 둔다
//   · 자리를 비우는(512로 되돌리는) 것은 새로 받을 것이 있을 때만, 그것도 keep(절두체 안이거나 줌 범위 안)이 아닌 것 중 가장 오래 안 쓴 것.
//     예외로 고른 천체(want의 첫 번째, selected)는 늘 HD — 자리가 없으면 keep인 것 중 가장 우선순위가 낮은 것을 비운다
//   · 되돌린 것은 cooldown(10초) 동안 다시 요청하지 않는다
// 텍스처 일은 주입한 함수로 (node로 시험): load(it, ok(tex), fail()) · apply(it, tex) · revert(it) · discard(tex).
// it.hd: 없음 → "loading" → "loaded" | "failed" (실패한 사진은 512 그대로, 다시 요청하지 않는다)
export const HD_LIMIT = 8;           // 1024² RGB ≈ 4MB × 8 = GPU 32MB
export const HD_INTERVAL = 250;      // 판정 간격 (ms)
export const HD_COOLDOWN = 10000;    // 되돌린 뒤 다시 요청하지 않는 시간 (ms)
export class HdSwap {
  constructor({ load, apply, revert, discard = () => {}, limit = HD_LIMIT, interval = HD_INTERVAL, cooldown = HD_COOLDOWN }) {
    Object.assign(this, { load, apply, revert, discard, limit, interval, cooldown });
    this.loaded = new Set();                 // 받아서 붙인 것
    this.pending = null;                     // 받는 중인 것 (한 번에 하나)
    this.last = -Infinity;                   // 마지막 판정 시각
  }

  // 판정할 때가 되었는가 (interval마다)
  due(now) { return now - this.last >= this.interval; }

  // now: ms. want: HD로 보고 싶은 것, 우선순위 순 (고른 천체 먼저, 그다음 카메라에 가까운 순).
  // keep(it): 되돌리면 안 되는 것 (절두체 안이거나 줌 범위 안). selected: 고른 천체 (늘 HD)
  tick(now, want, { keep = () => false, selected = null } = {}) {
    if (now - this.last < this.interval) return;
    this.last = now;
    for (const it of want) if (it.hd === "loaded") it.hdUsed = now;   // 최근에 쓴 것 — 되돌릴 때 오래 안 쓴 것부터
    if (this.pending) return;
    const next = want.find((it) => !it.hd && (it === selected || !((it.hdCool ?? -Infinity) > now)));   // 고른 천체는 쿨다운도 넘는다
    if (!next) return;
    if (this.loaded.size >= this.limit && !this.evict(now, keep, next === selected ? want : null, selected)) return;
    this.request(next);
  }

  // 자리 하나를 비운다 — keep이 아닌 것 중 가장 오래 안 쓴 것.
  // 없으면 고른 천체를 받을 때만(want를 넘겼을 때) want에 없는 것 중 가장 오래 안 쓴 것, 그것도 없으면 want에서 가장 뒤의 것
  evict(now, keep, want, selected) {
    const oldest = (pick) => {
      let v = null;
      for (const it of this.loaded) if (it !== selected && pick(it) && (!v || (it.hdUsed ?? 0) < (v.hdUsed ?? 0))) v = it;
      return v;
    };
    let victim = oldest((it) => !keep(it));
    if (!victim && want) victim = oldest((it) => !want.includes(it)) ?? [...want].reverse().find((it) => it !== selected && this.loaded.has(it)) ?? null;
    if (!victim) return false;
    this.loaded.delete(victim);
    this.revert(victim);
    victim.hd = null;
    victim.hdCool = now + this.cooldown;     // 곧바로 다시 받지 않는다
    return true;
  }

  request(it) {
    it.hd = "loading";
    this.pending = it;
    this.load(it, (tex) => {
      if (this.pending === it) this.pending = null;
      if (it.hd !== "loading") { this.discard(tex); return; }
      this.apply(it, tex);
      it.hd = "loaded";
      this.loaded.add(it);
    }, () => {
      if (this.pending === it) this.pending = null;
      if (it.hd === "loading") it.hd = "failed";
    });
  }
}
