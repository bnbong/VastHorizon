// 실제 하늘 그리기 — 히파르코스 별 · 은하수 · 성운 · 성단 · 은하를 GPU로. 하늘과 내 세상(우주 지도)이 함께 쓴다.
//
// 좌표 변환은 GPU가 한다: 적도 단위 벡터 × 회전 행렬(uRot) → 화면 방향.
//   하늘   uRot = 위도 · 항성시마다 바뀌는 적도 → 지평 행렬 (skydata.eqToHorizonMatrix)
//   지도   uRot = 고정 (skydata.EQ_TO_MAP)
// 화각이 좁아지면 한계 등급(uLimit)이 올라가 더 어두운 별이 나타난다 (skydata.limitingMag).
//
// 별 모습: 색지수(B−V)로 색, 밝을수록 크고 빛이 번지며, 아주 밝은 별에는 은은한 빛살, 지평선 가까이는 약한 반짝임.

import { THREE } from "./scene.js";
import { decodeMilkyway, decodeStars, radecToEq, SkyGrid, starColor } from "./skydata.js";

const loaded = new Map();
function load(path, kind) {
  if (!loaded.has(path)) {
    loaded.set(path, fetch(path).then((r) => {
      if (!r.ok) throw new Error(`${path} ${r.status}`);
      return kind === "json" ? r.json() : r.arrayBuffer();
    }).catch((e) => { loaded.delete(path); throw e; }));
  }
  return loaded.get(path);
}

export const loadStars = (part) => load(`data/stars_${part}.bin`, "bin").then(decodeStars);
export const loadMilkyway = () => load("data/milkyway.bin", "bin").then(decodeMilkyway);
export const loadDsos = () => load("data/dsos.json", "json");

const rotUniform = (m) => new THREE.Matrix3().set(...m);

// ── 별 ────────────────────────────────────────────────────────────────────

const STAR_VERT = /* glsl */ `
  attribute float mag;
  attribute float seed;
  attribute vec3 color;
  uniform mat3 uRot;
  uniform float uRadius, uLimit, uPixel, uTime, uTwinkle, uDim, uHorizon;
  varying vec3 vColor;
  varying float vAlpha, vGlow;
  void main() {
    vec3 p = uRot * position;
    float d = uLimit - mag;
    if (d < 0.0 || (uHorizon > 0.5 && p.y < -0.03)) {
      gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
      gl_PointSize = 0.0;
      vAlpha = 0.0;
      return;
    }
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p * uRadius, 1.0);
    // 크기는 실제 밝기(등급)로 — 확대해도 밝은 별이 부풀지 않는다. 한계 근처는 옅게 나타난다
    float core = 1.8 + 1.45 * max(0.0, 7.0 - mag);
    vGlow = clamp((2.0 - mag) / 3.5, 0.0, 1.0);
    gl_PointSize = core * (1.0 + 2.2 * vGlow) * uPixel;
    float twinkle = 1.0 + uTwinkle * 0.22 * sin(uTime * (1.3 + seed * 2.1) + seed * 37.0) * (1.0 - clamp(p.y * 2.5, 0.0, 0.85));
    vAlpha = clamp(d / 1.2, 0.0, 1.0) * mix(0.55, 1.0, clamp(d / 5.0, 0.0, 1.0)) * twinkle * uDim;
    if (uHorizon > 0.5) vAlpha *= smoothstep(-0.03, 0.08, p.y);      // 지평선 가까이 흐려진다 (대기)
    vColor = color;
  }`;

const STAR_FRAG = /* glsl */ `
  varying vec3 vColor;
  varying float vAlpha, vGlow;
  void main() {
    vec2 q = gl_PointCoord * 2.0 - 1.0;
    float r2 = dot(q, q);
    if (r2 > 1.0) discard;
    float f = 1.0 + 2.2 * vGlow;                 // 빛 번짐만큼 점이 커져도 중심의 크기는 그대로
    float core = exp(-r2 * 1.5 * f * f) * (1.0 - r2);
    float halo = vGlow * 0.35 * exp(-r2 * 3.5) * (1.0 - r2);
    float spikes = vGlow * vGlow * 0.55 * (exp(-abs(q.x) * 30.0) + exp(-abs(q.y) * 30.0)) * (1.0 - sqrt(r2));
    float a = (core + halo + spikes) * vAlpha;
    gl_FragColor = vec4(mix(vColor, vec3(1.0), core * 0.5) * a, a);
  }`;

