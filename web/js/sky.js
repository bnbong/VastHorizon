// ✨ 하늘 — 첫 화면. 내가 있는 곳 · 시각에 올려다본 실제 하늘.
// 히파르코스 별 11만 개(확대할수록 어두운 별까지) · 은하수 · 성운 · 성단 · 은하 · 별자리 선과 이름 · 지평선과 방위.
// 태양 · 달 · 행성은 그날의 위치를 브라우저에서 계산해 실제 시지름 · 실제 태양 방향의 빛으로 그린다 (solar.js — 달의 위상도 저절로).
//
// 화면의 모든 점은 실제 천체다. 카탈로그 천체(별 · 메시에)는 아직 관측하지 않았으면 옅은 고리로만 표시하고,
// 이야기를 읽고 '내 세상에 담기'를 누르면 금빛 고리와 이름이 생긴다. 아무 별이나 누르면 그 별(hip:…)의 서랍이 열린다.

import { THREE, label, pointsMaterial, ring } from "./scene.js";
import { altAzToScene, localSiderealDeg, radecToEq } from "./astro.js";
import { applyMatrix, colorWord, eqToHorizonMatrix, limitingMag, pickSky, transpose } from "./skydata.js";
import { DsoLayer, loadDsos, loadMilkyway, loadStars, MilkyWayLayer, StarLayer } from "./starfield.js";
import { SolarLayer } from "./solar.js";

const R = 100;
const DIRECTIONS = [["북", 0], ["북동", 45], ["동", 90], ["남동", 135], ["남", 180], ["남서", 225], ["서", 270], ["북서", 315]];
const PICK_PX = 12;
const FAINT_FROM = 7.6;            // 한계 등급이 이보다 높아지면(확대) 어두운 별 묶음을 내려받는다
const DEG = Math.PI / 180;

// 사진 가장자리를 부드럽게 — 가운데는 그대로, 바깥으로 갈수록 투명
let softDiscTexture;
function softDisc() {
  if (softDiscTexture) return softDiscTexture;
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0, "#fff");
  grad.addColorStop(0.6, "#fff");
  grad.addColorStop(1, "#000");
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  softDiscTexture = new THREE.CanvasTexture(c);
  return softDiscTexture;
}

// 하늘 끌기 속도 — OrbitControls는 회전각 = 2π × 끈 픽셀 / 화면 높이 × rotateSpeed.
// 화면 가운데에서 1픽셀은 2·tan(화각/2)/높이 만큼의 각이므로 rotateSpeed = tan(화각/2)/π 이면 잡은 하늘이 커서를 그대로 따라온다
// (작은 화각에서는 화각/360과 같다. 넓은 화각에서 화각/360을 쓰면 75도에서 86%만 따라왔다). 부호는 고개 돌리기 방향
export function skyRotateSpeed(fovDeg) {
  return -Math.tan((fovDeg * Math.PI) / 360) / Math.PI;
}

// 선택 고리의 맥박 — 움직임 줄이기면 멈춘 채로
export function pulse(points, t, moving) {
  if (!points) return;
  const k = moving ? 0.5 + 0.5 * Math.sin(t * 3.2) : 0.6;
  points.material.size = 26 + 10 * k;
  points.material.opacity = 0.55 + 0.4 * (1 - k);
}

