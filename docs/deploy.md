# 배포

VastHorizon을 공개 서버에 올리려는 분을 위한 안내입니다. 로컬에서 먼저 실행해 보려면 [setup.md](setup.md)를 보세요.

---

## 1. 배포 구성

| 항목 | 값 |
|---|---|
| 설정 파일 | `config.deploy.toml` (`VH_CONFIG`로 지정) |
| 답변 생성 | Claude API (`claude-sonnet-5-5`) |
| 검색용 임베딩 | 서버 안 로컬 모델 `paraphrase-multilingual-MiniLM-L12-v2` |
| 키 | `CLAUDE_API_KEY` (`ANTHROPIC_API_KEY`도 받습니다) |
| 의존성 | `requirements-deploy.txt` (`requirements.txt`에 `langchain-anthropic`, `anthropic`, `fastembed`를 더함) |
| 색인 위치 | `data/deploy/chroma/` (다른 임베딩 모델의 색인과 벡터를 섞지 않습니다) |
| 호출 한도 | 사용자(IP)별, 서버 전체 하루 한도 |

### 임베딩 모델 선택과 실측

Claude API에는 임베딩 API가 없습니다. 그런데 이 서비스는 질문할 때마다 질문을 임베딩해 근거를 찾고, 처음 묻는 천체는 문서를 모아 바로 색인합니다.
그래서 키 없이 서버 안에서 돌아가는 다국어 모델([fastembed](https://github.com/qdrant/fastembed), ONNX라 torch가 필요 없습니다)을 씁니다.

실제로 모은 문서 113청크에서 한국어 질문 4개의 정답 청크가 몇 번째로 검색되는지 비교했습니다.

| 모델 | 크기 | 정답 청크 순위 (질문 4개) | 113청크 임베딩 (노트북 CPU) | 청크당 시간 (ARM 2코어 서버) |
|---|---|---|---|---|
| `intfloat/multilingual-e5-large` | 2.2GB, 1024차원 | 1, 1, 1, 1 | 약 83초 | 5.3초 |
| `paraphrase-multilingual-mpnet-base-v2` | 1.0GB, 768차원 | 17, 1, 9, 2 | 약 17초 | 1.6초 |
| `paraphrase-multilingual-MiniLM-L12-v2` (기본) | 0.22GB, 384차원 | 12, 2, 1, 1 | 약 11초 | 0.15초 |

질문은 안드로메다 은하 중심 블랙홀의 이름, 베가가 밝기 기준별로 쓰인 이유, 궁수자리 A*의 발견, 안드로메다와 우리 은하의 충돌 시기입니다. 서버 측정은 청크 하나(1,000자, 배치 16)를 기준으로 했습니다.
품질만 보면 e5-large가 가장 정확합니다. 그러나 ARM 2코어 서버에서는 문서가 긴 천체의 첫 질문이 5분 넘게 걸렸고, 비스트리밍 요청은 Nginx의 120초 제한에 걸려 504로 끝났습니다.
그래서 근거 순위가 다소 떨어지더라도(한 질문은 12위) 공개 서버의 CPU에서는 속도가 필요하다고 판단해 MiniLM을 기본으로 정했습니다. GPU나 빠른 x86 서버에서는 e5-large를 쓰는 편이 좋습니다.

### 서버에 필요한 것

| 항목 | 권장 |
|---|---|
| 메모리 | 기본 모델(MiniLM)이면 2GB로 충분합니다. e5-large로 바꾸면 첫 색인을 만들 때 4GB를 넘기므로 8GB 이상을 두고 컨테이너 상한을 7GB로 권합니다 |
| 디스크 | 이미지 약 5.1GB + 색인과 문서 캐시 수백 MB |
| 네트워크 | 바깥으로 나가는 HTTPS (Claude API, 위키백과, Wikidata, JPL Horizons) |

---

## 2. Docker 컨테이너 하나

화면과 API를 컨테이너 하나로 띄우는 가장 단순한 방식입니다. 저장소 폴더에 `.env`를 만듭니다. 이 파일은 `.gitignore`와 `.dockerignore`에 들어 있어 GitHub에도, 이미지에도 올라가지 않습니다.

```bash
CLAUDE_API_KEY=sk-ant-...        # 필수
WIKI_CONTACT=you@example.com     # 권장: 위키백과, Wikidata User-Agent 연락처
```

```bash
git clone https://github.com/bnbong/VastHorizon.git
cd VastHorizon
docker compose up -d --build
docker compose logs -f           # 첫 실행: 색인 만들기 (몇 분) → 서버 시작
```

| 단계 | 하는 일 | 시간 (참고) |
|---|---|---|
| 이미지 만들기 | 의존성을 설치하고 `scripts/prefetch_model.py`로 임베딩 모델을 이미지에 미리 받습니다. 모델 레이어가 소스보다 앞에 있어서 소스가 바뀌어도 다시 받지 않습니다 | 처음 한 번, 수 분 |
| 첫 실행 | `scripts/deploy_init.py`가 항목 색인 424건과 관점 전환 서가 123청크를 만듭니다 | Docker Desktop(CPU 4개, 메모리 8GB)에서 약 8분, ARM 2코어 서버에서 25분 안팎 |
| 다음 실행 | 색인이 볼륨(`vh-data`)에 남아 있어 바로 시작합니다 | 수 초 |

`http://서버:8000`에서 화면이 열리고, `http://서버:8000/api/health`에서 키와 색인 상태를 볼 수 있습니다(키 값은 내보내지 않습니다).
업데이트는 `git pull` 뒤 `docker compose up -d --build`를 다시 실행하면 되며, 색인 볼륨은 그대로 남습니다.

화면만 Cloudflare Pages 같은 정적 호스팅에 둘 수도 있습니다. `python scripts/build_static.py --api <API 주소>`가 `web/`을 `dist/`로 복사하면서 API 주소를 넣고, API 서버에는 `VH_CORS_ORIGINS`로 그 화면의 출처를 허용합니다.

---

## 3. 프록시와 사용자 주소

AI 호출 한도는 사용자 주소마다 셉니다. 앱은 전달 헤더(`X-Forwarded-For`, `CF-Connecting-IP`)를 직접 읽지 않고, Uvicorn이 정한 `request.client`만 씁니다.
Uvicorn은 **믿을 수 있는 프록시에서 온 연결일 때만** `X-Forwarded-For`를 오른쪽부터 읽고, 믿을 프록시가 아닌 첫 주소를 사용자 주소로 정합니다. 믿을 프록시는 환경변수 `FORWARDED_ALLOW_IPS`(IP, CIDR, 쉼표 구분)로 정합니다.

| 공개 방식 | `FORWARDED_ALLOW_IPS` | 원본 포트 |
|---|---|---|
| 프록시 없이 바로 공개 | `""` (기본: 아무 헤더도 믿지 않음) | `8000:8000` |
| 같은 서버의 Nginx, Caddy 뒤 | 컨테이너가 보는 프록시 주소 (보통 Docker 브리지 게이트웨이) | `127.0.0.1:8000:8000` |
| Cloudflare Tunnel (`docker-compose.yml`의 주석 블록) | `172.30.0.0/24` (compose 네트워크) | 열지 않음 (`ports` 삭제) |
| Cloudflare 프록시로 원본에 바로 연결 | Cloudflare IP 대역 | 방화벽에서 Cloudflare IP 대역만 허용 |

프록시를 믿게 해 두고 원본 포트까지 바깥에 열어 두면, 누군가 프록시를 거치지 않고 원본에 바로 접속해 헤더를 속일 수 있습니다. 프록시를 쓸 때는 원본 포트를 반드시 닫습니다.

---

## 4. 개인 서버 두 대에 나누어 두는 구성

운영 중인 공개 배포는 화면과 API를 개인 서버 두 대에 나누어 둡니다. 정적 Nginx 호스트가 화면을 내보내고, API 호스트의 컨테이너가 API를 맡습니다.
Nginx 호스트가 `/api/`를 API 호스트로 프록시하므로 화면과 API는 같은 출처이고, CORS를 열 필요가 없습니다.
운영자용 구체 값(서버 주소, 경로, 네트워크 이름 등)은 저장소 밖의 내부 문서에 둡니다. 이 절의 `<API 호스트 사설 IP>`, `<배포 디렉터리>` 같은 자리표시는 자기 환경의 값으로 바꾸어 읽으면 됩니다.

| 구분 | 위치 | 내용 |
|---|---|---|
| 화면 | Nginx 호스트의 `<정적 화면 디렉터리>` | 저장소의 `web/`을 그대로 복사해 Nginx가 정적으로 내보냅니다 |
| API | API 호스트의 `<배포 디렉터리>` | `deploy/vm2/docker-compose.yml`로 띄운 컨테이너(`vm2-vasthorizon`)입니다 |
| 연결 | Nginx 호스트 → `<API 호스트 사설 IP>:8020` | 컨테이너의 8000을 API 호스트의 사설 IP와 `127.0.0.1`의 8020에만 공개합니다 |

```text
<배포 디렉터리>/
├── docker-compose.yml            # 저장소의 deploy/vm2/docker-compose.yml
├── docker-compose.override.yml   # 선택: 저장소 밖에서 관리하는 추가 네트워크 등
├── .env                          # deploy/vm2/env.template을 채운 파일
└── src/                          # 저장소 소스 (현장에서 이미지를 만들 때만 씁니다)
```

| `.env` 변수 | 설명 |
|---|---|
| `CLAUDE_API_KEY` | 필수입니다. 컨테이너 환경변수로만 넘어가고 이미지에는 들어가지 않습니다 |
| `WIKI_CONTACT` | 권장합니다. 위키백과, Wikidata User-Agent 연락처입니다 |
| `VM2_PRIVATE_IP` | 필수입니다. 비어 있으면 포트가 모든 주소에 열리므로 compose가 멈춥니다 |
| `VM1_PRIVATE_IP` | 필수입니다. `FORWARDED_ALLOW_IPS`로 들어가며, Nginx 호스트에서 온 연결만 `X-Forwarded-For`를 믿게 합니다. 틀리면 모든 사용자가 한도 하나를 함께 쓰게 됩니다 |
| `VASTHORIZON_IMAGE` | 선택입니다. 비우면 `ghcr.io/bnbong/vasthorizon:main`을 씁니다 |

수동으로 배포할 때는 소스를 API 호스트로 보내 그 자리에서 이미지를 만들고, 화면은 Nginx 호스트로 따로 보냅니다.

```bash
rsync -az --delete --exclude .git --exclude .venv --exclude data/deploy --exclude .env \
    ./ <API 호스트>:<배포 디렉터리>/src/
scp deploy/vm2/docker-compose.yml <API 호스트>:<배포 디렉터리>/docker-compose.yml
ssh <API 호스트> "cd <배포 디렉터리> && docker compose up -d --build"
rsync -az --delete web/ <Nginx 호스트>:<정적 화면 디렉터리>/
```

ARM 2코어 서버에서는 첫 색인 만들기가 오래 걸리므로 healthcheck의 `start_period`를 1800초로 늘려 두었습니다. 스왑이 없는 서버이므로 `mem_limit: 7g`로 상한을 두어, 메모리가 넘치면 서버 전체가 아니라 이 컨테이너만 다시 시작되게 했습니다.

---

## 5. GitHub Actions 파이프라인

`main`에 서비스 코드가 바뀐 커밋이 올라오면 `.github/workflows/release.yml`이 다음 순서로 실행됩니다. `docs/`처럼 서비스와 관계없는 파일만 바뀐 커밋은 배포하지 않습니다.

| 순서 | job | 하는 일 |
|---|---|---|
| 1 | `build` | ARM 러너에서 `linux/arm64` 이미지를 만들어 GHCR에 올립니다. 태그는 `sha-<커밋 7자리>`와 `main`입니다 |
| 2 | `deploy-api` | API 호스트에 `deploy/vm2/deploy.sh`와 compose 파일을 올리고, 방금 만든 이미지를 digest로 고정한 참조로 배포합니다 |
| 3 | `deploy-web` | Nginx 호스트에 `web/`을 rsync로 맞추고, `/`와 `/api/health`가 200인지 확인합니다 |

API를 화면보다 먼저 바꾸는 이유는 새 화면이 새 API에 기대는 경우가 많기 때문입니다. API 배포가 실패하면 워크플로는 화면을 건드리지 않고 멈춥니다.

`deploy.sh`는 `.env`의 `VASTHORIZON_IMAGE` 줄만 새 참조로 바꾸고 컨테이너를 교체한 다음, `/api/health`가 200이 될 때까지 최대 1000초 기다립니다. 확인이 실패하면 로그를 `deploy-failures/<UTC>.log`에 남기고 이전 이미지로 되돌립니다.

| 종료 코드 | 뜻 |
|---|---|
| 0 | 배포에 성공했습니다 |
| 1 | 배포에 실패했지만 이전 이미지로 돌아갔거나, 운영 컨테이너를 건드리기 전에 멈췄습니다 |
| 2 | 이미지 참조 형식이 올바르지 않습니다 |
| 3 | 이전 이미지도 health 확인을 통과하지 못했습니다. 서비스가 멈춘 상태이므로 바로 조치해야 합니다 |

저장소 Settings의 `production` environment에는 아래 값을 등록합니다. 서버 경로는 저장소에 적지 않고 variable로 받으며, 비어 있거나 절대 경로가 아니면 해당 job이 첫 단계에서 멈춥니다.

| 이름 | 종류 | 값 |
|---|---|---|
| `VM2_DEPLOY_DIR`, `VM1_WEB_DIR` | variable | API 호스트의 배포 디렉터리, Nginx 호스트의 정적 화면 디렉터리 (절대 경로) |
| `VM2_HOST`, `VM1_HOST` | secret | 각 호스트의 공인 IP 주소 |
| `VM2_SSH_PRIVATE_KEY`, `VM1_SSH_PRIVATE_KEY` | secret | 각 호스트의 `ubuntu` 계정에 접속할 배포용 SSH 개인 키 |
| `VM2_SSH_KNOWN_HOSTS`, `VM1_SSH_KNOWN_HOSTS` | secret | `ssh-keyscan -H <공인 IP>`로 얻은 host key |

API 호스트는 GHCR에 로그인하지 않고 이미지를 받으므로, 첫 `build`가 끝나면 GitHub Packages에서 `vasthorizon` 패키지를 **public**으로 바꿔야 합니다.
되돌릴 때는 Actions 탭에서 워크플로를 `workflow_dispatch`로 실행하고 `image_ref`에 `ghcr.io/bnbong/vasthorizon:sha-1a2b3c4` 같은 태그를 넣습니다. 그러면 `build`를 건너뛰고 API와 화면이 함께 그 커밋으로 돌아갑니다.

---

## 6. 설정 바꾸기 (`config.deploy.toml`)

| 설정 | 기본 | 바꾸는 경우 |
|---|---|---|
| `llm.anthropic_model` | `claude-sonnet-5-5` | 비용을 줄이려면 `claude-haiku-5-5` |
| `llm.max_tokens` | 2048 | 답이 잘리면 늘립니다 |
| `llm.local_embedding_model` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | GPU나 빠른 x86 서버에서는 `intfloat/multilingual-e5-large` |
| `llm.local_embedding_batch_size` | 16 | 키우면 색인이 조금 빨라지지만 메모리를 더 씁니다. 결과 벡터는 같으므로 색인을 다시 만들 필요는 없습니다 |
| `limits.per_ip_per_minute` / `per_ip_per_day` | 6 / 60 | 한 사용자가 1분, 하루에 보낼 수 있는 질문 수 |
| `limits.global_per_day` | 1500 | 서버 전체 하루 질문 수 (개인 키의 하루 비용 상한 역할) |
| `limits.daily_cost_usd` | 3.3 | 하루 추정 비용 예산(달러)입니다. 월 $100을 30일로 나눈 값에 맞췄습니다 |
| `server.cors_origins` | 없음 | 화면을 다른 주소에 둘 때 허용할 출처 (환경변수 `VH_CORS_ORIGINS`로도 바꿉니다) |

한도는 실제로 LLM을 부르는 요청만 셉니다. 하늘 계산(`guide=false`), 천체 목록, 내 세계 보기는 세지 않으므로 예산을 다 써도 하늘은 그대로 쓸 수 있습니다.
한도는 서버 메모리에만 두므로 다시 시작하면 처음부터 셉니다. 더 엄격하게 막으려면 Anthropic 콘솔에서 키의 월 사용 한도도 함께 걸어 두기를 권합니다.

월 $100을 상한으로 삼는다면 `daily_cost_usd = 3.3`으로 둡니다. 이 값은 앱이 기록한 추정 비용 기준이므로 실제 청구액과 다를 수 있습니다. 따라서 Anthropic Console에서 해당 키의 월 지출 한도도 함께 설정하기를 권합니다.

항목 색인은 카탈로그 내용의 해시(`catalog_hash`)를 함께 기록하며, `deploy_init`은 해시가 다르면 항목 색인을 자동으로 다시 만듭니다. 보강 데이터가 추가된 뒤 처음 배포하면 424건을 다시 색인하는데, MiniLM 모델에서는 1~2분이 걸립니다. 강제로 다시 만들려면 `--rebuild`를 붙입니다.

임베딩 모델을 바꾸면 `deploy_init`이 다음 실행 때 이를 알아채고 항목, 관점 전환 서가, 질문하며 모은 문서의 세 색인을 모두 새 모델로 다시 만듭니다. 문서는 캐시(`data/deploy/cache`)에서 다시 색인하므로 새로 받지 않습니다.
세 색인 모두 임시 컬렉션에 새로 만들고 검증한 뒤에 바꿔 넣습니다. 중간에 실패하면 기존 색인은 그대로 남고, `deploy_init`은 실패 코드로 끝나 서버를 띄우지 않습니다.

---

## 7. 확인한 것

| 확인 | 결과 |
|---|---|
| 컨테이너 첫 실행 | 색인을 만든 뒤 474초에 서버가 시작했습니다. 베가 첫 질문은 문서 수집과 색인을 포함해 67초 만에 근거 인용 답변을 돌려주었습니다 |
| Docker 이미지 크기 | 5.1GB입니다. 처음 만든 이미지는 모델 폴더의 권한을 바꾸는 단계가 모델을 한 번 더 복사해 12.3GB였으므로, 실행 사용자로 모델을 받도록 바꿨습니다 |
| 호출 한도 | 1분에 6번째 POST에서 429와 `Retry-After: 60`이 돌아오고, 조회(GET)는 200입니다 |
| 전달 헤더로 한도 우회 | `X-Forwarded-For` 첫 값만 바꾸던 재현이 4회 모두 200에서 200, 200, 429, 429로 바뀌었습니다 (`ProxyTrustTest`) |
| 첫 실행의 메모리 (ARM 2코어 서버) | fastembed 기본 배치(256)로 e5-large 서가 색인을 만들 때 메모리가 6.4GB까지 올라, 상한 4GB에서는 프로세스가 죽었습니다. 이제 배치 16으로 나눠 계산합니다 |
| 첫 질문의 스트림 끊김 | 공개 배포에서 임베딩과 답변 생성이 이어지는 동안 바이트가 나가지 않아 136초쯤 연결이 끊겼습니다. 이제 15초마다 SSE 주석 줄(`: keepalive`)을 보냅니다 |
