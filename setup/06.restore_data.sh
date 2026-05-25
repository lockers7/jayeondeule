#!/bin/bash
# =========================================================================
# [6단계] 데이터 복원 (PostgreSQL + ChromaDB + Upload)
# system-configs/restore.sh data 를 호출
# =========================================================================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=========================================="
echo "  [6단계] 데이터 복원"
echo "=========================================="
echo ""

bash "$PROJECT_DIR/setup/system-configs/restore.sh" data

echo ""
echo "다음 단계: bash setup/7.build_all.sh"
echo ""
