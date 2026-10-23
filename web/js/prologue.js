// 프롤로그 — 서비스를 처음 켰을 때. 세상이 좁게 느껴지는 날, 현대 우주 과학이 밝힌 사실로 "당신의 세상은 생각보다 넓다"를 건넨다.
//
// 원칙은 서비스와 같다: 위로를 지어내지 않는다, 사실로 위로한다. 사실을 말하는 장면은 모두 출처를 함께 보여 준다.
//   - 양자 장면은 과장하지 않는다. "의식이 세상을 만든다"가 아니라, 결과를 미리 정해 둔 숨은 지시(국소적 숨은 변수)만으로는
//     자연을 설명할 수 없다는 실험 결과(벨 부등식 위배, 2022년 노벨 물리학상)를 말한다.
//
// 모션: 글자가 한 자씩 흐림에서 또렷하게 떠오르고, 뒤의 입자들(캔버스)이 장면마다 다른 모양으로 모인다.
//   먼지 → 지평선 → 먼 빛줄기 → 별의 탄생 → 확률 구름이 관측되어 한 점으로 → 팽창하는 고리 → 관측 가능한 우주의 구 → 하늘로
// 조작: 자동으로 넘어가고, 클릭 · 스페이스 · → 로 다음, Esc · '건너뛰기'로 끝. 마우스를 움직이면 입자가 살짝 따라온다.
// 움직임 줄이기 설정(또는 ?motion=off)이면 입자는 멈춘 채, 글은 한 번에 나타난다.

import { measure } from "./astro.js";

const WIKI = (title) => `https://ko.wikipedia.org/wiki/${encodeURIComponent(title.replace(/ /g, "_"))}`;
const LY_KM = 9460730472580.8;
export const STORAGE_KEY = "vh-prologue-seen";

export const BEATS = [
  { fx: "dust", lines: ["세상이 좁게 느껴지는 날이 있습니다."], note: "오늘이 유난히 작고 답답했다면, 잠시 함께 올려다봐요.", hold: 4600 },
  { fx: "horizon", lines: ["지금 당신이 볼 수 있는 땅의 끝은", "지평선까지 약 4.7km입니다."],
    counter: { from: 0.001, to: 4.7 },
    fact: "눈높이 1.7m에서 보이는 지평선까지의 거리 (지구 반지름 6,371km로 계산)",
    sources: [{ label: "계산 √(2 × 6,371km × 1.7m)" }], hold: 6200 },
  { fx: "beam", lines: ["그런데 고개를 들면,", "250만 년 전에 떠난 빛이 오늘 당신에게 닿습니다."],
    fact: "안드로메다 은하는 약 250만 광년 떨어져 있습니다. 어두운 밤하늘에서는 맨눈으로도 보입니다.",
    sources: [{ label: "위키백과 「안드로메다 은하」", url: WIKI("안드로메다 은하") }], hold: 7000 },
  { fx: "converge", lines: ["당신은 별에서 왔습니다."],
    fact: "몸을 이루는 탄소와 산소 같은 무거운 원소는 별 내부의 핵융합으로 만들어졌습니다.",
    sources: [{ label: "위키백과 「항성 핵합성」", url: WIKI("항성 핵합성") }], hold: 6200 },
  { fx: "cloud", lines: ["그리고 세상은,", "아직 다 정해지지 않았습니다."],
    fact: "아인슈타인은 입자 안에 결과를 미리 정해 둔 '숨은 변수'가 있으리라 여겼습니다. 벨 부등식 실험들은 그런 숨은 지시만으로는 자연을 설명할 수 없음을 보였고, 2022년 노벨 물리학상을 받았습니다.",
    sources: [{ label: "노벨상 2022 물리학상 발표", url: "https://www.nobelprize.org/prizes/physics/2022/press-release/" },
              { label: "위키백과 「벨 부등식」", url: WIKI("벨 부등식") }], hold: 9000 },
  { fx: "expand", lines: ["우주는 지금 이 순간에도", "넓어지고 있습니다."],
    fact: "멀리 있는 초신성들은 우주의 팽창이 점점 빨라지고 있음을 보여 주었습니다 (2011년 노벨 물리학상).",
    sources: [{ label: "위키백과 「우주의 가속 팽창」", url: WIKI("우주의 가속 팽창") }], hold: 6600 },
  { fx: "sphere", lines: ["관측 가능한 우주의 반지름은 약 465억 광년.", "그 구의 중심에는 언제나, 바라보는 당신이 있습니다."],
    counter: { from: 4.7, to: 465e8 * LY_KM },
    fact: "관측 가능한 우주는 관찰자를 중심으로 하는 구형의 영역입니다. 우주의 모든 자리에는 그 자리만의 관측 가능한 우주가 있습니다.",
    sources: [{ label: "위키백과 「관측 가능한 우주」", url: WIKI("관측 가능한 우주") }], hold: 8600 },
  { fx: "finale", lines: ["당신의 세상은 생각보다 넓습니다."], note: "고개를 들어, 첫 번째 빛을 바라보세요.", final: true, hold: 0 },
];

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// 글자 하나씩 — 글자마다 지연을 준다 (줄이 바뀌어도 이어서). 낱말은 묶어 두어 줄은 낱말 사이에서만 바뀐다 ("46 / 5억" 방지)
export function splitGlyphs(lines, stepMs = 42) {
  let i = 0;
  return lines.map((line) => `<span class="pl-line">${line.split(" ").map((word) => `<span class="pl-w">${[...word]
    .map((ch) => `<span class="pl-g" style="--d:${(i++) * stepMs}ms">${esc(ch)}</span>`).join("")}</span>`).join(" ")}</span>`).join("");
}

