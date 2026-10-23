// VastHorizon 로고 — docs/images/brand/vasthorizon-logo-v1.png(1254×1254)를 선 기반 인라인 SVG로 다시 그렸다.
// 네 요소: 출발점(당신) · 그 점에서 오른쪽 위로 휘어 오르는 빛의 궤적 · 궤적 끝의 4각 별 · 아래를 가로지르는 지평선 호.
// 궤적과 호는 끝이 가늘어지는 면이고, 그 위에 같은 선을 따라가는 마스크 획(stroke-dashoffset)을 씌워 "그려지게" 한다.

const R = (n) => Math.round(n * 10) / 10;

// 궤적 중심선 — 출발점 바로 옆에서 시작해 곧게 오르다 별 아래 끝으로 휘어 든다 (원본 픽셀에 맞춘 3차 베지어)
const TRAIL = [[325, 965], [890, 615], [975, 620], [1024, 436]];
const TRAIL_D = `M${TRAIL[0]} C${TRAIL[1]} ${TRAIL[2]} ${TRAIL[3]}`;

function bezier(t) {
  const [p0, p1, p2, p3] = TRAIL, u = 1 - t;
  const pt = (i) => u * u * u * p0[i] + 3 * u * u * t * p1[i] + 3 * u * t * t * p2[i] + t * t * t * p3[i];
  const dt = (i) => 3 * u * u * (p1[i] - p0[i]) + 6 * u * t * (p2[i] - p1[i]) + 3 * t * t * (p3[i] - p2[i]);
  return { x: pt(0), y: pt(1), dx: dt(0), dy: dt(1) };
}

// 궤적 굵기 — 점 쪽은 실처럼 가늘고, 가운데가 가장 두껍고, 별 쪽 끝은 뾰족하다 (원본에서 잰 [t, 굵기])
const WIDTHS = [[0, 5], [0.1, 11], [0.2, 16], [0.3, 19], [0.45, 20], [0.6, 19], [0.75, 16.5], [0.9, 11.5], [1, 3]];
function trailWidth(t) {
  const i = Math.max(1, WIDTHS.findIndex(([at]) => at >= t));
  const [t0, w0] = WIDTHS[i - 1], [t1, w1] = WIDTHS[i];
  return w0 + (w1 - w0) * (t - t0) / (t1 - t0);
}

function trailOutline(steps = 48) {
  const left = [], right = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps, { x, y, dx, dy } = bezier(t), len = Math.hypot(dx, dy) || 1;
    const nx = -dy / len, ny = dx / len, h = trailWidth(t) / 2;
    left.push(`${R(x + nx * h)} ${R(y + ny * h)}`);
    right.push(`${R(x - nx * h)} ${R(y - ny * h)}`);
  }
  return `M${left.join("L")}L${right.reverse().join("L")}Z`;
}

// 지평선 호 — 바깥 타원과 조금 납작한 안쪽 타원이 양 끝에서 만나, 가운데는 두툼하고 끝은 뾰족한 초승달
const HORIZON_EDGE = "M110 1010A525 427 0 0 1 1140 1010";
const HORIZON_D = `${HORIZON_EDGE}A526.5 399 0 0 0 110 1010Z`;

// 4각 별 — 안으로 오목한 네 변. 위 · 오른쪽 · 아래 · 왼쪽 끝을 차례로 잇는다
const STAR = { cx: 1035, cy: 392, arms: [116, 106, 111, 106] };
function starPath({ cx, cy, arms }, k = 0.2, w = 4) {
  const dirs = [[0, -1], [1, 0], [0, 1], [-1, 0]];
  const tip = (i) => [cx + dirs[i][0] * arms[i], cy + dirs[i][1] * arms[i]];
  let d = `M${tip(0)}`;
  for (let i = 0; i < 4; i++) {
    const j = (i + 1) % 4, [ax, ay] = dirs[i], [bx, by] = dirs[j];
    // 끝에서 중심 쪽으로 k만큼 들어온 점을 다음 끝 방향으로 w만큼 밀어 — 팔은 가늘고 가운데는 도톰하다
    const c1 = [cx + ax * arms[i] * k + bx * w, cy + ay * arms[i] * k + by * w];
    const c2 = [cx + bx * arms[j] * k + ax * w, cy + by * arms[j] * k + ay * w];
    d += `C${c1.map(R)} ${c2.map(R)} ${tip(j)}`;
  }
  return `${d}Z`;
}
const STAR_D = starPath(STAR);
const DOT = { cx: 307, cy: 973, r: 23 };

