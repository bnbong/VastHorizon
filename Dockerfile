# VastHorizon 배포 이미지 — 화면(web/)과 API(FastAPI)를 컨테이너 하나로. Claude API + 서버 안 로컬 임베딩.
#
#     docker build -t vasthorizon .
#     docker run -p 8000:8000 --env-file .env -v vh-data:/app/data/deploy vasthorizon
#
# 키는 이미지에 넣지 않는다. 실행할 때 환경변수(CLAUDE_API_KEY, WIKI_CONTACT)로 넘긴다.
# 색인 · 문서 캐시는 /app/data/deploy (볼륨). 처음 실행할 때 색인을 만든다 (몇 분, scripts/deploy_init.py).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VH_CONFIG=config.deploy.toml \
    FASTEMBED_CACHE_PATH=/app/models \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    FORWARDED_ALLOW_IPS="" \
    PORT=8000

WORKDIR /app

COPY requirements.txt requirements-deploy.txt ./
RUN pip install --no-cache-dir -r requirements-deploy.txt

# 레이어 순서: 잘 바뀌지 않는 것부터 — 의존성 → 실행 사용자 → 임베딩 모델(2.2GB) → 소스 · 화면 · 데이터.
# 모델 단계는 config.deploy.toml과 scripts/prefetch_model.py(표준 라이브러리 + fastembed)만 보고, vasthorizon 소스에는
# 기대지 않는다. 그래서 소스 · web · 데이터가 바뀌어도 모델 레이어는 캐시에서 그대로 쓰고(GitHub Actions gha 캐시, 서버 build),
# config.deploy.toml이 바뀔 때(모델 변경 등)만 다시 받는다.

# 실행 사용자 — 쓰기는 데이터 폴더와 모델 캐시에만. 모델을 받기 전에 만들어 두어야
# chown 때문에 모델(2.2GB)이 레이어에 한 번 더 복사되지 않는다
RUN useradd --create-home --uid 10001 vh \
    && mkdir -p /app/data/deploy /app/data/raw /app/models \
    && chown vh /app/data /app/data/deploy /app/data/raw /app/models

# 로컬 임베딩 모델을 이미지에 미리 받아 둔다 (첫 실행이 빨라지고, 실행 중에는 모델을 받으러 나가지 않는다).
# vh 사용자로 받아 /app/models가 처음부터 vh 소유가 되게 한다
COPY config.deploy.toml ./
COPY scripts/prefetch_model.py ./scripts/prefetch_model.py
USER vh
RUN python scripts/prefetch_model.py config.deploy.toml

# 소스 · 화면 · 데이터 — 자주 바뀌므로 모델 뒤에. 읽기만 하므로 root 소유로 둔다
COPY vasthorizon ./vasthorizon
COPY scripts ./scripts
COPY web ./web
COPY config.toml config.deploy.toml ./
COPY data/items.json data/constellations.json data/sky_stars.json ./data/

VOLUME ["/app/data/deploy"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health', timeout=4)"

# 사용자 주소: Uvicorn이 FORWARDED_ALLOW_IPS(신뢰 프록시)에서 온 연결만 X-Forwarded-For를 읽는다. 기본 ""는 아무 헤더도 믿지 않음
CMD ["sh", "-c", "python -m scripts.deploy_init && exec uvicorn vasthorizon.api.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
