#!/usr/bin/env bash
# VM2 VastHorizon image deployment script (GHCR release entrypoint)
#
# 운영 배치 위치: /opt/bnbong/vasthorizon/deploy.sh (저장소의 deploy/vm2/deploy.sh)
# 호출 주체: 이 저장소의 .github/workflows/release.yml이 SSH로
#            `bash /opt/bnbong/vasthorizon/deploy.sh <image_ref>`를 실행한다.
#            ubuntu 계정으로 실행하며 sudo는 쓰지 않는다. ubuntu는 docker 그룹에
#            속해 있고 /opt/bnbong/vasthorizon의 소유자다.
#
# 설계 요지
#   - 이 스크립트는 소스를 build하지 않는다. GHCR에 이미 올라간 image만 교체한다.
#     compose 파일의 build 블록(src/)은 GHCR을 쓸 수 없을 때 사람이 쓰는 대체 경로다.
#   - flock으로 동시 실행을 막는다. 워크플로의 concurrency와 손으로 하는 배포가
#     겹치면 .env 갱신과 compose up이 서로 엇갈릴 수 있기 때문이다.
#   - .env는 통째로 다시 쓰지 않는다. VASTHORIZON_IMAGE 줄만 바꾸고 나머지 비밀 값은
#     보존하며, 임시 파일에 쓴 뒤 mv로 교체하여 중간 상태가 남지 않게 한다.
#   - 교체 직전 컨테이너의 image ID를 rollback/vm2-vasthorizon:previous 태그로 남긴다.
#     .env의 이전 값이 비어 있거나(compose 기본값 :main) 현장 build로 만든 로컬
#     태그이면, 그 참조가 지금도 같은 image를 가리킨다는 보장이 없다. 이 경우
#     되돌릴 때 이 태그로 고정한다. 태그는 하나만 두고 매번 덮어쓰므로 쌓이지 않는다.
#   - health check가 실패하면 실패한 컨테이너의 로그와 State를 먼저 갈무리한 다음
#     .env를 이전 내용으로 되돌리고 이전 image로 다시 기동한다. 갈무리한 내용은
#     $DEPLOY_DIR/deploy-failures/<UTC>.log에 남긴다.
#   - 되돌린 뒤에도 같은 health 확인을 수행한다. 이전 image까지 실패하면 서비스가
#     중단된 상태이므로 종료 코드 3으로 알린다.
#   - docker image prune은 실행하지 않는다. VM2에는 다른 stack의 image도 있다.
#     오래된 VastHorizon image는 사람이 판단하여 지운다.
#
# health 대기 시간
#   첫 기동이나 임베딩 모델이 바뀐 뒤에는 색인을 다시 만들기 때문에 health가 200이
#   되기까지 15분 가까이 걸릴 수 있다. 그래서 기본 대기 시간을 1000초(100회 x 10초)로
#   잡았다. 볼륨이 남아 있는 평소 재배포는 수십 초 안에 끝난다.
#
# 사용법
#   release.yml은 build 직후에 digest로 고정한 참조를 넘긴다.
#     bash /opt/bnbong/vasthorizon/deploy.sh ghcr.io/bnbong/vasthorizon@sha256:<64자리>
#   되돌릴 때 쓰는 workflow_dispatch 실행과 손으로 하는 배포는 태그 참조를 넘긴다.
#     bash /opt/bnbong/vasthorizon/deploy.sh ghcr.io/bnbong/vasthorizon:sha-1a2b3c4
#
# 환경 변수 (시험용 재정의)
#   DEPLOY_DIR        기본 /opt/bnbong/vasthorizon. compose 파일과 .env가 있는 디렉터리다.
#   HEALTH_URL        기본 http://127.0.0.1:8020/api/health
#   HEALTH_RETRIES    기본 100
#   HEALTH_INTERVAL   기본 10 (초)
#   FAILURE_LOG_DIR   기본 $DEPLOY_DIR/deploy-failures
#   DOCKER, CURL, FLOCK
#                     기본 docker, curl, flock. docker가 없는 곳에서 인자 검증과
#                     .env 교체만 시험할 때 가짜 명령으로 바꾼다.

set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/bnbong/vasthorizon}"
ENV_FILE="$DEPLOY_DIR/.env"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"
RELEASES_LOG="$DEPLOY_DIR/releases.log"
LOCK_FILE="$DEPLOY_DIR/.deploy.lock"
FAILURE_LOG_DIR="${FAILURE_LOG_DIR:-$DEPLOY_DIR/deploy-failures}"

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8020/api/health}"
HEALTH_RETRIES="${HEALTH_RETRIES:-100}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-10}"

