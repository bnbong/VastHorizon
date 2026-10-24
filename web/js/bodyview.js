// 서랍 안 근접 3D 뷰 — 태양계 천체를 가까이서 본 모습. 태양 쪽 빛을 받으며 천천히 돈다 (blackhole.js의 서랍 안 작은 화면과 같은 구조).
//
// - 표면은 사진이 아니라 알려진 특징(탐사선 사진 · 관측으로 알려진 색 · 지형)을 바탕으로 절차적으로 그린 상상도다.
//   지구의 대륙 · 구름도 실제 지도가 아니라 잡음으로 만든 모양이다.
// - 크기 · 모양 표: solarbodies.js BODY_TABLE (반지름 · 세 축 크기 출처는 그 파일에).
// - 구가 아닌 천체(포보스 · 데이모스 · 베스타 · 베누 · 류구 · 아포피스 · 아로코트 · 혜성 핵)는 구 지오메트리를 잡음으로 일그러뜨린다.
//   베누 · 류구는 적도가 불룩한 팽이 모양, 아로코트 · 67P는 두 덩이, 핼리 혜성 핵은 땅콩 모양. 혜성은 핵 둘레에 희미한 코마.
// - 하늘에서 이미 그리는 태양 · 달 · 행성은 solar.js의 셰이더(BODY_FRAG)와 토성 고리를 그대로 쓴다.
// - 한 번에 하나만 — 새로 띄우면 앞의 것을 정리한다. 정리할 때 WebGL 컨텍스트까지 놓아 준다 (forceContextLoss).

import { THREE } from "./scene.js";
import { mergeVertices } from "three/addons/utils/BufferGeometryUtils.js";
import { BODY_FRAG, BODY_VERT, TYPES, saturnRings } from "./solar.js";
import { axisRatios, bodyInfo } from "./solarbodies.js";

// 표면 무늬 번호 — SURFACE_FRAG의 uSurf 분기
const SURFACES = { earth: 0, io: 1, europa: 2, ganymede: 3, callisto: 4, titan: 5, enceladus: 6, triton: 7, charon: 8, pluto: 9,
                   ceres: 10, eris: 11, makemake: 12, haumea: 13, phobos: 14, deimos: 15, vesta: 16, bennu: 17, ryugu: 18,
                   apophis: 19, arrokoth: 20, comet: 21 };
// 대기가 있는 천체 — 가장자리가 빛난다 (지구는 푸르게, 타이탄은 주황 안개)
const GLOW = { earth: [0.45, 0.68, 1.0, 0.55, 0.09], titan: [1.0, 0.62, 0.25, 0.9, 0.14], comet: [0.78, 0.86, 1.0, 0.36, 1.15],
               sun: [1.0, 0.62, 0.3, 0.9, 0.25], venus: [1.0, 0.92, 0.75, 0.3, 0.06] };
// 처음 보이는 면의 경도(라디안, 셰이더의 atan(y, x)) — 명왕성의 하트 · 세레스의 오카토르 · 이오의 화산이 앞에 오게
// 길쭉한 천체는 긴 축(x)이 옆으로 눕게 (경도 π/2가 앞)
const FRONT_LON = { pluto: 0.25, ceres: 1.2, charon: 0.4 };
const SIDEWAYS = Math.PI / 2 + 0.35;
const SOUTH_UP = new Set(["enceladus"]);
// 그림의 빛 — 왼쪽 위 앞에서 비춘다 (낮과 밤의 경계가 보이게). 실제 그날의 태양 방향이 아니라 보기 좋은 고정 방향이다
export const SUN_DIR = new THREE.Vector3(-0.72, 0.38, 0.58).normalize();

const SURFACE_VERT = /* glsl */ `
  varying vec3 vP;
  varying vec3 vN;
  varying vec3 vW;
  void main() {
    vP = position;                                           // 천체 좌표 (z 자전축) — 무늬가 함께 돈다
    vN = normalize(mat3(modelMatrix) * normal);
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vW = wp.xyz;
    gl_Position = projectionMatrix * viewMatrix * wp;
  }`;

