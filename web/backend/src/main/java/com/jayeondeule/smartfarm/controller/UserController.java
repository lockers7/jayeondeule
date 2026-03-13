package com.jayeondeule.smartfarm.controller;

import com.jayeondeule.smartfarm.dto.user.*;
import com.jayeondeule.smartfarm.enums.user.AuthLvel;
import com.jayeondeule.smartfarm.service.UserService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

//회원가입, 로그인 등 사용자 관련 API 엔드포인트
@RestController
@RequestMapping("/api/users")
@RequiredArgsConstructor
public class UserController {
    private final UserService userService;

    //회원가입
    @PostMapping
    public void insertUser(@RequestBody @Valid UserInsertDTO userInfo) {
        userService.insertUser(userInfo);
    }

    //아이디 회원정보 리스트 조회
    @GetMapping
    public ResponseEntity<Page<UserDTO>> getUsers(@AuthenticationPrincipal UserClaimDTO userInfo,
                                                  @RequestParam int page,
                                                  @RequestParam int size,
                                                  @RequestParam long searchQuery) {
        if (userInfo == null) {
            return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(null);
        }
        // admin: 전체 조회 (삭제 포함)
        if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
            if (searchQuery == -1) {
                return ResponseEntity.ok(userService.getUsersAll(page, size));
            } else {
                return ResponseEntity.ok(userService.getUsersAll(page, size, searchQuery));
            }
        }
        // 비admin: 자기 소속 농장 사용자만 조회
        long myFarmId = userService.getUserOwnedFarmId(userInfo.getUserId());
        if (myFarmId > 0) {
            return ResponseEntity.ok(userService.getUsers(page, size, myFarmId));
        }
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(null);
    }

    @GetMapping("/me")
    public ResponseEntity<UserDTO> getUser(@AuthenticationPrincipal UserClaimDTO userInfo) {
        if (userInfo != null) {
            return ResponseEntity.ok(userService.getUser(userInfo.getUserId()));
        }
        return ResponseEntity
                .status(HttpStatus.BAD_REQUEST)
                .body(null);
    }

    //아이디 중복 확인
    @GetMapping("/id-dupl-check")
    public ResponseEntity<Boolean> idDuplicationCheck(@RequestParam String userId) {
        return ResponseEntity.ok(userService.idDuplicationCheck(userId));
    }

    //회원정보 수정 (자기 자신)
    @PatchMapping
    public void patchUser(@AuthenticationPrincipal UserClaimDTO userInfo,
                          @RequestBody @Valid UserPatchDTO modifiedInfo) {
        if (userInfo != null) {
            userService.patchUser(modifiedInfo, userInfo.getUserId());
        }
    }

    //관리자/농장관리자에 의한 특정 사용자 정보 수정
    @PatchMapping("/{userId}/info")
    public void patchUserInfo(@AuthenticationPrincipal UserClaimDTO userInfo,
                              @PathVariable String userId,
                              @RequestBody @Valid UserPatchDTO modifiedInfo) {
        if (userInfo == null) return;
        if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
            userService.patchUser(modifiedInfo, userId);
        } else if (userInfo.getAuthLvel().equals(AuthLvel.FARM_ADMIN)) {
            long myFarmId = userService.getUserOwnedFarmId(userInfo.getUserId());
            long targetFarmId = userService.getUserOwnedFarmId(userId);
            if (myFarmId > 0 && myFarmId == targetFarmId) {
                userService.patchUser(modifiedInfo, userId);
            }
        }
    }

    //회원 농장 접근 권한 부여 (admin: 전체, FARM_ADMIN: 자기 농장 소속만)
    @PatchMapping("/{userId}")
    public void patchUserFarmId(@AuthenticationPrincipal UserClaimDTO userInfo,
                                @PathVariable String userId,
                                @RequestBody @Valid UserFarmIdPatchDTO modifiedInfo) {
        if (userInfo == null) return;
        if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
            userService.patchUserFarmId(modifiedInfo, userId);
        } else if (userInfo.getAuthLvel().equals(AuthLvel.FARM_ADMIN)) {
            // FARM_ADMIN은 자기 농장 소속 또는 미배정(farmId=0) 사용자를 자기 농장에 배정 가능
            long myFarmId = userService.getUserOwnedFarmId(userInfo.getUserId());
            long targetFarmId = userService.getUserOwnedFarmId(userId);
            long requestedFarmId = modifiedInfo.getFarmId() != null ? modifiedInfo.getFarmId() : 0;
            if (myFarmId > 0 && (myFarmId == targetFarmId || targetFarmId == 0)
                    && (requestedFarmId == myFarmId || requestedFarmId == 0)) {
                userService.patchUserFarmId(modifiedInfo, userId);
            }
        }
    }

    //비밀번호 변경
    @PatchMapping("/password")
    public ResponseEntity<String> patchUserPassword(@AuthenticationPrincipal UserClaimDTO userInfo,
                                                    @RequestBody UserPasswordPatchDTO passwordInfo) {
        if (userInfo != null) {
            if (userService.patchUserPassword(passwordInfo, userInfo.getUserId())) {
                return ResponseEntity.ok(null);
            } else {
                return ResponseEntity
                        .status(HttpStatus.BAD_REQUEST)
                        .body("현재 비밀번호가 일치하지 않습니다.");
            }
        } else {
            return ResponseEntity
                    .status(HttpStatus.BAD_REQUEST)
                    .body("Invalid Token.");
        }
    }

    //회원탈퇴 (자기 자신)
    @DeleteMapping
    public void deleteUser(@AuthenticationPrincipal UserClaimDTO userInfo) {
        if(userInfo != null) {
            userService.deleteUser(userInfo.getUserId());
        }
    }

    //관리자/농장관리자에 의한 특정 사용자 삭제 (soft delete)
    @DeleteMapping("/{userId}")
    public ResponseEntity<Void> deleteUserById(@AuthenticationPrincipal UserClaimDTO userInfo,
                               @PathVariable String userId) {
        if (userInfo == null) return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
            userService.deleteUser(userId);
            return ResponseEntity.ok().build();
        } else if (userInfo.getAuthLvel().equals(AuthLvel.FARM_ADMIN)) {
            long myFarmId = userService.getUserOwnedFarmId(userInfo.getUserId());
            long targetFarmId = userService.getUserOwnedFarmId(userId);
            if (myFarmId > 0 && myFarmId == targetFarmId) {
                userService.deleteUser(userId);
                return ResponseEntity.ok().build();
            }
        }
        return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
    }

    //관리자에 의한 사용자 복원 (dlteYn='N')
    @PatchMapping("/{userId}/restore")
    public void restoreUser(@AuthenticationPrincipal UserClaimDTO userInfo,
                            @PathVariable String userId) {
        if (userInfo == null) return;
        if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
            userService.restoreUser(userId);
        }
    }

    //관리자에 의한 사용자 완전 삭제 (hard delete)
    @DeleteMapping("/{userId}/hard")
    public ResponseEntity<Void> hardDeleteUser(@AuthenticationPrincipal UserClaimDTO userInfo,
                                               @PathVariable String userId) {
        if (userInfo == null) return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        if (userInfo.getAuthLvel().equals(AuthLvel.ADMIN)) {
            userService.hardDeleteUser(userId);
            return ResponseEntity.ok().build();
        }
        return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
    }
}