export class StarLayer {
  constructor({ radius, horizon }) {
    this.group = new THREE.Group();
    this.uniforms = {
      uRot: { value: new THREE.Matrix3() }, uRadius: { value: radius }, uLimit: { value: 6 },
      uPixel: { value: Math.min(window.devicePixelRatio || 1, 2) }, uTime: { value: 0 }, uTwinkle: { value: 1 },
      uDim: { value: 1 }, uHorizon: { value: horizon ? 1 : 0 },
    };
    this.material = new THREE.ShaderMaterial({
      uniforms: this.uniforms, vertexShader: STAR_VERT, fragmentShader: STAR_FRAG,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    });
    this.parts = [];                 // [{ stars, grid }]
  }

  // 별 묶음 하나 (밝은 별 · 어두운 별)를 더한다
  add(stars) {
    const pos = new Float32Array(stars.count * 3), col = new Float32Array(stars.count * 3);
    const seed = new Float32Array(stars.count);
    const grid = new SkyGrid(2);
    for (let i = 0; i < stars.count; i++) {
      pos.set(radecToEq(stars.ra[i], stars.dec[i]), i * 3);
      col.set(starColor(stars.bv[i]), i * 3);
      seed[i] = ((stars.hip[i] * 2654435761) % 1000) / 1000;
      grid.add(stars.ra[i], stars.dec[i], i);
    }
    const geom = new THREE.BufferGeometry()
      .setAttribute("position", new THREE.BufferAttribute(pos, 3))
      .setAttribute("color", new THREE.BufferAttribute(col, 3))
      .setAttribute("mag", new THREE.BufferAttribute(stars.mag, 1))
      .setAttribute("seed", new THREE.BufferAttribute(seed, 1));
    geom.boundingSphere = new THREE.Sphere(new THREE.Vector3(), this.uniforms.uRadius.value * 2);
    const points = new THREE.Points(geom, this.material);
    points.frustumCulled = false;
    points.renderOrder = 1;
    this.group.add(points);
    this.parts.push({ stars, grid });
  }

  setRotation(m) { this.uniforms.uRot.value.copy(rotUniform(m)); }
  setLimit(limit) { this.uniforms.uLimit.value = limit; }
}

// ── 은하수 ────────────────────────────────────────────────────────────────

