// 천체 카드의 핵심 사실 한 문장 — 항목 메타데이터(근거 1: 거리 · 종류 · 발사일 · 별자리 모양 데이터)만으로 만든다. LLM 없음.
//
//   { before, em, after, detail }  — 문장은 before + em(핵심 숫자, 보라) + after. detail은 그 숫자의 근거를 풀어 쓴 두 문장
//   만들 근거가 없으면 null (화면은 그 줄을 생략한다)
//
//   우리 은하                  우리는 이 은하 안에 있어요. 은하 중심까지는 [약 2.6만 광년]이에요.   지구에서 은하 중심까지의 거리
//   궁수자리 A* (블랙홀)       지금 지구에 닿은 전파는 [약 2.6만 년]을 건너왔어요.     거리(광년) → 전파가 걸린 시간 (가시광선으로는 보이지 않는다)
//   별 · 메시에 (1광년 이상)   지금 눈에 닿은 빛은 [약 25년]을 건너왔어요.            거리(광년) → 빛이 걸린 시간
//   태양계 천체                이 빛은 [약 1.3초] 전에 달을 떠났어요.                 거리(km) ÷ 광속
//   지구 궤도 위성             지금 [약 420 km] 높이에서 지구를 돌고 있어요.          지표면 위 궤도 고도
//   탐사선 · 우주망원경        빛의 속도로도 [약 24시간]이 걸리는 곳에 있어요.         거리(km) ÷ 광속
//   거리를 모르는 인공물       [1977년]에 지구를 떠났어요.                            발사일
//   별자리                     이 모양을 이루는 별 중 가장 먼 별은 [약 1,340광년] 떨어져 있어요.   별자리 선의 별 거리
//   그 밖                      {이름}은(는) [{종류}]예요.                              종류만

import { departureLabel, distanceText, horizonKm, lightTime } from "./astro.js";

const LY_KM = 9460730472580.8;
const SURFACE = "지표면 위 궤도 고도";

// 받침이 있으면 첫째, 없으면 둘째 — 을/를 · 은/는 · 이에요/예요. 한글이 아니면 둘을 함께 쓴다
export function josa(word, withFinal, without) {
  const ch = String(word ?? "").trim().slice(-1);
  const code = ch.charCodeAt(0) - 0xac00;
  if (code < 0 || code > 11171) return `${withFinal}(${without})`;
  return code % 28 ? withFinal : without;
}

// 우리 은하 — 우리는 그 안에 있어 '우리 은하까지의 거리'는 없다. 방향 · 거리는 은하 중심의 것이고 거리 기준(reference)으로 밝힌다
//   (서버 vasthorizon/data/items/common.py REF_GALACTIC_CENTER와 같은 글자)
export const MILKY_WAY_ID = "Q321";
export const CENTER_REF = "지구에서 우리 은하 중심까지";

// 목록 · 담기 안내 · 지도 툴팁의 거리 글. id나 거리 기준이 은하 중심이면 "은하 중심까지 약 2.6만 광년", 아니면 distanceText(km)
export function distanceLabel(km, { id = null, reference = null } = {}) {
  const center = id === MILKY_WAY_ID || reference === CENTER_REF;
  return center && km ? `은하 중심까지 ${distanceText(km)}` : distanceText(km);
}

const year = (d) => (/^\d{4}/.test(String(d ?? "")) ? Number(String(d).slice(0, 4)) : null);