const SURFACE_FRAG = /* glsl */ `
  uniform int uSurf;
  uniform vec3 uSun;
  uniform float uTime, uNeck;
  varying vec3 vP;
  varying vec3 vN;
  varying vec3 vW;
  float hash3(vec3 p) { return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
  float vnoise(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash3(i), hash3(i + vec3(1, 0, 0)), f.x), mix(hash3(i + vec3(0, 1, 0)), hash3(i + vec3(1, 1, 0)), f.x), f.y),
               mix(mix(hash3(i + vec3(0, 0, 1)), hash3(i + vec3(1, 0, 1)), f.x), mix(hash3(i + vec3(0, 1, 1)), hash3(i + vec3(1, 1, 1)), f.x), f.y), f.z);
  }
  float fbm(vec3 p) {
    float s = 0.0, a = 0.5;
    for (int i = 0; i < 5; i++) { s += a * vnoise(p); p = p * 2.03 + 11.7; a *= 0.5; }
    return s / 0.97;
  }
  // 크레이터 — 3차원 칸마다 하나 (밀도 density). x: 움푹한 바닥 · y: 테두리 · z: 밝은 분출물 번짐
  vec3 craters(vec3 p, float density, float size) {
    vec3 ip = floor(p), res = vec3(0.0);
    for (int i = -1; i <= 1; i++) for (int j = -1; j <= 1; j++) for (int k = -1; k <= 1; k++) {
      vec3 c = ip + vec3(float(i), float(j), float(k));
      if (hash3(c) > density) continue;
      vec3 o = c + vec3(hash3(c + 1.3), hash3(c + 7.1), hash3(c + 3.7));
      float r = size * (0.35 + 0.65 * hash3(c + 11.0));
      float d = length(p - o);
      res.x = max(res.x, smoothstep(r, r * 0.55, d));
      res.y = max(res.y, smoothstep(r * 1.3, r, d) * smoothstep(r * 0.7, r, d));
      res.z = max(res.z, smoothstep(r * 2.4, r * 0.5, d));
    }
    return res;
  }
  // 칸 경계 — 가장 가까운 두 점까지 거리의 차 (트리톤의 캔털루프 무늬)
  float cellEdge(vec3 p) {
    vec3 ip = floor(p);
    float d1 = 9.0, d2 = 9.0;
    for (int i = -1; i <= 1; i++) for (int j = -1; j <= 1; j++) for (int k = -1; k <= 1; k++) {
      vec3 c = ip + vec3(float(i), float(j), float(k));
      float d = length(p - c - vec3(hash3(c + 1.3), hash3(c + 7.1), hash3(c + 3.7)));
      if (d < d1) { d2 = d1; d1 = d; } else if (d < d2) d2 = d;
    }
    return d2 - d1;
  }
  // 선 무늬 — 잡음의 등고선 한 줄 (유로파의 균열 · 가니메데의 홈)
  float lineae(vec3 p, float width) {
    float v = vnoise(p) * 0.62 + vnoise(p * 2.3 + 4.1) * 0.38;             // 부드러운 잡음 — 등고선이 길게 이어진다
    return 1.0 - smoothstep(width * 0.35, width, abs(v - 0.5));
  }

  vec3 surface(vec3 p) {
    vec3 n = normalize(p);
    float lat = asin(clamp(n.z, -1.0, 1.0)), lon = atan(n.y, n.x);
    vec3 c;
    if (uSurf == 0) {                                        // 지구 — 바다 · 대륙 · 사막 · 극관 · 구름
      float h = fbm(n * 1.7 + 3.1) + 0.3 * fbm(n * 5.5 - 2.0);
      float land = smoothstep(0.655, 0.675, h);
      c = mix(vec3(0.02, 0.08, 0.24), vec3(0.05, 0.2, 0.4), smoothstep(0.6, 0.66, h));
      float dry = smoothstep(0.3, 0.05, abs(abs(lat) - 0.42)) * smoothstep(0.45, 0.7, vnoise(n * 4.0 + 5.0));
      vec3 ground = mix(vec3(0.15, 0.3, 0.11), vec3(0.66, 0.55, 0.34), dry);
      ground = mix(ground, vec3(0.38, 0.33, 0.25), smoothstep(0.86, 0.98, h));
      c = mix(c, ground, land);
      c = mix(c, vec3(0.93, 0.95, 0.98), smoothstep(1.12, 1.2, abs(lat) + 0.12 * vnoise(n * 6.0)));
      vec3 q = vec3(n.x * cos(uTime * 0.03) - n.y * sin(uTime * 0.03), n.x * sin(uTime * 0.03) + n.y * cos(uTime * 0.03), n.z);
      float cl = fbm(q * vec3(2.6, 2.6, 5.5) + 0.8 * fbm(q * 3.0));
      c = mix(c, vec3(0.98), smoothstep(0.56, 0.76, cl) * 0.88);
    } else if (uSurf == 1) {                                 // 이오 — 노랑 · 주황 황, 흰 서리, 어두운 화산 반점과 붉은 둘레
      c = mix(vec3(0.94, 0.86, 0.42), vec3(0.86, 0.56, 0.22), smoothstep(0.42, 0.68, fbm(n * 2.6)));
      c = mix(c, vec3(0.96, 0.94, 0.8), smoothstep(0.58, 0.72, fbm(n * 4.5 + 7.0)) * 0.55);
      c = mix(c, vec3(0.7, 0.48, 0.34), smoothstep(0.9, 1.35, abs(lat)) * 0.65);
      vec3 v = craters(n * 6.0, 0.4, 0.22);
      c = mix(c, vec3(0.78, 0.3, 0.12), v.z * 0.45);
      c = mix(c, vec3(0.1, 0.07, 0.05), v.x * 0.92);
    } else if (uSurf == 2) {                                 // 유로파 — 밝은 얼음 위 갈색 균열
      c = mix(vec3(0.93, 0.91, 0.87), vec3(0.8, 0.68, 0.55), smoothstep(0.55, 0.8, fbm(n * 2.2)) * 0.55);
      float L = max(lineae(n * 2.4 + 1.0, 0.014), max(lineae(n * 3.7 + 9.0, 0.011) * 0.85, lineae(n * 6.3 - 4.0, 0.008) * 0.6));
      c = mix(c, vec3(0.55, 0.32, 0.18), L * 0.85);
    } else if (uSurf == 3) {                                 // 가니메데 — 어두운 회갈색 지대와 홈 파인 밝은 지대, 밝은 크레이터
      float f = fbm(n * 2.0 + 4.0);
      float groove = lineae(n * 7.0 + 2.0, 0.05) + lineae(n * 11.0 - 6.0, 0.04);
      c = mix(vec3(0.34, 0.3, 0.26), vec3(0.66, 0.64, 0.6) * (1.0 - 0.1 * groove), smoothstep(0.45, 0.56, f + 0.04 * vnoise(n * 12.0)));
      vec3 k = craters(n * 8.0, 0.32, 0.24);
      c = mix(c, vec3(0.9, 0.9, 0.88), k.z * 0.55);
      c = mix(c, vec3(0.86, 0.87, 0.9), smoothstep(1.0, 1.3, abs(lat)) * 0.45);
    } else if (uSurf == 4) {                                 // 칼리스토 — 어두운 표면에 밝은 크레이터가 빽빽이
      c = vec3(0.27, 0.24, 0.21) * (0.85 + 0.3 * fbm(n * 3.0));
      vec3 k = craters(n * 14.0, 0.55, 0.22);
      c = mix(c, vec3(0.78, 0.76, 0.72), k.z * 0.6 + k.y * 0.3);
      vec3 k2 = craters(n * 5.0, 0.25, 0.3);
      c = mix(c, vec3(0.7, 0.68, 0.64), k2.y * 0.5);
    } else if (uSurf == 5) {                                 // 타이탄 — 짙은 주황 안개, 옅은 띠
      c = mix(vec3(0.84, 0.56, 0.22), vec3(0.72, 0.45, 0.17), 0.5 + 0.5 * sin(lat * 3.0 + 2.0 * fbm(n * 1.5)));
      c = mix(c, vec3(0.62, 0.42, 0.22), smoothstep(1.1, 1.4, lat) * 0.5);   // 북극의 어두운 두건
    } else if (uSurf == 6) {                                 // 엔셀라두스 — 아주 밝은 얼음, 남극의 푸른 호랑이 줄무늬
      c = vec3(0.96, 0.97, 0.99) * (0.93 + 0.07 * fbm(n * 4.0));
      vec3 k = craters(n * 9.0, 0.4, 0.28);
      c *= 1.0 - 0.14 * k.x * smoothstep(-0.1, 0.3, n.z);
      float d = dot(n.xy, vec2(0.8, 0.6)) + 0.03 * (vnoise(n * 9.0) - 0.5);
      float s = abs(fract(d / 0.15 + 0.5) - 0.5);
      float stripe = (1.0 - smoothstep(0.04, 0.1, s)) * step(abs(d), 0.3) * smoothstep(-0.62, -0.8, n.z);
      c = mix(c, vec3(0.45, 0.6, 0.74), stripe * 0.9);
    } else if (uSurf == 7) {                                 // 트리톤 — 분홍빛 질소 얼음 극관, 캔털루프 지형
      c = vec3(0.86, 0.75, 0.71) * (0.9 + 0.15 * fbm(n * 3.0));
      float cap = smoothstep(0.0, -0.25, n.z + 0.1 * (vnoise(n * 5.0) - 0.5));
      c = mix(c, vec3(0.96, 0.87, 0.84), cap);
      c = mix(c, vec3(0.5, 0.4, 0.37), cap * smoothstep(0.62, 0.8, fbm(vec3(n.x * 3.0, n.y * 3.0, n.z * 14.0))) * 0.5);   // 극관의 어두운 줄 (간헐천 자국)
      float edge = cellEdge(n * 10.0);                       // 캔털루프 — 움푹한 칸과 그 사이의 낮은 능선
      vec3 cant = vec3(0.74, 0.71, 0.62) * (0.86 + 0.1 * (1.0 - smoothstep(0.0, 0.12, edge)) - 0.08 * smoothstep(0.15, 0.5, edge));
      c = mix(c, cant, smoothstep(0.05, 0.3, n.z) * smoothstep(0.2, 0.6, sin(lon + 0.5) + 0.3 * vnoise(n * 4.0)));
    } else if (uSurf == 8) {                                 // 카론 — 회색, 북극의 붉은 반점 (모르도르 반점)
      c = vec3(0.56, 0.54, 0.53) * (0.82 + 0.3 * fbm(n * 3.0));
      vec3 k = craters(n * 7.0, 0.35, 0.25);
      c *= 1.0 - 0.25 * k.x + 0.2 * k.y;
      c = mix(c, vec3(0.48, 0.23, 0.15), smoothstep(0.72, 0.86, n.z + 0.08 * (vnoise(n * 6.0) - 0.5)));
    } else if (uSurf == 9) {                                 // 명왕성 — 밝은 하트(톰보 지역 · 스푸트니크 평원), 적갈색 크툴루 지대
      c = vec3(0.74, 0.6, 0.47) * (0.86 + 0.24 * fbm(n * 3.0));
      c = mix(c, vec3(0.78, 0.72, 0.6), smoothstep(0.7, 0.9, n.z) * 0.6);
      // 크툴루 지대 — 하트 서쪽 적도를 따라 길게 누운 어두운 지대, 동쪽에도 어두운 반점들
      float wob = 0.25 * (fbm(n * 5.0) - 0.5);
      float cth = 1.0 - smoothstep(0.8, 1.0, length(vec2((lon + 1.55) / 0.95, (lat + 0.17) / 0.24)) + wob);
      float east = 1.0 - smoothstep(0.8, 1.0, length(vec2((lon - 1.6) / 0.55, (lat + 0.12) / 0.2)) + wob);
      c = mix(c, vec3(0.3, 0.14, 0.09), max(cth, east * 0.85) * (0.85 + 0.15 * fbm(n * 8.0)));
      float x = lon / 0.52, y = (lat - 0.3) / 0.45 + 0.06 * (vnoise(n * 10.0) - 0.5);
      float k = x * x + y * y - 1.0;                         // 하트 곡선 (x² + y² − 1)³ − x²y³ ≤ 0 — pow는 음수 밑을 못 받아 곱으로
      float hv = k * k * k - x * x * y * y * y;
      float heart = 1.0 - smoothstep(-0.04, 0.04, hv);
      c = mix(c, x < 0.0 ? vec3(0.99, 0.96, 0.91) : vec3(0.93, 0.88, 0.82), heart);
    } else if (uSurf == 10) {                                // 세레스 — 어두운 회색, 크레이터, 오카토르의 밝은 점
      c = vec3(0.4, 0.39, 0.38) * (0.84 + 0.3 * fbm(n * 3.0));
      vec3 k = craters(n * 7.0, 0.42, 0.28);
      c *= 1.0 - 0.3 * k.x + 0.25 * k.y;
      vec3 occ = normalize(vec3(cos(0.35) * cos(1.2), cos(0.35) * sin(1.2), sin(0.35)));
      float d = length(n - occ);
      c *= 1.0 - 0.25 * smoothstep(0.1, 0.07, d) + 0.25 * smoothstep(0.12, 0.1, d) * smoothstep(0.08, 0.1, d);
      c = mix(c, vec3(1.0), smoothstep(0.026, 0.01, d) + smoothstep(0.016, 0.006, length(n - normalize(occ + vec3(0.04, -0.03, 0.02)))));
    } else if (uSurf == 11) {                                // 에리스 — 아주 밝은 얼음
      c = vec3(0.92, 0.92, 0.9) * (0.94 + 0.08 * fbm(n * 3.0));
    } else if (uSurf == 12) {                                // 마케마케 — 밝지만 붉은 기가 도는 얼음
      c = mix(vec3(0.9, 0.8, 0.7), vec3(0.74, 0.56, 0.44), smoothstep(0.52, 0.72, fbm(n * 2.5)) * 0.7);
    } else if (uSurf == 13) {                                // 하우메아 — 밝은 결정질 얼음
      c = vec3(0.93, 0.93, 0.95) * (0.92 + 0.1 * fbm(n * 3.0));
    } else if (uSurf == 14) {                                // 포보스 — 어두운 회색, 나란한 홈, 크레이터
      c = vec3(0.36, 0.33, 0.3) * (0.85 + 0.3 * fbm(p * 3.0));
      c *= 0.92 + 0.08 * smoothstep(0.3, 0.9, sin(p.z * 40.0 + p.x * 8.0 + 3.0 * vnoise(p * 4.0)));
      vec3 k = craters(p * 6.0, 0.45, 0.3);
      c *= 1.0 - 0.3 * k.x + 0.2 * k.y;
    } else if (uSurf == 15) {                                // 데이모스 — 먼지에 덮인 매끈한 표면
      c = vec3(0.5, 0.46, 0.41) * (0.88 + 0.22 * fbm(p * 2.5));
      vec3 k = craters(p * 5.0, 0.3, 0.3);
      c *= 1.0 - 0.15 * k.x;
    } else if (uSurf == 16) {                                // 베스타 — 밝고 어두운 얼룩, 크레이터
      c = mix(vec3(0.62, 0.6, 0.56), vec3(0.4, 0.38, 0.35), smoothstep(0.45, 0.7, fbm(p * 2.5)));
      vec3 k = craters(p * 7.0, 0.45, 0.28);
      c *= 1.0 - 0.25 * k.x + 0.25 * k.y;
    } else if (uSurf == 17 || uSurf == 18) {                  // 베누 · 류구 — 아주 어두운 탄소질, 바윗덩이
      c = (uSurf == 17 ? vec3(0.25, 0.235, 0.22) : vec3(0.22, 0.205, 0.195)) * (0.85 + 0.25 * fbm(p * 4.0));
      vec3 k = craters(p * 18.0, 0.5, 0.25);
      c *= 1.0 + 0.6 * k.x * (hash3(floor(p * 18.0)) - 0.4);
    } else if (uSurf == 19) {                                // 아포피스 — 석질(S형), 회갈색
      c = vec3(0.56, 0.51, 0.45) * (0.85 + 0.25 * fbm(p * 3.5));
      vec3 k = craters(p * 8.0, 0.35, 0.25);
      c *= 1.0 - 0.15 * k.x;
    } else if (uSurf == 20) {                                // 아로코트 — 붉은 표면, 두 덩이가 이어진 목은 밝게
      c = vec3(0.62, 0.36, 0.25) * (0.85 + 0.25 * fbm(p * 3.0));
      c = mix(c, vec3(0.8, 0.6, 0.5), smoothstep(0.1, 0.0, abs(p.x - uNeck)) * 0.7);
    } else {                                                 // 혜성 핵 — 아주 어두운 표면, 군데군데 밝은 매끈한 땅
      c = vec3(0.12, 0.11, 0.1) * (0.8 + 0.4 * fbm(p * 3.5));
      c = mix(c, vec3(0.3, 0.28, 0.26), smoothstep(0.62, 0.72, fbm(p * 2.0 + 5.0)) * 0.6);
    }
    return c;
  }

  void main() {
    vec3 c = surface(vP);
    vec3 N = normalize(vN), L = normalize(uSun), V = normalize(cameraPosition - vW);
    float mu0 = dot(N, L), mu = max(dot(N, V), 0.0);
    float term = smoothstep(-0.03, 0.12, mu0);
    float lam = max(mu0, 0.0);
    float lit;
    if (uSurf == 0 || uSurf == 5) lit = term * (0.12 + 0.88 * lam);
    else lit = term * mix(lam, min(2.0 * lam / (lam + mu + 0.05), 1.4) * 0.7, 0.45);   // 공기 없는 천체 — 가장자리까지 밝다 (로멜-젤리거)
    vec3 col = c * (lit + 0.025);
    if (uSurf == 0) col += vec3(0.35, 0.55, 1.0) * pow(1.0 - mu, 3.0) * smoothstep(-0.25, 0.4, mu0) * 0.55;   // 대기 테두리
    if (uSurf == 5) col += vec3(1.0, 0.62, 0.26) * pow(1.0 - mu, 2.0) * smoothstep(-0.45, 0.35, mu0) * 0.75;  // 안개 테두리 — 밤 쪽까지 번진다
    gl_FragColor = vec4(col, 1.0);
  }`;

