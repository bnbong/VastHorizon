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
| 메모리 | 8GB 이상 (e5-large는 첫 색인을 만들 때 4GB를 넘깁니다. 컨테이너 상한은 7GB를 권합니다. MiniLM이면 2GB면 충분합니다) |
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
| 이미지 만들기 | 의존성 설치, `scripts/prefetch_model.py`로 임베딩 모델을 이미지에 미리 받기. 모델 레이어가 소스보다 앞에 있어서 소스가 바뀌어도 다시 받지 않습니다 | 처음 한 번, 네트워크에 따라 수 분 |
| 첫 실행 | `scripts/deploy_init.py`: 항목 색인 424건, 관점 전환 서가 123청크 | Docker Desktop(CPU 4개, 메모리 8GB)에서 약 8분, 노트북에서 직접 실행하면 2~3분. VM2(ARM 2코어, 배치 16)에서는 항목 색인 약 20분, 전체 25분 안팎 |
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

### 3-5. BNGdrasil(VM1 + VM2) 구성

BNGdrasil에서는 화면과 API를 두 서버에 나누어 둡니다. 화면은 VM1 Nginx가 정적 파일로 내보내고, API는 VM2의 컨테이너가 맡습니다.
VM1 Nginx가 `vasthorizon.bnbong.com`의 `/api/`를 VM2로 프록시하므로 화면과 API는 같은 출처이고, CORS를 열 필요가 없습니다.

| 구분 | 위치 | 내용 |
|---|---|---|
| 화면 | VM1 `/opt/bnbong/vasthorizon/web` | 저장소의 `web/`을 그대로 복사합니다. Nginx가 정적으로 내보냅니다 |
| API | VM2 `/opt/bnbong/vasthorizon` | `deploy/vm2/docker-compose.yml`로 띄운 컨테이너(`vm2-vasthorizon`)입니다 |
| 연결 | VM1 Nginx → `10.0.1.60:8020` | 컨테이너의 8000을 VM2 사설 IP와 `127.0.0.1`의 8020에만 공개합니다 |

VM2에는 다음처럼 파일을 둡니다. compose 프로젝트 이름은 `vasthorizon`입니다(compose 파일의 `name:`).

```text
/opt/bnbong/vasthorizon/
├── docker-compose.yml   # 저장소의 deploy/vm2/docker-compose.yml
├── .env                 # deploy/vm2/env.template을 채운 파일
└── src/                 # 저장소 소스 (현장에서 이미지를 만들 때만 씁니다)
```

**`.env` 준비.** `deploy/vm2/env.template`을 VM2의 `/opt/bnbong/vasthorizon/.env`로 복사하고 값을 채웁니다.

| 변수 | 값 | 설명 |
|---|---|---|
| `CLAUDE_API_KEY` | `sk-ant-...` | 필수입니다. 컨테이너 환경변수로만 넘어가고 이미지에는 들어가지 않습니다 |
| `WIKI_CONTACT` | 메일 주소 | 권장합니다. 위키백과, Wikidata User-Agent 연락처입니다 |
| `VM2_PRIVATE_IP` | `10.0.1.60` | 필수입니다. 비어 있으면 compose가 멈춥니다. 비어 있는 채로 띄우면 포트가 모든 주소에 열리기 때문입니다 |
| `VM1_PRIVATE_IP` | `10.0.1.133` | 필수입니다. `FORWARDED_ALLOW_IPS`로 들어가며, VM1 Nginx에서 온 연결만 `X-Forwarded-For`를 믿게 합니다 |
| `VASTHORIZON_IMAGE` | 비워 둠 | 선택입니다. 비우면 `ghcr.io/bnbong/vasthorizon:main`을 씁니다 |

VM1 Nginx는 `X-Forwarded-For`에 `CF-Connecting-IP` 값 하나를 넣어 보내므로, 3-3절의 규칙에 따라 그 값이 AI 호출 한도의 사용자 주소가 됩니다.
`VM1_PRIVATE_IP`가 틀리면 모든 사용자가 VM1 주소 하나로 묶여 한도를 함께 쓰게 됩니다.

**수동 배포.** 개발 PC에서 소스를 VM2로 보낸 뒤, VM2에서 이미지를 만들어 띄웁니다. GHCR 이미지를 쓸 수 있으면 `--build` 대신 `docker compose pull`과 `docker compose up -d --no-build`를 씁니다.

