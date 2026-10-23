// VastHorizon 화면 (디자인 v2) — 무대가 곧 페이지. 떠 있는 머리 · 발, 필요할 때만 여는 서랍, 처음 · 끝 장면.
//
//   하늘(첫 화면) ─ 흐릿한 빛 · 별을 누르면 그 천체의 이야기를 먼저 읽고, '내 세상에 담기'를 누르면
//                   흐릿한 빛이 한 점으로 모이며 이름 · 거리가 생기고, 내 세상의 반지름이 넓어진다
//   서랍         ─ 천체(물어보기) · 천체 목록 · 조건 탐색 · 빛의 편지 · 마음 한 줄 · 오늘 밤 하늘 · 별자리 펼치기
//   지평선 길    ─ 지평선(하늘) · 태양계 · 별 · 은하 · 우주의 끝 — 지평선 너머를 누르면 지구에서 떠오른다

import { api, askStream } from "./api.js";
import { departureLabel, distanceText, horizonKm, horizonScale, measure, worldScaleLine } from "./astro.js";
import { clearHistoryFlow, requestGate, runLatest } from "./flows.js";
import { icon } from "./icons.js";
import { GROUP_COLORS, MapMode } from "./map.js";
import { Stage } from "./scene.js";
import { colorWord } from "./skydata.js";
import { SkyMode } from "./sky.js";
import { playPrologue, STORAGE_KEY as PROLOGUE_KEY } from "./prologue.js";
import { igniteBurst } from "./dream.js";
import { loadBlackHoles, mountBlackHole } from "./blackhole.js";
import { analogies, countByGroup, growthText, groupLine, knownAndUnknown, newlyInside } from "./worldscale.js";
import { entryOf, localDate, reachOf, recent, restoreVisited, serialize, todays, WORLD_KEY } from "./journal.js";
import { UnfoldMode } from "./unfold.js";

const $ = (sel, root = document) => root.querySelector(sel);
const app = $("#app");
const drawerBody = $("#drawer-body");
const state = { mode: "sky", item: null, map: null, sky: null, unfold: null, constellations: [], refYear: 2026,
                drawer: null, scene: null, catalog: null };
const DEFAULT_CONSTELLATION = "오리온자리";
const LY_KM = 9460730472580.8;
const GROUPS = [["all", "전체"], ["star", "별"], ["messier", "메시에 천체"], ["solar_system", "태양계"],
                ["human_made", "인류의 발자취"], ["constellation", "별자리"]];
const groupColor = (g) => `#${(GROUP_COLORS[g] ?? 0x93b2ee).toString(16).padStart(6, "0")}`;
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

// 근거 목록 — 제목 · 원문 링크 · 출처 종류 태그(F2016: 메타데이터 / 외부 문서) · 발췌
function evidenceHtml(cited, scope) {
  return `<div><div class="evidence-title">근거</div><ol class="evidence" id="ev-${scope}">${cited.map((ev) => {
    const meta = ev.kind === "항목 메타데이터";
    return `<li data-n="${ev.number}"><span class="num">${ev.number}</span><div>
      <a href="${esc(ev.url)}" target="_blank" rel="noopener">${esc(ev.title)}${ev.section ? `<span class="sec"> › ${esc(ev.section)}</span>` : ""}</a>
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
  `<p class="status ${tone === "progress" ? "" : tone}">${tone === "progress" ? "<span class=\"dots\"><i></i><i></i><i></i></span>" : ""}${esc(text)}</p>`;

function measureHtml(km, { label, caption, size = "m", center = false, unitOnly } = {}) {
  const m = unitOnly ?? measure(km);
  return `<div class="measure ${size} ${center ? "center" : ""}">
    ${label ? `<div class="measure-label">${esc(label)}</div>` : ""}
    <div class="measure-row"><span class="measure-value">${esc(m.value)}</span><span class="measure-unit">${esc(m.unit)}</span></div>
    ${caption ? `<div class="measure-caption">${esc(caption)}</div>` : ""}</div>`;
}

const btn = (label, { variant = "secondary", size = "sm", ic, icRight, id, attrs = "" } = {}) =>
  `<button type="button" class="btn btn-${variant} ${size ? `btn-${size}` : ""}" ${id ? `id="${id}"` : ""} ${attrs}>${ic ? icon(ic, size === "lg" ? 17 : 15) : ""}<span class="label-text">${esc(label)}</span>${icRight ? icon(icRight, 15) : ""}</button>`;

function composerHtml(id, { ic = "message-circle", placeholder, type = "text", min, max } = {}) {
  return `<form class="composer" id="${id}" autocomplete="off">${icon(ic, 16)}
    <input type="${type}" ${min !== undefined ? `min="${min}" max="${max}"` : ""} maxlength="300" placeholder="${esc(placeholder)}" aria-label="${esc(placeholder)}">
    <button class="send" type="submit" aria-label="보내기">${icon("arrow-up", 16)}</button></form>`;
}

// 입력이 있을 때만 보내기 버튼이 켜진다
function bindComposer(form, onSubmit) {
  const input = form.querySelector("input");
  const sync = () => form.classList.toggle("ready", !!input.value.trim());
  input.addEventListener("input", sync);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const value = input.value.trim();
    if (!value || form.dataset.busy) return;
    onSubmit(value, input);
    sync();
  });
  return { input, setBusy: (b) => { if (b) form.dataset.busy = "1"; else delete form.dataset.busy; input.disabled = b; } };
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
// 지난 세대의 응답(성공 · 오류 모두)은 화면 · state에 반영하지 않는다. (F2014 리뷰 P2 — 응답 순서 · 화면 수명)
let panelGen = 0;
function claimPanel() {
  const gen = ++panelGen;
  return () => gen === panelGen;
}

