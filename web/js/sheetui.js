// 휴대폰 아래 시트 제어기 — 걸림 높이(peek · half · full)에 멈추는 서랍. 계산은 sheet.js, 여기서는 DOM만 다룬다 (Playwright로 확인).
//
// - 시트(.drawer)의 높이는 늘 full로 두고, 보이는 높이 V는 transform(--sheet-y = full - V)으로만 바꾼다. 끄는 동안 레이아웃을 다시 계산하지 않게
// - 본문(.drawer-body)의 높이(--sheet-body-h)는 끌기를 시작할 때 full로 늘리고, 정착한 뒤 V에 맞춘다.
//   정착한 뒤에는 스크롤 영역이 보이는 영역과 같아 scrollIntoView · 고정 입력창(.composer-wrap)이 그대로 동작한다
// - 끌기 입구는 둘: 손잡이 · 엿보기 머리글 · 본문 첫 블록(.head)의 포인터, 본문이 맨 위일 때 아래로 끄는 터치
//   (본문은 브라우저 스크롤을 쓰므로 포인터가 pointercancel로 끊긴다 — 터치 이벤트로 받는다)
// - 정착은 transitionend와 340ms 타이머 중 먼저 오는 쪽에서 한 번 (움직임 줄이기에서는 transitionend가 오지 않을 수 있다)

import { nextSnap, peekOpacity, rubberBand, snapHeights, stepSnap, velocityOf } from "./sheet.js";

const DRAG_SLOP = 8;                     // 손잡이 · 머리글 — 이만큼 세로로 움직여야 끌기 (그 전에 떼면 탭)
const BODY_SLOP = 6;                     // 본문 맨 위에서 아래로 — 이만큼 내려야 시트가 받는다
const SETTLE_MS = 340;
const HANDLES = ".sheet-grip, .sheet-peek, .drawer-body > .head";
const INPUTS = ".composer input, .composer textarea, .search-field input, textarea";

