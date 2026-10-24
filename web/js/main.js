// VastHorizon 화면 (디자인 v2) — 무대가 곧 페이지. 떠 있는 머리 · 발, 필요할 때만 여는 서랍, 처음 · 끝 장면.
//
//   하늘(첫 화면) ─ 흐릿한 빛 · 별을 누르면 그 천체의 이야기를 먼저 읽고, '내 세계에 담기'를 누르면
//                   흐릿한 빛이 한 점으로 모이며 이름 · 거리가 생기고, 내 세계의 반지름이 넓어진다
//   서랍         ─ 천체(물어보기) · 천체 목록 · 조건 탐색 · 빛의 편지 · 마음 한 줄 · 오늘 밤 하늘 · 별자리 펼치기 · 받은 편지
//   지평선 길    ─ 지평선(하늘) · 태양계 · 별 · 은하 · 우주의 끝 — 지평선 너머를 누르면 지구에서 떠오른다

import { absoluteUrl, api, API_BASE, askStream } from "./api.js";
import { departureLabel, distanceText, horizonKm, horizonScale, measure, worldScaleLine } from "./astro.js";
import { clearHistoryFlow, requestGate, runLatest } from "./flows.js";
import { icon } from "./icons.js";
import { miniLogoSvg } from "./logo.js";
import { MapMode } from "./map.js";
import { Stage } from "./scene.js";
import { colorWord, pickFirstLight } from "./skydata.js";
import { EARTH_ID, heroFact, placeNote } from "./facts.js";
import { SkyMode } from "./sky.js";
import { playPrologue, STORAGE_KEY as PROLOGUE_KEY } from "./prologue.js";
import { igniteBurst } from "./dream.js";
import { loadBlackHoles, mountBlackHole } from "./blackhole.js";
import { mountBodyView, stopBodyView } from "./bodyview.js";
import { bodyInfo, sizeCaption } from "./solarbodies.js";
import { analogies, growthText, knownAndUnknown, newlyInside } from "./worldscale.js";
import { entryOf, localDate, reachOf, recent, restoreVisited, serialize, todays, WORLD_KEY } from "./journal.js";
import { UnfoldMode } from "./unfold.js";
import { farthestParts, markHtml, worldHeading } from "./worldmarks.js";
import { advance, popView } from "./drawerstack.js";
import { sound } from "./sound.js";
import { available as kakaoAvailable, feedMessage, loadKakao, sendFeed } from "./kakao.js";
import { addLetter, findLetter, firstSentence, letterDate, letterItemIds, LETTERS_KEY, makeEntry, plainText, removeLetter, restoreLetters,
         sameLetter, serializeLetters, setShare, sharedView } from "./letters.js";

const $ = (sel, root = document) => root.querySelector(sel);
const app = $("#app");
const drawerBody = $("#drawer-body");
const state = { mode: "sky", item: null, map: null, sky: null, unfold: null, constellations: [], refYear: 2026,
                drawer: null, scene: null, catalog: null };
const DEFAULT_CONSTELLATION = "오리온자리";
const LY_KM = 9460730472580.8;
const GROUPS = [["all", "전체"], ["star", "별"], ["messier", "메시에 천체"], ["solar_system", "태양계"],
                ["human_made", "인류의 발자취"], ["constellation", "별자리"]];
const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches
  || new URLSearchParams(location.search).get("motion") === "off";

// ── 글 · 근거 표시 ───────────────────────────────────────────────────────

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// 답변 본문 — **굵게**는 강조(Keyword), [근거 N]은 근거 목록으로 가는 버튼
function answerHtml(text, scope) {
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, '<em class="kw">$1</em>')
    .replace(/\[근거\s*([\d,\s]+)\]/g, (_, nums) => nums.split(",").map((n) => n.trim()).filter(Boolean)
      .map((n) => `<button class="cite" type="button" data-scope="${scope}" data-n="${n}" aria-label="근거 ${n}">${n}</button>`).join(""))
    .replace(/\n/g, "<br>");
}

// 원문 링크로 만들 주소 — http: · https:만 (javascript: · data: 등은 글자로만)
const linkable = (url) => { try { return /^https?:$/.test(new URL(String(url ?? "")).protocol); } catch { return false; } };

// 근거 목록 — 제목 · 원문 링크 · 출처 종류 태그(메타데이터 / 외부 문서) · 발췌
function evidenceHtml(cited, scope) {
  return `<div><div class="evidence-title">근거</div><ol class="evidence" id="ev-${scope}">${cited.map((ev) => {
    const meta = ev.kind === "항목 메타데이터";
    const name = `${esc(ev.title)}${ev.section ? `<span class="sec"> › ${esc(ev.section)}</span>` : ""}`;
    return `<li data-n="${ev.number}"><span class="num">${ev.number}</span><div>
      ${linkable(ev.url) ? `<a href="${esc(ev.url)}" target="_blank" rel="noopener">${name}</a>` : `<span class="ev-title">${name}</span>`}
      <span class="meta"><span class="tag ${meta ? "meta-tag" : ""}">${meta ? "메타데이터" : "외부 문서"}</span><span class="src">${esc(ev.source_type)}</span></span>
      ${ev.excerpt ? `<div class="excerpt">${esc(ev.excerpt)}</div>` : ""}</div></li>`;
  }).join("")}</ol></div>`;
}

const NO_CITE = "이 답변에는 인용된 근거가 없습니다.";
function resultHtml(body, cited, scope, notice, warnings = [], cls = "") {
  const evidence = cited?.length ? `${notice ? `<p class="status warn">${esc(notice)}</p>` : ""}${evidenceHtml(cited, scope)}`
    : `<p class="no-cite">${esc(notice || NO_CITE)}</p>`;
  return `<div class="answer ${cls}">${answerHtml(body, scope)}</div>
    ${warnings.map((w) => `<p class="status warn">${esc(w)}</p>`).join("")}${evidence}`;
}

const statusHtml = (text, tone = "progress") =>
  `<p class="status ${tone === "progress" ? "" : tone}">${tone === "progress" ? miniLogoSvg() : ""}${esc(text)}</p>`;

function measureHtml(km, { label, caption, size = "m", center = false, unitOnly } = {}) {
  const m = unitOnly ?? measure(km);
  return `<div class="measure ${size} ${center ? "center" : ""}">
    ${label ? `<div class="measure-label">${esc(label)}</div>` : ""}
    <div class="measure-row"><span class="measure-value">${esc(m.value)}</span><span class="measure-unit">${esc(m.unit)}</span></div>
    ${caption ? `<div class="measure-caption">${esc(caption)}</div>` : ""}</div>`;
}

const btn = (label, { variant = "secondary", size = "sm", ic, icRight, id, attrs = "" } = {}) =>
  `<button type="button" class="btn btn-${variant} ${size ? `btn-${size}` : ""}" ${id ? `id="${id}"` : ""} ${attrs}>${ic ? icon(ic, size === "lg" ? 17 : 15) : ""}<span class="label-text">${esc(label)}</span>${icRight ? icon(icRight, 15) : ""}</button>`;

// multiline: 여러 줄 입력(textarea) — Enter로 보내고 Shift+Enter로 줄을 바꾼다 (마음 한 줄)
function composerHtml(id, { ic = "message-circle", placeholder, type = "text", min, max, multiline = false, label } = {}) {
  const field = multiline
    ? `<textarea rows="1" maxlength="300" placeholder="${esc(placeholder)}" aria-label="${esc(label ?? placeholder)}"></textarea>`
    : `<input type="${type}" ${min !== undefined ? `min="${min}" max="${max}"` : ""} maxlength="300" placeholder="${esc(placeholder)}" aria-label="${esc(label ?? placeholder)}">`;
  return `<form class="composer ${multiline ? "multi" : ""}" id="${id}" autocomplete="off">${icon(ic, 16)}
    ${field}
    <button class="send" type="submit" aria-label="보내기">${icon("arrow-up", 16)}</button></form>`;
}

// 입력이 있을 때만 보내기 버튼이 켜진다
function bindComposer(form, onSubmit) {
  const input = form.querySelector("input, textarea");
  const sync = () => form.classList.toggle("ready", !!input.value.trim());
  const grow = () => {                          // 여러 줄 입력은 내용만큼 (최대 5줄 남짓)
    if (input.tagName !== "TEXTAREA") return;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  };
  input.addEventListener("input", () => { sync(); grow(); });
  if (input.tagName === "TEXTAREA") input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.shiftKey || e.isComposing || e.keyCode === 229) return;   // 한글 조합 중의 Enter는 글자를 마치는 것
    e.preventDefault();
    form.requestSubmit();
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const value = input.value.trim();
    if (!value || form.dataset.busy) return;
    onSubmit(value, input);
    sync();
  });
  let hadFocus = false;
  return { input, setBusy: (b) => {
    if (b) { form.dataset.busy = "1"; hadFocus = form.contains(document.activeElement); }
    else delete form.dataset.busy;
    input.disabled = b;
    // 기다리는 동안 입력창이 잠겨 포커스가 문서 처음으로 빠졌다 — 키보드로 쓰던 사람이 제자리에서 이어 가게
    if (!b && hadFocus && form.isConnected && (!document.activeElement || document.activeElement === document.body)) input.focus({ preventScroll: true });
  } };
}

drawerBody.addEventListener("click", (e) => {
  const cite = e.target.closest(".cite");
  if (!cite) return;
  const li = $(`#ev-${cite.dataset.scope} li[data-n="${cite.dataset.n}"]`);
  if (!li) return;
  li.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "center" });
  li.classList.add("flash");
  setTimeout(() => li.classList.remove("flash"), 1600);
});

const errorText = (e) => e?.message || "처리 중 문제가 생겼습니다.";

// ── 서랍 — 패널 세대 ─────────────────────────────────────────────────────
// 서랍 내용을 바꾸는 기능마다 새 세대를 받는다. await 뒤에는 자기 세대가 아직 살아 있는지 보고,
// 지난 세대의 응답(성공 · 오류 모두)은 화면 · state에 반영하지 않는다. (리뷰 P2 — 응답 순서 · 화면 수명)
let panelGen = 0;
let panelLeave = null;                         // 지금 서랍 화면이 떠날 때 정리할 일 (예: 오늘 밤 하늘의 시각 막대 타이머)
function claimPanel() {
  stopSpeaking();                              // 읽어 주던 편지는 화면이 바뀌면 멈춘다
  const gen = ++panelGen;
  const leave = panelLeave;
  panelLeave = null;
  leave?.();
  return () => gen === panelGen;
}

// 서랍 안 작은 WebGL 화면(블랙홀 · 천체 근접 뷰) — 한 번에 하나만. 서랍 내용이 바뀌거나 닫히면 컨텍스트까지 정리한다
let drawerView = null;
function stopDrawerView() {
  drawerView?.stop();
  drawerView = null;
  stopBodyView();
}

function openDrawer(kind, html) {
  if (kind !== "item") clearSelection();      // 다른 기능 서랍으로 바뀌면 선택 표시도 지운다
  stopDrawerView();
  state.drawer = kind;
  drawerBody.dataset.kind = kind;
  const hadFocus = drawerBody.contains(document.activeElement);   // 서랍 안에서 다른 화면으로 — 교체로 사라질 포커스를 새 화면 제목으로
  drawerBody.innerHTML = html;
  drawerBody.scrollTop = 0;
  if (hadFocus) focusDrawerHeading();
  drawerBody.classList.remove("entering");
  void drawerBody.offsetWidth;                 // 내용이 바뀔 때마다 떠오르는 연출을 다시
  drawerBody.classList.add("entering");
  app.classList.add("drawer-open");
  const drawer = $("#drawer");
  if (drawer.inert) {                          // 닫혀 있다 열릴 때만 — 포커스를 서랍으로, 닫으면 원래 자리로
    drawer.inert = false;
    sound.open();
    // 메뉴 안에서 열었으면 닫을 때 메뉴 버튼으로 (메뉴는 닫혀 숨는다)
    openDrawer.returnTo = document.activeElement?.closest?.("#menu") ? $("#menu-btn") : document.activeElement;
    $("#drawer-close").focus({ preventScroll: true });
  }
  drawer.setAttribute("aria-hidden", "false");
  stage?.setInset(window.innerWidth > 650 ? drawer.offsetWidth + 32 : 0);   // 서랍(폭 + 여백 16 × 2) 만큼 시야를 비킨다 (650px 이하는 아래 시트)
  renderChrome();
}

// 새 서랍 화면의 첫 제목(h2 · .name)으로 포커스 — 제목이 없으면 닫기 버튼으로
function focusDrawerHeading() {
  const head = drawerBody.querySelector("h2, .name");
  if (head) {
    head.tabIndex = -1;
    head.focus({ preventScroll: true });
  } else $("#drawer-close").focus({ preventScroll: true });
}

// ── 서랍 — 뒤로 가기 ─────────────────────────────────────────────────────
// 서랍 화면마다 다시 그릴 수 있는 설명자(drawerstack.js)를 남긴다. 진입 함수가 맨 앞에서 enterView를 부르고,
// 같은 화면 안에서 바뀐 상태(목록 필터 · 검색어 · 탐색 결과)는 updateView로 지금 화면의 설명자만 고친다.
// 뒤로 가기는 스택에서 하나 꺼내 그 설명자의 진입 함수를 다시 부른다(이때는 쌓지 않는다). 서랍을 닫으면 비운다
let nav = { stack: [], current: null };
let restoringView = false;

function enterView(view) {
  if (restoringView) nav.current = view;
  else nav = advance(nav, view);
  renderBack();
}

function updateView(view) {
  nav.current = view;
}

function renderBack() {
  $("#drawer-back").hidden = !nav.stack.length;   // 첫 화면에서는 숨긴다
}

function goBack() {
  const { stack, view } = popView(nav.stack);
  if (!view) return;
  nav.stack = stack;
  restoringView = true;
  try { openView(view); } finally { restoringView = false; }   // 진입 함수의 enterView는 await 앞에서 불린다
  renderBack();
  if ($("#drawer-back").hidden && document.activeElement === $("#drawer-back")) $("#drawer-close").focus({ preventScroll: true });
}

// 설명자 → 진입 함수
function openView(v) {
  switch (v.kind) {
    case "item": return selectItem(v.id, { fly: false, hint: v._hint ?? null });
    case "catalog": return showCatalog({ group: v.group, q: v.q });
    case "explore": return showExplore({ query: v.query });
    case "letter": return showLetter(v.body);
    case "perspective": return showPerspective({ req: v.req });
    case "tonight": return showSkyGuide();
    case "letters": return showLetters();
    case "kept": return showKept(v);
    case "unfold":
      if (state.mode === "unfold" && state.unfold?.con.item_id === v.id) return showUnfoldPanel(state.unfold.con);
      return setMode("unfold", v.id);
    default: return null;
  }
}

// 같은 요청을 다시 그릴 때 — 뒤로 가기로 돌아온 탐색 결과 · 편지 · 마음 한 줄은 서버에 다시 묻지 않고 같은 결과를 (최근 20개)
const replies = new Map();
function remembered(key, work) {
  if (replies.has(key)) return Promise.resolve(replies.get(key));
  return work().then((res) => {
    replies.set(key, res);
    if (replies.size > 20) replies.delete(replies.keys().next().value);
    return res;
  });
}

// 선택 표시 (하늘 · 내 세계) — 누른 천체 둘레의 맥박 고리
function showSelection(sel) {
  state.sky?.select(sel);
  state.map?.select(sel?.id, { fly: false });
}

function clearSelection() {
  showSelection(null);
}

function closeDrawer() {
  claimPanel();                                // 진행 중인 응답이 닫힌 서랍을 다시 그리지 않게
  stopDrawerView();
  clearSelection();
  state.drawer = null;
  nav = { stack: [], current: null };          // 서랍을 닫으면 뒤로 가기 기록도 비운다
  renderBack();
  app.classList.remove("drawer-open");
  const drawer = $("#drawer");
  if (!drawer.inert) sound.close();            // 열려 있던 서랍만 — 이미 닫힌 서랍을 다시 닫을 때는 조용히
  const inside = drawer.contains(document.activeElement);
  drawer.setAttribute("aria-hidden", "true");
  drawer.inert = true;                         // 숨은 서랍 안으로 포커스가 들어가지 않게
  if (inside && openDrawer.returnTo?.isConnected) openDrawer.returnTo.focus({ preventScroll: true });
  stage?.setInset(0);
  renderChrome();
}

