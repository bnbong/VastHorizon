// 태양 · 달 · 행성 그리기 — 그날의 위치(ephemeris.js)에 실제 시지름으로, 실제 태양 방향의 빛으로.
//
// - 빛을 실제 태양 쪽에서 비추므로 달의 위상(밝은 부분의 크기와 방향)은 따로 계산하지 않아도 맞는다.
// - 천체마다 좌표축: z = 자전축(IAU), x = 지구 쪽. 달은 늘 같은 면이 지구를 보므로 표면 지도의 경도 0이 x 쪽이다.
// - 달 표면: NASA 과학시각화 스튜디오 CGI Moon Kit (LRO LROC 색 지도, 1k) — 공공 저작물, 출처 표기.
//   행성 표면은 사진이 아니라 실제 모습을 단순화한 그림이다 (목성 띠와 대적점 · 토성 고리와 그림자 · 화성 극관 · 금성 구름 · 수성 크레이터).
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
  varying vec3 vCenter;
  varying vec3 vAxis;
  varying float vScale;
  void main() {
    vLocal = normal;                                         // 천체 좌표 (z 자전축, x 지구 쪽)
    vWorldN = normalize(mat3(modelMatrix) * normal);
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vWorldPos = wp.xyz;
    vCenter = (modelMatrix * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
    vAxis = normalize(mat3(modelMatrix) * vec3(0.0, 0.0, 1.0));
    vScale = length(modelMatrix[0].xyz);
    gl_Position = projectionMatrix * viewMatrix * wp;
  }`;

// 표면 무늬는 사진이 아니라 실제 모습을 단순화한 그림이다 (목성 띠와 대적점, 토성 고리와 그림자, 화성 극관, 금성 구름, 수성 크레이터)
const BODY_FRAG = /* glsl */ `
  uniform int uType;
  uniform vec3 uSun;                                         // 태양 쪽 방향 (화면 좌표)
  uniform sampler2D uMap;
  uniform float uHasMap, uDim;
  varying vec3 vLocal;
  varying vec3 vWorldN;
  varying vec3 vWorldPos;
  varying vec3 vCenter;
  varying vec3 vAxis;
  varying float vScale;
  const float PI = 3.141592653589793;
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
  }
  // 구 위의 잡음 — 경도 이음새가 없게 3차원 좌표로
  float noise3(vec3 p) {
    return noise(p.xy + p.z * 1.7) * 0.5 + noise(p.yz * 1.3 - p.x) * 0.3 + noise(p.zx * 2.1 + p.y) * 0.2;
  }
  float fbm3(vec3 p) { return noise3(p) * 0.55 + noise3(p * 2.3) * 0.3 + noise3(p * 5.1) * 0.15; }
  // 크레이터 — 칸마다 하나, 바닥은 어둡고 테두리는 밝게
  float craters(vec3 n, float scale) {
    vec2 uv = vec2(atan(n.y, n.x), asin(n.z)) * scale;
    vec2 id = floor(uv), f = fract(uv) - 0.5;
    float r = 0.15 + 0.3 * hash(id);
    float d = length(f - (vec2(hash(id + 2.0), hash(id + 5.0)) - 0.5) * 0.4);
    return step(0.55, hash(id + 9.0)) * (smoothstep(r, r * 0.7, d) * -0.35 + smoothstep(r * 1.25, r, d) * smoothstep(r * 0.8, r, d) * 0.25);
  }
  void main() {
    vec3 n = normalize(vLocal);
    float lat = asin(clamp(n.z, -1.0, 1.0));
    float lon = atan(n.y, n.x);
    vec3 view = normalize(cameraPosition - vWorldPos);
    float mu = max(dot(normalize(vWorldN), view), 0.0);
    vec3 c;
    if (uType == 0) {                                        // 태양 — 쌀알 무늬, 가장자리는 어둡고 붉게
      float gran = fbm3(n * 38.0);
      vec3 base = mix(vec3(1.0, 0.62, 0.32), vec3(1.0, 0.95, 0.84), pow(mu, 0.45));
      gl_FragColor = vec4(base * (0.42 + 0.58 * pow(mu, 0.5)) * (0.9 + 0.18 * gran), 1.0);
      return;
    }
    if (uType == 1 && uHasMap > 0.5) c = texture2D(uMap, vec2(0.5 + lon / (2.0 * PI), 0.5 - lat / PI)).rgb;
    else if (uType == 1) c = vec3(0.6);
    else if (uType == 2) {                                   // 수성 — 회색 표면과 크레이터
      c = vec3(0.56, 0.54, 0.51) * (0.82 + 0.3 * fbm3(n * 5.0));
      c *= 1.0 + craters(n, 7.0) * 0.7 + craters(n, 17.0) * 0.35;
    } else if (uType == 3) {                                 // 금성 — 두꺼운 구름이 옆으로 흐른다
      float w = fbm3(vec3(n.x * 2.0 + 0.8 * sin(lat * 6.0), n.y * 2.0, n.z * 7.0));
      c = mix(vec3(0.93, 0.84, 0.62), vec3(1.0, 0.96, 0.86), w);
    } else if (uType == 4) {                                 // 화성 — 붉은 사막, 어두운 지대, 극관
      float d = fbm3(n * 2.2) * 0.7 + fbm3(n * 7.0) * 0.3;
      c = mix(vec3(0.85, 0.47, 0.27), vec3(0.42, 0.24, 0.16), smoothstep(0.5, 0.68, d));
      c = mix(c, vec3(0.97, 0.96, 0.95), smoothstep(1.22, 1.32, abs(lat) + 0.06 * noise(vec2(lon * 6.0, 1.0))));
    } else if (uType == 5) {                                 // 목성 — 밝은 대와 어두운 띠가 소용돌이치고, 남반구에 대적점
      float warp = fbm3(n * vec3(3.0, 3.0, 12.0)) - 0.5;
      float y = lat + warp * 0.06;
      float belt = 0.5 + 0.28 * sin(y * 13.0 + 0.4) + 0.14 * sin(y * 29.0 + 1.3) + 0.08 * sin(y * 53.0);   // 폭이 고르지 않은 띠
      c = mix(vec3(0.74, 0.55, 0.4), vec3(0.94, 0.9, 0.82), smoothstep(0.3, 0.7, belt));
      c = mix(c, vec3(0.9, 0.72, 0.52), (1.0 - smoothstep(0.0, 0.12, abs(lat))) * 0.35);   // 적도대는 옅은 주황
      c *= 0.9 + 0.18 * fbm3(n * vec3(7.0, 7.0, 40.0));
      vec2 spot = vec2((lon - 0.6) * cos(lat) / 0.16, (lat + 0.39) / 0.07);   // 대적점 (남위 약 22도)
      float s = length(spot);
      c = mix(c, vec3(0.78, 0.38, 0.24), smoothstep(1.0, 0.55, s) * 0.9);
      c = mix(c, vec3(0.96, 0.9, 0.82), smoothstep(1.25, 1.05, s) * smoothstep(0.95, 1.05, s) * 0.6);
      c *= 1.0 - 0.3 * smoothstep(1.0, 1.5, abs(lat));
    } else if (uType == 6) {                                 // 토성 — 옅은 황금빛 띠, 북극 쪽은 푸르스름하게
      float warp = fbm3(n * vec3(2.0, 2.0, 9.0)) - 0.5;
      float b = sin((lat + warp * 0.05) * 11.0);
      c = mix(vec3(0.8, 0.69, 0.48), vec3(0.95, 0.88, 0.68), smoothstep(-0.6, 0.6, b));
      c = mix(c, vec3(0.6, 0.66, 0.68), smoothstep(1.2, 1.45, lat) * 0.6);
    } else if (uType == 7) {                                 // 천왕성 — 거의 무늬 없는 청록빛
      c = vec3(0.62, 0.85, 0.9) * (0.96 + 0.05 * sin(lat * 8.0));
    } else {                                                 // 해왕성 — 짙은 푸른빛, 옅은 띠와 흰 구름 줄
      c = vec3(0.3, 0.46, 0.94) * (0.92 + 0.1 * sin(lat * 7.0));
      c = mix(c, vec3(0.92, 0.95, 1.0), smoothstep(0.82, 0.92, fbm3(n * vec3(4.0, 4.0, 16.0))) * 0.7);
    }
    vec3 sun = normalize(uSun);
    float light = dot(normalize(vWorldN), sun);
    float lit = smoothstep(-0.03, 0.12, light) * (0.35 + 0.65 * max(light, 0.0));
    if (uType >= 5) lit *= 0.6 + 0.4 * pow(mu, 0.35);        // 가스 행성 — 가장자리가 어두워진다
    if (uType == 6) {                                        // 토성 — 고리 그림자가 행성 위에
      float tPlane = -dot(vWorldPos - vCenter, vAxis) / dot(sun, vAxis);
      if (tPlane > 0.0) {
        float rr = length(vWorldPos + sun * tPlane - vCenter) / vScale;
        float ringA = smoothstep(1.27, 1.29, rr) * (1.0 - smoothstep(2.33, 2.35, rr));
        lit *= 1.0 - 0.6 * ringA * (1.0 - smoothstep(1.995, 2.005, rr) * (1.0 - smoothstep(2.09, 2.1, rr)));
      }
    }
    if (uType == 3) lit += 0.08 * pow(1.0 - mu, 3.0) * max(light + 0.2, 0.0);   // 금성 — 두꺼운 대기의 테두리 빛
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

  // 토성 고리 — 적도면(자전축에 수직), 실제 반지름 비율. C · B · A 고리의 밝기 차이, 카시니 · 엥케 간극,
  // 행성이 드리우는 그림자(고리 위의 점에서 태양 쪽으로 행성에 가려지는가)
  saturnRings(bodyUniforms) {
    const R = 58232, inner = 74500 / R, outer = 136780 / R;
    const geom = new THREE.RingGeometry(inner, outer, 192, 1);
    const mat = new THREE.ShaderMaterial({
      uniforms: { uSun: bodyUniforms.uSun, uDim: bodyUniforms.uDim },
      vertexShader: /* glsl */ `
        varying float vR;
        varying vec3 vWorldPos;
        varying vec3 vCenter;
        varying float vScale;
        void main() {
          vR = length(position.xy);
          vec4 wp = modelMatrix * vec4(position, 1.0);
          vWorldPos = wp.xyz;
          vCenter = (modelMatrix * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
          vScale = length(modelMatrix[0].xyz);
          gl_Position = projectionMatrix * viewMatrix * wp;
        }`,
      fragmentShader: /* glsl */ `
        uniform vec3 uSun;
        uniform float uDim;
        varying float vR;
        varying vec3 vWorldPos;
        varying vec3 vCenter;
        varying float vScale;
        float band(float r, float a, float b) { return smoothstep(a - 300.0, a + 300.0, r) * (1.0 - smoothstep(b - 300.0, b + 300.0, r)); }
        void main() {
          float r = vR * 58232.0;                            // km
          float C = band(r, 74500.0, 92000.0) * 0.22;
          float B = band(r, 92000.0, 117580.0) * (0.8 + 0.2 * smoothstep(95000.0, 110000.0, r));
          float A = band(r, 122170.0, 136780.0) * 0.6 * (1.0 - band(r, 133420.0, 133745.0));   // 사이 = 카시니 간극, 엥케 간극
          float a = (C + B + A) * (0.9 + 0.1 * sin(r * 0.00045));
          vec3 col = mix(vec3(0.72, 0.64, 0.52), vec3(0.95, 0.88, 0.72), clamp(B + A * 0.6, 0.0, 1.0));
          vec3 s = normalize(uSun), oc = vWorldPos - vCenter;     // 행성 그림자 — 태양 쪽으로 행성에 가려지면 어둡게
          float bq = dot(oc, s), cq = dot(oc, oc) - vScale * vScale;
          float shade = (bq < 0.0 && bq * bq - cq > 0.0) ? 0.12 : 1.0;
          gl_FragColor = vec4(col * uDim * shade, a * 0.95);
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
