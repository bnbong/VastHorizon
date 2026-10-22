// 천문 계산 · 좌표 변환 — 서버 features/sky.py 와 같은 식. Three.js에 의존하지 않는다 (node로 시험).

const DEG = Math.PI / 180;

export function julianDay(date) {
  return date.getTime() / 86400000 + 2440587.5;
}

// 지방 항성시 (도)
export function localSiderealDeg(date, lonDeg) {
  const gmst = 280.46061837 + 360.98564736629 * (julianDay(date) - 2451545.0);
  return (((gmst + lonDeg) % 360) + 360) % 360;
}

// 적경 · 적위 → 고도 · 방위 (방위: 북 0도 → 동 90도)
export function altAz(raDeg, decDeg, latDeg, lstDeg) {
  const ha = (lstDeg - raDeg) * DEG, dec = decDeg * DEG, phi = latDeg * DEG;
  const sinAlt = Math.sin(dec) * Math.sin(phi) + Math.cos(dec) * Math.cos(phi) * Math.cos(ha);
  const alt = Math.asin(Math.max(-1, Math.min(1, sinAlt)));
  const az = Math.atan2(-Math.cos(dec) * Math.sin(ha),
                        Math.sin(dec) * Math.cos(phi) - Math.cos(dec) * Math.sin(phi) * Math.cos(ha));
  return { alt: alt / DEG, az: ((az / DEG) % 360 + 360) % 360 };
}

// 적도 좌표 단위 벡터 (x: 춘분점, z: 천구 북극)
export function radecToEq(raDeg, decDeg) {
  const ra = raDeg * DEG, dec = decDeg * DEG;
  return [Math.cos(dec) * Math.cos(ra), Math.cos(dec) * Math.sin(ra), Math.sin(dec)];
}

// 적도 좌표 → 화면 좌표 (Three.js는 y가 위) — 천구 북극이 화면 위쪽
export function eqToScene([x, y, z]) {
  return [x, z, -y];
}

// 고도 · 방위 → 화면 좌표 (지평 좌표: y 위, 북쪽 −z, 동쪽 +x)
export function altAzToScene(altDeg, azDeg) {
  const alt = altDeg * DEG, az = azDeg * DEG;
  return [Math.cos(alt) * Math.sin(az), Math.sin(alt), -Math.cos(alt) * Math.cos(az)];
}

// 우주 지도의 로그 스케일 반지름 — 400km(국제우주정거장) ~ 250만 광년(안드로메다)을 한 화면에
export const MAP_SCALE = 6;
export function mapRadius(km) {
  return km > 0 ? Math.max(0.8, (Math.log10(km) - 2) * MAP_SCALE) : 0;
}

// 펼치기 — 별까지의 거리(광년)를 화면 반지름으로 (로그 스케일)
export function unfoldRadius(ly) {
  return 28 * Math.log10(Math.max(ly, 1.5));
}

const DIRS = ["북", "북동", "동", "남동", "남", "남서", "서", "북서"];
export function compass(azDeg) {
  return DIRS[Math.floor(((azDeg + 22.5) % 360) / 45)];
}

// 사람이 읽는 거리 — 서버의 korean_number 와 같은 단위 감각
export function distanceText(km) {
  const LY = 9460730472580.8, AU = 149597870.7;
  if (!km) return "지구";
  if (km < 1e6) return `약 ${Math.round(km).toLocaleString("ko-KR")} km`;
  if (km < 0.1 * LY) return `약 ${+(km / AU).toPrecision(3)} 천문단위`;
  const ly = km / LY;
  if (ly < 10000) return `약 ${+ly.toPrecision(3)} 광년`;
  if (ly < 1e8) return `약 ${+(ly / 1e4).toPrecision(3)}만 광년`;
  return `약 ${+(ly / 1e8).toPrecision(3)}억 광년`;
}

// 적도 좌표 단위 벡터 → 적경 · 적위 (도)
export function eqToRadec([x, y, z]) {
  return { ra: ((Math.atan2(y, x) / DEG) % 360 + 360) % 360, dec: Math.asin(Math.max(-1, Math.min(1, z))) / DEG };
}

// 지평선까지의 거리 (km) — 눈높이 h(m)에서 √(2Rh). 1.7m면 약 4.7km
export function horizonKm(eyeHeightM = 1.7) {
  return Math.sqrt(2 * 6371 * (eyeHeightM / 1000));
}