```bash
# 개발 PC: 소스와 compose 파일을 VM2로 보낸다 (.env는 VM2에서 따로 관리한다)
rsync -az --delete --exclude .git --exclude .venv --exclude data/deploy --exclude .env \
    ./ vm2:/opt/bnbong/vasthorizon/src/
scp deploy/vm2/docker-compose.yml vm2:/opt/bnbong/vasthorizon/docker-compose.yml

# VM2: 이미지를 만들고 컨테이너를 바꾼다 (색인 볼륨은 그대로 남는다)
cd /opt/bnbong/vasthorizon
docker compose up -d --build
docker compose logs -f           # 첫 실행: 색인 만들기 → 서버 시작
```

저장소 폴더에서 바로 확인하려면 `docker compose -f deploy/vm2/docker-compose.yml up -d --build`처럼 실행할 수 있습니다. 이때 `.env`와 `src/`는 compose 파일과 같은 `deploy/vm2/` 아래에 있어야 합니다.

화면은 VM1로 따로 보냅니다.

```bash
rsync -az --delete web/ vm1:/opt/bnbong/vasthorizon/web/
```

**확인.** VM2에서 다음 명령으로 키와 색인 상태를 봅니다.

```bash
curl http://127.0.0.1:8020/api/health
docker inspect --format '{{.State.Health.Status}}' vm2-vasthorizon
```

VM2는 2코어 ARM 서버이므로 첫 실행의 색인 만들기가 Docker Desktop보다 오래 걸립니다. 그래서 compose의 healthcheck는 `start_period`를 1800초로 늘려 두었습니다 (실측: VM2 ARM 2코어, 배치 16에서 항목 색인 약 20분, 전체 25분 안팎). 그동안은 상태가 `starting`으로 보여도 정상입니다.
VM2에는 스왑이 없으므로 `mem_limit: 7g`로 상한을 두었습니다. e5-large로 첫 색인을 만들 때 4g에서는 OOM으로 프로세스가 죽었기 때문입니다. 메모리가 넘치면 서버 전체가 아니라 이 컨테이너만 다시 시작됩니다.

### 3-6. GitHub Actions로 자동 배포

3-5절의 수동 배포는 `.github/workflows/release.yml`로 자동화되어 있습니다. `main`에 서비스 코드가 바뀐 커밋이 올라오면 워크플로가 다음 순서로 실행됩니다. `docs/`처럼 서비스와 관계없는 파일만 바뀐 커밋은 배포하지 않습니다.

| 순서 | job | 하는 일 |
|---|---|---|
| 1 | `build` | ARM 러너(`ubuntu-24.04-arm`)에서 `linux/arm64` 이미지를 만들어 GHCR에 올립니다. 태그는 `ghcr.io/bnbong/vasthorizon:sha-<커밋 7자리>`와 `:main` 두 가지입니다 |
| 2 | `deploy-api` | VM2에 `deploy/vm2/deploy.sh`와 `deploy/vm2/docker-compose.yml`을 올리고, 방금 만든 이미지를 digest로 고정한 참조(`@sha256:...`)로 배포합니다 |
| 3 | `deploy-web` | VM1의 `/opt/bnbong/vasthorizon/web/`에 `web/`을 rsync로 맞추고, VM1 안에서 Cloudflare를 거치지 않는 경로로 `/`와 `/api/health`가 200인지 확인합니다 |

API를 화면보다 먼저 바꾸는 이유는 새 화면이 새 API에 기대는 경우가 많기 때문입니다. VM2 배포가 실패하면 워크플로는 VM1의 화면을 건드리지 않고 멈춥니다.
이미지에는 임베딩 모델(약 2.2GB)이 들어 있어서, 빌드 캐시가 비어 있으면 `build`만 수십 분이 걸릴 수 있습니다.

**VM2의 `deploy.sh`.** VM2 쪽 교체는 `/opt/bnbong/vasthorizon/deploy.sh`가 맡습니다. 이 스크립트는 `.env`에서 `VASTHORIZON_IMAGE` 줄만 새 참조로 바꾸고 `docker compose up -d --no-build`로 컨테이너를 교체한 다음, `http://127.0.0.1:8020/api/health`가 200이 될 때까지 기다립니다. 기본 대기 시간은 1000초입니다. 첫 기동이나 임베딩 모델을 바꾼 뒤에는 색인을 다시 만드느라 15분 가까이 걸리기 때문입니다.
health 확인이 실패하면 스크립트는 로그를 `deploy-failures/<UTC>.log`에 남기고, `.env`를 되돌려 이전 이미지로 다시 띄웁니다. 성공한 배포는 `releases.log`에 한 줄씩 기록됩니다. 종료 코드는 다음과 같습니다.