// ── 내 세계 — 알아간 빛의 기록. 날마다 지워지지 않고 쌓인다 (journal.js) ──────────────────────
//   가장 먼 빛(world.km · name)은 거리를 아는 기록에서 계산한다. 시작은 지평선(약 4.7km)

const HORIZON_KM = horizonKm();
const world = loadWorld();

function loadWorld() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(WORLD_KEY) || "null"); } catch { /* 저장소를 못 쓰면 이번 화면에서만 */ }
  const w = { visited: restoreVisited(saved, localDate()) };
  return Object.assign(w, reachOf(w.visited, HORIZON_KM));
}

function syncReach() {
  const r = reachOf(world.visited, HORIZON_KM);
  world.km = r.km;
  world.name = r.name;
}

function saveWorld() {
  try { localStorage.setItem(WORLD_KEY, serialize(world.visited)); } catch { /* 무시 */ }
}

const isObserved = (id) => world.visited.some((v) => v.id === id);
const todayCount = () => todays(world.visited, localDate()).length;

// 알아간 빛 하나 — 거리를 몰라도 기록에 남는다. 가장 먼 빛이 바뀌면 그만큼 더 멀리 닿는다
// 반환: { id, name, km, count, farther, fromKm, toKm, passed } (이미 담은 천체면 null)
function discover(item) {
  if (!item?.id || isObserved(item.id)) return null;
  const fromKm = world.km;
  world.visited.push(entryOf(item, localDate()));
  syncReach();
  const farther = world.km > fromKm;
  const known = new Set(world.visited.map((v) => v.id));
  const d = { id: item.id, name: item.name, km: item.distance_km > 0 ? item.distance_km : null, count: world.visited.length,
              group: item.group, farther, fromKm, toKm: world.km,
              passed: farther ? newlyInside(mapPoints(), fromKm, world.km).filter((p) => !known.has(p.id)) : [] };
  saveWorld();
  state.sky?.setObserved(world.visited);
  state.map?.setWorld(world.km, world.visited, { fresh: state.mode === "map" ? item.id : null });   // 지도에서 담으면 표식 · 선이 빛무리와 함께
  renderChrome();
  sound.collect();
  showDiscovery(d);
  return d;
}

// 지구 — 내 세계의 첫 천체. 프롤로그의 구 장면('그 구의 중심에는 언제나, 바라보는 당신이')에서 담기고,
// 프롤로그를 건너뛰었거나 이미 본 사람도 앱을 켤 때 조용히 담긴다 (발견 알림 · 리본 굴림 없이, 날짜는 오늘).
// 거리 0이라 가장 먼 빛은 그대로, 알아간 빛 N개 · 오늘 새로 알아간 빛에는 센다. 반환: 새로 담았으면 true
function ensureEarth() {
  if (isObserved(EARTH_ID)) return false;
  const earth = state.mapData?.points?.find((p) => p.id === EARTH_ID) ?? { id: EARTH_ID, name: "지구", group: "solar_system" };
  world.visited.unshift(entryOf({ ...earth, distance_km: null }, localDate()));
  syncReach();                                               // 거리 0 — 가장 먼 빛 · 리본 숫자는 그대로
  saveWorld();
  state.sky?.setObserved(world.visited);
  state.map?.setWorld(world.km, world.visited);
  renderChrome();
  return true;
}

// 지구 말고도 알아간 빛이 있는지 — 첫 하늘의 '첫 번째 빛' 문장은 지구만 담긴 새 사람에게 그대로
const metBeyondEarth = () => world.visited.some((v) => v.id !== EARTH_ID);

// 기록 지우기 — 사람이 직접 고를 때만. 지구(내 세계의 첫 천체 · 당신이 서 있는 곳)는 남는다
function resetWorld() {
  world.visited = world.visited.filter((v) => v.id === EARTH_ID);
  syncReach();
  saveWorld();
  state.sky?.setObserved(world.visited);
  state.map?.setWorld(world.km, world.visited);
  renderChrome();
  toast("알아간 빛의 기록을 지웠습니다 · 오늘은 어떤 빛을 알아가 볼까요?");
}

// 거리가 있는 지도 천체 (지구 제외) — 거리 안 · 밖을 셀 때
const mapPoints = () => (state.mapData?.points ?? []).filter((p) => p.placement !== "origin" && p.km > 0);

// 알아간 순간의 안내 — 가까운 천체든 먼 천체든 새 빛 하나는 늘 의미가 있다. 더 멀리 닿았으면 그 거리를 덧붙인다
function showDiscovery(d) {
  const el = $("#growth");
  const line = d.farther
    ? `이번에는 <em class="kw plain">${esc(distanceText(d.toKm))}</em> 너머까지 닿았습니다 · 닿은 거리 ${esc(growthText(d.fromKm, d.toKm))}`
    : d.km ? `가장 먼 빛은 그대로지만, 내 세계는 빛 하나만큼 더 풍성해졌습니다`
    : d.id === EARTH_ID ? `지구는 내가 있는 곳이라, 알아간 빛 기록의 첫 자리에 남았습니다`
    : d.group === "constellation" ? `별자리는 여러 거리의 별이 모인 모양이라 지도에는 놓지 않고, 알아간 빛 기록에 남겼습니다`
    : `거리는 아직 확인되지 않았지만, 알아간 빛 기록에 남았습니다`;
  const go = d.farther ? "넓어진 내 세계 보기" : d.km ? "내 세계에서 보기" : "알아간 빛 기록 보기";
  // 별 · 메시에 천체처럼 빛이 출발한 해를 셀 수 있는 천체면 그 빛의 편지로 (이미 편지 화면에서 담았으면 빼고)
  const canLetter = (d.group === "star" || d.group === "messier") && d.km > 0 && state.drawer !== "letter";
  el.innerHTML = `<div class="growth-head"><span class="growth-x">${d.count.toLocaleString("ko-KR")}번째 빛</span>
      <span>내 세계에 새로운 빛 하나가 더해졌습니다 · <em class="kw plain">${esc(d.name)}</em></span></div>
    <p class="growth-in">${line}</p>
    ${d.passed.length ? `<p class="growth-in">그 사이에 아직 알아가지 않은 천체 ${d.passed.length.toLocaleString("ko-KR")}개 · 앞으로 알아갈 가능성입니다</p>` : ""}
    <div class="growth-actions"><button type="button" class="btn btn-horizon btn-sm" id="growth-go">${icon("globe", 14)}<span>${go}</span></button>
      ${canLetter ? `<button type="button" class="btn btn-horizon btn-sm" id="growth-letter">${icon("mail", 14)}<span>이 빛의 편지 받기</span></button>` : ""}</div>`;
  el.hidden = false;
  el.classList.remove("show");
  void el.offsetWidth;
  el.classList.add("show");
  clearTimeout(showDiscovery.timer);
  showDiscovery.timer = setTimeout(() => { el.hidden = true; }, 9000);
  $("#growth-go").addEventListener("click", () => {
    el.hidden = true;
    if (d.farther) playGrowth(d);
    else openWorld(d.km ? { focus: d.id } : { log: true });
  });
  $("#growth-letter")?.addEventListener("click", () => {
    el.hidden = true;
    showLetter({ item_id: d.id });
  });
}

// 넓어지는 순간을 내 세계 보기에서 — 닿은 거리의 테두리가 자라고, 새로 알게 된 천체의 이름이 또렷해진다
function playGrowth(g) {
  closeScene();
  closeDrawer();
  if (state.mode !== "map") setMode("map");
  const crossed = pickCrossed(g.passed, 8);
  state.map.expandTo(g.fromKm, g.toKm, crossed, () => {
    toast(`<em class="kw plain">${esc(g.name)}</em>까지 내 세계가 닿았습니다 · 닿은 거리 ${esc(growthText(g.fromKm, g.toKm))}`);
  }, g.id);
}

// 이름을 띄울 천체 — 거리(로그)에 고르게 몇 개만 (너무 많으면 겹친다)
function pickCrossed(points, max) {
  if (points.length <= max) return points;
  return Array.from({ length: max }, (_, i) => points[Math.round((i * (points.length - 1)) / (max - 1))]);
}

// 담기 — 천체의 이야기를 읽고 난 뒤 사람이 직접 누른다. 거리를 몰라도 알아간 빛으로 기록할 수 있다
// 알아간 빛 표식 — 살구색 채운 원 안의 ✦ (하늘 · 목록 · 서랍 · 내 세계에서 같은 모양)
const collectedHtml = (text) => `<div class="collected"><span class="known-mark" aria-hidden="true">✦</span><span>${esc(text)}</span></div>`;

function collectButtonHtml(obj) {
  if (isObserved(obj.id)) return collectedHtml("이미 내 세계에 담은 빛입니다");
  const note = obj.distance_km ? `담으면 내 세계 지도에 ${distanceText(obj.distance_km)} 거리로 놓입니다.`
    : obj.group === "constellation" ? "별자리는 여러 거리의 별이 모인 모양이라 지도 대신 알아간 빛 기록에 남깁니다."
    : "거리가 확인되지 않아 지도 대신 알아간 빛 기록에 남깁니다.";
  return `<div class="collect">
    <button type="button" class="save-button" data-collect="1"><span>이 빛을 내 세계에 담기</span><span class="plus" aria-hidden="true">＋</span></button>
    <p class="collect-note">${esc(note)}</p></div>`;
}

function bindCollect(root, obj) {
  root.querySelectorAll("[data-collect]").forEach((b) => b.addEventListener("click", () => {
    state.sky?.observe(obj);                     // 하늘에 떠 있으면 빈 점선 원이 살구색 표식과 이름표로 (이름이 막 나타나는 연출)
    // 알게 되는 순간 — 그 천체가 환하게 켜진다. 자리는 지금 보기(하늘 · 펼치기 · 내 세계)의 카메라로 투영한 화면 좌표.
    // 화면에 없으면 알아간 거리가 바뀌는 리본 쪽에서 (내 세계는 지도에 없는 천체면 '나'의 자리에서 — map.js screenOf)
    const at = stage?.mode?.screenOf?.(obj.id) ?? meterPoint();
    if (at) igniteBurst(at.x, at.y, { reducedMotion: reducedMotion() });
    const d = discover(obj);
    b.closest(".collect").outerHTML = collectedHtml(`내 세계에 새로운 빛으로 담았습니다 · 알아간 빛 ${(d?.count ?? world.visited.length).toLocaleString("ko-KR")}개`);
  }));
}

// 리본의 '내가 지금까지 알아간 거리' 숫자 자리 — 보이지 않으면(내 세계 보기) null
function meterPoint() {
  const r = $("#world-meter .meter-value")?.getBoundingClientRect();
  return r?.width ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : null;
}

// 숫자는 로그 공간에서 1.8초 동안 굴러 올라간다
let meterKm = world.km, meterRaf = 0;
function rollMeter(to) {
  cancelAnimationFrame(meterRaf);
  const from = meterKm;
  if (reducedMotion() || from === to) {
    meterKm = to;
    drawMeter(to);
    return;
  }
  const a = Math.log10(from), b = Math.log10(to), t0 = performance.now();
  const tick = (now) => {
    const t = Math.min(1, (now - t0) / 1800), k = 1 - Math.pow(1 - t, 4);
    meterKm = Math.pow(10, a + (b - a) * k);
    drawMeter(meterKm);
    if (t < 1) meterRaf = requestAnimationFrame(tick);
    else meterKm = to;
  };
  meterRaf = requestAnimationFrame(tick);
}

// 아래 리본의 거리 — 가장 먼 빛까지. 아직 거리를 아는 빛이 없으면 지평선(약 4.7km)에서 시작한다
function drawMeter(km) {
  const m = measure(km), n = world.visited.length.toLocaleString("ko-KR");
  const caption = world.name === "지평선"
    ? `지평선에서 시작하는 중${world.visited.length ? ` · 알아간 빛 ${n}개` : ""}`
    : `${world.name}까지 · 알아간 빛 ${n}개`;
  const el = $("#world-meter");
  el.innerHTML = `<small class="meter-label">내가 지금까지 알아간 거리</small>
    <strong class="meter-value">${esc(m.value)}<span class="meter-unit">${esc(m.unit)}</span></strong>
    <em class="meter-caption">${esc(caption)}</em>`;
  el.title = `${worldScaleLine(km)} · 눌러서 내 세계 보기`;
}

// ── 받은 편지 — 빛의 편지 · 마음 한 줄을 이 기기에 남긴다 (letters.js, localStorage "vh-letters") ─────────────

let letters = loadLetters();

function loadLetters() {
  try { return restoreLetters(localStorage.getItem(LETTERS_KEY)); } catch { return []; }
}

function saveLetters() {
  try { localStorage.setItem(LETTERS_KEY, serializeLetters(letters)); } catch { /* 저장소를 못 쓰면 이번 화면에서만 */ }
  state.map?.setLetters(letterItemIds(letters));       // 내 세계 지도의 ✉ 표식
}

// 받은 편지 하나를 남긴다 — 이미 있으면 그 기록(공유 정보가 채워졌을 수 있다)을 돌려준다
function keepLetter(fields) {
  const entry = makeEntry(fields);
  letters = addLetter(letters, entry);
  saveLetters();
  return letters.find((e) => sameLetter(e, entry)) ?? entry;
}

function keepShare(key, share) {
  letters = setShare(letters, key, share);
  saveLetters();
}

const shareCardUrl = (id) => absoluteUrl(`/api/l/${encodeURIComponent(id)}`);
const shareImageUrl = (id) => absoluteUrl(`/api/l/${encodeURIComponent(id)}.png`);

// 읽어 주기 — 브라우저 음성 합성(ko-KR). 지원하지 않으면 버튼을 내지 않는다
const speech = typeof window.speechSynthesis !== "undefined" && typeof window.SpeechSynthesisUtterance !== "undefined" ? window.speechSynthesis : null;
let speakingButton = null;

function drawSpeakButton(b, on) {
  b.innerHTML = `${icon(on ? "square" : "volume", 15)}<span class="label-text">${on ? "멈추기" : "읽어 주기"}</span>`;
}

function stopSpeaking() {
  if (!speech) return;
  const b = speakingButton;
  speakingButton = null;
  if (b?.isConnected) drawSpeakButton(b, false);
  if (speech.speaking || speech.pending) speech.cancel();
}

function toggleSpeak(text, b) {
  if (speakingButton === b) { stopSpeaking(); return; }
  stopSpeaking();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "ko-KR";
  const voice = speech.getVoices().find((v) => /^ko([-_]|$)/i.test(v.lang));
  if (voice) u.voice = voice;
  u.rate = 0.95;
  const done = () => { if (speakingButton === b) { speakingButton = null; if (b.isConnected) drawSpeakButton(b, false); } };
  u.onend = done;
  u.onerror = done;
  speakingButton = b;
  drawSpeakButton(b, true);
  speech.speak(u);
}

// 결과 아래 버튼 묶음 — 링크 복사 · 카카오톡으로 보내기(키가 있을 때만) · 이미지로 저장 · 읽어 주기. note: 버튼 아래 한 줄 안내
function shareBarHtml({ note = "", shareable = true } = {}) {
  return `<div class="share-bar" data-share-bar>
    <div class="row">${shareable ? btn("링크 복사", { ic: "link", attrs: 'data-act="copy"' })
      + (kakaoAvailable ? btn("카카오톡으로 보내기", { ic: "message-circle", attrs: 'data-act="kakao"' }) : "")
      + btn("이미지로 저장", { ic: "download", attrs: 'data-act="image"' }) : ""}
      ${speech ? `<button type="button" class="btn btn-ghost btn-sm" data-act="speak">${icon("volume", 15)}<span class="label-text">읽어 주기</span></button>` : ""}</div>
    ${note ? `<p class="disclaimer">${esc(note)}</p>` : ""}
    <div class="share-slot" data-share-slot></div></div>`;
}

function shareErrorText(e) {
  const own = e?.message && !/^요청 실패/.test(e.message) ? e.message : null;
  if (e?.status === 404 || e?.code === "share_not_ready") return own ?? "편지를 다시 받은 뒤 공유해 주세요.";
  if (e?.status === 409) return own ?? "이 응답은 공유할 수 없습니다.";
  if (e?.status === 429) return own ?? "공유 요청이 많습니다. 잠시 뒤에 다시 시도해 주세요.";
  return errorText(e);
}

