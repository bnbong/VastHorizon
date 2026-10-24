// 사운드 — 오디오 파일 없이 Web Audio API로 합성하는 조용한 배경음과 효과음.
//
// 분위기는 화면과 같다: 밤하늘 위의 편지(남보라 · 살구). 큰 소리와 급격한 소리는 쓰지 않는다.
//   - 마스터 볼륨은 약 -18dB(0.126배)로 낮게 시작하고, 끝에 완만한 컴프레서를 두어 겹쳐도 튀지 않게 한다.
//   - 모든 음정은 D 장조 펜타토닉(D E F# A B) 안에서 고른다. 어떤 효과음이 겹쳐도 서로 부딪치지 않는다.
//   - 잔향은 리버브 대신 긴 딜레이(0.55초)와 약한 피드백으로 만든다. 피드백 경로에 저역 통과 필터를 두어 메아리가 점점 흐려진다.
//
// 배경음(ambient) — 낮은 사인 · 삼각파 세 음을 음마다 두 개씩 살짝 어긋나게(디튠) 겹친 패드.
//   느린 LFO 두 개가 음량과 필터를 서로 다른 빠르기로 흔들어 숨 쉬듯 움직인다. 모드가 바뀌면 2.5초 동안 크로스페이드한다.
//   - prologue: 가장 낮고 어두운 패드. 아직 하늘이 열리기 전, 먼지와 지평선의 시간.
//   - sky:      한 단계 밝은 패드. 하늘을 올려다보는 기본 화면.
//   - map:      조금 더 높고 넓게 열린 패드. 내 세계 지도를 멀리 둘러보는 시간.
//
// 효과음 — 모두 짧고 부드럽게. 시작은 몇 밀리초라도 램프를 주어 '딱' 소리가 나지 않게 한다.
//   - collect: 담기. 위로 올라가는 두 음(A4 → D5)과 그 위에 아주 작은 반짝임 두 개. "주머니에 넣었다"는 작은 기쁨. 0.8초.
//   - sparkle: 프롤로그 장면 전환 · 별 반짝임. 높은 음 하나가 아주 작게 '톡'. 매번 펜타토닉 고음 중 하나를 고른다. 0.2초.
//   - open:    서랍 열기. 낮은 삼각파 '톡'이 살짝 위로 휜다.
//   - close:   서랍 닫기. 같은 '톡'이 살짝 아래로 내려앉는다.
//   - arrive:  프롤로그가 끝나 첫 하늘에 도착. 다섯 음 화음이 차례로 천천히 피어나고 필터가 열린다. 2초.
//   - tick:    조건 탐색 결과 · 버튼의 미세한 피드백. 거의 들리지 않을 만큼 작은 사인 한 번.
//
// 안전장치
//   - 브라우저 자동 재생 정책: 첫 사용자 제스처(unlock) 전에는 AudioContext를 만들지 않는다.
//   - 같은 효과음이 100ms 안에 다시 불리면 무시하고(연타 보호), 동시에 울리는 효과음은 6개까지만.
//   - 설정은 localStorage "vh-sound"("on" | "off", 기본 "on"). 움직임 줄이기 설정과는 무관하다.
//   - 탭이 숨겨지면 배경음 버스를 1.2초 동안 페이드 아웃한 뒤 AudioContext를 suspend하고, 돌아오면 resume해 1.5초 동안 페이드 인한다.
//     숨은 탭에서는 효과음을 내지 않는다. 꺼진 채 돌아오면 패드를 멈추고 suspend를 다시 예약한다(끄기 직후 숨겨 예약이 지워졌을 때).
//   - iOS Safari는 제스처 안의 resume을 거부하기도 한다. pointerdown · touchend에서 AudioContext가 running이 될 때까지 unlock을 다시 시도하고,
//     탭 복귀 · 켜기 뒤 resume이 거부되면 다시 시도를 건다.
//   - 끌 때는 패드를 짧게(0.05초) 멈추고, 노드가 끝난 뒤(+0.2초)에 suspend한다.
//   - 모든 메서드는 오디오를 쓸 수 없거나 꺼져 있으면 조용히 아무것도 하지 않는다. 예외를 밖으로 던지지 않는다.
//   - window · AudioContext는 함수 안에서만 참조하므로 Node에서 import해도 오류가 나지 않는다(순수 함수 테스트용).