| 종료 코드 | 뜻 |
|---|---|
| 0 | 배포에 성공했습니다 |
| 1 | 배포에 실패했지만 이전 이미지로 돌아갔거나, 운영 컨테이너를 건드리기 전에 멈췄습니다 |
| 2 | 이미지 참조 형식이 올바르지 않습니다 |
| 3 | 이전 이미지도 health 확인을 통과하지 못했습니다. 서비스가 멈춘 상태이므로 바로 조치해야 합니다 |

`deploy.sh`를 VM2에 미리 설치할 필요는 없습니다. `deploy-api`가 실행될 때마다 저장소의 `deploy.sh`와 compose 파일을 먼저 `/opt/bnbong/vasthorizon/`에 올리고 나서 실행하므로, 첫 실행에서 자동으로 놓입니다. `.env`는 워크플로가 올리지 않으며, 3-5절대로 VM2에서 직접 관리합니다.
워크플로를 거치지 않고 VM2에서 직접 실행할 수도 있습니다. 이때도 `ubuntu` 계정으로 실행하며 `sudo`는 필요 없습니다.

```bash
bash /opt/bnbong/vasthorizon/deploy.sh ghcr.io/bnbong/vasthorizon:sha-1a2b3c4
```

**GitHub 설정.** 저장소의 Settings에서 `production` environment를 만들고, 아래 secret 6개를 그 environment에 등록합니다. 두 배포 job이 모두 `environment: production`을 쓰므로, 저장소 전체 secret이 아니라 environment secret으로 둡니다.

| secret | 값 |
|---|---|
| `VM2_HOST` | VM2의 공인 IP 주소 |
| `VM2_SSH_PRIVATE_KEY` | VM2의 `ubuntu` 계정에 접속할 배포용 SSH 개인 키의 전체 내용 |
| `VM2_SSH_KNOWN_HOSTS` | `ssh-keyscan -H <VM2 공인 IP>`로 얻은 VM2의 host key |
| `VM1_HOST` | VM1의 공인 IP 주소 |
| `VM1_SSH_PRIVATE_KEY` | VM1의 `ubuntu` 계정에 접속할 배포용 SSH 개인 키의 전체 내용 |
| `VM1_SSH_KNOWN_HOSTS` | `ssh-keyscan -H <VM1 공인 IP>`로 얻은 VM1의 host key |

GHCR에 올리는 데에는 워크플로의 `GITHUB_TOKEN`을 쓰므로 따로 등록할 secret이 없습니다.
다만 VM2는 GHCR에 로그인하지 않고 이미지를 받습니다. 그래서 첫 `build`가 끝나면 GitHub의 Packages에서 `vasthorizon` 패키지의 공개 범위를 **public**으로 바꿔야 합니다. 패키지가 private이면 `deploy.sh`의 `docker pull`이 실패하고, 운영 컨테이너는 그대로 남은 채 종료 코드 1로 끝납니다.

**되돌리기.** Actions 탭에서 이 워크플로를 `workflow_dispatch`로 실행하고, `image_ref`에 되돌아갈 커밋의 태그를 넣습니다.

```text
ghcr.io/bnbong/vasthorizon:sha-1a2b3c4
```

`image_ref`를 채우면 `build`를 건너뛰고 그 이미지로 VM2를 배포합니다. 화면도 태그에 적힌 커밋의 `web/`으로 맞추므로, API와 화면이 함께 그 커밋으로 돌아갑니다. 커밋별 태그는 각 실행의 Summary나 GHCR 패키지 페이지에서 찾을 수 있습니다.
`image_ref`를 비워 두고 실행하면 선택한 브랜치의 최신 커밋을 다시 빌드해서 배포합니다.

