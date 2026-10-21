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

## 7. 테스트

외부 API를 호출하지 않는 회귀 테스트다.

```bash
python -m unittest discover -s tests -t .
```

---

## 8. 설정 파일

검색 품질에 영향을 주는 값은 `config.toml`에서 바꾼다.

| 섹션 | 키 | 기본값 | 의미 |
|---|---|---|---|
| `llm` | `chat_model` | `gpt-5.4-nano` | 답변 · 프롬프트용 GPT 모델 |
| `llm` | `embedding_model` | `text-embedding-3-small` | 임베딩 모델 |
| `chunking` | `chunk_size` / `chunk_overlap` | 1000 / 200 | 문서 청크 크기 · 중복 길이 |
| `retrieval` | `search_type` | `similarity` | `similarity` 또는 `mmr` |
| `retrieval` | `top_k_docs` | 6 | 외부 문서 근거 수 |
| `retrieval` | `mmr_fetch_k` / `mmr_lambda` | 30 / 0.5 | MMR 후보 수 · 다양성 가중치 |
| `http` | `min_interval_sec` | 0.5 | 같은 호스트 호출 간격 |

비교 실험은 설정 파일을 복사해 값만 바꾸고 지정한다.

```bash
cp config.toml config.chunk500.toml   # chunk_size = 500 으로 수정
VH_CONFIG=config.chunk500.toml python -m scripts.check_env
```