export const LOGO_VIEWBOX = "0 0 1254 1254";
export const LOGO_VIEWBOX_TIGHT = "80 240 1094 800";   // 여백을 걷어 낸 구도 — 로딩 화면처럼 그림 너비로 크기를 맞출 때

// 궤적의 [from, 1] 구간 — 3차 베지어를 de Casteljau로 잘라 낸다 (작은 로더는 별 쪽 윗부분만 쓴다)
function trailTail(from) {
  const lerp = (a, b) => [a[0] + (b[0] - a[0]) * from, a[1] + (b[1] - a[1]) * from];
  const [p0, p1, p2, p3] = TRAIL;
  const a = lerp(p0, p1), b = lerp(p1, p2), c = lerp(p2, p3), d = lerp(a, b), e = lerp(b, c), f = lerp(d, e);
  return `M${f.map(R)}C${e.map(R)} ${c.map(R)} ${p3}`;
}

// 전체 로고 — 장식이므로 aria-hidden. 같은 문서에 여럿 둘 때를 위해 마스크 id 앞머리를 바꿀 수 있다.
// 그리기 애니메이션은 마스크 획(.logo-draw)의 stroke-dashoffset으로 — 기본 상태는 완성된 로고다 (style.css).
// 호가 궤적 뒤로 끊기는 틈도 궤적 마스크를 따라 궤적이 지나갈 때 생긴다
export function logoSvg({ id = "vh-logo", className = "logo", viewBox = LOGO_VIEWBOX } = {}) {
  const trail = trailOutline();
  return `<svg class="${className}" viewBox="${viewBox}" aria-hidden="true" focusable="false">
  <defs>
    <mask id="${id}-tr" maskUnits="userSpaceOnUse" x="0" y="0" width="1254" height="1254">
      <path class="logo-draw logo-draw-trail" d="${TRAIL_D}" pathLength="1" fill="none" stroke="#fff" stroke-width="70"/>
    </mask>
    <mask id="${id}-hz" maskUnits="userSpaceOnUse" x="0" y="0" width="1254" height="1254">
      <path class="logo-draw logo-draw-horizon" d="${HORIZON_EDGE}" pathLength="1" fill="none" stroke="#fff" stroke-width="90"/>
      <path d="${trail}" fill="#000" stroke="#000" stroke-width="16" stroke-linejoin="round" mask="url(#${id}-tr)"/>
    </mask>
  </defs>
  <path class="logo-horizon" d="${HORIZON_D}" mask="url(#${id}-hz)"/>
  <circle class="logo-dot" cx="${DOT.cx}" cy="${DOT.cy}" r="${DOT.r}"/>
  <path class="logo-trail" d="${trail}" mask="url(#${id}-tr)"/>
  <g class="logo-star-wrap"><path class="logo-star" d="${STAR_D}"/></g>
</svg>`;
}

// 작은 로더 — 별과 궤적 윗부분만, currentColor. 20px에서도 보이게 별의 가운데를 조금 더 도톰하게 그린다
const MINI_TRAIL_D = trailTail(0.52);
const MINI_STAR_D = starPath(STAR, 0.26, 12);
export function miniLogoSvg(size = 20) {
  return `<svg class="mini-logo" width="${size}" height="${size}" viewBox="820 262 380 380" aria-hidden="true" focusable="false">
  <path class="mini-trail" d="${MINI_TRAIL_D}" pathLength="1" fill="none" stroke-width="36"/>
  <path class="mini-star" d="${MINI_STAR_D}"/>
</svg>`;
}
