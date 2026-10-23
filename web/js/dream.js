// 몽환적인 표현 — 이미지 파일 없이 색감 · 질감을 코드로 그린다. (알아간 천체의 표식은 scene.js knownMark — 살구색 채운 원)
//
// | 대상            | 느낌                                                         | 구현                         |
// |-----------------|--------------------------------------------------------------|------------------------------|
// | 발견하는 순간   | 그 천체가 환하게 켜진다 — 빛이 차오르고 빛무리 · 빛살이 번진다   | igniteBurst — 화면 위 2D 캔버스 |
// | 내 세상의 영역  | 내가 알게 된 천체 둘레의 청록 · 흐린 보라 · 살구 성운 (닿은 가장 먼 곳은 옅은 테두리만) | DreamSphere — 셰이더 구 |

import { THREE } from "./scene.js";

// 네온 대신 시안 팔레트의 파스텔 — 살구 · 장밋빛 · 흐린 보라 · 자주 · 청록 · 옅은 청록 (web/tokens/colors.css)
const PASTEL = ["#f3dad5", "#e7bccb", "#b9a0cf", "#9970af", "#63a9c9", "#a9d6e8"];
const DREAM = ["#63a9c9", "#8a91cf", "#b9a0cf", "#f3dad5"];

// 결정적인 난수 — 같은 무늬가 매번 같게
function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