// body: POST /api/share 본문 · share: 이미 있는 공유({ id, url, image_url }) · text: 읽어 줄 글 · keepKey: 보관함 기록의 열쇠
// letter: 카카오톡 피드에 담을 { title, text(본문 — 앞 두 문장을 설명으로) }
function bindShareBar(bar, { body = null, share = null, text = "", keepKey = null, letter = null } = {}) {
  if (!bar) return;
  let current = share;
  let pending = null;
  const slot = bar.querySelector("[data-share-slot]");
  const ensure = () => {
    if (current) return Promise.resolve(current);
    pending ??= api.share(body).then((res) => {
      current = { id: res.id, url: absoluteUrl(res.url), image_url: absoluteUrl(res.image_url ?? `/api/l/${res.id}.png`) };
      if (keepKey) keepShare(keepKey, { id: current.id, url: current.url });
      return current;
    }).finally(() => { pending = null; });
    return pending;
  };
  bar.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    if (b.dataset.act === "speak") { toggleSpeak(text, b); return; }
    if (b.dataset.busy) return;                // disabled 대신 — 누른 버튼에서 키보드 포커스가 빠지지 않게
    b.dataset.busy = "1";
    b.setAttribute("aria-busy", "true");
    slot.innerHTML = "";
    const kakaoReady = b.dataset.act === "kakao" ? loadKakao() : null;   // SDK는 공유 링크를 만드는 동안 함께 불러 둔다
    try {
      const s = await ensure();
      if (!bar.isConnected) return;
      if (b.dataset.act === "copy") await copyLink(s.url, slot);
      else if (kakaoReady) await sendKakao(s, letter ?? { title: "", text }, slot, kakaoReady);
      else saveImage(s);
    } catch (err) {
      if (bar.isConnected) slot.innerHTML = statusHtml(shareErrorText(err), "warn");
    } finally {
      delete b.dataset.busy;
      b.removeAttribute("aria-busy");
    }
  });
}

// 클립보드에 링크를 — 안 되면(권한 · 오래된 브라우저) 선택해 둔 입력창으로 직접 복사하게
async function copyLink(url, slot) {
  try {
    if (!navigator.clipboard?.writeText) throw new Error("clipboard");
    await navigator.clipboard.writeText(url);
    toast("링크를 복사했습니다. 카카오톡에 붙여 넣으면 카드로 보여요");
  } catch {
    slot.innerHTML = `<label class="share-url"><span>이 링크를 길게 눌러 복사해 주세요</span><input type="text" readonly value="${esc(url)}"></label>`;
    const input = slot.querySelector("input");
    input.focus({ preventScroll: true });
    input.select();
  }
}

// 카카오톡 피드 메시지 — SDK를 못 불러오면 링크 복사로 안내하고, 보낸 뒤의 실패 · 취소는 조용히 둔다
async function sendKakao(s, letter, slot, ready = loadKakao()) {
  if (!(await ready)) {
    if (slot.isConnected) slot.innerHTML = statusHtml("카카오톡을 열지 못했습니다. 링크 복사 버튼으로 링크를 복사해 카카오톡에 붙여 넣어 주세요.", "warn");
    return;
  }
  await sendFeed(feedMessage({ title: letter.title, text: letter.text, id: s.id, imageUrl: s.image_url, origin: location.origin }));
}

function saveImage(s) {
  // 화면과 API가 다른 출처면(API_BASE로 분리 배포) download 속성이 무시된다 — 새 탭으로 열어 거기서 저장하게
  let crossOrigin = false;
  try { crossOrigin = !!API_BASE && new URL(s.image_url, location.href).origin !== location.origin; } catch { crossOrigin = false; }
  if (crossOrigin) {
    window.open(s.image_url, "_blank", "noopener");
    toast("새 탭에서 공유 카드 이미지를 열었습니다. 길게 누르거나 오른쪽 클릭으로 저장해 주세요");
    return;
  }
  const a = document.createElement("a");
  a.href = s.image_url;
  a.download = `vasthorizon-${s.id}.png`;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  toast("공유 카드 이미지를 저장합니다");
}

// ── 머리 · 발 ─────────────────────────────────────────────────────────────

const TOOLS = [["explore", "search", "조건 탐색"], ["letter", "mail", "빛의 편지"], ["mind", "moon-star", "마음 한 줄"],
               ["tonight", "orbit", "오늘 밤 하늘"], ["unfold", "telescope", "별자리 펼치기"]];
const STOPS = [{ label: "지평선", sub: "하늘 보기", km: HORIZON_KM }, { label: "태양계", sub: "10¹² m", km: 1e9 },
               { label: "별", sub: "10¹⁷ m", km: 1e14 }, { label: "은하", sub: "10²² m", km: 1e19 },
               { label: "우주의 끝", sub: "10²⁶ m", km: 4.4e23 }];

function renderChrome() {
  app.dataset.mode = state.mode;                // 첫 하늘 · 지평선 길의 표시 여부를 CSS가 정한다
  // 기능 모음 (메뉴 안) — 지금 연 기능은 표시
  $("#launcher").innerHTML = TOOLS.map(([id, ic, label]) =>
    `<button type="button" class="menu-item ${state.drawer === id ? "on" : ""}" data-tool="${id}">${icon(ic, 16)}<span>${label}</span></button>`).join("");
  $("#catalog-btn").classList.toggle("on", state.drawer === "catalog");
  $("#menu-letters").classList.toggle("on", state.drawer === "letters");
  $("#nav-sky").toggleAttribute("aria-current", state.mode === "sky");
  $("#nav-world").toggleAttribute("aria-current", state.mode === "map");

  // 지평선 길 — 금빛은 오늘 바라본 가장 먼 곳까지
  const fill = horizonScale(world.km);
  const active = state.mode === "map" ? Math.max(1, STOPS.reduce((n, s, i) => (horizonScale(s.km) <= fill + 1e-9 ? i : n), 1)) : 0;
  const scale = $("#horizon-scale");
  scale.innerHTML = `
    <div class="scale-rail"><div class="scale-line"></div><div class="scale-fill" style="width:${(fill * 100).toFixed(2)}%"></div>
      ${STOPS.map((s) => { const x = horizonScale(s.km) * 100;
        return `<span class="scale-dot ${x <= fill * 100 + 0.01 ? "on" : ""}" style="left:${x.toFixed(2)}%"></span>`; }).join("")}</div>
    <div class="scale-labels">${STOPS.map((s, i) => { const x = horizonScale(s.km) * 100;
      const cls = i === 0 ? "first" : i === STOPS.length - 1 ? "last" : "";
      return `<button type="button" class="scale-stop ${cls} ${active === i ? "active" : ""}" data-stop="${i}" style="left:${x.toFixed(2)}%">
        <div class="name">${s.label}</div><div class="sub">${s.sub}</div></button>`; }).join("")}</div>
    <div class="scale-note">${state.drawer ? "로그 스케일" : "거리는 로그 스케일 · 출처 Wikidata · 위키백과 · NASA · JPL Horizons · CelesTrak · d3-celestial"}</div>`;

  if (meterKm !== world.km) rollMeter(world.km);
  else drawMeter(world.km);
  renderRibbonCopy();
  renderFirstSky();
  renderWorldHeading();
  renderHint();
  renderWorldCard();
  syncHush();                                   // 요약 카드의 자리가 정해진 뒤에 지도 이름표 숨김 구역을 다시
}

// 살구색 리본 오른쪽 문구 — 알아간 빛이 지구뿐인 사람이 밤늦게(22시~5시) 들어왔으면 마음 한 줄로 이어 준다
const RIBBON_COPY = "아직 모르는 빛은<br>가능성으로 남겨 둡니다.";
function renderRibbonCopy() {
  const el = $(".ribbon-copy");
  const h = new Date().getHours();
  const late = !metBeyondEarth() && (h >= 22 || h < 5);
  if (el.dataset.late === String(late)) return;       // 그대로면 다시 그리지 않는다 (포커스가 버튼에 있을 수 있다)
  el.dataset.late = String(late);
  el.innerHTML = late ? `<button type="button" class="ribbon-mind" data-mind>힘든 하루였다면,<br>한 줄만 적어 보세요</button>` : RIBBON_COPY;
}

// 내 세계 지도의 머리글 — 오늘 새로 알아간 빛 · 두 줄 제목 · 범례 (design-proposal .collect-heading · .map-legend)
function renderWorldHeading() {
  const el = $("#world-heading");
  const shown = state.mode === "map" && !state.scene;
  el.classList.toggle("away", !shown);
  $("#world-foot").classList.toggle("away", !shown);
  el.inert = !shown;
  if (!shown) return;
  headingDay = localDate();
  if (!midnightTimer) scheduleHeadingDay();
  const h = worldHeading(world.visited, headingDay);
  $("#world-kicker").textContent = h.kicker;
  $("#world-title").innerHTML = `${esc(h.lines[0])}<br><em>${esc(h.lines[1])}</em>`;
  $("#map-legend").innerHTML = `<li>${markHtml(true)}<span>${esc(h.known)}</span></li><li>${markHtml(false)}<span>${esc(h.unknown)}</span></li>`;
}

// 자정이 지나면 '오늘 새로 알아간 빛'이 어제 것을 세지 않게 — 자정 타이머와 탭이 다시 보일 때(잠든 탭은 타이머가 늦다) 날짜를 본다
let headingDay = null;
let midnightTimer = null;
function scheduleHeadingDay() {
  clearTimeout(midnightTimer);
  const now = new Date();
  const next = new Date(now);
  next.setHours(24, 0, 1, 0);                  // 다음 날 0시 0분 1초
  midnightTimer = setTimeout(checkHeadingDay, next - now);
}
function checkHeadingDay() {
  scheduleHeadingDay();
  if (headingDay !== null && headingDay !== localDate()) renderWorldHeading();
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) checkHeadingDay(); });

// 첫 하늘 — 하늘 보기에서 서랍 · 장면이 닫혀 있을 때만. 이미 알아간 빛이 있으면 다음 빛을 권한다
function renderFirstSky() {
  const el = $("#first-sky");
  const shown = state.mode === "sky" && !state.drawer && !state.scene;
  el.classList.toggle("away", !shown);
  el.inert = !shown;
  app.classList.toggle("first-sky-on", shown);
  syncHush();
  const met = metBeyondEarth();
  $("#first-sky-title").innerHTML = met ? "오늘은 어떤 빛을<br><em>알아가 볼까요?</em>"
    : "당신이 아직<br>만나지 못한 빛이<br><em>이토록 많아요.</em>";
  $("#first-light").innerHTML = `<span>${met ? "다음 빛 만나기" : "첫 번째 빛 만나기"}</span>${icon("arrow-up-right", 20)}`;
}

// 하늘 이름표를 숨길 구역 — 첫 하늘 문장 뒤의 별자리 이름, 워드마크 · 상단 탐색 둘레의 모든 이름표 (sky.js applyHush)
function syncHush() {
  if (!state.sky || !stage) return;
  const box = stage.container.getBoundingClientRect();
  const zone = (el, pad, only) => {
    const r = el.getBoundingClientRect();
    return r.width ? { x0: r.left - box.left - pad, y0: r.top - box.top - pad, x1: r.right - box.left + pad, y1: r.bottom - box.top + pad, only } : null;
  };
  state.sky.hushZones = [app.classList.contains("first-sky-on") ? zone($("#first-sky"), 28, "constellation") : null,
                         zone($(".wordmark"), 16), zone($(".chrome-top-right"), 16)].filter(Boolean);
  // 내 세계 지도 — 머리글 · 요약 카드 · 바닥 문구 뒤의 거리 고리 이름 (map.js applyHush)
  if (state.map) state.map.nameZones = state.mode !== "map" ? [] : [zone($("#world-card"), 6)].filter(Boolean);
  if (state.map) state.map.hushZones = state.mode !== "map" ? [] : [zone($(".world-title"), 12), zone($("#map-legend"), 12), zone($("#world-card"), 12),
    zone($("#world-foot"), 10), zone($(".wordmark"), 16), zone($(".chrome-top-right"), 16)].filter(Boolean);
}

// 프롤로그가 끝나고 크롬이 나타날 때 — 첫 하늘 문장이 350ms 동안 떠오른다
function arriveFirstSky() {
  const el = $("#first-sky");
  syncHush();
  el.classList.remove("arrive");
  void el.offsetWidth;
  el.classList.add("arrive");
}

// 첫 번째 빛 만나기 — 지금 이 하늘에 떠 있는 밝은 천체 중 아직 알아가지 않은 것 하나의 서랍을 연다.
// 고르는 규칙은 skydata.pickFirstLight (지평선 위 15도 이상 · 태양 제외 · 겉보기 등급이 밝은 순)
function meetFirstLight() {
  if (!state.sky) return;
  if (state.mode !== "sky") setMode("sky");
  const pick = pickFirstLight(state.sky.brightCandidates(), isObserved);
  if (!pick) {
    showCatalog();
    toast("지금 하늘에 새로 만날 밝은 빛이 없어 천체 목록을 열었습니다");
    return;
  }
  state.sky.lookAt(pick.id);
  showSelection({ id: pick.id, name: pick.name });          // 서랍이 열리기 전에 바로 표시
  selectItem(pick.id, { fly: false });
}

// 내 세계 요약 카드 — 종이색 각진 카드. 나의 가장 먼 빛(큰 숫자) → 그 천체 이름 → 한 문단 → 다른 빛 만나러 가기.
// 크기 비교 · 알아간 빛 기록 · 기록 지우기 · 우주 끝까지 떠나 보기는 카드 아래 접힘으로 (design-proposal .world-note)
function renderWorldCard() {
  const el = $("#world-card");
  if (!el) return;
  el.hidden = state.mode !== "map" || !!state.scene;
  if (el.hidden) { fitMapView(); return; }
  const open = new Set([...el.querySelectorAll("details[open]")].map((d) => d.dataset.k));   // 다시 그려도 펼친 곳은 그대로
  if (renderWorldCard.openLog) { open.add("log"); renderWorldCard.openLog = false; }
  const byId = new Map(mapPoints().map((p) => [p.id, p]));
  const groupOf = (v) => v.group ?? byId.get(v.id)?.group ?? (v.id.startsWith("hip:") ? "star" : null);
  const visited = world.visited;
  const { unknown } = knownAndUnknown(mapPoints(), new Set(visited.map((v) => v.id)), world.km);
  const facts = analogies(world.km);
  const n = (x) => x.toLocaleString("ko-KR");
  const far = farthestParts(world.km);
  const copy = visited.length
    ? `알아간 빛 ${n(visited.length)}개가 내 세계에 남아 있어요. 아직 닿지 않은 점들도 언제든 만나볼 수 있습니다.`
    : "아직 알아간 빛이 없어요. 하늘에서 빛 하나를 만나 담으면 이 지도에 살구색 표식이 켜집니다.";
  el.innerHTML = `<p class="wc-kicker">나의 가장 먼 빛</p>
    <p class="wc-far"><span class="wc-far-value">${esc(far.value)}</span><span class="wc-far-unit">${esc(far.unit)}</span></p>
    <hr class="wc-rule">
    <p class="wc-name">${esc(world.name)}</p>
    <p class="wc-copy">${esc(copy)}</p>
    <button type="button" class="wc-link" id="wc-meet">${visited.length ? "다른 빛 만나러 가기" : "첫 번째 빛 만나러 가기"} <span aria-hidden="true">↗</span></button>
    <div class="wc-extra">
    <details class="wc-more" data-k="compare" ${open.has("compare") ? "open" : ""}><summary>크기 비교 더 보기</summary>
      ${facts.map((f) => `<div class="wc-row"><span>${esc(f.label)}</span><b>${esc(f.value)}</b></div>${f.note ? `<div class="wc-note">${esc(f.note)}</div>` : ""}`).join("")}
      <div class="wc-row"><span>그 거리 안 아직 알아가지 않은 천체</span><b>${n(unknown.length)}개</b></div>
      <div class="wc-note">앞으로 알아갈 가능성입니다</div>
      <div class="wc-src">기준 · 지구 지름 12,742km(위키백과 「지구」) · 빛의 속도 299,792km/s</div></details>
    <details class="wc-more" data-k="log" ${open.has("log") ? "open" : ""}><summary>알아간 빛 기록 (${n(visited.length)})</summary>
      ${visited.length ? `<ol class="wc-log">${recent(visited).map((v) => `<li><button type="button" data-open="${esc(v.id)}">${markHtml(true)}${esc(v.name)}</button>
        <span>${v.id === EARTH_ID ? "내가 있는 곳" : v.km ? esc(distanceText(v.km)) : groupOf(v) === "constellation" ? "별자리" : "거리 미확인"} · ${esc(v.at.slice(5).replace("-", "."))}</span></li>`).join("")}</ol>
        <button type="button" class="wc-reset" id="wc-reset">기록 처음부터 다시 시작</button>` : `<div class="wc-note">아직 기록이 없습니다</div>`}</details>
    <button type="button" class="wc-journey" id="wc-journey">${icon("sparkles", 14)}<span>우주 끝까지 떠나 보기</span></button></div>`;
  el.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => {
    const v = world.visited.find((x) => x.id === b.dataset.open);
    if (v?.km) state.map?.select(v.id);
    selectItem(b.dataset.open, { fly: false });
  }));
  $("#wc-meet").addEventListener("click", meetFirstLight);       // 하늘로 돌아가 아직 만나지 않은 밝은 빛 하나를 연다
  fitMapView();
  $("#wc-journey").addEventListener("click", startJourney);
  $("#wc-reset")?.addEventListener("click", (e) => {
    if (e.currentTarget.dataset.armed) { resetWorld(); return; }    // 한 번 더 눌러야 지운다
    e.currentTarget.dataset.armed = "1";
    e.currentTarget.textContent = "정말 지울까요? 한 번 더 누르면 모든 기록을 지웁니다";
  });
}

