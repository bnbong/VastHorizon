// 🌍 우주 지도 — 지구('나')를 중심으로 모든 항목을 실제 방향 · 로그 스케일 거리에 놓는다. 배경은 실제 별과 은하수.

import { CSS2DObject, SPACE_BG, THREE, dashedRing, knownMark, label, pointsMaterial, ring } from "./scene.js";
import { pulse } from "./sky.js";
import { MODELS, ModelShelf } from "./models.js";
import { BodyShelf } from "./bodyshelf.js";
import { DreamSphere } from "./dream.js";
import { DetailLayer } from "./details.js";
import { distanceText, eqToScene, mapRadius, radecToEq } from "./astro.js";
import { EQ_TO_MAP } from "./skydata.js";
import { loadMilkyway, loadStars, MilkyWayLayer, StarLayer } from "./starfield.js";
import { labelledIds, nearFade } from "./worldmarks.js";

const LINK_COLOR = 0xffe1dd;        // '나'와 알아간 빛을 잇는 실선 (web/tokens/colors.css --link-line)
const UNKNOWN_ALPHA = 0.12;         // 아직 만나지 않은 빛 — 기본 지도에서는 흐리게 (시안의 인상은 "빈 점 몇 개")
const FAR_TURN = -0.5;              // 가장 먼 알아간 빛을 화면 바로 위에서 이만큼(라디안) 돌려 놓는다