export const STORAGE_KEY = "vh-sound";
export const MASTER_DB = -18;
export const ROOT_MIDI = 62;                      // D4
export const PENTATONIC = [0, 2, 4, 7, 9];        // 장조 펜타토닉 (도 레 미 솔 라)
export const THROTTLE_MS = 100;
export const MAX_VOICES = 6;
export const CROSSFADE_S = 2.5;
export const MODES = ["prologue", "sky", "map", "off"];

// ── 순수 함수 ───────────────────────────────────────────────

export const dbToGain = (db) => Math.pow(10, db / 20);
export const gainToDb = (g) => (g > 0 ? 20 * Math.log10(g) : -Infinity);
export const midiHz = (midi) => 440 * Math.pow(2, (midi - 69) / 12);

/** 펜타토닉 step(0 = 근음, 5 = 한 옥타브 위, 음수 = 아래)의 MIDI 번호. */
export function pentaMidi(step, rootMidi = ROOT_MIDI) {
  const n = PENTATONIC.length;
  const octave = Math.floor(step / n);
  const degree = ((step % n) + n) % n;
  return rootMidi + 12 * octave + PENTATONIC[degree];
}

/** 펜타토닉 step의 주파수(Hz). noteHz(0) = D4 ≈ 293.66Hz. */
export const noteHz = (step, rootMidi = ROOT_MIDI) => midiHz(pentaMidi(step, rootMidi));

/** 같은 효과음을 마지막으로 낸 시각(last, ms)과 지금(now) — 너무 가까우면 true(무시). */
export function shouldThrottle(last, now, gap = THROTTLE_MS) {
  if (last == null || !Number.isFinite(last)) return false;
  return now - last < gap;
}

/** 동시에 울리는 효과음 수가 한도에 닿았는지. */
export const voicesFull = (active, max = MAX_VOICES) => active >= max;

/** 저장된 설정 문자열 → 켜짐 여부. 값이 없거나 알 수 없으면 기본값 켜짐. */
export const parseSetting = (raw) => !(typeof raw === "string" && raw.trim().toLowerCase() === "off");
export const serializeSetting = (on) => (on ? "on" : "off");

/** 알 수 없는 모드는 "off"로. */
export const normalizeMode = (mode) => (MODES.includes(mode) ? mode : "off");

/** sparkle이 고를 고음 step(B5 · D6 · E6 · F#6). rand는 [0, 1). */
export const SPARKLE_STEPS = [9, 10, 11, 12];
export const pickSparkleStep = (rand) =>
  SPARKLE_STEPS[Math.min(SPARKLE_STEPS.length - 1, Math.max(0, Math.floor(rand * SPARKLE_STEPS.length)))];

// 모드별 패드 — notes는 rootMidi 기준 펜타토닉 step, 음마다 waves[i] 오실레이터 두 개를 ±detune 센트로 겹친다.
//   level: 패드 음량(마스터 전), cutoff: 저역 통과 기준(Hz), lfoHz: 음량 LFO 빠르기, lfoDepth: 음량 흔들림 비율(0~1),
//   filterLfoHz · filterDepth: 필터 LFO 빠르기와 폭(Hz), delaySend: 딜레이로 보내는 양.
export const PAD_MODES = {
  prologue: { rootMidi: 50, notes: [-2, 0, 3], waves: ["sine", "sine", "triangle"], detune: 5,
    level: 0.18, cutoff: 480, lfoHz: 0.045, lfoDepth: 0.35, filterLfoHz: 0.031, filterDepth: 140, delaySend: 0.35 },
  sky: { rootMidi: 50, notes: [0, 3, 5], waves: ["sine", "triangle", "sine"], detune: 6,
    level: 0.16, cutoff: 760, lfoHz: 0.06, lfoDepth: 0.3, filterLfoHz: 0.043, filterDepth: 220, delaySend: 0.3 },
  map: { rootMidi: 50, notes: [2, 5, 7], waves: ["sine", "triangle", "triangle"], detune: 8,
    level: 0.15, cutoff: 1050, lfoHz: 0.08, lfoDepth: 0.25, filterLfoHz: 0.057, filterDepth: 300, delaySend: 0.4 },
};