공개 주소(`https://vasthorizon.bnbong.com`)는 GitHub 러너에서 확인하면 Cloudflare 챌린지(403)를 받을 수 있습니다. 그래서 워크플로는 VM1 안에서 `--resolve`로 확인한 결과만으로 성공 여부를 판정하고, 공개 주소 응답은 참고로만 출력합니다.

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
| `llm.local_embedding_batch_size` | 16 | 로컬 임베딩 모델에 한 번에 넣는 문서 수입니다. 키우면 색인을 조금 빨리 만들지만 메모리를 더 씁니다. fastembed 기본값인 256으로 두면 e5-large에서 메모리가 6GB 넘게 올라갑니다 (7절). 값을 바꿔도 결과 벡터는 같으므로 색인을 다시 만들 필요는 없습니다 |
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
| 첫 실행의 메모리 부족 (VM2: ARM64 2코어) | 임베딩을 배치 크기 지정 없이 계산하던 때는 fastembed 기본 배치(256문서)가 적용되었습니다. 그래서 e5-large로 서가 색인을 만드는 동안 컨테이너 메모리가 6.4GB까지 올라갔고, 메모리 상한을 4GB로 둔 첫 실행은 항목 색인을 만드는 도중에 프로세스가 강제 종료(`Killed`)되었습니다. 이제는 `llm.local_embedding_batch_size`(기본 16)만큼 나눠서 계산합니다. 설정값이 그대로 전달되는지는 가짜 엔진으로 확인했습니다 (`LocalEmbeddingBatchTest`) |
| 도중에 끊긴 색인 | 강제 종료된 뒤 다시 시작한 실행은 `항목 색인 있음 (200건)`이라고 출력하고 넘어갔습니다. 건수가 0보다 크기만 하면 완성된 색인으로 여겼기 때문입니다. 이제 항목, 서가 색인 스크립트는 끝까지 성공했을 때만 컬렉션 메타데이터에 완성 표식(`index_complete`, `index_count`)을 남깁니다. `deploy_init`은 표식이 없거나, 기록된 건수 또는 `data/items.json`의 항목 수가 실제 건수와 다르면 `항목 색인이 불완전합니다 (200/424건)`처럼 알리고 임시 컬렉션에서 다시 만듭니다. 표식과 건수가 맞으면 다시 만들지 않습니다 (`DeployInitTest`) |
| 정적 화면 빌드 | `dist/index.html`에 API 주소가 들어가고, 잘못된 주소는 거부 |
| Docker 이미지 | 빌드 성공, 5.1GB. 처음 만든 이미지는 모델 폴더의 권한을 바꾸는 단계가 모델을 한 번 더 복사해 12.3GB였습니다. 실행 사용자를 먼저 만들고 그 사용자로 모델을 받도록 바꿨습니다. 모델은 소스를 복사하기 전 단계에서 `scripts/prefetch_model.py`로 받으므로, 소스만 바뀌면 2.2GB 모델 레이어를 캐시에서 다시 씁니다 |
| 컨테이너 실행 | 첫 실행에 색인을 만든 뒤 서버 시작 (474초), `/api/health` 준비 완료(항목 색인 424건), 실제 질문에 근거 인용 답변 (67초) |
| 컨테이너 호출 한도 | 1분에 6번째 POST에서 429와 `Retry-After: 60`, 조회(GET)는 200 |
| 의존성 고정 | `langchain-anthropic` 최신판은 `langchain-core` 1.6.10 이상을 요구해 `requirements.txt`의 1.6.0 고정과 충돌했습니다. 1.6.0과 맞는 1.7.0으로 고정했습니다 |
| 한국어 출력 | Claude가 검색어를 일본어로 뽑거나("見かけの等級") 답에 한자를 섞는("1950년代") 일이 있어, 공통 역할 문장에 한글로만 쓰라는 규칙을 더했습니다. 이후 검색어 추출 3회 모두 한국어 JSON 하나 |
| 첫 질문의 스트림이 끊김 | 공개 배포(Cloudflare, VM1 Nginx, VM2 컨테이너)에서 첫 질문을 보내면 진행 상태가 "문서 5건을 색인하는 중"까지 온 뒤 136초쯤에 연결이 끊겼습니다(HTTP 200, result 이벤트 없음). 임베딩(e5-large, ARM 2코어)과 Claude 답변 생성이 이어지는 동안 서버가 아무 바이트도 보내지 않았기 때문입니다. Cloudflare는 원본이 100초 동안 바이트를 보내지 않으면 연결을 끊고, Nginx의 `proxy_read_timeout`도 이벤트 사이의 간격에 적용됩니다. 이제 `/api/ask/stream`은 15초(`KEEPALIVE_SECONDS`) 동안 보낼 이벤트가 없으면 SSE 주석 줄(`: keepalive`)을 보냅니다. 화면의 스트림 파서는 `event:` 줄이 없는 블록을 건너뜁니다. 느린 질의 함수로 주석 줄이 여러 번 나온 뒤 result가 오는지 확인했습니다 (`test_stream_keepalive_while_worker_is_slow`) |