// item: /api/items/{id} 응답 · figure: 별자리면 그 별자리 모양 데이터({ stars: [{ name, distance_ly }] }) · refYear: 빛이 출발한 해의 기준
export function heroFact(item, { figure = null, refYear = new Date().getFullYear() } = {}) {
  if (!item) return null;
  const name = item.name ?? "";
  const km = item.distance_km ?? item.distance?.km ?? null;
  const attrs = item.attrs ?? {};
  const surface = item.distance?.reference === SURFACE;

  if (item.group === "constellation") {
    const stars = (figure?.stars ?? []).filter((s) => s.distance_ly > 0);
    if (stars.length >= 2) {
      const far = stars.reduce((a, b) => (b.distance_ly > a.distance_ly ? b : a));
      const near = stars.reduce((a, b) => (b.distance_ly < a.distance_ly ? b : a));
      return { before: "이 모양을 이루는 별 중 가장 먼 별은 ", em: distanceText(far.distance_ly * LY_KM), after: " 떨어져 있어요.",
               detail: `선으로 이은 별 ${stars.length}개는 지구에서 볼 때만 한자리에 모여 보입니다. 가장 가까운 ${near.name ?? "별"}${josa(near.name, "은", "는")} ${distanceText(near.distance_ly * LY_KM)}, 가장 먼 ${far.name ?? "별"}${josa(far.name, "은", "는")} ${distanceText(far.distance_ly * LY_KM)}입니다.` };
    }
    const bright = String(attrs["가장 밝은 별"] ?? "").replace(/\s*\(.*\)\s*$/, "");
    if (bright) {
      return { before: "이 별자리에서 가장 밝은 별은 ", em: bright, after: `${josa(bright, "이에요", "예요")}.`,
               detail: attrs["관측 계절"] ? `${attrs["관측 계절"]} 밤하늘에서 잘 보이는 별자리입니다.${attrs["저녁에 잘 보이는 달"] ? ` 저녁에는 ${attrs["저녁에 잘 보이는 달"]}에 잘 보입니다.` : ""}` : "" };
    }
  }

  if (km > 0 && surface) {
    const period = Number(attrs["공전 주기(분)"]);
    return { before: "지금 ", em: distanceText(km), after: " 높이에서 지구를 돌고 있어요.",
             detail: period > 0 ? `한 바퀴 도는 데 약 ${Math.round(period)}분이 걸려, 하루에 지구를 약 ${Math.round(1440 / period)}바퀴 돕니다.${year(attrs["발사일"]) ? ` ${year(attrs["발사일"])}년에 발사되었습니다.` : ""}`
               : year(attrs["발사일"]) ? `${year(attrs["발사일"])}년에 발사되었습니다.` : "" };
  }

  if (km > 0 && item.distance?.reference === CENTER_REF) {
    const em = distanceText(km);
    return { before: "우리는 이 은하 안에 있어요. 은하 중심까지는 ", em, after: `${josa(em, "이에요", "예요")}.`,
             detail: attrs["보이는 모습"] ? `밤하늘의 은하수가 이 은하를 안에서 본 모습입니다. ${attrs["보이는 모습"]}.` : "" };
  }

  if (km > 0 && item.group === "milky_way") {
    return { before: "지금 지구에 닿은 전파는 ", em: lightTime(km), after: "을 건너왔어요.",
             detail: `이 블랙홀까지의 거리가 ${distanceText(km)}이기 때문입니다.${attrs["관측"] ? ` ${attrs["관측"]}.` : ""}` };
  }

  if (km > 0 && (item.group === "star" || item.group === "messier") && km / LY_KM >= 1) {
    const what = item.group === "star" ? "별" : "천체";
    const departed = departureLabel(km, refYear);
    return { before: "지금 눈에 닿은 빛은 ", em: lightTime(km), after: "을 건너왔어요.",
             detail: `이 ${what}까지의 거리가 ${distanceText(km)}이기 때문입니다. 오늘 밤 보이는 것은 ${departed}에 출발한 빛입니다.` };
  }

  if (km > 0 && item.group === "solar_system") {
    return { before: "이 빛은 ", em: lightTime(km), after: ` 전에 ${name}${josa(name, "을", "를")} 떠났어요.`,
             detail: `지금 지구에서 ${distanceText(km)} 떨어져 있어, 빛의 속도(초속 약 30만 km)로도 그만큼 걸립니다.${attrs["평균 반지름(km)"] ? ` 평균 반지름은 약 ${Math.round(attrs["평균 반지름(km)"]).toLocaleString("ko-KR")} km입니다.` : ""}` };
  }

  if (km > 0 && item.group === "human_made") {
    const t = lightTime(km);
    return { before: "빛의 속도로도 ", em: t, after: `${josa(t, "이", "가")} 걸리는 곳에 있어요.`,
             detail: `지금 지구에서 ${distanceText(km)} 떨어져 있습니다.${year(attrs["발사일"]) ? ` ${year(attrs["발사일"])}년에 발사되었습니다.` : ""}` };
  }

  const launched = year(attrs["발사일"]);
  if (launched) {
    return { before: "", em: `${launched}년`, after: "에 지구를 떠났어요.", detail: attrs["현재 위치"] ? `현재 위치는 ${attrs["현재 위치"]}입니다.` : "" };
  }

  const kind = item.kind ?? attrs["분류"];
  if (kind && name) {
    return { before: `${name}${josa(name, "은", "는")} `, em: kind, after: `${josa(kind, "이에요", "예요")}.`, detail: "" };
  }
  return null;
}

// 지구 서랍에만 붙는 한 문단 — 핵심 사실(지구는 거리가 없어 '종류' 분기) 아래에. 다른 천체는 null
//   4.7 km: 지평선까지의 거리 (astro.horizonKm — 눈높이 1.7 m, 지구 반지름 6,371 km, 프롤로그와 같은 계산)
//   61억 km · 0.12화소: README "고개를 들면 보이는 사실들" (위키백과 「창백한 푸른 점」)
export const EARTH_ID = "Q2";
export const EARTH_SOURCE = { name: "위키백과 「창백한 푸른 점」", url: "https://ko.wikipedia.org/wiki/창백한_푸른_점" };

export function placeNote(item) {
  if (item?.id !== EARTH_ID) return null;
  const horizon = horizonKm().toFixed(1);
  return {
    text: `지금 당신이 서 있는 곳입니다. 눈높이에서 바라보면 세상의 끝은 약 ${horizon} km 떨어진 지평선이지만, 오늘 밤 고개를 들면 그 끝은 별까지 이어집니다. `
      + "보이저 1호가 약 61억 km 떨어진 곳에서 찍은 사진에서 지구는 0.12화소 크기의 점이었습니다. "
      + "그 작은 점 위에서 당신은 아직 만나지 못한 빛을 바라보고 있습니다.",
    source: EARTH_SOURCE,
  };
}
