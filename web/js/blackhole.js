// 은하 중심 블랙홀 — 영화 「인터스텔라」의 가르강튀아처럼 보이는 모습을, 그림이 아니라 빛의 경로를 계산해 그린다.
//
// 화면의 각 점에서 빛을 거꾸로 쏘아, 슈바르츠실트 블랙홀 둘레에서 휘는 경로를 따라간다 (단위: 슈바르츠실트 반지름 = 1).
//   빛의 궤적: x'' = −(3/2) h² x / r⁵  (h = |x × v|, 뉴턴식 모양이지만 일반상대론의 빛 경로와 같은 휨을 준다)
//   - 빛이 r < 1로 들어가면 돌아오지 못한다 → 검은 그림자
//   - 얇은 강착 원반(적도면, 안쪽 반지름 ISCO 3 근처)을 지날 때마다 빛을 더한다 → 원반 뒤쪽이 그림자 위아래로 휘어 보인다
//   - 원반을 여러 번 도는 빛 → 그림자 가장자리의 얇은 광자 고리
// 영화의 가르강튀아처럼 도플러 밝기 차이는 넣지 않았다. 실제 크기 · 모습이 아니라 계산으로 그린 상상도다.

import { THREE } from "./scene.js";

export const BH_FRAG = /* glsl */ `
  uniform float uTime, uIncl, uRoll, uFade;
  varying vec2 vUv;
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
  }
  // 원반 — 온도는 안쪽일수록 높고(r^-3/4), 고리 무늬는 케플러 회전으로 안쪽이 빨리 돈다
  vec4 disk(vec3 h) {
    float r = length(h.xz);
    if (r < 2.6 || r > 12.0) return vec4(0.0);
    float a = -uTime * 2.2 * pow(r, -1.5);                   // 안쪽일수록 빨리 돈다
    vec2 q = mat2(cos(a), -sin(a), sin(a), cos(a)) * h.xz;   // 각도 대신 회전한 좌표로 — 이음새 없이
    float bands = 0.55 + 0.14 * sin(r * 5.0 + 3.0 * noise(q * 0.7)) + 0.4 * noise(q * 1.6) + 0.22 * noise(q * 5.0);
    float temp = pow(3.0 / r, 0.75) * pow(max(1.0 - sqrt(2.6 / r), 0.0), 0.25);
    float inner = smoothstep(2.6, 3.2, r), outer = 1.0 - smoothstep(8.5, 12.0, r);
    float I = temp * bands * inner * outer * 2.6;
    vec3 c = mix(vec3(1.0, 0.38, 0.08), vec3(1.0, 0.86, 0.62), clamp(temp * 1.2 - 0.1, 0.0, 1.0));
    return vec4(c * I, clamp(I * 1.1, 0.0, 1.0));
  }
  void main() {
    vec2 p = vUv * 2.0 - 1.0;
    float cr = cos(uRoll), sr = sin(uRoll);
    p = mat2(cr, -sr, sr, cr) * p;
    float D = 28.0;
    vec3 ro = vec3(0.0, D * sin(uIncl), -D * cos(uIncl));
    vec3 fw = normalize(-ro);
    vec3 rt = normalize(cross(vec3(0.0, 1.0, 0.0), fw));
    vec3 up = cross(fw, rt);
    vec3 pos = ro;
    vec3 vel = normalize(fw + (p.x * rt + p.y * up) * 0.5);
    float h2 = dot(cross(pos, vel), cross(pos, vel));
    vec3 col = vec3(0.0);
    float alpha = 0.0, minR = 1e9;
    bool captured = false;
    for (int i = 0; i < 300; i++) {
      float r2 = dot(pos, pos);
      float r = sqrt(r2);
      minR = min(minR, r);
      float dt = clamp(0.07 * r, 0.015, 1.2);
      vec3 prev = pos;
      vel += -1.5 * h2 * pos / (r2 * r2 * r) * dt;
      pos += vel * dt;
      if (dot(pos, pos) < 1.0) { captured = true; break; }
      if (prev.y * pos.y < 0.0) {                           // 원반면을 지났다
        vec3 hit = mix(prev, pos, prev.y / (prev.y - pos.y));
        vec4 d = disk(hit);
        col += (1.0 - alpha) * d.rgb;
        alpha += (1.0 - alpha) * d.a;
        if (alpha > 0.98) break;
      }
      if (r > D * 1.3 && dot(pos, vel) > 0.0) break;        // 멀리 빠져나갔다
    }
    if (captured) alpha = 1.0;                              // 그림자 — 뒤의 별빛을 가린다
    else {
      // 휘어 들어온 뒤쪽 별빛 (아인슈타인 고리 근처에 몰린다) + 광자 고리의 옅은 빛
      vec3 d = normalize(vel);
      vec2 sp = vec2(atan(d.z, d.x), asin(d.y)) * 60.0;
      float star = step(0.993, hash(floor(sp))) * smoothstep(0.3, 0.0, length(fract(sp) - 0.5));
      float ring = exp(-(minR - 1.5) * 9.0) * 0.6;
      float haze = 0.22 * exp(-dot(p, p) * 5.0);                // 원반 빛의 번짐
      col += (1.0 - alpha) * (vec3(0.85, 0.9, 1.0) * star * 0.7 + vec3(1.0, 0.75, 0.45) * ring + vec3(1.0, 0.62, 0.32) * haze);
      alpha += (1.0 - alpha) * clamp(star * 0.7 + ring + haze, 0.0, 1.0);
    }
    col = vec3(1.0) - exp(-col * 1.35);                          // 눈부신 안쪽은 흰빛으로 (톤 매핑)
    float edge = 1.0 - smoothstep(0.82, 1.0, length(vUv * 2.0 - 1.0));   // 사각형 가장자리가 보이지 않게
    gl_FragColor = vec4(col * edge * uFade, alpha * edge * uFade);   // 미리 곱한 알파
  }`;