function openDrawer(kind, html) {
  if (kind !== "item") clearSelection();      // 다른 기능 서랍으로 바뀌면 선택 표시도 지운다
  state.drawer = kind;
  drawerBody.dataset.kind = kind;
  drawerBody.innerHTML = html;
  drawerBody.scrollTop = 0;
  drawerBody.classList.remove("entering");
  void drawerBody.offsetWidth;                 // 내용이 바뀔 때마다 떠오르는 연출을 다시
  drawerBody.classList.add("entering");
  app.classList.add("drawer-open");
  const drawer = $("#drawer");
  if (drawer.inert) {                          // 닫혀 있다 열릴 때만 — 포커스를 서랍으로, 닫으면 원래 자리로
    drawer.inert = false;
    openDrawer.returnTo = document.activeElement;
    $("#drawer-close").focus({ preventScroll: true });
  }
  drawer.setAttribute("aria-hidden", "false");
  stage?.setInset(window.innerWidth > 860 ? 432 : 0);   // 서랍(400 + 여백 16 × 2) 만큼 시야를 비킨다
  renderChrome();
}

// 선택 표시 (하늘 · 내 세상) — 누른 천체 둘레의 맥박 고리
function showSelection(sel) {
  state.sky?.select(sel);
  state.map?.select(sel?.id, { fly: false });
}

function clearSelection() {
  showSelection(null);
}

function closeDrawer() {
  claimPanel();                                // 진행 중인 응답이 닫힌 서랍을 다시 그리지 않게
  clearSelection();
  state.drawer = null;
  app.classList.remove("drawer-open");
  const drawer = $("#drawer");
  const inside = drawer.contains(document.activeElement);
  drawer.setAttribute("aria-hidden", "true");
  drawer.inert = true;                         // 숨은 서랍 안으로 포커스가 들어가지 않게
  if (inside && openDrawer.returnTo?.isConnected) openDrawer.returnTo.focus({ preventScroll: true });
  stage?.setInset(0);
  renderChrome();
}

// ── 내 세상 — 알아간 빛의 기록. 날마다 지워지지 않고 쌓인다 (journal.js) ──────────────────────
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
  state.map?.setWorld(world.km, world.visited);
  renderChrome();
  showDiscovery(d);
  return d;
}

// 기록 지우기 — 사람이 직접 고를 때만
function resetWorld() {
  world.visited = [];
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
    : d.km ? `가장 먼 빛은 그대로지만, 내 세상은 빛 하나만큼 더 풍성해졌습니다`
    : d.group === "constellation" ? `별자리는 여러 거리의 별이 모인 모양이라 지도에는 놓지 않고, 알아간 빛 기록에 남겼습니다`
    : `거리는 아직 확인되지 않았지만, 알아간 빛 기록에 남았습니다`;
  const go = d.farther ? "넓어진 내 세상 보기" : d.km ? "내 세상에서 보기" : "알아간 빛 기록 보기";
  el.innerHTML = `<div class="growth-head"><span class="growth-x">${d.count.toLocaleString("ko-KR")}번째 빛</span>
      <span>내 세상에 새로운 빛 하나가 더해졌습니다 · <em class="kw plain">${esc(d.name)}</em></span></div>
    <p class="growth-in">${line}</p>
    ${d.passed.length ? `<p class="growth-in">그 사이에 아직 알아가지 않은 천체 ${d.passed.length.toLocaleString("ko-KR")}개 · 앞으로 알아갈 가능성입니다</p>` : ""}
    <button type="button" class="btn btn-horizon btn-sm" id="growth-go">${icon("globe", 14)}<span>${go}</span></button>`;
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
}

