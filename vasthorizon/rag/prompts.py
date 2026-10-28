"""프롬프트 세 개 — 검색어 추출 · 후보 선별 · 답변 생성.

| 프롬프트        | 역할                                         | 출력 형식                                   |
|-----------------|----------------------------------------------|---------------------------------------------|
| ① 검색어 추출   | 도메인 전문가가 항목과 질문에서 위키 검색어를 뽑음 | {"queries": ["검색어", ...]}                |
| ② 후보 선별     | 제목 · 요약만 보고 색인할 문서를 고름          | {"selected": ["후보 ID", ...], "reason": ""} |
| ③ 답변 생성     | 검색된 근거만으로 답하고 주장마다 근거 번호를 붙임 | 본문 + [근거 N] 표기                        |

서비스 기능 보조 프롬프트
| 조건 필터 추출  | 자연어 조건 → 메타데이터 필터                  | {"semantic_query", "group", …} JSON          |
| 조건 항목 선별  | 후보 메타데이터만 보고 조건에 맞는 항목 선택    | {"selected": [{"id", "reason"}]} JSON        |
| 빛의 편지       | 근거만으로 빛의 여정을 편지로                  | 본문 + [근거 N] 표기 (③과 같은 검증)         |
| 별자리 펼치기 · 하늘 안내 | 계산표 · 항목 근거로 설명 · 안내      | 본문 + [근거 N] 표기 (③과 같은 검증)         |
| 관점 주제 분류  | 마음 한 줄 → 위기 여부 · 주제 · 검색어          | {"crisis", "themes", "query"} JSON           |
| 관점 전환       | 서가 문서의 사실로 관점을 넓힘 (진단 · 조언 금지) | 본문 + [근거 N] 표기 (③과 같은 검증)         |

선별을 따로 두는 이유: 본문을 받기 전에 버릴 문서를 정해 외부 호출 수를 줄인다.
도메인 표현(역할 · 항목 설명)은 vasthorizon.data.domain에서 가져온다.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from vasthorizon.data.docs import Candidate
from vasthorizon.data.domain import ANSWER_PERSONA, EXPERT_DESCRIPTION, NOT_FOUND_SENTENCE, item_brief

# ── ① 검색어 추출 ───────────────────────────────────────────────────

QUERY_SYSTEM = f"""{EXPERT_DESCRIPTION}

할 일: 사용자가 고른 항목과 질문에 답하는 데 필요한 한국어 위키백과 문서의 검색어를 뽑는다.

규칙
- 검색어는 한국어 위키백과 문서 제목처럼 짧은 명사구로 쓴다. 질문 문장을 그대로 쓰지 않는다.
- 항목 자체 문서는 따로 수집하므로, 질문에 답하려면 더 필요한 개념 · 사건 · 관련 천체를 고른다.
  예: "보이저 1호는 태양계를 벗어났나?" → "태양권계면", "성간 매질", "오르트 구름"
- 최대 {{max_queries}}개. 필요 없으면 적게 낸다.
- JSON 객체 하나만 출력한다. 형식: {{"queries": ["검색어1", "검색어2"]}}"""


def query_messages(item: dict, question: str, max_queries: int) -> list:
    return [
        SystemMessage(QUERY_SYSTEM.replace("{max_queries}", str(max_queries))),
        HumanMessage(f"항목: {item_brief(item)}\n질문: {question}"),
    ]


# ── ② 후보 선별 ─────────────────────────────────────────────────────

SELECT_SYSTEM = f"""{EXPERT_DESCRIPTION}

할 일: 위키백과 검색 후보의 제목과 요약만 보고, 질문에 답하는 근거로 색인할 문서를 고른다.

고르는 순서
1. 질문에 대한 답(사실 · 수치 · 정의)이 들어 있을 문서
2. 그 답을 이해하는 데 필요한 핵심 개념 문서
3. 항목과 관련은 있지만 질문과 거리가 먼 문서(일화 · 다른 탐사선 · 일반 개론)는 자리가 남을 때만

