// 하늘 가리키기 화면 — 휴대폰을 하늘로 들어 올리면 담은 빛 쪽으로 안내하고, 맞추면 그 빛이 떠난 때를 알려 준다.
// 계산은 pointer.js(순수 모듈), 이 파일은 전체 화면 오버레이 · 센서 · 그리기만. 설계: 하늘 가리키기 4장
//
// - 층: 토스트(5) · 장면(7) · 담기 빛무리(40)보다 위, 프롤로그(50)보다 아래인 45. index.html은 고치지 않고 JS로 만든다
// - 센서: deviceorientationabsolute(Android Chrome, 북쪽 기준 α)를 먼저, 없으면 deviceorientation.
//   iOS는 α가 시작 기준이라 webkitCompassHeading으로 기준점을 천천히 따라간다 (시상수 2초)
// - 방위 보정: 나침반은 자북 기준이라 한국 · 일본 주변은 자기 편각(pointer.declinationDeg)을 더한다. "나침반 맞추기"가 남은 오차를 한 번에 줄인다
//   (보정값은 기기 · 장소마다 달라 sessionStorage "vh-compass-offset"에만)
// - 센서가 없거나(1.5초 안에 값이 없음) 권한을 거부하면 글 안내("남서쪽, 주먹 4개 높이")로
// - 열린 동안 무대(3D)는 멈추고(main.js onOpen · onClose), 탭이 숨으면 센서 · 그리기 · 화면 꺼짐 방지를 거둔다

import { altAz, compass, localSiderealDeg } from "./astro.js";
import { BODIES, solarSystem } from "./ephemeris.js";
import { josa } from "./facts.js";
import { ALIGN_DWELL_MS, ALIGN_ENTER, alignStep, alphaFromCompass, altAzToEnu, azDelta, compassSource, declinationDeg, deviceBasis, enuToAltAz,
         followOffset, guide, guideText, lightLine, lookText, moonLitAngle, moonLitPath, rotateAz, screenBasis, smoothBasis, VFOV } from "./pointer.js";
import { starColor } from "./skydata.js";
import { bodyInfo } from "./solarbodies.js";
import { sound } from "./sound.js";

const DEG = Math.PI / 180;
const NO_SENSOR_MS = 1500;
const COMPASS_TAU_MS = 2000;
const SKY_REFRESH_MS = 5000;
const TEXT_REFRESH_MS = 30_000;
const STAR_MAG = 4.5;                      // 근처 밝은 별 — 밝은 별 묶음에서 4.5등급까지 (약 920개)
// 기준점 — 야외에서 먼저 눈에 들어오는 달과 맨눈 행성. 천왕성 · 해왕성 · 태양은 그리지 않는다
const LANDMARKS = ["moon", "mercury", "venus", "mars", "jupiter", "saturn"];
const LANDMARK_MIN_ALT = -2;
const MOON_MIN_R = 9;                      // 실제 시반지름(0.25°)은 몇 px뿐 — 지름 18px 이상으로
const PLANET_R = 4.5;                      // 별(최대 3.5px)보다 크게, 깜빡임 없이
const PLANET_COLOR = "#fff1dc";            // BODIES에 색이 없어 살짝 따뜻한 흰색
const BODY_BY_NAME = new Map(Object.entries(BODIES).map(([key, b]) => [b.name, key]));
const OFFSET_KEY = "vh-compass-offset";
// 출처별 자기 편각 보정 — iOS webkitCompassHeading은 자북 기준. Android Chrome의 절대 α도 자기장 센서 기반이라 자북으로 본다
// (실기기 확인 전 가정 — 진북 기준으로 확인되면 absolute를 false로)
const DECLINATION_FOR = { ios: true, absolute: true };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const mod360 = (x) => ((x % 360) + 360) % 360;
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

// 휴대폰인가 — 데스크톱 Chrome에도 DeviceOrientationEvent가 있어 굵은 포인터(터치)를 함께 본다
export const isHandheld = () => matchMedia("(pointer: coarse)").matches && "DeviceOrientationEvent" in window;

