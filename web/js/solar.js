// 태양 · 달 · 행성 그리기 — 그날의 위치(ephemeris.js)에 실제 시지름으로, 실제 태양 방향의 빛으로.
//
// - 빛을 실제 태양 쪽에서 비추므로 달의 위상(밝은 부분의 크기와 방향)은 따로 계산하지 않아도 맞는다.
// - 천체마다 좌표축: z = 자전축(IAU), x = 지구 쪽. 달은 늘 같은 면이 지구를 보므로 표면 지도의 경도 0이 x 쪽이다.
// - 달 표면: NASA 과학시각화 스튜디오 CGI Moon Kit (LRO LROC 색 지도, 1k) — 공공 저작물, 출처 표기.
//   행성 표면은 사진이 아니라 색과 띠를 단순화한 그림이다 (목성 띠 · 토성 고리 · 화성 극관).
// - 시지름이 화면에서 몇 픽셀보다 작으면 등급에 맞는 빛점이 대신 보인다.

import { THREE, dot } from "./scene.js";
import { applyMatrix } from "./skydata.js";
import { solarSystem, topocentric } from "./ephemeris.js";

const TYPES = { sun: 0, moon: 1, mercury: 2, venus: 3, mars: 4, jupiter: 5, saturn: 6, uranus: 7, neptune: 8 };
// 화면 반지름 비율 — 달이 행성 · 태양 앞을 가린다 (별 · 은하수보다 늘 안쪽)
const DEPTH = { moon: 0.93, sun: 0.97 };

const BODY_VERT = /* glsl */ `
  varying vec3 vLocal;
  varying vec3 vWorldN;
  varying vec3 vWorldPos;
  void main() {
    vLocal = normal;                                         // 천체 좌표 (z 자전축, x 지구 쪽)
    vWorldN = normalize(mat3(modelMatrix) * normal);
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vWorldPos = wp.xyz;
    gl_Position = projectionMatrix * viewMatrix * wp;
  }`;

const BODY_FRAG = /* glsl */ `
  uniform int uType;
  uniform vec3 uSun;                                         // 태양 쪽 방향 (화면 좌표)
  uniform sampler2D uMap;
  uniform float uHasMap, uDim;
  varying vec3 vLocal;
  varying vec3 vWorldN;
  varying vec3 vWorldPos;
  const float PI = 3.141592653589793;
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
  }
  void main() {
    vec3 n = normalize(vLocal);
    float lat = asin(clamp(n.z, -1.0, 1.0));
    float lon = atan(n.y, n.x);
    vec3 c;
    if (uType == 0) {                                        // 태양 — 가장자리 어두워짐
      float mu = max(dot(normalize(vWorldN), normalize(cameraPosition - vWorldPos)), 0.0);
      gl_FragColor = vec4(vec3(1.0, 0.93, 0.78) * (0.45 + 0.55 * pow(mu, 0.6)), 1.0);
      return;
    }
    if (uType == 1 && uHasMap > 0.5) c = texture2D(uMap, vec2(0.5 + lon / (2.0 * PI), 0.5 - lat / PI)).rgb;
    else if (uType == 1) c = vec3(0.6);
    else if (uType == 2) c = vec3(0.55, 0.53, 0.5) * (0.85 + 0.3 * noise(vec2(lon, lat) * 6.0));
    else if (uType == 3) c = vec3(0.96, 0.9, 0.74) * (0.95 + 0.05 * sin(lat * 9.0));
    else if (uType == 4) {                                   // 화성 — 붉은 표면, 어두운 지대, 극관
      float d = noise(vec2(lon * 2.5, lat * 3.0)) * 0.6 + noise(vec2(lon, lat) * 9.0) * 0.4;
      c = mix(vec3(0.82, 0.45, 0.26), vec3(0.45, 0.25, 0.16), smoothstep(0.55, 0.75, d));
      c = mix(c, vec3(0.95), smoothstep(1.25, 1.35, abs(lat)));
    } else if (uType == 5) {                                 // 목성 — 밝은 대와 어두운 띠
      float b = sin(lat * 14.0 + 0.6 * noise(vec2(lon * 3.0, lat * 20.0)));
      c = mix(vec3(0.62, 0.46, 0.34), vec3(0.93, 0.88, 0.78), smoothstep(-0.3, 0.4, b));
      c *= 1.0 - 0.25 * smoothstep(1.1, 1.5, abs(lat));
    } else if (uType == 6) {                                 // 토성 — 옅은 띠
      float b = sin(lat * 10.0);
      c = mix(vec3(0.82, 0.72, 0.5), vec3(0.95, 0.88, 0.68), smoothstep(-0.5, 0.6, b));
    } else if (uType == 7) c = vec3(0.62, 0.85, 0.9);
    else c = vec3(0.36, 0.5, 0.95);
    float light = dot(normalize(vWorldN), normalize(uSun));
    float lit = smoothstep(-0.03, 0.12, light) * (0.35 + 0.65 * max(light, 0.0));
    float earthshine = uType == 1 ? 0.035 : 0.0;             // 달의 어두운 부분 — 지구 반사광
    gl_FragColor = vec4(c * (lit + earthshine) * uDim, 1.0);
  }`;

