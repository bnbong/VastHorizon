// 접기 상태 — 첫 하늘 문장 · 내 세계 요약 카드를 접어 둔 것을 이 기기에 남긴다. DOM에 의존하지 않는다 (node로 시험).
//
// - 기록: { first: true, world: true } — 접힌 곳만 true로 남긴다. 기본은 펼침(키가 없으면 펼침)
// - 알 수 없는 키 · true가 아닌 값 · 깨진 JSON은 버린다

export const FOLD_KEY = "vh-fold";
export const FOLD_PARTS = ["first", "world"];

// 저장된 문자열 → 접힘 상태. 읽을 수 없으면 모두 펼침
export function restoreFold(raw) {
  let saved;
  try { saved = JSON.parse(raw || "null"); } catch { return {}; }
  if (!saved || typeof saved !== "object" || Array.isArray(saved)) return {};
  return Object.fromEntries(FOLD_PARTS.filter((k) => saved[k] === true).map((k) => [k, true]));
}

// 한 곳을 접거나 편 새 상태 — 원래 객체는 그대로 둔다
export function withFold(fold, key, on) {
  const next = { ...restoreFold(JSON.stringify(fold ?? {})) };
  if (!FOLD_PARTS.includes(key)) return next;
  if (on) next[key] = true;
  else delete next[key];
  return next;
}

export function serializeFold(fold) {
  return JSON.stringify(restoreFold(JSON.stringify(fold ?? {})));
}
