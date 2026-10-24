// 태양계 천체의 3D 모습 — 내 세계 보기에서 태양 · 달 · 행성 · 위성 · 왜행성 · 소행성 · 혜성에 가까이 다가가면 띄운다.
//
// - 메시는 서랍 근접 뷰와 같은 것(bodyview.js buildBodyMesh — solar.js 셰이더 · 절차적 표면)을 쓴다. 표면은 상상도다.
// - 지도는 거리가 로그 스케일이라 크기도 실제 비율이 아니다. 모두 같은 지름(1.6, models.js와 같다)으로, 토성은 고리만큼 더 넓다.
// - 처음에는 만들지 않는다. 카메라가 그 점 가까이(30 안) 오면 그때 만들고(한 프레임에 하나씩), 멀어지면 숨긴다.
// - 셰이더가 uSun으로 스스로 빛을 받으므로 three.js 조명은 넣지 않는다. 빛은 서랍과 같이 화면 왼쪽 위 앞에서 (카메라 기준 고정 방향).
// - 위성은 모행성과 지도 위 자리가 거의 같다(로그 스케일). 겹치지 않게 모행성 둘레에 작게, 화면을 마주 보는 원 위에 늘어놓는다.

import { THREE } from "./scene.js";
import { SUN_DIR, buildBodyMesh } from "./bodyview.js";
import { bodyInfo } from "./solarbodies.js";

const NEAR = 30;          // 이보다 가까우면 천체를 보인다 (models.js와 같다)
const SIZE = 1.6;         // 천체의 지름 (지도 단위, models.js와 같다)
const SAME_SPOT = 0.5;    // 이보다 가까운 점끼리는 한 자리(모행성과 위성)로 본다
const MOON_SCALE = 0.4;   // 위성의 지름 — 모행성 지름에 대한 비율
const SATURN_EXTENT = 2.35;   // 토성 고리 바깥 반지름 / 토성 반지름 (solar.js saturnRings 136,780 / 58,232 km)

// 크기 순서를 정할 반지름 (km) — 세 축만 있는 천체는 가장 긴 축의 반
const radiusOf = (info) => info.radiusKm ?? Math.max(...(info.axesKm ?? [0])) / 2;

export class BodyShelf {
  constructor(group, points) {
    this.group = group;
    const items = points.map((p) => ({ point: p, info: bodyInfo(p.id) })).filter((it) => it.info)
      .map((it) => ({ ...it, object: null, mesh: null, primary: null, slot: 0 }));
    // 한 자리에 여럿이면 가장 큰 천체가 가운데, 나머지는 그 둘레의 위성 자리로
    const byRadius = [...items].sort((a, b) => radiusOf(b.info) - radiusOf(a.info));
    for (const it of byRadius) {
      const host = byRadius.find((o) => o !== it && !o.primary && radiusOf(o.info) >= radiusOf(it.info) && o.satellites
        && o.point.position.distanceTo(it.point.position) < SAME_SPOT);
      if (host) { it.primary = host; it.slot = host.satellites.length; host.satellites.push(it); }
      else it.satellites = [];
    }
    this.items = items;
    this.clock = 0;
  }

  update(dt, camera) {
    this.clock += dt;
    const q = camera.quaternion;
    const sun = SUN_DIR.clone().applyQuaternion(q);                 // 화면 왼쪽 위 앞 — 서랍의 근접 뷰와 같은 빛
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(q);
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(q);
    let built = false;
    for (const it of this.items) {
      const near = camera.position.distanceTo(it.point.position) < NEAR;
      if (near && !it.object && !built) {                         // 한 프레임에 하나씩 — 표면 지오메트리 계산이 몰리지 않게
        built = true;
        it.mesh = buildBodyMesh(it.info);
        it.object = it.mesh.tilt;
        it.object.scale.setScalar((SIZE / 2) * (it.primary ? MOON_SCALE : 1));
        it.object.position.copy(it.point.position);
        this.group.add(it.object);
      }
      if (!it.object) continue;
      it.object.visible = near;
      if (!near) continue;
      const { spin, uniforms, start } = it.mesh;
      spin.rotation.z = start + (2 * Math.PI * this.clock) / (it.info.spinSec ?? 10);
      if (uniforms.uTime) uniforms.uTime.value = this.clock;
      uniforms.uSun.value.copy(sun);
      if (it.primary) {                                             // 모행성 둘레에 고르게, 천천히 돈다
        const host = it.primary;
        const r = (SIZE / 2) * (host.info.key === "saturn" ? SATURN_EXTENT : 1) + SIZE * 0.4;
        const a = (2 * Math.PI * it.slot) / host.satellites.length + this.clock * 0.05;
        it.object.position.copy(host.point.position)
          .addScaledVector(right, Math.cos(a) * r).addScaledVector(up, Math.sin(a) * r);
      }
    }
  }

  // 시험 · 점검용 — 3D 모습이 보이는 천체
  shown() {
    return this.items.filter((it) => it.object?.visible).map((it) => it.point.name);
  }
}
