# 부록 B. 배포 안내 (Claude API + 로컬 임베딩)

VastHorizon을 공개 서버에 올리려는 분을 위한 안내입니다.
과제 제출 환경(SSAFY GMS)은 [부록 A](appendix_a_setup_guide.md)를 그대로 따르고, 이 문서는 개인 Claude API 키로 배포할 때만 씁니다.

---

## 1. 두 환경의 차이

| 항목 | 과제 제출 환경 | 배포 환경 |
|---|---|---|
| 설정 파일 | `config.toml` (기본) | `config.deploy.toml` (`VH_CONFIG`로 지정) |
| 답변 생성 | SSAFY GMS의 GPT (`gpt-6-luna`) | Claude API (`claude-sonnet-5-5`) |
| 검색용 임베딩 | GMS `text-embedding-3-small` | 서버 안 로컬 모델 `intfloat/multilingual-e5-large` |
| 키 | `GMS_KEY` | `CLAUDE_API_KEY` (`ANTHROPIC_API_KEY`도 받습니다) |
| 의존성 | `requirements.txt` | `requirements-deploy.txt` (위에 `langchain-anthropic`, `anthropic`, `fastembed`를 더함) |
| 색인 위치 | `data/chroma/` | `data/deploy/chroma/` (임베딩 모델이 달라 벡터를 섞지 않습니다) |
| 호출 한도 | 없음 | 사용자(IP)별, 서버 전체 하루 한도 |

두 환경은 코드가 같고 설정만 다릅니다. 배포 전용 패키지는 그 설정을 쓸 때만 불러오므로, 과제 환경에는 설치하지 않아도 됩니다.

### 왜 로컬 임베딩인가