DOCKER="${DOCKER:-docker}"
CURL="${CURL:-curl}"
FLOCK="${FLOCK:-flock}"

IMAGE_REPO="ghcr.io/bnbong/vasthorizon"
IMAGE_VAR="VASTHORIZON_IMAGE"
SERVICE="vasthorizon"
CONTAINER="vm2-vasthorizon"
ROLLBACK_TAG="rollback/${CONTAINER}:previous"

log()  { echo "[INFO]  $*"; }
warn() { echo "[WARN]  $*" >&2; }
err()  { echo "[ERROR] $*" >&2; }

usage() {
    cat <<'USAGE'
usage: deploy.sh <image_ref>

  image_ref : ghcr.io/bnbong/vasthorizon@sha256:<64자리 16진수>  (release 기본)
              ghcr.io/bnbong/vasthorizon:<tag>                   (되돌릴 때, 예: sha-1a2b3c4)

종료 코드
  0 : 배포에 성공했다.
  1 : 배포에 실패했으나 서비스는 이전 image로 돌아갔거나 운영을 건드리지 않았다.
  2 : 인자나 image 참조 형식이 올바르지 않다.
  3 : 배포에 실패했고 되돌린 뒤에도 health 확인을 통과하지 못했다. 서비스가
      중단된 상태이므로 사람이 즉시 조치해야 한다.
USAGE
}

# ----------------------------------------------------------------------------
# 1. 인자 검증
# ----------------------------------------------------------------------------
if [ "$#" -ne 1 ]; then
    err "인자는 정확히 하나여야 한다. (받은 개수: $#)"
    usage >&2
    exit 2
fi

IMAGE_REF="$1"

# ghcr.io/bnbong/vasthorizon image만 받는다. 이 검사를 두지 않으면 호출자가 임의의
# registry에서 가져온 image를 운영 컨테이너로 올릴 수 있다. 두 가지 표기를 받는다.
#   digest 고정 참조: <repo>@sha256:<64자리 소문자 16진수>
#   태그 참조       : <repo>:<태그>  (Docker 태그 규칙: 첫 글자는 영숫자나 _, 최대 128자)
if printf '%s' "$IMAGE_REF" | grep -Eq "^${IMAGE_REPO//./\\.}@sha256:[0-9a-f]{64}\$"; then
    IMAGE_REF_KIND="digest"
elif printf '%s' "$IMAGE_REF" | grep -Eq "^${IMAGE_REPO//./\\.}:[A-Za-z0-9_][A-Za-z0-9._-]{0,127}\$"; then
    IMAGE_REF_KIND="tag"
else
    err "image 참조 형식이 올바르지 않다: $IMAGE_REF"
    err "형식은 ${IMAGE_REPO}@sha256:<64자리 16진수> 또는 ${IMAGE_REPO}:<tag>이다."
    exit 2
fi

for f in "$COMPOSE_FILE" "$ENV_FILE"; do
    if [ ! -f "$f" ]; then
        err "필요한 파일이 없다: $f"
        exit 1
    fi
done

for cmd in "$DOCKER" "$CURL" "$FLOCK"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        err "$cmd 명령을 찾지 못했다."
        exit 1
    fi
done

# ----------------------------------------------------------------------------
# 2. 동시 실행 방지
# ----------------------------------------------------------------------------
# 뒤에 온 쪽을 기다리게 하지 않고 즉시 실패시켜서, 워크플로 로그에 무엇 때문에
# 중단되었는지 남기고 다시 실행하도록 한다.
exec 9>"$LOCK_FILE"
if ! "$FLOCK" -n 9; then
    err "다른 배포가 진행 중이다($LOCK_FILE). 끝난 뒤에 다시 실행한다."
    exit 1
fi

# 호출한 셸에 같은 이름의 변수가 있으면 compose가 .env보다 그 값을 먼저 쓴다.
# 이 스크립트가 바꾸는 값은 .env에만 있어야 하므로 지운다.
unset "$IMAGE_VAR"

# --project-directory를 명시해야 현재 작업 디렉터리와 상관없이 같은 .env를 읽는다.
compose() {
    "$DOCKER" compose --project-directory "$DEPLOY_DIR" -f "$COMPOSE_FILE" "$@"
}