export class SkyMode {
  // catalog: 우주 지도 점 중 하늘 방향이 있는 것 (별 · 메시에) — 관측 대상
  // solarItems: 태양계 항목 (이름으로 화면의 태양 · 달 · 행성과 잇는다)
  constructor(constellations, catalog, solarItems = []) {
    this.constellations = constellations;
    this.solarIds = new Map(solarItems.map((p) => [p.name, p.id]));
    this.catalog = catalog.map((p) => ({ ...p, eq: p.dir }));
    this.byCode = new Map(this.catalog.filter((p) => p.code).map((p) => [p.code.replace(/\s+/g, ""), p]));
    this.figureHips = new Set(constellations.flatMap((c) => c.stars.map((s) => s.hip)));
    this.group = new THREE.Group();
    this.dynamic = new THREE.Group();
    this.group.add(this.dynamic);
    this.buildStatic();
    this.solar = new SolarLayer({ radius: R, horizon: true });
    this.group.add(this.solar.group);
    this.solarLabels = new THREE.Group();      // 태양계 이름표 — 시야가 바뀔 때 이 그룹만 다시 만든다
    this.group.add(this.solarLabels);
    this.place = { lat: 37.5665, lon: 126.978, name: "서울" };
    this.date = new Date();
    this.planets = [];
    this.observed = new Set();
    this.justObserved = new Set();
    this.matrix = eqToHorizonMatrix(this.place.lat, localSiderealDeg(this.date, this.place.lon));
    this.dim = 1;
    this.loadSky();
    this.photos = new Map();             // 메시에 번호 → { sprite, state }
    fetch("data/messier/credits.json").then((r) => (r.ok ? r.json() : {})).then((c) => { this.photoCredits = c; })
      .catch(() => { this.photoCredits = {}; });
  }

  // 실제 하늘 — 밝은 별 · 은하수 먼저, 성운 · 성단 · 은하는 이어서
  async loadSky() {
    this.stars = new StarLayer({ radius: R, horizon: true });
    this.group.add(this.stars.group);
    this.ready = Promise.all([loadStars("bright"), loadMilkyway()]).then(([bright, mw]) => {
      this.stars.add(bright);
      this.milkyway = new MilkyWayLayer(mw, { radius: R * 0.999, horizon: true });
      this.group.add(this.milkyway.mesh);
      this.applyView();
    }).catch((e) => console.warn("하늘 데이터를 불러오지 못했습니다", e));
    loadDsos().then((data) => {
      this.dsos = new DsoLayer(data, { radius: R * 0.998, horizon: true });
      this.group.add(this.dsos.points);
      this.applyView();
    }).catch((e) => console.warn("성운 · 성단 · 은하 데이터를 불러오지 못했습니다", e));
  }