// 넓어지는 순간을 내 세상 보기에서 — 닿은 거리의 테두리가 자라고, 새로 알게 된 천체의 이름이 또렷해진다
function playGrowth(g) {
  closeScene();
  closeDrawer();
  if (state.mode !== "map") setMode("map");
  const crossed = pickCrossed(g.passed, 8);
  state.map.expandTo(g.fromKm, g.toKm, crossed, () => {
    toast(`<em class="kw plain">${esc(g.name)}</em>까지 내 세상이 닿았습니다 · 닿은 거리 ${esc(growthText(g.fromKm, g.toKm))}`);
  }, g.id);
}

// 이름을 띄울 천체 — 거리(로그)에 고르게 몇 개만 (너무 많으면 겹친다)
function pickCrossed(points, max) {
  if (points.length <= max) return points;
  return Array.from({ length: max }, (_, i) => points[Math.round((i * (points.length - 1)) / (max - 1))]);
}

// 담기 — 천체의 이야기를 읽고 난 뒤 사람이 직접 누른다. 거리를 몰라도 알아간 빛으로 기록할 수 있다
function collectButtonHtml(obj) {
  if (isObserved(obj.id)) {
    return `<div class="collected">${icon("sparkles", 15)}이미 내 세상에 담긴 빛입니다</div>`;
  }
  const label = obj.distance_km ? `다 읽었어요, 내 세상에 담기 (${distanceText(obj.distance_km)})`
    : obj.group === "constellation" ? "다 읽었어요, 알아간 빛으로 기록하기" : "다 읽었어요, 알아간 빛으로 기록하기 (거리 미확인)";
  const note = obj.distance_km ? `다 읽으셨다면, 이 ${obj.kindWord ?? "천체"}를 내 세상에 더해 보세요.`
    : "지도에 놓을 거리는 없지만, 알아간 빛 기록에는 남길 수 있습니다.";
  return `<div class="collect">
    <p class="collect-note">${note}</p>
    ${btn(label, { variant: "horizon", size: "lg", ic: "globe", attrs: 'data-collect="1" style="width:100%"' })}
  </div>`;
}