echo "=== VM2 VastHorizon image deployment ==="
log "image     : $IMAGE_REF ($IMAGE_REF_KIND)"
log "deploy dir: $DEPLOY_DIR"

# compose 파일이나 .env가 이미 잘못되어 있으면 운영 컨테이너를 건드리기 전에 멈춘다.
# VM2_PRIVATE_IP, VM1_PRIVATE_IP처럼 `${VAR:?...}`로 선언한 값이 없을 때 여기에서 걸린다.
if ! compose config -q; then
    err "docker compose config가 실패했다. ${ENV_FILE}의 필수 값을 먼저 고친다."
    err "운영 컨테이너는 그대로 두고 중단한다."
    exit 1
fi

# ----------------------------------------------------------------------------
# 3. image 내려받기
# ----------------------------------------------------------------------------
log "[1/5] image를 내려받는다."
if ! "$DOCKER" pull "$IMAGE_REF"; then
    err "docker pull에 실패했다: $IMAGE_REF"
    err "GHCR 패키지가 public인지, 태그가 실제로 존재하는지, 아키텍처가 arm64인지 확인한다."
    exit 1
fi
NEW_IMAGE_ID="$("$DOCKER" image inspect --format '{{.Id}}' "$IMAGE_REF")"
log "image id: $NEW_IMAGE_ID"

# ----------------------------------------------------------------------------
# 4. 이전 상태 기억
# ----------------------------------------------------------------------------
log "[2/5] 이전 상태를 기억한다."

# .env에 적힌 이전 값. 줄이 없거나 비어 있으면 compose 기본값(:main)을 쓰던 상태다.
PREV_VALUE="$(awk -v var="$IMAGE_VAR" '
    $0 ~ "^[[:space:]]*" var "=" { sub("^[[:space:]]*" var "=", ""); sub(/\r$/, ""); v = $0 }
    END { print v }
' "$ENV_FILE")"
log "이전 ${IMAGE_VAR}: ${PREV_VALUE:-(비어 있음, compose 기본값 사용)}"

# 지금 돌고 있는 컨테이너의 image ID에 롤백 태그를 붙인다. 태그가 아니라 ID를
# 대상으로 삼아야, 같은 태그가 새 image로 덮여도 이전 layer를 되찾을 수 있다.
PREV_IMAGE_ID=""
if "$DOCKER" inspect --type container "$CONTAINER" >/dev/null 2>&1; then
    PREV_IMAGE_ID="$("$DOCKER" inspect --type container --format '{{.Image}}' "$CONTAINER")"
    "$DOCKER" tag "$PREV_IMAGE_ID" "$ROLLBACK_TAG"
    log "rollback point: $ROLLBACK_TAG ($PREV_IMAGE_ID)"
else
    warn "$CONTAINER 컨테이너가 없다. 최초 배포로 간주하며 롤백 지점을 만들지 않는다."
fi

# .env는 통째로 되돌릴 수 있도록 사본을 남긴다.
ENV_BACKUP="$(mktemp "${ENV_FILE}.bak.XXXXXX")"
chmod 600 "$ENV_BACKUP"
cat "$ENV_FILE" >"$ENV_BACKUP"

cleanup() {
    rm -f "$ENV_BACKUP"
}
trap cleanup EXIT

# ----------------------------------------------------------------------------
# 5. .env의 image 변수 갱신
# ----------------------------------------------------------------------------
log "[3/5] .env의 $IMAGE_VAR 값을 갱신한다."

# 권한을 그대로 유지해야 한다. 새로 만든 파일로 바꾸면 umask에 따라 0644가 되어
# 비밀 값이 다른 사용자에게 읽힐 수 있다.
update_env_var() {
    local var="$1" value="$2" tmp
    tmp="$(mktemp "${ENV_FILE}.new.XXXXXX")"
    chmod --reference="$ENV_FILE" "$tmp" 2>/dev/null || chmod 600 "$tmp"

    if grep -Eq "^[[:space:]]*${var}=" "$ENV_FILE"; then
        # 주석 처리된 예시 줄(`# VASTHORIZON_IMAGE=...`)은 건드리지 않는다.
        awk -v var="$var" -v val="$value" '
            $0 ~ "^[[:space:]]*" var "=" { print var "=" val; next }
            { print }
        ' "$ENV_FILE" >"$tmp"
    else
        cat "$ENV_FILE" >"$tmp"
        # 파일이 개행으로 끝나지 않으면 새 줄이 앞 줄에 붙는다.
        if [ -s "$tmp" ] && [ "$(tail -c 1 "$tmp" | wc -l)" -eq 0 ]; then
            printf '\n' >>"$tmp"
        fi
        printf '%s=%s\n' "$var" "$value" >>"$tmp"
    fi

    mv -f "$tmp" "$ENV_FILE"
}