/** 효과음 이름과 길이(초, 딜레이 꼬리 제외). 동시 발음 수를 셀 때 쓴다. */
export const SFX_DURATION = { collect: 0.8, sparkle: 0.2, open: 0.18, close: 0.18, arrive: 2.0, tick: 0.06 };

// ── 오디오 그래프 (BaseAudioContext면 무엇이든 — 실시간 · OfflineAudioContext 모두) ─────

/**
 * 마스터 체인을 만든다: (ambient · sfx) → master → 컴프레서 → destination, 그리고 두 버스에서 받는 딜레이 send.
 * 반환하는 노드에 패드와 효과음을 연결한다.
 */
export function createGraph(ctx, { masterDb = MASTER_DB, masterOn = true } = {}) {
  const master = ctx.createGain();
  master.gain.value = masterOn ? dbToGain(masterDb) : 0;
  const comp = ctx.createDynamicsCompressor();
  comp.threshold.value = -14; comp.knee.value = 12; comp.ratio.value = 3;
  comp.attack.value = 0.01; comp.release.value = 0.4;
  master.connect(comp).connect(ctx.destination);

  const ambient = ctx.createGain();
  ambient.gain.value = 1;
  ambient.connect(master);
  const sfx = ctx.createGain();
  sfx.gain.value = 1;
  sfx.connect(master);

  // 긴 딜레이 + 약한 피드백 (리버브 대신)
  const send = ctx.createGain();
  send.gain.value = 1;
  const delay = ctx.createDelay(2);
  delay.delayTime.value = 0.55;
  const fbFilter = ctx.createBiquadFilter();
  fbFilter.type = "lowpass"; fbFilter.frequency.value = 2000; fbFilter.Q.value = 0.3;
  const feedback = ctx.createGain();
  feedback.gain.value = 0.32;
  const wet = ctx.createGain();
  wet.gain.value = 0.22;
  send.connect(delay);
  delay.connect(fbFilter).connect(feedback).connect(delay);
  fbFilter.connect(wet).connect(master);
  return { master, ambient, sfx, send, comp };
}

/** 패드 하나를 만들어 bus(배경음 버스)로 페이드 인. stop(fadeS)로 페이드 아웃 뒤 정리한다. */
export function buildPad(ctx, bus, send, mode, { fadeS = CROSSFADE_S, at = ctx.currentTime } = {}) {
  const p = PAD_MODES[mode];
  if (!p) return null;
  const filter = ctx.createBiquadFilter();
  filter.type = "lowpass"; filter.frequency.value = p.cutoff; filter.Q.value = 0.5;
  const amp = ctx.createGain();
  amp.gain.value = p.level;
  const fade = ctx.createGain();
  fade.gain.setValueAtTime(0, at);
  fade.gain.linearRampToValueAtTime(1, at + fadeS);
  filter.connect(amp).connect(fade).connect(bus);
  const sendGain = ctx.createGain();
  sendGain.gain.value = p.delaySend;
  fade.connect(sendGain).connect(send);

  const oscs = [];
  const perOsc = 1 / (p.notes.length * 2);
  p.notes.forEach((step, i) => {
    const hz = noteHz(step, p.rootMidi);
    const vg = ctx.createGain();
    vg.gain.value = perOsc * (i === 0 ? 1.15 : 0.92);  // 가장 낮은 음을 조금 두껍게
    vg.connect(filter);
    for (const sign of [-1, 1]) {
      const o = ctx.createOscillator();
      o.type = p.waves[i] || "sine";
      o.frequency.value = hz;
      o.detune.value = sign * p.detune;
      o.connect(vg);
      oscs.push(o);
    }
  });

  // 음량 LFO와 필터 LFO — 빠르기를 어긋나게 두어 같은 모양이 반복되지 않게
  const lfo = ctx.createOscillator();
  lfo.frequency.value = p.lfoHz;
  const lfoGain = ctx.createGain();
  lfoGain.gain.value = p.level * p.lfoDepth * 0.5;
  lfo.connect(lfoGain).connect(amp.gain);
  const flfo = ctx.createOscillator();
  flfo.frequency.value = p.filterLfoHz;
  const flfoGain = ctx.createGain();
  flfoGain.gain.value = p.filterDepth;
  flfo.connect(flfoGain).connect(filter.frequency);
  oscs.push(lfo, flfo);
  for (const o of oscs) o.start(at);

  let stopped = false;
  return {
    mode,
    stop(fadeOutS = CROSSFADE_S) {
      if (stopped) return;
      stopped = true;
      const now = ctx.currentTime;
      try {
        fade.gain.cancelScheduledValues(now);
        fade.gain.setValueAtTime(fade.gain.value, now);
        fade.gain.linearRampToValueAtTime(0, now + fadeOutS);
        for (const o of oscs) o.stop(now + fadeOutS + 0.05);
      } catch { /* 이미 멈춘 노드 */ }
      const last = oscs[0];
      last.onended = () => { try { fade.disconnect(); sendGain.disconnect(); } catch { /* 무시 */ } };
    },
  };
}

