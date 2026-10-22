// 🔭 펼치기 — 지구에서 본 별자리 모양에서 시작해, 별들을 실제 거리(로그 스케일)로 옮긴다.

import { THREE, label, pointsMaterial } from "./scene.js";
import { eqToScene, radecToEq, unfoldRadius } from "./astro.js";

const SKY_R = 60;           // '지구에서 본 모양'의 반지름 — 모든 별이 같은 거리에 있는 것처럼
const LABELED = 7;          // 이름표를 붙일 밝은 별 수 (가장 가까운 · 먼 별은 항상)

export class UnfoldMode {
  constructor(constellation) {
    this.con = constellation;
    this.group = new THREE.Group();
    this.progress = 0;
    this.stars = constellation.stars.map((s) => {
      const dir = new THREE.Vector3(...eqToScene(radecToEq(s.ra_deg, s.dec_deg)));
      const far = s.distance_ly ? dir.clone().multiplyScalar(unfoldRadius(s.distance_ly)) : dir.clone().multiplyScalar(SKY_R);
      return { ...s, dir, near: dir.clone().multiplyScalar(SKY_R), far, pos: dir.clone().multiplyScalar(SKY_R) };
    });
    this.byHip = new Map(this.stars.map((s) => [s.hip, s]));
    this.center = this.stars.reduce((c, s) => c.add(s.dir), new THREE.Vector3()).normalize();
    this.build();
  }

  build() {
    const known = this.stars.filter((s) => s.distance_ly).sort((a, b) => a.distance_ly - b.distance_ly);
    this.nearest = known[0];
    this.farthest = known[known.length - 1];

    this.pointGeom = new THREE.BufferGeometry().setAttribute("position",
      new THREE.BufferAttribute(new Float32Array(this.stars.length * 3), 3));
    this.group.add(new THREE.Points(this.pointGeom, pointsMaterial({ color: 0xfff4d6, size: 11 })));

    const segments = this.con.lines.reduce((n, l) => n + l.length - 1, 0);
    this.lineGeom = new THREE.BufferGeometry().setAttribute("position",
      new THREE.BufferAttribute(new Float32Array(segments * 6), 3));
    this.group.add(new THREE.LineSegments(this.lineGeom,
      new THREE.LineBasicMaterial({ color: 0x6f9bff, transparent: true, opacity: 0.75 })));

    // 지구 — 모든 시선이 모이는 곳
    this.group.add(new THREE.Mesh(new THREE.SphereGeometry(0.8, 20, 12), new THREE.MeshBasicMaterial({ color: 0x4da3ff })));
    const earth = label("지구", "label me");
    earth.position.set(0, 1.6, 0);
    this.group.add(earth);

    // 지구에서 각 별로 가는 시선 — 펼쳐질수록 길이가 달라진다
    this.sightGeom = new THREE.BufferGeometry().setAttribute("position",
      new THREE.BufferAttribute(new Float32Array(this.stars.length * 6), 3));
    this.group.add(new THREE.LineSegments(this.sightGeom,
      new THREE.LineBasicMaterial({ color: 0x334466, transparent: true, opacity: 0.35 })));

    const bright = [...known].sort((a, b) => a.mag - b.mag).slice(0, LABELED);
    const tagged = new Set([...bright, this.nearest, this.farthest].filter(Boolean));
    this.tags = [...tagged].map((s) => {
      const tag = label("", "label star");
      this.group.add(tag);
      return { s, tag };
    });
    this.apply();
  }

  apply() {
    const k = this.progress;
    const pos = this.pointGeom.attributes.position;
    const sight = this.sightGeom.attributes.position;
    this.stars.forEach((s, i) => {
      s.pos.lerpVectors(s.near, s.far, k);
      pos.setXYZ(i, s.pos.x, s.pos.y, s.pos.z);
      sight.setXYZ(i * 2, 0, 0, 0);
      sight.setXYZ(i * 2 + 1, s.pos.x, s.pos.y, s.pos.z);
    });
    let j = 0;
    const lines = this.lineGeom.attributes.position;
    for (const line of this.con.lines) {
      for (let i = 0; i < line.length - 1; i++, j += 2) {
        const a = this.byHip.get(line[i])?.pos, b = this.byHip.get(line[i + 1])?.pos;
        if (!a || !b) continue;
        lines.setXYZ(j, a.x, a.y, a.z);
        lines.setXYZ(j + 1, b.x, b.y, b.z);
      }
    }
    for (const g of [this.pointGeom, this.lineGeom, this.sightGeom]) {
      g.attributes.position.needsUpdate = true;
      g.computeBoundingSphere();
    }
    for (const { s, tag } of this.tags) {
      tag.position.copy(s.pos);
      tag.element.textContent = k > 0.5 ? `${s.name} · 약 ${Math.round(s.distance_ly).toLocaleString("ko-KR")}광년` : s.name;
    }
  }

  // 시점: 지구에서 별자리 방향 / 옆에서 본 모습
  views() {
    const far = unfoldRadius(this.farthest?.distance_ly ?? 100);
    const mid = this.center.clone().multiplyScalar(far * 0.55);
    const side = new THREE.Vector3().crossVectors(this.center, new THREE.Vector3(0, 1, 0));
    if (side.lengthSq() < 1e-6) side.set(1, 0, 0);
    side.normalize();
    return {
      earth: { position: new THREE.Vector3(), target: this.center.clone().multiplyScalar(SKY_R) },
      side: { position: mid.clone().add(side.multiplyScalar(far * 1.35)).add(new THREE.Vector3(0, far * 0.2, 0)), target: mid },
    };
  }

  enter(stage) {
    this.stage = stage;
    stage.fovZoom = false;
    const { earth } = this.views();
    stage.camera.position.copy(earth.position).add(this.center.clone().multiplyScalar(-0.01));
    stage.controls.target.copy(earth.target);
    stage.camera.fov = 45;
    stage.camera.updateProjectionMatrix();
  }

  play(unfold = true) {
    const from = this.progress, to = unfold ? 1 : 0;
    const v = this.views()[unfold ? "side" : "earth"];
    this.stage.animate(3500, (k) => {
      this.progress = from + (to - from) * k;
      this.apply();
    });
    this.stage.flyTo(unfold ? v.position : v.position.clone().add(this.center.clone().multiplyScalar(-0.01)), v.target, 3500);
  }

  pickables() {
    return this.stars.filter((s) => s.item_id).map((s) => ({ position: s.pos, data: { id: s.item_id, name: s.name } }));
  }

  describe(p) {
    const s = this.stars.find((x) => x.item_id === p.id);
    return s?.distance_ly ? `${s.name} — 약 ${Math.round(s.distance_ly).toLocaleString("ko-KR")}광년` : p.name;
  }
}