const MW_VERT = /* glsl */ `
  varying vec3 vDir;
  void main() {
    vDir = position;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;

const MW_FRAG = /* glsl */ `
  uniform sampler2D uMap;
  uniform mat3 uInv;
  uniform float uStrength, uHorizon;
  varying vec3 vDir;
  const float PI = 3.141592653589793;
  void main() {
    vec3 d = normalize(vDir);
    vec3 e = uInv * d;
    float ra = atan(e.y, e.x);
    float dec = asin(clamp(e.z, -1.0, 1.0));
    float v = texture2D(uMap, vec2(fract(ra / (2.0 * PI)), (0.5 * PI - dec) / PI)).r;
    float a = pow(v, 0.8) * uStrength;
    if (uHorizon > 0.5) a *= smoothstep(-0.02, 0.12, d.y);
    gl_FragColor = vec4(mix(vec3(0.62, 0.78, 1.0), vec3(0.86, 0.66, 1.0), v) * a, a);   // 라벤더빛 은하수 (밝은 곳은 분홍빛)
  }`;

export class MilkyWayLayer {
  constructor(mw, { radius, horizon, strength = 1.0 }) {
    const tex = new THREE.DataTexture(mw.data, mw.width, mw.height, THREE.RedFormat, THREE.UnsignedByteType);
    tex.wrapS = THREE.RepeatWrapping;
    tex.magFilter = tex.minFilter = THREE.LinearFilter;
    tex.needsUpdate = true;
    this.uniforms = { uMap: { value: tex }, uInv: { value: new THREE.Matrix3() }, uStrength: { value: strength },
                      uHorizon: { value: horizon ? 1 : 0 } };
    this.mesh = new THREE.Mesh(new THREE.SphereGeometry(radius, 96, 48), new THREE.ShaderMaterial({
      uniforms: this.uniforms, vertexShader: MW_VERT, fragmentShader: MW_FRAG, side: THREE.BackSide,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    }));
    this.mesh.renderOrder = 0;
    this.mesh.frustumCulled = false;
  }

  // 화면 → 적도 (회전의 역 = 전치)
  setRotation(m) { this.uniforms.uInv.value.copy(rotUniform(m)).transpose(); }
}

// ── 성운 · 성단 · 은하 ─────────────────────────────────────────────────────

// 0 은하 · 1 산개 성단 · 2 성운 · 3 행성상 성운 · 4 구상 성단
const DSO_CLASS = { s: 0, s0: 0, sd: 0, e: 0, i: 0, g: 0, gg: 0, oc: 1, gc: 4, en: 2, bn: 2, rn: 2, dn: 2, sfr: 2, snr: 2, pn: 3 };

const DSO_VERT = /* glsl */ `
  attribute float size;
  attribute float mag;
  attribute float cls;
  attribute float seed;
  attribute float photo;
  uniform mat3 uRot;
  uniform float uRadius, uLimit, uPxPerDeg, uPixel, uShow, uHorizon;
  varying float vAlpha, vCls, vRing, vSeed, vPx;
  void main() {
    vec3 p = uRot * position;
    float px = size / 60.0 * uPxPerDeg;                       // 장축(각분) → 화면 픽셀
    bool bright = mag > -50.0 && mag <= uLimit + 0.5;
    if (uShow <= 0.0 || !bright || (uHorizon > 0.5 && p.y < 0.0)) {      // 등급이 알려진 천체만 — 한계 등급을 따라 늘어난다
      gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
      gl_PointSize = 0.0;
      vAlpha = 0.0;
      return;
    }
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p * uRadius, 1.0);
    gl_PointSize = clamp(px * 1.4, 12.0 * uPixel, 420.0 * uPixel);   // 빛이 퍼지는 만큼 조금 크게
    vPx = gl_PointSize;
    vRing = 1.6 * uPixel / gl_PointSize;                      // 테두리 두께 약 1.6px
    // 밝을수록 또렷하게 (등급 · 한계 등급 차이)
    vAlpha = uShow * mix(0.55, 1.0, clamp((uLimit - mag) / 4.0, 0.0, 1.0));
    vAlpha *= 1.0 - photo * smoothstep(60.0, 140.0, px / uPixel * 1.3);   // 허블 사진이 나타나면(sky.js updatePhotos와 같은 기준) 그림은 물러난다
    vCls = cls;
    vSeed = seed;
  }`;

// 사진처럼 보이게 — 은하는 밝은 핵과 옅은 원반, 성단은 별 알갱이, 성운은 뭉게뭉게한 수소 · 산소 빛, 행성상 성운은 고리.
// 방향(위치각) 정보가 없어 모두 둥글게 그린다. 아주 옅은 테두리를 남겨 누를 수 있는 천체임을 알린다
const DSO_FRAG = /* glsl */ `
  varying float vAlpha, vCls, vRing, vSeed, vPx;
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
  }
  float fbm(vec2 p) { return 0.5 * noise(p) + 0.3 * noise(p * 2.1) + 0.2 * noise(p * 4.3); }
  // 별 알갱이 — 칸마다 하나, 칸 크기는 화면 픽셀에 맞춰 (작게 보일 때 뭉개지지 않게)
  float grains(vec2 q, float density, float cells) {
    vec2 g = q * cells + vSeed * 91.0;
    vec2 id = floor(g), f = fract(g) - 0.5;
    float h = hash(id);
    vec2 o = (vec2(hash(id + 3.1), hash(id + 7.7)) - 0.5) * 0.6;
    return step(1.0 - density, h) * smoothstep(0.22, 0.0, length(f - o)) * (0.5 + 0.5 * hash(id + 1.3));
  }
  void main() {
    vec2 q = gl_PointCoord * 2.0 - 1.0;
    float r = length(q);
    if (r > 1.0) discard;
    float ring = smoothstep(1.0 - 2.5 * vRing, 1.0 - vRing, r) * (1.0 - smoothstep(1.0 - vRing, 1.0, r));
    float cells = clamp(vPx / 7.0, 3.0, 26.0);
    vec3 c;
    float a;
    if (vCls < 0.5) {                                          // 은하 — 밝은 팽대부 + 옅은 원반 + 먼지 얼룩
      float bulge = exp(-r * r * 26.0);
      float disc = exp(-r * 3.4) * (0.75 + 0.25 * fbm(q * 4.0 + vSeed * 13.0));
      c = mix(vec3(0.72, 0.78, 1.0), vec3(1.0, 0.9, 0.74), bulge);
      a = bulge * 0.9 + disc * 0.42 + ring * 0.14;
    } else if (vCls < 1.5) {                                   // 산개 성단 — 드문드문 밝은 젊은 별 (푸른 흰빛)
      float s = grains(q, 0.16 * (1.0 - r * 0.6), cells * 0.7);
      c = vec3(0.82, 0.88, 1.0);
      a = s * 1.1 + exp(-r * r * 4.0) * 0.05 + ring * 0.12;
    } else if (vCls < 2.5) {                                   // 성운 — 수소(분홍) · 산소(청록) 빛이 뭉게뭉게
      float n = fbm(q * 2.6 + vSeed * 17.0);
      float m = fbm(q * 4.2 - vSeed * 5.0);
      c = mix(vec3(0.95, 0.52, 0.66), vec3(0.58, 0.84, 0.95), smoothstep(0.4, 0.75, m));
      a = smoothstep(0.32, 0.8, n) * (1.0 - smoothstep(0.5, 1.0, r)) * 0.38 + ring * 0.12;
    } else if (vCls < 3.5) {                                   // 행성상 성운 — 청록 고리와 붉은 가장자리
      float shell = exp(-pow((r - 0.55) / 0.18, 2.0));
      c = mix(vec3(0.5, 1.0, 0.85), vec3(1.0, 0.5, 0.55), smoothstep(0.5, 0.8, r));
      a = shell * 0.8 + exp(-r * r * 30.0) * 0.5 + ring * 0.12;
    } else {                                                   // 구상 성단 — 빽빽한 핵 + 별 알갱이 (늙은 별, 노란빛)
      float core = exp(-r * r * 9.0);
      float s = grains(q, 0.55 * core + 0.12, cells);
      c = vec3(1.0, 0.9, 0.72);
      a = core * 0.45 + s * 0.9 + ring * 0.1;
    }
    a = min(a * vAlpha * 1.7, 1.0);
    gl_FragColor = vec4(c * a, a);
  }`;

export class DsoLayer {
  constructor(data, { radius, horizon }) {
    const rows = data.rows;
    const pos = new Float32Array(rows.length * 3), size = new Float32Array(rows.length);
    const mag = new Float32Array(rows.length), cls = new Float32Array(rows.length), seed = new Float32Array(rows.length);
    this.grid = new SkyGrid(2);
    this.rows = rows;
    this.types = data.types;
    rows.forEach(([, type, ra, dec, m, major], i) => {
      pos.set(radecToEq(ra, dec), i * 3);
      size[i] = major ?? 0;
      mag[i] = m ?? -99;
      cls[i] = DSO_CLASS[type] ?? 2;
      seed[i] = (i * 0.6180339887) % 1;
      this.grid.add(ra, dec, i);
    });
    this.uniforms = { uRot: { value: new THREE.Matrix3() }, uRadius: { value: radius }, uLimit: { value: 6 },
                      uPxPerDeg: { value: 10 }, uPixel: { value: Math.min(window.devicePixelRatio || 1, 2) },
                      uShow: { value: 1 }, uHorizon: { value: horizon ? 1 : 0 } };
    const geom = new THREE.BufferGeometry()
      .setAttribute("position", new THREE.BufferAttribute(pos, 3))
      .setAttribute("size", new THREE.BufferAttribute(size, 1))
      .setAttribute("mag", new THREE.BufferAttribute(mag, 1))
      .setAttribute("cls", new THREE.BufferAttribute(cls, 1))
      .setAttribute("seed", new THREE.BufferAttribute(seed, 1))
      .setAttribute("photo", new THREE.BufferAttribute(new Float32Array(rows.length), 1));
    this.points = new THREE.Points(geom, new THREE.ShaderMaterial({
      uniforms: this.uniforms, vertexShader: DSO_VERT, fragmentShader: DSO_FRAG,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    }));
    this.points.frustumCulled = false;
    this.points.renderOrder = 1;
  }

  setRotation(m) { this.uniforms.uRot.value.copy(rotUniform(m)); }

  // 허블 사진이 있는 메시에 천체 — 사진이 보일 만큼 확대하면 그린 빛 대신 사진만 (codes: 메시에 번호 집합)
  markPhotos(codes) {
    const attr = this.points.geometry.attributes.photo;
    this.rows.forEach((r, i) => { attr.array[i] = r[7] && codes.has(r[7]) ? 1 : 0; });
    attr.needsUpdate = true;
  }

  // 화면 크기 · 화각 · 한계 등급 — 화면에 그려지는 크기를 정한다
  setView({ fov, height, limit }) {
    this.uniforms.uPxPerDeg.value = (height * this.uniforms.uPixel.value) / fov;
    this.uniforms.uLimit.value = limit;
  }

  // 그 행이 지금 화면에 보이는가 (셰이더와 같은 조건)
  visible(i, { fov, height, limit }) {
    const m = this.rows[i][4];
    return m != null && m <= limit + 0.5;
  }

  describe(i) {
    const [name, type, , , m, major, minor, messier] = this.rows[i];
    const parts = [this.types[type] ?? "천체"];
    if (m != null) parts.push(`${m}등급`);
    if (major) parts.push(`크기 ${major}′${minor && minor !== major ? ` × ${minor}′` : ""}`);
    return `${messier && messier !== name ? `${messier} (${name})` : name}: ${parts.join(", ")}`;
  }
}
