// 우주 지도에서 가까이 갔을 때의 모습 — 멀리서는 점, 가까이 가면 그 천체다운 모습이 서서히 나타난다.
//
//   별        분광형 색의 빛나는 원반 (가장자리 어두워짐 · 쌀알 무늬 · 코로나 · 빛살)
//   메시에    NASA 허블 메시에 목록의 실제 사진 (web/data/messier, 출처는 서랍에). 사진이 없는 성단 · 성운은 그 종류의 모습을 그린다
//   은하 중심 블랙홀  근거(web/data/blackholes.json)가 있는 은하에만, 줌 거리보다 더 들어가면 중심에 가르강튀아 모습(상상도)
// 크기 · 나타나는 거리 · 줌 거리는 closeup.js 한 곳에 (지도의 카메라 비행 map.js select와 같은 표).
// 사진은 가로 512px로 시작하고, 줌 거리의 HD_RANGE배 안으로 들어오면 1024px(data/messier/hd)로 바꾼다 — 한 번에 HD_LIMIT장까지 (closeup.js HdSwap)
// 지도는 거리가 로그 스케일인 그림이라, 모습의 크기는 실제 크기 비율이 아니다.

import { THREE, label } from "./scene.js";
import { BILLBOARD_VERT, BlackHoleSprite, loadBlackHoles } from "./blackhole.js";
import { spectralColor } from "./skydata.js";
import { FILL, HD_RANGE, HdSwap, SIZE, bhFade, bhViewDistance, closeupFill, closeupNear, closeupSize, hasCloseup, viewDistance } from "./closeup.js";

