// 읽어 주기 — 브라우저 음성 합성(speechSynthesis)에 넘길 음성 고르기와 문장 나누기. DOM에 의존하지 않는다 (node로 시험).
//
// - pickVoice: getVoices()에서 한국어(ko-KR) 음성을 우선순위대로 하나 — 없으면 null (lang만 ko-KR로 두고 브라우저에 맡긴다)
//   Yuna(Apple — 프리미엄 · 향상됨 · 기기 안 음성 우선) > Sora > Google 한국의 > Microsoft SunHi · Heami > 그 밖의 한국어
//   목록은 늦게 채워지기도 한다 (Chrome) — voiceschanged 뒤에 다시 고른다
// - speechChunks: 문장 단위로 나눈 발화 — [근거 N] · **굵게** 표시는 걷어 낸다. 너무 긴 문장은 쉼표에서 한 번 더 나눈다
//   (Chrome은 긴 발화를 15초쯤에서 끊는다). 문장마다 SpeechSynthesisUtterance 하나 — 연속 큐가 문장 사이에 짧게 쉰다

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
