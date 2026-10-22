"""항목 1건 → 색인 텍스트 1개 · 검색 필터용 메타데이터. (F2001)

사용자가 무엇으로 항목을 찾을지를 기준으로 속성을 묶는다.
- 이름 · 영문명 · 종류 → "안드로메다", "산개 성단"
- 거리 · 빛이 걸리는 시간 · 빛이 출발한 시대 → "조선 시대에 출발한 빛"
- 관측 정보 → "맨눈으로 볼 수 있는", "겨울밤에 보이는"
- 탐사 정보 → "한국이 쏘아 올린", "지금도 운용 중인"
"""

from __future__ import annotations

import hashlib
import math
import re

from vasthorizon.data.items.common import GROUPS, LY_KM, REF_SURFACE_ALTITUDE

SOURCE_TYPE = "항목 메타데이터"
LIGHT_KM_S = 299_792.458
YEAR_S = 365.25 * 24 * 3600

# 색인 텍스트에 넣지 않는 내부용 속성
HIDDEN_ATTRS = {"horizons_id", "별자리 약어", "발사일 출처", "Horizons 위치 기준일", "SATCAT 스냅샷"}
# '아니오'도 정보가 되는 속성 — 나머지 거짓 값은 검색 잡음이라 뺀다
SHOW_FALSE_ATTRS = {"맨눈 관측", "황도 별자리"}


# ── 숫자 · 시간 표현 ────────────────────────────────────────────────────────

def korean_number(value: float) -> str:
    """큰 수를 만 · 억 · 조 단위로. 예: 2_540_000 → '254만', 227_300_000 → '2.27억'."""
    units = [("", 1.0), ("만", 1e4), ("억", 1e8), ("조", 1e12)]
    idx = max(i for i, (_, size) in enumerate(units) if abs(value) >= size or i == 0)
    while True:
        unit, size = units[idx]
        scaled = value / size
        digits = 0 if abs(scaled) >= 100 else (1 if abs(scaled) >= 10 else 2)
        # 반올림하면 1만이 되는 값은 한 단계 큰 단위로 올린다 — 99,999,999 → '1억' ('10,000만' 아님)
        if round(abs(scaled), digits) >= 10_000 and idx + 1 < len(units):
            idx += 1
            continue
        break
    if unit == "" and abs(value) < 100:
        return f"{value:.3g}"
    return _trim_fraction(f"{scaled:,.{digits}f}") + unit


def _trim_fraction(text: str) -> str:
    """소수점 아래의 불필요한 0만 지운다. 정수부의 0과 천 단위 구분자는 보존한다."""
    if "." not in text:
        return text
    return text.rstrip("0").rstrip(".")


def light_time_text(km: float) -> str:
    """빛이 그 거리를 가는 데 걸리는 시간."""
    seconds = km / LIGHT_KM_S
    if seconds < 60:
        return f"약 {seconds:.2g}초"
    if seconds < 3600:
        return f"약 {seconds / 60:.2g}분"
    if seconds < 86400:
        return f"약 {seconds / 3600:.2g}시간"
    if seconds < YEAR_S:
        return f"약 {seconds / 86400:.2g}일"
    return f"약 {korean_number(seconds / YEAR_S)}년"


def departure_year(ly: float, ref_year: int) -> int:
    """지금 보는 빛이 출발한 해 (기원전은 음수, 0년은 없다)."""
    year = round(ref_year - ly)
    return year if year > 0 else year - 1


def year_text(year: int) -> str:
    return f"기원전 {-year}년" if year < 0 else f"{year}년"


# 한국사 시대 — (시작 연도, 이름), 최근 순. 색인 텍스트와 조건 탐색 프롬프트가 같은 표를 쓴다.
KOREAN_ERAS = [
    (1948, "대한민국 시대"), (1945, "광복 직후"), (1910, "일제 강점기"), (1897, "대한제국 시대"),
    (1392, "조선 시대"), (918, "고려 시대"), (676, "통일 신라 시대"), (-57, "삼국 시대"),
    (-2333, "고조선 시대"),
]


