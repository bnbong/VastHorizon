// 애니메이션 대기열 — Three.js에 의존하지 않는다 (node로 시험).
//
// 한 프레임에서 처리하는 것은 프레임 시작 때 있던 애니메이션뿐이다.
// 완료 콜백이 다음 애니메이션을 등록하면 그것은 보존해 다음 프레임부터 진행한다. (리뷰 P1)
// cancelAll()은 세대 번호를 올려, 이전 세대 애니메이션을 같은 프레임 안에서도 더 진행하지 않는다
// (콜백이 모드를 바꾸며 연출을 취소하는 경우).

export const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

// 두 점 사이를 원점 기준 구면으로 보간 — 방향은 각도로 돌리고 길이는 선형으로. a · b · 결과는 [x, y, z].
// 직선 보간(lerp)은 원점을 사이에 둔 반대 방향끼리면 중간에 원점을 지나 길이가 0이 된다 (하늘 보기 카메라가 뒤집히던 문제).
// 정확히 반대면 수평으로 돌아가는 수직 축(위쪽 y 기준, 거의 수직이면 x 기준)을 경유한다
export function slerpPoint(a, b, k) {
  const la = Math.hypot(...a), lb = Math.hypot(...b);
  if (la < 1e-12 || lb < 1e-12) return a.map((v, i) => v + (b[i] - v) * k);
  const ua = a.map((v) => v / la), ub = b.map((v) => v / lb);
  const dot = Math.max(-1, Math.min(1, ua[0] * ub[0] + ua[1] * ub[1] + ua[2] * ub[2]));
  const theta = Math.acos(dot);
  let w = ub.map((v, i) => v - dot * ua[i]);        // ua에 수직인 b 쪽 성분
  let lw = Math.hypot(...w);
  if (lw < 1e-6) {
    if (dot > 0) return a.map((v, i) => v + (b[i] - v) * k);   // 같은 방향 — 길이만
    w = Math.hypot(ua[0], ua[2]) > 1e-3 ? [-ua[2], 0, ua[0]] : [0, -ua[2], ua[1]];
    lw = Math.hypot(...w);
  }
  w = w.map((v) => v / lw);
  const c = Math.cos(k * theta), s = Math.sin(k * theta), len = la + (lb - la) * k;
  return ua.map((v, i) => (c * v + s * w[i]) * len);
}

export class TweenQueue {
  constructor() {
    this.items = [];
    this.generation = 0;
  }

  // instant면 끝 모습으로 바로 (움직임 줄이기)
  add(ms, step, done, { instant = false } = {}) {
    if (instant || ms <= 0) {
      step(1);
      done?.();
      return;
    }
    this.items.push({ ms, elapsed: 0, step, done, generation: this.generation });
  }

  cancelAll() {
    this.generation += 1;
    this.items = [];
  }

  get size() {
    return this.items.length;
  }

  tick(dtMs) {
    const running = this.items;
    this.items = [];                                // 진행 중 등록되는 새 애니메이션은 여기에 쌓인다
    const keep = [];
    for (const tw of running) {
      if (tw.generation !== this.generation) continue;           // 이 프레임 안에서 취소됨
      tw.elapsed += dtMs;
      const k = Math.min(tw.elapsed / tw.ms, 1);
      tw.step(ease(k));
      if (k < 1) keep.push(tw);
      else tw.done?.();
    }
    this.items = [...keep.filter((tw) => tw.generation === this.generation), ...this.items];
  }
}
