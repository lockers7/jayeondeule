package com.jayeondeule.smartfarm.controller;

import com.jayeondeule.smartfarm.dto.relay.RelayDTO;
import com.jayeondeule.smartfarm.dto.relay.RelayInsertDTO;
import com.jayeondeule.smartfarm.dto.relay.RelayWriteResultDTO;
import com.jayeondeule.smartfarm.dto.user.UserClaimDTO;
import com.jayeondeule.smartfarm.enums.user.AuthLvel;
import com.jayeondeule.smartfarm.service.FarmService;
import com.jayeondeule.smartfarm.service.RelayService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

//릴레이 동장(수동 및 알고리즘 제어) API
@RestController
@RequestMapping("/api/farms/{farmId}/houses/{houseId}/relays")
@RequiredArgsConstructor
public class RelayController {
    private final RelayService relayService;
    private final FarmService farmService;

    //릴레이 동작 상태 조회
    @GetMapping
    public ResponseEntity<RelayDTO> getRelay(@PathVariable Long farmId,
                                             @PathVariable Long houseId,
                                             @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo != null) {
            if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN) ||
                    farmService.getFarmByUserId(userInfo.getUserId()).getFarmId() == farmId) {
                return ResponseEntity.ok(relayService.getRelay(farmId, houseId));
            }
        }

        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(null);
    }

    //릴레이 상태 변경 — FastAPI 인터록 게이트 경유 → 결과/위반사유 반환
    @PostMapping
    public ResponseEntity<RelayWriteResultDTO> insertRelay(@RequestBody RelayInsertDTO relayInfo,
                                                            @PathVariable Long farmId,
                                                            @PathVariable Long houseId,
                                                            @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo != null) {
            if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN) ||
                    farmService.getFarmByUserId(userInfo.getUserId()).getFarmId() == farmId) {
                RelayWriteResultDTO result = relayService.insertRelay(farmId, houseId, relayInfo);
                return ResponseEntity.ok(result);
            }
        }
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(null);
    }
}
