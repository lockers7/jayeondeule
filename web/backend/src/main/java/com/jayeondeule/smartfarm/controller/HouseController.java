package com.jayeondeule.smartfarm.controller;

import com.jayeondeule.smartfarm.dto.house.*;
import com.jayeondeule.smartfarm.dto.house.FarmHousePatchDTO;
import com.jayeondeule.smartfarm.dto.user.UserClaimDTO;
import com.jayeondeule.smartfarm.enums.user.AuthLvel;
import com.jayeondeule.smartfarm.service.HouseService;
import com.jayeondeule.smartfarm.service.UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

//재배사 등록, 모니터링, 설정 API
@RestController
@RequestMapping("/api/farms/{farmId}/houses")
@RequiredArgsConstructor
public class HouseController {

    private final HouseService houseService;
    private final UserService userService;

    //재배사 등록 (ADMIN: 모든 농장, 비admin: 자기 농장만)
    @PostMapping
    public ResponseEntity<Void> insertFarmHouse(@RequestBody FarmHouseInsertDTO insertInfo,
                                @PathVariable Long farmId,
                                @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo == null) return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
            houseService.insertHouse(insertInfo);
            return ResponseEntity.ok().build();
        } else {
            // housId=0은 시스템관리자만 생성 가능
            if (insertInfo.getHousId() == 0) {
                return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
            }
            long myFarmId = userService.getUserOwnedFarmId(userInfo.getUserId());
            if (myFarmId == farmId) {
                houseService.insertHouse(insertInfo);
                return ResponseEntity.ok().build();
            }
        }
        return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
    }

    //다음 재배사 번호 조회 (등록 폼 기본값 표시용)
    @GetMapping("/next-id")
    public ResponseEntity<Long> getNextHousId(@PathVariable Long farmId,
                                               @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo != null) {
            return ResponseEntity.ok(houseService.getNextHousId(farmId));
        }
        return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
    }

    //농장의 재배사 조회 (ADMIN: 삭제 포함 전체, 비admin: 정상만)
    @GetMapping
    public ResponseEntity<List<FarmHouseDTO>> getFarmHouse(@PathVariable Long farmId,
                                                           @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo != null) {
            if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
                return ResponseEntity.ok(houseService.getHouseListAll(farmId));
            } else if (userService.getUserOwnedFarmId(userInfo.getUserId()) == farmId) {
                return ResponseEntity.ok(houseService.getHouseList(farmId));
            }
        }
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(null);
    }

    //농장의 특정 재배사 조회
    @GetMapping("/{houseId}")
    public ResponseEntity<FarmHouseDTO> getFarmHouse(@PathVariable Long farmId,
                                     @PathVariable Long houseId,
                                     @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo != null) {
            if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN) ||
                    userService.getUserOwnedFarmId(userInfo.getUserId()) == farmId) {
                return ResponseEntity.ok(houseService.getHouse(farmId, houseId));
            }
        }
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(null);
    }

    //재배사 정보 수정
    @PatchMapping("/{houseId}")
    public ResponseEntity<Void> patchFarmHouse(@RequestBody FarmHousePatchDTO modifiedInfo,
                               @PathVariable Long farmId,
                               @PathVariable Long houseId,
                               @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo == null) return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        // housId 변경은 ADMIN만 허용
        if (!userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
            modifiedInfo.setNewHousId(null);
        }
        if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN) ||
                userService.getUserOwnedFarmId(userInfo.getUserId()) == farmId) {
            houseService.patchHouse(modifiedInfo, farmId, houseId);
            return ResponseEntity.ok().build();
        }
        return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
    }

    //재배사 삭제 — soft delete (ADMIN: 모든 농장, FARM_ADMIN: 자기 농장만)
    @DeleteMapping("/{houseId}")
    public ResponseEntity<Void> deleteFarmHouse(@PathVariable Long farmId,
                                @PathVariable Long houseId,
                                @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo == null) return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
            houseService.deleteHouse(farmId, houseId);
            return ResponseEntity.ok().build();
        } else if (userInfo.getAuthLvel().equals(AuthLvel.FARM_ADMIN)) {
            long myFarmId = userService.getUserOwnedFarmId(userInfo.getUserId());
            if (myFarmId == farmId) {
                houseService.deleteHouse(farmId, houseId);
                return ResponseEntity.ok().build();
            }
        }
        return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
    }

    //관리자에 의한 재배사 복원 (dlteYn='N')
    @PatchMapping("/{houseId}/restore")
    public void restoreHouse(@PathVariable Long farmId,
                             @PathVariable Long houseId,
                             @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo == null) return;
        if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
            houseService.restoreHouse(farmId, houseId);
        }
    }

    //관리자에 의한 재배사 완전 삭제 (hard delete)
    @DeleteMapping("/{houseId}/hard")
    public ResponseEntity<Void> hardDeleteHouse(@PathVariable Long farmId,
                                                @PathVariable Long houseId,
                                                @AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo == null) return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
            houseService.hardDeleteHouse(farmId, houseId);
            return ResponseEntity.ok().build();
        }
        return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
    }
}
