// 프롤로그 — 서비스를 처음 켰을 때. 세상이 좁게 느껴지는 날, 현대 우주 과학이 밝힌 사실로 "당신의 세상은 생각보다 넓다"를 건넨다.
//
// 원칙은 서비스와 같다: 위로를 지어내지 않는다, 사실로 위로한다. 사실을 말하는 장면은 모두 출처를 함께 보여 준다.
//   - 양자 장면은 과장하지 않는다. "의식이 세상을 만든다"가 아니라, 결과를 미리 정해 둔 숨은 지시(국소적 숨은 변수)만으로는
//     자연을 설명할 수 없다는 실험 결과(벨 부등식 위배, 2022년 노벨 물리학상)를 말한다.
//
// 모션: 글자가 한 자씩 흐림에서 또렷하게 떠오르고, 뒤의 입자들(캔버스)이 장면마다 다른 모양으로 모인다.
//   먼지 → 지평선 → 먼 빛줄기 → 별 먼지가 내려와 제목 둘레에 머문다 → 무한 기호 궤도를 흐른다 → 팽창하는 고리
//   → 관측 가능한 우주의 구 (가운데 '당신'의 자리에서 빛무리 — 지구가 내 세계의 첫 천체로 담긴다) → 하늘로
// 조작: 자동으로 넘어가고, 클릭 · 스페이스 · → 로 다음, Esc · '건너뛰기'로 끝. 마우스를 움직이면 입자가 살짝 따라온다.
//   초점이 버튼 · 링크에 있으면 스페이스 · Enter는 그 버튼만 누른다(장면은 넘기지 않는다). Esc는 어디서든 끝.
// 움직임 줄이기 설정(또는 ?motion=off)이면 입자는 멈춘 배치를 한 번만 그리고(장면이 바뀔 때만 다시), 글은 한 번에 나타난다.
// 소리(sound.js): 장면이 실제로 그려질 때 sparkle, 구 장면의 빛무리에 collect. 건너뛰기 옆의 작은 버튼으로 켜고 끈다(메뉴의 소리 항목과 같은 설정).
//
// 장면 전환은 상태 하나로 (빠르게 넘기면 스파클 · 글이 겹치던 문제):
//   요청(클릭 · 키 · 점 · 자동) → decideStep이 다음 장면을 정한다 → 같은 프레임의 요청은 마지막 것만 → show(i)
//   show(i)는 이전 장면의 범위(createScope — 타이머 · 프레임 · 리스너)를 모두 취소하고, 무대에는 물러나는 장면 하나만 남긴 뒤 그린다.
//   입자는 인스턴스 하나가 모드만 바꾸며 보간한다.

import { measure } from "./astro.js";
import { icon } from "./icons.js";
import { sound } from "./sound.js";

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
    counter: { from: 4.7, to: 465e8 * LY_KM }, earth: true,     // 글이 다 떠오르면 가운데(당신의 자리)에서 빛무리 — 지구를 내 세계에 담는다
    fact: "관측 가능한 우주는 관찰자를 중심으로 하는 구형의 영역입니다. 우주의 모든 자리에는 그 자리만의 관측 가능한 우주가 있습니다.",
    sources: [{ label: "위키백과 「관측 가능한 우주」", url: WIKI("관측 가능한 우주") }], hold: 8600 },
  { fx: "finale", lines: ["당신의 세상은 생각보다 넓습니다."], note: "고개를 들어, 첫 번째 빛을 바라보세요.", final: true, hold: 0 },
];

const GLYPH_MS = 42;
const BEAT_OUT_MS = 450;        // 물러나는 장면의 사라짐 (style.css .pl-beat.out)
const RAPID_MS = 900;           // 이보다 빨리 넘기면 물러나는 연출 없이 바로 비운다
export const FINAL_GUARD_MS = 1500;   // 마지막 장면에 막 들어온 뒤의 '다음'은 끝내지 않는다 (연타가 시작하기를 건너뛰지 않게)

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// 글자 하나씩 — 글자마다 지연을 준다 (줄이 바뀌어도 이어서). 낱말은 묶어 두어 줄은 낱말 사이에서만 바뀐다 ("46 / 5억" 방지)
export function splitGlyphs(lines, stepMs = GLYPH_MS) {
  let i = 0;
  return lines.map((line) => `<span class="pl-line">${line.split(" ").map((word) => `<span class="pl-w">${[...word]
    .map((ch) => `<span class="pl-g" style="--d:${(i++) * stepMs}ms">${esc(ch)}</span>`).join("")}</span>`).join(" ")}</span>`).join("");
}

// ── 전환 상태 머신의 순수 부분 (node로 시험) ─────────────────────────────────

