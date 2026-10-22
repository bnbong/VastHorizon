# 부록 A. 설치 · 실행 안내

VastHorizon을 직접 실행하려는 사람을 위한 안내다.
프로젝트 수행 결과는 [README](../README.md)를 본다.

> 이 문서는 구현이 진행되며 단계별로 채워진다.

---

## 1. 준비물

| 항목 | 버전 · 내용 |
|---|---|
| Python | 3.10 이상 (`tomllib` 사용으로 3.11 이상 권장) |
| SSAFY GMS 키 | https://gms.ssafy.io/web/ 에서 발급 |
| 연락처 이메일 | 위키백과 · Wikidata User-Agent용 |

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

`.env.example`을 복사해 `.env`를 만들고 값을 채운다.

```
GMS_KEY=발급받은_키
WIKI_CONTACT=your-email@example.com
```

| 변수 | 필수 | 설명 |
|---|:---:|---|
| `GMS_KEY` | ✅ | GMS 키. 코드에 직접 쓰지 않는다 |
| `WIKI_CONTACT` | ✅ | 외부 API User-Agent 연락처 |
| `VH_CONFIG` | | 다른 설정 파일 경로 (비교 실험용) |

> `.env`는 `.gitignore`에 등록되어 있다. 키가 커밋되면 폐기하고 재발급한다.

---

## 4. 환경 점검

```bash
python -m scripts.check_env          # 설정 · 외부 API 연결 확인 (토큰 사용 없음)
python -m scripts.check_env --llm    # GMS 채팅 · 임베딩까지 1회 호출
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
| 원본 캐시 | `data/raw/` — 파일마다 `*.meta.json`에 수집 시각 기록 (커밋 제외) |
| 저장 조건 | 최소 100건 · 5개 그룹 · QID 중복 없음 · 좌표 · 거리 · 출처 검증 통과 |
| 실패 시 | 종료 코드 1, 기존 `data/items.json`은 그대로 유지 |

### 별자리 모양 데이터

별자리 펼치기 · 하늘 안내 · 3D 화면이 쓰는 별자리 선과 별들의 실제 거리다. 카탈로그를 만든 뒤 실행한다.

```bash
python -m scripts.collect_constellations            # data/raw 캐시가 있으면 재사용
python -m scripts.collect_constellations --refresh
```

| 동작 | 설명 |
|---|---|
| 결과 | `data/constellations.json` (커밋 대상) — 별자리 88개 · 선을 이루는 별 766개 |
| 별 연결 | d3-celestial 별자리 선의 꼭짓점 → 0.02도 안의 별 → 히파르코스 번호 |
| 거리 | Wikidata 거리 값을 연주시차로 검증 (단위가 틀린 값 제외) |
| 없을 때 | 서버는 동작하고, 상태 점검에 `figures_missing` 안내 · 펼치기는 `422 figure_unavailable` |

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
| 재실행 | 같은 ID로 덮어쓰기 — 중복 저장 없음 |
| 증분 | 텍스트가 바뀐 항목만 다시 임베딩 (`text_hash` 비교) |
| 정리 | 카탈로그에서 빠진 항목은 컬렉션에서도 삭제 |
| 확인 | 마지막 줄 `[ OK ] 로드 N건 = 색인 N건` |

---

## 7. 외부 문서 수집

```bash
# 질문 하나로 수집 흐름 확인 — 검색어 · 후보별 색인/제외 사유 · 연결 문서 출력
python -m scripts.collect_docs --item "보이저 1호" --question "보이저 1호는 태양계를 벗어났나?"