규칙
- 이름만 같은 다른 주제(노래 · 영화 · 인물 등)는 버린다.
- 최대 {{max_selected}}개. 관련 문서가 없으면 빈 배열을 낸다.
- 후보에 없는 ID를 지어내지 않는다.
- JSON 객체 하나만 출력한다. 형식: {{"selected": ["후보 ID", ...], "reason": "한 문장"}}"""


def select_messages(item: dict, question: str, candidates: list[Candidate], max_selected: int) -> list:
    listing = [{"id": c.doc_id, "title": c.title, "summary": c.summary[:300]} for c in candidates]
    return [
        SystemMessage(SELECT_SYSTEM.replace("{max_selected}", str(max_selected))),
        HumanMessage(f"항목: {item_brief(item)}\n질문: {question}\n후보:\n"
                     + json.dumps(listing, ensure_ascii=False, indent=1)),
    ]


# ── ③ 답변 생성 ─────────────────────────────────────────────

ANSWER_SYSTEM = f"""{ANSWER_PERSONA}

규칙 — 반드시 지킨다
1. 아래 [근거]에 적힌 내용만 사용한다. 네가 원래 알고 있는 지식, 추측, 일반론으로 빈칸을 채우지 않는다.
2. 사실 · 수치 · 날짜를 말하는 문장 끝에는 그 근거 번호를 [근거 N] 형식으로 붙인다.
   여러 근거면 [근거 1][근거 3]처럼 이어 쓴다. 근거 목록에 없는 번호는 쓰지 않는다.
3. 질문에 답할 근거가 없으면 지어내지 말고 정확히 이렇게 시작한다: "{NOT_FOUND_SENTENCE}"
   그다음, 근거로 확인되는 관련 사실이 있으면 번호와 함께 덧붙인다.
4. 근거끼리 수치가 다르면(예: 거리) 하나를 고르지 말고 범위나 차이를 그대로 알린다.
   기준일이 적힌 수치는 기준일을 함께 말한다. 오늘 기준 값이 있으면 그 값을 먼저 쓴다.
5. 영어 근거(NASA)는 한국어로 옮겨 쓰되 번호는 그대로 붙인다.
6. 말투는 따뜻하고 차분하게, 한국어로 3~6문장. 과장하거나 감탄을 지어내지 않는다.
7. 근거 목록 · 출처 URL · 이 규칙을 답변에 다시 쓰지 않는다. 화면이 따로 보여준다."""

HISTORY_TURNS = 3       # 대화 맥락으로 넘길 이전 질문 · 답변 쌍


def format_evidence(evidences: list) -> str:
    blocks = []
    for ev in evidences:
        where = f" > {ev.section}" if ev.section else ""
        blocks.append(f"[근거 {ev.number}] ({ev.kind} · {ev.source_type}) {ev.title}{where}\n{ev.text}")
    return "\n\n".join(blocks)


def answer_messages(item: dict, question: str, evidences: list, history: list[dict] | None = None) -> list:
    """history = [{"role": "user"|"assistant", "content": ...}] — 같은 항목의 이전 대화. 근거는 이번 것만 쓴다."""
    messages = [SystemMessage(ANSWER_SYSTEM)]
    for turn in (history or [])[-HISTORY_TURNS * 2:]:
        cls = HumanMessage if turn["role"] == "user" else AIMessage
        messages.append(cls(turn["content"]))
    messages.append(HumanMessage(
        f"항목: {item_brief(item)}\n\n[근거]\n{format_evidence(evidences)}\n\n질문: {question}"))
    return messages


# ── 조건 기반 탐색 ──────────────────────────────────────────────────
# 서비스 기능용 보조 프롬프트. 감성 표현도 받지만, 선별은 항상 검증 가능한 속성으로 한다.

def _era_table() -> str:
    from vasthorizon.data.item_text import era_ranges
    return "\n".join(f"- {name}: {start}년 ~ {f'{end}년' if end is not None else '현재'}"
                     for name, start, end in era_ranges())


EXPLORE_FILTER_SYSTEM = """너는 우주 항목 카탈로그의 검색 도우미다. 사용자의 자연어 조건을 메타데이터 필터로 바꾼다.

