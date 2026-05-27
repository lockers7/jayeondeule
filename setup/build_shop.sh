#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# 쇼핑몰 프론트엔드 농장별 빌드 [2026-07-07]
#
# 구조: web/common/shop/frontend-base(공통 소스) + web/<farm>/frontend-custom
#       (농장별 콘텐츠 파일 오버레이) → web/<farm>/dist 산출.
# 신규 농장 쇼핑몰 = web/<farm>/{config,frontend-custom,upload} 만 만들면 됨
# (공통 코드 수정 불필요 — "농장 추가 시 코드 변경 없음" 원칙).
#
# 사용: ./setup/build_shop.sh jayeondeule | goheung | all
# ══════════════════════════════════════════════════════════════════════════════
set -e
BASE_DIR="/workspace/jayeondeule"
FB="$BASE_DIR/web/common/shop/frontend-base"

build_one() {
    local farm="$1"
    local custom="$BASE_DIR/web/$farm/frontend-custom"
    local dist="$BASE_DIR/web/$farm/dist"
    local work="$BASE_DIR/web/$farm/.frontend-build"
    [ -d "$custom" ] || { echo "[$farm] frontend-custom 없음 — 건너뜀"; return 1; }

    echo "[$farm] 오버레이 준비..."
    rm -rf "$work"
    mkdir -p "$work"
    # 하드링크 복사(빠름·무용량) 후 커스텀 파일만 실복사로 덮음
    cp -al "$FB/." "$work/"
    (cd "$custom" && find . -type f) | while read -r f; do
        rm -f "$work/$f"
        install -D "$custom/$f" "$work/$f"
    done

    echo "[$farm] vite 빌드..."
    (cd "$work" && npx vite build --outDir "$dist" --emptyOutDir 2>&1 | tail -2)
    rm -rf "$work"
    echo "[$farm] 완료 → $dist"
}

case "${1:-all}" in
    all) build_one jayeondeule; build_one goheung ;;
    *)   build_one "$1" ;;
esac