// 좁은 화면 — 요약 카드가 지도 아래쪽을 덮으므로 '나'를 카드 위로 올린다 (카드 높이의 45%만큼 시야를 위로)
function fitMapView() {
  const card = $("#world-card");
  const lift = state.mode === "map" && !card.hidden && !state.drawer && window.innerWidth <= 650 ? Math.round(card.offsetHeight * 0.45) : 0;
  stage?.setInsetY(lift);
}

function renderHint() {
  const hint = $("#stage-hint");
  if (state.mode === "map") hint.textContent = "";      // 내 세계 지도는 범례(#map-legend)와 바닥 문구(#world-foot)가 안내한다
  else if (state.mode === "unfold") hint.textContent = `지구에서 본 ${state.unfold?.con.name ?? "별자리"} · '펼치기'를 누르면 별들이 실제 거리로 이동합니다`;
  else if (state.daytime) hint.textContent = "지금은 해가 떠 있어 별이 보이지 않습니다 · 오늘 밤 하늘에서 시각을 바꿔 보세요";
  else hint.textContent = world.visited.length ? "아무 별이나 눌러 알아보세요 · 점선 원은 아직 만나지 않은 빛 · 휠로 확대하면 더 어두운 별까지"
    : "하늘의 빛을 눌러 살펴보세요 · 휠로 확대하면 더 어두운 별까지";
}

let toastTimer;
function toast(html) {
  const el = $("#toast");
  el.innerHTML = html;
  el.hidden = false;
  el.style.animation = "none";
  void el.offsetWidth;
  el.style.animation = "";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4200);
}

// 4초 동안 움직임이 없으면 크롬을 흐리게 — 서랍 · 장면이 열려 있으면 그대로
let idleTimer;
function wake() {
  $("#chrome").classList.remove("idle");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    if (!state.drawer && !state.scene) $("#chrome").classList.add("idle");
  }, 4000);
}

// ── 장면 — 처음 · 떠오르기의 끝 ──────────────────────────────────────────

function showScene(kind, html) {
  state.scene = kind;
  const el = $("#scene");
  el.className = `scene ${kind}`;
  el.innerHTML = html;
  el.hidden = false;
  $("#chrome").hidden = true;
  $("#world-card").hidden = true;
}

function closeScene() {
  state.scene = null;
  $("#scene").hidden = true;
  $("#chrome").hidden = false;
  renderFirstSky();
  wake();
}

// 프롤로그 — 처음 켰을 때 한 번 (다시 보기 · ?prologue=1 로 언제든). 끝나면 첫 하늘로
function startPrologue() {
  $("#chrome").hidden = true;
  sound.ambient("prologue");
  // 구 장면에서 지구를 담는다 (이미 담겼으면 빛무리만). 건너뛰었으면 끝날 때 조용히
  playPrologue({ reducedMotion: reducedMotion(), onEarth: ensureEarth })
    .then((r) => {
      ensureEarth();
      $("#chrome").hidden = false;
      sound.arrive();                                      // 첫 하늘에 도착하는 화음, 그 뒤로 지금 화면의 배경음
      sound.ambient(ambientOf(state.mode));
      if (r?.next === "mind") { showPerspective(); wake(); return; }   // 마지막 장면의 '마음 한 줄 먼저 남기기'
      arriveFirstSky();
      wake();
    });
}

function prologueWanted(params) {
  if (params.get("prologue") === "1") return true;
  if (params.get("prologue") === "0" || params.has("mode")) return false;
  try { return !localStorage.getItem(PROLOGUE_KEY); } catch { return true; }
}

// 우주 끝까지 떠나 보기 — 땅 위의 나에서 관측 가능한 우주의 끝까지 (긴 연출, 고를 때만)
function startJourney() {
  closeScene();
  closeDrawer();
  markJourneySeen();
  setMode("map", null, { journey: true });
}

const JOURNEY_KEY = "vh-journey-seen";
function journeySeen() { try { return !!localStorage.getItem(JOURNEY_KEY); } catch { return true; } }
function markJourneySeen() { try { localStorage.setItem(JOURNEY_KEY, "1"); } catch { /* 무시 */ } }

// 내 세계 보기 — 처음 한 번만 우주 끝까지 떠오르고, 그 뒤에는 바로 지도로 (마지막에 보던 자리 · 알아간 천체가 한눈에)
// focus: 그 천체로 · log: 기록 펼치기 · km: 거리 눈금(그 거리가 보이는 자리로)
function openWorld({ focus = null, log = false, km = null } = {}) {
  if (!journeySeen() && !focus && !log && km == null) { startJourney(); return; }
  closeScene();
  closeDrawer();
  if (log) renderWorldCard.openLog = true;
  if (state.mode !== "map") setMode("map", null, { keepView: true });   // 마지막에 보던 자리 그대로
  else renderChrome();
  if (focus) state.map.select(focus);
  else if (km != null) state.map.viewDistance(km);
}

function journeyEnd() {
  const seen = world.visited.length, today = todayCount();
  showScene("end", `<div class="scene-col">
    <div class="serif-line st0">지금 당신의 세상은</div>
    <div class="end-measure st1">${measureHtml(world.km, { size: "xl", center: true })}</div>
    <div class="serif-line st2">${seen ? `${seen.toLocaleString("ko-KR")}개의 빛을 알아가, ${world.name === "지평선" ? "기록에 담았습니다" : `${esc(world.name)}까지 닿았습니다`}` : "첫 번째 빛을 기다리고 있습니다"}</div>
    <p class="muted st3">${today ? `오늘 새로운 빛 ${today}개를 알아갔습니다 · ` : ""}가장 바깥의 분홍빛 고리는 관측 가능한 우주의 끝, 반지름 약 465억 광년.
      그 구의 중심에는 언제나 <em class="kw sky">바라보는 당신</em>이 있습니다.</p>
    <div class="actions st4">${btn(seen ? "다음 빛 알아가러 하늘로" : "첫 번째 빛 만나러 하늘로", { variant: "primary", size: "md", ic: "sparkles", id: "end-sky" })}
      ${btn("이 우주 둘러보기", { variant: "ghost", size: "md", id: "end-stay" })}</div>
    <div class="src st4">출처: <a href="${esc(state.mapData?.observable_universe_source ?? "")}" target="_blank" rel="noopener">위키백과 「관측 가능한 우주」</a></div></div>`);
  $("#end-sky").addEventListener("click", () => { closeScene(); setMode("sky"); });
  $("#end-stay").addEventListener("click", closeScene);
  state.map?.recenterForEnd();
}

// ── 서랍: 천체 ────────────────────────────────────────────────────────────

const ATTR_LIMIT = 12;
const ATTR_LABELS = { "서울에서_관측": "서울에서 관측" };     // 저장 키(밑줄) → 화면 이름

// 거리를 확인할 수 없는 별 — 거리는 지어내지 않는다. 화면 데이터(등급 · 색)를 보여 주고, 지도 대신 알아간 빛 기록에는 남길 수 있다
function unknownStar(id, hint) {
  const name = `HIP ${id.slice(4)}`;
  return { id, name, distance_km: null, group: "star", ra_deg: hint?.ra ?? null, dec_deg: hint?.dec ?? null };
}

function unknownStarHtml(id, hint) {
  const hip = id.slice(4);
  const facts = hint?.mag != null ? `<p class="muted">겉보기 등급 ${hint.mag.toFixed(1)} · ${colorWord(hint.bv)} 별 (d3-celestial)</p>` : "";
  return `<div class="head"><div class="eyebrow">별 · <span class="code">HIP ${esc(hip)}</span></div><h2 class="name">HIP ${esc(hip)}</h2></div>
    ${facts}
    <p class="status">Wikidata에 이 별의 거리가 없어 지도에는 놓지 않습니다. 거리를 모르는 별의 거리는 지어내지 않습니다.</p>
    <div id="collect-slot">${collectButtonHtml(unknownStar(id, hint))}</div>
    <a class="btn btn-ghost btn-sm" href="https://www.wikidata.org/w/index.php?search=${encodeURIComponent(`HIP ${hip}`)}" target="_blank" rel="noopener">Wikidata에서 찾아보기</a>`;
}