restore_env() {
    local tmp
    tmp="$(mktemp "${ENV_FILE}.new.XXXXXX")"
    chmod --reference="$ENV_FILE" "$tmp" 2>/dev/null || chmod 600 "$tmp"
    cat "$ENV_BACKUP" >"$tmp"
    mv -f "$tmp" "$ENV_FILE"
}

update_env_var "$IMAGE_VAR" "$IMAGE_REF"

# ----------------------------------------------------------------------------
# 6. 컨테이너 교체와 health 확인
# ----------------------------------------------------------------------------
log "[4/5] 컨테이너를 교체한다."

# 200이 나오고, 응답한 컨테이너가 기대한 image로 돌고 있을 때만 성공으로 본다.
# image까지 대조해야 compose가 컨테이너를 바꾸지 못하고 이전 컨테이너가 계속
# 응답하는 상황을 성공으로 오인하지 않는다.
run_health_check() {
    local expected_id="$1" i code running_id
    for ((i = 1; i <= HEALTH_RETRIES; i++)); do
        code="$("$CURL" -s -o /dev/null -w '%{http_code}' --max-time 5 "$HEALTH_URL" || true)"
        if [ "$code" = "200" ]; then
            running_id="$("$DOCKER" inspect --type container --format '{{.Image}}' "$CONTAINER" 2>/dev/null || true)"
            if [ "$running_id" = "$expected_id" ]; then
                log "  health 200 ($i/$HEALTH_RETRIES)"
                return 0
            fi
            err "  health는 200인데 컨테이너 image가 다르다. (기대 $expected_id, 실제 ${running_id:-없음})"
            return 1
        fi
        # 진행 상황을 너무 자주 찍지 않는다. 색인을 다시 만드는 동안 로그가 길어진다.
        if [ "$i" -eq 1 ] || [ $((i % 6)) -eq 0 ]; then
            log "  대기 중 ($i/$HEALTH_RETRIES, 응답 ${code:-000})"
        fi
        sleep "$HEALTH_INTERVAL"
    done
    err "  health가 $((HEALTH_RETRIES * HEALTH_INTERVAL))초 안에 200이 되지 않았다."
    return 1
}

capture_failure() {
    local phase="$1" file
    if mkdir -p "$FAILURE_LOG_DIR" 2>/dev/null; then
        file="$FAILURE_LOG_DIR/$(date -u +%Y%m%dT%H%M%SZ).log"
        # 로그에 요청 내용이 섞일 수 있으므로 소유자만 읽게 한다.
        chmod 700 "$FAILURE_LOG_DIR" 2>/dev/null || true
    else
        warn "실패 기록 디렉터리를 만들지 못했다: $FAILURE_LOG_DIR"
        file="/dev/null"
    fi

    {
        echo "=== deploy failure capture ==="
        echo "time    : $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "phase   : $phase"
        echo "image   : $IMAGE_REF"
        echo "previous: ${PREV_VALUE:-(비어 있음)} ${PREV_IMAGE_ID:+($PREV_IMAGE_ID)}"
        echo ""
        echo "--- docker compose logs --tail 120 ---"
        compose logs --no-color --tail 120 2>&1 || echo "(로그를 읽지 못했다)"
        echo ""
        echo "--- docker inspect .State ---"
        "$DOCKER" inspect --type container --format '{{json .State}}' "$CONTAINER" 2>&1 \
            || echo "(State를 읽지 못했다)"
    } | tee -a "$file"

    if [ "$file" != "/dev/null" ]; then
        chmod 600 "$file" 2>/dev/null || true
        err "실패 기록을 남겼다: $file"
    fi
}

HEALTH_FAILED=0
if compose up -d --no-build "$SERVICE"; then
    log "health를 확인한다. (최대 $((HEALTH_RETRIES * HEALTH_INTERVAL))초)"
    run_health_check "$NEW_IMAGE_ID" || HEALTH_FAILED=1
else
    err "docker compose up이 실패했다."
    HEALTH_FAILED=1
fi