const VERT = /* glsl */ `
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

// 늘 카메라를 보는 사각형. 원반을 보는 기울기(uIncl)는 카메라와 원반 법선의 각도로 — 돌아보면 모습이 바뀐다
export const BILLBOARD_VERT = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    vec4 center = modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);
    vec2 scale = vec2(length(modelMatrix[0].xyz), length(modelMatrix[1].xyz));
    gl_Position = projectionMatrix * (center + vec4(position.xy * scale, 0.0, 0.0));
  }`;

export function blackHoleMaterial({ billboard = false } = {}) {
  return new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uIncl: { value: 0.06 }, uRoll: { value: 0.12 }, uFade: { value: 1 } },
    vertexShader: billboard ? BILLBOARD_VERT : VERT, fragmentShader: BH_FRAG,
    transparent: true, depthWrite: false, premultipliedAlpha: true,
    blending: THREE.CustomBlending, blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor,
  });
}

// 우주 지도 위의 블랙홀 — 은하 중심에. normal: 원반 법선 (은하마다 다르게)
export class BlackHoleSprite {
  constructor(normal) {
    this.material = blackHoleMaterial({ billboard: true });
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), this.material);
    this.mesh.renderOrder = 6;
    this.mesh.frustumCulled = false;
    this.normal = normal.clone().normalize();
  }

  update(t, camera) {
    const u = this.material.uniforms;
    u.uTime.value = t;
    const toCam = camera.position.clone().sub(this.mesh.getWorldPosition(new THREE.Vector3())).normalize();
    const e = Math.asin(THREE.MathUtils.clamp(toCam.dot(this.normal), -1, 1));
    u.uIncl.value = Math.sign(e || 1) * Math.max(Math.abs(e), 0.06);   // 원반 바로 옆에서도 조금은 위에서
  }
}

// 서랍 안 작은 화면 — 같은 계산을 따로 그린다. 서랍이 바뀌면(캔버스가 문서에서 빠지면) 멈추고 정리한다
export function mountBlackHole(canvas, { still = false } = {}) {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false, premultipliedAlpha: true });
  } catch {
    return null;                                      // WebGL을 쓸 수 없으면 그림 없이 글만
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-0.5, 0.5, 0.5, -0.5, 0.1, 10);
  camera.position.z = 1;
  const material = blackHoleMaterial();
  scene.add(new THREE.Mesh(new THREE.PlaneGeometry(1, 1), material));
  const size = () => {
    const w = canvas.clientWidth || 320, h = canvas.clientHeight || 200;
    renderer.setSize(w, h, false);
    Object.assign(camera, { left: -0.5 * w / h, right: 0.5 * w / h, top: 0.5, bottom: -0.5 });   // 높이에 맞춘 정사각형
    camera.updateProjectionMatrix();
  };
  size();
  const t0 = performance.now();
  let raf = 0;
  const frame = () => {
    if (!canvas.isConnected) { renderer.dispose(); material.dispose(); return; }
    material.uniforms.uTime.value = still ? 2 : (performance.now() - t0) / 1000;
    renderer.render(scene, camera);
    if (!still) raf = requestAnimationFrame(frame);
  };
  frame();
  return { stop: () => { cancelAnimationFrame(raf); renderer.dispose(); material.dispose(); } };
}

let listPromise;
// web/data/blackholes.json — 근거(위키 문서 문장 · Wikidata)가 있는 은하 중심 블랙홀
export function loadBlackHoles() {
  listPromise ??= fetch("data/blackholes.json").then((r) => (r.ok ? r.json() : { galaxies: [] }))
    .catch(() => ({ galaxies: [] }));
  return listPromise;
}