// 한 음: 짧은 램프로 올라가 지수 곡선으로 사라진다.
function tone(ctx, out, send, { hz, at, type = "sine", attack = 0.01, decay = 0.3, peak = 0.2, glideTo, sendAmt = 0, lowpass }) {
  const o = ctx.createOscillator();
  o.type = type;
  o.frequency.setValueAtTime(hz, at);
  if (glideTo) o.frequency.exponentialRampToValueAtTime(glideTo, at + attack + decay * 0.6);
  const g = ctx.createGain();
  g.gain.setValueAtTime(0, at);
  g.gain.linearRampToValueAtTime(peak, at + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, at + attack + decay);
  let head = o;
  if (lowpass) {
    const f = ctx.createBiquadFilter();
    f.type = "lowpass"; f.frequency.value = lowpass; f.Q.value = 0.4;
    head = o.connect(f);
  }
  head.connect(g).connect(out);
  if (sendAmt > 0 && send) {
    const s = ctx.createGain();
    s.gain.value = sendAmt;
    g.connect(s).connect(send);
  }
  o.start(at);
  o.stop(at + attack + decay + 0.05);
  return o;
}

/** 효과음 하나를 when(초, ctx 시간)에 예약한다. 알 수 없는 이름이면 false. */
export function playSfx(ctx, out, send, name, when = ctx.currentTime, rand = Math.random) {
  const t = when;
  switch (name) {
    case "collect":
      tone(ctx, out, send, { hz: noteHz(3), at: t, attack: 0.012, decay: 0.42, peak: 0.34, sendAmt: 0.3 });
      tone(ctx, out, send, { hz: noteHz(5), at: t + 0.11, attack: 0.012, decay: 0.6, peak: 0.36, sendAmt: 0.35 });
      tone(ctx, out, send, { hz: noteHz(10), at: t + 0.19, attack: 0.006, decay: 0.45, peak: 0.07, sendAmt: 0.6 });
      tone(ctx, out, send, { hz: noteHz(12), at: t + 0.27, attack: 0.006, decay: 0.5, peak: 0.05, sendAmt: 0.6 });
      return true;
    case "sparkle":
      tone(ctx, out, send, { hz: noteHz(pickSparkleStep(rand())), at: t, attack: 0.004, decay: 0.18, peak: 0.2, sendAmt: 0.45 });
      return true;
    case "open":
      tone(ctx, out, send, { hz: noteHz(-2), glideTo: noteHz(-1), type: "triangle", at: t, attack: 0.005, decay: 0.16, peak: 0.42, lowpass: 900, sendAmt: 0.12 });
      return true;
    case "close":
      tone(ctx, out, send, { hz: noteHz(-1), glideTo: noteHz(-3), type: "triangle", at: t, attack: 0.005, decay: 0.16, peak: 0.42, lowpass: 750, sendAmt: 0.1 });
      return true;
    case "arrive": {
      const f = ctx.createBiquadFilter();
      f.type = "lowpass"; f.Q.value = 0.5;
      f.frequency.setValueAtTime(320, t);
      f.frequency.exponentialRampToValueAtTime(2600, t + 1.3);
      f.connect(out);
      const sendIn = ctx.createGain();
      sendIn.gain.value = 0.35;
      f.connect(sendIn).connect(send);
      [-5, 0, 2, 3, 5].forEach((step, i) => {
        tone(ctx, f, null, { hz: noteHz(step), type: i % 2 ? "triangle" : "sine", at: t + i * 0.13,
          attack: 0.55 + i * 0.05, decay: 1.4 - i * 0.12, peak: i === 0 ? 0.18 : 0.14 });
      });
      return true;
    }
    case "tick":
      tone(ctx, out, send, { hz: noteHz(8), at: t, attack: 0.002, decay: 0.05, peak: 0.07 });
      return true;
    default:
      return false;
  }
}

