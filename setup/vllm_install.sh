#!/bin/bash
# ════════════════════════════════════════════════════════════════════════════
# vLLM 설치 + gemma3:27b AWQ 모델 준비 스크립트 (Ollama 대체 옵션)
# [2026-05-25 신규]
#
# 본 스크립트는 *준비* 만 함 — 실 운영 전환은 별도:
#   1) .env 에 LLM_BACKEND=vllm 추가
#   2) systemctl start vllm.service
#   3) agriAiCore restart 00  (APP 서비스 재시작)
#
# Rollback: .env 의 LLM_BACKEND 줄을 지우거나 ollama 로 변경 + restart.
#
# 전제:
#   · CUDA 12.1+ + NVIDIA Driver 535+
#   · venv: /workspace/jayeondeule/venv
#   · GPU VRAM 충분 (gemma3:27b AWQ ≈ 18GB) — RTX 5060 Ti 16GB 단독은 분산 필요
# ════════════════════════════════════════════════════════════════════════════
set -euo pipefail

BASE_DIR="/workspace/jayeondeule"
VENV_BIN="$BASE_DIR/venv/bin"
MODEL_DIR="${VLLM_MODEL_DIR:-$BASE_DIR/.vllm_models}"

# 기본 모델 — gemma3:27b AWQ-INT4 (HF Mirror). 변경 시 .env 의 VLLM_MODEL 도 같이.
VLLM_MODEL_HF="${VLLM_MODEL_HF:-google/gemma-3-27b-it}"   # safetensors 원본
# AWQ 양자화 버전이 따로 제공되면 그쪽 사용 권장 (VRAM 절감)
# 예: ISTA-DASLab/gemma-3-27b-it-AWQ-Int4 (커뮤니티 빌드)

echo "════════════════════════════════════════════════════════════"
echo " vLLM 설치 (Ollama 병행 운영용)"
echo "════════════════════════════════════════════════════════════"
echo " BASE_DIR  = $BASE_DIR"
echo " VENV      = $VENV_BIN"
echo " MODEL_DIR = $MODEL_DIR"
echo " HF MODEL  = $VLLM_MODEL_HF"
echo ""

# ─── 1) Python venv 확인 ───
if [ ! -x "$VENV_BIN/python" ]; then
    echo "❌ venv 없음: $VENV_BIN/python"
    exit 1
fi

# ─── 2) NVIDIA + CUDA 확인 ───
echo "── nvidia-smi 확인 ──"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv | head -5

# ─── 3) vLLM 설치 ───
echo ""
echo "── vLLM pip 설치 (수 분 소요) ──"
"$VENV_BIN/pip" install --upgrade pip
"$VENV_BIN/pip" install "vllm>=0.6.0,<0.8.0"  # 0.6+ gemma3 지원

# ─── 4) HF transformers / accelerate 부속 ───
"$VENV_BIN/pip" install --upgrade transformers accelerate safetensors

# ─── 5) 모델 다운로드 디렉터리 준비 ───
mkdir -p "$MODEL_DIR"
echo ""
echo "── HF 모델 다운로드 ($VLLM_MODEL_HF → $MODEL_DIR) ──"
echo "   (HF token 필요 시 환경변수 HF_TOKEN 설정)"
"$VENV_BIN/python" - <<PY
import os
from huggingface_hub import snapshot_download
target = os.environ.get("VLLM_MODEL_HF", "$VLLM_MODEL_HF")
local = os.environ.get("VLLM_MODEL_DIR", "$MODEL_DIR") + "/" + target.replace("/", "_")
print(f"target  = {target}")
print(f"local   = {local}")
os.makedirs(local, exist_ok=True)
snapshot_download(repo_id=target, local_dir=local, local_dir_use_symlinks=False,
                  token=os.environ.get("HF_TOKEN") or None)
print(f"✓ 다운로드 완료: {local}")
PY

# ─── 6) systemd unit 배포 ───
echo ""
echo "── systemd unit 배포 ──"
UNIT_SRC="$BASE_DIR/setup/system-configs/systemd/vllm.service"
if [ -f "$UNIT_SRC" ]; then
    sudo cp -v "$UNIT_SRC" /etc/systemd/system/vllm.service
    sudo systemctl daemon-reload
    echo "  → enable 은 운영자 검증 후: sudo systemctl enable --now vllm.service"
else
    echo "  ⚠️ $UNIT_SRC 없음 — Phase 5 산출물 누락. setup/system-configs/systemd 에 vllm.service 작성 필요."
fi

# ─── 7) .env 가이드 ───
echo ""
echo "════════════════════════════════════════════════════════════"
echo " 다음 단계 (.env 보강):"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "   LLM_BACKEND=vllm                  # ← 활성화 (default ollama)"
echo "   VLLM_URL=http://127.0.0.1:8001"
echo "   VLLM_MODEL=$VLLM_MODEL_HF         # 또는 AWQ 버전"
echo "   VLLM_MODEL_DIR=$MODEL_DIR"
echo ""
echo " 활성화:"
echo "   sudo systemctl start vllm.service"
echo "   sudo systemctl status vllm.service"
echo "   curl -s http://127.0.0.1:8001/v1/models | jq"
echo "   sudo $BASE_DIR/agriAiCore restart 00    # APP 재시작 (env 반영)"
echo ""
echo " Rollback:"
echo "   sed -i '/^LLM_BACKEND=vllm/d' $BASE_DIR/.env"
echo "   sudo systemctl stop vllm.service"
echo "   sudo $BASE_DIR/agriAiCore restart 00"
echo ""
echo "✓ 설치 준비 완료. 운영 전환은 사용자 결정."
