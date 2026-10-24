// 카카오톡으로 보내기 — Kakao SDK for JavaScript의 카카오톡 공유(피드 메시지). 받은 사람은 카드를 눌러 앱의 그 편지(?letter=<id>)로 온다.
//
// - 키: index.html의 <meta name="vh-kakao-key">. 저장소에는 비워 두고 내보낼 때 채운다
//   (서버 [share] kakao_js_key · release.yml의 KAKAO_JS_KEY · build_static.py의 VH_KAKAO_KEY). 비어 있으면 available=false — 버튼을 내지 않는다
// - SDK는 버튼을 처음 누를 때 한 번만 불러 Kakao.init(key)한다. 불러오지 못하면 false — 다음에 누르면 다시 시도한다
// - 피드 메시지 내용(feedMessage)은 DOM 없이 만든다 (node로 시험)
import { excerptOf, firstSentence, plainText } from "./letters.js";

// 카카오 개발자 문서(JavaScript SDK 다운로드)의 2.7 계열 최신 버전과 SRI 값
export const SDK_URL = "https://t1.kakaocdn.net/kakao_js_sdk/2.7.9/kakao.min.js";
export const SDK_INTEGRITY = "sha384-JpLApTkB8lPskhVMhT+m5Ln8aHlnS0bsIexhaak0jOhAkMYedQoVghPfSpjNi9K1";
export const DESC_MAX = 100;              // 피드 설명 — 본문 앞 두 문장, 100자 안
const LOAD_TIMEOUT_MS = 10000;
const KEY_RE = /^[A-Za-z0-9]{1,64}$/;

const metaKey = () => (typeof document === "undefined" ? ""
  : (document.querySelector('meta[name="vh-kakao-key"]')?.content ?? "").trim());

export const KAKAO_KEY = metaKey();
export const available = KEY_RE.test(KAKAO_KEY);

// 피드 설명 — 굵게 · [근거 N]을 걷어 낸 본문의 앞 두 문장. 넘치면 첫 문장만, 그래도 넘치면 잘라 말줄임표
export function feedDescription(text, max = DESC_MAX) {
  const all = plainText(text);
  const first = firstSentence(all);
  const second = firstSentence(all.slice(first.length).trim());
  const two = second ? `${first} ${second}` : first;
  if (two.length <= max) return two;
  if (first.length <= max) return first;
  return excerptOf(first, max - 1);
}

// 앱 딥링크 — 받은 사람이 카드를 누르면 이 편지를 서랍에 연다 (main.js의 ?letter=<id>)
export const letterLink = (id, origin) => `${String(origin).replace(/\/+$/, "")}/?letter=${encodeURIComponent(id)}`;

// Kakao.Share.sendDefault에 넘길 피드 메시지
export function feedMessage({ title, text, id, imageUrl, origin }) {
  const url = letterLink(id, origin);
  const link = { mobileWebUrl: url, webUrl: url };
  return {
    objectType: "feed",
    content: { title: String(title || "VastHorizon의 편지"), description: feedDescription(text), imageUrl,
               imageWidth: 1200, imageHeight: 630, link },
    buttons: [{ title: "편지 보기", link }],
  };
}

let loading = null;

const ready = () => !!globalThis.Kakao?.isInitialized?.();

function initKakao() {
  try {
    if (!ready()) globalThis.Kakao.init(KAKAO_KEY);
    return ready();
  } catch {
    return false;
  }
}

// SDK를 불러 초기화 — 성공하면 true. 키가 없거나 · 불러오지 못하거나(차단 · 네트워크) · init이 실패하면 false
export function loadKakao() {
  if (!available || typeof document === "undefined") return Promise.resolve(false);
  if (ready()) return Promise.resolve(true);
  loading ??= new Promise((resolve) => {
    let script = document.querySelector("script[data-kakao-sdk]");
    const done = (ok) => {
      clearTimeout(timer);
      if (!ok) { script?.remove(); loading = null; }   // 다음에 누르면 다시 시도
      resolve(ok);
    };
    const timer = setTimeout(() => done(false), LOAD_TIMEOUT_MS);
    if (globalThis.Kakao) { done(initKakao()); return; }
    if (!script) {
      script = document.createElement("script");
      script.src = SDK_URL;
      script.integrity = SDK_INTEGRITY;
      script.crossOrigin = "anonymous";
      script.async = true;
      script.dataset.kakaoSdk = "";
      document.head.appendChild(script);
    }
    script.addEventListener("load", () => done(!!globalThis.Kakao && initKakao()), { once: true });
    script.addEventListener("error", () => done(false), { once: true });
  });
  return loading;
}

// 피드 메시지 보내기 — PC 웹은 SDK가 QR · 카카오 로그인 창을 띄운다. 실패 · 취소는 조용히 false
export async function sendFeed(message) {
  try {
    await globalThis.Kakao.Share.sendDefault(message);
    return true;
  } catch {
    return false;
  }
}