def korean_era(year: int) -> str:
    """빛이 출발한 해의 한국사 시대 — '조선 시대에 출발한 빛' 같은 조건 검색용."""
    for start, name in KOREAN_ERAS:
        if year >= start:
            return name
    return "인류 문명 이전"


def era_ranges() -> list[tuple[str, int, int | None]]:
    """(시대 이름, 시작 연도, 끝 연도 — 지금까지면 None)."""
    ranges, end = [], None
    for start, name in KOREAN_ERAS:
        ranges.append((name, start, end))
        end = start - 1
    return ranges


def distance_text(dist: dict) -> str:
    km, ly = dist["km"], dist["ly"]
    if dist["reference"] == REF_SURFACE_ALTITUDE:
        text = f"지표면 위 고도 약 {korean_number(km)}km"
    elif ly >= 0.1:
        text = f"지구로부터 약 {korean_number(ly)}광년"
    else:
        text = f"지구로부터 약 {korean_number(km)}km"

    notes = []
    if dist.get("n_values", 1) > 1 and dist.get("km_min") and dist.get("km_max"):
        lo, hi = dist["km_min"] / LY_KM, dist["km_max"] / LY_KM
        if ly >= 0.1:
            notes.append(f"출처 {dist['n_values']}개 값의 중앙값, 범위 {korean_number(lo)}~{korean_number(hi)}광년")
        else:
            notes.append(f"출처 {dist['n_values']}개 값의 중앙값")
    elif dist.get("method"):
        notes.append(dist["method"])
    if dist.get("approximate"):
        notes.insert(0, "근삿값")
    return text + (f" ({' · '.join(notes)})" if notes else "")


def light_lines(dist: dict, ref_year: int) -> list[str]:
    """빛이 걸리는 시간과 출발 시점. 지표 고도처럼 지구 중심 거리가 아니면 만들지 않는다."""
    if dist["reference"] == REF_SURFACE_ALTITUDE:
        return []
    lines = [f"빛이 걸리는 시간: {light_time_text(dist['km'])}"]
    ly = dist["ly"]
    if ly >= 1:
        if ly < 100_000:
            year = departure_year(ly, ref_year)
            lines.append(f"지금 보는 빛이 출발한 때: {year_text(year)} 무렵 ({korean_era(year)})")
        else:
            lines.append(f"지금 보는 빛이 출발한 때: 약 {korean_number(ly)}년 전 (인류 문명 이전)")
    return lines


# ── 요약 문장 ───────────────────────────────────────────────────────────────
# "키: 값" 나열만으로는 자연어 질문과 의미가 잘 맞지 않는다.
# 속성으로 만든 요약 문장을 맨 앞에 둬서 "태양계 밖으로 나간 우주선" 같은 질문에 걸리게 한다.
# LLM을 쓰지 않는 규칙 기반 문장이라 속성에 없는 내용은 들어가지 않는다.

def _has_batchim(word: str) -> bool:
    """마지막 글자의 받침 여부. 끝의 괄호 설명은 건너뛴다 — '소멸(재진입)' → '소멸' 기준."""
    word = re.sub(r"\s*\([^)]*\)\s*$", "", word or "")
    last = word.rstrip()[-1:]
    if "가" <= last <= "힣":
        return (ord(last) - 0xAC00) % 28 != 0
    return last in "013678LMNRlmnr"     # 영문 · 숫자는 읽는 소리 기준 근사


def josa(word: str, pair: str) -> str:
    """받침에 따라 조사를 붙인다. pair 예: '은는', '이가', '을를', '와과'."""
    return word + (pair[0] if _has_batchim(word) else pair[1])


def copula(word: str) -> str:
    """서술격 조사 — '성단이다', '별자리다'."""
    return word + ("이다" if _has_batchim(word) else "다")


def euro(word: str) -> str:
    """'(으)로' — ㄹ 받침이거나 받침이 없으면 '로'."""
    last = re.sub(r"\s*\([^)]*\)\s*$", "", word).rstrip()[-1:]
    rieul = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 == 8
    return word + ("으로" if _has_batchim(word) and not rieul else "로")