// hint: 하늘에서 누른 별의 화면 데이터 (hip · 등급 · 색지수) — 거리를 확인할 수 없는 별의 안내에 쓴다
async function selectItem(id, { fly = true, hint = null } = {}) {
  enterView({ kind: "item", id, _hint: hint });
  const alive = claimPanel();
  let item;
  const star = id.startsWith("hip:");
  if (star) openDrawer("item", statusHtml("이 별의 정보를 Wikidata에서 찾는 중…"));   // 처음 누른 별은 1~2초
  try {
    item = await api.item(id);
  } catch (e) {
    if (!alive()) return;
    if (star && e.code === "item_not_found") {
      openDrawer("item", unknownStarHtml(id, hint));
      bindCollect($("#collect-slot"), unknownStar(id, hint));
    }
    else openDrawer("item", `<p class="status err">${esc(errorText(e))}</p>`);
    return;
  }
  if (!alive()) return;              // 그사이 다른 항목 · 기능을 골랐다 — 항목 · 카메라 · 기록 모두 건드리지 않는다
  state.item = item;
  showSelection({ id: item.id, name: item.name, ra_deg: item.ra_deg, dec_deg: item.dec_deg });
  if (fly && state.mode === "map") state.map?.select(id);
  if (fly && state.mode === "sky") state.sky?.lookAt(id);

  const a = item.attrs;
  const code = a["메시에 번호"] ?? a["약어"] ?? a["바이어 명칭"] ?? a["COSPAR ID"] ?? (item.attrs["별자리"] && item.id.startsWith("hip:") ? item.attrs["별자리"] : "");
  const surface = item.distance?.reference === "지표면 위 궤도 고도";
  const departs = (item.group === "star" || item.group === "messier") && item.distance_km ? departureLabel(item.distance_km, state.refYear) : null;
  // 서울에서_관측(참거짓)은 "서울에서 관측"으로 보인다 — 별자리처럼 같은 이름의 문구 속성이 있으면 문구만
  const attrs = Object.entries(a).filter(([k, v]) => v !== null && v !== "" && !/horizons_id/.test(k) && !(k === "서울에서_관측" && a["서울에서 관측"]))
    .map(([k, v]) => [ATTR_LABELS[k] ?? k, v]).slice(0, ATTR_LIMIT);
  const isCon = item.group === "constellation";
  const suggestions = departs ? [`${item.name}의 빛은 언제 출발했나요?`, "맨눈으로 볼 수 있나요?"]
    : isCon ? [`${item.name}에서 가장 밝은 별은 무엇인가요?`, "언제 잘 보이나요?"]
    : [`${item.name}은(는) 지금 어디에 있나요?`, "어떤 일을 했나요?"];

  // 읽기 카드의 첫 단 — 그룹 → 이름 → 지정 번호 · 종류 · 거리 → 핵심 사실 한 문장(항목 메타데이터, facts.js) → 짧은 설명 → 출처 → 담기
  const fact = heroFact(item, { figure: isCon ? state.constellations.find((c) => c.item_id === item.id) : null, refYear: state.refYear });
  const note = placeNote(item);                // 지구에만 — 지금 서 있는 곳에서 고개를 들면 (facts.js)
  const meta = [code, item.kind, item.distance_km ? `${surface ? "지표면 위 " : ""}${distanceText(item.distance_km)}` : null].filter(Boolean);
  const source = item.sources?.[0];
  openDrawer("item", `
    <div class="head reveal" style="animation-delay:0ms">
      <div class="eyebrow">${esc(item.group_ko)}</div>
      <h2 class="name card-name">${esc(item.name)}</h2>
      ${meta.length ? `<div class="card-meta">${meta.map((m) => `<span>${esc(m)}</span>`).join('<i aria-hidden="true">·</i>')}</div>` : ""}</div>
    ${fact ? `<div class="reveal" style="animation-delay:150ms"><p class="hero-fact">${esc(fact.before)}<em>${esc(fact.em)}</em>${esc(fact.after)}</p>
      ${fact.detail ? `<p class="fact-detail">${esc(fact.detail)}</p>` : ""}</div>` : ""}
    ${note ? `<div class="reveal place-note" style="animation-delay:220ms"><p class="fact-detail">${esc(note.text)}</p>
      <p class="disclaimer">근거 · <a href="${esc(note.source.url)}" target="_blank" rel="noopener">${esc(note.source.name)}</a></p></div>` : ""}
    <div class="evidence-line reveal" style="animation-delay:300ms"><span>근거 있는 이야기 · 항목 메타데이터</span>
      ${source ? `<a href="${esc(source.url)}" target="_blank" rel="noopener">${esc(source.name)} ↗</a>` : ""}</div>
    <div class="reveal" id="collect-slot" style="animation-delay:420ms">${collectButtonHtml(item)}</div>
    <button type="button" class="ask-hint reveal" id="ask-hint" style="animation-delay:480ms">궁금한 것을 물어보세요 ${icon("arrow-up-right", 13)}</button>
    <div class="more-read reveal" style="animation-delay:540ms">
      <div class="intro-clip" id="intro-clip"><div class="stack lg intro" id="intro">${statusHtml("이 천체의 이야기를 불러오는 중…")}</div></div>
      <button type="button" class="disclosure" id="intro-btn" aria-expanded="false" aria-controls="intro-clip" hidden><span class="eyebrow">더 읽기</span>${icon("chevron-down", 14)}</button>
      <div id="intro-source"></div></div>
    <div class="reveal" id="photo" style="animation-delay:600ms"></div>
    <div class="reveal" id="bodyview" style="animation-delay:600ms"></div>
    <div class="reveal" id="blackhole" style="animation-delay:620ms"></div>
    ${departs ? `<div class="card emphasis letter-card reveal" style="animation-delay:660ms">
      <div class="letter-head">${icon("mail", 14)}빛의 편지</div>
      <div class="letter-body">지금 보이는 이 빛은 <em class="kw">${esc(departs)}</em>에 출발해, 오늘 당신의 눈에 닿아 여정을 마쳤습니다.</div>
      <div class="letter-note">카탈로그 거리(${esc(distanceText(item.distance_km))})로 계산한 출발 시점입니다.</div>
      <div class="row">${btn("그 해 지구의 기록 보기", { variant: "ghost", icRight: "arrow-right", id: "act-letter", attrs: 'style="padding-left:0"' })}</div></div>` : ""}
    <div class="stack reveal" style="animation-delay:720ms">
      <button type="button" class="disclosure" id="more-btn" aria-expanded="false"><span class="eyebrow">자세한 정보</span>${icon("chevron-down", 14)}</button>
      <div id="more" hidden>
        <dl class="attrs">${attrs.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(typeof v === "boolean" ? (v ? "예" : "아니오") : v)}</dd>`).join("")}</dl>
        <p class="disclaimer" style="margin-top:10px">출처 · ${item.sources.map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a>`).join(" · ")}</p>
      </div>
      <div class="row">
        ${isCon ? btn("펼쳐 보기", { ic: "telescope", id: "act-unfold" }) + btn("하늘에서 찾기", { variant: "ghost", ic: "sparkles", id: "act-find" }) : ""}
        ${!departs && item.distance_km && !surface ? btn("빛의 편지", { ic: "mail", id: "act-letter2" }) : ""}
        ${item.wiki_title ? `<a class="btn btn-ghost btn-sm" href="https://ko.wikipedia.org/wiki/${encodeURIComponent(item.wiki_title)}" target="_blank" rel="noopener">위키백과${icon("arrow-up-right", 15)}</a>` : ""}
      </div></div>
    <div class="rule"></div>
    <div class="stack lg reveal" style="animation-delay:1080ms">
      <div class="eyebrow">${esc(item.name)}에게 물어보기</div>
      <div class="chips" id="suggest">${suggestions.map((q) => `<button type="button" class="chip sm" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>
      <div class="chat-log" id="chat-log"></div>
      <div class="row" id="clear-row" hidden>${btn("대화 지우기", { variant: "ghost", id: "clear-chat" })}<span id="clear-status"></span></div></div>
    <div class="spacer"></div>
    <div class="composer-wrap">${composerHtml("chat-form", { placeholder: `${item.name}에 대해 물어보세요` })}
      <div class="composer-note">문서로 확인되지 않은 내용은 확인되지 않는다고 답합니다.</div></div>`);

  $("#more-btn").addEventListener("click", (e) => {
    const more = $("#more");
    more.hidden = !more.hidden;
    e.currentTarget.setAttribute("aria-expanded", String(!more.hidden));
    e.currentTarget.lastElementChild.outerHTML = icon(more.hidden ? "chevron-down" : "chevron-up", 14);
  });
  $("#ask-hint").addEventListener("click", () => $("#chat-form input")?.focus());
  $("#act-letter")?.addEventListener("click", () => showLetter({ item_id: item.id }));
  $("#act-letter2")?.addEventListener("click", () => showLetter({ item_id: item.id }));
  $("#act-unfold")?.addEventListener("click", () => setMode("unfold", item.id));
  $("#act-find")?.addEventListener("click", () => { setMode("sky"); state.sky.lookAt(item.id); });
  const composer = bindComposer($("#chat-form"), (q, input) => { input.value = ""; ask(item, q, composer, alive); });
  // 추천 질문도 입력창과 같은 규칙 — 답하는 중에는 새 질문을 받지 않는다
  $("#suggest").querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => {
    if (!$("#chat-form").dataset.busy) ask(item, b.dataset.q, composer, alive);
  }));
  const historyGate = requestGate();
  const clear = clearHistoryFlow({
    request: () => api.clearHistory(item.id), historyGate, alive,
    onBusy: (b) => { $("#clear-chat").disabled = b; if (b) $("#clear-status").innerHTML = ""; },
    onCleared: () => {
      $("#chat-log").innerHTML = "";
      $("#suggest").hidden = false;
      $("#clear-row").hidden = true;
    },
    onFailed: (e) => {        // 서버 기록은 남아 있다 — 화면 기록도 그대로 두고 다시 시도할 수 있게
      $("#clear-status").innerHTML = statusHtml(`대화 기록을 지우지 못했습니다 — ${errorText(e)} 다시 눌러 주세요.`, "err");
    },
  });
  $("#clear-chat").addEventListener("click", clear);
  bindCollect($("#collect-slot"), item);
  loadIntro(item, alive);
  loadPhoto(item, alive);
  loadBlackHole(item, alive);
  showBodyView(item);
  state.historyLoaded = loadHistory(item, alive, historyGate);   // 넘어온 질문은 기록을 다 그린 뒤에 보낸다
}

// 천체의 이야기 — 자체 위키 문서 첫머리 · 역사 절 발췌 (LLM 없음). 출처 · 이용 조건을 함께
// 은하 중심 블랙홀 — 근거(위키 문서 문장 · Wikidata)가 있는 은하에만. 모습은 빛의 경로를 계산한 상상도 (blackhole.js)
async function loadBlackHole(item, alive) {
  const data = await loadBlackHoles();
  const bh = data.galaxies.find((g) => g.id === item.id);
  const box = $("#blackhole");
  if (!bh || !alive() || !box || state.item?.id !== item.id) return;
  const src = [bh.doc && `<a href="${esc(bh.doc.permalink ?? bh.doc.url)}" target="_blank" rel="noopener">위키백과 「${esc(bh.doc.title)}」</a>`,
               bh.wikidata && `<a href="${esc(bh.wikidata.url)}" target="_blank" rel="noopener">Wikidata ${esc(bh.wikidata.qid)}</a>`].filter(Boolean).join(" · ");
  box.innerHTML = `<figure class="bh-card">
    <canvas class="bh-canvas" aria-label="${esc(bh.black_hole ?? "중심 블랙홀")} 상상도 — 블랙홀 둘레에서 휘는 빛을 계산한 그림"></canvas>
    <figcaption>
      <div class="eyebrow">중심 블랙홀${bh.black_hole ? ` · <span class="code">${esc(bh.black_hole)}</span>` : ""}</div>
      ${bh.quote ? `<blockquote>${esc(bh.quote)}</blockquote>` : `<p>Wikidata에 이 은하의 일부인 블랙홀로 기록되어 있습니다.</p>`}
      <p class="disclaimer">${esc(data.note)} 빛이 블랙홀 둘레에서 휘는 경로를 계산해, 원반 뒤쪽이 그림자 위아래로 보이는 모습(영화 「인터스텔라」의 가르강튀아와 같은 원리)을 그렸습니다. 출처 · ${src}</p>
    </figcaption></figure>`;
  stopDrawerView();
  drawerView = mountBlackHole(box.querySelector("canvas"), { still: reducedMotion() });
}

// 태양계 천체를 가까이서 본 모습 — 태양 쪽 빛을 받으며 천천히 돈다 (bodyview.js). 표면은 알려진 특징을 바탕으로 한 상상도
function showBodyView(item) {
  const info = bodyInfo(item.id);
  const box = $("#bodyview");
  if (!info || !box) return;
  const note = info.key === "moon" ? "달 표면은 NASA 과학시각화 스튜디오 CGI Moon Kit(LRO 색 지도)입니다."
    : `표면은 알려진 특징을 바탕으로 한 상상도입니다.${info.key === "earth" ? " 대륙과 구름의 모양은 실제 지도가 아닙니다." : ""}`;
  box.innerHTML = `<figure class="body-card">
    <canvas class="body-canvas" aria-label="${esc(item.name)}을(를) 가까이서 본 모습 — 상상도"></canvas>
    <figcaption>
      <div class="eyebrow">가까이서 본 모습</div>
      <p class="body-size">${esc(sizeCaption(info))}</p>
      <p class="disclaimer">${esc(note)} 크기 출처 · NASA · 위키백과 공개 값</p>
    </figcaption></figure>`;
  stopDrawerView();
  drawerView = mountBodyView(box.querySelector("canvas"), item.id, { still: reducedMotion() });
}

// 메시에 천체 사진 — NASA 'Hubble's Messier Catalog'의 대표 사진과 출처 표기 (web/data/messier, 없으면 비워 둔다)
async function loadPhoto(item, alive) {
  const code = item.attrs?.["메시에 번호"];
  if (!code) return;
  const credits = await messierCredits();
  const c = credits?.[code];
  if (!c || !alive()) return;
  const box = $("#photo");
  if (!box || state.item?.id !== item.id) return;
  box.innerHTML = `<figure class="photo"><img src="data/messier/${esc(code)}.jpg" alt="${esc(item.name)} 사진" loading="lazy">
    <figcaption class="disclaimer">사진 · ${esc(c.credit)} · <a href="${esc(c.page)}" target="_blank" rel="noopener">NASA Hubble's Messier Catalog</a></figcaption></figure>`;
}

let creditsPromise;
function messierCredits() {
  creditsPromise ??= fetch("data/messier/credits.json").then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  return creditsPromise;
}

async function loadIntro(item, alive) {
  let r;
  try {
    r = await api.intro(item.id);
  } catch (e) {
    r = { status: "unavailable", sections: [], notice: errorText(e) };
  }
  if (!alive()) return;
  const box = $("#intro");
  if (!box) return;
  if (!r.sections.length) {          // 이야기가 없으면 안내만 — 더 읽기 버튼은 숨긴 그대로
    box.innerHTML = r.notice ? `<p class="disclaimer">${esc(r.notice)}</p>` : "";
    return;
  }
  box.innerHTML = r.sections.map((x) => `<div class="story"><div class="eyebrow">${esc(x.heading)}</div><p class="story-text">${esc(x.text)}</p></div>`).join("");
  // 출처는 미리보기 밖에 둔다 — 접힌 본문 중간에서 잘려 보이지 않게, 접든 펴든 늘 보인다
  $("#intro-source").innerHTML = `<p class="disclaimer">출처 · <a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.source_type)} 「${esc(r.title)}」</a> · ${esc(r.license)} — 문서 첫머리를 그대로 옮겼습니다.</p>`;
  bindIntroPreview($("#intro-clip"), box, $("#intro-btn"));
}

// 이야기 미리보기 — 앞부분만 보이다가 '더 읽기'로 전체를, '접기'로 다시 미리보기로. 잘리지 않을 만큼 짧으면 버튼 · 페이드 없이 전부 보인다
function bindIntroPreview(clip, box, btn) {
  clip.classList.add("clipped");
  if (box.scrollHeight <= clip.clientHeight + 1) { clip.classList.remove("clipped"); return; }
  btn.hidden = false;
  const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  clip.addEventListener("transitionend", (e) => {
    if (e.propertyName === "max-height" && clip.classList.contains("open")) clip.style.maxHeight = "none";   // 다 펼친 뒤에는 높이를 풀어 창 크기가 바뀌어도 잘리지 않게
  });
  btn.addEventListener("click", () => {
    const open = !clip.classList.contains("open");
    if (open) {
      clip.classList.add("open");
      clip.style.maxHeight = still() ? "none" : `${box.scrollHeight}px`;
    } else {
      clip.style.maxHeight = `${box.scrollHeight}px`;   // none → 실제 높이로 고정한 뒤 미리보기 높이로 줄여야 전환이 보인다
      void clip.offsetHeight;
      clip.classList.remove("open");
      clip.style.maxHeight = "";
    }
    btn.setAttribute("aria-expanded", String(open));
    btn.firstElementChild.textContent = open ? "접기" : "더 읽기";
    btn.lastElementChild.outerHTML = icon(open ? "chevron-up" : "chevron-down", 14);
  });
}

let turnSeq = 0;
function appendTurn(question) {
  const log = $("#chat-log");
  if (!log) return null;
  $("#suggest").hidden = true;
  $("#clear-row").hidden = false;
  const el = document.createElement("div");
  el.className = "chat-log";
  el.innerHTML = `<div class="bubble">${esc(question)}</div><div class="turn-answer"></div>`;
  log.appendChild(el);
  return el.querySelector(".turn-answer");
}

async function loadHistory(item, alive, gate) {
  const isLatest = gate.start();      // 조회 중에 대화를 지우면 이 응답은 버린다 — 지운 기록이 되살아나지 않게
  const hist = await api.history(item.id).catch(() => null);
  if (!alive() || !isLatest() || !hist) return;
  // 기록은 질문(user) · 답변(assistant) 차례로 온다
  let question = null;
  for (const t of hist.turns ?? []) {
    if (t.role === "user") { question = t.content; continue; }
    const out = appendTurn(question ?? "");
    if (out) out.innerHTML = resultHtml(t.content, t.cited, `h${++turnSeq}`);
    question = null;
  }
}

// 진행 상태 — 서버가 보내는 단계 메시지를 차례로 쌓고, 지난 단계는 완료(초록)로
function progressSteps(out) {
  const steps = [];
  const draw = () => {
    if (!out.isConnected) return;
    out.innerHTML = `<div class="steps">${steps.map((s, i) => statusHtml(s, i < steps.length - 1 ? "ok" : "progress")).join("")}</div>`;
  };
  return (msg) => { if (steps[steps.length - 1] !== msg) { steps.push(msg); draw(); } };
}

async function ask(item, question, composer, alive) {
  const out = appendTurn(question);
  if (!out) return;
  const step = progressSteps(out);
  step("질문을 확인하는 중…");
  out.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "end" });
  composer.setBusy(true);
  try {
    const res = await askStream(item.id, question, step);
    if (!out.isConnected || !alive()) return;  // 답하는 동안 다른 서랍으로 갔다 — 답변은 서버 대화 기록에 남는다
    const notes = [...res.warnings, ...(res.recorded === false ? ["이 답변은 대화 기록에 남지 않았습니다."] : [])];
    out.innerHTML = resultHtml(res.answer, res.cited, `t${++turnSeq}`, res.notice, notes);
    sound.sparkle();                           // 답이 도착했다 — 아주 작은 '톡' 하나
  } catch (e) {
    if (out.isConnected) out.innerHTML = statusHtml(errorText(e), "err");
  } finally {
    if (alive()) composer.setBusy(false);
  }
}

// ── 서랍: 천체 목록 ───────────────────────────────────────────────

async function showCatalog({ group: startGroup = "all", q: startQ = "" } = {}) {
  enterView({ kind: "catalog", group: startGroup, q: startQ });
  const alive = claimPanel();
  openDrawer("catalog", `
    <div class="head"><div class="eyebrow">천체 목록</div><h2 class="h2 sm">어디를 바라볼까요</h2></div>
    <label class="search-field">${icon("search", 15)}<input id="catalog-q" type="search" placeholder="천체 이름 찾기 (예: 보이저, 베가)" aria-label="천체 이름 찾기"></label>
    <div class="chips" id="catalog-groups">${GROUPS.map(([g, l]) => `<button type="button" class="chip sm ${g === startGroup ? "selected" : ""}" data-g="${g}">${l}</button>`).join("")}</div>
    <div class="catalog" id="catalog-list">${statusHtml("목록을 불러오는 중…")}</div>
    <div class="disclaimer" id="catalog-note"></div>`);
  if (!state.catalog) {
    try {
      state.catalog = await api.search("");
    } catch (e) {
      if (alive()) $("#catalog-list").innerHTML = statusHtml(errorText(e), "err");
      return;
    }
  }
  if (!alive()) return;
  let group = GROUPS.some(([g]) => g === startGroup) ? startGroup : "all";
  $("#catalog-q").value = startQ;
  const draw = () => {
    updateView({ kind: "catalog", group, q: $("#catalog-q").value });   // 뒤로 돌아오면 같은 필터 · 검색어로
    const q = $("#catalog-q").value.trim().toLowerCase();
    const list = state.catalog.filter((o) => (group === "all" || o.group === group)
      && (!q || o.name.toLowerCase().includes(q) || (o.name_en ?? "").toLowerCase().includes(q)));
    $("#catalog-list").innerHTML = list.map((o) => `<button type="button" class="catalog-row ${isObserved(o.id) ? "seen" : ""}" data-id="${esc(o.id)}">
        ${markHtml(isObserved(o.id))}
        <span><span class="nm">${esc(o.name)}</span><span class="ds">${esc(o.group_ko)}${o.kind ? ` · ${esc(o.kind)}` : ""}</span></span>
        <span class="dist">${o.distance_km ? esc(distanceText(o.distance_km)) : ""}</span></button>`).join("")
      || `<p class="status warn">찾는 항목이 없습니다.</p>`;
    $("#catalog-note").textContent = `전체 ${state.catalog.length}건 중 ${list.length}건 · ✦ 표식은 내 세계에 담은 빛, 점선 원은 아직 만나지 않은 빛`;
  };
  $("#catalog-q").addEventListener("input", draw);
  $("#catalog-groups").addEventListener("click", (e) => {
    const b = e.target.closest("[data-g]");
    if (!b) return;
    group = b.dataset.g;
    $("#catalog-groups").querySelectorAll("[data-g]").forEach((x) => x.classList.toggle("selected", x === b));
    draw();
  });
  $("#catalog-list").addEventListener("click", (e) => {
    const row = e.target.closest("[data-id]");
    if (row) pickItem(row.dataset.id);
  });
  draw();
  $("#catalog-q").focus({ preventScroll: true });
}

