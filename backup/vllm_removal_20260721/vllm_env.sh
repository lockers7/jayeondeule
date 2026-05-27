#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# vLLM 실행 환경 (별도 venv — 운영 venv 와 완전 분리)
#
# 2026-07-17 실측으로 확정한 조합. 하나라도 어긋나면 기동 실패한다:
#   · RTX 5060 Ti = Blackwell sm_120 → CUDA 13 필요 (운영 venv 의 cu126 은 sm_90 까지)
#   · torch 2.11.0+cu130 — vLLM 0.25.1 이 빌드된 버전. 임의 상향 시 flash attention
#     확장(_vllm_fa2_C) ABI 불일치로 ImportError.
#   · CUDA_HOME — 시스템 nvcc 는 12.0 이라 flashinfer 가 "SM 12.x requires CUDA >= 12.9"
#     로 거부한다. venv 내장 nvcc 13.2 를 가리켜야 한다.
#   · VLLM_USE_FLASHINFER_SAMPLER=0 — flashinfer JIT 가 시스템 /usr/include 의
#     CUDA 12.0 헤더를 먼저 잡아 nvcc 13.2 와 충돌("headers are incompatible").
#   · CUDA_DEVICE_ORDER/VISIBLE_DEVICES — GPU1(1660 SUPER sm_75) 이 섞이면 경고·오동작.
#
# ⛔ Ollama 와 동시 가동 불가 (GPU 메모리). 전환 시 Ollama 정지 필요.
# ══════════════════════════════════════════════════════════════════════════════
export CUDA_HOME="/workspace/jayeondeule/venv_vllm/lib/python3.12/site-packages/nvidia/cu13"
export VLLM_USE_FLASHINFER_SAMPLER=0
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES=0
export VLLM_VENV="/workspace/jayeondeule/venv_vllm"
