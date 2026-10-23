// VastHorizon API 호출 — 오류는 {code, message} 형식 그대로 ApiError로 던진다.
//
// API 주소: 기본은 같은 서버(상대 경로). 화면만 다른 곳(Cloudflare Pages 등)에 둘 때는
// index.html의 <meta name="vh-api-base" content="https://api.example.com">로 API 서버를 가리킨다 (scripts/build_static.py).
export const API_BASE = (document.querySelector('meta[name="vh-api-base"]')?.content ?? "").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || `요청 실패 (${status})`);
    this.status = status;
    this.code = body?.code || "unknown";
  }
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(API_BASE + path, { headers: { "Content-Type": "application/json" }, ...options });
  } catch {
    throw new ApiError(0, { code: "network", message: "서버에 연결할 수 없습니다. 서버가 켜져 있는지 확인해 주세요." });
  }
  if (res.status === 204) return null;
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, body);
  return body;
}

const get = (path) => request(path);
const post = (path, data) => request(path, { method: "POST", body: JSON.stringify(data ?? {}) });

// 대화 세션 ID — 브라우저마다 하나 (서버는 세션 + 항목별로 대화 기록을 둔다)
export function sessionId() {
  const make = () => (crypto.randomUUID ? crypto.randomUUID() : `s-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  try {
    let id = localStorage.getItem("vh-session");
    if (!id) localStorage.setItem("vh-session", (id = make()));
    return id;
  } catch {
    return (sessionId.memory ??= make());
  }
}

export const api = {
  health: () => get("/api/health"),
  map: () => get("/api/map"),
  constellations: () => get("/api/constellations"),
  item: (id) => get(`/api/items/${encodeURIComponent(id)}`),
  intro: (id) => get(`/api/items/${encodeURIComponent(id)}/intro`),
  search: (q) => get(`/api/items?q=${encodeURIComponent(q)}`),
  history: (id) => get(`/api/history/${encodeURIComponent(id)}?session_id=${sessionId()}`),
  clearHistory: (id) => request(`/api/history/${encodeURIComponent(id)}?session_id=${sessionId()}`, { method: "DELETE" }),
  explore: (query) => post("/api/explore", { query }),
  letter: (body) => post("/api/light-letter", body),
  unfold: (id) => post(`/api/constellations/${encodeURIComponent(id)}/unfold`),
  sky: (body) => post("/api/sky", body),
  themes: () => get("/api/perspective/themes"),
  perspective: (body) => post("/api/perspective", body),
};

// 질문 — SSE(POST) 스트림을 읽어 진행 상태를 알리고 최종 답변을 돌려준다
export async function askStream(itemId, question, onProgress) {
  let res;
  try {
    res = await fetch(`${API_BASE}/api/ask/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId(), item_id: itemId, question }),
    });
  } catch {
    throw new ApiError(0, { code: "network", message: "서버에 연결할 수 없습니다." });
  }
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      if (!/^event: /m.test(block)) continue; // 하트비트(: keepalive) 같은 주석 · 빈 블록은 건너뛴다
      const event = /^event: (.+)$/m.exec(block)?.[1];
      const data = JSON.parse(/^data: (.+)$/m.exec(block)?.[1] ?? "null");
      if (event === "progress") onProgress?.(data.message);
      else if (event === "result") return data;
      else if (event === "error") throw new ApiError(500, data);
    }
  }
  throw new ApiError(500, { code: "stream", message: "답변 스트림이 중간에 끊겼습니다. 다시 시도해 주세요." });
}