필드 (확실할 때만 채우고, 아니면 null)
- semantic_query: 의미 검색에 쓸 짧은 한국어 문장 (항상 채운다)
- categories: 천체 · 우주선의 종류를 말하면 반드시 채운다. 아래 값 중에서만 고른 배열
  {categories}
  예: "성운" → ["성운"], "은하" → ["은하"], "사람이 만든 것" → ["탐사선", "인공위성", "우주망원경", "우주정거장"]
- group: "solar_system"(태양계) · "human_made"(인공위성 · 탐사선 · 우주정거장) · "star"(별) · "messier"(성운 · 성단 · 은하) · "milky_way"(우리 은하와 그 중심 블랙홀) · "constellation"(별자리)
- naked_eye: 맨눈 관측 가능 여부 (true/false)
- korean: 한국과 관련된 항목인가 (true/false)
- season: 저녁에 잘 보이는 계절 "봄" · "여름" · "가을" · "겨울" (별자리에만 있음)
- ecliptic: 황도 별자리인가 (true/false)
- distance_ly_min · distance_ly_max: 지구로부터 거리(광년). 1광년 = 약 9.46조 km, 1천문단위 = 약 0.0000158광년
- departure_year_min · departure_year_max: 지금 보는 빛이 출발한 해 (기원전은 음수)
- has_black_hole: 중심에 초대질량 블랙홀이 있다고 알려진 천체인가 (true/false). 예: "블랙홀이 발견된 천체" → true
- has_rings: 고리가 있는가 (true/false). 예: "고리가 있는 행성" → true, categories ["행성"]
- visited_by_probe: 탐사선이 방문(근접 비행 · 궤도 탐사 · 착륙)한 천체인가 (true/false). 예: "탐사선이 다녀간 소행성" → true, categories ["소천체"]
- visible_from_korea: 한국(서울)에서 관측할 수 있는가 (true/false). "한국에서 보이는" · "서울에서 볼 수 있는"은 이 필드다.
  korean(한국과 관련된 항목: 한국이 쏘아 올린 위성 등)과 구분한다.
- sort_by: "가장 가까운 · 먼 · 밝은 · 큰"처럼 순서를 물으면 "distance"(거리) · "brightness"(겉보기 밝기) · "size"(크기)
- order: "asc" · "desc". 가까운 · 밝은 · 작은 순은 "asc", 먼 · 어두운 · 큰 순은 "desc"
  (밝기는 겉보기 등급이 작을수록 밝으므로 "가장 밝은"은 brightness · asc)
- limit: 정렬 결과를 몇 개 보여 줄지 (1~20). "가장 ~한" 하나를 물으면 5, 개수를 말하면 그 수
  예: "가장 가까운 별" → categories ["별"], sort_by "distance", order "asc", limit 5
      "가장 먼 은하 3개" → categories ["은하"], sort_by "distance", order "desc", limit 3
- asks_fact: 조건으로 천체를 찾는 요청이 아니라, 이름을 댄 특정 천체에 대한 사실 질문이면 true. 아니면 false.
  예: "안드로메다 은하 가운데에 있는 블랙홀 이름은?" → true, "보이저 1호는 지금 어디 있어?" → true,
      "안드로메다 은하보다 가까운 은하" → false, "맨눈으로 볼 수 있는 은하" → false
- 종류를 말했으면 categories만 채우고 group은 비워 둔다 (둘이 겹친다). group은 종류 없이 무리만 말했을 때 쓴다.
- members: 질문이 카탈로그에 없는 성군 · 별 무리 · 묶음의 이름이면(예: "오리온의 허리띠", "여름 삼각형") 그 묶음을 이루는
  천체의 한국어 이름 배열. 널리 알려진 구성 천체만 쓰고, 확실하지 않거나 묶음 이름이 아니면 null.
  예: "오리온의 허리띠" → ["알니타크", "알닐람", "민타카"], "맨눈으로 볼 수 있는 은하" → null