// 다음에 할 일 — { type: "show", index } · { type: "finish" } · { type: "none" }
//   from: 지금 장면(아직 그리지 않은 요청이 있으면 그 장면), action: "next" · "auto" · "skip" · { goto: i }
//   sinceShown: 지금 장면이 그려진 뒤 지난 시간(ms) — 마지막 장면의 '다음'은 FINAL_GUARD_MS가 지나야 끝낸다
export function decideStep(from, action, { n = BEATS.length, final = n - 1, sinceShown = Infinity, guardMs = FINAL_GUARD_MS } = {}) {
  if (action === "skip") return { type: "finish" };
  if (action && typeof action === "object" && Number.isInteger(action.goto)) {
    const i = Math.max(0, Math.min(n - 1, action.goto));
    return i === from ? { type: "none" } : { type: "show", index: i };
  }
  if (action === "next" || action === "auto") {
    if (from >= final) return sinceShown >= guardMs ? { type: "finish" } : { type: "none" };
    return { type: "show", index: Math.max(0, from + 1) };
  }
  return { type: "none" };
}

// 아직 그리지 않은 요청이 있으면 자동 넘김은 받지 않는다 (사람이 넘긴 장면 위로 자동 넘김이 한 장면 더 얹히지 않게)
export const acceptsRequest = (action, pending) => !(action === "auto" && pending != null);

// 키 → 요청 ("skip" · "next" · null). inControl: 초점이 버튼 · 링크 안 — 스페이스 · Enter는 그 버튼의 것이라 Esc만 받는다
export function keyAction(key, { inControl = false } = {}) {
  if (key === "Escape") return "skip";
  if (inControl) return null;
  return key === " " || key === "Enter" || key === "ArrowRight" ? "next" : null;
}

// 취소 토큰 — 한 장면이 건 타이머 · 프레임 · 리스너를 한 번에 거둔다. cancel() 뒤에는 아무것도 걸리지도, 불리지도 않는다
export function createScope(timers = globalThis) {
  let alive = true;
  const timeouts = new Set(), frames = new Set(), offs = [];
  return {
    get alive() { return alive; },
    timeout(fn, ms) {
      if (!alive) return 0;
      const id = timers.setTimeout(() => { timeouts.delete(id); if (alive) fn(); }, ms);
      timeouts.add(id);
      return id;
    },
    frame(fn) {
      if (!alive) return 0;
      const id = timers.requestAnimationFrame((now) => { frames.delete(id); if (alive) fn(now); });
      frames.add(id);
      return id;
    },
    listen(target, type, fn, opts) {
      if (!alive) return;
      target.addEventListener(type, fn, opts);
      offs.push(() => target.removeEventListener(type, fn, opts));
    },
    cancel() {
      if (!alive) return;
      alive = false;
      for (const id of timeouts) timers.clearTimeout(id);
      for (const id of frames) timers.cancelAnimationFrame(id);
      for (const off of offs) off();
      timeouts.clear(); frames.clear(); offs.length = 0;
    },
  };
}

// ── 프롤로그 ───────────────────────────────────────────────────────────────

let active = null;   // 이미 떠 있으면 그 프롤로그를 그대로 (두 번 겹쳐 뜨지 않게)