export class SolarLayer {
  // radius: 하늘 구의 반지름 (별과 같은 R), horizon: 지평선 아래는 숨긴다
  constructor({ radius, horizon }) {
    this.radius = radius;
    this.horizon = horizon;
    this.group = new THREE.Group();
    this.bodies = new Map();
    const sphere = new THREE.SphereGeometry(1, 64, 32);
    const moonMap = new THREE.TextureLoader().load("data/textures/moon_lroc_1k.jpg", () => { moonUniforms.uHasMap.value = 1; });
    moonMap.colorSpace = THREE.SRGBColorSpace;
    let moonUniforms;
    for (const [key, type] of Object.entries(TYPES)) {
      const uniforms = { uType: { value: type }, uSun: { value: new THREE.Vector3(1, 0, 0) }, uMap: { value: moonMap },
                         uHasMap: { value: 0 }, uDim: { value: 1 } };
      if (key === "moon") moonUniforms = uniforms;
      const holder = new THREE.Group();
      const mesh = new THREE.Mesh(sphere, new THREE.ShaderMaterial({ uniforms, vertexShader: BODY_VERT, fragmentShader: BODY_FRAG }));
      mesh.renderOrder = 3;
      holder.add(mesh);
      if (key === "saturn") holder.add(this.saturnRings(uniforms));
      // 빛점 — 시지름이 작을 때도 보이게 (밝기는 등급으로)
      const glow = new THREE.Points(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3()]),
        new THREE.PointsMaterial({ map: dot(), transparent: true, depthWrite: false, sizeAttenuation: false,
                                   blending: THREE.AdditiveBlending, color: key === "sun" ? 0xfff0c8 : 0xfff6e8 }));
      glow.renderOrder = 2;
      this.group.add(holder, glow);
      this.bodies.set(key, { holder, mesh, uniforms, glow });
    }
  }

  // 토성 고리 — 적도면(자전축에 수직), 안쪽 · 바깥 반지름은 실제 비율, 카시니 간극
  saturnRings(bodyUniforms) {
    const inner = 74500 / 58232, outer = 136780 / 58232;
    const geom = new THREE.RingGeometry(inner, outer, 96, 1);
    const mat = new THREE.ShaderMaterial({
      uniforms: { uSun: bodyUniforms.uSun, uDim: bodyUniforms.uDim, uInner: { value: inner }, uOuter: { value: outer } },
      vertexShader: /* glsl */ `
        varying float vR;
        void main() { vR = length(position.xy); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
      fragmentShader: /* glsl */ `
        uniform float uInner, uOuter, uDim;
        varying float vR;
        void main() {
          float t = (vR - uInner) / (uOuter - uInner);
          float a = 0.55 + 0.35 * sin(t * 40.0) * 0.3;
          a *= 1.0 - smoothstep(0.66, 0.68, t) * (1.0 - smoothstep(0.71, 0.73, t)) * 0.9;   // 카시니 간극
          a *= smoothstep(0.0, 0.05, t) * (1.0 - smoothstep(0.95, 1.0, t));
          gl_FragColor = vec4(vec3(0.9, 0.82, 0.62) * uDim, a);
        }`,
      transparent: true, side: THREE.DoubleSide, depthWrite: false,
    });
    const ring = new THREE.Mesh(geom, mat);
    ring.renderOrder = 4;
    return ring;
  }

  // 그 시각 · 회전 행렬(적도 → 화면)로 놓는다. 반환: 천체 목록 (화면 위치 · 이름 · 시지름 · 밝은 비율)
  update(date, matrix, { pxPerDeg = 10, dim = 1 } = {}) {
    this.placed = [];
    const toScene = (v) => new THREE.Vector3(...applyMatrix(matrix, v));
    for (const b of solarSystem(date)) {
      const item = this.bodies.get(b.key);
      if (!item) continue;
      const dist = this.radius * (DEPTH[b.key] ?? 0.95);
      // 하늘(지평 좌표)에서는 관측자 기준으로 — 방향 · 거리 · 시반지름 · 지평선 판정 모두 보정된 값 (달의 일주시차)
      if (this.horizon) {
        const topo = topocentric(toScene(b.dir).normalize().toArray(), b.distanceKm);
        b.sceneDir = topo.dir;
        b.distanceKm = topo.distanceKm;
        b.angularRadiusDeg = Math.atan(b.radiusKm / topo.distanceKm) * 180 / Math.PI;
      }
      const dir = b.sceneDir ? new THREE.Vector3(...b.sceneDir) : toScene(b.dir).normalize();
      const pos = dir.clone().multiplyScalar(dist);
      const size = dist * Math.tan(b.angularRadiusDeg * Math.PI / 180);
      const above = !this.horizon || dir.y > -Math.sin(b.angularRadiusDeg * Math.PI / 180);
      // 좌표축: z 자전축, x 지구 쪽 (자전축과 수직이 되게)
      const z = toScene(polarVector(b.pole)).normalize();
      const x = dir.clone().negate().addScaledVector(z, dir.dot(z)).normalize();
      const y = new THREE.Vector3().crossVectors(z, x);
      item.holder.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(x, y, z));
      item.holder.position.copy(pos);
      item.holder.scale.setScalar(size);
      item.holder.visible = above;
      item.uniforms.uSun.value.copy(toScene(b.toSun));
      item.uniforms.uDim.value = b.key === "sun" ? 1 : dim;
      // 빛점 크기 — 등급으로 (밝은 천체일수록 크게), 원반이 충분히 크면 사라진다
      const diskPx = 2 * b.angularRadiusDeg * pxPerDeg;
      const glowPx = b.key === "sun" ? 60 : b.key === "moon" ? 26 : Math.max(4, 9 - 1.4 * b.mag);
      item.glow.geometry.attributes.position.setXYZ(0, pos.x, pos.y, pos.z);
      item.glow.geometry.attributes.position.needsUpdate = true;
      item.glow.geometry.computeBoundingSphere();
      item.glow.material.size = glowPx * (window.devicePixelRatio > 1 ? 1.5 : 1);
      item.glow.material.opacity = (b.key === "sun" ? 0.9 : Math.max(0, 1 - diskPx / 14)) * (b.key === "sun" ? 1 : dim);
      item.glow.visible = above;
      this.placed.push({ ...b, position: pos, above, diskPx });
    }
    return this.placed;
  }
}

function polarVector([ra, dec]) {
  const r = ra * Math.PI / 180, d = dec * Math.PI / 180;
  return [Math.cos(d) * Math.cos(r), Math.cos(d) * Math.sin(r), Math.sin(d)];
}