def display_name(name: str) -> str:
    """'다누리 (우주선)' → '다누리'. 위키 동음이의 구분 괄호를 뗀다."""
    return name.split(" (")[0]


def _location_phrase(location: str) -> str:
    base = location.split(" (")[0]
    if base == "태양계 탈출 궤도":
        return "지금은 태양계를 벗어나 성간 공간 쪽으로 날아가고 있다"
    if base == "지구 궤도":
        return "지금 지구 주위를 돌고 있다"
    if base.startswith("대기권 재진입"):
        when = location[location.find("(") + 1:location.find(")")] if "(" in location else ""
        return f"{when}에 대기권으로 재진입해 지금은 궤도에 없다" if when else "대기권으로 재진입해 지금은 궤도에 없다"
    if base.endswith("부근"):
        return f"지금 {base}에 있다"
    if base in ("위치 정보 없음",) or base.startswith(("기준일 상태 미상", "기타")):
        return ""
    return f"지금 위치는 {copula(base)}"


def summary_sentence(item: dict) -> str:
    attrs, group = item.get("attrs", {}), item["group"]
    name, kind = display_name(item["name"]), item.get("kind") or GROUPS[group]
    dist = item.get("distance")
    far = ""
    if dist and dist["reference"] != REF_SURFACE_ALTITUDE:
        far = (f"지구에서 약 {korean_number(dist['ly'])}광년" if dist["ly"] >= 0.1
               else f"지구에서 약 {korean_number(dist['km'])}km")

    if group == "human_made":
        who = attrs.get("국가")
        year = (attrs.get("발사일") or "")[:4]
        head = f"{josa(name, '은는')} "
        head += f"{josa(who, '이가')} " if who else ""
        head += f"{year}년에 발사한 {copula(kind)}." if year else f"{copula(kind)}."
        where = _location_phrase(attrs.get("현재 위치", ""))
        status = attrs.get("운용 상태")
        tail = " ".join(s for s in (
            f"{where}." if where else "",
            f"운용 상태는 {copula(status)}." if status and status != "미상" else "",
        ) if s)
        return f"{head} {tail}".strip()

    if group == "constellation":
        text = f"{josa(name, '은는')} {attrs.get('관측 계절', '')}철 저녁 하늘에서 잘 보이는 별자리다."
        if attrs.get("가장 밝은 별"):
            text += f" 가장 밝은 별은 {copula(attrs['가장 밝은 별'].split(' (')[0])}."
        if attrs.get("황도 별자리"):
            text += " 태양이 지나가는 길인 황도 위의 별자리다."
        return text

    where = f"{attrs['별자리']}에 있는 " if attrs.get("별자리") else ""
    color = f"{attrs['색']} " if attrs.get("색") else ""
    noun = f"{where}{color}{kind}"
    text = f"{josa(name, '은는')} " + (f"{euro(noun)}, {far} 떨어져 있다." if far else f"{copula(noun)}.")
    if attrs.get("맨눈 관측"):
        text += " 맨눈으로 볼 수 있다."
    return text


def _attr_value(value) -> str:
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


# ── 정규화 범주 (조건 탐색 필터용) ────────────────────────────────────────────
# Wikidata의 세부 종류는 "LINER" · "적외선원" · "우주선"처럼 제각각이라, 조건 탐색에서
# "은하" · "성운" · "탐사선" 같은 말로 거를 수 있게 범주 하나로 모은다.

CATEGORIES = ("은하", "성운", "성단", "별", "별자리", "행성", "왜행성", "위성", "소천체",
              "탐사선", "인공위성", "우주망원경", "우주정거장", "기타")
_GALAXY = ("은하", "LINER")
_NEBULA = ("성운", "전리수소영역", "초신성잔해")
_PROBE = ("탐사선", "궤도선", "착륙선", "샘플 리턴")


def _deep_sky_category(text: str) -> str | None:
    if any(k in text for k in _GALAXY):
        return "은하"
    if any(k in text for k in _NEBULA):
        return "성운"
    if "성단" in text:
        return "성단"
    return None


