// ✨ 하늘 — 첫 화면. 내가 있는 곳 · 시각에 올려다본 하늘.
// 맨눈 별(약 5천 개) · 별자리 선과 이름 · 카탈로그 천체(별 · 메시에) · 행성(서버 계산) · 지평선과 방위.
//
// 관측하면 드러난다 (디자인 v2): 아직 관측하지 않은 카탈로그 천체는 이름 없는 흐릿한 빛(입자 28개가 천천히 흔들림)으로 그린다.
// 누르면 1.1초 동안 한 점으로 모이고 이름이 나타난다. 관측한 천체는 오늘 하루 이름과 거리를 갖는다.

import { THREE, label, pointsMaterial } from "./scene.js";
import { altAz, altAzToScene, eqToRadec, localSiderealDeg } from "./astro.js";

const R = 100;
const DIRECTIONS = [["북", 0], ["북동", 45], ["동", 90], ["남동", 135], ["남", 180], ["남서", 225], ["서", 270], ["북서", 315]];
const CLOUD_PARTICLES = 28;
const CLOUD_RADIUS = 4.5;          // 화면에서 반지름 약 30px (화각 75도 기준)
const COLLAPSE_MS = 1100;
const MATCH_DEG = 0.12;            // 맨눈 별 ↔ 카탈로그 별 같은 별로 볼 각거리
const easeOutQuart = (t) => 1 - Math.pow(1 - t, 4);

// 색지수(B−V) → 별빛 색 (파랑 → 흰색 → 노랑 → 주황)
function starColor(bv) {
  const stops = [[-0.4, [0.62, 0.72, 1]], [0, [0.85, 0.9, 1]], [0.6, [1, 0.97, 0.9]], [1.2, [1, 0.82, 0.6]], [2, [1, 0.65, 0.45]]];
  for (let i = 1; i < stops.length; i++) {
    if (bv <= stops[i][0]) {
      const [b0, c0] = stops[i - 1], [b1, c1] = stops[i];
      const k = Math.max(0, (bv - b0) / (b1 - b0));
      return c0.map((v, j) => v + (c1[j] - v) * k);
    }
  }
  return stops[stops.length - 1][1];
}

function angularDeg(ra1, dec1, ra2, dec2) {
  const d = Math.PI / 180;
  const c = Math.sin(dec1 * d) * Math.sin(dec2 * d) + Math.cos(dec1 * d) * Math.cos(dec2 * d) * Math.cos((ra1 - ra2) * d);
  return Math.acos(Math.max(-1, Math.min(1, c))) / d;
}

export class SkyMode {
  // catalog: 우주 지도 점 중 하늘 방향이 있는 것 (별 · 메시에) — 관측 대상
  constructor(constellations, skyStars, catalog) {
    this.constellations = constellations;
    this.skyStars = skyStars;
    this.catalog = catalog.map((p) => ({ ...p, radec: eqToRadec(p.dir) }));
    this.catalogIds = new Set(this.catalog.map((p) => p.id));
    this.matchStars();
    this.group = new THREE.Group();
    this.dynamic = new THREE.Group();
    this.group.add(this.dynamic);
    this.buildStatic();
    this.place = { lat: 37.5665, lon: 126.978, name: "서울" };
    this.date = new Date();
    this.planets = [];
    this.observed = new Set();
    this.collapsing = new Map();       // 항목 ID → 관측한 시각 (모이는 연출)
    this.justObserved = new Set();     // 이름이 막 나타나는 천체
    this.clock = 0;
  }

  // 카탈로그 별과 같은 맨눈 별 — 관측 전에는 그 별을 흐릿한 빛으로만 보여 준다
  matchStars() {
    this.starOf = new Map();
    for (const p of this.catalog) {
      if (p.group !== "star") continue;
      let best = -1, bestD = MATCH_DEG;
      this.skyStars.forEach(([ra, dec], i) => {
        if (Math.abs(dec - p.radec.dec) > MATCH_DEG) return;
        const d = angularDeg(ra, dec, p.radec.ra, p.radec.dec);
        if (d < bestD) { bestD = d; best = i; }
      });
      if (best >= 0) this.starOf.set(p.id, best);
    }
  }

