// 읽어 주기 — 브라우저 음성 합성(speechSynthesis)에 넘길 음성 고르기와 문장 나누기. DOM에 의존하지 않는다 (node로 시험).
//
// - pickVoice: getVoices()에서 한국어(ko-KR) 음성을 우선순위대로 하나 — 없으면 null (lang만 ko-KR로 두고 브라우저에 맡긴다)
//   Yuna(Apple — 프리미엄 · 향상됨 · 기기 안 음성 우선) > Sora > Google 한국의 > Microsoft SunHi · Heami > 그 밖의 한국어
//   목록은 늦게 채워지기도 한다 (Chrome) — voiceschanged 뒤에 다시 고른다
// - speechChunks: 문장 단위로 나눈 발화 — [근거 N] · **굵게** 표시는 걷어 낸다. 너무 긴 문장은 쉼표에서 한 번 더 나눈다
//   (Chrome은 긴 발화를 15초쯤에서 끊는다). 문장마다 SpeechSynthesisUtterance 하나 — 연속 큐가 문장 사이에 짧게 쉰다
// - 서버 읽어 주기(GET /api/l/<id>/audio.mp3, Google TTS)를 먼저 쓰고, 못 쓰면 같은 클릭에서 위의 기기 음성으로 읽는다.
//   shouldFallback: 서버 응답(상태 · 오류 코드)이 기기 음성으로 넘어갈 경우인가 · serverPause: 이 세션에서 서버를 다시 부르지 않을 시간

export const SPEECH_RATE = 0.92;
export const SPEECH_PITCH = 0.95;
export const CHUNK_MAX = 160;              // 한 발화의 최대 글자 수 — 넘치면 쉼표에서 나눈다
export const VOICE_HINT = "더 자연스러운 목소리: macOS 시스템 설정 → 손쉬운 사용 → 음성 콘텐츠 → 시스템 음성 → 한국어 Yuna(향상됨 · 프리미엄)를 내려받아 주세요";

const KOREAN = /^ko([-_]|$)/i;
const TIERS = [
  [/yuna|유나/i, 500],
  [/sora|소라/i, 400],
  [/google\s*(한국의|korean)/i, 300],
  [/sunhi|heami|선희|해미/i, 200],
];

export const isKorean = (v) => KOREAN.test(String(v?.lang ?? ""));

// 음성 점수 — 한국어가 아니면 -1. 같은 이름 계열 안에서는 프리미엄 > 향상됨 > 기본, 기기 안 음성(localService)이 앞
export function voiceScore(v) {
  if (!isKorean(v)) return -1;
  const name = String(v.name ?? "");
  const tier = TIERS.find(([re]) => re.test(name));
  let score = tier ? tier[1] : 100;
  if (/premium|프리미엄/i.test(name)) score += 40;
  else if (/enhanced|향상/i.test(name)) score += 30;
  if (/natural/i.test(name)) score += 20;          // Microsoft SunHi Online (Natural)
  if (v.localService) score += 10;
  return score;
}

// 가장 나은 한국어 음성 — 점수가 같으면 목록 앞의 것. 한국어 음성이 없으면 null
export function pickVoice(voices) {
  let best = null;
  let bestScore = -1;
  for (const v of Array.isArray(voices) ? voices : Array.from(voices ?? [])) {
    const s = voiceScore(v);
    if (s > bestScore) { best = v; bestScore = s; }
  }
  return bestScore >= 0 ? best : null;
}

// 화면 표시용 기호를 걷어 낸 글 — [근거 1, 2] · **굵게**
export function speakableText(text) {
  return String(text ?? "")
    .replace(/\s*\[근거\s*[\d,，\s]+\]/g, "")
    .replace(/\*\*/g, "")
    .replace(/[ \t]+/g, " ")
    .trim();
}

// 너무 긴 문장은 쉼표 뒤에서 나눈다 — 그래도 길면 그대로 (어절 중간은 자르지 않는다)
function splitLong(sentence, max) {
  if (sentence.length <= max) return [sentence];
  const parts = sentence.split(/(?<=[,，])\s+/);
  const out = [];
  let cur = "";
  for (const p of parts) {
    if (cur && cur.length + 1 + p.length > max) { out.push(cur); cur = p; }
    else cur = cur ? `${cur} ${p}` : p;
  }
  if (cur) out.push(cur);
  return out;
}

// 읽어 줄 발화 목록 — 문장(. ! ? 。 … 뒤 공백 · 줄바꿈) 단위
export function speechChunks(text, max = CHUNK_MAX) {
  return speakableText(text)
    .split(/(?<=[.!?。？！…])\s+|\n+/)
    .map((s) => s.replace(/\s+/g, " ").trim())
    .filter((s) => /[\p{L}\p{N}]/u.test(s))
    .flatMap((s) => splitLong(s, max));
}

// ── 서버 읽어 주기 (Google TTS) ─────────────────────────────────────────────

export const AUDIO_CACHE_MAX = 8;          // 세션 안에서 다시 쓰는 서버 오디오(blob) 수 — 공유 ID별
export const QUOTA_NOTE = "이달 서버 읽어 주기 한도를 다 써서 기기 음성으로 읽어 드려요";
// 503 tts_quota의 reason → 안내 (서버가 message를 주면 그 문구를 그대로 쓴다)
export const QUOTA_NOTES = {
  month: QUOTA_NOTE,
  day: "오늘 서버 읽어 주기 한도를 다 써서 기기 음성으로 읽어 드려요",
  cooldown: "서버 읽어 주기를 잠시 쉬고 있어서 기기 음성으로 읽어 드려요",
};

// 한도 안내 한 줄 — 서버 message > reason별 문구 > 이달 한도 문구
export function quotaNote(reason, message) {
  const own = typeof message === "string" ? message.trim() : "";
  return own || QUOTA_NOTES[reason] || QUOTA_NOTE;
}

// 서버 오디오 응답이 실패인가 — 성공(2xx)이 아니거나 오류 코드가 있으면 기기 음성으로 (status 0: 네트워크 오류 · 공유 실패)
// 503 tts_unavailable · tts_quota, 502 tts_failed, 429 rate_limited, 404 share_not_found …
export function shouldFallback(status, code) {
  const s = Number(status);
  return !(s >= 200 && s < 300) || Boolean(code);
}

// 이 세션에서 서버 읽어 주기를 쉬는 시간(ms) — 쓸 수 없음이면 끝까지, 한도면 Retry-After(없으면 10분)만큼, 그 밖에는 쉬지 않는다
export function serverPause(status, code, retryAfter) {
  if (code === "tts_unavailable") return Infinity;
  if (code === "tts_quota") {
    const s = Number(retryAfter);
    return (Number.isFinite(s) && s > 0 ? s : 600) * 1000;
  }
  return 0;
}

// 아주 짧은 무음 WAV(8kHz · 8비트 · 1채널) — iOS Safari는 클릭 안에서 한 번 재생한 audio 요소만 나중에(await 뒤) 재생을 허락한다
export function silentWav(samples = 80) {
  const bytes = new Uint8Array(44 + samples);
  const view = new DataView(bytes.buffer);
  const text = (at, s) => { for (let i = 0; i < s.length; i += 1) bytes[at + i] = s.charCodeAt(i); };
  text(0, "RIFF"); view.setUint32(4, 36 + samples, true); text(8, "WAVE");
  text(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, 8000, true); view.setUint32(28, 8000, true); view.setUint16(32, 1, true); view.setUint16(34, 8, true);
  text(36, "data"); view.setUint32(40, samples, true);
  bytes.fill(128, 44);                     // 8비트 PCM의 0(무음)은 128
  return bytes;
}