function bindCollect(root, obj) {
  root.querySelectorAll("[data-collect]").forEach((b) => b.addEventListener("click", () => {
    state.sky?.observe(obj);                     // 하늘에 떠 있으면 옅은 고리가 네온 분필 오로라와 이름으로 (이름이 막 나타나는 연출)
    const at = state.mode === "sky" ? state.sky.screenOf(obj.id) : null;
    if (at) igniteBurst(at.x, at.y, { reducedMotion: reducedMotion() });  // 알게 되는 순간 — 그 천체가 환하게 켜진다
    const d = discover(obj);
    b.closest(".collect").outerHTML = `<div class="collected">${icon("sparkles", 15)}내 세상에 새로운 빛으로 담았습니다 · 알아간 빛 ${(d?.count ?? world.visited.length).toLocaleString("ko-KR")}개</div>`;
  }));
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

function drawMeter(km) {
  $("#world-meter").innerHTML = `${measureHtml(km, {
    label: "내 세상의 가장 먼 빛", size: "l",
    caption: world.name === "지평선" ? "지평선까지 · 눈높이 1.7m 기준" : `${world.name}까지 · 알아간 빛 ${world.visited.length.toLocaleString("ko-KR")}개` })}
    <div class="meter-scale">${esc(worldScaleLine(km))}</div>`;
}

// ── 머리 · 발 ─────────────────────────────────────────────────────────────

const TOOLS = [["explore", "search", "조건 탐색"], ["letter", "mail", "빛의 편지"], ["mind", "moon-star", "마음 한 줄"],
               ["tonight", "orbit", "오늘 밤 하늘"], ["unfold", "telescope", "별자리 펼치기"]];
const STOPS = [{ label: "지평선", sub: "하늘 보기", km: HORIZON_KM }, { label: "태양계", sub: "10¹² m", km: 1e9 },
               { label: "별", sub: "10¹⁷ m", km: 1e14 }, { label: "은하", sub: "10²² m", km: 1e19 },
               { label: "우주의 끝", sub: "10²⁶ m", km: 4.4e23 }];

function renderChrome() {
  // 발사대 — 지금 연 기능은 밝게
  $("#launcher").innerHTML = TOOLS.map(([id, ic, label]) =>
    btn(label, { variant: state.drawer === id ? "primary" : "ghost", ic, attrs: `data-tool="${id}" title="${label}"` })).join("");
  $("#catalog-btn").className = `btn btn-sm ${state.drawer === "catalog" ? "btn-primary" : "btn-secondary"}`;

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
  renderHint();
  renderWorldCard();
}

// 내 세상 카드 — 내 세상 보기에서 늘. 기본은 알아간 빛 · 가장 먼 빛 · 최근 알아간 천체만, 크기 비교와 기록은 펼쳐서
function renderWorldCard() {
  const el = $("#world-card");
  if (!el) return;
  el.hidden = state.mode !== "map" || !!state.scene;
  if (el.hidden) return;
  const open = new Set([...el.querySelectorAll("details[open]")].map((d) => d.dataset.k));   // 다시 그려도 펼친 곳은 그대로
  if (renderWorldCard.openLog) { open.add("log"); renderWorldCard.openLog = false; }
  const byId = new Map(mapPoints().map((p) => [p.id, p]));
  const groupOf = (v) => v.group ?? byId.get(v.id)?.group ?? (v.id.startsWith("hip:") ? "star" : null);
  const visited = world.visited, today = todayCount(), last = recent(visited, 1)[0];
  const counts = countByGroup(visited.map((v) => ({ group: groupOf(v) })));
  const { unknown } = knownAndUnknown(mapPoints(), new Set(visited.map((v) => v.id)), world.km);
  const facts = analogies(world.km);
  const n = (x) => x.toLocaleString("ko-KR");
  el.innerHTML = `<div class="wc-kicker">내 세상</div>
    <div class="wc-row wc-main"><span>알아간 빛</span><b>${n(visited.length)}개</b></div>
    ${visited.length ? `<div class="wc-note">${today ? `오늘 새로 ${n(today)}개 · ` : ""}${esc(groupLine(counts))}</div>`
      : `<div class="wc-note">첫 번째 빛을 기다리고 있습니다. 천체 하나를 알아가면 이 지도에 첫 빛이 켜집니다</div>`}
    <div class="wc-row"><span>가장 먼 빛</span><b>${esc(distanceText(world.km))}</b></div>
    ${world.name !== "지평선" ? `<div class="wc-note">${esc(world.name)}</div>` : ""}
    ${last ? `<div class="wc-row"><span>최근 알아간 천체</span><b class="wc-name">${esc(last.name)}</b></div>` : ""}
    <details class="wc-more" data-k="compare" ${open.has("compare") ? "open" : ""}><summary>크기 비교 더 보기</summary>
      ${facts.map((f) => `<div class="wc-row"><span>${esc(f.label)}</span><b>${esc(f.value)}</b></div>${f.note ? `<div class="wc-note">${esc(f.note)}</div>` : ""}`).join("")}
      <div class="wc-row"><span>그 거리 안 아직 알아가지 않은 천체</span><b>${n(unknown.length)}개</b></div>
      <div class="wc-note">앞으로 알아갈 가능성입니다</div>
      <div class="wc-src">기준 · 지구 지름 12,742km(위키백과 「지구」) · 빛의 속도 299,792km/s</div></details>
    <details class="wc-more" data-k="log" ${open.has("log") ? "open" : ""}><summary>알아간 빛 기록 (${n(visited.length)})</summary>
      ${visited.length ? `<ol class="wc-log">${recent(visited).map((v) => `<li><button type="button" data-open="${esc(v.id)}">${esc(v.name)}</button>
        <span>${v.km ? esc(distanceText(v.km)) : groupOf(v) === "constellation" ? "별자리" : "거리 미확인"} · ${esc(v.at.slice(5).replace("-", "."))}</span></li>`).join("")}</ol>
        <button type="button" class="wc-reset" id="wc-reset">기록 처음부터 다시 시작</button>` : `<div class="wc-note">아직 기록이 없습니다</div>`}</details>
    <button type="button" class="btn btn-ghost btn-sm wc-journey" id="wc-journey">${icon("sparkles", 14)}<span>우주 끝까지 떠나 보기</span></button>`;
  el.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => {
    const v = world.visited.find((x) => x.id === b.dataset.open);
    if (v?.km) state.map?.select(v.id);
    selectItem(b.dataset.open, { fly: false });
  }));
  $("#wc-journey").addEventListener("click", startJourney);
  $("#wc-reset")?.addEventListener("click", (e) => {
    if (e.currentTarget.dataset.armed) { resetWorld(); return; }    // 한 번 더 눌러야 지운다
    e.currentTarget.dataset.armed = "1";
    e.currentTarget.textContent = "정말 지울까요? 한 번 더 누르면 모든 기록을 지웁니다";
  });
}

