# 설치와 실행

VastHorizon을 직접 실행해 보려는 분을 위한 안내입니다.
기본 구성은 **Claude API로 답하고, 검색용 임베딩은 서버 안의 로컬 모델(MiniLM)로 계산하는 방식**입니다.
공개 서버에 올리는 방법은 [deploy.md](deploy.md)에, 파이프라인 설계는 [architecture.md](architecture.md)에 있습니다.

---

## 1. 준비물

| 항목 | 내용 |
|---|---|
| Python | **3.11 이상**이 필요합니다. 설정 모듈이 3.11부터 제공되는 표준 라이브러리 `tomllib`를 씁니다 |
| Claude API 키 | [Anthropic 콘솔](https://console.anthropic.com/)에서 발급합니다 |
| 연락처 이메일 | 위키백과와 Wikidata의 User-Agent에 넣습니다 |
| Node.js 21 이상 | 화면의 천문 계산 테스트를 돌릴 때만 필요합니다 |

---

## 2. 설치

```bash
python -m venv .venv
source .venv/bin/activate              # Windows (Git Bash): source .venv/Scripts/activate
pip install -r requirements-deploy.txt # requirements.txt + Claude, 로컬 임베딩(fastembed)
```

`.env.example`을 복사해 `.env`를 만들고 값을 채웁니다. `.env`는 `.gitignore`에 들어 있습니다.

```bash
CLAUDE_API_KEY=sk-ant-...          # 필수 (ANTHROPIC_API_KEY도 받습니다)
WIKI_CONTACT=you@example.com       # 권장: 외부 API User-Agent 연락처
```

이 구성은 설정 파일 `config.deploy.toml`을 씁니다. 아래 명령은 모두 `VH_CONFIG`가 지정된 셸에서 실행합니다.

```bash
export VH_CONFIG=config.deploy.toml          # Windows PowerShell: $env:VH_CONFIG="config.deploy.toml"
python -m scripts.check_env                  # 설정, 외부 API 연결 확인 (토큰 사용 없음)
python -m scripts.check_env --llm            # Claude 채팅 1회, 로컬 임베딩 1회 (키 값은 출력하지 않습니다)
```

---

## 3. 색인 만들고 실행하기

```bash
python -m scripts.deploy_init                     # 항목 색인 424건, 관점 전환 서가 색인 (data/deploy/)
uvicorn vasthorizon.api.app:app --port 8000
```

- 화면은 http://localhost:8000/ 에서, API 문서는 http://localhost:8000/docs 에서 열립니다.
- `deploy_init`은 색인이 이미 있고 임베딩 모델이 같으면 아무것도 하지 않습니다. 모델이 바뀌었으면 세 색인을 모두 새 모델로 다시 만듭니다(`--rebuild`로 강제할 수 있습니다).
- 문서 색인은 비어 있는 채로 시작합니다. 어떤 천체에 처음 질문하면 그 천체의 문서를 모아 색인하므로, 첫 답은 30초~1분쯤 걸립니다.

### 바로 가기 주소

| 주소 | 화면 |
|---|---|
| `/?mode=sky` | 처음 장면 없이 하늘 |
| `/?item=Q3427` | 베가 서랍을 연 하늘 |
| `/?panel=catalog`, `explore`, `letter`, `mind`, `tonight` | 그 서랍을 연 하늘 |
| `/?mode=map` | 내 세계 |
| `/?mode=unfold&con=Q8860` | 오리온자리 펼치기 |
| `/?prologue=1`, `/?prologue=0` | 프롤로그를 다시 보거나 건너뜁니다 |
| `/?motion=off` | 카메라 움직임을 끕니다 (운영체제의 '움직임 줄이기' 설정도 따릅니다) |

---

## 4. 데이터 다시 만들기

저장소에는 만들어 둔 데이터(`data/items.json`, `data/constellations.json`, `web/data/`)가 들어 있습니다. 데이터를 출처에서 다시 받거나 갱신할 때만 아래 스크립트를 씁니다.
스크립트는 원본 응답을 `data/raw/`에 캐시하며, `--refresh`를 주면 출처에서 다시 받습니다.

| 스크립트 | 만드는 것 | 출처 |
|---|---|---|
| `python -m scripts.collect_items` | `data/items.json`: 항목 메타데이터 424건, 5개 그룹 (`--epoch`로 Horizons 기준일 지정) | Wikidata, JPL Horizons, CelesTrak |
| `python -m scripts.collect_constellations` | `data/constellations.json`: 별자리 88개와 선을 이루는 별 756개의 카탈로그 거리 | d3-celestial, Wikidata |
| `python -m scripts.index_items` | `cosmos_items` 색인 (바뀐 항목만 임베딩, `--dry-run`, `--rebuild`) | `data/items.json` |
| `python -m scripts.index_perspective` | `cosmos_perspective`: 관점 전환 서가 13문서 | 한국어 위키백과 |
| `python -m scripts.build_sky_data` | `web/data/`의 별 118,216개, 성운과 성단과 은하 15,809개, 은하수 | d3-celestial |
| `python -m scripts.build_messier_images` | `web/data/messier/`: 메시에 천체 사진 89장과 출처 표기 | NASA Hubble's Messier Catalog |
| `python -m scripts.build_blackholes` | `web/data/blackholes.json`: 은하 중심 블랙홀 목록과 근거 | 색인한 위키 문서, Wikidata |
| `python -m scripts.build_icons` | 파비콘, 앱 아이콘, manifest, 공유 이미지 | `web/js/logo.js`의 로고 도형 |

질문 하나를 처리하는 과정을 터미널에서 끝까지 실행해 볼 수도 있습니다.

```bash
python -m scripts.collect_docs --item "보이저 1호" --question "보이저 1호는 태양계를 벗어났나?"   # 수집 흐름만
python -m scripts.ask --item "보이저 1호" --question "보이저 1호는 태양계를 벗어났나?"            # 수집, 검색, 답변
python -m scripts.ask --item "제임스 웹" --question "…" --compare                             # 유사도와 MMR 근거 비교
python -m scripts.index_docs --stats                                                           # 문서 컬렉션 현황
```

검색 방식(유사도, MMR)을 나란히 비교하는 Streamlit 검증 페이지도 있습니다(`streamlit run app/streamlit_app.py`).

---

## 5. API

| 메서드, 경로 | 역할 |
|---|---|
| `GET /api/health` | 키, 색인 상태와 화면 안내 (키 값은 내보내지 않습니다) |
| `GET /api/items`, `GET /api/items/{id}` | 항목 목록 (`group`, `q` 필터), 상세 |
| `GET /api/items/{id}/intro` | 천체 이야기: 자체 위키 문서 첫머리와 역사 절 발췌 (LLM 호출 없음) |
| `POST /api/ask`, `POST /api/ask/stream` | 질문 → 근거 기반 답변 (스트림은 진행 상태를 SSE로 보냅니다) |
| `GET`, `DELETE /api/history/{id}?session_id=` | 항목별 대화 기록 조회, 삭제 |
| `POST /api/explore` | 자연어 조건으로 항목 찾기 |
| `POST /api/light-letter` | 빛의 편지: `{"item_id": "Q13423"}` 또는 `{"age": 25}` |
| `GET /api/constellations/{id}/figure` | 별자리 선과 별들의 카탈로그 거리 (LLM 호출 없음) |
| `POST /api/constellations/{id}/unfold` | 별자리 펼치기 설명 |
| `POST /api/sky` | 오늘 밤 나의 하늘 (`guide: false`이면 계산만 하고 LLM을 부르지 않습니다) |
| `GET /api/perspective/themes`, `POST /api/perspective` | 관점 전환 감정 버튼 목록, 마음 한 줄에 대한 답 |
| `POST /api/share` | 캐시에 있는 편지를 공유 링크로 만듭니다. 응답의 `image_url`은 1200×630 미리보기 이미지이고, `tall_image_url`과 `tall_image_height`는 편지 전체를 담은 세로형 카드(폭 1080, 높이 1620~1920)의 주소와 높이입니다 |

```bash
curl -N -X POST http://localhost:8000/api/ask/stream -H "Content-Type: application/json" \
  -d '{"session_id": "demo-session-01", "item_id": "Q48469", "question": "보이저 1호는 태양계를 벗어났나?"}'
```

| 오류 코드 | 상황 |
|---|---|
| `missing_key` (503) | LLM 키가 없습니다 |
| `index_missing` (503), `index_incompatible` (503) | 항목 색인이 없거나, 색인과 임베딩 설정이 다릅니다 |
| `item_not_found` (404), `invalid_request` (422) | 잘못된 항목이나 요청입니다 |
| `conversation_busy` (409) | 같은 대화(세션 + 항목)에서 앞 질문을 처리하고 있습니다 |
| `rate_limited` (429) | 호출 한도를 넘었습니다 (배포 설정에서만) |
| `internal` (500) | 그 밖의 오류입니다. 자세한 내용은 서버 로그에만 남습니다 |

대화 기록은 서버 메모리에 (세션, 항목)별로 보관하므로 서버를 다시 시작하면 지워집니다. 알아간 빛의 기록(내 세계)은 브라우저에만 저장합니다.

---

## 6. 테스트

아래 명령은 외부 API를 호출하지 않는 회귀 테스트를 실행합니다.

```bash
python -m unittest discover -s tests -t .
node --test tests/js/*.test.mjs          # 화면의 천문 계산
```

---

## 7. 설정 파일

검색 품질에 영향을 주는 값은 코드가 아니라 설정 파일에서 바꿉니다. 비교 실험을 할 때는 설정 파일을 복사해 값만 바꾼 뒤 `VH_CONFIG`로 지정합니다.

| 섹션 | 키 | 기본값 | 의미 |
|---|---|---|---|
| `llm` | `anthropic_model` | `claude-sonnet-5-5` | 사용자에게 보이는 긴 글(답변, 편지, 마음 한 줄, 별자리 설명, 하늘 안내)을 쓰는 Claude 모델 |
| `llm` | `anthropic_fast_model` | `claude-haiku-5-5` | 짧은 JSON(검색어 추출, 후보 선별, 조건 탐색 필터, 마음 한 줄 분류)을 만드는 모델입니다. 비우면 답변 모델을 씁니다 |
| `llm` | `answer_effort` / `fast_effort` | `medium` / `low` | 답변 모델과 구조화 모델의 `output_config.effort` (`low`, `medium`, `high`, `xhigh`, `max`). 비우면 모델 기본값을 쓰고, effort를 모르는 모델에는 보내지 않습니다 |
| `llm` | `local_embedding_model` | `paraphrase-multilingual-MiniLM-L12-v2` | 서버 안에서 계산하는 임베딩 모델 |
| `chunking` | `chunk_size` / `chunk_overlap` | 1000 / 200 | 문서 청크 크기와 겹침 길이 |
| `retrieval` | `search_type` / `top_k_docs` | `similarity` / 6 | 검색 방식, 외부 문서 근거 수 |
| `retrieval` | `mmr_fetch_k` / `mmr_lambda` | 30 / 0.5 | MMR 후보 수, 다양성 가중치 |
| `collect` | `max_queries` / `max_selected` | 4 / 4 | 검색어 수, 한 번에 고를 문서 수 |
| `collect` | `max_doc_chars` | 20000 | 문서 본문 최대 길이 |
| `http` | `min_interval_sec` | 0.5 | 같은 호스트 호출 간격 |
| `limits` | `daily_cost_usd` | 3.3 | 하루(한국 시각) 추정 비용 예산입니다. 넘으면 새 LLM 호출을 막으며, `enabled`와 관계없이 적용됩니다 |
| `usage` | `enabled` / `log_path` | `true` / `data/cache/usage.jsonl` | LLM 호출마다 모델, 용도, 토큰, 소요 시간, 추정 비용을 JSONL 한 줄로 남깁니다. 프롬프트와 응답 본문은 남기지 않습니다 |
| `usage.prices.<모델>` | `input` / `output` / `cache_read` / `cache_write` | 모델별 | 100만 토큰당 달러 단가입니다. `cache_read`와 `cache_write`를 비우면 입력 단가의 0.1배와 1.25배를 씁니다. 가격표에 없는 모델은 비용 0으로 세므로 하루 예산에도 반영되지 않습니다 |
| `cache` | `enabled` / `dir` / `memory_items` | `true` / `data/cache/responses` / 512 | 서버 응답 캐시의 사용 여부, 디스크 폴더, 메모리에 두는 항목 수입니다. 비우려면 `dir` 폴더를 지웁니다 |
| `cache` | `explore_days` / `letter_days` | 7 / 7 | 조건 탐색 결과와 빛의 편지(항목별)의 보관 일수 |
| `cache` | `unfold_days` / `perspective_days` | 30 / 1 | 별자리 펼치기 설명과 마음 한 줄(문장 해시가 키)의 보관 일수 |
| `cache` | `ask_days` / `ask_live_days` | 7 / 1 | 질의응답 답변(대화 기록이 없는 첫 질문만)과, 오늘 기준 실시간 위치나 거리가 근거에 들어간 답변의 보관 일수 |
| `share` | `kakao_js_key` | 없음 | 카카오톡 공유에 쓰는 JavaScript 키입니다. `.env`의 `KAKAO_JS_KEY`가 있으면 그 값을 먼저 씁니다. 서버가 `index.html`을 내보낼 때 이 키를 `vh-kakao-key` meta에 넣고, 키가 없으면 "카카오톡으로 보내기" 버튼을 숨깁니다 |

`GET /api/health`의 `usage` 필드에는 오늘(한국 시각)의 LLM 사용량과 추정 비용이 나옵니다. 사용량 기록이 꺼져 있으면 이 필드는 비어 있습니다. 질의응답, 조건 탐색, 편지, 별자리 펼치기, 마음 한 줄 응답의 `cached` 필드가 `true`이면 캐시에서 꺼낸 응답이라는 뜻이며, 이때는 LLM을 부르지 않습니다.

### 다른 OpenAI 호환 API를 쓸 때

`config.toml`은 OpenAI 호환 엔드포인트로 채팅과 임베딩을 모두 부르는 설정입니다. `[llm]`의 `base_url`, `chat_model`, `embedding_model`을 쓰려는 엔드포인트에 맞게 바꾸고, `.env`의 `GMS_KEY`에 그 키를 넣은 뒤 `VH_CONFIG` 없이 실행하면 됩니다. 이 설정의 색인은 `data/chroma/`에 따로 쌓이므로, 임베딩 모델이 다른 배포 색인(`data/deploy/`)과 섞이지 않습니다.