const STAR_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uTime, uFade, uSeed;
  varying vec2 vUv;
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
  }
  void main() {
    vec2 p = vUv * 2.0 - 1.0;
    float r = length(p), R = 0.3;
    float disk = 1.0 - smoothstep(R - 0.01, R, r);
    float mu = sqrt(max(1.0 - (r / R) * (r / R), 0.0));
    float gran = noise(p * 40.0 + uSeed * 50.0 + uTime * 0.15) * 0.5 + noise(p * 90.0 - uTime * 0.1) * 0.5;
    vec3 surface = uColor * (0.35 + 0.6 * pow(mu, 0.6)) * (0.85 + 0.3 * gran);   // 가장자리는 어둡고 더 붉게
    float corona = exp(-max(r - R, 0.0) * 11.0) * (1.0 - disk) * 0.45;
    float rays = (exp(-abs(p.x) * 70.0) + exp(-abs(p.y) * 70.0)) * exp(-r * 3.2) * 0.35;
    rays *= 1.0 - disk;                                      // 빛살은 원반 바깥에만
    vec3 c = surface * disk * 0.95 + uColor * (corona + rays);
    float a = clamp(disk + corona + rays, 0.0, 1.0) * (1.0 - smoothstep(0.85, 1.0, r)) * uFade;
    gl_FragColor = vec4(c * a, a);
  }`;

// 사진이 없는 메시에 천체 — 산개 성단(드문드문 젊은 별) · 행성상 성운(고리) · 이중성 · 성군
const DEEP_FRAG = /* glsl */ `
  uniform float uKind, uFade, uSeed;
  varying vec2 vUv;
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
  }
  float star(vec2 p, vec2 at, float s) { float d = length(p - at); return exp(-d * d / (s * s)); }
  void main() {
    vec2 p = vUv * 2.0 - 1.0;
    float r = length(p);
    vec3 c = vec3(0.0);
    float a = 0.0;
    if (uKind < 0.5) {                                        // 산개 성단 — 별 40개, 가운데 몰리게
      for (int i = 0; i < 40; i++) {
        float fi = float(i) + uSeed * 31.0;
        float rr = pow(hash(vec2(fi, 1.3)), 1.6) * 0.8, th = hash(vec2(fi, 7.1)) * 6.2832;
        float b = 0.35 + 0.65 * pow(hash(vec2(fi, 3.7)), 3.0);
        float s = star(p, rr * vec2(cos(th), sin(th)), 0.012 + 0.02 * b);
        c += mix(vec3(0.7, 0.8, 1.0), vec3(1.0, 0.85, 0.6), step(0.85, hash(vec2(fi, 9.9)))) * s * b * 1.6;
        a += s * b;
      }
    } else if (uKind < 1.5) {                                 // 행성상 성운 — 청록 껍질과 붉은 가장자리, 가운데 흰 왜성
      float n = noise(p * 6.0 + uSeed * 9.0);
      float shell = exp(-pow((r - 0.42) / 0.16, 2.0)) * (0.75 + 0.35 * n);
      c = mix(vec3(0.4, 0.95, 0.85), vec3(1.0, 0.45, 0.5), smoothstep(0.38, 0.62, r)) * shell + vec3(1.0) * star(p, vec2(0.0), 0.03);
      a = shell * 0.8 + star(p, vec2(0.0), 0.03);
    } else {                                                  // 이중성 · 성군 — 몇 개의 밝은 별
      for (int i = 0; i < 5; i++) {
        float fi = float(i) + uSeed * 17.0;
        float on = uKind < 2.5 ? step(float(i), 1.5) : 1.0;
        vec2 at = (vec2(hash(vec2(fi, 2.2)), hash(vec2(fi, 4.4))) - 0.5) * (uKind < 2.5 ? 0.35 : 1.0);
        float s = star(p, at, 0.035) * on;
        c += vec3(1.0, 0.95, 0.85) * s * 1.5;
        a += s;
      }
    }
    a = clamp(a, 0.0, 1.0) * (1.0 - smoothstep(0.85, 1.0, r)) * uFade;
    gl_FragColor = vec4(c * uFade, a);
  }`;

let softDiscTex;
function softDisc() {
  if (softDiscTex) return softDiscTex;
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d"), grad = g.createRadialGradient(64, 64, 20, 64, 64, 64);
  grad.addColorStop(0, "#fff");
  grad.addColorStop(1, "#000");
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  softDiscTex = new THREE.CanvasTexture(c);
  return softDiscTex;
}

function billboard(fragmentShader, uniforms) {
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.ShaderMaterial({
    uniforms: { uFade: { value: 0 }, uTime: { value: 0 }, uSeed: { value: 0 }, ...uniforms },
    vertexShader: BILLBOARD_VERT, fragmentShader, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  }));
  mesh.frustumCulled = false;
  mesh.renderOrder = 5;
  return mesh;
}

const DEEP_KIND = (kind) => (/행성상/.test(kind) ? 1 : /이중성/.test(kind) ? 2 : /성군/.test(kind) ? 3 : 0);

export class DetailLayer {
  constructor(points, parent) {
    this.group = new THREE.Group();
    parent.add(this.group);
    this.items = points.filter(hasCloseup)
      .map((p, i) => ({ p, seed: (i * 0.618) % 1, obj: null, kind: null }));
    this.blackHoles = new Map();               // 은하 ID → { info, sprite, tag }
    fetch("data/messier/credits.json").then((r) => (r.ok ? r.json() : {})).catch(() => ({}))
      .then((c) => { this.photos = c; this.onPhotos?.(); });   // 목록이 늦게 오면 지도가 고른 천체로 다시 날아간다 (map.js)
    loadBlackHoles().then((d) => { this.bhInfo = new Map(d.galaxies.map((g) => [g.id, g])); });
    this.frame = { fov: 55, aspect: 1 };       // 보이는 영역의 화각 · 비율 (map.js update가 매 프레임 closeup.js insetFrame으로)
    this.anisotropy = 1;                       // 렌더러 최대치 (map.js update)
    this.selectedId = null;                    // 지도에서 고른 천체 (map.js update) — 고해상도 사진은 고른 천체나 화면 안의 천체만
    this.frustum = new THREE.Frustum();
    this.sphere = new THREE.Sphere();
    this.projScreen = new THREE.Matrix4();
    // 고해상도 사진 — HD_LIMIT장까지, 250ms마다 한 건씩 (closeup.js HdSwap). 다 받은 텍스처만 붙이고,
    // 되돌릴 때는 처음 받아 둔 512 텍스처(it.lowTex)를 다시 붙인다 — 새로 받는 동안 빈(검은) 텍스처가 보이지 않게
    this.hd = new HdSwap({
      load: (it, ok, fail) => { const tex = this.photoTexture(`data/messier/hd/${it.p.code}.jpg`, () => ok(tex), () => { tex.dispose(); fail(); }); },
      apply: (it, tex) => this.swapMap(it, tex),
      revert: (it) => this.swapMap(it, it.lowTex),
      discard: (tex) => tex.dispose(),
    });
  }

  // 사진 텍스처를 한 프레임에 갈아 끼우고 앞의 것은 GPU에서 내린다 — visible · opacity는 건드리지 않는다.
  // 512 텍스처(it.lowTex)는 dispose해도 이미지가 남아 있어, 되돌리면 그 프레임에 바로 다시 올라간다
  swapMap(it, tex) {
    const old = it.obj.material.map;
    if (old === tex) return;
    it.obj.material.map = tex;
    it.obj.material.needsUpdate = true;
    old?.dispose();
  }

  // 고해상도 사진 판정 (HD_INTERVAL마다) — 줌 거리의 HD_RANGE배 안이고, 고른 천체이거나 카메라 시야(절두체) 안이면 받고 싶다
  // (거리만 보면 이웃 은하까지 받는다). 고른 천체 먼저, 그다음 카메라에 가까운 순.
  // 되돌려도 되는 것은 절두체 밖이고 범위 밖인 것만 — 화면 안의 사진이 512로 바뀌는 일이 없게
  planHd(camera) {
    const now = performance.now();
    if (!this.hd.due(now)) return;
    camera.updateMatrixWorld();
    this.frustum.setFromProjectionMatrix(this.projScreen.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse));
    const want = [], keep = new Set();
    let selected = null;
    for (const it of this.items) {
      if (!it.photo || !it.obj) continue;
      const d = camera.position.distanceTo(it.p.position);
      const inRange = d < this.viewOf(it.size) * HD_RANGE;
      this.sphere.set(it.p.position, it.size * 0.5);
      const inView = this.frustum.intersectsSphere(this.sphere);
      if (inRange || inView) keep.add(it);
      const sel = it.p.id === this.selectedId;
      if (sel && inRange) selected = it;
      if (inRange && it.obj.visible && (sel || inView)) want.push({ it, d: sel ? -1 : d });
    }
    want.sort((a, b) => a.d - b.d);
    this.hd.tick(now, want.map((w) => w.it), { keep: (it) => keep.has(it), selected });
  }

  // 근접 모습의 크기 (closeup.js) — 근접 모습이 없거나 사진 목록을 아직 받지 못했으면 null (지도의 카메라 비행이 쓴다)
  sizeOf(p) {
    if (!this.photos || !hasCloseup(p)) return null;
    return closeupSize(p, !!this.photos[p.code]);
  }

  // 지금 화면에서 그 크기의 근접 모습이 짧은 변의 fill(기본 45%, 별은 closeup.js STAR_FILL)을 차지하는 거리
  viewOf(size, fill = FILL) {
    return viewDistance(size, this.frame.fov, this.frame.aspect, fill);
  }

  // 그 천체의 줌 거리 — 별이면 별 전용 채움 비율로
  viewOfPoint(p, size) {
    return this.viewOf(size, closeupFill(p));
  }

  // 사진 텍스처 — 색 공간 · 비등방 필터를 맞춘다
  photoTexture(url, onLoad, onError) {
    const tex = new THREE.TextureLoader().load(url, onLoad, undefined, onError);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = this.anisotropy;
    return tex;
  }

  // 처음 가까이 갔을 때 만든다 — 사진도 그때 내려받는다
  build(it) {
    const { p } = it;
    const photo = !!this.photos?.[p.code];
    if (p.group === "star") {
      it.obj = billboard(STAR_FRAG, { uColor: { value: new THREE.Color(...spectralColor(p.spectral)) } });
    } else if (photo) {
      it.lowTex = this.photoTexture(`data/messier/${p.code}.jpg`);   // 512 — HD를 되돌릴 때 다시 붙인다
      it.obj = new THREE.Sprite(new THREE.SpriteMaterial({ map: it.lowTex, alphaMap: softDisc(),
        transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0 }));
      it.obj.renderOrder = 5;
      it.photo = true;
    } else {
      it.obj = billboard(DEEP_FRAG, { uKind: { value: DEEP_KIND(p.kind ?? "") } });
    }
    it.size = closeupSize(p, photo);
    it.near = closeupNear(p, photo);
    it.obj.material.uniforms && (it.obj.material.uniforms.uSeed.value = it.seed);
    it.obj.position.copy(p.position);
    it.obj.scale.setScalar(it.size);
    this.group.add(it.obj);
  }

  setFade(it, f) {
    if (it.photo) it.obj.material.opacity = f * 0.95;
    else it.obj.material.uniforms.uFade.value = f;
    it.obj.visible = f > 0.001;
  }

  update(t, camera, still) {
    if (!this.photos) return;
    const cam = camera.position;
    for (const it of this.items) {
      const d = cam.distanceTo(it.p.position);
      const near = it.near ?? closeupNear(it.p, !!this.photos[it.p.code]);
      const f = THREE.MathUtils.smoothstep(near - d, 0, near * 0.4);
      if (f <= 0) { if (it.obj) it.obj.visible = false; } else {
        if (!it.obj) this.build(it);
        this.setFade(it, f);
        if (!it.photo) it.obj.material.uniforms.uTime.value = still ? 0 : t;
      }
      this.updateBlackHole(it, d, t, camera, still);
    }
    // 고해상도 사진 — 다 받기 전 · 받지 못하면 · 상한이 찼으면 512 그대로
    this.planHd(camera);
  }

  // 은하 중심 블랙홀 — 근거가 있는 은하에만, 줌 거리보다 더 들어가면 중심에 (이름표: 이름 · 상상도).
  // 줌 거리(viewOf)에서는 보이지 않고 블랙홀 거리(closeup.js bhViewDistance)까지 들어가면 또렷하다 — 화면 비율에 따라 두 거리가 함께 바뀐다
  updateBlackHole(it, d, t, camera, still) {
    const info = this.bhInfo?.get(it.p.id);
    if (!info) return;
    let bh = this.blackHoles.get(it.p.id);
    const galaxyView = this.viewOf(it.size ?? this.sizeOf(it.p) ?? SIZE.photo);
    const f = bhFade(d, galaxyView, bhViewDistance(this.frame, galaxyView));
    if (f <= 0) { if (bh) { bh.sprite.mesh.visible = false; bh.tag.visible = false; } return; }
    if (!bh) {
      const h = [...it.p.id].reduce((s, ch) => s + ch.charCodeAt(0), 0);
      const sprite = new BlackHoleSprite(new THREE.Vector3(Math.sin(h), 3, Math.cos(h * 1.7)));   // 원반 기울기는 은하마다 다르게
      sprite.mesh.position.copy(it.p.position);
      sprite.mesh.scale.setScalar(SIZE.bh);
      const tag = label(`${info.black_hole ?? "중심 블랙홀"} · 계산한 상상도`, "label blackhole");
      tag.position.copy(it.p.position).add(new THREE.Vector3(0, -SIZE.bh * 0.55, 0));
      this.group.add(sprite.mesh, tag);
      bh = { info, sprite, tag };
      this.blackHoles.set(it.p.id, bh);
    }
    bh.sprite.mesh.visible = true;
    bh.tag.visible = f > 0.5;
    bh.sprite.material.uniforms.uFade.value = f;
    bh.sprite.update(still ? 2 : t, camera);
    if (it.photo) it.obj.material.opacity = Math.min(it.obj.material.opacity, 0.95 - 0.5 * f);   // 사진은 조금 옅게 — 중심이 보이게
  }
}