function renderHint() {
  const hint = $("#stage-hint");
  if (state.mode === "map") hint.textContent = "분필처럼 빛나는 점이 내가 알아간 천체 · 빛의 선은 내가 알아간 여정 · 흐린 점은 아직 알아가지 않은 천체";
  else if (state.mode === "unfold") hint.textContent = `지구에서 본 ${state.unfold?.con.name ?? "별자리"} · '펼치기'를 누르면 별들이 실제 거리로 이동합니다`;
  else if (state.daytime) hint.textContent = "지금은 해가 떠 있어 별이 보이지 않습니다 · 오늘 밤 하늘에서 시각을 바꿔 보세요";
  else hint.textContent = world.visited.length ? "아무 별이나 눌러 알아보세요 · 옅은 고리는 아직 알아가지 않은 천체 · 휠로 확대하면 더 어두운 별까지"
    : "오늘은 어떤 빛을 알아가 볼까요? · 별 하나를 눌러 보세요 · 휠로 확대하면 더 어두운 별까지";
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
  wake();
}

function showIntro() {
  showScene("intro", `<div class="scene-col">
    <div class="kicker st0">VASTHORIZON</div>
    <h1 class="st1">고개를 들어 보세요</h1>
    <div class="intro-measure st2">${measureHtml(HORIZON_KM, { label: "눈앞의 지평선", caption: "지평선까지 · 눈높이 1.7m 기준", size: "l", center: true })}</div>
    <p class="lede st3">눈앞의 지평선은 약 4.7km. 하지만 알아갈 수 있는 세계는 그 너머에 있습니다.<br>빛 하나를 알아갈 때마다, 당신의 세상은 <em class="kw">그만큼</em> 넓어집니다.</p>
    <div class="actions st4">${btn("내 위치의 하늘 보기", { variant: "primary", size: "lg", ic: "map-pin", id: "intro-locate" })}
      ${btn("서울 하늘로 시작", { variant: "ghost", size: "lg", id: "intro-seoul" })}</div>
    <button type="button" class="replay st4" id="intro-prologue">프롤로그 다시 보기</button></div>`);
  $("#intro-locate").addEventListener("click", () => { closeScene(); locate(); });
  $("#intro-seoul").addEventListener("click", closeScene);
  $("#intro-prologue").addEventListener("click", () => { closeScene(); startPrologue(); });
}

