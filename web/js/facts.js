// 천체 카드의 핵심 사실 한 문장 — 항목 메타데이터(근거 1: 거리 · 종류 · 발사일 · 별자리 모양 데이터)만으로 만든다. LLM 없음.
//
//   { before, em, after, detail }  — 문장은 before + em(핵심 숫자, 보라) + after. detail은 그 숫자의 근거를 풀어 쓴 두 문장
//   만들 근거가 없으면 null (화면은 그 줄을 생략한다)
//
//   별 · 메시에 (1광년 이상)   지금 눈에 닿은 빛은 [약 25년]을 건너왔어요.            거리(광년) → 빛이 걸린 시간
//   태양계 천체                이 빛은 [약 1.3초] 전에 달을 떠났어요.                 거리(km) ÷ 광속
//   지구 궤도 위성             지금 [약 420 km] 높이에서 지구를 돌고 있어요.          지표면 위 궤도 고도
//   탐사선 · 우주망원경        빛의 속도로도 [약 24시간]이 걸리는 곳에 있어요.         거리(km) ÷ 광속
//   거리를 모르는 인공물       [1977년]에 지구를 떠났어요.                            발사일
//   별자리                     이 모양을 이루는 별 중 가장 먼 별은 [약 1,340광년] 떨어져 있어요.   별자리 선의 별 거리
//   그 밖                      {이름}은(는) [{종류}]예요.                              종류만

import { departureLabel, distanceText, lightTime } from "./astro.js";

const LY_KM = 9460730472580.8;
const SURFACE = "지표면 위 궤도 고도";

// 받침이 있으면 첫째, 없으면 둘째 — 을/를 · 은/는 · 이에요/예요. 한글이 아니면 둘을 함께 쓴다
export function josa(word, withFinal, without) {
  const ch = String(word ?? "").trim().slice(-1);
  const code = ch.charCodeAt(0) - 0xac00;
  if (code < 0 || code > 11171) return `${withFinal}(${without})`;
  return code % 28 ? withFinal : without;
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
