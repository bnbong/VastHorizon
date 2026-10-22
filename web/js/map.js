// 🌍 우주 지도 — 지구('나')를 중심으로 모든 항목을 실제 방향 · 로그 스케일 거리에 놓는다. 배경은 실제 별과 은하수.

import { THREE, label, pointsMaterial, ring } from "./scene.js";
import { pulse } from "./sky.js";
import { MODELS, ModelShelf } from "./models.js";
import { distanceText, eqToScene, mapRadius } from "./astro.js";
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
        new THREE.LineBasicMaterial({ color: ring.edge ? 0xd2a356 : 0x5a6b93, transparent: true, opacity: ring.edge ? 0.9 : 0.35 })));
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
    // 내 세상 — 지금까지 바라본 가장 먼 천체까지의 구
    this.worldSphere = new THREE.Mesh(new THREE.SphereGeometry(1, 48, 24),
      new THREE.MeshBasicMaterial({ color: 0x4d8fdc, transparent: true, opacity: 0.1, depthWrite: false }));
    this.worldEdge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(1, 3)),
      new THREE.LineBasicMaterial({ color: 0x7eb6ff, transparent: true, opacity: 0.22, depthWrite: false }));
    this.group.add(this.worldSphere, this.worldEdge);
    // 오늘의 궤적 — '나'에서 바라본 천체를 거리순으로 잇는 금빛 선
    this.trail = new THREE.Group();
    this.group.add(this.trail);
    this.visitedGroup = new THREE.Group();
    this.group.add(this.visitedGroup);
    this.edgeRadius = mapRadius(Math.max(...rings.map((r) => r.km)));

    this.selectedTag = label("", "label selected");
    this.selectedTag.visible = false;
    this.group.add(this.selectedTag);
    // 선택 표시 — 누른 천체 둘레에서 맥박 치는 고리 (하늘과 같은 모양)
    this.selectRing = new THREE.Points(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3()]),
      pointsMaterial({ map: ring(), size: 30, color: 0x9fd8ff, opacity: 0.95 }));
    this.selectRing.visible = false;
    this.group.add(this.selectRing);
    // 대표 기체의 실제 형태 (NASA 3D 모델) — 가까이 가면 내려받아 그 점 자리에 띄운다
    this.models = new ModelShelf(this.group, this.points.filter((p) => MODELS[p.name]));
  }

  update(dt, stage) {
    this.backdrop.position.copy(stage.camera.position);
    this.models.update(dt, stage.camera);
    this.clock = (this.clock ?? 0) + dt;
    pulse(this.selectRing.visible ? this.selectRing : null, this.clock, !matchMedia("(prefers-reduced-motion: reduce)").matches
      && new URLSearchParams(location.search).get("motion") !== "off");
  }

  enter(stage) {
    this.stage = stage;
    Object.assign(stage.controls, { minDistance: 1.5, maxDistance: 900 });
    stage.camera.position.set(0, 2.5, 6);
    stage.controls.target.set(0, 0, 0);
  }

  // 첫 화면 연출 — 지구 위 '나'에서 시작해 우주 전체로 시야를 넓힌다 (기획안 장면 1 · 2)
  zoomOut(ms = 6000) {
    this.stage.flyTo(new THREE.Vector3(70, 120, 210), new THREE.Vector3(0, 0, 0), ms);
  }

  // 내 세상 — 반지름(바라본 가장 먼 거리)과 바라본 천체 이름표
  setWorld(worldKm, visited) {
    const r = Math.max(mapRadius(worldKm), 0.6);
    this.worldSphere.scale.setScalar(r);
    this.worldEdge.scale.setScalar(r);
    this.worldRadius = r;
    this.visitedGroup.clear();
    for (const v of visited) {
      const p = this.byId.get(v.id);
      if (!p) continue;
      const tag = label(p.name, "label visited");
      tag.position.copy(p.position);
      this.visitedGroup.add(tag);
      this.landmarkTags.get(p.id)?.removeFromParent();
    }
    this.trail.clear();
    const stops = visited.map((v) => this.byId.get(v.id)).filter(Boolean).sort((a, b) => a.km - b.km).map((p) => p.position);
    if (stops.length) {
      const path = [new THREE.Vector3(), ...stops];
      this.trail.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(path),
        new THREE.LineBasicMaterial({ color: 0xf0d396, transparent: true, opacity: 0.7 })));
      this.trail.add(new THREE.Points(new THREE.BufferGeometry().setFromPoints(stops),        // 이음점의 금빛 번짐
        pointsMaterial({ color: 0xe6bf78, size: 16, opacity: 0.35 })));
    }
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
    const p = id ? this.byId.get(id) : null;
    for (const [tagId, tag] of this.landmarkTags) tag.visible = tagId !== id;   // 선택 이름표와 겹치지 않게
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