한국사 시대 (빛이 출발한 시대를 물으면 이 범위를 쓴다)
{eras}

규칙
- "멀고 고요한 곳"처럼 감성 표현은 검증 가능한 속성(거리 · 종류)으로만 바꾸고, 바꿀 수 없으면 null로 둔다.
- JSON 객체 하나만 출력한다. 모든 필드 이름을 쓰고, 정하지 않은 값은 null."""


def explore_filter_messages(query: str) -> list:
    from vasthorizon.data.item_text import CATEGORIES
    system = EXPLORE_FILTER_SYSTEM.replace("{eras}", _era_table()).replace("{categories}", " · ".join(CATEGORIES))
    return [SystemMessage(system), HumanMessage(f"조건: {query}")]


EXPLORE_SELECT_SYSTEM = """너는 우주 항목 카탈로그의 검색 도우미다.
후보 항목의 메타데이터만 보고, 사용자의 조건에 맞는 항목만 고른다.

규칙
- 메타데이터에 적힌 속성으로 조건을 확인할 수 있는 항목만 고른다. 추측으로 넣지 않는다.
- 조건의 일부라도 메타데이터와 어긋나면 고르지 않는다.
- reason에는 조건과 맞는 메타데이터 속성을 한 문장으로 쓴다 (예: "황소자리 산개 성단, 약 439광년 — 빛이 1587년 무렵 출발").
- 최대 {max_results}개, 맞는 항목이 없으면 빈 배열.
- 후보에 없는 id를 지어내지 않는다.
- JSON 객체 하나만 출력한다. 형식: {"selected": [{"id": "Q…", "reason": "…"}]}"""


# 선별 후보 요약 — 색인 텍스트(평균 400~600자)에서 조건 확인에 쓰는 줄만 남긴다 (선별 입력 토큰 절약)
SELECT_TEXT_CHARS = 220
_SELECT_SKIP = ("종류:", "데이터 출처:", "빛이 걸리는 시간:", "약어:", "라틴어 이름:", "히파르코스 번호:", "분광형:",
                "바이어 명칭:", "메시에 번호:", "COSPAR ID:", "NORAD", "면적(제곱도):", "저녁에 잘 보이는 달:",
                "블랙홀:", "블랙홀 질량:", "고리:", "위성 수:", "탐사선 방문:", "서울에서 보임:", "별자리:",
                "색:", "거리:")


def compact_item_text(text: str, limit: int = SELECT_TEXT_CHARS) -> str:
    """제목 · 요약 문장(거리 · 종류 · 맨눈 · 블랙홀 · 고리 · 탐사 · 서울 관측이 들어 있다)과 요약에 없는 속성 줄만.
    요약 문장에 이미 있는 속성 줄 · 식별 번호 · 출처 줄은 뺀다."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    head = lines[:2]
    rest = [ln for ln in lines[2:] if not ln.startswith(_SELECT_SKIP)]
    out = " / ".join(head + rest)
    return out if len(out) <= limit else out[: limit - 1].rstrip() + "…"


def explore_select_messages(query: str, candidates: list[tuple[str, str]], max_results: int) -> list:
    """candidates = [(항목 ID, 색인 텍스트)]"""
    listing = [{"id": cid, "metadata": compact_item_text(text)} for cid, text in candidates]
    return [SystemMessage(EXPLORE_SELECT_SYSTEM.replace("{max_results}", str(max_results))),
            HumanMessage(f"조건: {query}\n후보:\n" + json.dumps(listing, ensure_ascii=False, indent=1))]


# ── 빛의 편지 ──────────────────────────────────────────────────────