// 프롤로그 — 처음 켰을 때 한 번 (다시 보기 · ?prologue=1 로 언제든). 끝나면 처음 장면으로
function startPrologue() {
  $("#chrome").hidden = true;
  playPrologue({ reducedMotion: reducedMotion() }).then(() => { $("#chrome").hidden = false; showIntro(); });
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

// 내 세상 보기 — 처음 한 번만 우주 끝까지 떠오르고, 그 뒤에는 바로 지도로 (마지막에 보던 자리 · 알아간 천체가 한눈에)
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
  const attrs = Object.entries(a).filter(([k, v]) => v !== null && v !== "" && !/horizons_id/.test(k)).slice(0, ATTR_LIMIT);
  const isCon = item.group === "constellation";
  const suggestions = departs ? [`${item.name}의 빛은 언제 출발했나요?`, "맨눈으로 볼 수 있나요?"]
    : isCon ? [`${item.name}에서 가장 밝은 별은 무엇인가요?`, "언제 잘 보이나요?"]
    : [`${item.name}은(는) 지금 어디에 있나요?`, "어떤 일을 했나요?"];

  openDrawer("item", `
    <div class="head reveal" style="animation-delay:0ms">
      <div class="eyebrow">${esc(item.group_ko)}${code ? ` · <span class="code">${esc(code)}</span>` : ""}</div>
      <h2 class="name">${esc(item.name)}</h2>
      <div class="sub">${esc(item.kind ?? "")}</div></div>
    ${item.distance_km ? `<div class="reveal" style="animation-delay:180ms">${measureHtml(item.distance_km, { label: surface ? "지표면 위 고도" : "지구로부터" })}</div>` : ""}
    <div class="reveal" id="photo" style="animation-delay:270ms"></div>
    <div class="reveal" id="blackhole" style="animation-delay:300ms"></div>
    <div class="stack lg reveal intro" id="intro" style="animation-delay:360ms">${statusHtml("이 천체의 이야기를 불러오는 중…")}</div>
    ${departs ? `<div class="card emphasis letter-card reveal" style="animation-delay:540ms">
      <div class="letter-head">${icon("mail", 14)}빛의 편지</div>
      <div class="letter-body">지금 보이는 이 빛은 <em class="kw">${esc(departs)}</em>에 출발해, 오늘 당신의 눈에 닿아 여정을 마쳤습니다.</div>
      <div class="letter-note">카탈로그 거리(${esc(distanceText(item.distance_km))})로 계산한 출발 시점입니다.</div>
      <div class="row">${btn("그 해 지구의 기록 보기", { variant: "ghost", icRight: "arrow-right", id: "act-letter", attrs: 'style="padding-left:0"' })}</div></div>` : ""}
    <div class="reveal" id="collect-slot" style="animation-delay:720ms">${collectButtonHtml({ ...item, kindWord: item.group === "star" ? "별" : "천체" })}</div>
    <div class="stack reveal" style="animation-delay:900ms">
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
  mountBlackHole(box.querySelector("canvas"), { still: reducedMotion() });
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
  if (!r.sections.length) {
    box.innerHTML = r.notice ? `<p class="disclaimer">${esc(r.notice)}</p>` : "";
    return;
  }
  box.innerHTML = `${r.sections.map((x) => `<div class="story"><div class="eyebrow">${esc(x.heading)}</div><p class="story-text">${esc(x.text)}</p></div>`).join("")}
    <p class="disclaimer">출처 · <a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.source_type)} 「${esc(r.title)}」</a> · ${esc(r.license)} — 문서 첫머리를 그대로 옮겼습니다.</p>`;
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

// 진행 상태(F2012) — 서버가 보내는 단계 메시지를 차례로 쌓고, 지난 단계는 완료(초록)로
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
  } catch (e) {
    if (out.isConnected) out.innerHTML = statusHtml(errorText(e), "err");
  } finally {
    if (alive()) composer.setBusy(false);
  }
}

// ── 서랍: 천체 목록 (F2009) ───────────────────────────────────────────────

async function showCatalog() {
  const alive = claimPanel();
  openDrawer("catalog", `
    <div class="head"><div class="eyebrow">천체 목록</div><h2 class="h2 sm">어디를 바라볼까요</h2></div>
    <label class="search-field">${icon("search", 15)}<input id="catalog-q" type="search" placeholder="천체 이름 찾기 (예: 보이저, 베가)" aria-label="천체 이름 찾기"></label>
    <div class="chips" id="catalog-groups">${GROUPS.map(([g, l], i) => `<button type="button" class="chip sm ${i === 0 ? "selected" : ""}" data-g="${g}">${l}</button>`).join("")}</div>
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
  let group = "all";
  const draw = () => {
    const q = $("#catalog-q").value.trim().toLowerCase();
    const list = state.catalog.filter((o) => (group === "all" || o.group === group)
      && (!q || o.name.toLowerCase().includes(q) || (o.name_en ?? "").toLowerCase().includes(q)));
    $("#catalog-list").innerHTML = list.map((o) => `<button type="button" class="catalog-row ${isObserved(o.id) ? "seen" : ""}" data-id="${esc(o.id)}">
        <span class="gdot" style="background:${groupColor(o.group)};color:${groupColor(o.group)}"></span>
        <span><span class="nm">${esc(o.name)}</span><span class="ds">${esc(o.group_ko)}${o.kind ? ` · ${esc(o.kind)}` : ""}</span></span>
        <span class="dist">${o.distance_km ? esc(distanceText(o.distance_km)) : ""}</span></button>`).join("")
      || `<p class="status warn">찾는 항목이 없습니다.</p>`;
    $("#catalog-note").textContent = `전체 ${state.catalog.length}건 중 ${list.length}건 · 빛나는 점은 오늘 관측한 천체`;
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

// 목록 · 탐색 결과에서 고르기 — 하늘에 떠 있으면 그쪽으로 고개를 돌리고, 없으면 내 세상(지도)에서
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

function showExplore() {
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
    work: () => api.explore(q),
    onStart: () => { out.innerHTML = statusHtml("조건을 해석하고 찾는 중…"); composer.setBusy(true); },
    onError: (e) => { out.innerHTML = statusHtml(errorText(e), "err"); },
    onSettled: () => composer.setBusy(false),
    onSuccess: (res) => {
      const dist = (id) => state.catalog?.find((o) => o.id === id)?.distance_km;
      // 질문에 나온 천체에게 묻기 — 사실 질문(ask)이면 주 안내, 카드가 있으면 카드 아래 보조 문구 (오류처럼 보이지 않게)
      const askHtml = res.mentioned?.length ? `<div class="stack sm ask-about">
            <p class="sub">${res.status === "ask" ? "이 천체에게 직접 물으면 문서를 찾아 근거와 함께 답합니다." : "질문에 나온 천체에게 직접 물어볼 수도 있습니다."}</p>
            ${res.mentioned.map((m) => `<button type="button" class="card explore-card ask" data-ask="${esc(m.item_id)}" data-question="${esc(res.query)}">
              <div class="top"><span class="nm">${esc(m.name)}에게 이 질문하기</span>${icon("arrow-right", 14)}</div>
              <p class="sub">"${esc(res.query)}"</p></button>`).join("")}</div>` : "";
      const cardsHtml = res.cards.map((c) => `<button type="button" class="card explore-card" data-id="${esc(c.item_id)}">
            <div class="top"><span class="nm">${esc(c.name)}</span>${dist(c.item_id) ? `<span class="badge neutral">${esc(distanceText(dist(c.item_id)))}</span>` : ""}</div>
            <p class="sub">${c.kind ? `${esc(c.kind)} · ` : ""}${esc(c.reason)}</p></button>`).join("");
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
}

async function showLetter(body) {
  const alive = claimPanel();
  const target = body?.item_id && state.item?.id === body.item_id ? state.item.name : null;
  openDrawer("letter", `
    ${toolHead("빛의 편지", target ? `${esc(target)}의 빛이<br>출발했을 때` : "당신이 태어난 해에<br>출발한 빛",
      "지금 당신에게 닿은 이 빛이 출발했을 때, 지구에서는 무슨 일이 있었을까요? 나이를 넣으면 나이만큼 먼 별을 찾습니다.")}
    ${composerHtml("letter-form", { ic: "mail", type: "number", min: 1, max: 120, placeholder: "나이 (예: 25)" })}
    <div class="stack lg" id="letter-out"></div>`);
  let composer;
  const gate = requestGate();
  const out = $("#letter-out");
  const run = (req) => runLatest(gate, alive, {
    work: () => api.letter(req),
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
        <div id="letter-collect">${collectButtonHtml({ id: res.item_id, name: res.item_name, distance_km: km, kindWord: "별" })}</div>`;
      bindCollect($("#letter-collect"), { id: res.item_id, name: res.item_name, distance_km: km });
    },
  });
  composer = bindComposer($("#letter-form"), (age) => run({ age: Number(age) }));
  if (target) run(body);
}

function supportHtml(res, strong) {
  return `<div class="support ${strong ? "strong" : ""}">${res.support.map((s) =>
    `<div class="line"><span class="nm">${esc(s.name)}</span><strong>${esc(s.number)}</strong><span class="hr">${esc(s.hours)}</span></div>`).join("")}</div>`;
}

async function showPerspective() {
  const alive = claimPanel();
  openDrawer("mind", `
    ${toolHead("마음 한 줄", "지금의 마음 곁에<br>사실 하나를", "지금의 마음을 한 줄로 적거나 골라 주세요. 그 곁에 우주의 사실 하나를 근거와 함께 놓아 드립니다.")}
    <div class="chips" id="themes"></div>
    ${composerHtml("mind-form", { ic: "moon-star", placeholder: "예: 요즘 내가 너무 작게 느껴져" })}
    <div class="stack lg" id="mind-out"></div>
    <div class="spacer"></div>
    <p class="disclaimer">VastHorizon은 전문 심리상담을 대신하지 않습니다.</p>`);
  let composer;
  const gate = requestGate();
  const out = $("#mind-out");
  const run = (req) => runLatest(gate, alive, {
    work: () => api.perspective(req),
    onStart: () => { out.innerHTML = statusHtml("마음 한 줄을 읽고 이어 줄 사실을 찾는 중…"); composer.setBusy(true); },
    onError: (e) => { out.innerHTML = statusHtml(errorText(e), "err"); },
    onSettled: () => composer.setBusy(false),
    onSuccess: (res) => {
      if (res.status === "crisis" || res.status === "unchecked") {
        out.innerHTML = `<div class="answer lead">${esc(res.answer)}</div>${supportHtml(res, true)}`;
      } else {
        const items = res.items.map((it) => `<button type="button" class="chip" data-id="${esc(it.id)}">${esc(it.name)}</button>`).join("");
        out.innerHTML = `${resultHtml(res.answer, res.cited, "mind", res.notice, res.warnings, "lead")}
          ${items ? `<div class="eyebrow">이어서 둘러보기</div><div class="chips">${items}</div>` : ""}${supportHtml(res, false)}`;
      }
    },
  });
  composer = bindComposer($("#mind-form"), (text) => run({ text }));
  $("#mind-out").addEventListener("click", (e) => { const c = e.target.closest("[data-id]"); if (c) pickItem(c.dataset.id); });
  const themes = await api.themes().catch(() => []);
  if (!alive()) return;               // 감정 버튼을 받는 사이 다른 서랍으로 갔다
  $("#themes").innerHTML = themes.map((t) => `<button type="button" class="chip" data-theme="${esc(t.key)}">${esc(t.label)}</button>`).join("");
  $("#themes").addEventListener("click", (e) => {
    const b = e.target.closest("[data-theme]");
    if (!b) return;
    $("#themes").querySelectorAll("[data-theme]").forEach((x) => x.classList.toggle("selected", x === b));
    run({ theme: b.dataset.theme });
  });
}

async function showSkyGuide() {
  if (state.mode !== "sky") setMode("sky");
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
    onStart: () => { out.innerHTML = statusHtml(progress); $("#guide-btn").disabled = guide; },
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
  $("#hours").addEventListener("input", () => {
    showHours();
    state.skyHours = Number($("#hours").value);
    clearTimeout(skyTimer);
    skyTimer = setTimeout(async () => {
      await refreshSky();
      if (!alive()) return;
      $("#sky-when").textContent = fmt(state.sky.date);
      clearTimeout(listTimer);
      listTimer = setTimeout(loadList, 100);
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

// ── 상태 점검 (F2002 색인 건수 · F2012 안내) ─────────────────────────────

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

function bindChrome() {
  $("#catalog-btn").innerHTML = `${icon("list", 15)}<span>천체 목록</span>`;
  $("#catalog-btn").addEventListener("click", () => (state.drawer === "catalog" ? closeDrawer() : showCatalog()));
  $("#drawer-close").innerHTML = icon("x", 15);
  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#world-meter").addEventListener("click", () => openWorld());
  $("#journey-btn").innerHTML = `${icon("globe", 17)}<span class="label-text">내 세상 보기</span>`;
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
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (state.scene === "end") closeScene();
    else if (state.drawer) closeDrawer();
  });
}

async function start() {
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
    bindStage();
    $("#loading").hidden = true;
    // 바로 가기 주소 — ?mode=sky · ?mode=unfold&con=Q8860 · ?item=Q48469 · ?mode=map&journey=end · ?panel=catalog|explore|letter|mind|tonight (시연 · 공유용)
    const params = new URLSearchParams(location.search);
    const mode = ["map", "sky", "unfold"].includes(params.get("mode")) ? params.get("mode") : "sky";
    setMode(mode, params.get("con"), { journey: mode === "map" && !params.get("item") && params.get("journey") !== "end" });
    if (params.get("item")) selectItem(params.get("item"), { fly: true });
    else if (params.get("panel") === "catalog") showCatalog();
    else if (TOOL_OPEN[params.get("panel")]) TOOL_OPEN[params.get("panel")]();
    else if (mode === "sky" && prologueWanted(params)) startPrologue();
    else if (mode === "sky" && !params.has("mode")) showIntro();
    if (params.get("journey") === "end") {
      stage.camera.position.copy(state.map.edgeView());
      journeyEnd();
    }
  } catch (e) {
    $("#loading").textContent = `우주를 불러오지 못했습니다 — ${errorText(e)}`;
  }
}

if (new URLSearchParams(location.search).get("debug") === "1") {
  window.__vh = { state, world, selectItem, setMode, discover, openWorld, startJourney, resetWorld, showExplore, showPerspective, showSkyGuide, showCatalog, closeDrawer,
                  refreshSky, get stage() { return stage; } };
}

start();