# ----------------------------------------------------------------------------
# 7. 실패하면 되돌린다
# ----------------------------------------------------------------------------
if [ "$HEALTH_FAILED" -ne 0 ]; then
    err "배포에 실패했다. 되돌리기 전에 실패한 컨테이너의 상태를 먼저 갈무리한다."
    capture_failure "new-image"

    err "이전 상태로 되돌린다."
    restore_env
    log ".env를 이전 내용으로 되돌렸다."

    if [ -z "$PREV_IMAGE_ID" ]; then
        warn "최초 배포라서 되돌릴 image가 없다. 컨테이너 상태를 직접 확인한다."
        echo ""
        echo "확인 명령"
        echo "  cd $DEPLOY_DIR && docker compose ps && docker compose logs --tail 100"
        exit 1
    fi

    # .env의 이전 값이 지금도 이전 컨테이너의 image를 가리키면 되돌린 .env를 그대로
    # 쓴다. 이전 값이 비어 있어 compose 기본값(:main)을 쓰던 경우나, 로컬 태그가
    # 다른 image로 옮겨 간 경우에는 롤백 태그로 고정한다.
    PREV_RESOLVED_ID="$("$DOCKER" image inspect --format '{{.Id}}' \
        "${PREV_VALUE:-${IMAGE_REPO}:main}" 2>/dev/null || true)"
    if [ "$PREV_RESOLVED_ID" != "$PREV_IMAGE_ID" ]; then
        log "이전 참조(${PREV_VALUE:-기본값 :main})가 이전 image를 가리키지 않는다. $ROLLBACK_TAG 로 고정한다."
        update_env_var "$IMAGE_VAR" "$ROLLBACK_TAG"
    fi

    ROLLBACK_FAILED=0
    if compose up -d --no-build "$SERVICE"; then
        log "이전 image로 다시 기동했다. 같은 기준으로 health를 다시 확인한다."
        run_health_check "$PREV_IMAGE_ID" || ROLLBACK_FAILED=1
    else
        err "이전 image로 다시 기동하는 데에도 실패했다."
        ROLLBACK_FAILED=1
    fi

    if [ "$ROLLBACK_FAILED" -ne 0 ]; then
        capture_failure "rollback"
        echo "" >&2
        err "############################################################"
        err "# 서비스 중단 상태다. 이전 image도 health 확인을 통과하지 못했다."
        err "# 실패 image : $IMAGE_REF"
        err "# 이전 image : $PREV_IMAGE_ID ($ROLLBACK_TAG)"
        err "# 사람이 즉시 조치해야 한다."
        err "############################################################"
        err "확인 순서"
        err "  1) 위의 실패 기록과 ${FAILURE_LOG_DIR}의 파일을 읽는다."
        err "  2) compose 파일이나 .env의 형식이 이번에 바뀌었는지 확인한다."
        err "     이전 image는 새 형식을 읽지 못할 수 있다."
        err "  3) 색인을 다시 만드는 중이라 시간이 모자랐을 수도 있다. 아래로 상태를 본다."
        err "     docker inspect --format '{{.State.Health.Status}}' $CONTAINER"
        exit 3
    fi
    log "이전 image가 health 확인을 통과했다. 서비스는 이전 상태로 돌아갔다."
    echo ""
    echo "확인 명령"
    echo "  cd $DEPLOY_DIR && docker compose ps && docker compose logs --tail 100"
    exit 1
fi

# ----------------------------------------------------------------------------
# 8. 기록
# ----------------------------------------------------------------------------
log "[5/5] release 기록을 남긴다."
# 시각, 이번 참조, 이번 image ID, 이전 참조, 이전 image ID를 탭으로 구분해 남긴다.
printf '%s\t%s\t%s\t%s\t%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$IMAGE_REF" "$NEW_IMAGE_ID" \
    "${PREV_VALUE:--}" "${PREV_IMAGE_ID:--}" \
    >>"$RELEASES_LOG"

echo ""
echo "=== 배포를 완료했다 ==="
echo "  image : $IMAGE_REF"
echo "  id    : $NEW_IMAGE_ID"
echo "  기록   : $RELEASES_LOG"
echo ""
if [ -n "$PREV_IMAGE_ID" ]; then
    echo "이 배포를 되돌리려면 release 워크플로를 workflow_dispatch로 실행하고"
    echo "image_ref에 이전 sha- 태그를 넣는다. VM2에서 직접 되돌리려면 아래를 실행한다."
    echo "  bash $DEPLOY_DIR/deploy.sh ${IMAGE_REPO}:sha-<이전 커밋 7자리>"
    echo "  (이전 image ID: $PREV_IMAGE_ID, 태그 $ROLLBACK_TAG)"
fi