// onMove(V): 끄는 동안 rAF마다 · onSettle(snap, V): 정착 · 다시 맞춘 뒤 · onClose(): 아래로 내려 닫았다(서랍 닫기는 main.js)
// instant(): 움직임 줄이기 · home(): 이 화면의 기본 걸림 높이 · has3d(): 3D 오버레이가 있는 화면인가 (손잡이 이름 · 동작)
export function createSheet({ drawer, body, grip, peek, onMove, onSettle, onClose, instant = () => false, home = () => "half", has3d = () => false }) {
  const app = drawer.parentElement;
  let snap = "closed", visible = 0, snaps = { peek: 0, half: 0, full: 0 }, gripH = 0, safe = 0;
  let settleTimer = 0, onEnd = null, moving = false;
  let drag = null, raf = 0, suppressClick = false;
  let userSeq = 0;                               // 사람이 높이를 바꾼 횟수 (끌기 · 손잡이 · 입력창) — 늦게 정해지는 기본 높이가 그 높이를 덮지 않게
  const offs = [];
  const on = (el, type, fn, opts) => { el.addEventListener(type, fn, opts); offs.push(() => el.removeEventListener(type, fn, opts)); };

  // 걸림 높이 — 화면 높이 · 알림 띠 · 안전 영역 · 엿보기 머리글 높이로
  // 가상 키보드 — 키보드가 올라오면 레이아웃 뷰포트(app)는 그대로이고 보이는 뷰포트(visualViewport)만 줄어든다.
  // 걸림 높이는 보이는 높이로 계산하고, 키보드에 가린 아래쪽(kb)만큼 시트를 늘려 그 위에 시트가 놓이게 한다
  //   (--sheet-full = full + kb, 보이는 높이 V는 키보드 윗변부터 잰다 — 본문 · 입력창이 키보드 위에서 끝난다)
  const vv = window.visualViewport ?? null;
  let kb = 0;
  function measure() {
    const appH = app.clientHeight;
    const H = vv ? Math.min(appH, Math.round(vv.height)) : appH;
    kb = vv ? Math.max(0, Math.round(appH - vv.height - vv.offsetTop)) : 0;
    const noticeH = app.classList.contains("has-notice") ? parseFloat(getComputedStyle(app).getPropertyValue("--notice-h")) || 0 : 0;
    safe = parseFloat(getComputedStyle(drawer).paddingBottom) || 0;
    gripH = grip.offsetHeight;
    // 엿보기 머리글은 시트 아래끝까지 덮는 판이라(본문을 가린다) 안쪽 내용(.sheet-peek-in)의 높이로 잰다
    const inner = peek.hidden ? null : peek.querySelector(".sheet-peek-in");
    const peekContent = inner ? gripH + inner.offsetTop + inner.offsetHeight + (parseFloat(getComputedStyle(peek).paddingBottom) || 0) : null;
    snaps = snapHeights({ H, noticeH, safeBottom: safe, peekContent });
    drawer.style.setProperty("--sheet-full", `${snaps.full + kb}px`);
  }
  const resolve = (name) => (snaps[name] != null ? name : "full");   // 낮은 화면은 half가 없다
  const setBodyH = (V) => drawer.style.setProperty("--sheet-body-h", `${Math.max(0, Math.round(V - gripH - safe))}px`);

  function setPeekO(V) {
    const o = peekOpacity(V, snaps);
    drawer.style.setProperty("--peek-o", o.toFixed(3));
    const faded = o < 0.5;
    peek.classList.toggle("faded", faded);
    peek.setAttribute("aria-hidden", String(faded));
    // 옅어진 머리글은 읽기 · 포커스에서도 빠진다 — 안에 포커스가 있었으면 본문의 첫 포커스 가능 요소(없으면 손잡이)로
    if (faded && peek.contains(document.activeElement)) {
      const first = !body.inert && body.querySelector('a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select, [tabindex]:not([tabindex="-1"])');
      (first || grip).focus({ preventScroll: true });
    }
    peek.inert = faded;
  }

  // V에 놓는다 — animate가 아니면 전환 없이 바로
  function place(V, { animate }) {
    visible = V;
    if (!animate) drawer.classList.add("dragging");
    drawer.style.transform = "";
    drawer.style.setProperty("--sheet-y", `${Math.round(snaps.full - V)}px`);
    setPeekO(V);
    if (!animate) { void drawer.offsetHeight; drawer.classList.remove("dragging"); }
  }

  function syncState() {
    body.inert = snap === "peek";                      // peek에서 본문은 엿보기 머리글 아래에 가려진다 — 보이지 않는 곳으로 포커스가 가지 않게
    if (snap === "peek" && body.contains(document.activeElement)) grip.focus({ preventScroll: true });
    grip.setAttribute("aria-expanded", String(snap === "half" || snap === "full"));
    grip.setAttribute("aria-label", snap === "peek" ? "설명 더 보기" : has3d() ? "3D 크게 보기" : snap === "half" ? "설명 크게 보기" : "설명 줄이기");
  }

  function stopWaiting() {
    clearTimeout(settleTimer);
    if (onEnd) drawer.removeEventListener("transitionend", onEnd);
    onEnd = null;
    moving = false;
  }

  function settle() {
    stopWaiting();
    if (snap === "closed" || drag) return;
    setBodyH(visible);
    onSettle?.(snap, visible);
  }

  function waitSettle() {
    stopWaiting();
    moving = true;
    onEnd = (e) => { if (e.target === drawer && e.propertyName === "transform") settle(); };
    drawer.addEventListener("transitionend", onEnd);
    settleTimer = setTimeout(settle, SETTLE_MS);
  }

  // 그 걸림 높이로 — 닫힌 상태에서 열 때와, 열린 채 높이만 바꿀 때 모두
  function open(name, { animate = true } = {}) {
    if (drag) return;
    measure();
    const from = snap === "closed" ? 0 : visible;
    snap = resolve(name);
    const V = snaps[snap];
    if (snap !== "peek") body.inert = false;          // 머리글이 옅어질 때 그 안의 포커스를 본문으로 옮길 수 있게 먼저 푼다
    const anim = animate && !instant();
    setBodyH(Math.max(from, V));                       // 올라가는 동안 아래가 비지 않게 — 정착하면 V에 맞춘다
    place(V, { animate: anim });
    syncState();
    if (anim) waitSettle();
    else settle();
  }

  // 크기 · 알림 띠 · 엿보기 머리글이 바뀐 뒤 — 지금 상태 이름은 그대로, 새 높이로
  function relayout() {
    measure();
    if (snap === "closed" || drag) return;
    snap = resolve(snap);
    const V = snaps[snap];
    if (V === visible && !moving) { setBodyH(V); setPeekO(V); return; }
    place(V, { animate: moving && !instant() });       // 열리는 중이면 그 전환을 끊지 않는다
    syncState();
    if (!moving) settle();
  }

  function close() {
    stopWaiting();
    cancelAnimationFrame(raf);
    raf = 0;
    drag = null;
    snap = "closed";
    drawer.classList.remove("dragging");
    drawer.style.transform = "";
    body.inert = false;
    grip.setAttribute("aria-expanded", "false");
  }

  // ── 끌기 (포인터 · 터치 공통) ──
  function begin(y, t) {
    stopWaiting();
    drag = { y0: y, V0: visible, V: visible, samples: [{ t, y }] };
    drawer.classList.add("dragging");
    setBodyH(snaps.full);
  }
  function dragTo(y, t) {
    drag.samples.push({ t, y });
    if (drag.samples.length > 24) drag.samples.shift();
    drag.V = rubberBand(drag.V0 + (drag.y0 - y), snaps.peek, snaps.full);
    if (!raf) raf = requestAnimationFrame(frame);
  }
  function frame() {
    raf = 0;
    if (!drag) return;
    drawer.style.transform = `translate3d(0, ${Math.round(snaps.full - drag.V)}px, 0)`;
    setPeekO(drag.V);
    onMove?.(drag.V);
  }
  function finish() {
    const d = drag;
    drag = null;
    cancelAnimationFrame(raf);
    raf = 0;
    drawer.classList.remove("dragging");
    visible = d.V;
    suppressClick = true;                             // 끌고 놓은 자리의 버튼이 눌리지 않게
    setTimeout(() => { suppressClick = false; }, 0);
    userSeq++;
    const target = nextSnap({ from: snap, visible: d.V, velocity: velocityOf(d.samples), snaps });
    if (target === "closed") onClose?.();
    else open(target);
  }

  // 손잡이 · 엿보기 머리글 · 본문 첫 블록 — 포인터. 8px 세로로 움직이면 끌기, 가로가 먼저면 포기, 그 전에 떼면 탭(버튼 본래 동작)
  // 끌기를 시작할 때만 포인터를 붙잡는다 (누를 때 붙잡으면 안쪽 버튼의 click이 붙잡은 요소로 옮겨 간다)
  let track = null;
  on(drawer, "pointerdown", (e) => {
    if (snap === "closed" || track || drag || e.button > 0 || !e.target.closest(HANDLES)) return;
    if (e.target.closest("a, input, textarea, select")) return;
    track = { id: e.pointerId, x0: e.clientX, y0: e.clientY, t0: e.timeStamp, el: e.target.closest(HANDLES), drag: false };
  });
  on(window, "pointermove", (e) => {
    if (!track || e.pointerId !== track.id) return;
    const dx = e.clientX - track.x0, dy = e.clientY - track.y0;
    if (!track.drag) {
      if (Math.abs(dx) > DRAG_SLOP && Math.abs(dx) > Math.abs(dy)) { track = null; return; }
      if (Math.abs(dy) <= DRAG_SLOP) return;
      track.drag = true;
      begin(track.y0, track.t0);
      try { track.el.setPointerCapture(e.pointerId); } catch { /* 이미 떼었다 */ }
    }
    dragTo(e.clientY, e.timeStamp);
  });
  const pointerEnd = (e) => {
    if (!track || e.pointerId !== track.id) return;
    const t = track;
    track = null;
    if (t.drag && drag) finish();
  };
  on(window, "pointerup", pointerEnd);
  on(window, "pointercancel", pointerEnd);
  // 보이는 뷰포트가 바뀌면(키보드가 열리고 닫힘 · iOS가 입력창 쪽으로 화면을 옮김) 걸림 높이를 다시
  if (vv) {
    const onViewport = () => relayout();
    on(vv, "resize", onViewport);
    on(vv, "scroll", onViewport);
  }
  on(drawer, "click", (e) => { if (suppressClick) { e.preventDefault(); e.stopPropagation(); } }, true);

  // 본문 — 맨 위에서 아래로 끌 때만 시트가 받는다. 위로 끌기 · 맨 위가 아닐 때는 본문 스크롤
  let touch = null;
  on(body, "touchstart", (e) => {
    touch = null;
    if (snap === "closed" || snap === "peek" || drag || track || e.touches.length !== 1 || e.target.closest(HANDLES)) return;
    const p = e.touches[0];
    touch = { id: p.identifier, x0: p.clientX, y0: p.clientY, t0: e.timeStamp, top: body.scrollTop <= 0, drag: false };
  }, { passive: true });
  on(body, "touchmove", (e) => {
    if (!touch) return;
    const p = [...e.changedTouches].find((x) => x.identifier === touch.id);
    if (!p) return;
    if (!touch.drag) {
      const dx = p.clientX - touch.x0, dy = p.clientY - touch.y0;
      if (!touch.top || body.scrollTop > 0 || (dy < 0 && -dy > BODY_SLOP) || (Math.abs(dx) > BODY_SLOP && Math.abs(dx) > Math.abs(dy))) { touch = null; return; }
      if (dy < BODY_SLOP) return;
      touch.drag = true;
      begin(touch.y0, touch.t0);
    }
    if (e.cancelable) e.preventDefault();
    dragTo(p.clientY, e.timeStamp);
  }, { passive: false });
  const touchEnd = (e) => {
    if (!touch || ![...e.changedTouches].some((x) => x.identifier === touch.id)) return;
    const t = touch;
    touch = null;
    if (t.drag && drag) finish();
  };
  on(body, "touchend", touchEnd);
  on(body, "touchcancel", touchEnd);

  // 손잡이 — 누르면(Enter · Space) 한 칸 올리고 full에서는 기본 높이로. 3D가 있으면 half · full에서 3D가 크게 보이는 기본 높이로.
  // 위 · 아래 화살표는 한 칸씩 (아래로는 peek까지 — 닫기는 닫기 단추와 Escape가 맡는다)
  on(grip, "click", () => {
    if (snap === "closed") return;
    userSeq++;
    if (has3d() ? snap !== "peek" : snap === "full") open(home());
    else open(stepSnap(snap, 1, snaps));
  });
  on(grip, "keydown", (e) => {
    if (snap === "closed" || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    e.preventDefault();
    userSeq++;
    open(stepSnap(snap, e.key === "ArrowUp" ? 1 : -1, snaps));
  });

  // 입력창에 사람이 들어오면(누르기 · Tab) full로 — 가상 키보드가 올라와도 입력창이 화면 밖에 남지 않게.
  // 화면을 열 때 스크립트가 옮긴 포커스(천체 목록의 검색창 등)로는 올리지 않는다
  let lastPointer = { t: -Infinity, inBody: false }, lastTab = -Infinity;
  on(document, "pointerdown", (e) => { lastPointer = { t: e.timeStamp, inBody: body.contains(e.target) }; }, true);
  on(document, "keydown", (e) => { if (e.key === "Tab") lastTab = e.timeStamp; }, true);
  on(body, "focusin", (e) => {
    if (snap === "closed" || snap === "full" || drag || !e.target.matches?.(INPUTS)) return;
    const now = performance.now();
    if ((lastPointer.inBody && now - lastPointer.t < 1000) || now - lastTab < 1000) { userSeq++; open("full"); }
  });

  return {
    get snap() { return snap; },
    get visible() { return visible; },
    get snaps() { return snaps; },
    get dragging() { return !!drag; },
    get userSeq() { return userSeq; },
    open, relayout, close,
    // 시트 배치를 벗어날 때 — 인라인 스타일 · 리스너를 모두 걷어 데스크톱 CSS가 그대로 걸리게
    destroy() {
      close();
      for (const off of offs) off();
      for (const v of ["--sheet-full", "--sheet-y", "--sheet-body-h", "--peek-o"]) drawer.style.removeProperty(v);
      drawer.style.transform = "";
      peek.hidden = true;
      peek.innerHTML = "";
      peek.removeAttribute("aria-hidden");
      peek.inert = false;
      peek.classList.remove("faded");
    },
  };
}
