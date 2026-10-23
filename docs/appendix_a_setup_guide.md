# 부록 A. 설치, 실행 안내

VastHorizon을 직접 실행해 보려는 분을 위한 안내입니다.
프로젝트 수행 결과는 [README](../README.md)에서 확인하세요.
개인 Claude API 키로 공개 배포하는 방법은 [부록 B. 배포 안내](appendix_b_deploy_guide.md)에 따로 정리했습니다.

> 이 문서는 구현이 진행되는 대로 단계별로 채워집니다.

---

## 1. 준비물

| 항목 | 버전, 내용 |
|---|---|
| Python | **3.11 이상 필수** (설정 모듈이 3.11부터 제공되는 표준 라이브러리 `tomllib`를 씁니다). 3.12.10, 3.11에서 검증했습니다 |
| SSAFY GMS 키 | https://gms.ssafy.io/web/ 에서 발급 |
| 연락처 이메일 | 위키백과, Wikidata User-Agent용 |

---

## 2. 설치

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows (Git Bash)
# source .venv/bin/activate        # macOS / Linux
pip install -r requirements.txt
```

---

## 3. 환경변수

`.env.example`을 복사해 `.env`를 만들고 값을 채우세요.

```
GMS_KEY=발급받은_키
WIKI_CONTACT=your-email@example.com
```

| 변수 | 필수 | 설명 |
|---|:---:|---|
| `GMS_KEY` | ✅ | GMS 키. 코드에 직접 적지 마세요 |
| `WIKI_CONTACT` | ✅ | 외부 API User-Agent 연락처 |
| `VH_CONFIG` | | 다른 설정 파일 경로 (비교 실험용) |

> `.env`는 `.gitignore`에 등록되어 있습니다. 실수로 키를 커밋했다면 그 키는 폐기하고 새로 발급받으세요.

---

## 4. 환경 점검

```bash
python -m scripts.check_env          # 설정, 외부 API 연결 확인 (토큰 사용 없음)
python -m scripts.check_env --llm    # GMS 채팅, 임베딩까지 1회 호출
```

출력 예:

```
[ OK ] 설정 파일: config.toml
[ OK ] GMS_KEY 설정됨
[ OK ] 연락처 설정됨
[ OK ] 한국어 위키백과
[ OK ] Wikidata
[ OK ] JPL Horizons
[ OK ] CelesTrak SATCAT
```

---

## 5. 항목 메타데이터 수집

```bash
python -m scripts.collect_items                     # data/raw 캐시가 있으면 재사용
python -m scripts.collect_items --refresh           # 외부 출처에서 다시 받기
python -m scripts.collect_items --epoch 2026-10-21  # Horizons 위치 기준일 지정
```

| 동작 | 설명 |
|---|---|
| 결과 | `data/items.json` (커밋 대상) |
| 원본 캐시 | `data/raw/`: 파일마다 `*.meta.json`에 수집 시각 기록 (커밋 제외) |
| 저장 조건 | 최소 100건, 5개 그룹, QID 중복 없음, 좌표, 거리, 출처 검증 통과 |
| 실패 시 | 종료 코드 1, 기존 `data/items.json`은 그대로 유지 |

### 별자리 모양 데이터

별자리 펼치기, 하늘 안내, 3D 화면에서 쓰는 별자리 선과 별들의 카탈로그 거리 데이터입니다. 카탈로그를 만든 다음에 실행하세요.

```bash
python -m scripts.collect_constellations            # data/raw 캐시가 있으면 재사용
python -m scripts.collect_constellations --refresh
```

| 동작 | 설명 |
|---|---|
| 결과 | `data/constellations.json` (커밋 대상): 별자리 88개, 선을 이루는 별 756개 (중복 제외) |
| 맨눈 별 | `data/sky_stars.json`: 6등급까지 5,044개 [적경, 적위, 등급, 색지수]. 서버 API(`/api/constellations`)용이고, 3D 화면은 아래 하늘 데이터를 씁니다 |
| 별 연결 | d3-celestial 별자리 선의 꼭짓점 → 0.02도 안의 별 → 히파르코스 번호 |
| 거리 | Wikidata 거리 값을 연주시차로 교차 검증. 연주시차 5mas 이상(약 650광년 안)인 별만 적용, 예외는 [03 §3 별 거리 정책](03_rag_pipeline_design.md#별-거리-정책) |
| 없을 때 | 서버는 그대로 동작합니다. 상태 점검에는 `figures_missing` 안내가 나오고, 펼치기는 `422 figure_unavailable`을 돌려줍니다 |

### 하늘 데이터 (실제 별, 성운, 은하수)

하늘 화면과 내 세상 화면의 모든 점은 실제 천체입니다. d3-celestial 자료를 웹용 작은 파일로 바꿔 `web/data/`에 둡니다(커밋 대상).

```bash
python -m scripts.build_sky_data             # data/raw 캐시가 있으면 재사용
python -m scripts.build_sky_data --refresh   # 출처에서 다시 받기
```

| 파일 | 내용 | 크기 | 내려받는 때 |
|---|---|---:|---|
| `stars_bright.bin` | 히파르코스 별 8등급까지 41,411개 | 485KB | 처음 |
| `stars_faint.bin` | 그보다 어두운 별 76,805개 (13.8등급까지) | 900KB | 확대해 한계 등급이 7.6을 넘을 때 |
| `dsos.json` | 성운, 성단, 은하 15,809개 (메시에 104개는 메시에 번호와 연결) | 776KB | 처음 |
| `milkyway.bin` | 은하수 밝기 지도 (0.5도 격자, 윤곽 5단계) | 253KB | 처음 |
| `sky_meta.json` | 건수와 출처, 이용 조건 | 1KB | |

- 별 파일 형식과 은하수 계산 방법은 `vasthorizon/data/sky_catalog.py` 첫머리에 적어 두었습니다.
- 화각에 따라 보이는 한계 등급이 바뀝니다. 75도에서 6등급, 30도에서 8등급, 5도에서 12등급 안팎입니다.
- 성운, 성단, 은하는 등급이 알려진 것만 한계 등급에 맞춰 보입니다. 출처에 기울기(위치각)가 없어서 장축 지름의 원 안에 종류별 모습(은하는 밝은 핵과 옅은 원반, 성단은 별 알갱이, 성운은 수소와 산소 빛, 행성상 성운은 고리)으로 그립니다. 허블 사진이 있는 메시에 천체는 사진이 나타날 만큼 확대하면 그림 대신 사진만 보입니다.
- 암흑 성운의 숫자(1~6)는 밝기가 아니라 불투명도 등급이라 등급으로 쓰지 않습니다.

### 태양, 달, 행성과 사진, 3D 모델

```bash
python -m scripts.build_messier_images   # 메시에 천체 사진과 출처 표기 (이미 받은 사진은 건너뜀)
python -m scripts.build_blackholes       # 은하 중심 블랙홀 목록과 근거 (web/data/blackholes.json)
```

| 내용 | 파일, 방법 | 비고 |
|---|---|---|
| 태양, 달, 행성의 위치 | `web/js/ephemeris.js`: JPL 근사 궤도 요소(행성), 천문 연감 저정밀 식(달) | JPL Horizons 값과 대조해 행성 0.2~5분각, 달 약 2분각, 태양 0.02도 안. 좌표는 별 데이터와 같은 J2000 |
| 달 표면 | `web/data/textures/moon_lroc_1k.jpg` (NASA SVS CGI Moon Kit, 139KB) | 실제 태양 방향의 빛으로 비추므로 위상이 저절로 맞습니다 |
| 행성 표면 | 셰이더로 그린 모습 (목성 띠와 대적점, 토성 A, B, C 고리와 카시니, 엥케 간극, 고리와 행성의 그림자, 화성 극관, 금성 구름, 수성 크레이터, 태양 쌀알 무늬) | 사진이 아니라 실제 모습을 단순화한 그림입니다 |
| 은하 중심 블랙홀 | `web/data/blackholes.json` (`scripts/build_blackholes.py`), 그림은 `web/js/blackhole.js` | 색인한 위키 문서에 중심 초대질량 블랙홀을 사실로 서술한 문장이 있거나, Wikidata에서 은하와 블랙홀 항목이 이어진 은하만 고릅니다(M31, M84, M87, M104). "생겨날 가능성", "나타나지 않으며" 같은 문장은 근거로 쓰지 않습니다. 모습은 슈바르츠실트 블랙홀 둘레에서 휘는 빛의 경로를 셰이더로 계산한 상상도이며, 실제 크기나 모습이 아닙니다 |
| 가까이 간 천체 모습 | `web/js/details.js` | 내 세상 보기에서 가까이 가면 별은 분광형 색의 원반, 메시에 천체는 허블 사진, 사진이 없는 성단과 성운은 그 종류의 모습으로 보입니다. 지도의 크기는 실제 비율이 아닙니다 |
| 메시에 사진 | `web/data/messier/M{n}.jpg` 89장 + `credits.json` (4.7MB) | 허블 메시에 목록에 없는 21개(주로 산개 성단)는 사진 없이 둡니다. 사진의 시야와 방향 정보가 없어 하늘에서는 카탈로그 크기에 맞춰 둥글게 띄울 뿐, 방향은 맞추지 않습니다. 대표 사진이 천체의 일부만 담은 경우(M31 등)도 있습니다 |
| 3D 모델 | `web/data/models/*.glb` 4개 (3.4MB, NASA 3D Resources) | 내 세상 보기에서 그 점에 가까이 갈 때만 내려받습니다. 지도처럼 크기는 실제 비율이 아닙니다 |

출처와 이용 조건은 `web/data/textures/CREDITS.md`, `web/data/models/CREDITS.md`, `web/data/messier/credits.json`에 있습니다.

---

## 6. 항목 메타데이터 색인 (RAG 1)

```bash
python -m scripts.index_items --dry-run          # 임베딩 없이 색인 텍스트 확인 (토큰 사용 없음)
python -m scripts.index_items --show 플레이아데스  # 특정 항목의 색인 텍스트 출력
python -m scripts.index_items                    # 바뀐 항목만 임베딩해 cosmos_items에 색인
python -m scripts.index_items --rebuild          # 컬렉션을 지우고 처음부터 다시 색인
```

| 동작 | 설명 |
|---|---|
| 청크 | 항목당 1개, 청크 ID = Wikidata QID |
| 재실행 | 같은 ID로 덮어쓰기: 중복 저장 없음 |
| 증분 | 텍스트가 바뀐 항목만 다시 임베딩 (`text_hash` 비교) |
| 정리 | 카탈로그에서 빠진 항목은 컬렉션에서도 삭제 |
| 확인 | 마지막 줄 `[ OK ] 로드 N건 = 색인 N건` |

---

## 7. 외부 문서 수집

```bash
# 질문 하나로 수집 흐름 확인: 검색어, 후보별 색인/제외 사유, 연결 문서 출력
python -m scripts.collect_docs --item "보이저 1호" --question "보이저 1호는 태양계를 벗어났나?"

# 모든 항목의 자체 문서(위키 문서, NASA 미션 설명)를 미리 받기: LLM 호출 없음
python -m scripts.collect_docs --own
```

| 동작 | 설명 |
|---|---|
| 검색어 | 프롬프트 1이 추출, 항목 이름은 항상 포함 |
| 선별 | 프롬프트 2가 제목, 요약만 보고 고름: 본문은 선별된 문서만 받음 |
| 항목 자체 문서 | 선별, 길이 규칙과 상관없이 항상 연결 |
| 검색 결과 캐시 | 검색어별, **정상 응답만** 저장: 같은 검색어는 검색 API를 다시 부르지 않음 |
| 선별 판정 | (항목, 질문)별, **프롬프트 성공 시에만** 저장: 같은 질문은 LLM 호출 없음, 새 질문은 같은 후보도 다시 판정 |
| 본문 캐시 | 문서별, **본문이 있을 때만** 저장 |
| 실패 | 검색, 선별, 본문 실패는 완료로 기록하지 않습니다. 다시 실행하면 실패한 단계부터 이어서 처리합니다 |
| 위치 | `data/cache/` (커밋 제외) |

예전 형식의 캐시가 남아 있거나 수집이 꼬인 것 같으면 한 번 정리해 주세요.

```bash
python -m scripts.collect_docs --repair-cache   # 예전 기록 변환, 빈 본문, 확인 안 된 빈 검색 결과 삭제
```

---

## 8. 외부 문서 색인 (RAG 2)

서비스에서는 **질문이 들어온 항목의 문서만** 그때그때 청킹하고 색인합니다 (토큰 할당량 절약).
아래 명령은 결과를 확인하거나 미리 색인해 둘 때 씁니다.

```bash
python -m scripts.index_docs --item "보이저 1호" --dry-run   # 임베딩 없이 청크 수, 글자 수 확인
python -m scripts.index_docs --item "보이저 1호"             # 이미 수집한 문서를 청킹, 색인
python -m scripts.index_docs --demo                          # 시연용 대표 12개 항목의 자체 문서 수집, 색인 (LLM 없음)
python -m scripts.index_docs --reindex                       # 색인된 항목을 현재 청크 설정으로 다시 맞춤
python -m scripts.index_docs --rebuild                       # 임베딩 모델 변경 시: 임시 컬렉션에서 재구축 후 교체
python -m scripts.index_docs --stats                         # 컬렉션 현황
```

임베딩 모델이나 차원이 바뀌면 일반 실행은 불일치 오류를 내고 멈춥니다. 컬렉션별 복구 명령은 다음과 같습니다.

| 컬렉션 | 재구축 명령 | 실패 시 |
|---|---|---|
| `cosmos_items` | `python -m scripts.index_items --rebuild` | 기존 색인 보존 |
| `cosmos_docs` | `python -m scripts.index_docs --rebuild` | 기존 색인 보존, `cosmos_items`는 건드리지 않음 |
| `cosmos_perspective` | `python -m scripts.index_perspective --rebuild` | 기존 서가 보존 |

| 동작 | 설명 |
|---|---|
| 청크 ID | `항목ID:문서ID:순번`: 여러 항목이 같은 문서를 수집해도 덮어쓰지 않음 |
| 청킹 | 위키는 절 제목 경계 우선 + 절 경로 머리말, NASA는 문단, 문장 경계 |
| 증분 | 항목 단위로 비교해 바뀐 청크만 재임베딩, 연결이 풀린 문서의 청크만 삭제 |
| 보존 | 본문이 비었거나 캐시가 없는 문서는 기존 청크를 지우지 않음 (캐시는 연결 정보로 다시 받아 복구) |
| 청크 설정 변경 | `config.toml [chunking]` 수정 후 `--reindex`: 비교 실험은 `[collections] docs`도 바꿔 별도 컬렉션에 |

### 관점 전환 서가 색인

관점 전환이 근거로 삼는 위키 문서 13개(주제 5개)를 `cosmos_perspective`에 색인합니다. 서버를 처음 띄우기 전에 한 번 실행하세요.

```bash
python -m scripts.index_perspective --list      # 주제별 서가 문서 (외부 호출 없음)
python -m scripts.index_perspective             # 문서를 받아(캐시 우선) 바뀐 청크만 반영
python -m scripts.index_perspective --rebuild   # 임시 컬렉션에서 재구축 후 교체
```

| 동작 | 설명 |
|---|---|
| 서가 문서 | `vasthorizon/data/perspective_library.py`: 주제, 문서, 이어서 볼 천체 |
| 결과 | 문서 13개, 청크 123개 (기본 청크 설정 기준) |
| 보존 | 받지 못한 문서의 기존 청크는 지우지 않음, `--rebuild`는 하나라도 못 받으면 멈춤 |
| 분리 | 항목 문서 색인(`cosmos_docs`)과 다른 컬렉션: 항목 문서 재구축이 서가에 영향 없음 |

---

## 9. 질문하기 (RAG 전체 흐름)

```bash
python -m scripts.ask --item "보이저 1호" --question "보이저 1호는 태양계를 벗어났나?"
python -m scripts.ask --item "보이저 1호" --question "…" --no-collect        # 수집 없이 기존 색인만
python -m scripts.ask --item "보이저 1호" --question "…" --search-type mmr   # 검색 방식 지정
python -m scripts.ask --item "제임스 웹" --question "…" --compare           # 유사도 vs MMR 근거 비교
python -m scripts.ask --graph                                               # LangGraph 구조 출력
```

| 단계 | 내용 |
|---|---|
| 수집, 색인 | 질문이 들어온 항목의 문서만 (캐시 재사용) |
| retrieve | 항목 메타데이터 청크(항상 근거 1) + 항목 범위 외부 문서 Top-k, 병합, 중복 제거 |
| generate | 근거만으로 답변, 주장마다 `[근거 N]`: 인용된 근거만 원문 링크와 함께 표시 |
| 확인 불가 | 근거에 없으면 "제공된 문서에서는 확인되지 않습니다"라고 답합니다 |
| 답변 검증 | 목록에 없는 근거 번호, 인용 없는 사실 답변은 1회 재생성, 그래도 어기면 답변 대신 안내 문구 |
| 장애 | 임베딩 API 일시 장애 시 기존 색인 근거로 답변 (경고 표시), 임베딩 모델 불일치 시 중단 |

답변 상태에 나오는 '인용 번호 검증 통과'는 인용 번호가 근거 목록에 있는지만 확인하는 형식 검증입니다.
주장과 근거 내용이 실제로 맞는지까지 보장하지는 않습니다.


실시간 위치: JPL Horizons로 위치를 계산하는 항목(태양계 천체, 심우주 탐사선 52개)은 질문할 때마다 **오늘 위치**를
다시 계산해 근거에 넣습니다 (LLM 호출 없음, 하루 단위 캐시). 색인에 들어간 거리에는 수집 기준일을 함께 적어 둡니다.
예: 보이저 1호: "2026-10-22 기준 지구로부터 약 258억km … 수집 기준일 값보다 약 303만km 멀어짐".

---

## 10. API 서버

```bash
uvicorn vasthorizon.api.app:app --port 8000
```

- 3D 화면: http://localhost:8000/ (같은 서버가 `web/` 폴더도 함께 내보냅니다)
- API 문서(요청, 응답 형식): http://localhost:8000/docs

### 3D 화면 (디자인 v2)

무대가 곧 페이지입니다. 화면 전체가 하늘이고 머리와 발은 그 위에 떠 있으며, 정보는 필요할 때만 오른쪽 서랍을 열어 보여 줍니다.

```
처음          "고개를 들어 보세요", 지금 당신의 세상은 지평선까지 4.7km
하늘          실제 별 11만 개, 은하수, 성운, 성단, 은하. 휠로 확대하면 더 어두운 별이 나타난다
              옅은 고리(아직 관측하지 않은 카탈로그 천체)나 아무 별이나 누르면 서랍이 열린다
              → 이름 → 지구로부터 거리 → 그 천체의 이야기(위키 문서 첫머리, 역사 절) → 빛의 편지
              → 다 읽고 '내 세상에 담기'를 누르면 옅은 고리가 금빛 고리로 바뀌고 이름이 나타나며,
                내 세상의 반지름이 그 천체까지 넓어진다 (왼쪽 아래 숫자가 굴러 올라가고 "빛으로 약 548년, 지평선의 1,110조 배")
지평선 길     지평선, 태양계, 별, 은하, 우주의 끝: 금빛은 오늘 바라본 가장 먼 곳까지
              지평선 너머나 반지름 숫자를 누르면 지구에서 떠올라 → 끝 장면 "오늘 당신의 세상은 …"
```

| 화면 요소 | 역할, 요구사항 |
|---|---|
| 오른쪽 위 상태 | 색인 건수 "항목 424 · 문서 N 청크" (F2002), 문제가 있으면 노란 점 |
| 천체 목록 | 검색, 그룹 필터, 오늘 관측한 천체 표시 → 누르면 그 천체 서랍과 대화 기록 (F2009) |
| 발사대 | 조건 탐색, 빛의 편지, 마음 한 줄, 오늘 밤 하늘, 별자리 펼치기: 서랍이 열리면 아이콘만 |
| 근거 목록 | 제목, 원문 링크, 출처 종류 태그(메타데이터 / 외부 문서), 발췌, 인용 없으면 "이 답변에는 인용된 근거가 없습니다." (F2008, F2016) |
| 진행 상태 | 검색어 추출 → 문서 수집(제목) → 색인 → 답변 작성 단계를 차례로 표시 (F2012) |
| 안내 띠 | 색인 없음, API 키 없음을 맨 위에 (F2012): 키 값, 프롬프트, 오류 추적은 보이지 않음 (NF2004) |
| 쉬기 | 4초 동안 움직임이 없으면 머리와 발이 흐려집니다 (서랍이나 장면이 열려 있으면 그대로 둡니다) |

| 바로 가기 주소 | 화면 |
|---|---|
| `/?mode=sky` | 처음 장면 없이 하늘 |
| `/?item=Q12124` | 베텔게우스 서랍을 연 하늘 |
| `/?panel=catalog`, `explore`, `letter`, `mind`, `tonight` | 그 서랍을 연 하늘 |
| `/?mode=map` | 지구에서 떠오르기 |
| `/?mode=map&journey=end` | 끝 장면 (관측 가능한 우주) |
| `/?mode=unfold&con=Q8860` | 오리온자리 펼치기 |
| `/?prologue=1` | 프롤로그를 다시 (처음 방문에만 저절로 나옵니다. 시작 화면의 '프롤로그 다시 보기'로도 볼 수 있습니다) |
| `/?motion=off` | 카메라 움직임 없이 (운영체제의 '움직임 줄이기' 설정도 따릅니다) |

- Three.js(r170, MIT)와 Lucide 아이콘(0.468.0, ISC)은 `web/` 안에 들어 있어서 인터넷이 없어도 화면이 열립니다.
- 글꼴(Pretendard, Noto Serif KR, IBM Plex Mono)은 CDN에서 받습니다. 인터넷이 없으면 시스템 글꼴을 대신 씁니다.
- 디자인 토큰(색, 글자, 간격, 효과)은 `web/tokens/*.css`에 있으며, 디자인 키트 값을 그대로 씁니다.
- 지구 궤도 위성은 궤도 정보가 없어서 방향을 예시로 정해 두었고, 툴팁에 '방향은 예시'라고 표시합니다.
- 하늘의 아무 별이나 그 별 자체로 물어볼 수 있습니다. 항목 ID는 `hip:<히파르코스 번호>` 형식입니다.
  - 별자리 선의 별(756개, 카탈로그 밖 665개)은 별자리 모양 데이터(거리, 등급)로 바로 엽니다.
  - 그 밖의 별은 누를 때 히파르코스 번호로 Wikidata에서 거리, 한국어 이름, 한국어 위키 문서를 조회합니다(처음 1초 안팎). 결과는 `data/cache/stars/`에 남겨 다음부터는 바로 엽니다. 조회에 실패하면 캐시하지 않고 `503 star_lookup_failed`를 돌려줍니다.
  - 거리는 연주시차로 교차 검증합니다([03 §3](03_rag_pipeline_design.md#별-거리-정책)). Wikidata에 거리가 없는 별은 거리를 지어내지 않고 등급과 색만 보여 줍니다. 지도에는 놓지 않고, '거리 미확인'으로 알아간 빛 기록에만 남길 수 있습니다.
  - 한 번호에 Wikidata 엔티티가 여럿 걸리면 이름, 문서, 거리를 반드시 한 엔티티 안에서만 만듭니다. 거리가 있는 엔티티가 둘 이상이면 어느 별인지 정할 수 없으므로 담지 않습니다. 같은 값이 여러 행에 반복돼도 한 번만 셉니다.
- 카탈로그 별과 메시에 천체는 하늘 데이터의 히파르코스 번호와 메시에 번호로 카탈로그 항목과 이어집니다. 하늘에서 눌러도 카탈로그 항목이 열립니다.
- 고른 천체는 오늘 밤 하늘과 내 세상 보기 모두에서 맥박 치는 고리와 이름으로 표시됩니다. 서랍을 닫거나 다른 기능으로 바꾸면 사라집니다.
- 위치 버튼은 브라우저의 위치 권한을 사용합니다. 권한을 거절하면 서울을 기준으로 계산합니다.
- 알아간 빛의 기록(내 세상)은 브라우저에만 저장하며 서버로는 보내지 않습니다. 날짜가 바뀌어도 지워지지 않고, 내 세상 카드의 '기록 처음부터 다시 시작'을 두 번 눌러야 지워집니다.

| 메서드, 경로 | 역할 |
|---|---|
| `GET /api/health` | 키, 색인 상태와 화면 안내 (키 값은 노출하지 않음) |
| `GET /api/items`, `GET /api/items/{id}` | 항목 목록 (`group`, `q` 필터), 상세 |
| `GET /api/items/{id}/intro` | 천체 소개: 자체 위키 문서 첫머리, 역사 절 발췌 (LLM 호출 없음, 출처, 이용 조건 포함) |
| `POST /api/ask` | 질문 → 근거 기반 답변 |
| `POST /api/ask/stream` | 같은 질문을 진행 상태와 함께 (Server-Sent Events) |
| `GET`, `DELETE /api/history/{id}?session_id=` | 항목별 대화 기록 조회, 삭제 |
| `POST /api/explore` | 자연어 조건으로 항목 찾기: 적용한 필터와 조건에 맞는 항목 카드. 질문에 이름이 나온 천체(`mentioned`)도 함께 주고, 그 천체에 대한 사실 질문이면 `status: "ask"` |
| `POST /api/light-letter` | 빛의 편지: `{"item_id": "Q13423"}` 또는 `{"age": 25}` (나이만큼 먼 별) |
| `GET /api/constellations/{id}/figure` | 별자리 선과 별들의 좌표, 카탈로그 거리 (LLM 호출 없음) |
| `POST /api/constellations/{id}/unfold` | 별자리 펼치기 설명: 별 거리표를 근거로 인용 |
| `POST /api/sky` | 오늘 밤 나의 하늘: `{"lat": 37.57, "lon": 126.98, "at": "2026-10-22T21:00:00"}` |
| `GET /api/perspective/themes` | 관점 전환 감정 버튼 목록 |
| `POST /api/perspective` | 관점 전환: `{"text": "마음 한 줄"}`, `{"theme": "small"}`, 둘 다 |

`/api/sky` 메모

| 항목 | 동작 |
|---|---|
| 시각 | 비우면 지금, 시간대가 없으면 한국 시간(UTC+9) |
| `guide: false` | 별자리, 행성 위치만 계산 (LLM 호출 없음) |
| 낮, 박명 | 태양 고도 −6도 이상이면 안내 문장을 만들지 않음 (`status: daytime`) |
| 행성 | 카탈로그 위치 기준일 ±3일 안에서만 표시, 달은 표시하지 않음 |

`/api/perspective` 메모

| 항목 | 동작 |
|---|---|
| 위기 표현 | 코드 검사(LLM 호출 없음) → LLM 분류 2차 확인. 위기면 답변 없이 `status: crisis` + 상담 창구 (109, 1577-0199) |
| 확인 순서 | 위기 확인 ①② → 감정 버튼 값, 서가 색인 확인 → 검색, 답변. 버튼 값이 잘못되었거나 서가가 없어도 위기 확인은 그대로 진행합니다 |
| 2차 확인 실패 | 분류 모델 장애, 키 없음, `crisis` 값 오류 → `status: unchecked`: 답변 없이 재시도, 감정 버튼, 상담 창구 안내 |
| 모든 응답 | `disclaimer` "VastHorizon은 전문 심리상담을 대신하지 않습니다.", `support` 상담 창구 |
| 감정 버튼만 | 분류 호출 없이 그 주제의 서가 문서에서 검색 |
| 답변 규칙 | 서가 문서의 사실만 인용, 진단, 조언, 근거 없는 위로 금지 (질의응답과 같은 인용 검증) |

```bash
curl -N -X POST http://localhost:8000/api/ask/stream -H "Content-Type: application/json" \
  -d '{"session_id": "demo-session-01", "item_id": "Q48469", "question": "보이저 1호는 태양계를 벗어났나?"}'
```

| 오류 코드 | 상황 |
|---|---|
| `missing_key` (503) | GMS 키 없음 |
| `index_missing` (503) | 항목 색인 없음 |
| `index_incompatible` (503) | 색인과 임베딩 설정 불일치: 재구축 필요 |
| `item_not_found` (404), `invalid_request` (422) | 잘못된 항목, 요청 |
| `letter_unavailable` (422) | 빛의 편지를 쓸 수 없는 항목 (거리 없음, 지구 궤도 위성) |
| `figure_unavailable` (422) | 별자리가 아니거나 별자리 모양 데이터 없음 |
| `internal` (500) | 그 밖의 오류: 자세한 내용은 서버 로그에만 |

대화 기록은 서버 메모리에 (세션, 항목)별로 보관합니다. 서버를 다시 시작하면 지워집니다.

| 동시성 정책 | 동작 |
|---|---|
| 서비스 초기화 | 첫 요청에서 한 번만 생성: 동시에 들어온 첫 요청들도 같은 서비스와 대화 기록을 씁니다 |
| 같은 대화(세션 + 항목) | 한 번에 한 질문: 처리 중이면 `409 conversation_busy` (일반, SSE 동일, SSE는 스트림 열기 전) |
| 다른 대화 | 서로 기다리지 않고 독립 처리 |
| 실패한 질문 | 처리 중 표시를 풀어 다음 질문이 바로 가능 |
| 처리 중 기록 삭제 | 그 질문의 답변은 돌려주되 `recorded: false`: 지운 기록에 다시 섞이지 않음. 삭제 직후 새 질문 가능 |

### Chroma 저장소 구조와 이전

색인은 컬렉션마다 별도의 저장소에 둡니다: `data/chroma/cosmos_items/`, `data/chroma/cosmos_docs/`.
두 컬렉션을 한 저장소에 함께 두었더니 로컬 Chroma에서 검색 오류가 간헐적으로 생겼기 때문입니다.

아직 예전 구조(`data/chroma/chroma.sqlite3`)를 쓰고 있다면 한 번 이전하세요. 재임베딩 없이 벡터를 그대로 옮깁니다.

```bash
python -m scripts.migrate_chroma --dry-run   # 옮길 컬렉션, 건수 확인
python -m scripts.migrate_chroma             # 이전: 기존 저장소는 data/chroma_legacy_<시각>/ 에 보관
```

---

### 검증 페이지 (Streamlit): 검색 방식 비교 (F2014)

```bash
streamlit run app/streamlit_app.py      # http://localhost:8501
```

| 항목 | 동작 |
|---|---|
| 입력 | 문서가 색인된 항목, 질문, 왼쪽에서 top-k, fetch-k, lambda 조정 |
| 결과 | 유사도 검색, MMR 근거를 나란히: 제목 › 절, 출처 종류, 유사도, 청크 본문, 두 방식 공통 표시 |
| 비용 | 답변은 만들지 않습니다 (LLM 호출 없음, 질문 임베딩 1회) |
| 안내 | 문서 색인 없음, 이 항목의 청크 없음, 검색 오류, 청크 수가 top-k 이하 |

터미널에서도 같은 비교를 할 수 있습니다: `python -m scripts.ask --item "보이저 1호" --question "…" --compare` (같은 함수 `features/compare.py`를 씁니다).

### 검증 페이지: RAG 전후 비교 (F2015)

```bash
python -m scripts.compare_rag              # 기획안 7장 질문 8개: 근거 없이, RAG로 답하게 하고 저장
python -m scripts.compare_rag --only 3 7   # 일부만 다시: 같은 (번호, 버전)만 바꾸고 나머지는 실행 정보째 둠
```

| 항목 | 내용 |
|---|---|
| 결과 | `data/eval/rag_comparison.json` (커밋 대상): 검증 페이지의 'RAG 전후 비교' 탭이 이 파일을 읽습니다 |
| 실행 정보 | 문항마다 실행 ID, 시각, 모델, 검색, 청킹 설정, 프롬프트 지문, 코드 버전. 조건이 섞여 있으면 탭에 경고가 뜹니다 |
| 이전 결과 | 전체 실행 시 `data/eval/archive/`에 보관 (지우지 않음) |
| 비용 | 문항당 GMS 호출 약 4~5회 (근거 없이 1회 + RAG 질의응답) |
| 판정, 해설 | `docs/05_rag_comparison.md` |

---

## 11. 테스트

외부 API를 호출하지 않는 회귀 테스트입니다.

```bash
python -m unittest discover -s tests -t .
node --test "tests/js/*.test.mjs"   # 3D 화면의 천문 계산 (Node.js 21 이상)
```

---

## 12. 설정 파일

검색 품질에 영향을 주는 값은 `config.toml`에서 바꿉니다.

| 섹션 | 키 | 기본값 | 의미 |
|---|---|---|---|
| `llm` | `chat_model` | `gpt-6-luna` | 답변, 프롬프트용 GPT 모델 |
| `llm` | `embedding_model` | `text-embedding-3-small` | 임베딩 모델 |
| `chunking` | `chunk_size` / `chunk_overlap` | 1000 / 200 | 문서 청크 크기, 중복 길이 |
| `retrieval` | `search_type` | `similarity` | `similarity` 또는 `mmr` |
| `retrieval` | `top_k_docs` | 6 | 외부 문서 근거 수 |
| `retrieval` | `mmr_fetch_k` / `mmr_lambda` | 30 / 0.5 | MMR 후보 수, 다양성 가중치 |
| `collect` | `max_queries` / `max_selected` | 4 / 4 | 검색어 수, 한 번에 고를 문서 수 |
| `collect` | `min_summary_chars` / `min_doc_chars` | 40 / 200 | 선별 전 요약, 본문 최소 길이 (항목 자체 문서는 예외) |
| `collect` | `max_doc_chars` | 20000 | 문서 본문 최대 길이 |
| `http` | `min_interval_sec` | 0.5 | 같은 호스트 호출 간격 |

비교 실험을 할 때는 설정 파일을 복사해 값만 바꾼 뒤, 그 파일을 지정해 실행합니다.

```bash
cp config.toml config.chunk500.toml   # chunk_size = 500 으로 수정
VH_CONFIG=config.chunk500.toml python -m scripts.check_env
```