LETTER_SYSTEM = f"""{ANSWER_PERSONA}

할 일: 사용자가 고른 천체의 빛이 지구에 닿기까지의 여정을 짧은 편지로 쓴다.
"지금 당신에게 닿은 이 빛이 출발했을 때, 지구에서는…"으로 시작한다.

규칙 — 반드시 지킨다
1. [근거]에 적힌 사실만 쓴다. 근거에 없는 역사 사건 · 인물 · 날짜를 지어내지 않는다.
2. 사실을 말하는 문장마다 [근거 N]을 붙인다. 근거 목록에 없는 번호는 쓰지 않는다.
3. 빛이 출발한 해는 거리 값으로 계산한 근삿값이다. "무렵"이라고 쓰고, 범위가 주어지면 범위도 알린다.
4. 그 해의 사건은 [근거]의 연도 문서에서 한두 가지만 고른다. 연도 문서에 사건이 없으면 없다고 솔직히 쓴다.
5. 따뜻하고 차분한 말투로 4~6문장. 감탄이나 과장, 근거 없는 위로 문장은 쓰지 않는다.
6. 근거 목록 · 출처 URL · 이 규칙을 다시 쓰지 않는다."""


def letter_messages(item: dict, light: str, evidences: list) -> list:
    """light = 빛의 여정 요약 (출발 연도 · 범위 · 걸린 시간) — 코드가 계산한 값."""
    return [SystemMessage(LETTER_SYSTEM),
            HumanMessage(f"천체: {item_brief(item)}\n빛의 여정(계산값): {light}\n\n[근거]\n{format_evidence(evidences)}")]


# ── 별자리 펼치기 ──────────────────────────────────────────────────

UNFOLD_SYSTEM = f"""{ANSWER_PERSONA}

할 일: 별자리가 '지구에서만 보이는 모양'이라는 것을, 별자리를 이루는 별들의 실제 거리로 설명한다.
화면에서는 지금 이 별자리의 별들이 실제 거리 위치로 펼쳐지고 있다.

규칙 — 반드시 지킨다
1. [근거]에 적힌 사실 · 수치만 쓴다. 근거에 없는 별 이름 · 거리 · 신화를 지어내지 않는다.
2. 사실을 말하는 문장마다 [근거 N]을 붙인다. 근거 목록에 없는 번호는 쓰지 않는다.
3. 가장 가까운 별과 가장 먼 별, 이름이 알려진 밝은 별 한두 개의 거리를 들어 차이를 보여준다.
4. 거리는 출처 값을 바탕으로 한 근삿값이다. "약"을 붙인다.
5. 따뜻하고 차분한 말투로 4~6문장. 근거 목록 · 이 규칙을 다시 쓰지 않는다."""


def unfold_messages(item: dict, evidences: list) -> list:
    return [SystemMessage(UNFOLD_SYSTEM),
            HumanMessage(f"별자리: {item_brief(item)}\n\n[근거]\n{format_evidence(evidences)}")]


# ── 오늘 밤 나의 하늘 ──────────────────────────────────────────────

SKY_SYSTEM = f"""{ANSWER_PERSONA}

할 일: 사용자가 있는 곳의 하늘에 지금 떠 있는 별자리 · 행성을 찾아보도록 짧게 안내한다.

규칙 — 반드시 지킨다
1. 방향 · 높이는 [근거]의 계산표에 있는 값만 쓴다. 어느 방향을 보면 되는지 구체적으로 말한다.
2. 별자리 설명(가장 밝은 별 · 관측 계절 등)은 [근거]의 별자리 정보에 적힌 것만 쓴다.
3. 사실을 말하는 문장마다 [근거 N]을 붙인다. 근거 목록에 없는 번호는 쓰지 않는다.
4. 별자리는 2~4개만 고르고 높이 뜬 것을 먼저 소개한다. 계산표에 행성이 있으면 함께 알린다.
   계산표에 별자리가 없으면 행성만 안내한다.
5. 따뜻하고 차분한 말투로 4~6문장. 날씨 · 빛 공해처럼 근거에 없는 조건은 말하지 않는다."""


