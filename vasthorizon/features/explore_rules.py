"""조건 탐색 규칙 해석 — 동의어 표로 질의를 필터로 먼저 바꾼다 (LLM 없음).

    "블랙홀이 발견된 천체"   → has_black_hole=True
    "고리가 있는 행성"       → categories=["행성"], has_rings=True
    "가장 가까운 별"         → categories=["별"], sort_by="distance", order="asc"
    "한국에서 보이는 별자리" → categories=["별자리"], visible_from_korea=True

해석 결과(RuleParse)
- data: 필터 추출 LLM과 같은 모양의 dict (explore.parse_filters가 그대로 검증한다)
- complete: 질의의 모든 낱말을 표로 소비했고 조건이 하나 이상 나왔는가.
  True면 필터 추출 LLM을 부르지 않는다. False면 LLM 결과에 data를 합친다 (LLM이 비운 필드만 채운다).

표가 확신하는 패턴만 처리한다. 애매한 낱말("멋진", "신비로운", "조선 시대")이 남으면 complete=False가 되어 LLM이 해석한다.
"한국"은 뒤에 오는 말로 구분한다: "한국에서 보이는" → 서울 관측, "한국이 쏘아 올린" · "한국의 위성" → 한국 관련.

부정형 ("탐사선이 방문하지 않은 행성", "블랙홀이 없는 은하")
- 부정형 규칙을 긍정형보다 먼저 둔다 (탐사선 방문 · 블랙홀 · 고리 · 맨눈 · 서울 관측 → 값 False).
- 긍정 참거짓 규칙(블랙홀 · 고리 · 탐사선 방문 · 맨눈 · 한국)이 맞은 자리 바로 뒤에 부정어(않 · 없 · 못 · 안 · 아닌)가
  오면 그 규칙을 버리고 맞은 말을 남긴다 — complete=False가 되어 LLM이 해석하고, 틀린 긍정 필터가 data에 섞이지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_WORD = "가-힣A-Za-z0-9"
JOSA = ("에서는", "에서", "까지", "보다", "으로", "에는", "이란", "은", "는", "이", "가", "의", "에", "을", "를",
        "과", "와", "도", "로", "만", "들")
# 조건이 아니어서 소비해도 되는 낱말 (조사가 붙어도 된다)
FILLER = {
    "천체", "것", "곳", "대상", "항목", "목록", "종류", "모든", "전부", "다", "중", "중에서", "가운데",
    "있는", "있어", "있나", "있을까", "있니", "발견된", "발견된다는", "알려진", "가진", "지닌", "확인된",
    "알려줘", "알려", "줘", "주세요", "보여줘", "보여", "찾아줘", "찾아", "뭐야", "뭐가", "뭐", "무엇", "어떤", "어디",
    "목록을", "순", "순서", "순서대로", "순으로", "차례로", "수", "있다", "한", "건", "거", "게",
}
SUPERLATIVE_LIMIT = 5        # "가장 가까운 별" — 1위와 그다음 몇 개를 함께 보여 준다 (태양 다음 별까지 보이게)

# (정규식, 채울 필드) — 위에서부터 차례로 찾고, 이미 소비한 자리는 다시 쓰지 않는다. 긴 패턴을 먼저 둔다.
_RULES: list[tuple[str, dict]] = [
    # 블랙홀 (부정형 먼저)
    (r"블랙\s*홀\s*(?:이|가|은|는)?\s*(?:없는|없어|없을|발견되지\s*않은|있지\s*않은)", {"has_black_hole": False}),
    (r"블랙\s*홀", {"has_black_hole": True}),
    # 고리
    (r"고리\s*(?:가|를|이)?\s*(?:없는|없어|없을|있지\s*않은)", {"has_rings": False}),
    (r"고리", {"has_rings": True}),
    # 탐사선 방문 (탐사선 범주보다 먼저, 부정형 먼저)
    (r"탐사선\s*(?:이|가)?\s*(?:방문|다녀|찾아|도착|착륙|탐사|근접|지나)\S*?(?:\s*적\s*(?:이|은)?)?\s*(?:않은|않았던|못한|없는)",
     {"visited_by_probe": False}),
    (r"탐사선\s*(?:이|가)?\s*(?:(?:안|못)\s*(?:간|가본|가\s*본|다녀간|들른)|가지\s*않은|가\s*보지\s*않은)", {"visited_by_probe": False}),
    (r"(?:방문|탐사)\s*(?:하지|되지|받지)\s*(?:않은|못한)|(?:방문|탐사)\s*(?:한|된|받은)\s*적\s*(?:이|은)?\s*없는",
     {"visited_by_probe": False}),
    (r"탐사선\s*(?:이|가)?\s*(?:방문|다녀|찾아|도착|착륙|탐사|근접|지나)\S*(?:\s*적\s*(?:이|이\s*있는|있는))?",
     {"visited_by_probe": True}),
    (r"(?:방문|탐사)\s*(?:한|된|했던|받은)(?:\s*적\s*(?:이|이\s*있는|있는))?", {"visited_by_probe": True}),
    # 한국 · 서울에서 보이는
    (r"(?:한국|서울|우리나라)\s*(?:하늘)?\s*(?:에서|에선|에서는)\s*(?:안\s*보이는|볼\s*수\s*없는|보이지\s*않는|관측\s*(?:할\s*수\s*없는|불가능한|안\s*되는))",
     {"visible_from_korea": False}),
    (r"(?:한국|서울|우리나라)\s*(?:하늘)?\s*(?:에서|에선|에서는)\s*(?:(?:잘\s*)?보이는|볼\s*수\s*있는|관측\s*(?:할\s*수\s*있는|가능한|되는|된))",
     {"visible_from_korea": True}),
    # 한국 관련
    (r"(?:한국|우리나라)\s*(?:이|가|에서)?\s*(?:쏘아\s*올린|발사한|만든|개발한|보낸)", {"korean": True}),
    (r"(?:한국|우리나라)\s*(?:의|관련|과\s*관련된)", {"korean": True}),
    # 맨눈
    (r"맨\s*눈\s*(?:으로)?\s*(?:는)?\s*(?:안\s*보이는|볼\s*수\s*없는|보이지\s*않는)", {"naked_eye": False}),
    (r"맨\s*눈\s*(?:으로)?\s*(?:도)?\s*(?:(?:잘\s*)?보이는|볼\s*수\s*있는|관측\s*(?:할\s*수\s*있는|가능한|되는))?",
     {"naked_eye": True}),
    # 계절 (별자리에만 있는 속성)
    (r"(봄|여름|가을|겨울)\s*(?:철|밤)?\s*(?:에|의|하늘에)?\s*(?:(?:잘\s*)?보이는|볼\s*수\s*있는|뜨는)?", {"season": 1}),
    # 황도
    (r"황도\s*(?:12\s*)?(?:궁)?", {"ecliptic": True, "categories": ["별자리"]}),
    # 정렬 — 최상급 ("가장 가까운", "제일 먼") · 순서 ("가까운 순")
    (r"(?:가장|제일|젤|최고로)\s*(가까운|먼|밝은|어두운|큰|작은)", {"superlative": 1}),
    (r"(가까운|먼|밝은|어두운|큰|작은)\s*(?:순|순서|차례)\s*(?:으로|대로)?", {"order_word": 1}),
    # 거리 범위 ("100광년 이내", "1000광년보다 먼")
    (r"(\d+(?:\.\d+)?)\s*(만|억)?\s*광년\s*(?:이내|안|안쪽|이하|미만|보다\s*가까운|안에\s*있는)", {"dist_max": 1}),
    (r"(\d+(?:\.\d+)?)\s*(만|억)?\s*광년\s*(?:이상|넘는|초과|보다\s*먼|밖|너머)", {"dist_min": 1}),
    # 개수 ("3개", "다섯 곳")
    (r"(\d+)\s*(?:개|곳|가지|건)", {"limit": 1}),
    # 종류 · 범주 (긴 말 먼저)
    (r"행성상\s*성운", {"categories": ["성운"]}),
    (r"왜\s*행성", {"categories": ["왜행성"]}),
    (r"인공\s*위성", {"categories": ["인공위성"]}),
    (r"우주\s*망원경|망원경", {"categories": ["우주망원경"]}),
    (r"우주\s*정거장", {"categories": ["우주정거장"]}),
    (r"사람이\s*만든\s*(?:것)?|인공\s*천체|우주선", {"categories": ["탐사선", "인공위성", "우주망원경", "우주정거장"]}),
    (r"탐사선", {"categories": ["탐사선"]}),
    (r"별\s*자리", {"categories": ["별자리"]}),
    (r"은하", {"categories": ["은하"]}),
    (r"성운", {"categories": ["성운"]}),
    (r"성단", {"categories": ["성단"]}),
    (r"소행성", {"categories": ["소천체"], "kinds": ["소행성"]}),
    (r"혜성", {"categories": ["소천체"], "kinds": ["혜성"]}),
    (r"소천체", {"categories": ["소천체"]}),
    (r"행성", {"categories": ["행성"]}),
    (r"위성", {"categories": ["위성"]}),
    (r"항성|별", {"categories": ["별"]}),
    (r"태양계", {"group": "solar_system"}),
    (r"메시에", {"group": "messier"}),
]
_COMPILED = [(re.compile(p), fields) for p, fields in _RULES]
# 긍정 참거짓 규칙 — 바로 뒤에 부정어가 오면 버린다 (모듈 설명의 '부정형')
POSITIVE_KEYS = {"has_black_hole", "has_rings", "visited_by_probe", "naked_eye", "visible_from_korea", "korean"}
_NEGATION = re.compile(r"않|없|못")
_NEGATION_WORDS = {"안", "아닌", "아니", "아니라", "아니고"}
_NEGATION_BRIDGE = {"적", "적이", "적은", "적도", "게", "것", "것이", "것은", "건", "거"}   # "방문한 적 없는" · "보이는 게 아닌"

_SORT = {"가까운": ("distance", "asc"), "먼": ("distance", "desc"), "밝은": ("brightness", "asc"),
         "어두운": ("brightness", "desc"), "큰": ("size", "desc"), "작은": ("size", "asc")}
_UNIT = {None: 1, "": 1, "만": 1e4, "억": 1e8}


@dataclass
class RuleParse:
    data: dict = field(default_factory=dict)
    complete: bool = False
    leftover: list[str] = field(default_factory=list)   # 표로 소비하지 못한 낱말


def _strip_josa(word: str) -> str:
    changed = True
    while changed and word:
        changed = False
        for j in JOSA:
            if word.endswith(j) and len(word) > len(j):
                word, changed = word[: -len(j)], True
                break
    return word


def _consumable(word: str) -> bool:
    return word in FILLER or word in JOSA or _strip_josa(word) in FILLER


def _merge(data: dict, fields: dict, m: re.Match) -> None:
    for key, value in fields.items():
        if key == "categories" or key == "kinds":
            data[key] = list(dict.fromkeys([*(data.get(key) or []), *value]))
        elif key == "season":
            data["season"] = m.group(1)
        elif key == "superlative":
            data["sort_by"], data["order"] = _SORT[m.group(1)]
            data.setdefault("limit", SUPERLATIVE_LIMIT)
        elif key == "order_word":
            data["sort_by"], data["order"] = _SORT[m.group(1)]
        elif key in ("dist_max", "dist_min"):
            ly = float(m.group(1)) * _UNIT[m.group(2)]
            data["distance_ly_max" if key == "dist_max" else "distance_ly_min"] = ly
        elif key == "limit":
            data["limit"] = max(1, min(int(m.group(1)), 20))     # explore.MAX_LIMIT
        else:
            data[key] = value


def parse_rules(query: str) -> RuleParse:
    """질의를 표로 해석한다. 이름 질의 · 성군은 explore가 먼저 처리하므로 여기서는 보지 않는다."""
    data: dict = {}
    taken = [False] * len(query)
    conditions = 0
    negated: list[str] = []
    for pattern, fields in _COMPILED:
        for m in pattern.finditer(query):
            a, b = m.span()
            if a == b or any(taken[a:b]):
                continue
            # 낱말 중간에 걸리지 않게 — 앞은 낱말 경계(또는 이미 소비한 자리), 뒤는 경계나 조사만
            # ("은하수" · "별빛" · "구상성단"은 그대로 남아 LLM이 해석한다)
            if a > 0 and re.match(rf"[{_WORD}]", query[a - 1]) and not taken[a - 1]:
                continue
            tail = re.match(rf"[{_WORD}]+", query[b:])
            if tail and not _only_josa(tail.group(0)):
                continue
            if any(fields.get(k) is True for k in POSITIVE_KEYS) and _negated_after(query, b):
                for i in range(a, b):            # 뒤 규칙("탐사선" 범주 등)이 다시 쓰지 않게 자리는 차지하고,
                    taken[i] = True
                negated.append(query[a:b])       # 해석하지 못한 말로 남긴다 → LLM
                continue
            _merge(data, fields, m)
            for i in range(a, b):
                taken[i] = True
            conditions += 1
    rest = "".join(" " if t else ch for ch, t in zip(query, taken))
    leftover = negated + [w for w in re.findall(rf"[{_WORD}]+", rest) if not _consumable(w)]
    # 계절은 별자리에만 있는 속성 — 다른 범주와 함께 나오면 LLM에 맡긴다
    if data.get("season") and set(data.get("categories") or ["별자리"]) != {"별자리"}:
        leftover.append(data["season"])
    if data.get("season") and not data.get("categories"):
        data["categories"] = ["별자리"]
    if data.get("limit") and not data.get("sort_by"):
        data.pop("limit")                 # "3개"만으로는 순서를 정할 수 없다
    meaningful = {k for k in data if k not in ("limit",)}
    return RuleParse(data=data, complete=bool(meaningful) and conditions > 0 and not leftover, leftover=leftover)


def _negated_after(query: str, end: int) -> bool:
    """규칙이 맞은 자리 바로 뒤가 부정인가 — 붙은 조사 다음 첫 낱말을 본다.
    "~지"("있지" · "하지")로 끝나거나 "적" · "게" 같은 이음말이면 다음 낱말까지 ("고리가 있지 않은", "방문한 적 없는")."""
    rest = query[end:]
    attached = re.match(rf"[{_WORD}]*", rest).group(0)             # 붙은 조사 ("블랙홀이"의 "이")
    words = [attached] if attached else []
    for word in re.findall(rf"[{_WORD}]+", rest[len(attached):])[:3]:
        words.append(word)
        if not (word.endswith("지") or word in _NEGATION_BRIDGE):
            break
    return any(_NEGATION.search(w) or w in _NEGATION_WORDS for w in words)


def _only_josa(word: str) -> bool:
    """조사만으로 이루어진 낱말인가 ("이", "에서는", "들은")."""
    while word:
        j = next((j for j in sorted(JOSA, key=len, reverse=True) if word.startswith(j)), None)
        if j is None:
            return False
        word = word[len(j):]
    return True