// 지금 보는 빛이 출발한 때 — 서버 item_text.departure_year 와 같은 식 (기준 연도 − 광년)
export function lightJourney(km, refYear) {
  const LY = 9460730472580.8;
  const ly = km / LY;
  if (ly < 1) return null;
  if (ly >= 100000) return `약 ${+(ly / 1e4).toPrecision(3)}만 년 전, 인류 문명 이전에 출발한 빛`;
  const year = Math.round(refYear - ly);
  return `${year > 0 ? `${year}년` : `기원전 ${1 - year}년`} 무렵 출발한 빛`;
}

// 내 세상의 반지름 표기 (디자인 v2 · 측정값) — {value, unit}
//   1만 km 미만 "4.7 km" · 1억 km 미만 "38.4만 km" · 450억 km 미만 "6.3억 km" · 0.5광년 미만 "170 AU" · 그 뒤 광년 · 만 광년 · 억 광년
export function measure(km) {
  const LY = 9460730472580.8, AU = 149597870.7;
  const n = (v, d = 0) => v.toLocaleString("ko-KR", { maximumFractionDigits: d });
  if (km < 1e4) return { value: n(km, 1), unit: "km" };
  if (km < 1e8) return { value: `${n(km / 1e4, 1)}만`, unit: "km" };
  if (km < 4.5e10) return { value: `${n(km / 1e8, 1)}억`, unit: "km" };
  if (km < 0.5 * LY) return { value: n(km / AU), unit: "AU" };
  const ly = km / LY;
  if (ly < 1e4) return { value: n(ly, ly < 10 ? 1 : 0), unit: "광년" };
  if (ly < 1e8) return { value: `${n(ly / 1e4, 1)}만`, unit: "광년" };
  return { value: `${n(ly / 1e8, 1)}억`, unit: "광년" };
}

// 지평선 길 — 지평선(4.7km)에서 관측 가능한 우주의 끝(4.4×10²³ km)까지 로그 비율 0~1
export const EDGE_KM = 4.4e23;
export function horizonScale(km) {
  const lo = Math.log10(horizonKm()), hi = Math.log10(EDGE_KM);
  return Math.max(0, Math.min(1, (Math.log10(Math.max(km, 1e-9)) - lo) / (hi - lo)));
}

// 빛이 출발한 때만 — "1478년 무렵" · "기원전 75년 무렵" · "약 254만 년 전" (1광년 미만이면 null)
export function departureLabel(km, refYear) {
  const LY = 9460730472580.8;
  const ly = km / LY;
  if (ly < 1) return null;
  if (ly >= 100000) return `약 ${+(ly / 1e4).toPrecision(3)}만 년 전`;
  const year = Math.round(refYear - ly);
  return `${year > 0 ? `${year}년` : `기원전 ${1 - year}년`} 무렵`;
}

// 큰 수를 만 · 억 · 조 · 경 · 해로 — 1.1경, 254만
export function koreanBig(x) {
  const units = [[1e20, "해"], [1e16, "경"], [1e12, "조"], [1e8, "억"], [1e4, "만"]];
  for (const [size, name] of units) {
    if (x >= size) return `${(+(x / size).toPrecision(x / size >= 100 ? 3 : 2)).toLocaleString("ko-KR")}${name}`;
  }
  return x >= 10 ? Math.round(x).toLocaleString("ko-KR") : `${+x.toPrecision(2)}`;
}

// 빛으로 걸리는 시간 — "약 1.3초" · "약 8.3분" · "약 24시간" · "약 548년" · "약 254만 년"
export function lightTime(km) {
  const s = km / 299792.458;
  const f = (v) => +v.toPrecision(v >= 100 ? 3 : 2);
  if (s < 60) return `약 ${f(s)}초`;
  if (s < 3600) return `약 ${f(s / 60)}분`;
  if (s < 86400 * 2) return `약 ${f(s / 3600)}시간`;
  const days = s / 86400;
  if (days < 365.25) return `약 ${f(days)}일`;
  const years = days / 365.25;
  return years < 1e4 ? `약 ${Math.round(years).toLocaleString("ko-KR")}년` : `약 ${koreanBig(years)} 년`;
}

// 내 세상의 크기를 와닿게 — 빛으로 걸리는 시간 · 지평선의 몇 배
export function worldScaleLine(km) {
  const ratio = km / horizonKm();
  if (ratio < 1.01) return "아직 지평선 너머를 바라보지 않았습니다";
  return `빛으로 ${lightTime(km)} 걸리는 거리 · 지평선의 ${koreanBig(ratio)} 배`;
}