// iOS 13+ — 사용자 제스처 안의 첫 비동기 호출이어야 대화 상자가 뜬다. 다른 브라우저는 묻지 않는다
export function requestOrientation() {
  const DOE = window.DeviceOrientationEvent;
  if (typeof DOE?.requestPermission !== "function") return Promise.resolve("granted");
  try { return DOE.requestPermission().catch(() => "denied"); } catch { return Promise.resolve("denied"); }
}

// 방위 원판 — 북쪽이 위, 목표 방위로 화살표, 오른쪽에 고도 호와 점 (글 안내 · 데스크톱 카드)
export function dialSvg(alt, az) {
  const a = (mod360(az) - 90) * DEG, x = 50 + 34 * Math.cos(a), y = 50 + 34 * Math.sin(a);
  const h = Math.max(0, Math.min(90, alt)) * DEG, hx = 112 + 38 * Math.cos(h), hy = 88 - 38 * Math.sin(h);
  return `<svg class="pt-dial" viewBox="0 0 160 100" width="160" height="100" aria-hidden="true">
    <circle cx="50" cy="50" r="40" fill="none" stroke="currentColor" stroke-opacity=".35"/>
    <text x="50" y="7" text-anchor="middle">북</text><text x="96" y="54" text-anchor="middle">동</text>
    <text x="50" y="99" text-anchor="middle">남</text><text x="4" y="54" text-anchor="middle">서</text>
    <line x1="50" y1="50" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
    <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" class="pt-dial-target"/>
    <path d="M112 88 H154 M112 88 V46 M150 88 A38 38 0 0 0 112 50" fill="none" stroke="currentColor" stroke-opacity=".35"/>
    <line x1="112" y1="88" x2="${hx.toFixed(1)}" y2="${hy.toFixed(1)}" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    <circle cx="${hx.toFixed(1)}" cy="${hy.toFixed(1)}" r="4" class="pt-dial-target"/>
  </svg>`;
}

// 데스크톱 — "휴대폰에서 가리키기" 카드: 링크 복사 · 글 안내. QR은 넣지 않는다
export function phoneCardHtml({ link, pos, when }) {
  return `<div class="pt-phone-card">
    <p class="pt-phone-lead">휴대폰에서 이 링크를 열고 "하늘 가리키기"를 누르면, 휴대폰을 들어 올린 쪽으로 안내해 드려요.</p>
    <div class="pt-phone-link"><input type="text" readonly value="${esc(link)}" aria-label="휴대폰에서 열 링크">
      <button type="button" class="btn btn-secondary btn-sm" data-copy-point>링크 복사</button></div>
    <p class="pt-phone-note">기록은 기기마다 따로 남아요.</p>
    ${pos ? `<div class="pt-text-row">${dialSvg(pos.alt, pos.az)}<div><p class="pt-text-line">${esc(lookText(pos.alt, pos.az))}</p>
      ${when ? `<p class="pt-text-when">${esc(when)}</p>` : ""}</div></div>` : ""}
  </div>`;
}

export function bindPhoneCard(el, link, onCopied) {
  el.querySelector("[data-copy-point]")?.addEventListener("click", async () => {
    const input = el.querySelector("input");
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard");
      await navigator.clipboard.writeText(link);
      onCopied?.();
    } catch {
      input.focus({ preventScroll: true });
      input.select();
    }
  });
}

// 가리키기 시작 — 클릭 핸들러에서 곧바로 부른다 (권한 요청이 이 함수의 첫 비동기 호출)
//   o: { id, name, positionAt(date, place) → { alt, az, distanceKm? } | null, km, place, placeLabel(place), locate() → Promise<place|null>,
//        observed(), stars({ count, hip, ra, dec, mag, bv } | null), when, seenToday(), onSeen(), onOther(), onOpen(), onClose(), opener, reducedMotion }
export function startPointer(o) {
  const permission = requestOrientation();
  const view = mountPointer(o);
  permission.then((p) => {
    if (!view.alive()) return;
    if (p === "granted") view.listen();
    else view.textMode("denied");
    // 위치는 제스처가 필요 없어 권한 요청 뒤에 — 받지 못하면 지금 위치(기본 서울)로 계속
    o.locate?.().then((place) => { if (place && view.alive()) view.setPlace(place); }).catch(() => {});
  });
  return view;
}