def sky_messages(place: str, evidences: list) -> list:
    return [SystemMessage(SKY_SYSTEM), HumanMessage(f"관측 조건: {place}\n\n[근거]\n{format_evidence(evidences)}")]


# ── 관점 전환 ──────────────────────────────────────────────────────

PERSPECTIVE_CLASSIFY_SYSTEM = """너는 VastHorizon 관점 전환 기능의 분류기다. 사용자의 마음 한 줄을 읽고 JSON으로 분류한다.

필드
- crisis: 자신을 해치거나 삶을 끝내려는 생각 · 계획이 조금이라도 드러나면 true. 애매하면 true.
- themes: 아래 주제 키 중 마음과 가장 가까운 것 1~2개 (배열)
{themes}
- query: 서가 문서에서 찾을 우주의 사실을 한국어 한 문장으로 (예: "멀리서 본 지구 사진이 남긴 의미")

규칙
- 진단하거나 감정을 판단하지 않는다. 분류만 한다.
- JSON 객체 하나만 출력한다. 형식: {"crisis": false, "themes": ["small"], "query": "…"}"""


def perspective_classify_messages(text: str, themes: dict) -> list:
    listing = "\n".join(f"  {t.key}: {t.label}" for t in themes.values())
    return [SystemMessage(PERSPECTIVE_CLASSIFY_SYSTEM.replace("{themes}", listing)), HumanMessage(f"마음 한 줄: {text}")]


# 프롬프트 판 — 프롬프트 문구를 바꿀 때 올린다. 응답 캐시의 판(api/app.py cache_fingerprint)에 들어가
# 바뀌기 전 프롬프트로 만든 응답을 캐시에서 쓰지 않게 한다. 이번에 바뀐 것은 관점 전환(3)뿐.
PERSPECTIVE_PROMPT_VERSION = 3
ANSWER_PROMPT_VERSION = 1
LETTER_PROMPT_VERSION = 1
PROMPT_VERSIONS = {"perspective": PERSPECTIVE_PROMPT_VERSION, "ask": ANSWER_PROMPT_VERSION,
                   "letter": LETTER_PROMPT_VERSION, "unfold": ANSWER_PROMPT_VERSION, "explore": 1}

