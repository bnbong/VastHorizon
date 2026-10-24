// 3D 무대 — 렌더러 · 카메라 · 조작 · 이름표 · 선택(피킹). 보기 모드(우주 지도 · 천구 · 펼치기)를 갈아 끼운다.
//
// 모드 객체 규약
//   group                 : THREE.Group — 무대에 붙였다 뗀다
//   enter(stage)          : 카메라 · 조작 설정
//   exit()                : (선택) 정리
//   pickables()           : [{ position: Vector3, data, pickRadius? }] — 클릭 · 툴팁 대상 (pickRadius: 화면 반지름 px, 원반)
//   update(dt, stage)     : (선택) 매 프레임
//   pickNear(x, y)        : (선택) pickables에 없을 때 그 자리의 대상
//   screenOf(id)          : (선택) 그 천체의 화면 좌표(client px) — 담는 순간의 빛무리 자리 (main.js bindCollect). 보이지 않으면 null

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import { TweenQueue } from "./tween.js";
import { pickScore } from "./skydata.js";

export { THREE, CSS2DObject };

// 하늘 밖의 보기(내 세계 · 펼치기)의 바탕 — 깊은 남보라 (web/tokens/colors.css --ink-1)
export const SPACE_BG = 0x1c1d4a;

export function label(text, className = "label") {
  const el = document.createElement("div");
  el.className = className;
  el.textContent = text;
  return new CSS2DObject(el);
}

// 알아간 빛의 표식 — 살구색 채운 원 안의 ✦와 어두운 남보라 이름표. 하늘 · 내 세계 지도에서 같은 모양 (style.css .world-star,
// 서랍 · 천체 목록의 .known-mark와 같은 원). 요소는 크기 0으로 그 천체 자리에 놓이고, 원은 가운데 · 이름표는 오른쪽에
export function knownMark(name, { fresh = false } = {}) {
  const el = document.createElement("div");
  el.className = `world-star${fresh ? " observed" : ""}`;
  el.innerHTML = '<span class="known-mark" aria-hidden="true">✦</span>';
  const tag = document.createElement("span");
  tag.className = "star-name";
  tag.textContent = name;
  el.appendChild(tag);
  return new CSS2DObject(el);
}

// 둥근 별 점 — 기본 점은 사각형이라 가운데가 밝은 원형 텍스처를 한 번 만들어 쓴다
let dotTexture;
export function dot() {
  if (dotTexture) return dotTexture;
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.35, "rgba(255,255,255,0.9)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  dotTexture = new THREE.CanvasTexture(c);
  return dotTexture;
}

// 고리 — 하늘에서 '아직 관측 전'(옅게) · '담은 천체'(금빛) 표시
let ringTexture;
export function ring() {
  if (ringTexture) return ringTexture;
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  g.strokeStyle = "rgba(255,255,255,1)";
  g.lineWidth = 4;
  g.beginPath();
  g.arc(32, 32, 26, 0, Math.PI * 2);
  g.stroke();
  ringTexture = new THREE.CanvasTexture(c);
  return ringTexture;
}

// 아직 만나지 않은 빛 — 빈 점선 원 (design-proposal .world-unknown: 1.5px 점선, 안은 아주 옅게). 점 크기 = 원 지름
let dashedTexture;
export function dashedRing() {
  if (dashedTexture) return dashedTexture;
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  g.fillStyle = "rgba(255,255,255,.07)";
  g.beginPath();
  g.arc(32, 32, 28, 0, Math.PI * 2);
  g.fill();
  g.strokeStyle = "rgba(255,255,255,1)";
  g.lineWidth = 6;
  g.setLineDash([11, 8]);
  g.beginPath();
  g.arc(32, 32, 28, 0, Math.PI * 2);
  g.stroke();
  dashedTexture = new THREE.CanvasTexture(c);
  return dashedTexture;
}

export function pointsMaterial(options) {
  return new THREE.PointsMaterial({ map: dot(), transparent: true, depthWrite: false, sizeAttenuation: false, ...options });
}


export class Stage {
  constructor(container) {
    this.container = container;
    // alpha — 하늘 보기는 캔버스를 비워 두고 그 뒤의 CSS 하늘 그라데이션(.stage)을 보여 준다 (sky.js applyBackdrop)
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);

