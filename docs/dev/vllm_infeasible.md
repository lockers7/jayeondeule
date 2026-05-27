# vLLM 백엔드 — 제거 사유 / ⛔재착수 금지

2026-07-21. Ollama 대체 백엔드로 vLLM 을 시도했으나 **16GB VRAM 한계로 무의미**하여
코드·패키지를 전부 제거했다.

## 사유 (⛔ 재착수 금지)
- 목표: Ollama Q4_K_M 보다 나은 양자화(예: 27b w4a16)로 품질↑.
- 그러나 **27b w4a16 = 18.33 GiB > 사용가능 15.13 GiB (RTX 5060 Ti 16GB)**.
- 즉 **병목은 엔진(vLLM)이 아니라 VRAM.** vLLM 로 바꿔도 더 나은 모델을 못 올린다.
- Blackwell(sm_120) vLLM 빌드 함정 4개는 해결했으나(구동 자체는 가능), VRAM 벽 때문에
  효용 0. **현행 Ollama gemma3:27b Q4_K_M 이 이 하드웨어의 최적해.**
- VRAM 이 늘지 않는 한 결론 동일 → 재시도는 시간 낭비.

## 되돌리려면
- git: `6ee65e8 feat(vllm): Ollama 대체 vLLM backend 추상화` 복원.
- 백업: `backup/vllm_removal_20260721/` (삭제 파일 + 패키지 버전 목록 removed_packages.txt).