Claude API에는 임베딩 API가 없습니다. 그런데 이 서비스는 질문할 때마다 질문을 임베딩해 근거를 찾고, 처음 묻는 천체는 문서를 모아 바로 색인합니다. 그래서 키 없이 서버 안에서 돌아가는 다국어 모델([fastembed](https://github.com/qdrant/fastembed), ONNX라 torch가 필요 없습니다)을 씁니다.

실제로 모은 문서 113청크에서 한국어 질문 4개의 정답 청크가 몇 번째로 검색되는지 비교했습니다.

| 모델 | 크기 | 정답 청크 순위 (질문 4개) | 113청크 임베딩 시간 |
|---|---|---|---|
| `intfloat/multilingual-e5-large` (기본) | 2.2GB, 1024차원 | 1, 1, 1, 1 | 약 83초 |
| `paraphrase-multilingual-mpnet-base-v2` | 1.0GB, 768차원 | 17, 1, 9, 2 | 약 17초 |
| `paraphrase-multilingual-MiniLM-L12-v2` | 0.22GB, 384차원 | 12, 2, 1, 1 | 약 11초 |

질문: 안드로메다 은하 중심 블랙홀의 이름, 베가가 밝기 기준별로 쓰인 이유, 궁수자리 A*의 발견, 안드로메다와 우리 은하의 충돌 시기 (Windows 노트북 CPU 기준).
근거를 정확히 찾는 것이 이 서비스의 핵심이라 e5-large를 기본으로 정했습니다. 서버 메모리가 작으면 MiniLM으로 바꿀 수 있습니다 (5절).

---

## 2. 배포 방식 고르기

| 방식 | 구성 | 알맞은 경우 |
|---|---|---|
| **A. 컨테이너 하나** (권장) | 화면과 API를 Docker 컨테이너 하나로 | 개인 서버(BNGdrasil 등), 가장 단순합니다 |
| **B. 화면 분리** | 화면은 Cloudflare Pages, API는 개인 서버의 컨테이너 | 화면을 CDN으로 빠르게 내보내고 싶을 때 |

Cloudflare Pages만으로는 배포할 수 없습니다. Pages는 정적 파일만 내보내므로 FastAPI 서버, Chroma 색인, 임베딩 모델을 돌릴 수 없습니다. 방식 B에서도 API 서버는 따로 있어야 합니다.

### 서버에 필요한 것

| 항목 | 권장 |
|---|---|
| 메모리 | 4GB 이상 (임베딩 모델이 약 2.5GB를 씁니다. MiniLM이면 1GB면 충분합니다) |
| 디스크 | 이미지 약 5.1GB (임베딩 모델 2.25GB, 파이썬 패키지 약 1GB) + 색인과 문서 캐시 수백 MB |
| 네트워크 | 바깥으로 나가는 HTTPS (Claude API, 위키백과, Wikidata, JPL Horizons) |

---

## 3. 방식 A: 컨테이너 하나 (BNGdrasil 등)

### 3-1. 키 준비

저장소 폴더에 `.env`를 만듭니다. 이 파일은 `.gitignore`와 `.dockerignore`에 들어 있어 GitHub에도, 이미지에도 올라가지 않습니다.

```bash
CLAUDE_API_KEY=sk-ant-...        # 필수
WIKI_CONTACT=you@example.com     # 권장: 위키백과, Wikidata User-Agent 연락처
```

### 3-2. 실행

```bash
git clone https://github.com/bnbong/VastHorizon.git
cd VastHorizon
# .env 작성 (위)
docker compose up -d --build
docker compose logs -f           # 첫 실행: 색인 만들기 (몇 분) → 서버 시작
```

| 단계 | 하는 일 | 시간 (참고) |
|---|---|---|
| 이미지 만들기 | 의존성 설치, 임베딩 모델을 이미지에 미리 받기 | 처음 한 번, 네트워크에 따라 수 분 |
| 첫 실행 | `scripts/deploy_init.py`: 항목 색인 424건, 관점 전환 서가 123청크 | Docker Desktop(CPU 4개, 메모리 8GB)에서 약 8분, 노트북에서 직접 실행하면 2~3분 |
| 다음 실행 | 색인이 볼륨(`vh-data`)에 남아 있어 바로 시작 | 수 초 |

`http://서버:8000`에서 화면이 열리고, `http://서버:8000/api/health`에서 키와 색인 상태를 볼 수 있습니다(키 값은 내보내지 않습니다).
문서 색인은 비어 있는 채로 시작합니다. 어떤 천체에 처음 질문하면 그 천체의 문서를 모아 색인하므로 첫 답은 30초~1분쯤 걸리고(컨테이너에서 베가 첫 질문 67초), 그다음부터는 빨라집니다.

### 3-3. 사용자 주소와 프록시 (AI 호출 한도의 기준)

AI 호출 한도는 사용자 주소마다 셉니다. 이 주소는 앱이 전달 헤더(`X-Forwarded-For`, `CF-Connecting-IP`)를 직접 읽어 정하지 않습니다.
Uvicorn이 **믿을 수 있는 프록시에서 온 연결일 때만** `X-Forwarded-For`를 오른쪽부터 읽고, 믿을 프록시가 아닌 첫 주소를 사용자 주소로 정합니다. 앱은 그 값(`request.client`)만 씁니다.
믿을 프록시는 환경변수 `FORWARDED_ALLOW_IPS`(IP, CIDR, 쉼표 구분)로 정합니다. 사용자가 헤더 맨 앞에 다른 주소를 끼워 넣어도 오른쪽부터 읽으므로 고를 수 없고, 믿지 않는 연결의 헤더는 통째로 무시합니다.

| 공개 방식 | `FORWARDED_ALLOW_IPS` | 원본 포트 |
|---|---|---|
| 프록시 없이 바로 공개 | `""` (기본: 아무 헤더도 믿지 않음) | `8000:8000` |
| 같은 서버의 Nginx, Caddy 뒤 | 컨테이너가 보는 프록시 주소 (보통 Docker 브리지 게이트웨이, `docker network inspect`로 확인) | `127.0.0.1:8000:8000` (바깥에서 원본에 바로 닿지 않게) |
| Cloudflare Tunnel (`docker-compose.yml`의 주석 블록) | `172.30.0.0/24` (compose 네트워크, 곧 cloudflared 컨테이너만) | 열지 않음 (`ports` 삭제) |
| Cloudflare 프록시(주황 구름)로 원본에 바로 연결 | Cloudflare IP 대역 | 방화벽에서 Cloudflare IP 대역만 허용 |

프록시를 믿게 해 두고 원본 포트까지 바깥에 열어 두면, 누군가 프록시를 거치지 않고 원본에 바로 접속해 헤더를 속일 수 있습니다. 프록시를 쓸 때는 원본 포트를 꼭 닫습니다.
Docker의 포트 공개는 바깥 연결을 브리지 게이트웨이 주소로 바꿔 보이게 하는 경우가 있으므로, 게이트웨이 주소를 믿게 할 때는 더욱 `127.0.0.1`에만 공개합니다.

### 3-4. 업데이트

```bash
git pull
docker compose up -d --build     # 색인 볼륨은 그대로 남습니다
```

---

## 4. 방식 B: 화면은 Cloudflare Pages, API는 개인 서버

1. API 서버는 3절대로 띄웁니다. `docker-compose.yml`의 `VH_CORS_ORIGINS`에 Pages 주소를 적습니다 (여러 개면 쉼표로).
   ```yaml
   VH_CORS_ORIGINS: "https://vasthorizon.pages.dev"
   ```
2. Cloudflare Pages에서 GitHub 저장소를 연결하고 다음처럼 설정합니다.

   | 항목 | 값 |
   |---|---|
   | 빌드 명령 | `python scripts/build_static.py` |
   | 출력 폴더 | `dist` |
   | 환경변수 | `VH_API_BASE` = API 서버 주소 (예: `https://api.example.com`) |

   `build_static.py`는 표준 라이브러리만 쓰므로 Pages 빌드 환경에서 의존성 설치가 필요 없습니다. `web/`을 `dist/`로 복사하고, `index.html`의 `<meta name="vh-api-base">`에 API 주소를 넣습니다.
3. 화면의 별, 사진, 3D 모델 같은 정적 데이터(`web/data`, 약 11MB)는 Pages에서 내보내고, 질문과 답만 API 서버로 갑니다.

로컬에서 미리 확인하려면 `python scripts/build_static.py --api http://localhost:8000` 뒤 `dist/`를 아무 정적 서버로 열면 됩니다.

---

## 5. 설정 바꾸기 (`config.deploy.toml`)

| 설정 | 기본 | 바꾸는 경우 |
|---|---|---|
| `llm.anthropic_model` | `claude-sonnet-5-5` | 비용을 줄이려면 `claude-haiku-5-5` |
| `llm.max_tokens` | 2048 | 답이 잘리면 늘립니다 |
| `llm.local_embedding_model` | `intfloat/multilingual-e5-large` | 메모리가 작으면 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. 바꾼 뒤 컨테이너를 다시 띄우면 됩니다 (아래) |
| `limits.per_ip_per_minute` | 6 | 한 사용자가 1분에 보낼 수 있는 질문 수 |
| `limits.per_ip_per_day` | 60 | 한 사용자의 하루 질문 수 |
| `limits.global_per_day` | 1500 | 서버 전체 하루 질문 수 (개인 키의 하루 비용 상한 역할) |
| 환경변수 `FORWARDED_ALLOW_IPS` | `""` | 믿을 프록시 주소 (3-3) |
| `server.cors_origins` | 없음 | 환경변수 `VH_CORS_ORIGINS`로도 바꿀 수 있습니다 (4절) |

한도는 실제로 LLM을 부르는 요청(질문, 조건 탐색, 빛의 편지, 마음 한 줄, 별자리 설명, 하늘 안내 받기)만 셉니다. 시각을 바꿀 때의 하늘 계산(`/api/sky`의 `guide=false`), 천체 목록, 내 세상 보기 같은 요청은 세지 않으므로, 예산을 다 써도 하늘은 그대로 쓸 수 있습니다. 형식이 잘못된 요청도 세지 않습니다.
한도를 넘으면 429 응답과 함께 "1분쯤 뒤에 다시 물어봐 주세요", "내일 다시 찾아 주세요" 같은 안내가 화면에 보입니다.
### 임베딩 모델을 바꿀 때

색인 세 개(항목, 관점 전환 서가, 질문하며 모은 문서)는 만들 때의 임베딩 모델을 기록해 둡니다. 다른 모델의 벡터는 함께 쓸 수 없습니다.
`scripts/deploy_init.py`는 실행할 때마다 이 기록을 지금 설정과 비교해, 다르면 세 색인을 모두 새 모델로 다시 만듭니다. 모델을 바꾼 뒤 컨테이너를 다시 띄우기만 하면 됩니다 (`docker compose up -d --build`).
직접 실행할 때는 `python -m scripts.deploy_init --rebuild`로 강제로 다시 만들 수도 있습니다.

| 색인 | 다시 만드는 방법 |
|---|---|
| 항목 (424건) | `data/items.json`에서 |
| 관점 전환 서가 | 서가 문서 캐시에서 (없으면 위키백과에서 다시 받음) |
| 질문하며 모은 문서 | 문서 캐시(`data/deploy/cache`)에서. 이미 질문했던 천체의 문서를 다시 받지 않습니다 |

세 색인 모두 임시 컬렉션에 새로 만들고 검증한 뒤에 바꿔 넣습니다. 중간에 실패하면 기존 색인은 그대로 남고, `deploy_init`은 실패 코드로 끝나 서버를 띄우지 않습니다(로그에 이유가 남습니다).

한도는 서버 메모리에만 두므로 다시 시작하면 처음부터 셉니다. 더 엄격하게 막으려면 Anthropic 콘솔에서 키의 월 사용 한도도 함께 걸어 두는 것을 권합니다.

---

## 6. 컨테이너 없이 실행해 보기

```bash
pip install -r requirements-deploy.txt
export VH_CONFIG=config.deploy.toml          # Windows PowerShell: $env:VH_CONFIG="config.deploy.toml"
python -m scripts.check_env --llm            # Claude 채팅 1회, 로컬 임베딩 1회 (키 값은 출력하지 않습니다)
python -m scripts.deploy_init                # 색인 만들기 (data/deploy/)
uvicorn vasthorizon.api.app:app --port 8000
```

---

## 7. 확인한 것

| 확인 | 결과 |
|---|---|
| 과제 환경이 그대로인가 | `config.toml`은 GMS, 한도와 CORS 없음 (테스트 `test_submission_config_unchanged`). 배포 패키지가 없는 Python 3.11 환경에서도 전체 테스트 통과 (배포 전용 4개는 건너뜀) |
| Claude 연결 | `check_env --llm`: Claude 채팅 응답, 로컬 임베딩 1024차원 |
| 실제 질문 | "베가는 왜 밝기의 기준별로 쓰였나?": 문서 수집, 로컬 색인, 근거 인용 답변, 인용 번호 검증 통과 |
| 실제 질문 | "안드로메다 은하 가운데에 있는 블랙홀 이름은 뭐야?": "M31*"과 질량을 근거(위키백과 「안드로메다 은하」)와 함께 답함 |
| Claude 응답 형식 | Claude는 답을 내용 블록 목록으로 주고, JSON을 낸 뒤 스스로 고친 JSON을 한 번 더 내기도 합니다. 글만 모으고 마지막 JSON을 쓰도록 맞췄습니다 (테스트 `test_reply_text`, `test_parse_json_reply_takes_self_corrected_last_object`) |
| 호출 한도, CORS | 1분 한도 초과 시 429와 `Retry-After`, 허용한 출처만 CORS 헤더 (테스트 `tests/test_deploy.py`) |
| 코드 리뷰 반영: 전달 헤더로 한도 우회 | 신뢰 프록시를 거치며 `X-Forwarded-For` 첫 값만 바꾸던 재현(4회 모두 200)이 이제 200, 200, 429, 429. 신뢰하지 않는 접속자의 `X-Forwarded-For`, `CF-Connecting-IP`는 무시, 여러 프록시 체인은 오른쪽부터, 실제 사용자는 따로 셈 (`ProxyTrustTest`, 배포와 같은 Uvicorn 미들웨어로 확인) |
| 코드 리뷰 반영: 모델 변경 때 문서 색인 | 이전 모델로 만든 항목, 서가, 문서 색인이 새 모델에서 모두 다시 만들어짐(문서는 캐시에서). 문서 재구축이 실패하면 기존 색인을 남기고 실패 코드 1 (`DeployInitTest`) |
| 코드 리뷰 반영: 하늘 계산은 예산 밖 | `guide=false` 하늘 계산 5회 뒤에도 질문 2회 가능, 예산을 다 쓴 뒤에도 하늘 계산은 200, 하늘 안내(`guide=true`)는 LLM을 부르기 전에 429. 형식 오류 요청도 세지 않음 (`AiBudgetTest`) |
| 정적 화면 빌드 | `dist/index.html`에 API 주소가 들어가고, 잘못된 주소는 거부 |
| Docker 이미지 | 빌드 성공, 5.1GB. 처음 만든 이미지는 모델 폴더의 권한을 바꾸는 단계가 모델을 한 번 더 복사해 12.3GB였습니다. 실행 사용자를 먼저 만들고 그 사용자로 모델을 받도록 바꿨습니다 |
| 컨테이너 실행 | 첫 실행에 색인을 만든 뒤 서버 시작 (474초), `/api/health` 준비 완료(항목 색인 424건), 실제 질문에 근거 인용 답변 (67초) |
| 컨테이너 호출 한도 | 1분에 6번째 POST에서 429와 `Retry-After: 60`, 조회(GET)는 200 |
| 의존성 고정 | `langchain-anthropic` 최신판은 `langchain-core` 1.6.10 이상을 요구해 `requirements.txt`의 1.6.0 고정과 충돌했습니다. 1.6.0과 맞는 1.7.0으로 고정했습니다 |
| 한국어 출력 | Claude가 검색어를 일본어로 뽑거나("見かけの等級") 답에 한자를 섞는("1950년代") 일이 있어, 공통 역할 문장에 한글로만 쓰라는 규칙을 더했습니다. 이후 검색어 추출 3회 모두 한국어 JSON 하나 |