// ── 엔진 (브라우저에서만 실제로 동작) ─────────────────────────

const nowMs = () => (globalThis.performance?.now?.() ?? Date.now());

function readSetting() {
  try { return parseSetting(globalThis.localStorage?.getItem(STORAGE_KEY)); } catch { return true; }
}
function writeSetting(on) {
  try { globalThis.localStorage?.setItem(STORAGE_KEY, serializeSetting(on)); } catch { /* 저장소를 못 쓰면 이번 화면에서만 */ }
}
function rampTo(ctx, param, value, seconds) {
  const now = ctx.currentTime;
  param.cancelScheduledValues(now);
  param.setValueAtTime(param.value, now);
  param.linearRampToValueAtTime(value, now + seconds);
}

const state = {
  inited: false,
  on: true,
  gestured: false,
  ctx: null,
  graph: null,
  pad: null,
  mode: "off",          // 원하는 배경음 모드 (오디오가 아직 없어도 기억)
  hidden: false,
  last: {},             // 효과음 이름 → 마지막 시각(ms)
  voices: 0,
  suspendTimer: 0,
  armed: false,         // 제스처마다 unlock을 다시 시도하는 중인지
};

function safe(fn) {
  return (...args) => { try { return fn(...args); } catch { return undefined; } };
}

function ensureContext() {
  if (state.ctx) return state.ctx;
  const AC = globalThis.AudioContext || globalThis.webkitAudioContext;
  if (!AC) return null;
  state.ctx = new AC({ latencyHint: "interactive" });
  state.graph = createGraph(state.ctx, { masterOn: state.on });
  return state.ctx;
}

const live = () => state.ctx && state.on && state.ctx.state !== "closed";

// 제스처마다 unlock 다시 시도 — AudioContext가 running이 되면 거둔다 (iOS가 resume을 거부해도 다음 제스처에서 살아나게)
const RETRY_EVENTS = ["pointerdown", "touchend"];
const RETRY_OPTS = { capture: true, passive: true };
const running = () => state.ctx?.state === "running";
const onGesture = safe(() => {
  sound.unlock();
  if (running() || state.ctx?.state === "closed") disarmUnlock();
});
function armUnlock() {
  if (state.armed || !globalThis.addEventListener) return;
  state.armed = true;
  for (const type of RETRY_EVENTS) globalThis.addEventListener(type, onGesture, RETRY_OPTS);
}
function disarmUnlock() {
  if (!state.armed) return;
  state.armed = false;
  for (const type of RETRY_EVENTS) globalThis.removeEventListener?.(type, onGesture, RETRY_OPTS);
}
// resume하고, running이 되면 다시 시도를 거두고 거부되면(또는 여전히 멈춰 있으면) 다시 시도를 건다
function resumeCtx(ctx) {
  Promise.resolve(ctx.resume())
    .then(() => { if (ctx.state === "running") disarmUnlock(); else armUnlock(); })
    .catch(() => armUnlock());
}

// 끈 뒤 오디오 멈추기 — delayMs 뒤 패드를 0.05초에 멈추고, 그 노드가 끝난 뒤(정지 0.1초 + 0.2초)에 suspend
const OFF_SUSPEND_MS = 300;
function scheduleOffSuspend(delayMs) {
  clearTimeout(state.suspendTimer);
  state.suspendTimer = setTimeout(safe(() => {
    if (state.on || !state.ctx) return;
    if (state.pad) { state.pad.stop(0.05); state.pad = null; }
    state.suspendTimer = setTimeout(safe(() => { if (!state.on) state.ctx.suspend(); }), OFF_SUSPEND_MS);
  }), delayMs);
}

function syncPad() {
  if (!state.ctx || !state.graph) return;
  const want = state.on ? state.mode : "off";
  if (state.pad && state.pad.mode === want) return;
  if (state.pad) { state.pad.stop(CROSSFADE_S); state.pad = null; }
  if (want !== "off") state.pad = buildPad(state.ctx, state.graph.ambient, state.graph.send, want);
}