    this.labels = new CSS2DRenderer();
    this.labels.domElement.className = "label-layer";
    container.appendChild(this.labels.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(SPACE_BG);
    this.camera = new THREE.PerspectiveCamera(55, 1, 0.001, 5000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.mode = null;
    this.tweens = new TweenQueue();
    this.clock = new THREE.Clock();

    // 천구 · 펼치기 모드는 화각으로 확대한다 (카메라가 중심에 있어 거리로 확대할 수 없다)
    this.renderer.domElement.addEventListener("wheel", (e) => {
      if (!this.fovZoom) return;
      e.preventDefault();
      this.camera.fov = THREE.MathUtils.clamp(this.camera.fov * (e.deltaY > 0 ? 1.08 : 0.92), this.fovMin ?? 15, 100);
      this.applyInset(this.container.clientWidth, this.container.clientHeight);
    }, { passive: false });

    new ResizeObserver(() => this.resize()).observe(container);
    this.resize();
    this.renderer.setAnimationLoop(() => this.frame());
  }

  resize() {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (!w || !h) return;
    this.camera.aspect = w / h;
    this.applyInset(w, h);
    this.renderer.setSize(w, h);
    this.labels.setSize(w, h);
  }

  // 오른쪽 서랍이 열리면 시야의 중심을 서랍 폭의 절반만큼 왼쪽으로 — 천체가 서랍 뒤로 숨지 않게
  setInset(px) {
    this.inset = px;
    this.applyInset(this.container.clientWidth, this.container.clientHeight);
  }

  // 아래쪽 카드가 덮으면 시야의 중심을 insetY의 절반만큼 위로 — 좁은 화면 내 세계의 요약 카드 (main.js fitMapView)
  setInsetY(px) {
    if ((this.insetY ?? 0) === px) return;
    this.insetY = px;
    this.applyInset(this.container.clientWidth, this.container.clientHeight);
  }

  applyInset(w, h) {
    const x = this.inset && w > this.inset ? this.inset : 0, y = this.insetY && h > this.insetY ? this.insetY : 0;
    if (x || y) this.camera.setViewOffset(w + x, h + y, x, y, w, h);
    else {
      // setViewOffset은 가로세로 비를 전체 폭(화면 + 서랍) 기준으로 바꾸는데 clearViewOffset은 되돌리지 않는다.
      // 서랍을 닫은 뒤 하늘이 가로로 눌려 있던 문제 (원반이 타원 · 끌기가 77%만 따라옴) — 화면 폭 기준으로 되돌린다
      this.camera.clearViewOffset();
      this.camera.aspect = w / h;
    }
    this.camera.updateProjectionMatrix();
  }

  setMode(mode) {
    if (this.mode) {
      this.mode.exit?.();
      this.scene.remove(this.mode.group);
      // CSS2D 이름표는 그룹에서 빠져도 DOM에 남는다(직접 지운 이름표만 정리됨) — 다른 보기에 펼치기 별 이름이 떠 있던 문제.
      // 그룹 안의 이름표 요소를 직접 걷어낸다. 다시 이 보기로 오면 렌더러가 다시 붙인다.
      this.mode.group.traverse((obj) => { if (obj.isCSS2DObject) obj.element.remove(); });
    }
    this.tweens.cancelAll();                 // 이전 모드의 연출은 여기서 끝낸다
    this.mode = mode;
    this.fovZoom = false;
    this.fovMin = 15;
    this.camera.fov = 55;
    this.camera.updateProjectionMatrix();
    Object.assign(this.controls, { enableZoom: true, enablePan: true, enableDamping: true, rotateSpeed: 1, minDistance: 0, maxDistance: Infinity });
    this.scene.add(mode.group);
    mode.enter(this);
  }

  // 화면 좌표에서 가장 가까운 대상 (maxPx 안). 카메라 뒤쪽은 제외한다.
  // 모드가 pickPx를 정하면 그 반경 — 내 세계 지도는 표식의 터치 영역 44px 이상(반경 22px)
  pick(clientX, clientY, maxPx = this.mode?.pickPx ?? 14) {
    if (!this.mode) return null;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const facing = new THREE.Vector3();
    this.camera.getWorldDirection(facing);
    const v = new THREE.Vector3(), rel = new THREE.Vector3();
    let best = null;
    for (const p of this.mode.pickables()) {
      if (rel.copy(p.position).sub(this.camera.position).dot(facing) <= 0) continue;
      v.copy(p.position).project(this.camera);
      const x = rect.left + ((v.x + 1) / 2) * rect.width;
      const y = rect.top + ((1 - v.y) / 2) * rect.height;
      const d = Math.hypot(x - clientX, y - clientY);
      // 화면에서 크게 보이는 원반(태양 · 달 · 행성)은 원반 안 어디든 — 원반 안이면 점수가 음수라 뒤쪽 별 · 이름보다 앞선다.
      // 작게 보이면 기존 최소 영역(maxPx) 그대로 (12-2 리뷰 P2)
      const score = pickScore(d, maxPx, p.pickRadius);
      if (score !== null && (!best || score < best.score)) best = { d, score, ...p };
    }
    // 이름 있는 대상이 없으면 — 모드가 그 자리의 실제 천체를 찾는다 (하늘의 별 · 성운)
    return best ?? this.mode.pickNear?.(clientX, clientY) ?? null;
  }

  // 장면 좌표 → 화면 좌표(client px). 카메라 뒤쪽이거나 화면 밖이면 null. 서랍 · 카드로 비킨 시야(setViewOffset)도 투영 행렬에 들어 있다
  screenOf(position) {
    if (!position) return null;
    const facing = new THREE.Vector3();
    this.camera.getWorldDirection(facing);
    if (position.clone().sub(this.camera.position).dot(facing) <= 0) return null;
    const v = position.clone().project(this.camera);
    if (Math.abs(v.x) > 1 || Math.abs(v.y) > 1) return null;
    const rect = this.renderer.domElement.getBoundingClientRect();
    return { x: rect.left + ((v.x + 1) / 2) * rect.width, y: rect.top + ((1 - v.y) / 2) * rect.height };
  }

  // 카메라 이동 — 위치 · 바라보는 점을 ms 동안 부드럽게
  flyTo(position, target, ms = 1600, done) {
    const from = { p: this.camera.position.clone(), t: this.controls.target.clone() };
    this.animate(ms, (k) => {
      this.camera.position.lerpVectors(from.p, position, k);
      this.controls.target.lerpVectors(from.t, target, k);
    }, done);
  }

  animate(ms, step, done) {
    // 움직임 줄이기 설정이면 애니메이션 없이 끝 모습으로
    const instant = matchMedia("(prefers-reduced-motion: reduce)").matches
      || new URLSearchParams(location.search).get("motion") === "off";
    this.tweens.add(ms, step, done, { instant });
  }

  frame() {
    const dt = Math.min(this.clock.getDelta(), 0.1);
    this.tweens.tick(dt * 1000);
    this.mode?.update?.(dt, this);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.labels.render(this.scene, this.camera);
  }
}
