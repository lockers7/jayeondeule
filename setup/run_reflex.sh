#!/bin/bash
# =========================================================================
# Reflex UI 실행 래퍼 스크립트
# 실제 실행은 agri_ai_core/run_reflex.sh를 사용합니다.
# =========================================================================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec "$PROJECT_DIR/agri_ai_core/run_reflex.sh"