# 모든 항목의 자체 문서(위키 문서 · NASA 미션 설명)를 미리 받기 — LLM 호출 없음
python -m scripts.collect_docs --own
```

| 동작 | 설명 |
|---|---|
| 검색어 | 프롬프트 1이 추출, 항목 이름은 항상 포함 |
| 선별 | 프롬프트 2가 제목 · 요약만 보고 고름 — 본문은 선별된 문서만 받음 |
| 항목 자체 문서 | 선별 · 길이 규칙과 상관없이 항상 연결 |
| 검색 결과 캐시 | 검색어별, **정상 응답만** 저장 — 같은 검색어는 검색 API를 다시 부르지 않음 |
| 선별 판정 | (항목, 질문)별, **프롬프트 성공 시에만** 저장 — 같은 질문은 LLM 호출 없음, 새 질문은 같은 후보도 다시 판정 |
| 본문 캐시 | 문서별, **본문이 있을 때만** 저장 |
| 실패 | 검색 · 선별 · 본문 실패는 완료로 기록하지 않음 — 다시 실행하면 실패한 단계부터 이어서 처리 |
| 위치 | `data/cache/` (커밋 제외) |

예전 형식 캐시가 남아 있거나 수집이 꼬였다고 의심되면 한 번 정리한다.

```bash
python -m scripts.collect_docs --repair-cache   # 예전 기록 변환 · 빈 본문 · 확인 안 된 빈 검색 결과 삭제
```

---

## 8. 외부 문서 색인 (RAG 2)

서비스에서는 **질문이 들어온 항목의 문서만** 그때 청킹 · 색인한다 (토큰 할당량 절약).
아래 명령은 확인 · 사전 색인용이다.

```bash
python -m scripts.index_docs --item "보이저 1호" --dry-run   # 임베딩 없이 청크 수 · 글자 수 확인
python -m scripts.index_docs --item "보이저 1호"             # 이미 수집한 문서를 청킹 · 색인
python -m scripts.index_docs --demo                          # 시연용 대표 12개 항목의 자체 문서 수집 · 색인 (LLM 없음)
python -m scripts.index_docs --reindex                       # 색인된 항목을 현재 청크 설정으로 다시 맞춤
python -m scripts.index_docs --rebuild                       # 임베딩 모델 변경 시 — 임시 컬렉션에서 재구축 후 교체
python -m scripts.index_docs --stats                         # 컬렉션 현황
```

임베딩 모델 · 차원이 바뀌면 일반 실행은 불일치 오류로 멈춘다. 컬렉션별 복구 명령은 다음과 같다.

| 컬렉션 | 재구축 명령 | 실패 시 |
|---|---|---|
| `cosmos_items` | `python -m scripts.index_items --rebuild` | 기존 색인 보존 |
| `cosmos_docs` | `python -m scripts.index_docs --rebuild` | 기존 색인 보존 · `cosmos_items`는 건드리지 않음 |
| `cosmos_perspective` | `python -m scripts.index_perspective --rebuild` | 기존 서가 보존 |

| 동작 | 설명 |
|---|---|
| 청크 ID | `항목ID:문서ID:순번` — 여러 항목이 같은 문서를 수집해도 덮어쓰지 않음 |
| 청킹 | 위키는 절 제목 경계 우선 + 절 경로 머리말, NASA는 문단 · 문장 경계 |
| 증분 | 항목 단위로 비교해 바뀐 청크만 재임베딩, 연결이 풀린 문서의 청크만 삭제 |
| 보존 | 본문이 비었거나 캐시가 없는 문서는 기존 청크를 지우지 않음 (캐시는 연결 정보로 다시 받아 복구) |
| 청크 설정 변경 | `config.toml [chunking]` 수정 후 `--reindex` — 비교 실험은 `[collections] docs`도 바꿔 별도 컬렉션에 |

### 관점 전환 서가 색인

관점 전환이 근거로 쓰는 위키 문서 13개(주제 5개)를 `cosmos_perspective`에 색인한다. 서버를 처음 띄우기 전에 한 번 실행한다.

```bash
python -m scripts.index_perspective --list      # 주제별 서가 문서 (외부 호출 없음)
python -m scripts.index_perspective             # 문서를 받아(캐시 우선) 바뀐 청크만 반영
python -m scripts.index_perspective --rebuild   # 임시 컬렉션에서 재구축 후 교체
```

| 동작 | 설명 |
|---|---|
| 서가 문서 | `vasthorizon/data/perspective_library.py` — 주제 · 문서 · 이어서 볼 천체 |
| 결과 | 문서 13개 · 청크 123개 (기본 청크 설정 기준) |
| 보존 | 받지 못한 문서의 기존 청크는 지우지 않음 · `--rebuild`는 하나라도 못 받으면 멈춤 |
| 분리 | 항목 문서 색인(`cosmos_docs`)과 다른 컬렉션 — 항목 문서 재구축이 서가에 영향 없음 |

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
| 수집 · 색인 | 질문이 들어온 항목의 문서만 (캐시 재사용) |
| retrieve | 항목 메타데이터 청크(항상 근거 1) + 항목 범위 외부 문서 Top-k, 병합 · 중복 제거 |
| generate | 근거만으로 답변, 주장마다 `[근거 N]` — 인용된 근거만 원문 링크와 함께 표시 |
| 확인 불가 | 근거에 없으면 "제공된 문서에서는 확인되지 않습니다"로 답함 |
| 답변 검증 | 목록에 없는 근거 번호 · 인용 없는 사실 답변은 1회 재생성, 그래도 어기면 답변 대신 안내 문구 |
| 장애 | 임베딩 API 일시 장애 시 기존 색인 근거로 답변 (경고 표시), 임베딩 모델 불일치 시 중단 |

답변 상태의 '인용 번호 검증 통과'는 번호가 근거 목록에 있다는 형식 검증이다.
주장과 근거 내용이 실제로 맞는지까지 보장하지는 않는다.

---

## 10. API 서버

```bash
uvicorn vasthorizon.api.app:app --port 8000
```

- API 문서(요청 · 응답 형식): http://localhost:8000/docs

| 메서드 · 경로 | 역할 |
|---|---|
| `GET /api/health` | 키 · 색인 상태와 화면 안내 (키 값은 노출하지 않음) |
| `GET /api/items` · `GET /api/items/{id}` | 항목 목록 (`group` · `q` 필터) · 상세 |
| `POST /api/ask` | 질문 → 근거 기반 답변 |
| `POST /api/ask/stream` | 같은 질문을 진행 상태와 함께 (Server-Sent Events) |
| `GET` · `DELETE /api/history/{id}?session_id=` | 항목별 대화 기록 조회 · 삭제 |
| `POST /api/explore` | 자연어 조건으로 항목 찾기 — 적용한 필터와 조건에 맞는 항목 카드 |
| `POST /api/light-letter` | 빛의 편지 — `{"item_id": "Q13423"}` 또는 `{"age": 25}` (나이만큼 먼 별) |
| `GET /api/constellations/{id}/figure` | 별자리 선과 별들의 좌표 · 실제 거리 (LLM 호출 없음) |
| `POST /api/constellations/{id}/unfold` | 별자리 펼치기 설명 — 별 거리표를 근거로 인용 |
| `POST /api/sky` | 오늘 밤 나의 하늘 — `{"lat": 37.57, "lon": 126.98, "at": "2026-10-22T21:00:00"}` |
| `GET /api/perspective/themes` | 관점 전환 감정 버튼 목록 |
| `POST /api/perspective` | 관점 전환 — `{"text": "마음 한 줄"}` · `{"theme": "small"}` · 둘 다 |

`/api/sky` 메모

| 항목 | 동작 |
|---|---|
| 시각 | 비우면 지금 · 시간대가 없으면 한국 시간(UTC+9) |
| `guide: false` | 별자리 · 행성 위치만 계산 (LLM 호출 없음) |
| 낮 · 박명 | 태양 고도 −6도 이상이면 안내 문장을 만들지 않음 (`status: daytime`) |
| 행성 | 카탈로그 위치 기준일 ±3일 안에서만 표시 · 달은 표시하지 않음 |

`/api/perspective` 메모

| 항목 | 동작 |
|---|---|
| 위기 표현 | 코드 검사(LLM 호출 없음) → LLM 분류 2차 확인. 위기면 답변 없이 `status: crisis` + 상담 창구 (109 · 1577-0199) |
| 확인 순서 | 위기 확인 ①② → 감정 버튼 값 · 서가 색인 확인 → 검색 · 답변. 잘못된 버튼 값 · 서가 없음도 위기 확인을 막지 않음 |
| 2차 확인 실패 | 분류 모델 장애 · 키 없음 · `crisis` 값 오류 → `status: unchecked` — 답변 없이 재시도 · 감정 버튼 · 상담 창구 안내 |
| 모든 응답 | `disclaimer` "VastHorizon은 전문 심리상담을 대신하지 않습니다." · `support` 상담 창구 |
| 감정 버튼만 | 분류 호출 없이 그 주제의 서가 문서에서 검색 |
| 답변 규칙 | 서가 문서의 사실만 인용 · 진단 · 조언 · 근거 없는 위로 금지 (질의응답과 같은 인용 검증) |

```bash
curl -N -X POST http://localhost:8000/api/ask/stream -H "Content-Type: application/json" \
  -d '{"session_id": "demo-session-01", "item_id": "Q48469", "question": "보이저 1호는 태양계를 벗어났나?"}'
