#!/bin/bash
# =========================================================================
# MCP 서버 업그레이드 확인 및 설치 스크립트
# 사용법: bash scripts/mcp_upgrade.sh [check|upgrade|all]
# =========================================================================

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# 프로젝트 루트
PROJECT_ROOT="/workspace/jayeondeule"
WEB_SEARCH_DIR="$PROJECT_ROOT/.mcp/web-search"

# -------------------------------------------------------------------
# 로깅 함수
# -------------------------------------------------------------------
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_title() { echo -e "${CYAN}$1${NC}"; }

# -------------------------------------------------------------------
# npx 패키지 현재 설치된 버전 확인
# -------------------------------------------------------------------
get_installed_version() {
    local pkg=$1
    local cache_dir=$(npm config get cache 2>/dev/null)/_npx
    local ver=$(npm ls -g "$pkg" --depth=0 2>/dev/null | grep "$pkg" | sed 's/.*@//' || echo "")
    if [ -z "$ver" ]; then
        ver="(npx 캐시)"
    fi
    echo "$ver"
}

# -------------------------------------------------------------------
# npx 패키지 최신 버전 확인
# -------------------------------------------------------------------
get_latest_version() {
    local pkg=$1
    npm view "$pkg" version 2>/dev/null || echo "조회실패"
}

# -------------------------------------------------------------------
# [1] 버전 확인 (check)
# -------------------------------------------------------------------
check_versions() {
    log_title "=========================================="
    log_title "  MCP 서버 버전 확인"
    log_title "=========================================="
    echo ""

    # Node.js / npx 환경 확인
    log_info "Node.js: $(node --version 2>/dev/null || echo '미설치')"
    log_info "npx: $(npx --version 2>/dev/null || echo '미설치')"
    echo ""

    # --- npx 기반 서버 ---
    log_title "[ npx 기반 MCP 서버 ]"
    echo ""

    local NPX_PACKAGES=(
        "@modelcontextprotocol/server-postgres"
        "@modelcontextprotocol/server-filesystem"
        "@kazuph/mcp-fetch"
    )

    local NPX_NAMES=("postgres" "filesystem" "fetch")

    for i in "${!NPX_PACKAGES[@]}"; do
        local pkg="${NPX_PACKAGES[$i]}"
        local name="${NPX_NAMES[$i]}"
        local latest=$(get_latest_version "$pkg")

        if [ "$latest" = "조회실패" ]; then
            log_error "  $name ($pkg): 레지스트리 조회 실패"
        else
            log_info "  $name: 최신 버전 = $latest"
        fi
    done

    echo ""

    # --- 로컬 빌드 서버 (web-search) ---
    log_title "[ 로컬 빌드 MCP 서버 ]"
    echo ""

    if [ -d "$WEB_SEARCH_DIR/.git" ]; then
        cd "$WEB_SEARCH_DIR"

        local LOCAL_HASH=$(git rev-parse --short HEAD 2>/dev/null)
        local LOCAL_DATE=$(git log -1 --format="%ci" 2>/dev/null | cut -d' ' -f1)

        # 원격 최신 커밋 확인
        git fetch origin main --quiet 2>/dev/null || git fetch origin master --quiet 2>/dev/null || true
        local REMOTE_HASH=$(git rev-parse --short origin/main 2>/dev/null || git rev-parse --short origin/master 2>/dev/null || echo "확인불가")
        local REMOTE_DATE=$(git log -1 origin/main --format="%ci" 2>/dev/null | cut -d' ' -f1 || echo "")

        log_info "  web-search (pskill9/web-search)"
        log_info "    로컬:  $LOCAL_HASH ($LOCAL_DATE)"
        log_info "    원격:  $REMOTE_HASH ($REMOTE_DATE)"

        if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
            log_info "    상태:  최신 상태"
        elif git merge-base --is-ancestor "$REMOTE_HASH" HEAD 2>/dev/null; then
            log_info "    상태:  최신 상태 (로컬 커스텀 커밋 포함)"
        else
            log_warn "    상태:  업데이트 가능"
        fi

        cd "$PROJECT_ROOT"
    else
        log_error "  web-search: $WEB_SEARCH_DIR 디렉토리 없음"
    fi

    echo ""
}

# -------------------------------------------------------------------
# [2] npx 캐시 갱신 (upgrade-npx)
# -------------------------------------------------------------------
upgrade_npx() {
    log_title "=========================================="
    log_title "  npx MCP 서버 캐시 갱신"
    log_title "=========================================="
    echo ""

    local NPX_PACKAGES=(
        "@modelcontextprotocol/server-postgres"
        "@modelcontextprotocol/server-filesystem"
        "@kazuph/mcp-fetch"
    )

    local NPX_NAMES=("postgres" "filesystem" "fetch")

    for i in "${!NPX_PACKAGES[@]}"; do
        local pkg="${NPX_PACKAGES[$i]}"
        local name="${NPX_NAMES[$i]}"

        log_info "$name ($pkg) 캐시 갱신 중..."

        npx -y "$pkg" --help > /dev/null 2>&1 && \
            log_info "  $name: 갱신 완료 ($(get_latest_version "$pkg"))" || \
            log_warn "  $name: 갱신 중 오류 발생 (서비스 실행에는 영향 없음)"
    done

    echo ""
    log_info "npx 서버는 다음 실행 시 최신 버전을 자동으로 사용합니다."
    echo ""
}

