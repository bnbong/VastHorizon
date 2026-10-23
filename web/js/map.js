// 🌍 우주 지도 — 지구('나')를 중심으로 모든 항목을 실제 방향 · 로그 스케일 거리에 놓는다. 배경은 실제 별과 은하수.

import { THREE, label, pointsMaterial, ring } from "./scene.js";
import { pulse } from "./sky.js";
import { MODELS, ModelShelf } from "./models.js";
import { ChalkMarks, DreamSphere } from "./dream.js";
import { distanceText, eqToScene, mapRadius, radecToEq } from "./astro.js";
import { EQ_TO_MAP } from "./skydata.js";
import { loadMilkyway, loadStars, MilkyWayLayer, StarLayer } from "./starfield.js";

export const GROUP_COLORS = {
  solar_system: 0xffd27a, human_made: 0x7ee0ff, star: 0xf4f6ff, messier: 0xc59bff,
};
const LANDMARKS = ["달", "태양", "보이저 1호", "프록시마 센타우리", "시리우스", "베텔게우스",
                   "플레이아데스 성단", "안드로메다 은하", "국제우주정거장", "제임스 웹 우주망원경"];

export class MapMode {
  constructor(data) {
    this.group = new THREE.Group();
    this.points = data.points.filter((p) => p.placement !== "origin").map((p) => ({
      ...p, position: new THREE.Vector3(...eqToScene(p.dir)).multiplyScalar(mapRadius(p.km)),
    }));
    this.byId = new Map(this.points.map((p) => [p.id, p]));
    this.earth = data.points.find((p) => p.placement === "origin");
    this.build(data.rings);
  }