```

| 오류 코드 | 상황 |
|---|---|
| `missing_key` (503) | GMS 키 없음 |
| `index_missing` (503) | 항목 색인 없음 |
| `index_incompatible` (503) | 색인과 임베딩 설정 불일치 — 재구축 필요 |
| `item_not_found` (404) · `invalid_request` (422) | 잘못된 항목 · 요청 |
| `letter_unavailable` (422) | 빛의 편지를 쓸 수 없는 항목 (거리 없음 · 지구 궤도 위성) |
| `figure_unavailable` (422) | 별자리가 아니거나 별자리 모양 데이터 없음 |
| `internal` (500) | 그 밖의 오류 — 자세한 내용은 서버 로그에만 |

대화 기록은 서버 메모리에 (세션, 항목)별로 둔다. 서버를 다시 시작하면 지워진다.

| 동시성 정책 | 동작 |
|---|---|
| 서비스 초기화 | 첫 요청에서 한 번만 생성 — 동시에 들어온 첫 요청들도 같은 서비스 · 대화 기록을 쓴다 |
| 같은 대화(세션 + 항목) | 한 번에 한 질문 — 처리 중이면 `409 conversation_busy` (일반 · SSE 동일, SSE는 스트림 열기 전) |
| 다른 대화 | 서로 기다리지 않고 독립 처리 |
| 실패한 질문 | 처리 중 표시를 풀어 다음 질문이 바로 가능 |
| 처리 중 기록 삭제 | 그 질문의 답변은 돌려주되 `recorded: false` — 지운 기록에 다시 섞이지 않음. 삭제 직후 새 질문 가능 |

### Chroma 저장소 구조와 이전

색인은 컬렉션마다 다른 저장소에 둔다 — `data/chroma/cosmos_items/`, `data/chroma/cosmos_docs/`.
한 저장소에 두 컬렉션을 함께 두면 로컬 Chroma에서 검색 오류가 간헐적으로 생겼기 때문이다.

예전 구조(`data/chroma/chroma.sqlite3`)라면 한 번 이전한다. 재임베딩 없이 벡터를 그대로 옮긴다.

```bash
python -m scripts.migrate_chroma --dry-run   # 옮길 컬렉션 · 건수 확인
python -m scripts.migrate_chroma             # 이전 — 기존 저장소는 data/chroma_legacy_<시각>/ 에 보관
```

---

## 11. 테스트

외부 API를 호출하지 않는 회귀 테스트다.

```bash
python -m unittest discover -s tests -t .
```

---

## 12. 설정 파일

검색 품질에 영향을 주는 값은 `config.toml`에서 바꾼다.

| 섹션 | 키 | 기본값 | 의미 |
|---|---|---|---|
| `llm` | `chat_model` | `gpt-6-luna` | 답변 · 프롬프트용 GPT 모델 |
| `llm` | `embedding_model` | `text-embedding-3-small` | 임베딩 모델 |
| `chunking` | `chunk_size` / `chunk_overlap` | 1000 / 200 | 문서 청크 크기 · 중복 길이 |
| `retrieval` | `search_type` | `similarity` | `similarity` 또는 `mmr` |
| `retrieval` | `top_k_docs` | 6 | 외부 문서 근거 수 |
| `retrieval` | `mmr_fetch_k` / `mmr_lambda` | 30 / 0.5 | MMR 후보 수 · 다양성 가중치 |
| `collect` | `max_queries` / `max_selected` | 4 / 4 | 검색어 수 · 한 번에 고를 문서 수 |
| `collect` | `min_summary_chars` / `min_doc_chars` | 40 / 200 | 선별 전 요약 · 본문 최소 길이 (항목 자체 문서는 예외) |
| `collect` | `max_doc_chars` | 20000 | 문서 본문 최대 길이 |
| `http` | `min_interval_sec` | 0.5 | 같은 호스트 호출 간격 |

비교 실험은 설정 파일을 복사해 값만 바꾸고 지정한다.

```bash
cp config.toml config.chunk500.toml   # chunk_size = 500 으로 수정
VH_CONFIG=config.chunk500.toml python -m scripts.check_env
```