// 프롤로그를 띄우고, 끝나면(마지막 장면의 '시작하기' · 건너뛰기) 끝난다
export function playPrologue({ reducedMotion = false } = {}) {
  return new Promise((resolve) => {
    const root = document.createElement("div");
    root.className = `prologue ${reducedMotion ? "still" : ""}`;
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-label", "프롤로그");
    root.innerHTML = `
      <canvas class="pl-canvas" aria-hidden="true"></canvas>
      <div class="pl-veil"></div>
      <div class="pl-stage" aria-live="polite"></div>
      <div class="pl-foot">
        <div class="pl-dots">${BEATS.map((_, i) => `<span class="pl-dot" data-i="${i}"><i></i></span>`).join("")}</div>
        <button type="button" class="pl-skip">건너뛰기</button>
      </div>
      <p class="pl-hint">클릭하거나 스페이스를 누르면 다음으로</p>`;
    document.body.appendChild(root);
    const stage = root.querySelector(".pl-stage");
    const fx = new Particles(root.querySelector(".pl-canvas"), reducedMotion);
    let index = -1, timer = 0, done = false;

    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      window.removeEventListener("keydown", onKey);
      try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* 저장소를 못 쓰면 다음에도 보인다 */ }
      fx.set("rise");
      root.classList.add("leaving");
      setTimeout(() => { fx.stop(); root.remove(); resolve(); }, reducedMotion ? 0 : 1400);
    };

    const show = (i) => {
      if (done || i >= BEATS.length) return finish();
      index = i;
      const beat = BEATS[i];
      clearTimeout(timer);
      // 지금 보이는 장면은 모두 물러난다 — 빠르게 두 번 넘기면 물러나는 중인 장면만 골라 지금 장면이 남던 문제
      stage.querySelectorAll(".pl-beat:not(.out)").forEach((old) => {
        old.classList.add("out");
        setTimeout(() => old.remove(), reducedMotion ? 0 : 700);
      });
      const glyphs = beat.lines.join("").replace(/ /g, "").length;
      const textMs = reducedMotion ? 0 : glyphs * 42 + 600;
      const el = document.createElement("div");
      el.className = `pl-beat fx-${beat.fx}`;
      el.style.setProperty("--after", `${textMs}ms`);
      el.innerHTML = `
        <h2 class="pl-title">${splitGlyphs(beat.lines)}</h2>
        ${beat.counter ? `<div class="pl-counter" aria-hidden="true"><span class="v"></span><span class="u"></span></div>` : ""}
        ${beat.fact ? `<p class="pl-fact">${esc(beat.fact)}</p>` : ""}
        ${beat.sources ? `<p class="pl-src">근거 · ${beat.sources.map((s) => s.url
          ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}</a>` : `<span>${esc(s.label)}</span>`).join(" · ")}</p>` : ""}
        ${beat.note ? `<p class="pl-note">${esc(beat.note)}</p>` : ""}
        ${beat.final ? `<button type="button" class="pl-start">시작하기</button>` : ""}`;
      stage.appendChild(el);
      root.querySelectorAll(".pl-dot").forEach((d, k) => {
        d.classList.toggle("on", k === i);
        d.classList.toggle("past", k < i);
        d.style.setProperty("--hold", `${beat.hold}ms`);
      });
      fx.set(beat.fx, textMs);
      if (beat.counter) rollCounter(el.querySelector(".pl-counter"), beat.counter, reducedMotion ? 0 : textMs + 1800, textMs);
      if (beat.final) el.querySelector(".pl-start").addEventListener("click", (e) => { e.stopPropagation(); finish(); });
      if (beat.hold) timer = setTimeout(() => show(i + 1), beat.hold + textMs);
    };

    const next = () => { if (BEATS[index]?.final) finish(); else show(index + 1); };
    const onKey = (e) => {
      if (e.key === "Escape") finish();
      else if (e.key === " " || e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); next(); }
    };
    root.addEventListener("click", (e) => {
      if (e.target.closest(".pl-skip")) return finish();
      if (e.target.closest("a")) return;                      // 출처 링크는 그대로 열린다
      const dot = e.target.closest(".pl-dot");
      if (dot) return show(Number(dot.dataset.i));
      next();
    });
    root.addEventListener("pointermove", (e) => fx.pointer(e.clientX / innerWidth - 0.5, e.clientY / innerHeight - 0.5));
    window.addEventListener("keydown", onKey);
    root.__prologue = { next, finish, index: () => index };   // 점검용
    requestAnimationFrame(() => show(0));
  });
}

// 숫자가 로그 공간에서 굴러 오른다 — 4.7km에서 465억 광년까지
function rollCounter(el, { from, to }, ms, delay) {
  const draw = (km) => {
    const m = measure(km);
    el.querySelector(".v").textContent = m.value;
    el.querySelector(".u").textContent = m.unit;
  };
  draw(from);
  if (!ms) return draw(to);
  const a = Math.log10(from), b = Math.log10(to);
  setTimeout(() => {
    const t0 = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - t0) / ms), k = 1 - Math.pow(1 - t, 4);
      draw(Math.pow(10, a + (b - a) * k));
      if (t < 1 && el.isConnected) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, delay);
}

// ── 입자 모션그래픽 ─────────────────────────────────────────────────────────

const N = 520;

class Particles {
  constructor(canvas, still) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.still = still;
    this.mode = "dust";
    this.t0 = performance.now();
    this.px = 0; this.py = 0; this.tx = 0; this.ty = 0;
    this.p = Array.from({ length: N }, (_, i) => ({
      x: Math.random(), y: Math.random(), seed: Math.random(), k: i / N,
      size: 0.6 + Math.random() * 1.6, warm: Math.random() < 0.18,
    }));
    this.resize = () => {
      const r = Math.min(devicePixelRatio || 1, 2);
      canvas.width = innerWidth * r;
      canvas.height = innerHeight * r;
      this.ctx.setTransform(r, 0, 0, r, 0, 0);
    };
    this.resize();
    window.addEventListener("resize", this.resize);
    this.running = true;
    const loop = (now) => {
      if (!this.running) return;
      this.frame(now);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  set(mode, delay = 0) { this.mode = mode; this.since = performance.now(); this.delay = delay; }
  pointer(x, y) { this.tx = x; this.ty = y; }
  stop() { this.running = false; window.removeEventListener("resize", this.resize); }

  // 장면마다 입자가 향하는 자리 (화면 비율 0~1), 그리고 밝기
  target(p, t, s) {
    const cx = 0.5, cy = 0.5, w = innerWidth, h = innerHeight, asp = h / w;
    const ang = p.seed * Math.PI * 2;
    switch (this.mode) {
      case "horizon": {                                       // 지평선 — 화면 아래쪽 곡선 위로 내려앉는다
        const x = p.k;
        return [x, 0.78 + 0.03 * Math.pow((x - 0.5) * 2, 2) + 0.004 * Math.sin(t / 900 + p.seed * 9), 0.9];
      }
      case "beam": {                                          // 먼 빛 — 오른쪽 위의 한 점에서 아래 가운데(눈)로 흐르는 빛줄기
        const u = ((t / 2600 + p.seed) % 1);
        if (p.k < 0.42) return [0.78 + (0.5 - 0.78) * u + 0.004 * Math.sin(p.seed * 50), 0.16 + (0.78 - 0.16) * u, 0.4 + 0.6 * (1 - u)];
        return [p.x, p.y, 0.25];
      }
      case "converge": {                                      // 별의 탄생 — 소용돌이치며 한가운데로 모인다
        const r = 0.02 + 0.32 * Math.pow(1 - Math.min(1, s / 3600), 2) * (0.3 + p.seed);
        const a = ang + t / (900 + p.seed * 900);
        return [cx + Math.cos(a) * r * asp, 0.2 + Math.sin(a) * r * 0.7, 0.5 + 0.5 * Math.min(1, s / 3000)];   // 제목 위쪽에서
      }
      case "cloud": {                                         // 확률 구름 — 흔들리다가, 관측되는 순간 한 점으로
        const collapse = Math.min(1, Math.max(0, (s - 4200) / 900));
        const r = (1 - collapse) * (0.05 + 0.2 * Math.sqrt(p.seed)) * (1 + 0.25 * Math.sin(t / (500 + p.seed * 700) + p.seed * 20));
        return [cx + Math.cos(ang + t / 4000) * r * asp, 0.2 + Math.sin(ang * 1.7 + t / 3100) * r * 0.7, 0.35 + 0.65 * collapse];
      }
      case "expand": {                                        // 팽창 — 고리가 계속 밖으로
        const ring = Math.floor(p.k * 6);
        const r = ((t / 4200 + ring / 6) % 1) * 0.75;
        return [cx + Math.cos(ang) * r * asp, cy - 0.04 + Math.sin(ang) * r, 0.9 * (1 - r / 0.75)];
      }
      case "sphere": {                                        // 관측 가능한 우주 — 당신을 중심으로 한 구, 가장자리가 금빛으로
        if (p.k < 0.04) return [cx + (p.seed - 0.5) * 0.004, cy - 0.04 + (p.k - 0.02) * 0.1, 1];
        const r = 0.36 * Math.min(1, 0.15 + s / 3400);
        return [cx + Math.cos(ang + t / 30000) * r * asp, cy - 0.04 + Math.sin(ang + t / 30000) * r, 0.8];
      }
      case "rise":                                            // 끝 — 하늘로 떠올라 실제 하늘에 녹아든다
        return [p.x, p.y - 0.4, 0];
      case "finale":
        return [p.x + 0.002 * Math.sin(t / 1300 + p.seed * 9), p.y - 0.0004 * (t % 9000) / 9, 0.55 + 0.45 * Math.sin(t / (700 + p.seed * 900) + p.seed * 9)];
      default: {                                              // 먼지 — 천천히 떠다닌다
        return [((p.x + 0.00002 * (p.seed - 0.5) * 16) + 1) % 1, (p.y + 0.00004 * (0.5 - p.seed) + 1) % 1, 0.45];
      }
    }
  }

  frame(now) {
    const ctx = this.ctx, w = innerWidth, h = innerHeight;
    const t = now - this.t0, s = now - (this.since ?? this.t0) - (this.delay ?? 0) * 0.4;
    this.px += (this.tx - this.px) * 0.04;
    this.py += (this.ty - this.py) * 0.04;
    ctx.clearRect(0, 0, w, h);
    const ease = this.still ? 1 : this.mode === "rise" ? 0.03 : 0.045;
    for (const p of this.p) {
      const [x, y, a] = this.target(p, t, s);
      if (this.mode === "dust" || this.mode === "finale" || this.mode === "rise") { p.x += (x - p.x) * (this.mode === "rise" ? ease : 1); p.y += (y - p.y) * (this.mode === "rise" ? ease : 1); }
      else { p.x += (x - p.x) * ease; p.y += (y - p.y) * ease; }
      p.a = (p.a ?? 0) + (a - (p.a ?? 0)) * 0.05;
      const depth = 0.4 + p.seed;                              // 시차 — 가까운 입자일수록 마우스를 더 따라온다
      const sx = (p.x + this.px * 0.03 * depth) * w, sy = (p.y + this.py * 0.03 * depth) * h;
      const glow = p.size * (this.mode === "converge" || this.mode === "cloud" ? 1.4 : 1);
      ctx.globalAlpha = Math.max(0, Math.min(1, p.a));
      ctx.fillStyle = p.warm ? "#f0d396" : "#cfdcff";
      ctx.beginPath();
      ctx.arc(sx, sy, glow, 0, Math.PI * 2);
      ctx.fill();
    }
    // 장면의 중심 빛 — 별의 탄생 · 관측된 한 점 · 구의 중심(당신)
    // 장면이 막 바뀐 순간에는 경과 시간(s)이 음수일 수 있다 — 빛의 반지름이 음수가 되지 않게 0~1로 묶는다
    const core = Math.max(0, Math.min(1, { converge: s / 3200, cloud: (s - 4200) / 900, sphere: 1 }[this.mode] ?? 0));
    if (core > 0) {
      const cy = this.mode === "sphere" ? 0.46 : 0.2;
      const g = ctx.createRadialGradient(w / 2, cy * h, 0, w / 2, cy * h, 90 * core);
      g.addColorStop(0, `rgba(255,244,214,${(this.mode === "sphere" ? 0.35 : 0.9) * core})`);   // 구의 중심(당신)은 글 뒤라 은은하게
      g.addColorStop(1, "rgba(255,244,214,0)");
      ctx.globalAlpha = 1;
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
    }
    ctx.globalAlpha = 1;
  }
}