function mountPointer(o) {
  const root = document.createElement("div");
  root.className = "pointer";
  root.setAttribute("role", "dialog");
  root.setAttribute("aria-modal", "true");
  root.setAttribute("aria-label", `하늘 가리키기: ${o.name}`);
  root.innerHTML = `
    <canvas class="pt-sky" aria-hidden="true"></canvas>
    <div class="pt-reticle" aria-hidden="true"></div>
    <div class="pt-arrow" aria-hidden="true" hidden><svg viewBox="0 0 24 24" width="34" height="34"><path d="M5 12h13M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    <header class="pt-head">
      <p class="pt-name">${esc(o.name)}</p>
      <p class="pt-meta"></p>
      <p class="pt-place"></p>
    </header>
    <p class="pt-hint" aria-live="polite">휴대폰을 하늘로 들어 올려 주세요</p>
    <section class="pt-text" hidden>
      <div class="pt-text-row"><span class="pt-text-dial"></span><div><p class="pt-text-line"></p><p class="pt-text-when"></p></div></div>
      <p class="pt-text-note"></p>
    </section>
    <section class="pt-calib" hidden>
      <p class="pt-calib-line"></p>
      <div class="pt-calib-actions"><button type="button" class="primary-button" data-calib-done>맞췄어요</button>
        <button type="button" class="quiet-link" data-calib-cancel>그만두기</button></div>
    </section>
    <section class="pt-found" hidden aria-live="assertive">
      <p class="pt-found-name">${esc(o.name)}</p>
      <p class="pt-found-line"></p>
      <div class="pt-found-actions"><button type="button" class="primary-button" data-seen></button>
        <button type="button" class="quiet-link" data-other>다른 빛 가리키기</button></div>
    </section>
    <footer class="pt-foot">
      <span class="pt-acc"></span>
      <button type="button" class="quiet-link" data-calibrate>나침반 맞추기</button>
      <button type="button" class="quiet-link" data-close>끝내기</button>
    </footer>`;
  document.body.appendChild(root);
  const $ = (sel) => root.querySelector(sel);
  const canvas = $(".pt-sky"), ctx = canvas.getContext("2d");

  let open = true, mode = "wait";              // wait(센서 기다림) · sensor · text
  let place = o.place, basis = null, lastStamp = 0, received = false, gotAbsolute = false, foundShown = false;
  let source = null, accuracy = null, iosOffset = null;
  let userOffset = 0, calibrated = false, calibRef = null;
  try { const v = Number(sessionStorage.getItem(OFFSET_KEY)); if (Number.isFinite(v) && sessionStorage.getItem(OFFSET_KEY) != null) { userOffset = v; calibrated = true; } } catch { /* 무시 */ }
  let target = null, targetEnu = null, stars = [], landmarks = [], sunEnu = null, align = null, found = false;
  // 목표가 달 · 행성인가 — 항목 ID(위키데이터)로, 없으면 이름으로 (tonight.targetsOf와 같은 규칙). 위성(이오 등)은 해당 없음
  const targetBody = (() => {
    const info = bodyInfo(o.id);
    const key = info?.planet ? info.key : BODY_BY_NAME.get(o.name);
    return LANDMARKS.includes(key) ? key : null;
  })();
  let raf = 0, dwellTimer = 0, textWhy = null, dirty = true, noSensorTimer = 0, skyTimer = 0, textTimer = 0, wakeLock = null, listening = false;
  let W = 0, H = 0, F = 1;

  o.onOpen?.();
  history.pushState({ vhPointer: true }, "");

  // ── 하늘 (5초마다 지방 항성시 · 목표 위치를 다시) ──
  const refreshSky = () => {
    const now = new Date();
    const lst = localSiderealDeg(now, place.lon);
    target = o.positionAt(now, place);
    targetEnu = target ? altAzToEnu(target.alt, target.az) : null;
    const s = o.stars;
    stars = [];
    if (s) {
      for (let i = 0; i < s.count; i++) {
        if (s.mag[i] > STAR_MAG) continue;
        const p = altAz(s.ra[i], s.dec[i], place.lat, lst);
        if (p.alt < -5) continue;
        const [r, g, b] = starColor(s.bv[i]).map((c) => Math.round(c * 255));      // skydata는 0~1 배열 — 캔버스 색 문자열로
        stars.push({ v: altAzToEnu(p.alt, p.az), mag: s.mag[i], color: `rgb(${r},${g},${b})` });
      }
    }
    // 기준점 — 달(위상 · 시반지름)과 맨눈 행성. 태양은 달의 밝은 쪽을 정하는 데만
    landmarks = [];
    sunEnu = null;
    for (const b of solarSystem(now)) {
      const p = altAz(b.ra, b.dec, place.lat, lst);
      if (b.key === "sun") { sunEnu = altAzToEnu(p.alt, p.az); continue; }
      if (!LANDMARKS.includes(b.key) || p.alt < LANDMARK_MIN_ALT) continue;
      landmarks.push({ key: b.key, name: b.name, v: altAzToEnu(p.alt, p.az), illum: b.illum, angR: b.angularRadiusDeg });
    }
    $(".pt-place").textContent = o.placeLabel?.(place) ?? "";
    dirty = true;
  };

  const resize = () => {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    W = root.clientWidth; H = root.clientHeight;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    canvas.style.width = `${W}px`; canvas.style.height = `${H}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    F = (H / 2) / Math.tan((VFOV / 2) * DEG);
    const r = F * Math.tan(ALIGN_ENTER * DEG);
    const ret = $(".pt-reticle");
    ret.style.width = ret.style.height = `${Math.round(r * 2)}px`;
    dirty = true;
  };

  // ── 그리기 — 센서 값은 이벤트에서 저장만, 그리기는 rAF에서 바뀌었을 때만 ──
  const projectRaw = (v) => {
    const z = dot(v, basis.forward);
    if (z <= 0.05) return null;
    return { x: W / 2 + (dot(v, basis.right) / z) * F, y: H / 2 - (dot(v, basis.up) / z) * F };
  };
  const draw = () => {
    ctx.fillStyle = "#05060f";
    ctx.fillRect(0, 0, W, H);
    if (!basis) return;
    const cosLimit = Math.cos(Math.atan(Math.hypot(W, H) / 2 / F));
    for (const s of stars) {
      if (dot(s.v, basis.forward) < cosLimit) continue;
      const p = projectRaw(s.v);
      if (!p) continue;
      const r = Math.max(1, Math.min(3.5, 3.5 - (s.mag + 1) * 0.5));
      ctx.fillStyle = s.color;
      ctx.globalAlpha = 0.85;
      ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1;
    // 지평선 — 고도 0° 원을 같은 투영으로
    ctx.strokeStyle = "rgba(242,207,140,.35)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    let pen = false;
    for (let az = 0; az <= 360; az += 3) {
      const p = projectRaw(altAzToEnu(0, az));
      if (!p) { pen = false; continue; }
      if (pen) ctx.lineTo(p.x, p.y); else ctx.moveTo(p.x, p.y);
      pen = true;
    }
    ctx.stroke();
    // 기준점 — 달 · 행성. 목표와 같은 천체는 목표 표식에서 한 번만 그린다
    const near = (p, m) => p && p.x > -m && p.x < W + m && p.y > -m && p.y < H + m;
    for (const b of landmarks) {
      if (b.key === targetBody) continue;
      const p = projectRaw(b.v);
      if (b.key === "moon") {
        const r = moonRadius(b);
        if (!near(p, r * 2.5)) continue;
        drawMoon(p, b, r);
        ctx.font = "14px sans-serif"; ctx.fillStyle = "rgba(255,250,245,.8)";
        ctx.fillText(b.name, p.x + r + 7, p.y + 5);
      } else {
        if (!near(p, 20)) continue;
        drawPlanet(p);
        ctx.font = "11px sans-serif"; ctx.fillStyle = "rgba(255,250,245,.6)";
        ctx.fillText(b.name, p.x + PLANET_R + 5, p.y + 4);
      }
    }
    // 목표 — 살구색 표식. 달이면 위상 원반을, 행성이면 행성 점을 고리가 감싼다
    if (targetEnu) {
      const p = projectRaw(targetEnu);
      const body = targetBody && landmarks.find((b) => b.key === targetBody);
      const ringR = body?.key === "moon" ? moonRadius(body) + 6 : 13;
      if (near(p, Math.max(40, ringR * 2.5))) {
        if (body?.key === "moon") drawMoon(p, body, ringR - 6);
        else if (body) drawPlanet(p);
        ctx.strokeStyle = "#f3dad5"; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(p.x, p.y, ringR, 0, Math.PI * 2); ctx.stroke();
        if (!body) {
          ctx.fillStyle = "#f3dad5";
          ctx.beginPath(); ctx.arc(p.x, p.y, 3.5, 0, Math.PI * 2); ctx.fill();
        }
        ctx.font = body?.key === "moon" ? "14px sans-serif" : "13px sans-serif"; ctx.fillStyle = "rgba(255,250,245,.75)";
        ctx.fillText(o.name, p.x + ringR + 5, p.y + 4);
      }
    }
  };
  // 달 — 시반지름을 화면 px로 (지름 18px 이상)
  const moonRadius = (b) => Math.max(MOON_MIN_R, F * Math.tan(b.angR * DEG));
  // 달 원반 — 빛무리 · 어두운 원 · 태양 쪽 밝은 부분 (위상은 pointer.moonLitPath)
  const drawMoon = (p, b, r) => {
    const halo = ctx.createRadialGradient(p.x, p.y, r * 0.8, p.x, p.y, r * 2.5);
    halo.addColorStop(0, `rgba(244,239,226,${(0.08 + 0.14 * b.illum).toFixed(3)})`);
    halo.addColorStop(1, "rgba(244,239,226,0)");
    ctx.fillStyle = halo;
    ctx.beginPath(); ctx.arc(p.x, p.y, r * 2.5, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#2b2d3a";
    ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill();
    if (b.illum <= 0.005) return;
    const angle = moonLitAngle({ moonPx: p, sunPx: sunEnu ? projectRaw(sunEnu) : null, basis, moonEnu: b.v, sunEnu: sunEnu ?? b.v });
    const pts = moonLitPath(b.illum, angle, r, 32);
    ctx.fillStyle = "#f4efe2";
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(p.x + x, p.y + y) : ctx.moveTo(p.x + x, p.y + y)));
    ctx.closePath(); ctx.fill();
  };
  const drawPlanet = (p) => {
    ctx.fillStyle = PLANET_COLOR;
    ctx.beginPath(); ctx.arc(p.x, p.y, PLANET_R, 0, Math.PI * 2); ctx.fill();
  };

  const azKnown = () => source === "ios" || source === "absolute" || calibrated;
  const setHint = (text) => { const h = $(".pt-hint"); if (h.textContent !== text) h.textContent = text; };

  const updateGuide = () => {
    if (!basis || !targetEnu) {
      if (!targetEnu && mode === "sensor") setHint("이 빛의 지금 위치를 계산하지 못했어요");
      return;
    }
    const now = enuToAltAz(basis.forward);
    const g = guide(basis, targetEnu);
    const known = azKnown();
    const dAlt = target.alt - now.alt;
    $(".pt-meta").textContent = `${compass(target.az)}쪽 · 고도 ${Math.round(target.alt)}°${known ? ` · 목표까지 ${Math.round(g.sep)}°` : ""}`;
    // 화살표 — 목표 쪽 화면 가장자리. 방위 기준이 없으면 위 · 아래로만
    const arrow = $(".pt-arrow");
    const angle = known ? g.angle : (dAlt >= 0 ? 90 : -90);
    const show = known ? g.sep > ALIGN_ENTER : Math.abs(dAlt) > ALIGN_ENTER;
    arrow.hidden = !show;
    if (show) {
      const R = Math.min(W, H) * 0.36;
      const x = W / 2 + R * Math.cos(angle * DEG), y = H / 2 - R * Math.sin(angle * DEG);
      arrow.style.transform = `translate(${x - 17}px, ${y - 17}px) rotate(${-angle}deg)`;
    }
    if (calibRef) return;                       // 나침반 맞추기 중에는 그 안내를 둔다
    if (target.alt < 0) setHint(`지금은 지평선 아래에 있어요 · ${known ? guideText(azDelta(target.az, now.az), 0) : "땅 아래 방향이에요"}`);
    else if (!known) setHint(`${guideText(0, dAlt)} · 방위는 "나침반 맞추기"로 기준을 잡아 주세요`);
    else if (now.alt > 75) setHint("화살표 쪽으로 휴대폰을 기울여 보세요");
    else setHint(guideText(azDelta(target.az, now.az), dAlt));
    // 정렬 — 지평선 위에 있고 방위 기준이 있을 때만
    const was = align?.phase ?? "far";
    align = alignStep(align, known && target.alt >= 0 ? g.sep : Infinity, performance.now());
    if (align.phase === "far" && was !== "far") hideFound();     // 멀어지면 발견 카드를 거두고, 다시 맞추면 다시
    root.classList.toggle("near", align.phase !== "far");
    root.classList.toggle("aligned", align.phase === "aligned");
    if (align.fired) onAligned();
    // 머무름 판정 — 손이 멈춰 센서 이벤트가 뜸해도 500ms 뒤에 한 번 더 본다
    if (align.phase === "near") { clearTimeout(dwellTimer); dwellTimer = setTimeout(kick, ALIGN_DWELL_MS + 30); }
  };

  const frame = () => {
    raf = 0;
    if (!open) return;
    if (dirty) {
      dirty = false;
      draw();
      updateGuide();
    }
  };
  const kick = () => { dirty = true; if (!raf && open) raf = requestAnimationFrame(frame); };

  // 정렬 연출 — 정렬될 때마다 (alignStep이 far로 돌아간 뒤에만 다시 fired). 처음 한 번만 기록 단추로 포커스
  const drawSeen = () => {
    const b = $("[data-seen]");
    const done = o.seenToday?.();
    b.textContent = done ? "오늘 봤다고 남겼어요 ✓" : o.observed?.() === false ? "담고, 두 눈으로 봤다고 남기기" : "오늘 두 눈으로 봤어요";
    b.disabled = !!done;
  };
  function hideFound() {
    if (!foundShown) return;
    foundShown = false;
    const sec = $(".pt-found");
    if (sec.contains(document.activeElement)) $("[data-close]").focus({ preventScroll: true });   // 사라질 단추에 있던 포커스는 끝내기로
    sec.hidden = true;
  }
  function onAligned() {
    const km = target?.distanceKm ?? o.km;
    $(".pt-found-line").textContent = lightLine(km);
    drawSeen();
    const sec = $(".pt-found");
    sec.hidden = !!calibRef;                       // 나침반 맞추기 중이면 끝난 뒤에 보인다
    foundShown = true;
    if (!o.reducedMotion) { sec.classList.remove("rise"); void sec.offsetWidth; sec.classList.add("rise"); }
    if (!found) $("[data-seen]").focus({ preventScroll: true });
    found = true;
    sound.sparkle();
    navigator.vibrate?.([30, 40, 30]);
  }

  // ── 센서 ──
  const screenAngle = () => screen.orientation?.angle ?? (typeof window.orientation === "number" ? window.orientation : 0);
  const onOrientation = (e) => {
    if (e.alpha == null || e.beta == null || e.gamma == null) return;
    const src = compassSource(e);
    if (src.kind === "absolute") gotAbsolute = true;
    else if (gotAbsolute) return;                 // 절대 방위가 오면 상대 이벤트는 쓰지 않는다
    const stamp = e.timeStamp || performance.now();
    const dt = lastStamp ? Math.max(0, stamp - lastStamp) : 0;
    lastStamp = stamp;
    if (!received) { received = true; clearTimeout(noSensorTimer); if (mode !== "text") setSensorMode(); }
    let corr = 0;
    if (src.kind === "ios") {
      iosOffset = followOffset(iosOffset, mod360(e.alpha - alphaFromCompass(src.heading)), dt, COMPASS_TAU_MS);
      corr = iosOffset;
    }
    const decl = DECLINATION_FOR[src.kind] ? declinationDeg(place.lat, place.lon) : null;
    corr += (decl ?? 0) + (src.kind === "relative" && !calibrated ? 0 : userOffset);
    if (source !== src.kind || accuracy !== src.accuracy) {
      source = src.kind; accuracy = src.accuracy;
      const noDecl = DECLINATION_FOR[src.kind] && decl == null;
      $(".pt-acc").textContent = source === "relative" ? (calibrated ? "맞춘 방위 기준" : "방위 기준 없음")
        : `${accuracy != null ? `나침반 ±${Math.round(accuracy)}°` : "나침반"}${noDecl ? " · 방위가 몇 도 어긋날 수 있어요. 달이나 밝은 별로 맞춰 주세요" : ""}`;
    }
    const next = rotateAz(screenBasis(deviceBasis(e.alpha, e.beta, e.gamma), screenAngle()), corr);
    basis = smoothBasis(basis, next, dt);
    kick();
  };

  const events = ["deviceorientationabsolute", "deviceorientation"];
  const listen = () => {
    if (listening || mode === "text") return;
    listening = true;
    for (const ev of events) window.addEventListener(ev, onOrientation);
    if (!received) {
      clearTimeout(noSensorTimer);
      noSensorTimer = setTimeout(() => { if (!received && open) textMode("nosensor"); }, NO_SENSOR_MS);
    }
    navigator.wakeLock?.request?.("screen").then((l) => { if (open) wakeLock = l; else l.release(); }).catch(() => {});
  };
  const unlisten = () => {
    listening = false;
    for (const ev of events) window.removeEventListener(ev, onOrientation);
    clearTimeout(noSensorTimer);
    clearTimeout(dwellTimer);
    cancelAnimationFrame(raf); raf = 0;
    wakeLock?.release?.().catch?.(() => {});
    wakeLock = null;
  };

  function setSensorMode() {
    mode = "sensor";
    root.classList.add("sensor");
    kick();
  }

  // ── 글 안내 — 센서가 없거나 권한을 거부했을 때 (30초마다 다시) ──
  function textMode(why) {
    if (!open) return;
    unlisten();
    mode = "text";
    textWhy = why;
    root.classList.remove("sensor", "near", "aligned");
    root.classList.add("text-mode");
    $(".pt-text").hidden = false;
    $(".pt-arrow").hidden = true;
    $("[data-calibrate]").hidden = true;
    $(".pt-text-note").textContent = why === "denied"
      ? "동작 및 방향 접근이 허용되지 않아 글로 안내합니다. 설정에서 이 사이트의 동작 및 방향 접근을 허용해 주세요."
      : "이 기기에서는 방향 센서를 쓸 수 없어 글로 안내합니다.";
    setHint("");
    const drawText = () => {
      refreshSky();
      if (!target) { $(".pt-text-line").textContent = "이 빛의 지금 위치를 계산하지 못했어요."; return; }
      $(".pt-text-dial").innerHTML = dialSvg(target.alt, target.az);
      $(".pt-text-line").textContent = lookText(target.alt, target.az);
      $(".pt-text-when").textContent = o.when ?? "";
      $(".pt-meta").textContent = `${compass(target.az)}쪽 · 고도 ${Math.round(target.alt)}°`;
    };
    drawText();
    clearInterval(textTimer);
    textTimer = setInterval(drawText, TEXT_REFRESH_MS);
  }

  // ── 나침반 맞추기 — 지금 떠 있는 가장 밝은 천체(달 → 행성 → 목표)를 가운데에 두고 누른다 ──
  const reference = () => {
    const now = new Date(), lst = localSiderealDeg(now, place.lon);
    const bodies = solarSystem(now).filter((b) => b.key !== "sun")
      .map((b) => ({ name: b.name, mag: BODIES[b.key].mag, ...altAz(b.ra, b.dec, place.lat, lst) }))
      .filter((b) => b.alt >= 10 && b.mag <= 1).sort((a, b) => a.mag - b.mag);
    if (bodies[0]) return bodies[0];
    return target && target.alt >= 10 ? { name: o.name, alt: target.alt, az: target.az } : null;
  };
  const startCalib = () => {
    const ref = reference();
    if (!ref) { setHint("지금 맞출 밝은 빛이 지평선 위에 없어요"); return; }
    calibRef = ref;
    $(".pt-calib-line").textContent = `${ref.name}${josa(ref.name, "을", "를")} 화면 가운데 원 안에 두고 "맞췄어요"를 눌러 주세요 · ${compass(ref.az)}쪽 고도 ${Math.round(ref.alt)}°`;
    $(".pt-calib").hidden = false;
    $(".pt-found").hidden = true;                  // 같은 자리 — 맞추는 동안은 맞추기 안내만
    $("[data-calib-done]").focus({ preventScroll: true });
  };
  const endCalib = (apply) => {
    if (apply && basis && calibRef) {
      const now = enuToAltAz(basis.forward);
      userOffset = mod360(userOffset + azDelta(calibRef.az, now.az) + 180) - 180;
      basis = rotateAz(basis, azDelta(calibRef.az, now.az));
      calibrated = true;
      try { sessionStorage.setItem(OFFSET_KEY, String(userOffset)); } catch { /* 무시 */ }
      source = null;                               // 표시줄을 다시
      align = null;
    }
    calibRef = null;
    $(".pt-calib").hidden = true;
    $(".pt-found").hidden = !foundShown;
    kick();
  };

  // ── 닫기 · 포커스 · 탭 숨김 ──
  const focusables = () => [...root.querySelectorAll("button:not([hidden]):not(:disabled)")].filter((b) => b.offsetParent !== null);
  // Esc — 창 단계(capture)에서 먼저 받아 멈춘다. 뒤의 서랍(main.js의 Esc 닫기)이 함께 닫히지 않게
  const onEsc = (e) => {
    if (e.key !== "Escape") return;
    e.preventDefault();
    e.stopPropagation();
    close();
  };
  const onKey = (e) => {
    if (e.key !== "Tab") return;
    const list = focusables();
    if (!list.length) return;
    const i = list.indexOf(document.activeElement);
    if (e.shiftKey && (i <= 0)) { e.preventDefault(); list[list.length - 1].focus(); }
    else if (!e.shiftKey && i === list.length - 1) { e.preventDefault(); list[0].focus(); }
  };
  const onPop = () => close({ fromPop: true });
  const onVisible = () => {
    if (!open) return;
    if (document.hidden) { if (mode !== "text") unlisten(); }
    else if (mode !== "text") {
      received = false;                             // 돌아온 뒤 1.5초 안에 센서 값이 없으면 글 안내로
      lastStamp = 0;
      listen();
      kick();
    }
  };
  function close({ fromPop = false } = {}) {
    if (!open) return;
    open = false;
    unlisten();
    clearInterval(skyTimer); clearInterval(textTimer);
    window.removeEventListener("popstate", onPop);
    window.removeEventListener("keydown", onEsc, true);
    window.removeEventListener("resize", resize);
    document.removeEventListener("visibilitychange", onVisible);
    root.remove();
    if (!fromPop && history.state?.vhPointer) history.back();
    o.onClose?.();
    if (o.opener?.isConnected) o.opener.focus({ preventScroll: true });
  }

  root.addEventListener("keydown", onKey);
  root.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.hasAttribute("data-close")) close();
    else if (b.hasAttribute("data-calibrate")) startCalib();
    else if (b.hasAttribute("data-calib-done")) endCalib(true);
    else if (b.hasAttribute("data-calib-cancel")) endCalib(false);
    else if (b.hasAttribute("data-seen")) { o.onSeen?.(); drawSeen(); }
    else if (b.hasAttribute("data-other")) { close(); o.onOther?.(); }
  });
  window.addEventListener("popstate", onPop);
  window.addEventListener("keydown", onEsc, true);
  window.addEventListener("resize", resize);
  document.addEventListener("visibilitychange", onVisible);

  resize();
  refreshSky();
  skyTimer = setInterval(() => { if (mode !== "text") refreshSky(); kick(); }, SKY_REFRESH_MS);
  draw();
  $("[data-close]").focus({ preventScroll: true });

  return {
    alive: () => open,
    listen,
    textMode,
    close,
    setPlace(p) { place = p; refreshSky(); if (mode === "text") textMode(textWhy); kick(); },
    get state() { return { mode, source, align: align?.phase ?? "far", found, calibrated }; },
  };
}