// 목록 · 탐색 결과에서 고르기 — 하늘에 떠 있으면 그쪽으로 고개를 돌리고, 없으면 내 세계(지도)에서
function pickItem(id, question) {
  const inSky = state.mode === "sky" && state.sky.pickables().some((t) => t.data.id === id);
  if (inSky) state.sky.lookAt(id);
  else if (state.mode !== "map" && state.catalog?.find((o) => o.id === id)?.group !== "constellation") setMode("map");
  const opened = selectItem(id);
  // 조건 탐색에서 넘어온 질문 — 그 천체의 서랍이 열리면 같은 질문을 그대로 보낸다 (질의응답 · 근거)
  if (question) opened.then(() => state.historyLoaded).then(() => {
    const form = $("#chat-form");
    if (!form || state.item?.id !== id || state.drawer !== "item") return;   // 그사이 다른 것을 골랐다
    form.querySelector("input").value = question;
    form.requestSubmit();
  });
}

// ── 서랍: 기능 ────────────────────────────────────────────────────────────

const toolHead = (eyebrow, title, sub) =>
  `<div class="head"><div class="eyebrow">${eyebrow}</div><h2 class="h2">${title}</h2></div>${sub ? `<p class="sub">${sub}</p>` : ""}`;

function showExplore({ query = "" } = {}) {
  enterView({ kind: "explore", query });
  const alive = claimPanel();
  openDrawer("explore", `
    ${toolHead("조건 탐색", "확인할 수 있는<br>조건으로 찾기", "거리 · 종류 · 맨눈 관측 · 계절 · 빛이 출발한 시대처럼 확인할 수 있는 조건으로 찾습니다.")}
    ${composerHtml("explore-form", { ic: "search", placeholder: "예: 조선 시대에 출발한 빛이 지금 도착한 별" })}
    <div class="chips">${["맨눈으로 볼 수 있는 은하", "한국이 만든 인공위성", "겨울 밤에 보이는 별자리", "100광년 안의 밝은 별"]
      .map((q) => `<button type="button" class="chip sm" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>
    <div class="stack" id="explore-out"></div>`);
  let composer;
  const gate = requestGate();          // 같은 서랍 안의 연속 요청 — 최신 요청만 반영 (칩 · 입력 모두)
  const out = $("#explore-out");
  const run = (q) => runLatest(gate, alive, {
    work: () => remembered(`explore:${q}`, () => api.explore(q)),
    onStart: () => { out.innerHTML = statusHtml("조건을 해석하고 찾는 중…"); composer.setBusy(true); },
    onError: (e) => { out.innerHTML = statusHtml(errorText(e), "err"); },
    onSettled: () => composer.setBusy(false),
    onSuccess: (res) => {
      sound.tick();
      updateView({ kind: "explore", query: q });
      const dist = (id) => state.catalog?.find((o) => o.id === id)?.distance_km;
      // 질문에 나온 천체에게 묻기 — 사실 질문(ask)이면 주 안내, 카드가 있으면 카드 아래 보조 문구 (오류처럼 보이지 않게)
      const askHtml = res.mentioned?.length ? `<div class="stack sm ask-about">
            <p class="sub">${res.status === "ask" ? "이 천체에게 직접 물으면 문서를 찾아 근거와 함께 답합니다." : "질문에 나온 천체에게 직접 물어볼 수도 있습니다."}</p>
            ${res.mentioned.map((m) => `<button type="button" class="card explore-card ask" data-ask="${esc(m.item_id)}" data-question="${esc(res.query)}">
              <div class="top"><span class="nm">${esc(m.name)}에게 이 질문하기</span>${icon("arrow-right", 14)}</div>
              <p class="sub">"${esc(res.query)}"</p></button>`).join("")}</div>` : "";
      const cardsHtml = res.cards.map((c) => `<button type="button" class="card explore-card" data-id="${esc(c.item_id)}">
            <div class="top"><span class="nm">${markHtml(isObserved(c.item_id))}${esc(c.name)}</span>${dist(c.item_id) ? `<span class="badge neutral">${esc(distanceText(dist(c.item_id)))}</span>` : ""}</div>
            <p class="sub">${c.kind ? `${esc(c.kind)} · ` : ""}${esc(c.reason)}</p></button>${c.source_url && /^https?:\/\//.test(c.source_url)
              ? `<p class="disclaimer" style="margin-top:-4px;text-align:right"><a href="${esc(c.source_url)}" target="_blank" rel="noopener">근거 ↗</a></p>` : ""}`).join("");
      out.innerHTML = `
        ${res.applied.length ? `<p class="sub">적용한 조건: ${res.applied.map(esc).join(" · ")}</p>` : ""}
        ${res.notice ? `<p class="status warn">${esc(res.notice)}</p>` : ""}
        ${res.warnings.map((w) => `<p class="status warn">${esc(w)}</p>`).join("")}
        ${res.cards.length ? cardsHtml + askHtml : askHtml}`;
    },
  });
  composer = bindComposer($("#explore-form"), (q) => run(q));
  drawerBody.querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => { composer.input.value = b.dataset.q; run(b.dataset.q); }));
  $("#explore-out").addEventListener("click", (e) => {
    const ask = e.target.closest("[data-ask]");
    if (ask) return pickItem(ask.dataset.ask, ask.dataset.question);
    const c = e.target.closest("[data-id]");
    if (c) pickItem(c.dataset.id);
  });
  if (!state.catalog) api.search("").then((list) => { state.catalog ??= list; }).catch(() => null);   // 결과 카드의 거리 표시용
  if (query) { composer.input.value = query; composer.input.dispatchEvent(new Event("input")); run(query); }   // 뒤로 돌아온 결과
}

async function showLetter(body) {
  enterView({ kind: "letter", body: body ?? null });
  const alive = claimPanel();
  // 천체를 정해 왔으면(천체 서랍 · 발견 알림) 그 이름으로 — 지금 서랍의 천체가 아니면 알아간 빛 기록에서 찾는다
  const target = !body?.item_id ? null
    : state.item?.id === body.item_id ? state.item.name : world.visited.find((v) => v.id === body.item_id)?.name ?? null;
  openDrawer("letter", `
    ${toolHead("빛의 편지", target ? `${esc(target)}의 빛이<br>출발했을 때` : body?.item_id ? "이 빛이<br>출발했을 때" : "당신이 태어난 해에<br>출발한 빛",
      "지금 당신에게 닿은 이 빛이 출발했을 때, 지구에서는 무슨 일이 있었을까요? 나이를 넣으면 나이만큼 먼 별을 찾습니다.")}
    ${composerHtml("letter-form", { ic: "mail", type: "number", min: 1, max: 120, placeholder: "나이 (예: 25)" })}
    <div class="stack lg" id="letter-out"></div>`);
  let composer;
  const gate = requestGate();
  const out = $("#letter-out");
  const run = (req) => runLatest(gate, alive, {
    work: () => remembered(`letter:${JSON.stringify(req)}`, () => api.letter(req)),
    onStart: () => { out.innerHTML = statusHtml("빛의 여정을 계산하고 그 해의 기록을 찾는 중…"); composer.setBusy(true); },
    onError: (e) => { out.innerHTML = statusHtml(errorText(e), "err"); },
    onSettled: () => composer.setBusy(false),
    onSuccess: (res) => {
      const d = res.departure;
      const km = d.light_years * LY_KM;
      const label = res.matched_age ? `${res.matched_age}세 — ${res.item_name}의 빛` : `${res.item_name}의 빛`;
      out.innerHTML = `<div class="card emphasis pad-l">
          ${measureHtml(km, { label, size: "s" })}
          <p class="sub" style="margin-top:10px">${esc(d.summary)}</p>
          <div class="answer serif" style="margin-top:12px">${answerHtml(res.letter, "letter")}</div></div>
        ${res.warnings.map((w) => `<p class="status warn">${esc(w)}</p>`).join("")}
        ${res.cited.length ? `${res.notice ? `<p class="status warn">${esc(res.notice)}</p>` : ""}${evidenceHtml(res.cited, "letter")}`
          : `<p class="no-cite">${esc(res.notice || NO_CITE)}</p>`}
        ${res.status === "rejected" ? "" : shareBarHtml()}
        <div id="letter-collect">${collectButtonHtml({ id: res.item_id, name: res.item_name, distance_km: km, kindWord: "별" })}</div>`;
      bindCollect($("#letter-collect"), { id: res.item_id, name: res.item_name, distance_km: km });
      if (res.status === "rejected") return;    // 거절된 응답은 보관 · 공유하지 않는다
      const kept = keepLetter({ kind: "letter", item_id: res.item_id, item_name: res.item_name, title: label, text: res.letter, req });
      bindShareBar(out.querySelector("[data-share-bar]"), {
        body: { kind: "letter", ...req }, text: `${label}. ${plainText(res.letter)}`, keepKey: kept.key, letter: { title: label, text: res.letter },
        share: kept.shareId ? { id: kept.shareId, url: kept.url ?? shareCardUrl(kept.shareId), image_url: shareImageUrl(kept.shareId) } : null,
      });
    },
  });
  composer = bindComposer($("#letter-form"), (age) => {
    updateView({ kind: "letter", body: { age: Number(age) } });
    run({ age: Number(age) });
  });
  if (body?.item_id) run(body);
  else if (body?.age) { composer.input.value = String(body.age); composer.input.dispatchEvent(new Event("input")); run(body); }   // 뒤로 돌아온 나이
}

function supportHtml(res, strong) {
  return `<div class="support ${strong ? "strong" : ""}">${res.support.map((s) =>
    `<div class="line"><span class="nm">${esc(s.name)}</span><strong>${esc(s.number)}</strong><span class="hr">${esc(s.hours)}</span></div>`).join("")}</div>`;
}

async function showPerspective({ req: startReq = null } = {}) {
  enterView({ kind: "perspective", req: startReq });
  const alive = claimPanel();
  openDrawer("mind", `
    ${toolHead("마음 한 줄", "지금의 마음 곁에<br>사실 하나를", "지금의 마음을 한 줄로 적거나 골라 주세요. 그 곁에 우주의 사실 하나를 근거와 함께 놓아 드립니다.")}
    <div class="chips" id="themes"></div>
    ${composerHtml("mind-form", { ic: "moon-star", placeholder: "짧아도 괜찮아요. 지금 마음을 한 줄만", label: "지금 마음 한 줄 (Enter로 보내기, Shift+Enter로 줄 바꾸기)", multiline: true })}
    <div class="stack lg" id="mind-out"></div>
    <div class="spacer"></div>
    <p class="disclaimer">VastHorizon은 전문 심리상담을 대신하지 않습니다.</p>`);
  let composer;
  const gate = requestGate();
  const out = $("#mind-out");
  const run = (req) => runLatest(gate, alive, {
    work: () => remembered(`perspective:${JSON.stringify(req)}`, () => api.perspective(req)),
    onStart: () => { out.innerHTML = statusHtml("마음 한 줄을 읽고 이어 줄 사실을 찾는 중…"); composer.setBusy(true); },
    onError: (e) => { out.innerHTML = statusHtml(errorText(e), "err"); },
    onSettled: () => composer.setBusy(false),
    onSuccess: (res) => {
      updateView({ kind: "perspective", req });
      if (res.status === "crisis" || res.status === "unchecked") {
        out.innerHTML = `<div class="answer lead">${esc(res.answer)}</div>${supportHtml(res, true)}`;
      } else {
        const items = res.items.map((it) => `<button type="button" class="chip" data-id="${esc(it.id)}">${esc(it.name)}</button>`).join("");
        const shareable = res.status !== "rejected";          // 위기 · 거절 응답에는 공유 · 보관 버튼을 내지 않는다
        out.innerHTML = `${resultHtml(res.answer, res.cited, "mind", res.notice, res.warnings, "lead")}
          ${shareable ? shareBarHtml({ note: "공유 카드에는 적어 주신 문장은 담기지 않고, 곁에 놓인 우주의 사실만 담깁니다." }) : ""}
          ${items ? `<div class="eyebrow">이어서 둘러보기</div><div class="chips">${items}</div>` : ""}${supportHtml(res, false)}`;
        if (shareable) {
          // 보관함에는 사람이 적은 문장을 남기지 않는다 — 다시 받을 수 있게 고른 감정만
          const kept = keepLetter({ kind: "perspective", item_id: res.items[0]?.id ?? null, item_name: res.items[0]?.name ?? null,
                                    title: "마음 한 줄 곁의 사실", text: res.answer, req: req.theme ? { theme: req.theme } : null });
          bindShareBar(out.querySelector("[data-share-bar]"), {
            body: { kind: "perspective", ...req }, text: plainText(res.answer), keepKey: kept.key,
            letter: { title: "마음 한 줄 곁의 사실", text: res.answer },
            share: kept.shareId ? { id: kept.shareId, url: kept.url ?? shareCardUrl(kept.shareId), image_url: shareImageUrl(kept.shareId) } : null,
          });
        }
      }
    },
  });
  composer = bindComposer($("#mind-form"), (text) => run({ text }));
  if (startReq?.text) { composer.input.value = startReq.text; composer.input.dispatchEvent(new Event("input")); }
  if (startReq) run(startReq);                 // 뒤로 돌아온 마음 한 줄 — 같은 결과
  else composer.input.focus({ preventScroll: true });   // 처음 열면 바로 적을 수 있게 (키보드: 메뉴 → 마음 한 줄 → 입력)
  $("#mind-out").addEventListener("click", (e) => { const c = e.target.closest("[data-id]"); if (c) pickItem(c.dataset.id); });
  const themes = await api.themes().catch(() => []);
  if (!alive()) return;               // 감정 버튼을 받는 사이 다른 서랍으로 갔다
  $("#themes").innerHTML = themes.map((t) => `<button type="button" class="chip ${startReq?.theme === t.key ? "selected" : ""}" data-theme="${esc(t.key)}">${esc(t.label)}</button>`).join("");
  $("#themes").addEventListener("click", (e) => {
    const b = e.target.closest("[data-theme]");
    if (!b) return;
    $("#themes").querySelectorAll("[data-theme]").forEach((x) => x.classList.toggle("selected", x === b));
    run({ theme: b.dataset.theme });
  });
}

async function showSkyGuide() {
  if (state.mode !== "sky") setMode("sky");
  enterView({ kind: "tonight" });
  const alive = claimPanel();
  const { place } = state.sky;
  const fmt = (d) => d.toLocaleString("ko-KR", { dateStyle: "long", timeStyle: "short" });
  openDrawer("tonight", `
    ${toolHead("오늘 밤 나의 하늘", `${esc(place.name)}의 하늘`, "")}
    <p class="sub" id="sky-when">${esc(fmt(state.sky.date))}</p>
    <div class="field-row"><span class="lbl">시각</span>
      <input id="hours" type="range" min="-12" max="12" step="0.5" value="${state.skyHours ?? 0}" aria-label="시각 (지금부터 몇 시간)">
      <span class="val" id="hours-val"></span></div>
    <div class="row">${btn("이 하늘 안내 받기", { variant: "primary", ic: "sparkles", id: "guide-btn" })}${btn("내 위치로", { ic: "map-pin", id: "locate-btn" })}</div>
    <div class="stack lg" id="sky-out"></div>`);
  const out = $("#sky-out");
  const listHtml = (res) => `
    <div class="eyebrow">높이 뜬 별자리</div>
    <div class="chips">${res.constellations.slice(0, 12).map((c) => `<button type="button" class="chip sm" data-look="${esc(c.item_id)}">${esc(c.name)} · ${esc(c.direction)} ${Math.round(c.alt_deg)}°</button>`).join("")}</div>
    ${res.planets.length ? `<div class="eyebrow">행성</div><div class="chips">${res.planets.map((p) => `<button type="button" class="chip sm" data-look="${esc(p.item_id ?? "")}"><span class="dot" style="background:var(--group-solar)"></span>${esc(p.name)} · ${esc(p.direction)} ${Math.round(p.alt_deg)}°</button>`).join("")}</div>` : ""}
    ${res.is_night ? "" : `<p class="status warn">지금은 해가 떠 있거나 하늘이 밝습니다 (태양 고도 ${res.sun_alt_deg}°). 시각 막대로 밤을 골라 보세요.</p>`}`;
  const req = (guide) => ({ lat: state.sky.place.lat, lon: state.sky.place.lon, at: state.sky.date.toISOString(), guide });
  const gate = requestGate();
  const sky = (guide, progress, render) => runLatest(gate, alive, {
    work: () => api.sky(req(guide)),
    onStart: () => {
      const guideBtn = $("#guide-btn");
      if (!guideBtn) return;                  // 이미 다른 서랍 화면 — runLatest는 onStart를 세대와 상관없이 부른다
      out.innerHTML = statusHtml(progress);
      guideBtn.disabled = guide;
    },
    onSuccess: render,
    onError: (e) => { out.innerHTML = statusHtml(errorText(e), "err"); },
    onSettled: () => { $("#guide-btn").disabled = false; },
  });
  const warningsHtml = (res) => res.warnings.map((w) => `<p class="status warn">${esc(w)}</p>`).join("");
  const loadList = () => sky(false, "이 시각의 하늘을 계산하는 중…", (res) => { out.innerHTML = listHtml(res) + warningsHtml(res); });
  out.addEventListener("click", (e) => { const b = e.target.closest("[data-look]"); if (b?.dataset.look) state.sky.lookAt(b.dataset.look); });
  const showHours = () => {
    $("#hours-val").textContent = `${Number($("#hours").value) >= 0 ? "+" : ""}${$("#hours").value}시간`;
  };
  showHours();
  let listTimer;
  let skyPending = false;
  panelLeave = () => {                         // 서랍을 닫거나 다른 화면을 열면 — 시각 막대의 남은 타이머를 거둔다
    clearTimeout(skyTimer);
    clearTimeout(listTimer);
    if (skyPending && state.mode === "sky") refreshSky();   // 하늘 배경은 막대가 고른 시각에 맞춰 둔다 (목록은 그리지 않는다)
    skyPending = false;
  };
  $("#hours").addEventListener("input", () => {
    showHours();
    state.skyHours = Number($("#hours").value);
    clearTimeout(skyTimer);
    skyPending = true;
    skyTimer = setTimeout(async () => {
      skyPending = false;
      if (!alive()) return;
      await refreshSky();
      if (!alive()) return;
      $("#sky-when").textContent = fmt(state.sky.date);
      clearTimeout(listTimer);
      listTimer = setTimeout(() => alive() && loadList(), 100);
    }, 150);
  });
  $("#locate-btn").addEventListener("click", () => locate(() => { if (alive()) showSkyGuide(); }));
  $("#guide-btn").addEventListener("click", () => sky(true, "별자리 정보를 근거로 안내를 쓰는 중…", (res) => {
    const guide = res.guide ? resultHtml(res.guide, res.cited, "sky", res.notice) : "";
    out.innerHTML = guide + listHtml(res) + warningsHtml(res);
  }));
  loadList();
}

function showUnfoldPanel(con) {
  enterView({ kind: "unfold", id: con.item_id });
  const alive = claimPanel();
  const mode = state.unfold;
  const near = mode.nearest, far = mode.farthest;
  const ly = (s) => ({ value: Math.round(s.distance_ly).toLocaleString("ko-KR"), unit: "광년" });
  openDrawer("unfold", `
    ${toolHead("별자리 펼치기", `${esc(con.name)} 펼치기`, "별자리는 지구에서만 보이는 모양입니다. 같은 하늘에 붙어 보이는 별들이 실제로는 얼마나 떨어져 있는지 펼쳐 봅니다. (거리는 로그 스케일)")}
    <select class="select" id="con-select" aria-label="별자리 고르기">${state.constellations.map((c) => `<option value="${esc(c.item_id)}" ${c === con ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select>
    ${near && far ? `<div class="card"><div class="measure-pair">
      ${measureHtml(0, { label: "가장 가까운 별", caption: near.name, size: "s", unitOnly: ly(near) })}
      ${measureHtml(0, { label: "가장 먼 별", caption: far.name, size: "s", unitOnly: ly(far) })}</div></div>` : ""}
    <div class="row">${btn("펼치기", { variant: "primary", ic: "play", id: "do-unfold" })}${btn("지구에서 보기", { ic: "undo-2", id: "do-fold" })}</div>
    <div class="rule"></div>
    <div class="row">${btn("근거와 함께 설명 보기", { ic: "sparkles", id: "unfold-explain" })}${btn("별자리 정보 · 물어보기", { variant: "ghost", icRight: "arrow-right", id: "unfold-item" })}</div>
    <div class="stack" id="unfold-out"></div>`);
  $("#con-select").addEventListener("change", (e) => setMode("unfold", e.target.value));
  $("#do-unfold").addEventListener("click", () => state.unfold.play(true));
  $("#do-fold").addEventListener("click", () => state.unfold.play(false));
  $("#unfold-item").addEventListener("click", () => selectItem(con.item_id, { fly: false }));
  const gate = requestGate();
  $("#unfold-explain").addEventListener("click", () => runLatest(gate, alive, {
    work: () => api.unfold(con.item_id),
    onStart: () => { $("#unfold-out").innerHTML = statusHtml("별들의 거리표와 문서를 근거로 설명을 쓰는 중…"); $("#unfold-explain").disabled = true; },
    onSuccess: (res) => { $("#unfold-out").innerHTML = resultHtml(res.explanation, res.cited, "unfold", res.notice, res.warnings); },
    onError: (e) => { $("#unfold-out").innerHTML = statusHtml(errorText(e), "err"); },
    onSettled: () => { $("#unfold-explain").disabled = false; },
  }));
}

// ── 서랍: 받은 편지 ─────────────────────────────────────────────────────
//   목록(날짜 · 천체 · 첫 문장) → 다시 열기 · 삭제. 공유한 편지는 /api/l/<id>.json으로 전체를, 아니면 보관한 앞부분을

const kindLabel = (kind) => (kind === "perspective" ? "마음 한 줄" : "빛의 편지");

function showLetters() {
  enterView({ kind: "letters" });
  claimPanel();
  openDrawer("letters", `
    ${toolHead("받은 편지", "지금까지 받은<br>빛의 편지", "빛의 편지와 마음 한 줄을 이 기기에 최대 50개까지 남겨 둡니다. 다른 기기와는 이어지지 않습니다.")}
    <div id="letters-out"></div>`);
  const out = $("#letters-out");
  const draw = () => {
    out.innerHTML = letters.length ? `<ol class="letter-list">${letters.map((e) => `<li>
        <button type="button" class="letter-row" data-open="${esc(e.key)}">
          <span class="lr-meta">${esc(letterDate(e.at))} · ${esc(e.item_name || kindLabel(e.kind))}${e.shareId ? ` · <span class="lr-shared">공유함</span>` : ""}</span>
          <span class="lr-title">${esc(e.title || kindLabel(e.kind))}</span>
          <span class="lr-first">${esc(firstSentence(e.text))}</span></button>
        <button type="button" class="letter-del" data-del="${esc(e.key)}" aria-label="${esc(`${letterDate(e.at)} ${e.title || kindLabel(e.kind)} 삭제`)}">${icon("x", 14)}</button></li>`).join("")}</ol>`
      : `<p class="sub">아직 받은 편지가 없습니다. 빛의 편지를 받거나 마음 한 줄을 남기면 여기에 쌓입니다.</p>
        <div class="row">${btn("빛의 편지 받기", { ic: "mail", attrs: 'data-go="letter"' })}${btn("마음 한 줄 남기기", { ic: "moon-star", attrs: 'data-go="mind"' })}</div>`;
  };
  draw();
  out.addEventListener("click", (e) => {
    const go = e.target.closest("[data-go]");
    if (go) { TOOL_OPEN[go.dataset.go](); return; }
    const del = e.target.closest("[data-del]");
    if (del) {
      const rows = [...out.querySelectorAll("[data-del]")];
      const at = rows.indexOf(del);
      letters = removeLetter(letters, del.dataset.del);
      saveLetters();
      draw();
      toast("받은 편지 하나를 지웠습니다");
      // 지운 자리의 다음 항목으로 포커스 — 다 지웠으면 제목으로
      const next = out.querySelectorAll("[data-del]")[Math.min(at, letters.length - 1)];
      if (next) next.focus({ preventScroll: true });
      else focusDrawerHeading();
      return;
    }
    const row = e.target.closest("[data-open]");
    if (row) showKept({ key: row.dataset.open });
  });
}

// 받은 편지 하나 — key: 보관함 기록 · share: 공유 ID(딥링크 ?letter=<id>)
async function showKept({ key = null, share = null } = {}) {
  enterView(share ? { kind: "kept", share } : { kind: "kept", key });
  const alive = claimPanel();
  const entry = key ? findLetter(letters, key) : null;
  const shareId = share ?? entry?.shareId ?? null;
  if (!shareId) {
    if (entry) drawKeptLocal(entry);
    else openDrawer("kept", `${toolHead("받은 편지", "지운 편지입니다", "")}<div class="row">${btn("받은 편지 모두 보기", { id: "kept-list" })}</div>`);
    $("#kept-list")?.addEventListener("click", showLetters);
    return;
  }
  openDrawer("kept", statusHtml("편지를 불러오는 중…"));
  let rec;
  try {
    rec = await api.sharedLetter(shareId);
  } catch (e) {
    if (!alive()) return;
    if (entry) { drawKeptLocal(entry, "공유한 편지를 불러오지 못해 보관한 앞부분을 보여 드립니다."); return; }
    closeDrawer();
    toast(e.status === 404 ? "편지를 찾지 못했습니다 · 링크가 지워졌거나 주소가 잘못되었을 수 있어요" : esc(errorText(e)));
    return;
  }
  if (!alive()) return;
  const view = sharedView(rec);
  const kept = keepLetter({ kind: view.kind, item_id: view.item_id, item_name: view.item_name,
                            title: view.title, text: view.text, shareId, url: entry?.url ?? shareCardUrl(shareId), req: entry?.req ?? null });
  drawShared(view, kept, shareId);
}

// 공유된 편지 전체 — sharedView(서버의 편지 기록 { kind, item_id, item_name, title, text, departure?, cited, themes?, created })
function drawShared(rec, kept, shareId) {
  const { isLetter, cited, title } = rec;
  const d = rec.departure;
  openDrawer("kept", `
    ${toolHead(kindLabel(rec.kind), esc(title), "")}
    <p class="sub">${esc(letterDate(rec.created ?? kept.at))}${rec.item_name ? ` · ${esc(rec.item_name)}` : ""}</p>
    <div class="stack lg" id="kept-out">
      <div class="card emphasis pad-l">
        ${d?.light_years ? measureHtml(d.light_years * LY_KM, { label: `${rec.item_name ?? ""}의 빛`, size: "s" }) : ""}
        ${d?.summary ? `<p class="sub" style="margin-top:10px">${esc(d.summary)}</p>` : ""}
        <div class="answer serif" style="margin-top:12px">${answerHtml(rec.text, "kept")}</div></div>
      ${cited.length ? evidenceHtml(cited, "kept") : `<p class="no-cite">${esc(NO_CITE)}</p>`}
      ${shareBarHtml()}
      <div class="row">${isLetter && rec.item_id ? btn("이 천체 보기", { ic: "sparkles", id: "kept-item" }) : ""}${btn("받은 편지 모두 보기", { variant: "ghost", id: "kept-list" })}</div></div>`);
  bindShareBar($("#kept-out [data-share-bar]"), {
    share: { id: shareId, url: kept.url ?? shareCardUrl(shareId), image_url: shareImageUrl(shareId) },
    text: `${title}. ${plainText(rec.text)}`, letter: { title, text: rec.text },
  });
  $("#kept-item")?.addEventListener("click", () => pickItem(rec.item_id));
  $("#kept-list").addEventListener("click", showLetters);
}

// 공유하지 않은 편지 — 보관한 앞부분과, 다시 받는 길
function drawKeptLocal(entry, note = "보관함에는 편지의 앞부분만 남겨 둡니다. 전체를 다시 읽으려면 편지를 다시 받아 보세요.") {
  const again = entry.req && (entry.kind === "letter" || entry.req.theme);
  openDrawer("kept", `
    ${toolHead(kindLabel(entry.kind), esc(entry.title || kindLabel(entry.kind)), "")}
    <p class="sub">${esc(letterDate(entry.at))}${entry.item_name ? ` · ${esc(entry.item_name)}` : ""}</p>
    <div class="stack lg" id="kept-out">
      <div class="card emphasis pad-l"><div class="answer serif">${esc(entry.text)}</div></div>
      <p class="disclaimer">${esc(note)}</p>
      ${again ? shareBarHtml() : speech ? shareBarHtml({ shareable: false }) : ""}
      <div class="row">${again ? btn("이 편지 다시 받기", { variant: "primary", ic: "mail", id: "kept-again" }) : ""}
        ${entry.kind === "letter" && entry.item_id ? btn("이 천체 보기", { ic: "sparkles", id: "kept-item" }) : ""}
        ${btn("받은 편지 모두 보기", { variant: "ghost", id: "kept-list" })}</div></div>`);
  bindShareBar($("#kept-out [data-share-bar]"), { body: again ? { kind: entry.kind, ...entry.req } : null, text: `${entry.title}. ${entry.text}`, keepKey: entry.key,
                                                  letter: { title: entry.title || kindLabel(entry.kind), text: entry.text } });
  $("#kept-again")?.addEventListener("click", () => (entry.kind === "letter" ? showLetter(entry.req) : showPerspective({ req: entry.req })));
  $("#kept-item")?.addEventListener("click", () => pickItem(entry.item_id));
  $("#kept-list").addEventListener("click", showLetters);
}

const TOOL_OPEN = {
  explore: showExplore,
  letter: () => showLetter(state.item?.distance_km ? { item_id: state.item.id } : null),
  mind: showPerspective,
  tonight: showSkyGuide,
  unfold: () => setMode("unfold"),
};

// ── 보기 모드 ─────────────────────────────────────────────────────────────

let stage;
let skyTimer;
let skyRequest = 0;

// 배경음 — 내 세계 지도는 "map", 하늘과 별자리 펼치기는 "sky" (sound.js PAD_MODES)
const ambientOf = (mode) => (mode === "map" ? "map" : "sky");

function setMode(mode, conId, { journey = false, keepView = false } = {}) {
  clearTimeout(skyTimer);
  skyRequest += 1;                    // 진행 중인 하늘 요청은 무효 — 이전 모드의 응답이 새 화면을 건드리지 않게
  state.mode = mode;
  if (mode === "map") {
    state.map.setWorld(world.km, world.visited);      // 먼저 — 처음 들어올 때 알아간 천체가 한눈에 들어오는 자리를 잡는다
    stage.setMode(state.map);
    if (journey) state.map.journey(() => toast(`여기까지가 지금 당신의 세상입니다 · <em class="kw plain">${esc(world.name)}</em>`), journeyEnd);
    else if (state.item && !keepView) state.map.select(state.item.id);
  } else if (mode === "sky") {
    stage.setMode(state.sky);
    refreshSky();
  } else if (mode === "unfold") {
    const id = conId ?? (state.item?.group === "constellation" ? state.item.id : null);
    const con = state.constellations.find((c) => c.item_id === id) ?? state.constellations.find((c) => c.name === DEFAULT_CONSTELLATION);
    if (!con) return;
    state.unfold = new UnfoldMode(con);
    stage.setMode(state.unfold);
    showUnfoldPanel(con);
    setTimeout(() => state.unfold === stage.mode && state.unfold.play(true), 900);
  }
  if (!document.querySelector(".prologue")) sound.ambient(ambientOf(mode));   // 프롤로그가 떠 있으면 끝날 때 바꾼다
  renderChrome();
}

// 하늘의 위치 · 시각 — 최신 요청만 반영한다
async function refreshSky() {
  const sky = state.sky;
  const seq = ++skyRequest;
  const base = new Date();
  const date = new Date(base.getTime() + (state.skyHours ?? 0) * 3600_000);
  let planets = [];
  try {
    const res = await api.sky({ lat: sky.place.lat, lon: sky.place.lon, at: date.toISOString(), guide: false });
    if (seq !== skyRequest) return;   // 더 새 시각 · 위치 요청이 있다 — 날짜 · 행성 · 배경은 그 응답으로
    // 처음 열었는데 낮이면 오늘 밤 9시 하늘로 — 별을 볼 수 있는 시각부터 시작한다
    if (!res.is_night && state.skyHours === undefined) {
      const tonight = new Date(base);
      tonight.setHours(21, 0, 0, 0);
      const ahead = Math.round(((tonight - base) / 3600_000) * 2) / 2;
      if (ahead > 0 && ahead <= 12) {
        state.skyHours = ahead;
        if (!state.scene) toast("지금은 낮이라 오늘 밤 9시의 하늘을 보여 드립니다");
        return refreshSky();
      }
    }
    state.skyHours ??= 0;
    planets = res.planets;
    state.daytime = !res.is_night;
    sky.setDaylight(res.sun_alt_deg);
  } catch {
    if (seq !== skyRequest) return;   // 행성 없이 별자리만 (최신 요청일 때)
  }
  sky.setView({ date, planets });
  renderHint();
}

function locate(after) {
  if (!navigator.geolocation) return;
  navigator.geolocation.getCurrentPosition((pos) => {
    state.sky.place = { lat: pos.coords.latitude, lon: pos.coords.longitude, name: "내 위치" };
    if (state.mode === "sky") refreshSky();    // 위치를 받는 사이 다른 보기로 갔다면 다음에 하늘로 올 때 이 위치로
    after?.();
  }, () => toast("위치를 쓸 수 없어 서울 하늘로 계산합니다"));
}

// ── 3D 무대 조작 ──────────────────────────────────────────────────────────

function bindStage() {
  const el = stage.renderer.domElement;
  const tip = $("#tooltip");
  let down = null, pending = false, last = null;
  el.addEventListener("pointerdown", (e) => { down = { x: e.clientX, y: e.clientY }; });
  el.addEventListener("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5) return;
    const hit = stage.pick(e.clientX, e.clientY);
    if (!hit?.data?.id) return;
    showSelection({ id: hit.data.id, name: hit.data.name, position: hit.position });   // 서랍이 열리기 전에 바로 표시
    if (state.mode === "sky") selectItem(hit.data.id, { fly: false, hint: hit.data });   // 아무 별이나 그 별 자체(hip:…)로
    else selectItem(hit.data.id, { fly: state.mode === "map" });
  });
  el.addEventListener("pointermove", (e) => {
    last = e;
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      const hit = stage.pick(last.clientX, last.clientY);
      if (!hit) { tip.hidden = true; el.style.cursor = ""; return; }
      const rect = stage.container.getBoundingClientRect();
      tip.textContent = stage.mode.describe(hit.data);
      tip.style.left = `${last.clientX - rect.left}px`;
      tip.style.top = `${last.clientY - rect.top}px`;
      tip.hidden = false;
      el.style.cursor = state.mode === "sky" && hit.data.unobserved ? "crosshair" : "pointer";
    });
  });
  el.addEventListener("pointerleave", () => { tip.hidden = true; });
}

