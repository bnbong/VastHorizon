// 위성 · 탐사선의 실제 형태 — 내 세계 보기에서 대표 기체에 가까이 다가가면 NASA 3D 모델을 띄운다.
//
// - 모델: NASA 3D Resources (저작권 없음, NASA 미디어 이용 지침) — web/data/models/CREDITS.md
// - 지도는 거리가 로그 스케일이라 크기도 실제 비율이 아니다. 모델은 알아볼 수 있는 크기(지름 약 1.6)로 맞춘다.
// - 처음에는 내려받지 않는다. 카메라가 그 점 가까이(30 안) 오면 그때 내려받고, 멀어지면 숨긴다.
// - 모델은 Draco로 압축되어 있어 three.js의 DRACOLoader(해제기는 web/vendor/libs/draco)로 푼다.

import { THREE } from "./scene.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";

export const MODELS = {
  "국제우주정거장": "iss", "허블 우주망원경": "hubble", "제임스 웹 우주망원경": "jwst",
  "보이저 1호": "voyager", "보이저 2호": "voyager",
};
const NEAR = 30;          // 이보다 가까우면 모델을 보인다
const SIZE = 1.6;         // 모델의 지름 (지도 단위)

let loader;
function gltfLoader() {
  if (loader) return loader;
  const draco = new DRACOLoader().setDecoderPath("vendor/libs/draco/gltf/");
  loader = new GLTFLoader().setDRACOLoader(draco);
  return loader;
}

const cache = new Map();
function loadModel(key) {
  if (!cache.has(key)) {
    cache.set(key, gltfLoader().loadAsync(`data/models/${key}.glb`).then((gltf) => {
      const root = gltf.scene;
      const box = new THREE.Box3().setFromObject(root);
      const center = box.getCenter(new THREE.Vector3());
      const radius = box.getSize(new THREE.Vector3()).length() / 2 || 1;
      root.position.sub(center);
      const holder = new THREE.Group();
      holder.add(root);
      holder.scale.setScalar(SIZE / 2 / radius);
      return holder;
    }).catch((e) => { cache.delete(key); throw e; }));
  }
  return cache.get(key);
}

export class ModelShelf {
  constructor(group, points) {
    this.group = group;
    this.items = points.map((p) => ({ point: p, key: MODELS[p.name], object: null, loading: false }));
    // 모델용 빛 — 지도의 다른 것(점 · 선)은 빛과 무관한 재질이라 영향을 받지 않는다
    this.light = new THREE.Group();
    const sun = new THREE.DirectionalLight(0xffffff, 2.2);
    sun.position.set(5, 3, 4);
    this.light.add(new THREE.AmbientLight(0x8899bb, 0.9), sun);
    group.add(this.light);
    this.clock = 0;
  }

  update(dt, camera) {
    this.clock += dt;
    for (const it of this.items) {
      const near = camera.position.distanceTo(it.point.position) < NEAR;
      if (near && !it.object && !it.loading) {
        it.loading = true;
        loadModel(it.key).then((holder) => {
          it.object = holder.clone();
          it.object.position.copy(it.point.position);
          this.group.add(it.object);
        }).catch((e) => console.warn("3D 모델을 불러오지 못했습니다", it.key, e))
          .finally(() => { it.loading = false; });
      }
      if (it.object) {
        it.object.visible = near;
        it.object.rotation.y = this.clock * 0.25;          // 천천히 돌려 모양을 보여 준다
      }
    }
  }

  // 시험 · 점검용 — 모델이 보이는 기체
  shown() {
    return this.items.filter((it) => it.object?.visible).map((it) => it.point.name);
  }
}