// 프롤로그를 띄우고, 끝나면(마지막 장면의 '시작하기' · 건너뛰기) 끝난다.
// 돌려주는 값: { next: "mind" | null } — 마지막 장면의 '마음 한 줄 먼저 남기기'로 끝냈으면 "mind"
// onEarth: 구 장면에서 '당신의 자리'에 빛무리가 일 때 — 지구를 내 세계에 담는다 (main.js ensureEarth)
export function playPrologue({ reducedMotion = false, onEarth = null } = {}) {
  if (active) return active;
  active = new Promise((resolve) => {
    const root = document.createElement("div");
    root.className = `prologue ${reducedMotion ? "still" : ""}`;
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-label", "프롤로그");
    root.innerHTML = `
      <div class="pl-sky pl-sky-deep" aria-hidden="true"></div>
      <div class="pl-sky pl-sky-first" aria-hidden="true"></div>
      <canvas class="pl-canvas" aria-hidden="true"></canvas>
      <div class="pl-veil"></div>
      <div class="pl-stage" aria-live="polite"></div>
      <div class="pl-foot">
        <div class="pl-dots">${BEATS.map((_, i) => `<span class="pl-dot" data-i="${i}"><i></i></span>`).join("")}</div>
        <button type="button" class="pl-skip">건너뛰기</button>
        <button type="button" class="pl-sound"></button>
      </div>
      <p class="pl-hint">클릭하거나 스페이스를 누르면 다음으로</p>`;
    document.body.appendChild(root);
    const stage = root.querySelector(".pl-stage");
    const soundBtn = root.querySelector(".pl-sound");
    const drawSound = () => {                 // 소리 토글 — 이름은 "소리"로 고정, 상태는 aria-pressed와 아이콘으로
      const on = sound.enabled;
      soundBtn.innerHTML = icon(on ? "volume" : "volume-x", 16);
      soundBtn.setAttribute("aria-pressed", String(on));
      soundBtn.setAttribute("aria-label", "소리");
      soundBtn.title = on ? "소리 켜짐" : "소리 꺼짐";
    };
    drawSound();
    const fx = new Particles(root.querySelector(".pl-canvas"), reducedMotion);
    let index = -1, shownAt = 0, done = false;
    let scope = createScope();            // 지금 장면의 타이머 · 프레임 · 리스너
    let pending = null, pendingFrame = 0;  // 아직 그리지 않은 요청 — 같은 프레임의 연타는 마지막 것만

    const finish = (next = null) => {
      if (done) return;
      done = true;
      scope.cancel();
      cancelAnimationFrame(pendingFrame);
      pending = null;
      window.removeEventListener("keydown", onKey);
      try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* 저장소를 못 쓰면 다음에도 보인다 */ }
      fx.set("rise");
      root.style.setProperty("--pl-progress", "1");          // 건너뛰어도 첫 하늘의 색으로 물러난다
      root.classList.add("leaving");
      setTimeout(() => { fx.stop(); root.remove(); active = null; resolve({ next }); }, reducedMotion ? 0 : 1400);
    };

    // 무대 비우기 — 지금 장면은 물러나고(천천히 넘길 때만), 이미 물러나는 중인 장면은 바로 지운다. 무대에는 많아야 둘
    const clearStage = (rapid) => {
      stage.querySelectorAll(".pl-beat.out").forEach((old) => old.remove());
      stage.querySelectorAll(".pl-beat").forEach((old) => {
        if (rapid || reducedMotion) old.remove();
        else old.classList.add("out");
      });
      return !!stage.querySelector(".pl-beat.out");
    };

    const show = (i) => {
      if (done) return;
      if (i < 0 || i >= BEATS.length) return finish();
      scope.cancel();                                        // 이전 장면의 자동 넘김 · 숫자 굴림 · 빛무리 예약 · 리스너
      scope = createScope();
      const now = performance.now();
      const rapid = index >= 0 && now - shownAt < RAPID_MS;
      index = i;
      shownAt = now;
      const beat = BEATS[i];
      // 하늘이 장면마다 조금씩 밝아진다 — 깊은 남보라(0)에서 마지막 장면의 첫 하늘 그라데이션(1)까지
      root.style.setProperty("--pl-progress", (i / (BEATS.length - 1)).toFixed(3));
      const leaving = clearStage(rapid);
      const outgoing = stage.querySelector(".pl-beat.out");
      if (outgoing) scope.timeout(() => outgoing.remove(), BEAT_OUT_MS);
      // 물러나는 장면이 있으면 그만큼 늦게 떠오른다 — 두 장면의 글이 같은 자리에서 겹쳐 보이지 않게
      const lead = leaving && !reducedMotion ? Math.round(BEAT_OUT_MS * 0.7) : 0;
      const glyphs = beat.lines.join("").replace(/ /g, "").length;
      const textMs = reducedMotion ? 0 : lead + glyphs * GLYPH_MS + 600;
      const el = document.createElement("div");
      el.className = `pl-beat fx-${beat.fx}`;
      el.style.setProperty("--lead", `${lead}ms`);
      el.style.setProperty("--after", `${textMs}ms`);
      el.innerHTML = `
        <h2 class="pl-title">${splitGlyphs(beat.lines)}</h2>
        ${beat.counter ? `<div class="pl-counter" aria-hidden="true"><span class="v"></span><span class="u"></span></div>` : ""}
        ${beat.fact ? `<p class="pl-fact">${esc(beat.fact)}</p>` : ""}
        ${beat.sources ? `<p class="pl-src">근거 · ${beat.sources.map((s) => s.url
          ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}</a>` : `<span>${esc(s.label)}</span>`).join(" · ")}</p>` : ""}
        ${beat.note ? `<p class="pl-note">${esc(beat.note)}</p>` : ""}
        ${beat.final ? `<div class="pl-start-row"><button type="button" class="pl-start"><span>시작하기</span>${icon("arrow-up-right", 18)}</button>
          <button type="button" class="pl-mind">마음 한 줄 먼저 남기기</button></div>` : ""}`;
      stage.appendChild(el);
      sound.sparkle();                                       // 장면이 실제로 바뀌는 순간에만 (연타 보호는 sound.js)
      root.querySelectorAll(".pl-dot").forEach((d, k) => {
        d.classList.toggle("on", k === i);
        d.classList.toggle("past", k < i);
        d.style.setProperty("--hold", `${beat.hold}ms`);
      });
      // 입자 — 인스턴스 하나가 모드만 바꾼다. 글자 자리는 이 장면의 제목에서 (화면 좌표 → 캔버스)
      const title = el.querySelector(".pl-title");
      // 숫자는 입자보다 먼저 — 움직임 줄이기면 여기서 끝 값이 바로 그려져, 아래 set()이 읽는 숫자 칸의 폭이 맞다
      const rollMs = reducedMotion ? 0 : textMs + 1800;
      if (beat.counter) rollCounter(scope, el.querySelector(".pl-counter"), beat.counter, rollMs, textMs);
      // 사각형은 매 프레임 읽지 않는다 — 지금(장면 전환) · 글자가 다 떠오른 뒤 · 숫자가 다 구른 뒤 · resize 때만 다시 읽어 둔다
      fx.set(beat.fx, textMs, { anchor: () => title.getBoundingClientRect(),
        shield: () => [...el.querySelectorAll(".pl-title, .pl-counter, .pl-fact, .pl-src, .pl-note")].map((t) => t.getBoundingClientRect()) });
      if (!reducedMotion) {
        scope.timeout(() => fx.measure(), textMs + 50);
        if (beat.counter) scope.timeout(() => fx.measure(), textMs + rollMs + 50);   // 숫자 칸의 폭이 바뀐다
      }
      if (beat.earth) scope.timeout(() => {                  // 당신의 자리 — 구의 중심에서 빛무리, 지구가 내 세계의 첫 천체로
        fx.ignite(0.5, SPHERE_CY);
        sound.collect();
        try { onEarth?.(); } catch (e) { console.warn("지구를 내 세계에 담지 못했습니다", e); }
      }, reducedMotion ? 0 : textMs + 200);
      if (beat.final) scope.listen(el.querySelector(".pl-start"), "click", (e) => { e.stopPropagation(); finish(); });
      if (beat.final) scope.listen(el.querySelector(".pl-mind"), "click", (e) => { e.stopPropagation(); finish("mind"); });   // 프롤로그를 끝내고 마음 한 줄 서랍으로
      if (beat.hold) scope.timeout(() => request("auto"), beat.hold + textMs);
    };

    // 요청 — 다음 장면을 정해 두고, 그리기는 다음 프레임에 한 번. 그사이 들어온 요청은 정해 둔 장면에서 이어 센다
    const request = (action) => {
      if (done) return;
      if (!acceptsRequest(action, pending)) return;
      const from = pending ?? index;
      const step = decideStep(from, action, { sinceShown: pending == null ? performance.now() - shownAt : 0 });
      if (step.type === "finish") return finish();
      if (step.type !== "show") return;
      pending = step.index;
      if (!pendingFrame) pendingFrame = requestAnimationFrame(() => {
        pendingFrame = 0;
        const i = pending;
        pending = null;
        if (i != null) show(i);
      });
    };

    const onKey = (e) => {
      const action = keyAction(e.key, { inControl: !!e.target?.closest?.("button, a") });   // .pl-sound · .pl-skip · .pl-start · 출처 링크
      if (!action) return;
      if (action === "next") e.preventDefault();
      request(action);
    };
    root.addEventListener("click", (e) => {
      if (e.target.closest(".pl-skip")) return request("skip");
      if (e.target.closest(".pl-sound")) { sound.unlock(); sound.enabled = !sound.enabled; return drawSound(); }   // 장면은 넘기지 않는다
      if (e.target.closest("a") || e.target.closest(".pl-start, .pl-mind")) return;   // 출처 링크는 그대로 열린다
      const dot = e.target.closest(".pl-dot");
      if (dot) return request({ goto: Number(dot.dataset.i) });
      request("next");
    });
    root.addEventListener("pointermove", (e) => fx.pointer(e.clientX / innerWidth - 0.5, e.clientY / innerHeight - 0.5));
    window.addEventListener("keydown", onKey);
    root.__prologue = { next: () => request("next"), finish, index: () => index, beats: () => stage.querySelectorAll(".pl-beat").length, fx };   // 점검용
    requestAnimationFrame(() => show(0));
  });
  return active;
}

// 숫자가 로그 공간에서 굴러 오른다 — 4.7km에서 465억 광년까지. 장면이 바뀌면(scope 취소) 함께 멈춘다
function rollCounter(scope, el, { from, to }, ms, delay) {
  const draw = (km) => {
    const m = measure(km);
    el.querySelector(".v").textContent = m.value;
    el.querySelector(".u").textContent = m.unit;
  };
  draw(from);
  if (!ms) return draw(to);
  const a = Math.log10(from), b = Math.log10(to);
  scope.timeout(() => {
    const t0 = performance.now();
    const tick = (now) => {
      const t = Math.min(1, Math.max(0, (now - t0) / ms)), k = 1 - Math.pow(1 - t, 4);
      draw(Math.pow(10, a + (b - a) * k));
      if (t < 1) scope.frame(tick);
    };
    scope.frame(tick);
  }, delay);
}

// ── 입자 모션그래픽 ─────────────────────────────────────────────────────────

const N = 520;
const NARROW_PX = 650;         // 이 폭 이하(휴대폰)면 입자를 60%만
const SPHERE_CY = 0.46;        // 관측 가능한 우주의 구 — 중심(당신의 자리)
// 별빛 — 종이색 #FFFAF5 · 살구 #F3DAD5 · 옅은 청록(#63A9C9를 종이색 쪽으로 낮춘 채도)
const TONES = ["#fffaf5", "#f3dad5", "#a9cfdf"];
const TONES_RGB = ["255,250,245", "243,218,213", "169,207,223"];
const clamp01 = (v) => Math.max(0, Math.min(1, v));

// 무한 기호(베르누이 렘니스케이트) — x = cos t / (1 + sin²t), y = sin t cos t / (1 + sin²t). x ∈ [-1, 1], y ∈ [-0.35, 0.35]
export function lemniscate(t) {
  const s = Math.sin(t), c = Math.cos(t), d = 1 + s * s;
  return [c / d, (s * c) / d];
}

class Particles {
  constructor(canvas, still) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.still = still;
    this.mode = "dust";
    this.epoch = 0;
    this.t0 = performance.now();
    this.px = 0; this.py = 0; this.tx = 0; this.ty = 0;
    this.bursts = [];
    this.anchor = null;
    this.shield = null;
    this.boxRect = null;       // 제목 사각형 · 글 사각형들 — measure()가 읽어 둔 것
    this.rects = [];
    const count = innerWidth <= NARROW_PX ? Math.round(N * 0.6) : N;
    this.p = Array.from({ length: count }, (_, i) => {
      const big = Math.random() < 0.03, r = Math.random();
      return {
        x: Math.random(), y: Math.random(), seed: Math.random(), u: Math.random(), v: Math.random(), k: i / count, big,
        vx: 0, vy: 0,
        size: big ? 1.8 + Math.random() * 1.0 : 0.5 + Math.random() * 1.0,
        tone: r < 0.68 ? 0 : r < 0.9 ? 1 : 2,                  // 종이색 · 살구 · 옅은 청록
      };
    });
    this.resize = () => {
      const r = Math.min(devicePixelRatio || 1, 2);
      canvas.width = innerWidth * r;
      canvas.height = innerHeight * r;
      this.ctx.setTransform(r, 0, 0, r, 0, 0);
    };
    this.resize();
    this.onResize = () => { this.resize(); this.measure(); this.kick(); };
    window.addEventListener("resize", this.onResize);
    this.running = true;
    this.raf = 0;
    // 움직임 줄이기면 한 번 그리고 멈춘다 (빛무리가 남아 있는 동안만 이어 그린다). kick()이 다시 깨운다
    this.loop = (now) => {
      this.raf = 0;
      if (!this.running) return;
      this.frame(now);
      if (!this.still || this.bursts.length) this.raf = requestAnimationFrame(this.loop);
    };
    this.kick();
  }

  kick() { if (this.running && !this.raf) this.raf = requestAnimationFrame(this.loop); }

  // 제목 · 글 사각형(화면 px)을 다시 읽어 둔다 — 장면 전환 · resize · 글자 애니메이션이 끝날 때만 (매 프레임 읽지 않는다)
  measure() {
    const r = this.anchor?.();
    this.boxRect = r && r.width ? { pl: r.left, pt: r.top, pr: r.right, pb: r.bottom } : null;
    this.rects = (this.shield?.() ?? []).filter((x) => x.width);
  }

  // 모드 전환 — 입자는 그대로 두고 향하는 자리만 바꾼다(보간). 제목 둘레에 머물던 별 먼지는 다음 장면으로 넘어갈 때 흩어진다
  // anchor: 지금 장면 제목의 화면 사각형을 돌려주는 함수 (getBoundingClientRect), shield: 글이 놓인 사각형들 — 그 위를 지나는 입자는 옅어진다
  set(mode, delay = 0, { anchor = null, shield = null } = {}) {
    if (this.mode === "converge" && mode !== "converge" && !this.still) {
      for (const p of this.p) {
        const a = Math.atan2(p.y - 0.5, p.x - 0.5) + (p.u - 0.5) * 1.2, v = 0.002 + 0.004 * p.v;
        p.vx = Math.cos(a) * v;
        p.vy = Math.sin(a) * v;
      }
    }
    if (mode !== "cloud") for (const p of this.p) p.phi = null;   // 무한 기호의 잔상은 그 장면에서만
    this.mode = mode;
    this.epoch += 1;
    this.since = performance.now();
    this.delay = delay;
    this.anchor = anchor;
    this.shield = shield;
    this.measure();
    this.kick();
  }
  pointer(x, y) { this.tx = x; this.ty = y; }
  stop() { this.running = false; cancelAnimationFrame(this.raf); this.raf = 0; window.removeEventListener("resize", this.onResize); }
  // 빛무리 — 화면 비율 (x, y)에서 빛이 차오르고 천천히 가라앉는다 (dream.js igniteBurst와 같은 느낌, 프롤로그 캔버스 안에서)
  ignite(x, y) { this.bursts.push({ x, y, t0: performance.now(), dur: this.still ? 700 : 2400 }); this.kick(); }

  // 별 먼지가 머무는 자리 — 제목 상자의 위 · 아래 가장자리(넓게)와 좌우 여백. 은은히 맴돈다
  haloSlot(p, box, t) {
    const w = innerWidth, h = innerHeight;
    const { pl: L, pt: T, pr: R, pb: B } = box ?? { pl: w * 0.3, pt: h * 0.42, pr: w * 0.7, pb: h * 0.5 };
    const bw = R - L, bh = B - T;
    const side = p.u < 0.36 ? 0 : p.u < 0.72 ? 1 : p.u < 0.86 ? 2 : 3;   // 위 · 아래 · 왼쪽 · 오른쪽
    const drift = 0.04 * Math.sin(t / (6000 + p.seed * 5000) + p.seed * 20);
    const off = 9 + Math.pow((p.v * 2) % 1, 1.6) * 38;                     // 가장자리에 가까울수록 많이
    let x, y;
    if (side < 2) {
      const along = -0.1 + 1.2 * ((p.seed + drift + 1) % 1);
      x = L + bw * along;
      y = side === 0 ? T - off : B + off;
    } else {
      const along = (p.seed + drift + 1) % 1;
      x = side === 2 ? L - 10 - off * 1.6 : R + 10 + off * 1.6;
      y = T + bh * along;
    }
    x += 5 * Math.sin(t / (1800 + p.v * 1600) + p.seed * 31);
    y += 3.5 * Math.cos(t / (2100 + p.u * 1500) + p.seed * 17);
    return [x / w, y / h];
  }

  // 장면마다 입자가 향하는 자리 (화면 비율 0~1), 밝기, 그리고 바로 놓을지(true) · 따라갈지
  target(p, t, s, box) {
    const cx = 0.5, cy = 0.5, w = innerWidth, h = innerHeight, asp = h / w;
    const ang = p.seed * Math.PI * 2;
    const tt = this.still ? 0 : t;
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
      case "converge": {                                      // 별에서 — 별 먼지가 위에서 천천히 내려와 제목 둘레에 머문다
        if (p.v < 0.5) {                                      // 절반 — 제목 둘레로 모이는 먼지
          const fade = 650;
          if (!this.still && s < fade && p.drop !== this.epoch) return [p.x, p.y, 0, true];   // 지금 자리에서 먼저 사그라든다
          const [sx, sy] = this.haloSlot(p, box, tt);
          const startY = -0.04 - p.seed * 0.3;
          if (p.drop !== this.epoch) {                         // 화면 위로 옮겨 두고, 거기서부터 내려온다
            p.drop = this.epoch;
            if (!this.still) { p.x = sx; p.y = startY; p.a = 0; }
          }
          const prog = this.still ? 1 : clamp01((s - fade - p.seed * 2600) / 4600);
          const e = 1 - Math.pow(1 - prog, 3);
          const sway = (1 - e) * 0.012 * Math.sin(tt / 1400 + p.seed * 13);
          return [sx + sway, startY + (sy - startY) * e, 0.22 + 0.5 * e, true];
        }
        // 나머지 — 화면 전체에 아주 느리게 내려앉는 옅은 먼지
        return [p.x + 0.00003 * Math.sin(tt / 1300 + p.seed * 9), (p.y + (this.still ? 0 : 0.00018 * (0.4 + p.seed)) + 1.05) % 1.05 - 0.025, 0.2, true];
      }
      case "cloud": {                                         // 정해지지 않은 세상 — 무한 기호 궤도를 따라 흐르며 되풀이된다
        if (p.u >= 0.64) return [p.x, p.y, 0.14];               // 나머지는 옅은 배경 별로 머문다
        const lane = 0.88 + 0.24 * p.v;                          // 여러 겹의 궤도 — 고리 쪽은 띠처럼, 가운데 교차점은 가늘게
        const phi = p.seed * Math.PI * 2 + tt / (2300 * (1 + 0.06 * (p.v - 0.5)));
        const A = Math.min(w * 0.36, h * 0.9);
        const [lx, ly] = lemniscate(phi);
        p.phi = phi; p.lane = lane * A;
        const tw = 0.7 + 0.3 * Math.sin(tt / (600 + p.seed * 800) + p.seed * 9);
        return [cx + (lx * lane * A) / w, 0.47 + (ly * lane * A) / h, 0.5 * tw];
      }
      case "expand": {                                        // 팽창 — 고리가 계속 밖으로
        const ring = Math.floor(p.k * 6);
        const r = ((t / 4200 + ring / 6) % 1) * 0.75;
        return [cx + Math.cos(ang) * r * asp, cy - 0.04 + Math.sin(ang) * r, 0.9 * (1 - r / 0.75)];
      }
      case "sphere": {                                        // 관측 가능한 우주 — 당신을 중심으로 한 구, 가장자리가 금빛으로
        if (p.k < 0.04) return [cx + (p.seed - 0.5) * 0.004, SPHERE_CY + (p.k - 0.02) * 0.1, 1];
        const r = 0.36 * Math.min(1, 0.15 + s / 3400);
        return [cx + Math.cos(ang + t / 30000) * r * asp, SPHERE_CY + Math.sin(ang + t / 30000) * r, 0.8];
      }
      case "rise":                                            // 끝 — 하늘로 떠올라 실제 하늘에 녹아든다
        return [p.x, p.y - 0.4, 0];
      case "finale": {                                        // 생각보다 넓다 — 구가 천천히 화면 밖으로 넓어지고, 빈자리에는 새 별이 떠오른다
        const tw = 0.55 + 0.45 * Math.sin(t / (700 + p.seed * 900) + p.seed * 9);
        if (this.still) return [p.x, p.y, tw, true];
        let x = p.x + (p.x - 0.5) * 0.0011 * (0.4 + p.seed) + 0.00004 * Math.sin(t / 1300 + p.seed * 9);
        let y = p.y + (p.y - SPHERE_CY) * 0.0011 * (0.4 + p.seed) - 0.00003 * (0.5 + p.seed);
        if (x < -0.02 || x > 1.02 || y < -0.02 || y > 1.02) {   // 화면 밖으로 나가면 안쪽 아무 데서나 옅게 다시
          x = 0.5 + (Math.random() - 0.5) * 0.7;
          y = SPHERE_CY + (Math.random() - 0.5) * 0.7;
          p.a = 0;
        }
        return [x, y, tw, true];
      }
      default: {                                              // 먼지 — 천천히 떠다닌다
        return [((p.x + 0.00002 * (p.seed - 0.5) * 16) + 1) % 1, (p.y + 0.00004 * (0.5 - p.seed) + 1) % 1, 0.45, true];
      }
    }
  }

  frame(now) {
    const ctx = this.ctx, w = innerWidth, h = innerHeight;
    // 움직임 줄이기 — 한 번만 그리므로 장면은 다 펼쳐진 모습(경과 시간을 충분히 크게)으로
    const t = now - this.t0, s = this.still ? 1e9 : now - (this.since ?? this.t0) - (this.delay ?? 0) * 0.4;
    this.px += (this.tx - this.px) * 0.04;
    this.py += (this.ty - this.py) * 0.04;
    ctx.clearRect(0, 0, w, h);
    const ease = this.still ? 1 : this.mode === "rise" ? 0.03 : 0.045;
    const box = this.mode === "rise" ? null : this.boxRect;
    // 글자 위 — 제목 · 숫자 · 사실 · 출처 상자(조금 넓게) 안을 지나는 입자는 옅어진다
    const pad = 3, rects = this.mode === "rise" ? [] : this.rects;
    const inText = (x, y) => rects.some((r) => x > r.left - pad && x < r.right + pad && y > r.top - pad && y < r.bottom + pad);
    const trail = this.mode === "cloud" && !this.still ? clamp01(s / 2400) : 0;
    // 무한 기호는 궤도 위를 계속 움직이므로, 따라가기만 하면 늘 뒤처져 모서리를 깎는다 — 2.6초에 걸쳐 궤도 위에 그대로 올려 둔다
    const follow = this.mode === "cloud" ? Math.max(ease, clamp01(s / 2600)) : ease;
    for (const p of this.p) {
      const [x, y, a, direct] = this.target(p, t, s, box);
      if (direct) { p.x = x; p.y = y; }
      else { p.x += (x - p.x) * follow; p.y += (y - p.y) * follow; }
      const settled = trail ? clamp01(1 - Math.hypot((x - p.x) * w, (y - p.y) * h) / 14) : 0;   // 궤도에 올라선 입자만 잔상
      if (p.vx || p.vy) {                                    // 흩어짐 — 잦아드는 밀림
        p.x += p.vx; p.y += p.vy;
        p.vx *= 0.95; p.vy *= 0.95;
        if (Math.abs(p.vx) + Math.abs(p.vy) < 1e-5) { p.vx = 0; p.vy = 0; }
      }
      p.a = (p.a ?? 0) + (a - (p.a ?? 0)) * (this.still ? 1 : 0.05);
      const depth = 0.4 + p.seed;                              // 시차 — 가까운 입자일수록 마우스를 더 따라온다
      const sx = (p.x + this.px * 0.03 * depth) * w, sy = (p.y + this.py * 0.03 * depth) * h;
      const glow = p.size * (this.mode === "converge" ? 1.25 : this.mode === "cloud" ? 1.15 : 1);
      let alpha = clamp01(p.a);
      if (alpha > 0.01 && inText(sx, sy)) alpha *= this.mode === "cloud" ? 0.32 : 0.22;
      if (p.big && alpha > 0.02) {                             // 큰 광원 — 낮은 불투명도의 번짐 하나 (네온처럼 빛나지 않게)
        const halo = ctx.createRadialGradient(sx, sy, 0, sx, sy, glow * 5);
        halo.addColorStop(0, `rgba(${TONES_RGB[p.tone]},${0.22 * alpha})`);
        halo.addColorStop(1, `rgba(${TONES_RGB[p.tone]},0)`);
        ctx.globalAlpha = 1;
        ctx.fillStyle = halo;
        ctx.fillRect(sx - glow * 5, sy - glow * 5, glow * 10, glow * 10);
      }
      if (settled > 0 && p.phi != null && p.u < 0.64 && alpha > 0.02) {   // 무한 기호의 잔상 — 지나온 궤적이 짧게 남는다
        const [lx, ly] = lemniscate(p.phi);
        ctx.globalAlpha = alpha * 0.42 * trail * settled;
        ctx.strokeStyle = TONES[p.tone];
        ctx.lineWidth = Math.max(0.6, glow * 0.9);
        ctx.beginPath();
        ctx.moveTo(sx, sy);
        for (let k = 1; k <= 5; k++) {
          const [qx, qy] = lemniscate(p.phi - k * 0.045);
          ctx.lineTo(sx + (qx - lx) * p.lane, sy + (qy - ly) * p.lane);
        }
        ctx.stroke();
      }
      ctx.globalAlpha = alpha * (p.tone === 2 ? 0.8 : 1);
      ctx.fillStyle = TONES[p.tone];
      ctx.beginPath();
      ctx.arc(sx, sy, glow, 0, Math.PI * 2);
      ctx.fill();
    }
    // 장면의 중심 빛 — 구의 중심(당신). 글 뒤라 은은하게
    // 장면이 막 바뀐 순간에는 경과 시간(s)이 음수일 수 있다 — 빛의 반지름이 음수가 되지 않게 0~1로 묶는다
    const core = this.mode === "sphere" ? clamp01(s / 1200) : 0;
    if (core > 0) {
      const g = ctx.createRadialGradient(w / 2, SPHERE_CY * h, 0, w / 2, SPHERE_CY * h, 90 * core);
      g.addColorStop(0, `rgba(243,218,213,${0.4 * core})`);
      g.addColorStop(1, "rgba(243,218,213,0)");
      ctx.globalAlpha = 1;
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
    }
    this.drawBursts(now);
    ctx.globalAlpha = 1;
  }

  // 빛무리 — 빠르게 차오르고 천천히 가라앉는다. 흰 중심 → 살구 → 흐린 보라 → 청록으로 번지고, 빛살과 반짝이가 살짝 퍼진다
  drawBursts(now) {
    if (!this.bursts.length) return;
    const ctx = this.ctx, w = innerWidth, h = innerHeight;
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    this.bursts = this.bursts.filter((b) => now - b.t0 < b.dur);
    for (const b of this.bursts) {
      const t = clamp01((now - b.t0) / b.dur), x = b.x * w, y = b.y * h;
      const rise = Math.min(1, t / 0.24), fall = Math.max(0, (t - 0.24) / 0.76);
      const light = rise * (1 - fall * fall);
      const R = 34 + 170 * (this.still ? 0.5 : rise);
      const glow = ctx.createRadialGradient(x, y, 0, x, y, R);
      glow.addColorStop(0, `rgba(255,250,245,${0.95 * light})`);
      glow.addColorStop(0.2, `rgba(243,218,213,${0.75 * light})`);
      glow.addColorStop(0.55, `rgba(185,160,207,${0.26 * light})`);
      glow.addColorStop(1, "rgba(99,169,201,0)");
      ctx.globalAlpha = 1;
      ctx.fillStyle = glow;
      ctx.fillRect(x - R, y - R, R * 2, R * 2);
      if (this.still) continue;
      const ring = clamp01(t / 0.7);                           // 담기는 순간의 물결 — 살구빛 고리 하나가 번져 나가며 옅어진다
      ctx.globalAlpha = 0.5 * (1 - ring);
      ctx.strokeStyle = "#f3dad5";
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.arc(x, y, 16 + 210 * (1 - Math.pow(1 - ring, 3)), 0, Math.PI * 2);
      ctx.stroke();
      for (let i = 0; i < 8; i++) {                            // 은은한 빛살
        const a = (i / 8) * Math.PI * 2 + 0.2, len = (70 + 40 * ((i * 37) % 10) / 10) * rise;
        const g = ctx.createLinearGradient(x, y, x + Math.cos(a) * len, y + Math.sin(a) * len);
        g.addColorStop(0, `rgba(255,240,236,${0.45 * light})`);
        g.addColorStop(1, "rgba(255,240,236,0)");
        ctx.strokeStyle = g;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x + Math.cos(a) * len, y + Math.sin(a) * len);
        ctx.stroke();
      }
      for (let i = 0; i < 36; i++) {                           // 빛무리 속 반짝이 — 바깥으로 살짝 퍼지며 깜빡인다
        const a = i * 2.39996, d = (34 + (i * 53) % 80) * (0.4 + 0.6 * rise);
        ctx.globalAlpha = light * (0.5 + 0.5 * Math.sin((t * 6 + i / 36) * Math.PI));
        ctx.fillStyle = TONES[i % 3];
        ctx.fillRect(x + Math.cos(a) * d, y + Math.sin(a) * d, 1.6, 1.6);
      }
    }
    ctx.restore();
  }
}