  // 확대하면 어두운 별 묶음(약 7.7만 개)을 그때 내려받는다
  loadFaint() {
    if (this.faintLoading) return;
    this.faintLoading = loadStars("faint").then((faint) => this.stars.add(faint))
      .catch((e) => { this.faintLoading = null; console.warn("어두운 별을 불러오지 못했습니다", e); });
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

  // visited: [{ id, name, ra, dec }] — 카탈로그 밖의 별(hip:…)도 담은 자리에 금빛 고리와 이름을 남긴다
  setObserved(visited) {
    this.observedAt = new Map(visited.filter((v) => v.ra != null).map((v) => [v.id, v]));
    const next = new Set(visited.map((v) => v.id));
    const changed = next.size !== this.observed.size || [...next].some((id) => !this.observed.has(id));
    this.observed = next;
    if (changed && this.stage?.mode === this) this.rebuild();
  }

  // 담기 — 옅은 고리가 금빛 고리와 이름으로. obj: { id, name, ra_deg, dec_deg }
  observe(obj) {
    const id = obj.id;
    if (this.observed.has(id)) return;
    if (obj.ra_deg != null) (this.observedAt ??= new Map()).set(id, { id, name: obj.name, ra: obj.ra_deg, dec: obj.dec_deg });
    this.observed.add(id);
    this.justObserved.add(id);
    if (this.stage?.mode === this) this.rebuild();
  }

  scenePos(eq, r = R) {
    return new THREE.Vector3(...applyMatrix(this.matrix, eq)).multiplyScalar(r);
  }

  // 위치 · 시각에 맞춰 회전 행렬 · 이름표 · 표시를 다시 놓는다 (별 자체는 GPU가 행렬로 옮긴다)
  rebuild() {
    this.dynamic.clear();
    this.gold = [];
    this.matrix = eqToHorizonMatrix(this.place.lat, localSiderealDeg(this.date, this.place.lon));
    this.targets = [];
    this.applyView();                    // 태양 · 달 · 행성의 위치 · 이름표 · 선택 대상도 여기서 (syncSolar)

    // 별자리 선 · 이름 — 늘 보인다
    const linePos = [];
    for (const con of this.constellations) {
      const byHip = new Map();
      const center = new THREE.Vector3();
      for (const s of con.stars) {
        const v = this.scenePos(radecToEq(s.ra_deg, s.dec_deg), R * 0.995);
        byHip.set(s.hip, v);
        center.add(v);
        // 별자리 선의 별 — 카탈로그 천체가 아니어도 누를 수 있다 (거리 · 등급은 별자리 모양 데이터)
        if (v.y < 0 || (s.item_id && this.byCode.get(`HIP${s.hip}`)) || !s.distance_ly) continue;
        const id = `hip:${s.hip}`;
        this.targets.push({ position: v, data: { id, kind: "figure-star", name: s.name, hip: s.hip, mag: s.mag,
          distance_ly: s.distance_ly, constellation: con.name, constellation_id: con.item_id } });
        if (this.observed.has(id)) this.addMark(v, s.name, id);
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

    // 카탈로그 천체 — 관측 전에는 옅은 고리, 담은 뒤에는 금빛 고리와 이름. 천체 자체는 실제 별 · 성운으로 이미 그려져 있다
    const faint = [], faintCol = [];
    for (const p of this.catalog) {
      const v = this.scenePos(p.eq, R * 0.99);
      if (v.y < 0) continue;
      const seen = this.observed.has(p.id);
      this.targets.push({ position: v, data: { ...p, kind: p.group, unobserved: !seen } });
      if (seen) this.addMark(v, p.name, p.id);
      else {
        faint.push(...v.toArray());
        faintCol.push(...(p.group === "messier" ? [0.62, 0.5, 0.85] : [0.6, 0.66, 0.8]));
      }
    }
    if (faint.length) {
      this.dynamic.add(new THREE.Points(
        new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(faint, 3))
          .setAttribute("color", new THREE.Float32BufferAttribute(faintCol, 3)),
        pointsMaterial({ map: ring(), size: 15, vertexColors: true, opacity: 0.32 * this.dim })));
    }
    // 그 밖에 담은 별 (아무 별이나 눌러 담은 hip:…)
    const marked = new Set(this.targets.map((x) => x.data.id));
    for (const v of this.observedAt?.values() ?? []) {
      if (marked.has(v.id)) continue;
      const pos = this.scenePos(radecToEq(v.ra, v.dec), R * 0.99);
      if (pos.y < 0) continue;
      this.addMark(pos, v.name, v.id);
      this.targets.push({ position: pos, data: { id: v.id, name: v.name, kind: "sky-star-seen" } });
    }
    if (this.gold.length) {
      this.dynamic.add(new THREE.Points(new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(this.gold, 3)),
        pointsMaterial({ map: ring(), size: 19, color: 0xe6bf78, opacity: 0.9 })));
    }
    this.justObserved.clear();


    this.placeSelection();
  }

  // 선택 표시 — 누른 천체 둘레에서 맥박 치는 고리와 이름. sel: { id, name, ra_deg, dec_deg, position } | null
  // 위치는 이름 있는 대상(카탈로그 · 별자리 · 행성 · 별자리 선의 별)이 먼저, 없으면 적경 · 적위, 그것도 없으면 누른 자리
  select(sel) {
    this.selected = sel;
    this.placeSelection();
  }

  placeSelection() {
    // 그룹을 떼어도 안쪽 CSS2D 이름표의 DOM 요소는 남는다 (다른 보기에 이름이 떠 있던 문제) — 직접 지운다
    this.selectMark?.traverse((o) => { if (o.isCSS2DObject) o.element.remove(); });
    this.selectMark?.removeFromParent();
    this.selectMark = null;
    const sel = this.selected;
    if (!sel || this.stage?.mode !== this) return;
    const target = this.targets?.find((x) => x.data.id === sel.id);
    const pos = target?.position.clone()
      ?? (sel.ra_deg != null ? this.scenePos(radecToEq(sel.ra_deg, sel.dec_deg), R * 0.99) : sel.position?.clone());
    if (!pos || pos.y < 0) return;
    const mark = new THREE.Group();
    const ringPts = new THREE.Points(new THREE.BufferGeometry().setFromPoints([pos]),
      pointsMaterial({ map: ring(), size: 30, color: 0x9fd8ff, opacity: 0.95 }));
    mark.add(ringPts);
    if (sel.name && !this.observed.has(sel.id)) {           // 담은 천체는 이미 이름이 있다
      const tag = label(sel.name, "label selected");
      tag.position.copy(pos);
      mark.add(tag);
    }
    mark.userData.ring = ringPts;
    this.selectMark = mark;
    this.dynamic.add(mark);
  }

  // 메시에 사진 — 화면에서 지름 60px보다 커지면 그 자리에 사진을 띄운다 (그때 내려받음).
  // 사진의 시야 · 방향 정보가 없어 카탈로그 크기(장축)에 맞춰 둥글게 보여 줄 뿐, 북쪽 방향은 맞추지 않는다.
  updatePhotos(fov, height) {
    if (!this.dsos || !this.photoCredits) return;
    this.photoRows ??= this.dsos.rows.filter((r) => r[7] && this.photoCredits[r[7]] && r[5]);
    const pxPerDeg = height / fov;
    for (const row of this.photoRows) {
      const [, , ra, dec, , major, , code] = row;
      const px = (major / 60) * pxPerDeg * 1.3;
      let p = this.photos.get(code);
      const pos = this.scenePos(radecToEq(ra, dec), R * 0.985);
      if (px < 60 || pos.y < 0) {
        if (p) p.sprite.visible = false;
        continue;
      }
      if (!p) {
        const material = new THREE.SpriteMaterial({ map: new THREE.TextureLoader().load(`data/messier/${code}.jpg`),
          alphaMap: softDisc(), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0 });
        material.map.colorSpace = THREE.SRGBColorSpace;
        p = { sprite: new THREE.Sprite(material) };
        p.sprite.renderOrder = 2;
        this.group.add(p.sprite);
        this.photos.set(code, p);
      }
      const size = 2 * pos.length() * Math.tan(((major * 1.3) / 120) * DEG);
      p.sprite.position.copy(pos);
      p.sprite.scale.set(size, size, 1);
      p.sprite.material.opacity = 0.95 * THREE.MathUtils.smoothstep(px, 60, 140) * this.dim;
      p.sprite.visible = true;
    }
  }

  // 태양 · 달 · 행성의 이름표와 선택 대상 — 위치 · 시야(한계 등급 · 원반 크기)가 바뀔 때마다 이 부분만 다시 만든다.
  // 지평선 위이고 지금 한계 등급으로 보이는 것만. 확대하면 해왕성처럼 어두운 행성이 나타나고, 축소하면 빠진다 (12-2 리뷰 P2)
  syncSolar() {
    this.solarLabels.traverse((o) => { if (o.isCSS2DObject) o.element.remove(); });
    this.solarLabels.clear();
    this.targets = (this.targets ?? []).filter((t) => t.data.kind !== "planet");
    for (const b of this.solar.placed ?? []) {
      if (!b.above || b.mag > this.limit) continue;
      const tag = label(b.key === "sun" || b.key === "moon" ? b.name : `● ${b.name}`, "label planet");
      tag.position.copy(b.position);
      // 원반이 커지면 이름표를 원반 아래로 비킨다 (가운데를 가리지 않게)
      if (b.diskPx > 10) tag.element.style.marginTop = `${Math.round(b.diskPx / 2 + 12)}px`;
      this.solarLabels.add(tag);
      this.targets.push({ position: b.position, pickRadius: b.diskPx / 2, data: { id: this.solarIds.get(b.name), name: b.name,
        kind: "planet", body: b.key, illum: b.illum, angularRadiusDeg: b.angularRadiusDeg, distanceKm: b.distanceKm } });
    }
  }

  // 담은 천체 — 이름표와 금빛 고리 (고리는 rebuild 끝에서 한 번에 그린다)
  addMark(v, name, id) {
    const tag = label(name, `label star ${this.justObserved.has(id) ? "observed" : ""}`);
    tag.position.copy(v);
    this.dynamic.add(tag);
    this.gold.push(...v.toArray());
  }

  // 회전 · 한계 등급 · 밝기를 층마다 반영
  applyView() {
    const fov = this.stage?.camera.fov ?? 75;
    const height = this.stage?.container.clientHeight ?? 800;
    const limit = limitingMag(fov);
    this.limit = limit;
    if (this.stars) {
      this.stars.setRotation(this.matrix);
      this.stars.setLimit(limit);
      this.stars.uniforms.uDim.value = this.dim;
      if (limit > FAINT_FROM) this.loadFaint();
    }
    this.solar.update(this.date, this.matrix, { pxPerDeg: height / fov, dim: this.dim });
    this.syncSolar();
    this.updatePhotos(fov, height);
    this.milkyway?.setRotation(this.matrix);
    // 은하수 지도는 0.5도 격자라 크게 확대하면 뿌옇게 번진다 — 화각 15도 아래로는 옅게
    if (this.milkyway) this.milkyway.uniforms.uStrength.value = 0.7 * this.dim * this.dim * THREE.MathUtils.clamp((fov - 4) / 11, 0.25, 1);
    if (this.dsos) {
      this.dsos.setRotation(this.matrix);
      this.dsos.setView({ fov, height, limit });
      this.dsos.uniforms.uShow.value = this.dim;
    }
  }

  update(dt) {
    if (this.stage?.mode !== this || !this.stars) return;
    this.stars.uniforms.uTime.value += dt;
    pulse(this.selectMark?.userData.ring, this.stars.uniforms.uTime.value, this.stars.uniforms.uTwinkle.value > 0);
    if (this.stage.camera.fov !== this.lastFov) {
      this.lastFov = this.stage.camera.fov;
      this.stage.controls.rotateSpeed = skyRotateSpeed(this.lastFov);
      this.applyView();
    }
  }

  // 낮 · 박명이면 하늘을 밝게, 별 · 은하수는 흐리게 — 태양 고도는 서버(/api/sky)가 계산한다
  setDaylight(sunAltDeg) {
    const night = new THREE.Color(0x02040a), day = new THREE.Color(0x2b4f7e);
    const k = THREE.MathUtils.clamp((sunAltDeg + 12) / 18, 0, 1);      // −12도 이하 밤 → +6도 이상 낮
    this.background = night.lerp(day, k);
    this.dim = 1 - 0.9 * k;
    if (this.stage?.mode === this) this.stage.scene.background = this.background;
    this.applyView();
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
    stage.fovMin = 0.05;                                 // 확대하면 12등급 별 · 행성의 원반 (목성 지름 약 45″)까지
    // 관성 없이, 잡은 하늘이 커서를 그대로 따라오게 — 확대했을 때 천체가 미끄러져 달아나지 않는다
    Object.assign(stage.controls, { enableZoom: false, enablePan: false, enableDamping: false, rotateSpeed: skyRotateSpeed(75) });
    // 좌우로 끌면 방위각이 돈다. 고도가 높은 곳을 볼수록 방위각 1도가 화면에서 cos(고도)만큼 짧아지므로 그만큼 더 돌린다
    // (천정 근처는 cos 0.3에서 멈춘다) — 잡은 하늘이 좌우로도 커서를 따라오게
    const rotateLeft = Object.getPrototypeOf(stage.controls)._rotateLeft;
    stage.controls._rotateLeft = (angle) => {
      const look = new THREE.Vector3();
      stage.camera.getWorldDirection(look);
      rotateLeft.call(stage.controls, angle / Math.max(0.3, Math.sqrt(1 - look.y * look.y)));
    };
    // 카메라를 중심 바로 옆에 두고 중심을 바라보게 하면, 회전이 '고개 돌리기'가 된다.
    // 남쪽 하늘 고도 25도를 바라보면 지평선이 화면 높이의 약 80%에 놓인다 (화각 75도)
    const south = new THREE.Vector3(...altAzToScene(25, 180));
    stage.controls.target.set(0, 0, 0);
    stage.camera.position.copy(south.multiplyScalar(-0.01));
    stage.camera.fov = 75;
    stage.camera.updateProjectionMatrix();
    stage.scene.background = this.background ?? new THREE.Color(0x02040a);
    const twinkle = !(matchMedia("(prefers-reduced-motion: reduce)").matches
      || new URLSearchParams(location.search).get("motion") === "off");
    this.stars.uniforms.uTwinkle.value = twinkle ? 1 : 0;
    this.rebuild();
  }

  exit() {
    delete this.stage.controls._rotateLeft;          // 다른 보기는 원래 회전으로
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

  // 이름 있는 대상(pickables)이 없을 때 — 누른 방향에서 가장 가까운 실제 별 · 성운 · 은하
  pickNear(clientX, clientY) {
    if (!this.stars?.parts.length) return null;
    const stage = this.stage, rect = stage.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, stage.camera);
    const dir = ray.ray.direction;
    if (dir.y < 0) return null;                                      // 땅
    const [x, y, z] = applyMatrix(transpose(this.matrix), dir.toArray());
    const ra = ((Math.atan2(y, x) / DEG) % 360 + 360) % 360, dec = Math.asin(Math.max(-1, Math.min(1, z))) / DEG;
    const radius = (PICK_PX * stage.camera.fov) / rect.height;
    const toHit = (eq, data, degAway) => ({ d: (degAway / radius) * PICK_PX, position: this.scenePos(eq, R * 0.99), data });

    const view = { fov: stage.camera.fov, height: rect.height, limit: this.limit };
    const hit = pickSky(this.stars.parts, this.dsos, ra, dec, radius, this.limit, (i) => this.dsos.visible(i, view));
    if (!hit) return null;
    if (hit.type === "star") {
      const { stars } = this.stars.parts[hit.part], i = hit.index;
      const catalogStar = this.byCode.get(`HIP${stars.hip[i]}`);
      const data = catalogStar ? { ...catalogStar, kind: catalogStar.group, unobserved: !this.observed.has(catalogStar.id) }
        : { id: `hip:${stars.hip[i]}`, kind: "sky-star", hip: stars.hip[i], mag: stars.mag[i], bv: stars.bv[i] };
      return toHit(radecToEq(stars.ra[i], stars.dec[i]), data, hit.away);
    }
    // 성운 · 성단 · 은하 — 메시에 천체는 카탈로그 항목으로, 나머지는 이름만 알려 준다
    const [name, , dra, ddec, , , , messierNo] = this.dsos.rows[hit.index];
    const messier = messierNo && this.byCode.get(messierNo);
    const data = messier ? { ...messier, kind: messier.group, unobserved: !this.observed.has(messier.id) }
      : { kind: "dso", index: hit.index, name };
    return toHit(radecToEq(dra, ddec), data, Math.min(hit.away, radius));
  }

  describe(p) {
    if (p.kind === "sky-star") return `HIP ${p.hip}: ${p.mag.toFixed(1)}등급 ${colorWord(p.bv)} 별 · 눌러서 알아보기`;
    if (p.kind === "dso") return this.dsos.describe(p.index);
    if (p.unobserved) return `${p.name}: 아직 관측 전 · 눌러서 알아보기`;
    if (p.kind === "constellation") return `${p.name}: 별자리`;
    if (p.kind === "planet") {
      if (p.body === "moon") return `달: 밝은 부분 ${Math.round(p.illum * 100)}%, ${Math.round(p.distanceKm).toLocaleString("ko-KR")} km`;
      if (p.body === "sun") return "태양";
      return `행성 ${p.name}: 지름 ${(p.angularRadiusDeg * 7200).toFixed(1)}″, 밝은 부분 ${Math.round(p.illum * 100)}%`;
    }
    if (p.kind === "figure-star") return `${p.name}: ${p.constellation}의 별`;
    return p.name;
  }
}