// 테두리 빛 · 코마 — 천체 뒤의 카메라를 보는 판. 반지름 1(천체 가장자리) 바깥으로 번진다
const GLOW_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform vec2 uSun2;
  uniform float uStrength, uWidth;
  varying vec2 vUv;
  void main() {
    vec2 q = (vUv * 2.0 - 1.0) * 3.0;
    float r = length(q);
    // 대기는 가장자리 바깥으로 얇게, 코마는 핵을 감싸는 넓은 빛무리
    float g = uWidth > 0.5 ? exp(-r * r / (uWidth * uWidth)) : (r < 1.0 ? 1.0 : exp(-(r - 1.0) / uWidth));
    g *= 0.55 + 0.45 * clamp(dot(normalize(q + 1e-4), uSun2) + 0.5, 0.0, 1.0);
    gl_FragColor = vec4(uColor, clamp(g * uStrength, 0.0, 1.0));       // 더하기 섞기 — 알파만큼 더해진다
  }`;

// ── 모양 — 구를 잡음으로 일그러뜨린다 (CPU에서 한 번) ─────────────────────────────

function hashString(s) {
  let h = 2166136261;
  for (const ch of s) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return ((h >>> 0) % 1000) / 10;
}
const fract = (x) => x - Math.floor(x);
const hash3 = (x, y, z) => fract(Math.sin(x * 127.1 + y * 311.7 + z * 74.7) * 43758.5453);
function vnoise(x, y, z) {
  const ix = Math.floor(x), iy = Math.floor(y), iz = Math.floor(z);
  const s = (t) => t * t * (3 - 2 * t);
  const fx = s(x - ix), fy = s(y - iy), fz = s(z - iz);
  const l = (a, b, t) => a + (b - a) * t;
  const h = (dx, dy, dz) => hash3(ix + dx, iy + dy, iz + dz);
  return l(l(l(h(0, 0, 0), h(1, 0, 0), fx), l(h(0, 1, 0), h(1, 1, 0), fx), fy),
           l(l(h(0, 0, 1), h(1, 0, 1), fx), l(h(0, 1, 1), h(1, 1, 1), fx), fy), fz);
}
function fbm(x, y, z, oct = 4) {
  let s = 0, a = 0.5, n = 0;
  for (let i = 0; i < oct; i++) { s += a * vnoise(x, y, z); n += a; x = x * 2.03 + 11.7; y = y * 2.03 + 11.7; z = z * 2.03 + 11.7; a *= 0.5; }
  return s / n;
}

// 크레이터 자국 — 방향 c를 중심으로 각반지름 r(라디안)의 움푹한 그릇과 둥근 테두리 (반지름 비율로 더한다)
function dip(n, c, r, depth) {
  const d = Math.acos(Math.max(-1, Math.min(1, n[0] * c[0] + n[1] * c[1] + n[2] * c[2]))) / r;
  if (d > 1.4) return 0;
  return d < 1 ? -depth * (1 - d * d) : depth * 0.35 * Math.exp(-((d - 1.1) ** 2) / 0.02);
}

// 덩이 하나 — 단위 방향 n에서의 반지름 비율 (잡음 · 크레이터 · 팽이 모양)
function lobeRadius(n, { seed, rough, craters = 10, top = 0, waist = 0, big = [] }) {
  let r = 1 + rough * (fbm(n[0] * 1.3 + seed, n[1] * 1.3, n[2] * 1.3) - 0.5) * 2 + rough * 0.4 * (fbm(n[0] * 4 + seed, n[1] * 4, n[2] * 4) - 0.5);
  if (top) {                                            // 팽이 — 위아래가 원뿔처럼 줄고 적도가 능선
    const rho = Math.sqrt(1 - n[2] * n[2]);
    r *= 1 - top + top / (Math.abs(n[2]) / 0.95 + rho);
  }
  if (waist) r *= 1 - waist * Math.exp(-(n[0] * n[0]) / 0.08);   // 땅콩 — 가운데가 잘록하게
  for (let i = 0; i < craters; i++) {
    const u = hash3(seed, i, 1) * 2 - 1, phi = hash3(seed, i, 2) * Math.PI * 2, s = Math.sqrt(1 - u * u);
    r += dip(n, [s * Math.cos(phi), s * Math.sin(phi), u], 0.12 + 0.25 * hash3(seed, i, 3), 0.04 + 0.04 * hash3(seed, i, 4));
  }
  for (const b of big) r += dip(n, b.dir, b.r, b.depth);
  return r;
}

// 덩이 지오메트리 — 세 축 반지름 axes, 중심 center (가장 긴 축의 반이 1이 되는 단위)
function lobeGeometry(axes, center, opts, detail = 48) {
  let geo = new THREE.IcosahedronGeometry(1, detail);
  geo.deleteAttribute("normal");
  geo.deleteAttribute("uv");
  geo = mergeVertices(geo);                            // 이음새 없는 부드러운 법선
  const pos = geo.attributes.position;
  for (let i = 0; i < pos.count; i++) {
    const n = [pos.getX(i), pos.getY(i), pos.getZ(i)];
    const k = Math.hypot(...n);
    const u = n.map((v) => v / k);
    const r = lobeRadius(u, opts);
    pos.setXYZ(i, center[0] + u[0] * r * axes[0], center[1] + u[1] * r * axes[1], center[2] + u[2] * r * axes[2]);
  }
  geo.computeVertexNormals();
  return geo;
}

// 천체 모양 → 지오메트리 목록 (덩이마다 하나). 가장 긴 축의 반을 1로 맞춘다
export function bodyGeometries(info) {
  const seed = hashString(info.key);
  const [a, b, c] = axisRatios(info);
  if (info.shape === "sphere") return [new THREE.SphereGeometry(1, 96, 64)];
  if (info.shape === "ellipsoid") {
    const g = new THREE.SphereGeometry(1, 96, 64);
    g.scale(a, b, c);
    return [g];
  }
  if (info.shape === "top") return [lobeGeometry([a, b, c], [0, 0, 0], { seed, rough: 0.05, craters: 8, top: 0.5 })];
  if (info.lobes) {                                     // 두 덩이 — 큰 덩이 옆에 작은 덩이를 붙이고, 전체를 반지름 1 안에 맞춘다
    const comet = info.shape === "comet";
    const [A, B] = info.lobes.map((l) => l.map((v) => v / 2));                 // 세 축 반지름 (km)
    // 아로코트는 긴 축으로 나란히, 67P는 작은 덩이(머리)가 비스듬히 얹혀 있다
    const dir = comet ? [0.72, 0, 0.69] : [1, 0, 0];
    // 두 타원체가 dir 쪽으로 내민 길이(지지 함수)의 합보다 조금 가깝게 — 목이 맞붙는다
    const reach = (r) => Math.hypot(r[0] * dir[0], r[1] * dir[1], r[2] * dir[2]);
    const gap = (reach(A) + reach(B)) * (comet ? 0.76 : 0.88);
    const geos = [
      lobeGeometry(A, [0, 0, 0], { seed, rough: comet ? 0.12 : 0.05, craters: comet ? 4 : 6 }, 40),
      lobeGeometry(B, dir.map((v) => v * gap), { seed: seed + 3, rough: comet ? 0.12 : 0.05, craters: comet ? 3 : 5 }, 36),
    ];
    const box = new THREE.Box3();
    for (const g of geos) { g.computeBoundingBox(); box.union(g.boundingBox); }
    const center = box.getCenter(new THREE.Vector3());
    let r = 0;                                          // 가운데에서 가장 먼 꼭짓점이 1이 되게
    for (const g of geos) {
      g.translate(-center.x, -center.y, -center.z);
      const p = g.attributes.position;
      for (let i = 0; i < p.count; i++) r = Math.max(r, Math.hypot(p.getX(i), p.getY(i), p.getZ(i)));
    }
    for (const g of geos) g.scale(1 / r, 1 / r, 1 / r);
    return geos;
  }
  const big = [];
  if (info.key === "phobos") big.push({ dir: [1, 0, 0], r: 0.5, depth: 0.16 });           // 스티크니 크레이터
  if (info.key === "vesta") big.push({ dir: [0, 0, -1], r: 0.9, depth: 0.12 });          // 남극의 레아실비아 분지
  const comet = info.shape === "comet";
  return [lobeGeometry([a, b, c], [0, 0, 0], { seed, rough: comet ? 0.1 : info.key === "deimos" ? 0.06 : 0.09,
                                               craters: info.key === "deimos" ? 4 : 12, waist: comet ? 0.3 : 0, big })];
}

// ── 천체 메시 ──────────────────────────────────────────────────────────

// 그 천체의 메시 — 지름 2(반지름 1, 토성은 고리까지 더 넓다). 서랍 근접 뷰와 지도(bodyshelf.js)가 함께 쓴다.
// 반환: { tilt (바깥 그룹, 장면에 넣는다), spin (자전 — rotation.z), uniforms (uSun · uTime 갱신용), start (처음 보이는 면의 회전각) }
// track: 정리할 지오메트리 · 재질 · 텍스처를 넘겨받는다. onLoad: 달 텍스처가 도착했을 때
export function buildBodyMesh(info, { track = (x) => x, onLoad } = {}) {
  // 기울기 — 자전축(z)을 화면 위쪽으로, 조금 앞 · 옆으로 기울여 극 쪽 무늬도 보이게 (엔셀라두스는 남극 줄무늬가 보이게 남쪽을 앞으로)
  const tilt = new THREE.Group();
  tilt.rotation.set(-Math.PI / 2 + (SOUTH_UP.has(info.key) ? -0.62 : 0.38), 0, 0.32);
  const spin = new THREE.Group();
  tilt.add(spin);

  let uniforms;
  if (info.planet) {
    uniforms = { uType: { value: TYPES[info.key] }, uSun: { value: SUN_DIR.clone() }, uMap: { value: null },
                 uHasMap: { value: 0 }, uDim: { value: 1 } };
    if (info.key === "moon") {
      uniforms.uMap.value = track(new THREE.TextureLoader().load("data/textures/moon_lroc_1k.jpg", () => { uniforms.uHasMap.value = 1; onLoad?.(); }));
      uniforms.uMap.value.colorSpace = THREE.SRGBColorSpace;
    }
    const mat = track(new THREE.ShaderMaterial({ uniforms, vertexShader: BODY_VERT, fragmentShader: BODY_FRAG }));
    spin.add(new THREE.Mesh(track(new THREE.SphereGeometry(1, 96, 64)), mat));
    if (info.key === "saturn") {
      const rings = saturnRings(uniforms);
      track(rings.geometry);
      track(rings.material);
      spin.add(rings);
    }
  } else {
    uniforms = { uSurf: { value: SURFACES[info.surface] }, uSun: { value: SUN_DIR.clone() }, uTime: { value: 0 }, uNeck: { value: 0 } };
    const geos = bodyGeometries(info).map(track);
    if (info.key === "arrokoth") {                      // 두 덩이가 맞닿은 자리
      geos[0].computeBoundingBox();
      uniforms.uNeck.value = geos[0].boundingBox.max.x - 0.03;
    }
    const mat = track(new THREE.ShaderMaterial({ uniforms, vertexShader: SURFACE_VERT, fragmentShader: SURFACE_FRAG }));
    for (const g of geos) spin.add(new THREE.Mesh(g, mat));
    spin.userData.uniforms = uniforms;
  }

  // 처음(움직임 줄이기면 내내) 보이는 면 — 그 천체를 알아보게 하는 무늬 쪽 경도가 화면 앞(-y)으로
  const start = -Math.PI / 2 - (FRONT_LON[info.key] ?? (info.shape === "sphere" ? 0.4 : SIDEWAYS));
  return { tilt, spin, uniforms, start };
}

// ── 화면 ────────────────────────────────────────────────────────────────

let active = null;

// 그 항목의 천체를 canvas에 그린다. 반환: { stop } (WebGL을 쓸 수 없거나 태양계 천체가 아니면 null)
export function mountBodyView(canvas, id, { still = false } = {}) {
  active?.stop();
  const info = bodyInfo(id);
  if (!info) return null;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  } catch {
    return null;                                        // WebGL을 쓸 수 없으면 그림 없이 글만
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const extent = info.key === "saturn" ? 2.4 : 1.0;    // 토성은 고리까지
  const camera = new THREE.PerspectiveCamera(24, 1, 0.1, 100);
  camera.position.set(0, 0, (extent * 1.22) / Math.tan(12 * Math.PI / 180));
  const disposables = [];
  const track = (x) => { disposables.push(x); return x; };

  let onTexture = null;
  const { tilt, spin, start } = buildBodyMesh(info, { track, onLoad: () => onTexture?.() });
  scene.add(tilt);

  // 테두리 빛 · 코마 — 천체 뒤에 카메라를 보는 판
  const glow = GLOW[info.surface] ?? GLOW[info.key];
  if (glow) {
    const [r, g, b, strength, width] = glow;
    const sun2 = new THREE.Vector2(SUN_DIR.x, SUN_DIR.y).normalize();
    const plane = new THREE.Mesh(track(new THREE.PlaneGeometry(6, 6)), track(new THREE.ShaderMaterial({
      uniforms: { uColor: { value: new THREE.Vector3(r, g, b) }, uSun2: { value: sun2 }, uStrength: { value: strength }, uWidth: { value: width } },
      vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
      fragmentShader: GLOW_FRAG, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    })));
    plane.scale.setScalar(info.surface === "comet" ? 1.0 : 0.98);
    plane.position.z = -0.01;
    scene.add(plane);
  }

  const size = () => {
    const w = canvas.clientWidth || 320, h = canvas.clientHeight || 200;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  size();
  const period = (info.spinSec ?? 10) * 1000;
  const t0 = performance.now();
  let raf = 0, stopped = false;
  const draw = () => {
    const t = still ? 0 : (performance.now() - t0) / 1000;
    spin.rotation.z = start + (2 * Math.PI * (t * 1000)) / period;
    if (spin.userData.uniforms) spin.userData.uniforms.uTime.value = t;
    renderer.render(scene, camera);
  };
  const handle = {
    stop() {
      if (stopped) return;
      stopped = true;
      cancelAnimationFrame(raf);
      for (const d of disposables) d.dispose();
      renderer.dispose();
      renderer.forceContextLoss();                      // 컨텍스트까지 놓아 준다 — 서랍을 여러 번 열어도 쌓이지 않게
      if (active === handle) active = null;
    },
  };
  const frame = () => {
    if (stopped) return;
    if (!canvas.isConnected) { handle.stop(); return; }   // 서랍 내용이 바뀌었다
    draw();
    if (!still) raf = requestAnimationFrame(frame);
  };
  onTexture = () => { if (still && !stopped) draw(); };
  frame();
  active = handle;
  return handle;
}

// 지금 떠 있는 근접 뷰를 정리한다 (서랍을 닫거나 다른 항목으로 바꿀 때)
export function stopBodyView() {
  active?.stop();
}