// 내 세상의 범위 — 그라데이션 성운 구. 가장자리(시선과 비스듬한 곳)가 밝고, 안은 은은하다. 안쪽 반짝이는 구와 함께 커진다
// strength: 밝기 (1 = 성운 영역, 0.2 남짓 = 옅은 테두리), sparkles: 안쪽 반짝이
export class DreamSphere {
  constructor({ strength = 1, sparkles = true } = {}) {
    this.group = new THREE.Group();
    this.uniforms = { uTime: { value: 0 }, uStrength: { value: strength } };
    this.shell = new THREE.Mesh(new THREE.SphereGeometry(1, 72, 36), new THREE.ShaderMaterial({
      uniforms: this.uniforms, side: THREE.DoubleSide, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      vertexShader: /* glsl */ `
        varying vec3 vN, vView, vLocal;
        void main() {
          vLocal = position;
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          vN = normalize(normalMatrix * normal);
          vView = normalize(-mv.xyz);
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: /* glsl */ `
        uniform float uTime, uStrength;
        varying vec3 vN, vView, vLocal;
        void main() {
          float fres = pow(1.0 - abs(dot(normalize(vN), normalize(vView))), 2.4);
          float k = clamp(0.5 + 0.5 * vLocal.y + 0.18 * sin(vLocal.x * 3.0 + uTime * 0.25) + 0.12 * sin(vLocal.z * 5.0 - uTime * 0.18), 0.0, 1.0);
          vec3 teal = vec3(0.39, 0.66, 0.79), blue = vec3(0.54, 0.57, 0.81), violet = vec3(0.73, 0.63, 0.81), pink = vec3(0.95, 0.85, 0.84);
          vec3 c = k < 0.33 ? mix(teal, blue, k / 0.33) : k < 0.66 ? mix(blue, violet, (k - 0.33) / 0.33) : mix(violet, pink, (k - 0.66) / 0.34);
          float a = (0.05 + 0.6 * fres) * uStrength;
          gl_FragColor = vec4(c * a, a);
        }`,
    }));
    this.shell.renderOrder = 1;
    const r = rng(23), n = 700, pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const u = r() * 2 - 1, th = r() * Math.PI * 2, d = Math.cbrt(r()) * 0.98, s = Math.sqrt(1 - u * u);
      pos.set([d * s * Math.cos(th), d * u, d * s * Math.sin(th)], i * 3);
      const pick = new THREE.Color(r() < 0.6 ? "#ffffff" : DREAM[Math.floor(r() * DREAM.length)]);
      col.set([pick.r, pick.g, pick.b], i * 3);
    }
    this.sparkles = new THREE.Points(new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(pos, 3))
      .setAttribute("color", new THREE.BufferAttribute(col, 3)),
      new THREE.PointsMaterial({ size: 1.6, sizeAttenuation: false, vertexColors: true, transparent: true, opacity: 0.55,
                                 depthWrite: false, blending: THREE.AdditiveBlending }));
    this.group.add(this.shell);
    if (sparkles) this.group.add(this.sparkles);
  }

  setRadius(r) { this.group.scale.setScalar(r); }
  update(t) { this.uniforms.uTime.value = t; this.sparkles.material.opacity = 0.45 + 0.15 * Math.sin(t * 1.7); }
}

// 발견하는 순간 — 화면 위에 분필 빛줄기가 날아와 (x, y)에 꽂히고, 반짝이가 흩어진다 (약 1.4초)
export function cometBurst(x, y, { reducedMotion = false } = {}) {
  const c = document.createElement("canvas");
  c.className = "comet-burst";
  const dpr = Math.min(devicePixelRatio || 1, 2);
  c.width = innerWidth * dpr;
  c.height = innerHeight * dpr;
  document.body.appendChild(c);
  const g = c.getContext("2d");
  g.scale(dpr, dpr);
  const r = rng(Math.floor(x * 31 + y * 17));
  const from = { x: x - Math.min(520, innerWidth * 0.4), y: y - Math.min(380, innerHeight * 0.4) };
  const strokes = Array.from({ length: 26 }, () => ({ off: (r() - 0.5) * 34, w: 1 + r() * 3.5, col: ["#8a91cf", "#63a9c9", "#f3dad5", "#e7bccb", "#b9a0cf", "#ffffff"][Math.floor(r() * 6)], lag: r() * 0.25 }));
  const sparks = Array.from({ length: 46 }, () => ({ a: r() * Math.PI * 2, v: 40 + r() * 140, s: 1 + r() * 2.6, col: PASTEL[Math.floor(r() * PASTEL.length)] }));
  const dur = reducedMotion ? 600 : 1400, t0 = performance.now();
  const nx = -(y - from.y), ny = x - from.x, nl = Math.hypot(nx, ny) || 1;
  const frame = (now) => {
    const t = Math.min(1, (now - t0) / dur);
    g.clearRect(0, 0, innerWidth, innerHeight);
    g.globalCompositeOperation = "lighter";
    if (!reducedMotion) {
      for (const s of strokes) {                         // 빛줄기 — 앞쪽은 날아가고, 꼬리는 남았다 사라진다
        const head = Math.min(1, Math.max(0, (t - s.lag) / 0.45)), tail = Math.max(0, head - 0.55);
        if (head <= 0) continue;
        const px = (u) => from.x + (x - from.x) * u + (nx / nl) * s.off * (1 - u);
        const py = (u) => from.y + (y - from.y) * u + (ny / nl) * s.off * (1 - u);
        g.strokeStyle = s.col;
        g.globalAlpha = 0.55 * (1 - Math.max(0, (t - 0.55) / 0.45));
        g.lineWidth = s.w;
        g.beginPath();
        g.moveTo(px(tail), py(tail));
        g.lineTo(px(head), py(head));
        g.stroke();
      }
    }
    const k = reducedMotion ? t : Math.max(0, (t - 0.42) / 0.58);
    for (const s of sparks) {                            // 꽂힌 자리에서 흩어지는 반짝이
      if (k <= 0) break;
      const d = s.v * (1 - Math.pow(1 - k, 3));
      g.fillStyle = s.col;
      g.globalAlpha = 1 - k;
      g.fillRect(x + Math.cos(s.a) * d, y + Math.sin(s.a) * d, s.s, s.s);
    }
    if (k > 0) {
      const glow = g.createRadialGradient(x, y, 0, x, y, 70);
      glow.addColorStop(0, `rgba(255,240,236,${0.8 * (1 - k)})`);
      glow.addColorStop(1, "rgba(185,160,207,0)");
      g.globalAlpha = 1;
      g.fillStyle = glow;
      g.fillRect(x - 70, y - 70, 140, 140);
    }
    if (t < 1) requestAnimationFrame(frame);
    else c.remove();
  };
  requestAnimationFrame(frame);
  return c;
}

// 발견하는 순간 — 그 천체가 환하게 켜진다. 빛이 차오르며 부드러운 빛무리와 빛살이 번지고, 천천히 가라앉는다 (약 1.8초)
export function igniteBurst(x, y, { reducedMotion = false } = {}) {
  const c = document.createElement("canvas");
  c.className = "comet-burst";
  const dpr = Math.min(devicePixelRatio || 1, 2);
  c.width = innerWidth * dpr;
  c.height = innerHeight * dpr;
  document.body.appendChild(c);
  const g = c.getContext("2d");
  g.scale(dpr, dpr);
  const r = rng(Math.floor(x * 13 + y * 7));
  const motes = Array.from({ length: 36 }, () => ({ a: r() * Math.PI * 2, d: 30 + r() * 70, s: 0.8 + r() * 1.8, col: DREAM[Math.floor(r() * DREAM.length)], ph: r() }));
  const rays = Array.from({ length: 8 }, (_, i) => ({ a: (i / 8) * Math.PI * 2 + r() * 0.3, len: 60 + r() * 50 }));
  const dur = reducedMotion ? 700 : 1800, t0 = performance.now();
  const frame = (now) => {
    const t = Math.min(1, (now - t0) / dur);
    const rise = Math.min(1, t / 0.28), fall = Math.max(0, (t - 0.28) / 0.72);
    const light = rise * (1 - fall * fall);                      // 빠르게 차오르고 천천히 가라앉는다
    g.clearRect(0, 0, innerWidth, innerHeight);
    g.globalCompositeOperation = "lighter";
    const R = 26 + 120 * (reducedMotion ? 0.5 : rise) ;
    const glow = g.createRadialGradient(x, y, 0, x, y, R);
    glow.addColorStop(0, `rgba(255,255,255,${0.95 * light})`);
    glow.addColorStop(0.18, `rgba(243,218,213,${0.7 * light})`);
    glow.addColorStop(0.5, `rgba(185,160,207,${0.32 * light})`);
    glow.addColorStop(1, "rgba(99,169,201,0)");
    g.globalAlpha = 1;
    g.fillStyle = glow;
    g.fillRect(x - R, y - R, R * 2, R * 2);
    if (!reducedMotion) {
      for (const ray of rays) {                               // 은은한 빛살
        const len = ray.len * rise;
        const grad = g.createLinearGradient(x, y, x + Math.cos(ray.a) * len, y + Math.sin(ray.a) * len);
        grad.addColorStop(0, `rgba(255,240,236,${0.5 * light})`);
        grad.addColorStop(1, "rgba(255,240,236,0)");
        g.strokeStyle = grad;
        g.lineWidth = 1.2;
        g.beginPath();
        g.moveTo(x, y);
        g.lineTo(x + Math.cos(ray.a) * len, y + Math.sin(ray.a) * len);
        g.stroke();
      }
      for (const m of motes) {                                // 빛무리 속 반짝이 — 바깥으로 살짝 퍼지며 깜빡인다
        const d = m.d * (0.4 + 0.6 * rise);
        g.fillStyle = m.col;
        g.globalAlpha = light * (0.5 + 0.5 * Math.sin((t * 6 + m.ph) * Math.PI));
        g.fillRect(x + Math.cos(m.a) * d, y + Math.sin(m.a) * d, m.s, m.s);
      }
    }
    if (t < 1) requestAnimationFrame(frame);
    else c.remove();
  };
  requestAnimationFrame(frame);
  return c;
}
