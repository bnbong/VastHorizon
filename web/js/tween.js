// 애니메이션 대기열 — Three.js에 의존하지 않는다 (node로 시험).
//
// 한 프레임에서 처리하는 것은 프레임 시작 때 있던 애니메이션뿐이다.
// 완료 콜백이 다음 애니메이션을 등록하면 그것은 보존해 다음 프레임부터 진행한다. (F2014 리뷰 P1)
// cancelAll()은 세대 번호를 올려, 이전 세대 애니메이션을 같은 프레임 안에서도 더 진행하지 않는다
// (콜백이 모드를 바꾸며 연출을 취소하는 경우).

export const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

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