  build(rings) {
    // 배경 — 실제 별(6.5등급까지)과 은하수를 실제 방향에. 카메라를 따라다녀 늘 무한히 먼 하늘로 보인다
    this.backdrop = new THREE.Group();
    this.group.add(this.backdrop);
    const stars = new StarLayer({ radius: 2400, horizon: false });
    stars.setRotation(EQ_TO_MAP);
    stars.setLimit(6.5);
    stars.uniforms.uTwinkle.value = 0;
    stars.uniforms.uDim.value = 0.75;
    this.backdrop.add(stars.group);
    Promise.all([loadStars("bright"), loadMilkyway()]).then(([bright, mw]) => {
      stars.add(bright);
      const milkyway = new MilkyWayLayer(mw, { radius: 2450, horizon: false, strength: 0.7 });
      milkyway.setRotation(EQ_TO_MAP);
      this.backdrop.add(milkyway.mesh);
    }).catch((e) => console.warn("배경 하늘을 불러오지 못했습니다", e));

    // 거리 고리 — 지구 중심, 적도면
    rings.forEach((ring, idx) => {
      const r = mapRadius(ring.km);
      const pts = Array.from({ length: 161 }, (_, i) => {
        const a = (i / 160) * Math.PI * 2;
        return new THREE.Vector3(Math.cos(a) * r, 0, Math.sin(a) * r);
      });
      this.group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineBasicMaterial({ color: ring.edge ? 0xff8fd2 : 0x6a5fa8, transparent: true, opacity: ring.edge ? 0.9 : 0.35 })));
      const tag = label(ring.label, ring.edge ? "label ring edge" : "label ring");
      const angle = -0.35 * idx;              // 고리마다 이름표 각도를 달리해 겹치지 않게
      tag.position.set(Math.cos(angle) * r, 0, Math.sin(angle) * r);
      this.group.add(tag);
    });

    // 항목 — 그룹별 색. 방향이 예시(지구 궤도 위성)인 점은 흐리게
    const positions = new Float32Array(this.points.length * 3);
    const colors = new Float32Array(this.points.length * 3);
    this.points.forEach((p, i) => {
      positions.set(p.position.toArray(), i * 3);
      const c = new THREE.Color(GROUP_COLORS[p.group] ?? 0xffffff);
      if (p.placement === "illustrative") c.multiplyScalar(0.55);
      colors.set([c.r, c.g, c.b], i * 3);
    });
    const geom = new THREE.BufferGeometry()
      .setAttribute("position", new THREE.BufferAttribute(positions, 3))
      .setAttribute("color", new THREE.BufferAttribute(colors, 3));
    this.baseColors = colors.slice();            // 내 세상 안 · 밖에 따라 색을 바꿀 때의 기준
    this.pointGeom = geom;
    this.group.add(new THREE.Points(geom, pointsMaterial({ size: 9, vertexColors: true })));

    // 나 (지구)
    const me = new THREE.Mesh(new THREE.SphereGeometry(0.5, 24, 16), new THREE.MeshBasicMaterial({ color: 0x4d8fdc }));
    this.group.add(me);
    const meTag = label("나", "label me");
    meTag.position.set(0, 0.9, 0);
    this.group.add(meTag);

    this.landmarkTags = new Map();
    for (const name of LANDMARKS) {
      const p = this.points.find((q) => q.name === name);
      if (!p) continue;
      const tag = label(p.name, "label landmark");
      tag.position.copy(p.position);
      this.group.add(tag);
      this.landmarkTags.set(p.id, tag);
    }
    // 내 세상 — 내가 알아간(담은) 천체는 네온 분필과 이름, 빛의 선으로. 담지 않은 천체는 거리와 관계없이 아직 알아가지 않은 천체다.
    // (개인이 아직 모른다는 은유일 뿐, 천체의 물리적 상태와는 관계없다.) 가장 먼 빛까지는 영역처럼 보이지 않게 아주 옅은 테두리만
    this.reach = new DreamSphere({ strength: 0.22, sparkles: false });
    this.group.add(this.reach.group);
    // 오늘의 궤적 — '나'에서 바라본 천체를 거리순으로 잇는 무지갯빛 혜성 꼬리, 발견한 천체는 네온 분필
    this.trail = new THREE.Group();
    this.group.add(this.trail);
    this.visitedChalk = new ChalkMarks({ size: 34, haloSize: 84 });
    this.group.add(this.visitedChalk.group);
    this.crossedGroup = new THREE.Group();        // 넓어지는 순간 — 새로 안쪽에 들어온 천체 이름
    this.group.add(this.crossedGroup);
    this.clockT = 0;
    this.visitedGroup = new THREE.Group();
    this.group.add(this.visitedGroup);
    this.edgeRadius = mapRadius(Math.max(...rings.map((r) => r.km)));

    this.selectedTag = label("", "label selected");
    this.selectedTag.visible = false;
    this.group.add(this.selectedTag);
    // 선택 표시 — 누른 천체 둘레에서 맥박 치는 고리 (하늘과 같은 모양)
    this.selectRing = new THREE.Points(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3()]),
      pointsMaterial({ map: ring(), size: 30, color: 0xd7c4ff, opacity: 0.95 }));
    this.selectRing.visible = false;
    this.group.add(this.selectRing);
    // 대표 기체의 실제 형태 (NASA 3D 모델) — 가까이 가면 내려받아 그 점 자리에 띄운다
    this.models = new ModelShelf(this.group, this.points.filter((p) => MODELS[p.name]));
  }

  update(dt, stage) {
    this.backdrop.position.copy(stage.camera.position);
    // 움직임 줄이기 — 테두리 · 분필 · 일렁임을 멈춘 채 그린다 (편하게 읽을 수 있게)
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches || new URLSearchParams(location.search).get("motion") === "off";
    this.still = still;
    if (!still) this.clockT += dt;
    this.reach.update(this.clockT);
    this.visitedChalk.update(this.clockT);
    if (!still || !this.shimmered) this.shimmer(this.clockT);
    this.models.update(dt, stage.camera);
    this.clock = (this.clock ?? 0) + dt;
    pulse(this.selectRing.visible ? this.selectRing : null, this.clock, !matchMedia("(prefers-reduced-motion: reduce)").matches
      && new URLSearchParams(location.search).get("motion") !== "off");
  }

  enter(stage) {
    this.stage = stage;
    // 최대로 물러나면 관측 가능한 우주의 끝 전체가 보이는 자리 (edgeView와 같은 거리)
    Object.assign(stage.controls, { minDistance: 1.5, maxDistance: this.edgeView().length() });
    if (this.lastView) {                              // 다시 오면 마지막에 보던 자리 그대로
      stage.camera.position.copy(this.lastView.position);
      stage.controls.target.copy(this.lastView.target);
    } else {                                          // 처음에는 알아간 천체가 한눈에 들어오는 자리
      stage.camera.position.copy(this.knownView());
      stage.controls.target.set(0, 0, 0);
    }
  }

  exit() {
    this.lastView = { position: this.stage.camera.position.clone(), target: this.stage.controls.target.clone() };
  }

  // 알아간 천체가 모두 들어오는 자리 — 아직 없으면 '나' 가까이
  knownView() {
    let r = 2.4;
    for (const id of this.knownIds ?? []) {
      const p = this.lookup(id);
      if (p) r = Math.max(r, p.position.length());
    }
    return new THREE.Vector3(0.33, 0.42, 0.85).normalize().multiplyScalar(Math.max(6, r * 2.4));
  }

  // 거리 눈금 — 그 거리의 고리가 한눈에 보이는 자리로
  viewDistance(km) {
    const r = Math.min(mapRadius(km), this.edgeRadius);
    const to = r >= this.edgeRadius * 0.99 ? this.edgeView() : new THREE.Vector3(0.33, 0.62, 0.85).normalize().multiplyScalar(Math.max(6, r * 2.3));
    this.stage.flyTo(to, new THREE.Vector3(), this.still ? 1 : 1400);
  }

  // 지도 카탈로그의 점, 또는 카탈로그 밖에서 알아간 천체(방향 · 거리로 놓은 점)
  lookup(id) {
    return this.byId.get(id) ?? this.extra?.get(id) ?? null;
  }

  // 첫 화면 연출 — 지구 위 '나'에서 시작해 우주 전체로 시야를 넓힌다 (기획안 장면 1 · 2)
  zoomOut(ms = 6000) {
    this.stage.flyTo(new THREE.Vector3(70, 120, 210), new THREE.Vector3(0, 0, 0), ms);
  }

  // 내 세상 — 반지름(바라본 가장 먼 거리)과 바라본 천체 이름표
  setWorld(worldKm, visited) {
    const r = Math.max(mapRadius(worldKm), 0.6);
    this.reach.setRadius(r);
    this.worldRadius = r;
    this.worldKm = worldKm;
    this.knownIds = new Set(visited.map((v) => v.id));
    // 카탈로그 밖에서 알아간 천체 (하늘의 아무 별) — 거리와 방향을 알면 그 자리에 놓는다. 거리를 모르면 지도에는 놓지 않는다
    this.extra = new Map();
    for (const v of visited) {
      if (this.byId.has(v.id) || !(v.km > 0) || v.ra == null || v.dec == null) continue;
      this.extra.set(v.id, { id: v.id, name: v.name, km: v.km,
        position: new THREE.Vector3(...eqToScene(radecToEq(v.ra, v.dec))).multiplyScalar(mapRadius(v.km)) });
    }
    this.shimmer(this.clockT ?? 0);
    this.visitedGroup.clear();
    this.visitedTags = new Map();
    for (const v of visited) {
      const p = this.lookup(v.id);
      if (!p) continue;
      const tag = label(p.name, "label visited");
      this.visitedTags.set(p.id, tag);
      tag.position.copy(p.position);
      this.visitedGroup.add(tag);
      this.landmarkTags.get(p.id)?.removeFromParent();
    }
    this.trail.clear();
    const stops = visited.map((v) => this.lookup(v.id)).filter(Boolean).sort((a, b) => a.km - b.km).map((p) => p.position);
    this.visitedChalk.setPositions(stops.flatMap((v) => v.toArray()));
    if (stops.length) {
      // 혜성 꼬리 — 선을 잘게 나눠 분홍 → 주황 → 노랑 → 연두 → 파랑으로 흐르게
      const path = [new THREE.Vector3(), ...stops], pts = [], cols = [];
      const spectrum = [0xff4fa8, 0xff9f43, 0xffe066, 0x7dffb3, 0x3d7bff].map((h) => new THREE.Color(h));
      const segs = path.length - 1, steps = 24;
      for (let s = 0; s < segs; s++) {
        for (let k = 0; k <= steps; k++) {
          const u = (s + k / steps) / segs;
          pts.push(new THREE.Vector3().lerpVectors(path[s], path[s + 1], k / steps));
          const f = u * (spectrum.length - 1), i = Math.min(spectrum.length - 2, Math.floor(f));
          const c = spectrum[i].clone().lerp(spectrum[i + 1], f - i);
          cols.push(c.r, c.g, c.b);
        }
      }
      this.trail.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts).setAttribute("color", new THREE.Float32BufferAttribute(cols, 3)),
        new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false })));
    }
  }

  // 아직 알아가지 않은 천체 — 담지 않은 천체는 거리와 관계없이 흐리게 일렁인다. 알아간 천체는 또렷하게
  shimmer(t) {
    this.shimmered = true;
    const col = this.pointGeom.attributes.color, cool = new THREE.Color(0x6a6aa8), c = new THREE.Color();
    const known = this.knownIds ?? new Set();
    this.points.forEach((p, i) => {
      c.fromArray(this.baseColors, i * 3);
      if (known.has(p.id)) c.lerp(new THREE.Color(0xffffff), 0.25);
      else c.lerp(cool, 0.5).multiplyScalar(0.42 + 0.16 * Math.sin(t * (0.8 + (i % 7) * 0.13) + i));
      col.setXYZ(i, c.r, c.g, c.b);
    });
    col.needsUpdate = true;
  }

  // 넓어지는 순간 — 구가 이전 반지름에서 새 반지름까지 자라고, 카메라가 함께 물러난다.
  // 구의 가장자리가 지나는 천체는 이름이 하나씩 떠오른다 ("+ 시리우스"). 끝나면 done()
  // crossed: 그 사이에 지나는, 아직 알아가지 않은(담지 않은) 천체 — 이름만 흐리게 스친다. knownId: 새로 알게 된 천체
  expandTo(fromKm, toKm, crossed, done, knownId) {
    const r0 = Math.max(mapRadius(fromKm), 0.6), r1 = Math.max(mapRadius(toKm), 0.6);
    const st = this.stage;
    const dir = st.camera.position.clone().normalize();
    if (dir.lengthSq() < 1e-6 || Math.abs(dir.y) > 0.95) dir.set(0.33, 0.42, 0.85).normalize();
    st.controls.target.set(0, 0, 0);
    this.crossedGroup.traverse((o) => { if (o.isCSS2DObject) o.element.remove(); });
    this.crossedGroup.clear();
    // crossed는 지도 데이터(위치 없음)일 수 있다 — ID로 이 지도의 점(3D 위치)을 찾는다
    const marks = crossed.map((c) => this.byId.get(c.id)).filter(Boolean).map((p) => ({ p, r: mapRadius(p.km), shown: false }));
    const dist = (r) => Math.max(5, r * 2.5);
    const instant = matchMedia("(prefers-reduced-motion: reduce)").matches || new URLSearchParams(location.search).get("motion") === "off";
    st.animate(4200, (k) => {
      const r = r0 + (r1 - r0) * k;
      this.reach.setRadius(r);
      this.worldRadius = r;
      st.camera.position.copy(dir).multiplyScalar(dist(r));
      for (const m of marks) {
        if (m.shown || m.r > r) continue;
        m.shown = true;
        const tag = label(m.p.name, "label passing");
        tag.position.copy(m.p.position);
        this.crossedGroup.add(tag);
      }
    }, () => {
      const known = knownId && this.lookup(knownId);
      if (known) {                                 // 새로 알게 된 천체 — 이름이 또렷하게
        const tag = label(`+ ${known.name}`, "label crossed");
        tag.position.copy(known.position);
        this.crossedGroup.add(tag);
      }
      this.reach.setRadius(r1);
      this.worldRadius = r1;
      if (instant) for (const m of marks) if (!m.shown) { m.shown = true; const tag = label(m.p.name, "label passing"); tag.position.copy(m.p.position); this.crossedGroup.add(tag); }
      done?.();
      setTimeout(() => {                           // 이름은 잠시 뒤 사라진다
        this.crossedGroup.traverse((o) => { if (o.isCSS2DObject) o.element.remove(); });
        this.crossedGroup.clear();
      }, 6000);
    });
  }

  // 끝 장면 — 위쪽 글이 가리지 않게 우주를 화면 아래쪽(62%)으로
  recenterForEnd() {
    const lift = new THREE.Vector3(0, this.edgeRadius * 0.32, 0);
    this.stage.flyTo(this.stage.camera.position.clone().add(lift), this.stage.controls.target.clone().add(lift), 1400);
  }

  // 관측 가능한 우주 전체가 보이는 자리 (떠오르기의 끝)
  edgeView() {
    const edge = this.edgeRadius;
    return new THREE.Vector3(edge * 0.6, edge * 1.1, edge * 1.6);
  }

  // 떠오르기 — 땅 위의 나 → 내 세상의 끝 → 관측 가능한 우주의 끝
  journey(onWorld, onEdge) {
    const origin = new THREE.Vector3();
    this.stage.camera.position.set(0, 0.4, 1.4);
    this.stage.controls.target.copy(origin);
    const world = Math.max(this.worldRadius ?? 1, 2);
    this.stage.flyTo(new THREE.Vector3(world * 0.9, world * 1.1, world * 2.2), origin, 2600, () => {
      onWorld?.();
      this.stage.flyTo(this.edgeView(), origin, 2400, onEdge);
    });
  }

  pickables() {
    return this.points.map((p) => ({ position: p.position, data: p }));
  }

  describe(p) {
    const note = { illustrative: " · 방향은 예시", proxy: " · 위치는 근삿값" }[p.placement] ?? "";
    return `${p.name} — ${distanceText(p.km)}${note}`;
  }

  // 선택 — 이름표와 맥박 고리. fly면 그 천체로 카메라를 옮긴다. id가 없거나 지도에 없는 천체면 표시를 지운다
  select(id, { fly = true } = {}) {
    const p = id ? this.lookup(id) : null;
    for (const [tagId, tag] of this.landmarkTags) tag.visible = tagId !== id;   // 선택 이름표와 겹치지 않게
    for (const [tagId, tag] of this.visitedTags ?? []) tag.visible = tagId !== id;
    if (!p) {
      this.selectedTag.visible = false;
      this.selectRing.visible = false;
      return false;
    }
    this.selectedTag.element.textContent = `◎ ${p.name}`;
    this.selectedTag.position.copy(p.position);
    this.selectedTag.visible = true;
    this.selectRing.geometry.attributes.position.setXYZ(0, p.position.x, p.position.y, p.position.z);
    this.selectRing.geometry.attributes.position.needsUpdate = true;
    this.selectRing.geometry.computeBoundingSphere();
    this.selectRing.visible = true;
    if (!fly || !this.stage) return true;
    const back = p.position.clone().normalize().multiplyScalar(Math.max(8, p.position.length() * 0.25));
    this.stage.flyTo(p.position.clone().add(back).add(new THREE.Vector3(0, 4, 0)), p.position.clone());
    return true;
  }
}