// ── 상태 점검 (색인 건수 · 키, 색인 안내) ─────────────────────────────

const NOTICE_COPY = {
  index_missing: "색인된 항목이 없습니다 — 색인 스크립트를 먼저 실행해 주세요. 그동안 하늘은 볼 수 있지만 답변은 만들 수 없습니다.",
  catalog_missing: "항목 카탈로그가 없습니다 — 수집 스크립트를 먼저 실행해 주세요.",
  missing_key: "API 키가 설정되지 않았습니다 — 답변과 문서 수집을 쓸 수 없습니다. 관리자에게 환경 설정을 확인해 달라고 요청해 주세요.",
};
const NOTICE_ICON = { error: "circle-alert", warning: "triangle-alert", info: "info" };

async function showHealth() {
  const status = $("#index-status");
  try {
    const h = await api.health();
    const shown = h.notices.filter((n) => n.level !== "info");
    $("#notices").innerHTML = shown.map((n) =>
      `<div class="notice ${esc(n.level)}">${icon(NOTICE_ICON[n.level] ?? "info", 14)}${esc(NOTICE_COPY[n.code] ?? n.message)}</div>`).join("");
    app.classList.toggle("has-notice", shown.length > 0);
    app.style.setProperty("--notice-h", `${$("#notices").offsetHeight}px`);   // 안내가 여러 줄이어도 크롬이 가리지 않게
    status.classList.toggle("warn", shown.length > 0);
    status.querySelector(".text").textContent = h.items_indexed
      ? `항목 ${h.items_indexed.toLocaleString("ko-KR")} · 문서 ${h.docs_indexed.toLocaleString("ko-KR")} 청크` : "색인 0건";
  } catch (e) {
    $("#notices").innerHTML = `<div class="notice error">${icon("circle-alert", 14)}${esc(errorText(e))}</div>`;
    app.classList.add("has-notice");
    app.style.setProperty("--notice-h", `${$("#notices").offsetHeight}px`);
    status.classList.add("warn");
    status.querySelector(".text").textContent = "서버 연결 안 됨";
  }
}

