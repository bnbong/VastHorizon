// 가까이서 본 모습의 크기와 거리 — 지도의 근접 모습(details.js)과 카메라 비행(map.js select)이 같은 표를 쓴다.
// Three.js에 의존하지 않는다 (node로 시험).
//
//   크기   근접 모습 스프라이트 한 변 (지도 단위). 사진 은하 5 · 사진 기타 3.5 · 별 1.5 · 사진 없는 성단 · 성운 3.2
//   거리   스프라이트가 화면에서 보이는 영역의 짧은 변 FILL(45%)을 차지하는 자리
//   블랙홀 은하 중심의 가르강튀아 — 줌 직후에는 보이지 않고, 더 들어가면(flyInto · 손가락 확대) 떠오른다

export const NEAR = { star: 26, photo: 70, deep: 45 };   // 이 거리 안에서 나타나기 시작한다 (지도 단위)
export const SIZE = { star: 1.5, photo: 5, cluster: 3.2, nebula: 3.2, bh: 2.4 };
export const FILL = 0.45;          // 근접 모습이 짧은 변에서 차지하는 비율
export const STAR_FILL = 0.9;      // 별은 원반이 사각형의 30%뿐이라 사각형을 짧은 변의 90%로 — 원반 ≈ 27%, 코로나 · 빛살은 화면 가장자리 가까이까지
export const BH_FILL = 0.5;        // 블랙홀 사각형이 짧은 변에서 차지하는 비율 (원반이 사각형의 80%쯤이라 보이는 크기는 40%쯤)
export const HD_RANGE = 2;         // 줌 거리의 이 배 안으로 들어오면 고해상도 사진(data/messier/hd)으로 바꾼다

// 근접 모습이 있는 천체인가 — 하늘에 놓인 별 · 메시에 천체 (details.js DetailLayer.items와 같은 판정)
export const hasCloseup = (p) => !!p && (p.group === "star" || p.group === "messier") && p.placement === "sky";

// 근접 모습의 크기. photo: 그 메시에 천체의 사진이 있는가 (credits.json). 근접 모습이 없으면 null
export function closeupSize(p, photo = false) {
  if (!hasCloseup(p)) return null;
  if (p.group === "star") return SIZE.star;
  if (photo) return /은하|LINER/.test(p.kind ?? "") ? SIZE.photo : SIZE.photo * 0.7;
  return SIZE.cluster;
}

// 근접 모습이 짧은 변에서 차지할 비율 — 별은 STAR_FILL, 나머지는 FILL
export const closeupFill = (p) => (p?.group === "star" ? STAR_FILL : FILL);

export function closeupNear(p, photo = false) {
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

// 고해상도 사진 교체 — 받은 것은 최근에 쓴 순서로 limit장까지만 두고, 넘치면 가장 오래된 것을 512로 되돌린다.
// 텍스처 일은 주입한 함수로 (node로 시험): load(it, ok(tex), fail()) · apply(it, tex) · revert(it) · discard(tex).
// it.hd: 없음 → "loading" → "loaded" | "failed" (실패한 사진은 512 그대로, 다시 요청하지 않는다)
export const HD_LIMIT = 6;
export class HdSwap {
  constructor({ load, apply, revert, discard = () => {}, limit = HD_LIMIT }) {
    Object.assign(this, { load, apply, revert, discard, limit });
    this.order = [];                         // 받은 것 — 오래 안 쓴 것부터
  }

  // 가까이서 보고 있다 — 받은 적 없으면 요청하고, 받았으면 최근으로 올린다
  want(it) {
    if (it.hd === "loaded") { this.touch(it); return; }
    if (it.hd) return;                       // 받는 중 · 실패
    it.hd = "loading";
    this.load(it, (tex) => {
      if (it.hd !== "loading") { this.discard(tex); return; }
      this.apply(it, tex);
      it.hd = "loaded";
      this.order.push(it);
      while (this.order.length > this.limit) {
        const old = this.order.shift();
        this.revert(old);
        old.hd = null;                        // 다시 가까이 가면 또 받는다
      }
    }, () => { if (it.hd === "loading") it.hd = "failed"; });
  }

  touch(it) {
    const i = this.order.indexOf(it);
    if (i >= 0 && i !== this.order.length - 1) this.order.push(...this.order.splice(i, 1));
  }
}