export class MapMode {
  constructor(data) {
    this.group = new THREE.Group();
    this.points = data.points.filter((p) => p.placement !== "origin").map((p) => ({
      ...p, position: new THREE.Vector3(...eqToScene(p.dir)).multiplyScalar(mapRadius(p.km)),
    }));
    this.byId = new Map(this.points.map((p) => [p.id, p]));
    this.earth = data.points.find((p) => p.placement === "origin");
    this.pickPx = 22;                 // 표식의 터치 영역 44px 이상 (scene.js Stage.pick)
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

    // 거리 고리 — 지구 중심, 적도면. 얇은 흰 선 (관측 가능한 우주의 끝만 조금 더 또렷한 살구빛)
    rings.forEach((ring, idx) => {
      const r = mapRadius(ring.km);
      const pts = Array.from({ length: 161 }, (_, i) => {
        const a = (i / 160) * Math.PI * 2;
        return new THREE.Vector3(Math.cos(a) * r, 0, Math.sin(a) * r);
      });
      this.group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineBasicMaterial({ color: ring.edge ? LINK_COLOR : 0xffffff, transparent: true, opacity: ring.edge ? 0.5 : 0.25 })));
      const tag = label(ring.label, ring.edge ? "label ring edge" : "label ring");
      const angle = -0.35 * idx;              // 고리마다 이름표 각도를 달리해 겹치지 않게
      tag.position.set(Math.cos(angle) * r, 0, Math.sin(angle) * r);
      this.group.add(tag);
    });

    // 아직 만나지 않은 빛 — 빈 점선 원, 이름 없이 흐리게. 알아간 천체는 이 층에서 빼고(투명) 살구색 표식으로 그린다.
    // 방향이 예시(지구 궤도 위성)인 점은 더 흐리게. 색 속성의 네 번째 값(투명도)으로 점마다 숨기고 일렁인다
    const positions = new Float32Array(this.points.length * 3);
    const colors = new Float32Array(this.points.length * 4);
    this.points.forEach((p, i) => {
      positions.set(p.position.toArray(), i * 3);
      colors.set([1, 1, 1, UNKNOWN_ALPHA], i * 4);
    });
    const geom = new THREE.BufferGeometry()
      .setAttribute("position", new THREE.BufferAttribute(positions, 3))
      .setAttribute("color", new THREE.BufferAttribute(colors, 4));
    this.pointGeom = geom;
    this.unknownDots = new THREE.Points(geom, pointsMaterial({ map: dashedRing(), size: 16, vertexColors: true }));
    this.group.add(this.unknownDots);

    // 나 — 작은 종이색 원 안의 '나' (지구 자리)
    this.meTag = new CSS2DObject(Object.assign(document.createElement("div"), { className: "world-me", textContent: "나" }));
    this.group.add(this.meTag);

    // 내 세계 — 내가 알아간(담은) 천체는 살구색 표식과 이름표, '나'에서 잇는 실선으로. 담지 않은 천체는 거리와 관계없이 아직 만나지 않은 빛이다.
    // (개인이 아직 모른다는 은유일 뿐, 천체의 물리적 상태와는 관계없다.) 가장 먼 빛까지는 영역처럼 보이지 않게 아주 옅은 테두리만
    this.reach = new DreamSphere({ strength: 0.22, sparkles: false });
    this.group.add(this.reach.group);
    // 알아간 빛의 선 — '나'에서 알아간 천체마다 곧게 (design-proposal .world-paths)
    this.trail = new THREE.Group();
    this.group.add(this.trail);
    this.crossedGroup = new THREE.Group();        // 넓어지는 순간 — 새로 안쪽에 들어온 천체 이름
    this.group.add(this.crossedGroup);
    this.clockT = 0;
    this.visitedGroup = new THREE.Group();
    this.group.add(this.visitedGroup);
    this.edgeRadius = mapRadius(Math.max(...rings.map((r) => r.km)));

    this.selectedTag = label("", "label selected");
    this.selectedTag.visible = false;
    this.group.add(this.selectedTag);
    // 선택 표시 — 아직 만나지 않은 천체는 둘레에서 맥박 치는 흰 고리 (하늘과 같은 모양).
    // 알아간 천체는 표식 바깥의 흰 1px 고리(.world-star.is-selected)로
    this.selectRing = new THREE.Points(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3()]),
      pointsMaterial({ map: ring(), size: 30, color: 0xffffff, opacity: 0.95 }));
    this.selectRing.visible = false;
    this.group.add(this.selectRing);
    // 가까이 가면 그 천체다운 모습 — 별 원반 · 허블 사진 · 성단 · 은하 중심 블랙홀 (details.js)
    this.details = new DetailLayer(this.points, this.group);
    // 대표 기체의 실제 형태 (NASA 3D 모델) — 가까이 가면 내려받아 그 점 자리에 띄운다
    this.models = new ModelShelf(this.group, this.points.filter((p) => MODELS[p.name]));
    // 태양계 천체의 3D 모습 (서랍 근접 뷰와 같은 메시) — 가까이 가면 그 점 자리에 띄운다
    this.bodies = new BodyShelf(this.group, this.points.filter((p) => p.group === "solar_system"));
  }

  update(dt, stage) {
    this.backdrop.position.copy(stage.camera.position);
    // 움직임 줄이기 — 테두리 · 분필 · 일렁임을 멈춘 채 그린다 (편하게 읽을 수 있게)
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches || new URLSearchParams(location.search).get("motion") === "off";
    this.still = still;
    if (!still) this.clockT += dt;
    this.reach.update(this.clockT);
    this.camDist = stage.camera.position.length();      // '나'(원점)에서 카메라까지
    this.shimmer(this.clockT);               // 카메라 거리에 따라 가까운 점선 원이 나타나고 숨는다 (움직임 줄이기면 일렁임만 멈춘다)
    // 빈 점선 원의 지름 — 데스크톱 16px, 좁은 화면 13px (design-proposal .world-unknown)
    this.unknownDots.material.size = stage.container.clientWidth <= 650 ? 13 : 16;
    this.models.update(dt, stage.camera);
    this.bodies.update(dt, stage.camera);
    this.details.update(this.clockT, stage.camera, still);
    if ((this.hushTick = (this.hushTick ?? 0) + 1) % 8 === 0) this.applyHush();
    this.clock = (this.clock ?? 0) + dt;
    pulse(this.selectRing.visible ? this.selectRing : null, this.clock, !matchMedia("(prefers-reduced-motion: reduce)").matches
      && new URLSearchParams(location.search).get("motion") !== "off");
  }

  enter(stage) {
    this.stage = stage;
    stage.scene.background = null;                    // 캔버스를 비워 그 뒤의 CSS 밤하늘 그라데이션(.app[data-mode="map"] .stage)이 보이게
    // 최대로 물러나면 관측 가능한 우주의 끝 전체가 보이는 자리 (edgeView와 같은 거리)
    // (좁은 화면에서 가장 먼 알아간 빛까지 한눈에 들어오는 자리가 그보다 멀면 그 자리까지)
    Object.assign(stage.controls, { minDistance: 1.5, maxDistance: Math.max(this.edgeView().length(), this.knownView().length()) });
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
    this.stage.scene.background = new THREE.Color(SPACE_BG);
  }

  // 화면 글과 겹치는 이름표 숨기기 — 거리 고리 이름 · 스치는 이름 같은 .label만 (알아간 빛의 표식과 '나'는 그대로).
  // hushZones: [{ x0, y0, x1, y1 }] 무대 기준 픽셀 — 머리글 · 요약 카드 · 바닥 문구 · 상단 (main.js syncHush)
  applyHush() {
    const zones = this.hushZones ?? [], cam = this.stage.camera;
    const w = this.stage.container.clientWidth, h = this.stage.container.clientHeight, v = new THREE.Vector3();
    this.group.traverse((o) => {
      if (!o.isCSS2DObject) return;
      // 이름표가 화면 오른쪽 밖으로 나가거나 요약 카드(nameZones)와 겹치면 표식의 왼쪽으로
      if (o.element.classList.contains("world-star")) {
        o.getWorldPosition(v).project(cam);
        const x = ((v.x + 1) / 2) * w, y = ((1 - v.y) / 2) * h;
        const nw = o.element.querySelector(".star-name")?.offsetWidth || 120, x0 = x + 18, x1 = x0 + nw;
        const left = x1 > w - 8 || (this.nameZones ?? []).some((z) => x1 >= z.x0 && x0 <= z.x1 && y + 14 >= z.y0 && y - 14 <= z.y1);
        if (o.element.classList.contains("name-left") !== left) o.element.classList.toggle("name-left", left);
        return;
      }
      if (!o.element.classList.contains("label")) return;
      o.getWorldPosition(v).project(cam);
      const x = ((v.x + 1) / 2) * w, y = ((1 - v.y) / 2) * h;
      const hush = v.z < 1 && zones.some((z) => x >= z.x0 && x <= z.x1 && y >= z.y0 && y <= z.y1);
      if (o.element.classList.contains("hushed") !== hush) o.element.classList.toggle("hushed", hush);
    });
  }

  // 알아간 천체가 모두 들어오는 자리 — 고리가 둥글게 보이도록 위에서 비스듬히. 아직 없으면 '나' 둘레의 가까운 빛들이 보이게.
  // 가장 먼 알아간 빛이 화면 위쪽 조금 오른편에 오도록 그 반대편에서 내려다본다 (왼쪽 머리글 · 오른쪽 아래 요약 카드를 비켜서)
  knownView() {
    let r = 10, far = null;
    for (const id of this.knownIds ?? []) {
      const p = this.lookup(id);
      if (p && p.position.length() >= r) { r = p.position.length(); far = p.position; }
    }
    const dir = new THREE.Vector3(0.3, 0.78, 0.55);
    if (far && Math.hypot(far.x, far.z) > 1e-6) {
      const h = new THREE.Vector2(-far.x, -far.z).normalize().rotateAround(new THREE.Vector2(), FAR_TURN);
      dir.set(h.x * 0.62, 0.78, h.y * 0.62);
    }
    const narrow = (this.stage?.container.clientWidth ?? 1000) <= 650;   // 좁은 화면은 세로로 길어 조금 더 물러난다
    return dir.normalize().multiplyScalar(r * (narrow ? 3.6 : 2.8));
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

  // 첫 화면 연출 — 지구 위 '나'에서 시작해 우주 전체로 시야를 넓힌다
  zoomOut(ms = 6000) {
    this.stage.flyTo(new THREE.Vector3(70, 120, 210), new THREE.Vector3(0, 0, 0), ms);
  }

  // 내 세계 — 반지름(바라본 가장 먼 거리)과 바라본 천체 이름표
  // fresh: 지금 막 담은 천체 — 표식이 떠오르고, 그 자리에서 '나'까지 선이 그려진다 (main.js bindCollect의 빛무리와 함께)
  setWorld(worldKm, visited, { fresh = null } = {}) {
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
    // 알아간 빛의 표식 — 그룹에서 빼도 CSS2D 요소는 DOM에 남으므로 직접 걷어낸다
    this.visitedGroup.traverse((o) => { if (o.isCSS2DObject) o.element.remove(); });
    this.visitedGroup.clear();
    this.visitedTags = new Map();
    this.visitedList = visited;
    const named = labelledIds(visited, this.selectedId);
    const stops = [];
    let freshPos = null;
    for (const v of visited) {
      const p = this.lookup(v.id);
      if (!p) continue;
      const mark = knownMark(p.name, { fresh: p.id === fresh });
      mark.element.classList.toggle("quiet", !named.has(p.id));   // 많아지면 이름표는 최근 것과 고른 것만
      mark.element.classList.toggle("is-selected", p.id === this.selectedId);
      mark.element.classList.toggle("has-letter", !!this.letterIds?.has(p.id));   // 빛의 편지를 받은 천체 — 작은 ✉ 표식
      mark.position.copy(p.position);
      this.visitedTags.set(p.id, mark);
      this.visitedGroup.add(mark);
      if (p.id === fresh) freshPos = p.position;
      else stops.push(p.position);
    }
    // '나'에서 알아간 빛마다 곧은 실선
    this.trail.clear();
    if (stops.length) {
      const pts = stops.flatMap((v) => [0, 0, 0, ...v.toArray()]);
      this.trail.add(new THREE.LineSegments(new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(pts, 3)),
        new THREE.LineBasicMaterial({ color: LINK_COLOR, transparent: true, opacity: 0.85, depthWrite: false })));
    }
    if (freshPos) this.drawLink(freshPos);
    if (this.selectedId) this.select(this.selectedId, { fly: false });   // 막 담은 천체 — 맥박 고리 대신 표식 둘레의 흰 고리로
  }

  // 막 담은 빛의 선 — 그 천체 자리에서 '나'(원점)까지 빛무리가 차오른 뒤 이어진다. 이 지도가 무대에 없거나 움직임 줄이기면 바로 끝 모습
  drawLink(to) {
    const geom = new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute([...to.toArray(), ...to.toArray()], 3));
    const line = new THREE.Line(geom, new THREE.LineBasicMaterial({ color: LINK_COLOR, transparent: true, opacity: 0.85, depthWrite: false }));
    line.frustumCulled = false;
    this.trail.add(line);
    const end = new THREE.Vector3(), pos = geom.attributes.position;
    const draw = (k) => {
      const u = Math.min(1, Math.max(0, (k - 0.18) / 0.82));
      end.copy(to).multiplyScalar(1 - u);
      pos.setXYZ(1, end.x, end.y, end.z);
      pos.needsUpdate = true;
    };
    if (this.stage?.mode === this) this.stage.animate(1700, draw);
    else draw(1);
  }

  // 담는 순간의 빛무리 자리 — 그 천체의 화면 좌표. 지도에 놓지 않는 천체(거리 미확인 · 별자리)는 '나'의 자리로
  screenOf(id) {
    if (!this.stage) return null;
    const p = id ? this.lookup(id) : null;
    return this.stage.screenOf(p ? p.position : new THREE.Vector3());
  }

  // 아직 만나지 않은 빛 — 담지 않은 천체는 거리와 관계없이 흐린 점선 원으로 천천히 일렁인다. 알아간 천체는 이 층에서 숨긴다(살구색 표식이 대신)
  // 카메라가 멀면 '나' 가까이(반지름이 작은) 몰린 원은 숨긴다 — 확대하면 나타난다 (nearFade)
  shimmer(t) {
    const col = this.pointGeom.attributes.color;
    const known = this.knownIds ?? new Set(), dist = this.camDist ?? 0;
    this.points.forEach((p, i) => {
      const base = p.placement === "illustrative" ? UNKNOWN_ALPHA * 0.6 : UNKNOWN_ALPHA;
      const near = nearFade(dist, p.position.length());
      col.setW(i, known.has(p.id) || !near ? 0 : base * near * (0.8 + 0.2 * Math.sin(t * (0.8 + (i % 7) * 0.13) + i)));
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

  // 떠오르기 — 땅 위의 나 → 내 세계의 끝 → 관측 가능한 우주의 끝
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

  // 카탈로그 점과, 카탈로그 밖에서 알아간 천체(하늘의 아무 별)도 누를 수 있게
  pickables() {
    return [...this.points, ...(this.extra?.values() ?? [])].map((p) => ({ position: p.position, data: p }));
  }

  describe(p) {
    const note = { illustrative: " · 방향은 예시", proxy: " · 위치는 근삿값" }[p.placement] ?? "";
    return `${p.name} — ${distanceText(p.km)}${note}`;
  }

  // 빛의 편지를 받은 천체 ID(letters.js letterItemIds) — 알아간 빛의 이름표에 작은 ✉ 표식 (.world-star.has-letter)
  setLetters(ids) {
    this.letterIds = ids;
    for (const [id, tag] of this.visitedTags ?? []) tag.element.classList.toggle("has-letter", ids.has(id));
  }

  // 선택 — 알아간 천체는 표식 바깥의 흰 1px 고리와 이름표, 아직 만나지 않은 천체는 맥박 고리와 이름표.
  // fly면 그 천체로 카메라를 옮긴다. id가 없거나 지도에 없는 천체면 표시를 지운다.
  // 지구는 점으로 놓지 않으므로(points에서 뺌) '나' 표식이 곧 선택 표시 — 고리 · 이름표 없이 원점으로
  select(id, { fly = true } = {}) {
    const earth = !!id && id === this.earth?.id;
    const p = id && !earth ? this.lookup(id) : null;
    this.selectedId = p || earth ? id : null;
    const named = labelledIds(this.visitedList ?? [], this.selectedId);
    for (const [tagId, tag] of this.visitedTags ?? []) {
      tag.element.classList.toggle("is-selected", tagId === this.selectedId);
      tag.element.classList.toggle("quiet", !named.has(tagId));
    }
    if (earth) {
      this.selectedTag.visible = false;
      this.selectRing.visible = false;
      // '나'가 화면 가운데 또렷이 — 가까운 천체로 갈 때(최소 8 + 위 4)와 비슷한 거리, 거리 눈금과 같은 방향에서. 궤도 위성 · 달이 둘레에 보인다
      if (fly && this.stage) this.stage.flyTo(new THREE.Vector3(0.33, 0.62, 0.85).normalize().multiplyScalar(10), new THREE.Vector3());
      return true;
    }
    const known = !!p && !!this.visitedTags?.has(id);
    if (!p || known) {
      this.selectedTag.visible = false;
      this.selectRing.visible = false;
      if (!p) return false;
    } else {
      this.selectedTag.element.textContent = p.name;
      this.selectedTag.position.copy(p.position);
      this.selectedTag.visible = true;
      this.selectRing.geometry.attributes.position.setXYZ(0, p.position.x, p.position.y, p.position.z);
      this.selectRing.geometry.attributes.position.needsUpdate = true;
      this.selectRing.geometry.computeBoundingSphere();
      this.selectRing.visible = true;
    }
    if (!fly || !this.stage) return true;
    const back = p.position.clone().normalize().multiplyScalar(Math.max(8, p.position.length() * 0.25));
    this.stage.flyTo(p.position.clone().add(back).add(new THREE.Vector3(0, 4, 0)), p.position.clone());
    return true;
  }
}