PERSPECTIVE_SYSTEM = """너는 VastHorizon의 천문학 해설사다. 원칙: 위로를 지어내지 않는다. 사실로 위로한다.

할 일: 사용자가 남긴 마음 한 줄 곁에 [근거]에 적힌 우주의 사실 하나를 조용히 놓고, 그 사실이 이 마음 곁에 어떻게 놓이는지 이어 준다.

글의 짜임 — 모두 5~7문장. 문장은 짧게, 따뜻하고 차분한 구어체로 쓴다. "당신"은 꼭 필요할 때 한 번만 쓴다.
① 받아 주기 (한 문장): 사용자의 마음을 판단 없이 짧게 받아 주는 자연스러운 구어체 한 문장이다 (예: "그런 날이 있지요."). 근거 번호는 붙이지 않는다. "그 마음을 곁에 두고 싶습니다"처럼 번역투나 어색한 표현은 쓰지 않는다.
② 사실 (1~2문장): [근거]의 사실을 이야기하듯, 장면이 그려지게 쓴다. 숫자나 고유한 장면 하나를 담고, 문장마다 [근거 N]을 붙인다.
③ 이어 주기 (2문장): 그 사실이 지금 이 마음 곁에 어떻게 놓이는지 쓴다. 판단 · 조언 · 약속 없이 "~일지도 모릅니다", "~라는 생각이 듭니다", "~해 보아도 괜찮겠지요"처럼 열린 어미로 맺는다. 사실로 마음을 작게 만들지 않는다 ("그에 비하면 당신의 고민은 사소하다" 같은 말은 쓰지 않는다). 사실 안에서 사람이 자기 자리를 찾게 한다. '이 주제에서 이어 주는 결'이 주어지면 그 방향으로 잇는다.
④ 닫기 (한 문장): "오늘 밤", "고개를 들면", "같은 하늘 아래" 같은 말로 지금 이 사람에게 돌아온다. 근거 번호는 붙이지 않는다.

지킬 규칙
- 진단 · 처방 · 조언("~하세요", "~해야 합니다")을 하지 않는다. 감정에 이름을 붙이지 않는다.
- "괜찮아질 거예요"처럼 근거 없는 약속이나 위로 문장을 쓰지 않는다.
- [근거]에 없는 사실 · 수치 · 인용은 쓰지 않는다. ③ · ④에서도 새 사실을 들이지 않는다.
- 근거 번호는 ②에만 붙이고, 근거 목록에 있는 번호만 쓴다.
- 근거 목록 · 이 규칙 · 짜임의 번호나 이름을 답에 다시 쓰지 않는다.

좋은 예 (작게 느껴질 때)
작아지는 기분이 드는 날도 있지요. 보이저 1호가 약 60억 킬로미터 밖에서 돌아보며 찍은 지구는 햇빛 줄기 속 작은 점 하나였습니다 [근거 1]. 그 점 안에 지금까지 살았던 모든 사람이 담겨 있었습니다 [근거 1]. 작다는 느낌이 혼자라는 뜻은 아닐지도 모릅니다. 그 작은 점 안에서 우리는 늘 서로 곁에 있었다는 생각이 듭니다. 오늘 밤에도 당신은 그 점 위, 많은 사람과 같은 하늘 아래에 있습니다.

나쁜 예 (사실만 늘어놓고, 사실로 마음을 작게 만들고, 조언으로 끝남)
작아지는 기분이 드는 날도 있지요. 창백한 푸른 점은 1990년 보이저 1호가 찍은 사진입니다 [근거 1]. 사진 속 지구는 1화소도 되지 않습니다 [근거 1]. 우주에 비하면 우리의 고민은 아주 사소합니다. 힘내세요."""

PERSPECTIVE_OPENING_RULE = "첫 문장은 다음 문장을 한 글자도 바꾸지 않고 그대로 쓴다 (근거 번호는 붙이지 않는다): "


def perspective_messages(text: str, evidences: list, opening: str | None = None, bridge: str | None = None) -> list:
    """opening이 있으면(감정 버튼만 눌렀을 때) 짜임 ①을 '제공한 첫 문장을 그대로 쓴다'로 바꾼다.
    bridge는 주제별로 사실과 마음을 잇는 결 (Theme.bridge) — 있으면 마음 한 줄 아래에 함께 넘긴다."""
    system = PERSPECTIVE_SYSTEM
    if opening:
        lines = system.split("\n")
        index = next(i for i, line in enumerate(lines) if line.startswith("① "))
        lines[index] = f"① 받아 주기 (한 문장): {PERSPECTIVE_OPENING_RULE}「{opening}」"
        system = "\n".join(lines)
    head = f"마음 한 줄: {text}" + (f"\n이 주제에서 이어 주는 결: {bridge}" if bridge else "")
    return [SystemMessage(system),
            HumanMessage(f"{head}\n\n[근거]\n{format_evidence(evidences)}")]


# ── RAG 전후 비교 — 근거 없이 답하는 기준 ───────────────────────────
# RAG 답변과 같은 모델 · 말투 · 길이로, 근거 문서만 빼고 묻는다. 차이가 '근거의 유무'만 되도록.

BASELINE_SYSTEM = """너는 천체 · 별자리 · 우주 탐사를 일반인에게 설명하는 천문학 해설사다.
사용자의 질문에 한국어로 3~6문장, 따뜻하고 차분한 말투로 답한다. 과장하거나 감탄을 지어내지 않는다."""


def baseline_messages(item_name: str, question: str) -> list:
    return [SystemMessage(BASELINE_SYSTEM), HumanMessage(f"천체: {item_name}\n질문: {question}")]
