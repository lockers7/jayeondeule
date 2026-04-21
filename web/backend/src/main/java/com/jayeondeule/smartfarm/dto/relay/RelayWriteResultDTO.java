package com.jayeondeule.smartfarm.dto.relay;

import lombok.Getter;
import lombok.Setter;

import java.util.List;
import java.util.Map;

// ════════════════════════════════════════════════════════════════════════════
// FastAPI 의 인터록 게이트가 적용된 릴레이 쓰기 결과 — 컨트롤러 → 프론트엔드
// 응답 페이로드. interlockViolations 가 비어있지 않으면 프론트는 사용자에게
// "팬을 먼저 OFF 시키세요" 등의 팝업을 표시한다.
// ════════════════════════════════════════════════════════════════════════════
@Getter
@Setter
public class RelayWriteResultDTO {
    private boolean success;
    private String message;
    private Map<String, Boolean> settings;
    private List<Map<String, Object>> interlockViolations;
}
