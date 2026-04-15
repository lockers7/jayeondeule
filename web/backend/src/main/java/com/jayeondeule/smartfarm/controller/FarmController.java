package com.jayeondeule.smartfarm.controller;

import com.jayeondeule.smartfarm.dto.farm.FarmDTO;
import com.jayeondeule.smartfarm.dto.farm.FarmInsertDTO;
import com.jayeondeule.smartfarm.dto.farm.FarmPatchDTO;
import com.jayeondeule.smartfarm.dto.user.UserClaimDTO;
import com.jayeondeule.smartfarm.enums.user.AuthLvel;
import com.jayeondeule.smartfarm.service.FarmService;
import com.jayeondeule.smartfarm.service.UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

//농장 등록, 수정, 조회 관련 API
@RestController
@RequestMapping("/api/farms")
@RequiredArgsConstructor
public class FarmController {
    private final FarmService farmService;
    private final UserService userService;

    //농장 등록 (ADMIN만)
    @PostMapping
    public void insertFarm(@RequestBody FarmInsertDTO insertInfo,
                           @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo != null) {
            if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
                farmService.insertFarm(insertInfo);
            }
        }
    }

    //농장 리스트 (ADMIN만 — 삭제 포함 전체)
    @GetMapping
    public ResponseEntity<Page<FarmDTO>> getFarmList(
            @AuthenticationPrincipal UserClaimDTO userInfo,
            @RequestParam int page,
            @RequestParam int size) {
        if (userInfo != null) {
            if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
                return ResponseEntity.ok(farmService.getAllFarmsAll(page, size));
            }
        }
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(null);
    }

    @GetMapping("/me")
    public ResponseEntity<FarmDTO> getMyFarm(@AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo != null) {
            return ResponseEntity.ok(farmService.getFarmByUserId(userInfo.getUserId()));
        }
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(null);
    }

    @GetMapping("/{farmId}")
    public ResponseEntity<FarmDTO> getFarm(@PathVariable Long farmId,
                                           @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo != null) {
            if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN) ||
                    farmService.getFarmByUserId(userInfo.getUserId()).getFarmId() == farmId) {
                return ResponseEntity.ok(farmService.getFarmByFarmId(farmId));
            }
        }
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(null);
    }

    //농장 정보 수정 (ADMIN: 모든 농장, FARM_ADMIN: 자기 농장만)
    @PatchMapping("/{farmId}")
    public void patchFarm(@RequestBody FarmPatchDTO modifiedInfo,
                          @PathVariable Long farmId,
                          @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo == null) return;
        if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
            farmService.patchFarmByFarmId(farmId, modifiedInfo);
        } else {
            long myFarmId = userService.getUserOwnedFarmId(userInfo.getUserId());
            if (myFarmId == farmId) {
                farmService.patchFarmByFarmId(farmId, modifiedInfo);
            }
        }
    }

    //농장 삭제 (ADMIN만 — soft delete)
    @DeleteMapping("/{farmId}")
    public ResponseEntity<Void> deleteFarm(@PathVariable Long farmId,
                           @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo == null) return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
            farmService.deleteFarmByFarmId(farmId);
            return ResponseEntity.ok().build();
        }
        return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
    }

    //농장 복원 (ADMIN만 — dlteYn='N')
    @PatchMapping("/{farmId}/restore")
    public ResponseEntity<Void> restoreFarm(@PathVariable Long farmId,
                                             @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo == null) return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
            farmService.restoreFarm(farmId);
            return ResponseEntity.ok().build();
        }
        return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
    }

    //농장 완전 삭제 (ADMIN만 — hard delete)
    @DeleteMapping("/{farmId}/hard")
    public ResponseEntity<Void> hardDeleteFarm(@PathVariable Long farmId,
                                                @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo == null) return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
            farmService.hardDeleteFarm(farmId);
            return ResponseEntity.ok().build();
        }
        return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
    }
}