  buildStatic() {
    // 땅 — 지평선 아래를 가린다
    this.group.add(new THREE.Mesh(
      new THREE.SphereGeometry(R * 0.98, 48, 16, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2),
      new THREE.MeshBasicMaterial({ color: 0x060a09, side: THREE.BackSide })));
    // 지평선 근처의 옅은 빛 — 남색 위에 아주 옅은 금빛
    const glow = new THREE.Mesh(new THREE.CylinderGeometry(R * 0.965, R * 0.965, 8, 96, 1, true),
      new THREE.MeshBasicMaterial({ color: 0x1d3a6e, transparent: true, opacity: 0.16, side: THREE.BackSide, depthWrite: false }));
    glow.position.y = 4;
    const warm = new THREE.Mesh(new THREE.CylinderGeometry(R * 0.966, R * 0.966, 2.2, 96, 1, true),
      new THREE.MeshBasicMaterial({ color: 0xe6bf78, transparent: true, opacity: 0.06, side: THREE.BackSide, depthWrite: false }));
    warm.position.y = 1.1;
    this.group.add(glow, warm);
    const horizon = Array.from({ length: 181 }, (_, i) => {
      const a = (i / 180) * Math.PI * 2;
      return new THREE.Vector3(Math.cos(a) * R * 0.97, 0, Math.sin(a) * R * 0.97);
    });
    this.group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(horizon),
      new THREE.LineBasicMaterial({ color: 0x2f4a3a, transparent: true, opacity: 0.8 })));
    for (const [name, az] of DIRECTIONS) {
      const tag = label(name, name.length === 1 ? "label compass" : "label compass minor");
      tag.position.fromArray(altAzToScene(1.2, az)).multiplyScalar(R * 0.9);      // 지평선 바로 위 — 아래쪽은 발 크롬과 겹친다
      this.group.add(tag);
    }
  }

  setObserved(ids) {
    const next = new Set(ids);
    const changed = next.size !== this.observed.size || [...next].some((id) => !this.observed.has(id));
    this.observed = next;
    if (changed && !this.collapsing.size && this.stage?.mode === this) this.rebuild();
  }

  // 관측 — 흐릿한 빛이 한 점으로 모인 뒤 이름이 나타난다. 별자리 선의 별(카탈로그 밖)은 이름만 나타난다
  observe(id) {
    if (this.observed.has(id) || this.collapsing.has(id)) return;
    if (this.cloudIndex?.has(id)) {
      this.collapsing.set(id, performance.now());
    } else if (String(id).startsWith("hip:")) {
      this.observed.add(id);
      this.justObserved.add(id);
      if (this.stage?.mode === this) this.rebuild();
    }
  }

  // 위치 · 시각에 맞춰 별 · 선 · 이름표를 다시 놓는다
  rebuild() {
    this.dynamic.clear();
    const lst = localSiderealDeg(this.date, this.place.lon);
    const toScene = (ra, dec, r = R) => {
      const { alt, az } = altAz(ra, dec, this.place.lat, lst);
      return { alt, az, v: new THREE.Vector3(...altAzToScene(alt, az)).multiplyScalar(r) };
    };
    this.targets = [];
    const hidden = new Set([...this.starOf].filter(([id]) => !this.observed.has(id)).map(([, i]) => i));

    // 맨눈 별 — 밝기 단계별로 크기를 나눠 그린다 (관측 전 카탈로그 별은 흐릿한 빛으로만)
    const bands = [[-2, 1.5, 7.5], [1.5, 3, 5], [3, 4.5, 3.4], [4.5, 7, 2.2]];
    for (const [lo, hi, size] of bands) {
      const pos = [], col = [];
      this.skyStars.forEach(([ra, dec, mag, bv], i) => {
        if (mag < lo || mag >= hi || hidden.has(i)) return;
        const p = toScene(ra, dec);
        if (p.alt < -2) return;
        pos.push(...p.v.toArray());
        const fade = Math.min(1, Math.max(0.35, (7 - mag) / 5));
        col.push(...starColor(bv).map((c) => c * fade));
      });
      this.dynamic.add(new THREE.Points(
        new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(pos, 3))
          .setAttribute("color", new THREE.Float32BufferAttribute(col, 3)),
        pointsMaterial({ size, vertexColors: true })));
    }

    // 별자리 선 · 이름 — 늘 보인다
    const linePos = [];
    for (const con of this.constellations) {
      const byHip = new Map();
      const center = new THREE.Vector3();
      for (const s of con.stars) {
        const p = toScene(s.ra_deg, s.dec_deg, R * 0.995);
        byHip.set(s.hip, p.v);
        center.add(p.v);
        // 별자리 선의 별 — 카탈로그 천체가 아니어도 누를 수 있다 (거리 · 등급은 별자리 모양 데이터)
        if (p.alt < 0 || (s.item_id && this.catalogIds.has(s.item_id)) || !s.distance_ly) continue;
        const id = `hip:${s.hip}`;
        this.targets.push({ position: p.v, data: { id, kind: "figure-star", name: s.name, hip: s.hip, mag: s.mag,
          distance_ly: s.distance_ly, constellation: con.name, constellation_id: con.item_id } });
        if (this.observed.has(id)) {
          const tag = label(s.name, `label star ${this.justObserved.has(id) ? "observed" : ""}`);
          tag.position.copy(p.v);
          this.dynamic.add(tag);
        }
      }
      for (const line of con.lines) {
        for (let i = 0; i < line.length - 1; i++) {
          const a = byHip.get(line[i]), b = byHip.get(line[i + 1]);
          if (a && b) linePos.push(...a.toArray(), ...b.toArray());
        }
      }
      center.normalize().multiplyScalar(R * 0.95);
      if (center.y > 0) {
        const tag = label(con.name, "label constellation");
        tag.position.copy(center);
        this.dynamic.add(tag);
        this.targets.push({ position: center, data: { id: con.item_id, name: con.name, kind: "constellation" } });
      }
    }
    this.dynamic.add(new THREE.LineSegments(
      new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(linePos, 3)),
      new THREE.LineBasicMaterial({ color: 0x4a6aa8, transparent: true, opacity: 0.4 })));

    // 카탈로그 천체 — 관측한 것은 또렷한 점 · 이름, 아직이면 흐릿한 빛
    const sharp = [], sharpCol = [], cloud = [];
    for (const p of this.catalog) {
      const s = toScene(p.radec.ra, p.radec.dec, R * 0.99);
      if (s.alt < 0) continue;
      if (this.observed.has(p.id)) {
        sharp.push(...s.v.toArray());
        const c = p.group === "messier" ? [0.77, 0.61, 1] : [1, 0.95, 0.82];
        sharpCol.push(...c);
        const tag = label(p.name, `label star ${this.justObserved.has(p.id) ? "observed" : ""}`);
        tag.position.copy(s.v);
        this.dynamic.add(tag);
        this.targets.push({ position: s.v, data: { ...p, kind: p.group } });
      } else {
        cloud.push({ p, center: s.v });
        this.targets.push({ position: s.v, data: { ...p, kind: p.group, unobserved: true } });
      }
    }
    this.justObserved.clear();
    if (sharp.length) {
      this.dynamic.add(new THREE.Points(
        new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(sharp, 3))
          .setAttribute("color", new THREE.Float32BufferAttribute(sharpCol, 3)),
        pointsMaterial({ size: 9, vertexColors: true })));
    }
    this.buildClouds(cloud);

    // 행성 — 서버(/api/sky)가 계산한 고도 · 방위
    for (const p of this.planets) {
      const v = new THREE.Vector3(...altAzToScene(p.alt_deg, p.az_deg)).multiplyScalar(R * 0.94);
      const tag = label(`● ${p.name}`, "label planet");
      tag.position.copy(v);
      this.dynamic.add(tag);
      this.targets.push({ position: v, data: { id: p.item_id, name: p.name, kind: "planet" } });
    }
  }

  // 흐릿한 빛 — 천체마다 입자 28개, 접평면 위에서 천천히 흔들린다
  buildClouds(cloud) {
    this.clouds = cloud.map(({ p, center }) => {
      const n = center.clone().normalize();
      const u = new THREE.Vector3().crossVectors(n, new THREE.Vector3(0, 1, 0));
      if (u.lengthSq() < 1e-6) u.set(1, 0, 0);
      u.normalize();
      const v = new THREE.Vector3().crossVectors(n, u).normalize();
      const seed = [...p.id].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
      const rnd = (k) => ((Math.sin(seed * 12.9898 + k * 78.233) * 43758.5453) % 1 + 1) % 1;
      const parts = Array.from({ length: CLOUD_PARTICLES }, (_, k) => ({
        r: CLOUD_RADIUS * Math.sqrt(rnd(k)), theta: rnd(k + 100) * Math.PI * 2,
        period: 900 + rnd(k + 200) * 1500, phase: rnd(k + 300) * Math.PI * 2,
      }));
      return { id: p.id, center, u, v, parts, tint: p.group === "messier" ? [0.77, 0.61, 1] : [0.86, 0.88, 1] };
    });
    this.cloudIndex = new Map(this.clouds.map((c) => [c.id, c]));
    const count = this.clouds.length * CLOUD_PARTICLES;
    this.cloudGeom = new THREE.BufferGeometry()
      .setAttribute("position", new THREE.BufferAttribute(new Float32Array(count * 3), 3))
      .setAttribute("color", new THREE.BufferAttribute(new Float32Array(count * 3), 3));
    this.dynamic.add(new THREE.Points(this.cloudGeom, pointsMaterial({ size: 3, vertexColors: true, opacity: 0.9 })));
    this.updateClouds(performance.now());
  }

  updateClouds(now) {
    if (!this.cloudGeom) return;
    const pos = this.cloudGeom.attributes.position, col = this.cloudGeom.attributes.color;
    const tmp = new THREE.Vector3();
    const finished = [];
    this.clouds.forEach((c, ci) => {
      const started = this.collapsing.get(c.id);
      const k = started ? Math.min(1, (now - started) / COLLAPSE_MS) : 0;
      const spread = 1 - easeOutQuart(k);
      const glow = started ? 0.35 + 0.65 * easeOutQuart(k) : 0.3;
      if (k >= 1) finished.push(c.id);
      c.parts.forEach((pt, i) => {
        const wobble = Math.sin(now / pt.period + pt.phase);
        const r = pt.r * (1 + 0.22 * wobble) * spread;
        const th = pt.theta + 0.35 * Math.sin(now / (pt.period * 1.7) + pt.phase);
        tmp.copy(c.center).addScaledVector(c.u, Math.cos(th) * r).addScaledVector(c.v, Math.sin(th) * r);
        const j = ci * CLOUD_PARTICLES + i;
        pos.setXYZ(j, tmp.x, tmp.y, tmp.z);
        const a = glow * (0.55 + 0.45 * (0.5 + 0.5 * wobble));
        col.setXYZ(j, c.tint[0] * a, c.tint[1] * a, c.tint[2] * a);
      });
    });
    pos.needsUpdate = true;
    col.needsUpdate = true;
    this.cloudGeom.computeBoundingSphere();
    if (finished.length) {
      for (const id of finished) {
        this.collapsing.delete(id);
        this.observed.add(id);
        this.justObserved.add(id);
      }
      this.rebuild();                  // 모인 빛은 또렷한 점과 이름으로
    }
  }

  update() {
    if (this.stage?.mode === this) this.updateClouds(performance.now());
  }

  // 낮 · 박명이면 하늘을 밝게 — 태양 고도는 서버(/api/sky)가 계산한다
  setDaylight(sunAltDeg) {
    const night = new THREE.Color(0x02040a), day = new THREE.Color(0x2b4f7e);
    const k = THREE.MathUtils.clamp((sunAltDeg + 12) / 18, 0, 1);      // −12도 이하 밤 → +6도 이상 낮
    this.background = night.lerp(day, k);
    if (this.stage?.mode === this) this.stage.scene.background = this.background;
  }

  setView({ place, date, planets }) {
    if (place) this.place = place;
    if (date) this.date = date;
    if (planets) this.planets = planets;
    this.rebuild();
  }

  enter(stage) {
    this.stage = stage;
    stage.fovZoom = true;
    Object.assign(stage.controls, { enableZoom: false, enablePan: false, rotateSpeed: -0.35 });
    // 카메라를 중심 바로 옆에 두고 중심을 바라보게 하면, 회전이 '고개 돌리기'가 된다.
    // 남쪽 하늘 고도 25도를 바라보면 지평선이 화면 높이의 약 80%에 놓인다 (화각 75도)
    const south = new THREE.Vector3(...altAzToScene(25, 180));
    stage.controls.target.set(0, 0, 0);
    stage.camera.position.copy(south.multiplyScalar(-0.01));
    stage.camera.fov = 75;
    stage.camera.updateProjectionMatrix();
    stage.scene.background = this.background ?? new THREE.Color(0x02040a);
    this.rebuild();
  }

  exit() {
    this.stage.scene.background = new THREE.Color(0x02040a);
  }

  // 그 천체 쪽으로 고개 돌리기
  lookAt(itemId) {
    const t = this.targets?.find((x) => x.data.id === itemId);
    if (!t) return false;
    this.stage.flyTo(t.position.clone().normalize().multiplyScalar(-0.01), new THREE.Vector3(), 1200);
    return true;
  }

  pickables() {
    return this.targets ?? [];
  }

  describe(p) {
    if (p.unobserved) return "관측하기 — 아직 정해지지 않은 빛";
    if (p.kind === "constellation") return `${p.name} — 별자리`;
    if (p.kind === "planet") return `행성 ${p.name}`;
    if (p.kind === "figure-star") return `${p.name} — ${p.constellation}의 별`;
    return p.name;
  }
}