// ── 시작 ──────────────────────────────────────────────────────────────────

// 오늘의 하늘 — 서랍 · 장면을 닫고 하늘 보기로 (첫 하늘 문장이 다시 보인다)
function goSky() {
  closeScene();
  closeDrawer();
  if (state.mode !== "sky") setMode("sky");
}

// 메뉴 — 천체 목록 · 기능 모음 · 내 위치 · 프롤로그 · 색인 상태. 고르면 닫힌다
function setMenu(open) {
  const menu = $("#menu"), b = $("#menu-btn");
  if (menu.hidden === !open) return;
  menu.hidden = !open;
  app.classList.toggle("menu-open", open);     // 펼친 메뉴가 요약 카드 · 서랍 위로 (style.css .app.menu-open .chrome)
  b.setAttribute("aria-expanded", String(open));
  b.setAttribute("aria-label", open ? "메뉴 닫기" : "메뉴 열기");
  if (open) renderSoundItem();                 // 프롤로그에서 바꾼 소리 설정도 반영
  if (open) menu.querySelector(".menu-item:not([hidden])")?.focus({ preventScroll: true });
  else if (menu.contains(document.activeElement)) b.focus({ preventScroll: true });
}

// 글자 크게 — html[data-text="large"]면 서랍 본문 15 → 17px, 핵심 사실 · 제목도 같은 비율로 (style.css). 설정은 localStorage "vh-text"
const TEXT_KEY = "vh-text";
const textLarge = () => document.documentElement.dataset.text === "large";
function setTextLarge(on) {
  if (on) document.documentElement.dataset.text = "large";
  else delete document.documentElement.dataset.text;
  try { localStorage.setItem(TEXT_KEY, on ? "large" : "normal"); } catch { /* 무시 */ }
  renderTextItem();
}
function renderTextItem() {
  const b = $("#menu-text"), on = textLarge();
  b.innerHTML = `${icon("type", 16)}<span>글자 크게</span><span class="menu-state" aria-hidden="true">${on ? "켜짐" : "꺼짐"}</span>`;
  b.setAttribute("aria-pressed", String(on));
}
try { if (localStorage.getItem(TEXT_KEY) === "large") document.documentElement.dataset.text = "large"; } catch { /* 무시 */ }

// 메뉴의 소리 항목 — 이름은 "소리"로 고정, 상태는 aria-pressed와 아이콘(옆의 "켜짐" · "꺼짐"은 보기용, 읽지 않는다).
// 설정은 sound.js가 localStorage "vh-sound"에 (프롤로그의 소리 버튼과 같은 상태)
function renderSoundItem() {
  const b = $("#menu-sound"), on = sound.enabled;
  b.innerHTML = `${icon(on ? "volume" : "volume-x", 16)}<span>소리</span><span class="menu-state" aria-hidden="true">${on ? "켜짐" : "꺼짐"}</span>`;
  b.setAttribute("aria-pressed", String(on));
}

function bindChrome() {
  $("#menu-btn").innerHTML = icon("menu", 16);
  $("#menu-btn").addEventListener("click", () => setMenu($("#menu").hidden));
  document.addEventListener("pointerdown", (e) => { if (!e.target.closest(".menu-wrap")) setMenu(false); });
  $("#menu").addEventListener("click", (e) => { if (e.target.closest(".menu-item:not(#menu-sound):not(#menu-text)")) setMenu(false); });   // 소리 · 글자 크기는 켜고 끈 결과가 보이게 열어 둔다
  $("#menu-sky").innerHTML = `${icon("sparkles", 16)}<span>오늘의 하늘</span>`;
  $("#menu-world").innerHTML = `${icon("globe", 16)}<span>내 세계</span>`;
  $("#nav-sky").addEventListener("click", goSky);
  $("#menu-sky").addEventListener("click", goSky);
  $("#nav-world").addEventListener("click", () => openWorld());
  $("#menu-world").addEventListener("click", () => openWorld());
  $("#menu-locate").innerHTML = `${icon("map-pin", 16)}<span>내 위치의 하늘 보기</span>`;
  $("#menu-locate").addEventListener("click", () => { goSky(); locate(); });
  $("#menu-prologue").innerHTML = `${icon("play", 16)}<span>프롤로그 다시 보기</span>`;
  $("#menu-prologue").addEventListener("click", () => { closeScene(); closeDrawer(); startPrologue(); });
  renderSoundItem();
  $("#menu-sound").addEventListener("click", () => { sound.unlock(); sound.enabled = !sound.enabled; renderSoundItem(); });
  renderTextItem();
  $("#menu-text").addEventListener("click", () => setTextLarge(!textLarge()));
  $("#menu-letters").innerHTML = `${icon("mail", 16)}<span>받은 편지</span>`;
  $("#menu-letters").addEventListener("click", () => (state.drawer === "letters" ? closeDrawer() : showLetters()));
  $("#first-light").addEventListener("click", () => { sound.tick(); meetFirstLight(); });
  $("#first-prologue").innerHTML = `${icon("play", 14)}<span>프롤로그 다시 보기</span>`;
  $("#first-prologue").addEventListener("click", () => { closeScene(); closeDrawer(); startPrologue(); });
  $("#first-mind").innerHTML = `${icon("moon-star", 14)}<span>오늘 마음 한 줄 남기기</span>`;
  $("#first-mind").addEventListener("click", () => showPerspective());
  $(".ribbon-copy").addEventListener("click", (e) => { if (e.target.closest("[data-mind]")) showPerspective(); });
  $("#catalog-btn").innerHTML = `${icon("list", 16)}<span>천체 목록</span>`;
  $("#catalog-btn").addEventListener("click", () => (state.drawer === "catalog" ? closeDrawer() : showCatalog()));
  $("#drawer-close").innerHTML = icon("x", 15);
  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#drawer-back").innerHTML = `<span aria-hidden="true">←</span><span>뒤로</span>`;
  $("#drawer-back").addEventListener("click", goBack);   // 버튼으로만 — Alt+← · Backspace는 입력창과 겹친다
  $("#world-meter").addEventListener("click", () => openWorld());
  $("#journey-btn").innerHTML = icon("arrow-up-right", 20);
  $("#journey-btn").addEventListener("click", () => openWorld());
  $("#launcher").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tool]");
    if (!b) return;
    if (state.drawer === b.dataset.tool) closeDrawer();
    else TOOL_OPEN[b.dataset.tool]();
  });
  $("#horizon-scale").addEventListener("click", (e) => {
    const b = e.target.closest("[data-stop]");
    if (!b) return;
    if (b.dataset.stop === "0") { closeScene(); setMode("sky"); }
    else openWorld({ km: STOPS[+b.dataset.stop].km });          // 그 거리가 한눈에 보이는 자리로
  });
  for (const ev of ["pointermove", "pointerdown", "keydown", "wheel"]) window.addEventListener(ev, wake, { passive: true });
  window.addEventListener("resize", syncHush, { passive: true });
  window.addEventListener("resize", fitMapView, { passive: true });
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!$("#menu").hidden) setMenu(false);
    else if (state.scene === "end") closeScene();
    else if (state.drawer) closeDrawer();
  });
}

// 로딩 화면 걷기 — 금방 끝나도 깜빡이지 않게 로고가 뜬 뒤 최소 0.8초는 보여 주고, 0.35초에 걸쳐 사라진다
const LOADING_MIN_MS = 800, LOADING_LEAVE_MS = 350;
async function leaveLoading() {
  const el = $("#loading");
  const wait = LOADING_MIN_MS - (performance.now() - (Number(el.dataset.since) || 0));
  if (wait > 0) await new Promise((r) => setTimeout(r, wait));
  el.classList.add("leaving");
  setTimeout(() => { el.hidden = true; }, reducedMotion() ? 0 : LOADING_LEAVE_MS);
}

async function start() {
  sound.init();                                 // 설정 읽기 · 첫 제스처에서 오디오 열기 (그 전에는 소리를 내지 않는다)
  bindChrome();
  renderChrome();
  showHealth();
  wake();
  try {
    const [map, cons] = await Promise.all([api.map(), api.constellations()]);
    state.constellations = cons.constellations;
    state.mapData = map;
    state.refYear = map.ref_year ?? state.refYear;
    stage = new Stage($("#stage"));
    state.map = new MapMode(map);
    state.sky = new SkyMode(state.constellations, map.points.filter((p) => p.placement === "sky"),
                            map.points.filter((p) => p.group === "solar_system"));
    state.sky.setObserved(world.visited);
    state.map.setLetters(letterItemIds(letters));
    bindStage();
    await leaveLoading();
    // 바로 가기 주소 — ?mode=sky · ?mode=unfold&con=Q8860 · ?item=Q48469 · ?mode=map&journey=end · ?panel=catalog|explore|letter|mind|tonight|letters (시연 · 공유용)
    // 공유 링크 — ?letter=<id> 그 편지를 서랍에 열고 보관함에도 남긴다 (프롤로그는 건너뛴다 · 주소에서는 지워 새로 고쳐도 다시 열리지 않게)
    const params = new URLSearchParams(location.search);
    const letterId = params.get("letter");
    if (letterId) {
      const rest = new URLSearchParams(params);
      rest.delete("letter");
      history.replaceState(null, "", `${location.pathname}${rest.toString() ? `?${rest}` : ""}${location.hash}`);
    }
    const mode = ["map", "sky", "unfold"].includes(params.get("mode")) ? params.get("mode") : "sky";
    setMode(mode, params.get("con"), { journey: mode === "map" && !params.get("item") && params.get("journey") !== "end" });
    let prologue = false;                                   // 지구는 프롤로그의 구 장면에서 (건너뛰면 끝날 때)
    if (params.get("item")) selectItem(params.get("item"), { fly: true });
    else if (letterId) showKept({ share: letterId });
    else if (params.get("panel") === "catalog") showCatalog();
    else if (params.get("panel") === "letters") showLetters();
    else if (TOOL_OPEN[params.get("panel")]) TOOL_OPEN[params.get("panel")]();
    else if (mode === "sky" && prologueWanted(params)) { prologue = true; startPrologue(); }
    else if (mode === "sky" && !params.has("mode")) arriveFirstSky();
    if (!prologue) ensureEarth();                           // 프롤로그 없이 들어온 사람도 지구는 처음부터 알아간 빛
    if (params.get("journey") === "end") {
      stage.camera.position.copy(state.map.edgeView());
      journeyEnd();
    }
  } catch (e) {
    ensureEarth();
    $("#loading").classList.add("failed");   // 로고는 그 자리에 멈춘다
    $("#loading-text").textContent = `우주를 불러오지 못했습니다 — ${errorText(e)}`;
  }
}

if (new URLSearchParams(location.search).get("debug") === "1") {
  window.__vh = { state, world, selectItem, setMode, discover, openWorld, startJourney, resetWorld, showExplore, showPerspective, showSkyGuide, showCatalog, closeDrawer,
                  showLetter, showLetters, showKept, get letters() { return letters; },
                  refreshSky, get stage() { return stage; } };
}

start();