# -------------------------------------------------------------------
# [3] web-search 업그레이드 (upgrade-web-search)
# -------------------------------------------------------------------
upgrade_web_search() {
    log_title "=========================================="
    log_title "  web-search MCP 서버 업그레이드"
    log_title "=========================================="
    echo ""

    if [ ! -d "$WEB_SEARCH_DIR/.git" ]; then
        log_error "web-search 디렉토리가 없습니다: $WEB_SEARCH_DIR"
        log_info "새로 클론합니다..."
        git clone https://github.com/pskill9/web-search.git "$WEB_SEARCH_DIR"
    fi

    cd "$WEB_SEARCH_DIR"

    # 현재 상태 저장
    local BEFORE_HASH=$(git rev-parse --short HEAD 2>/dev/null)

    # 원격에서 최신 코드 가져오기
    log_info "원격 저장소에서 최신 코드 가져오는 중..."
    git fetch origin 2>/dev/null

    local DEFAULT_BRANCH=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}')
    DEFAULT_BRANCH=${DEFAULT_BRANCH:-main}

    git pull origin "$DEFAULT_BRANCH" 2>/dev/null || {
        log_warn "git pull 실패. 로컬 변경사항이 있을 수 있습니다."
        log_info "강제 리셋을 원하면: cd $WEB_SEARCH_DIR && git reset --hard origin/$DEFAULT_BRANCH"
        cd "$PROJECT_ROOT"
        return 1
    }

    local AFTER_HASH=$(git rev-parse --short HEAD 2>/dev/null)

    if [ "$BEFORE_HASH" = "$AFTER_HASH" ]; then
        log_info "이미 최신 상태입니다. ($AFTER_HASH)"
    else
        log_info "업데이트됨: $BEFORE_HASH -> $AFTER_HASH"

        # 의존성 재설치 및 빌드
        log_info "npm install 실행 중..."
        npm install 2>&1 | tail -3

        log_info "빌드 중..."
        npm run build 2>&1 | tail -3

        log_info "web-search 업그레이드 완료"
    fi

    cd "$PROJECT_ROOT"
    echo ""
}

# -------------------------------------------------------------------
# [4] 동작 테스트
# -------------------------------------------------------------------
test_servers() {
    log_title "=========================================="
    log_title "  MCP 서버 동작 테스트"
    log_title "=========================================="
    echo ""

    # web-search 빌드 파일 존재 확인
    if [ -f "$WEB_SEARCH_DIR/build/index.js" ]; then
        log_info "  web-search: 빌드 파일 존재 (OK)"
    else
        log_error "  web-search: 빌드 파일 없음 ($WEB_SEARCH_DIR/build/index.js)"
    fi

    # npx 패키지 존재 확인
    local NPX_PACKAGES=(
        "@modelcontextprotocol/server-postgres"
        "@modelcontextprotocol/server-filesystem"
        "@kazuph/mcp-fetch"
    )
    local NPX_NAMES=("postgres" "filesystem" "fetch")

    for i in "${!NPX_PACKAGES[@]}"; do
        local pkg="${NPX_PACKAGES[$i]}"
        local name="${NPX_NAMES[$i]}"
        local ver=$(get_latest_version "$pkg")

        if [ "$ver" != "조회실패" ]; then
            log_info "  $name: npm 레지스트리 접근 가능 (v$ver)"
        else
            log_error "  $name: npm 레지스트리 접근 불가"
        fi
    done

    # mcp.json 파일 존재 확인
    echo ""
    if [ -f "$PROJECT_ROOT/.vscode/mcp.json" ]; then
        log_info "  mcp.json: 설정 파일 존재 (OK)"
    else
        log_error "  mcp.json: 설정 파일 없음"
    fi

    echo ""
}

# -------------------------------------------------------------------
# 사용법
# -------------------------------------------------------------------
usage() {
    echo ""
    echo "사용법: bash $0 [명령어]"
    echo ""
    echo "명령어:"
    echo "  check              버전 확인만 수행"
    echo "  upgrade-npx        npx 기반 서버 캐시 갱신"
    echo "  upgrade-web        web-search 서버 업그레이드 (git pull + build)"
    echo "  upgrade            모든 서버 업그레이드"
    echo "  test               동작 테스트"
    echo "  all                전체 수행 (확인 + 업그레이드 + 테스트)"
    echo ""
}

# -------------------------------------------------------------------
# 메인 실행
# -------------------------------------------------------------------
case "${1:-check}" in
    check)
        check_versions
        ;;
    upgrade-npx)
        upgrade_npx
        ;;
    upgrade-web)
        upgrade_web_search
        ;;
    upgrade)
        upgrade_npx
        upgrade_web_search
        ;;
    test)
        test_servers
        ;;
    all)
        check_versions
        upgrade_npx
        upgrade_web_search
        test_servers
        log_title "=========================================="
        log_title "  전체 업그레이드 완료"
        log_title "=========================================="
        echo ""
        log_warn "VSCode를 재시작해야 MCP 서버가 새 버전으로 실행됩니다."
        echo ""
        ;;
    *)
        usage
        ;;
esac