def item_category(item: dict) -> str:
    group, kind, attrs = item["group"], item.get("kind") or "", item.get("attrs", {})
    if group == "messier":      # 종류 → 분류 목록 → 이름 순서로 본다 (예: 보데 은하는 종류가 '적외선원')
        return (_deep_sky_category(kind) or _deep_sky_category(attrs.get("분류", ""))
                or _deep_sky_category(item["name"]) or "기타")
    if group == "star":
        return "별"
    if group == "constellation":
        return "별자리"
    if group == "solar_system":
        if kind == "항성":
            return "별"
        if kind in ("행성", "왜행성", "위성"):
            return kind
        return "소천체"                      # 소행성 · 혜성 · 카이퍼대 천체
    labels = f"{kind} {attrs.get('분류', '')} {item['name']}"     # 분류가 비면 이름도 본다 (국제우주정거장)
    for category in ("우주망원경", "우주정거장"):
        if category in labels:
            return category
    if any(k in labels for k in _PROBE):
        return "탐사선"
    if kind == "우주선":                    # 분류 정보가 없는 항목 — 현재 위치로 판단한다
        where = attrs.get("현재 위치", "")
        return "인공위성" if where.startswith(("지구 궤도", "대기권 재진입")) else "탐사선"
    return "인공위성"


# ── 색인 텍스트 · 메타데이터 ────────────────────────────────────────────────

def build_item_text(item: dict, ref_year: int) -> str:
    group = GROUPS[item["group"]]
    title = item["name"] + (f" ({item['name_en']})" if item.get("name_en") and item["name_en"] != item["name"] else "")
    lines = [f"[{group}] {title}", summary_sentence(item), f"종류: {item.get('kind') or group}"]

    for key, value in item.get("attrs", {}).items():
        if key in HIDDEN_ATTRS or value in (None, ""):
            continue
        if value is False and key not in SHOW_FALSE_ATTRS:
            continue
        lines.append(f"{key}: {_attr_value(value)}")

    dist = item.get("distance")
    if dist:
        lines.append(f"거리: {distance_text(dist)}")
        lines.extend(light_lines(dist, ref_year))

    # 화면 표시용 근삿값에만 쓴 출처는 텍스트 내용의 근거가 아니므로 뺀다
    used = sorted({s["name"] for s in item.get("sources", [])
                   if not s.get("used_for", "").startswith("표시용")})
    if used:
        lines.append(f"데이터 출처: {', '.join(used)}")
    return "\n".join(lines)


def build_item_metadata(item: dict, ref_year: int, text: str) -> dict:
    """검색 필터 · 근거 표시용 메타데이터. Chroma 제약에 맞춰 스칼라 값만 넣는다."""
    attrs = item.get("attrs", {})
    dist = item.get("distance")
    wikidata = next((s["url"] for s in item.get("sources", []) if s["name"] == "Wikidata"), "")
    meta = {
        "item_id": item["id"],
        "source_type": SOURCE_TYPE,
        "group": item["group"],
        "group_ko": GROUPS[item["group"]],
        "name": item["name"],
        "name_en": item.get("name_en") or "",
        "kind": item.get("kind") or "",
        "category": item_category(item),
        "wiki_title": item["wiki_title"],
        "title": f"{item['name']} · {SOURCE_TYPE}",
        "source_url": wikidata,
        "constellation": attrs.get("별자리") or (item["name"] if item["group"] == "constellation" else ""),
        "naked_eye": bool(attrs.get("맨눈 관측", False)),
        "korean": bool(attrs.get("한국 관련", False)),
        "season": attrs.get("관측 계절", ""),
        "ecliptic": bool(attrs.get("황도 별자리", False)),
        "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
    }
    if dist:
        meta["distance_km"] = float(dist["km"])
        meta["distance_ly"] = float(dist["ly"])
        meta["distance_approx"] = bool(dist.get("approximate"))
        meta["distance_reference"] = dist["reference"]
        if dist["reference"] != REF_SURFACE_ALTITUDE and dist["ly"] >= 1:
            meta["light_departure_year"] = departure_year(dist["ly"], ref_year)
    for key in ("ra_deg", "dec_deg"):
        if item.get(key) is not None and math.isfinite(item[key]):
            meta[key] = float(item[key])
    return meta