function onVisibility() {
  const hidden = globalThis.document?.visibilityState === "hidden";
  if (hidden === state.hidden) return;
  state.hidden = hidden;
  if (!state.ctx || !state.graph) return;
  const ctx = state.ctx;
  clearTimeout(state.suspendTimer);
  if (hidden) {
    rampTo(ctx, state.graph.ambient.gain, 0, 1.2);
    state.suspendTimer = setTimeout(safe(() => { if (state.hidden) ctx.suspend(); }), 1400);
  } else {
    rampTo(ctx, state.graph.ambient.gain, 1, 1.5);
    if (state.on) resumeCtx(ctx);
    else scheduleOffSuspend(0);              // 꺼진 채 돌아왔다 — 끄기 직후 숨겨 지워진 suspend 예약을 다시
  }
}

function trigger(name) {
  if (!live()) return;
  if (state.hidden) return;                  // 숨은 탭에서는 효과음을 내지 않는다
  if (state.ctx.state !== "running") state.ctx.resume().catch(() => {});
  const t = nowMs();
  if (shouldThrottle(state.last[name], t)) return;
  if (voicesFull(state.voices)) return;
  state.last[name] = t;
  if (!playSfx(state.ctx, state.graph.sfx, state.graph.send, name)) return;
  state.voices++;
  setTimeout(() => { state.voices = Math.max(0, state.voices - 1); }, (SFX_DURATION[name] ?? 0.3) * 1000 + 60);
}

export const sound = {
  /** 설정을 읽고 탭 숨김 감지와 첫 제스처 감지를 건다. 여러 번 불러도 한 번만. 오디오는 아직 만들지 않는다. */
  init: safe(({ autoUnlock = true } = {}) => {
    if (state.inited) return;
    state.inited = true;
    state.on = readSetting();
    const doc = globalThis.document;
    if (!doc) return;
    state.hidden = doc.visibilityState === "hidden";
    doc.addEventListener("visibilitychange", safe(onVisibility));
    if (autoUnlock && globalThis.addEventListener) {
      globalThis.addEventListener("keydown", safe(() => sound.unlock()), { capture: true, once: true, passive: true });
      armUnlock();                           // pointerdown · touchend — running이 될 때까지 제스처마다
    }
  }),

  /** 사용자 제스처 핸들러 안에서 부른다. 켜져 있으면 AudioContext를 만들고 resume한 뒤 원하는 배경음을 튼다. */
  unlock: safe(() => {
    if (!state.inited) sound.init();
    state.gestured = true;
    if (!state.on) return;
    const ctx = ensureContext();
    if (!ctx) return;
    if (ctx.state === "running") disarmUnlock();
    else if (ctx.state === "suspended" && !state.hidden) resumeCtx(ctx);
    syncPad();
  }),

  get enabled() { return state.on; },
  /** 켜고 끄기 — 저장하고 0.6초 페이드. 끄면 페이드가 끝난 뒤 오디오를 멈춘다. */
  set enabled(v) {
    try {
      if (!state.inited) sound.init();
      const on = !!v;
      if (on === state.on) return;
      state.on = on;
      writeSetting(on);
      if (on && state.gestured) ensureContext();
      const ctx = state.ctx;
      if (!ctx || !state.graph) return;
      clearTimeout(state.suspendTimer);
      if (on) {
        if (!state.hidden) resumeCtx(ctx);
        rampTo(ctx, state.graph.master.gain, dbToGain(MASTER_DB), 0.6);
        syncPad();
      } else {
        rampTo(ctx, state.graph.master.gain, 0, 0.6);
        scheduleOffSuspend(750);             // 페이드가 끝난 뒤 패드를 멈추고, 노드가 끝난 뒤 suspend
      }
    } catch { /* 조용히 무시 */ }
  },

  /** 배경음 모드: "prologue" | "sky" | "map" | "off". 오디오가 아직 없으면 기억해 두었다가 unlock 때 튼다. */
  ambient: safe((mode) => {
    state.mode = normalizeMode(mode);
    if (live()) syncPad();
  }),

  get mode() { return state.mode; },

  collect: safe(() => trigger("collect")),
  sparkle: safe(() => trigger("sparkle")),
  open: safe(() => trigger("open")),
  close: safe(() => trigger("close")),
  arrive: safe(() => trigger("arrive")),
  tick: safe(() => trigger("tick")),
};
