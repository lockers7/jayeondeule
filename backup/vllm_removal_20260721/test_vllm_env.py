# ══════════════════════════════════════════════════════════════════════════════
# test_vllm_env — vLLM 별도 venv 환경 무결성 (1단계)
#
# 2026-07-17 구축. 이 조합이 깨지면 vLLM 이 Blackwell(sm_120)에서 기동 못 한다.
# 운영 venv(torch cu126)와 분리돼 있음을 함께 보장한다.
#
# 파일 시작 함수 목록:
#   test_vllm_venv_exists        : venv_vllm 실재
#   test_vllm_env_script         : setup/vllm_env.sh 필수 4개 설정
#   test_cuda_home_has_nvcc13    : venv 내장 nvcc 가 12.9+ (flashinfer 요구)
#   test_operational_venv_intact : 운영 venv 는 cu126 그대로 (오염 방지)
# ══════════════════════════════════════════════════════════════════════════════
import os
import re
import subprocess

import pytest

_ROOT = "/workspace/jayeondeule"
_VENV = f"{_ROOT}/venv_vllm"
_ENV_SH = f"{_ROOT}/setup/vllm_env.sh"


def test_vllm_venv_exists():
    assert os.path.isfile(f"{_VENV}/bin/python"), "venv_vllm 없음 — 1단계 미구축"


def test_vllm_env_script():
    assert os.path.isfile(_ENV_SH)
    body = open(_ENV_SH, encoding="utf-8").read()
    # 하나라도 빠지면 기동 실패 — 실측으로 확인된 필수 설정
    for key in ("CUDA_HOME", "VLLM_USE_FLASHINFER_SAMPLER=0",
                "CUDA_DEVICE_ORDER=PCI_BUS_ID", "CUDA_VISIBLE_DEVICES=0"):
        assert key in body, f"vllm_env.sh 에 {key} 누락"


def test_cuda_home_has_nvcc13():
    # 시스템 nvcc 는 12.0 → flashinfer 가 sm_120 을 거부한다. venv 내장 13.x 필요.
    nvcc = f"{_VENV}/lib/python3.12/site-packages/nvidia/cu13/bin/nvcc"
    if not os.path.isfile(nvcc):
        pytest.skip("venv_vllm 미구축")
    out = subprocess.run([nvcc, "--version"], capture_output=True, text=True, timeout=30)
    m = re.search(r"release (\d+)\.(\d+)", out.stdout)
    assert m, "nvcc 버전 파싱 실패"
    major, minor = int(m.group(1)), int(m.group(2))
    assert (major, minor) >= (12, 9), f"nvcc {major}.{minor} — sm_120 은 12.9+ 필요"


def test_operational_venv_intact():
    # ⛔ vLLM 작업이 운영 venv 를 오염시키면 703 테스트가 걸린 운영계가 위험해진다
    out = subprocess.run(
        [f"{_ROOT}/venv/bin/python", "-c", "import torch; print(torch.__version__)"],
        capture_output=True, text=True, timeout=60)
    assert "cu126" in out.stdout, f"운영 venv torch 가 변경됨: {out.stdout.strip()}"
