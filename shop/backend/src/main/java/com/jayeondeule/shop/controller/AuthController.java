package com.jayeondeule.shop.controller;

import com.jayeondeule.shop.dto.*;
import com.jayeondeule.shop.entity.ShopUser;
import com.jayeondeule.shop.repository.ShopUserRepository;
import com.jayeondeule.shop.service.AuthService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import java.util.HashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/shop/auth")
@RequiredArgsConstructor
public class AuthController {
    private final AuthService authService;
    private final ShopUserRepository userRepo;

    @PostMapping("/login")
    public ResponseEntity<?> login(@Valid @RequestBody LoginRequest req) {
        try {
            return ResponseEntity.ok(ApiResponse.ok("로그인 성공", authService.login(req)));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
    }

    @PostMapping("/register")
    public ResponseEntity<?> register(@Valid @RequestBody RegisterRequest req) {
        try {
            authService.register(req);
            return ResponseEntity.ok(ApiResponse.ok("회원가입 성공", null));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
    }

    @GetMapping("/check-id")
    public ResponseEntity<?> checkId(@RequestParam String id) {
        return ResponseEntity.ok(ApiResponse.ok(authService.checkIdAvailable(id)));
    }

    @GetMapping("/me")
    public ResponseEntity<?> me(Authentication auth) {
        if (auth == null) return ResponseEntity.status(401).body(ApiResponse.error("인증 필요"));
        String userId = auth.getPrincipal().toString();
        ShopUser user = userRepo.findById(userId).orElse(null);
        if (user == null) return ResponseEntity.ok(ApiResponse.ok(userId));
        Map<String, Object> info = new HashMap<>();
        info.put("shopUsrId", user.getShopUsrId());
        info.put("usrName", user.getUsrName());
        info.put("usrGrade", user.getUsrGrade());
        info.put("farmId", user.getFarmId());
        info.put("phone", user.getPhone() != null ? user.getPhone() : "");
        info.put("email", user.getEmail() != null ? user.getEmail() : "");
        info.put("zipcode", user.getZipcode() != null ? user.getZipcode() : "");
        info.put("address", user.getAddress() != null ? user.getAddress() : "");
        info.put("addressDetail", user.getAddressDetail() != null ? user.getAddressDetail() : "");
        return ResponseEntity.ok(ApiResponse.ok(info));
    }

    // 비밀번호 변경
    @PatchMapping("/password")
    public ResponseEntity<?> changePassword(Authentication auth, @RequestBody Map<String, String> body) {
        if (auth == null) return ResponseEntity.status(401).body(ApiResponse.error("인증 필요"));
        try {
            authService.changePassword(auth.getPrincipal().toString(), body.get("currentPassword"), body.get("newPassword"));
            return ResponseEntity.ok(ApiResponse.ok("비밀번호가 변경되었습니다.", null));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
    }

    // 회원정보 수정 (이름, 연락처, 이메일, 주소)
    @PutMapping("/me")
    public ResponseEntity<?> updateMe(Authentication auth, @RequestBody Map<String, String> body) {
        if (auth == null) return ResponseEntity.status(401).body(ApiResponse.error("인증 필요"));
        String userId = auth.getPrincipal().toString();
        ShopUser user = userRepo.findById(userId)
                .orElseThrow(() -> new RuntimeException("회원 정보를 찾을 수 없습니다."));

        if (body.containsKey("usrName")) user.setUsrName(body.get("usrName"));
        if (body.containsKey("phone")) user.setPhone(body.get("phone"));
        if (body.containsKey("email")) user.setEmail(body.get("email"));
        if (body.containsKey("zipcode")) user.setZipcode(body.get("zipcode"));
        if (body.containsKey("address")) user.setAddress(body.get("address"));
        if (body.containsKey("addressDetail")) user.setAddressDetail(body.get("addressDetail"));

        userRepo.save(user);

        // localStorage 갱신용으로 최신 userInfo 반환
        Map<String, Object> info = new HashMap<>();
        info.put("shopUsrId", user.getShopUsrId());
        info.put("usrName", user.getUsrName());
        info.put("usrGrade", user.getUsrGrade());
        info.put("farmId", user.getFarmId());
        info.put("phone", user.getPhone() != null ? user.getPhone() : "");
        info.put("email", user.getEmail() != null ? user.getEmail() : "");
        info.put("zipcode", user.getZipcode() != null ? user.getZipcode() : "");
        info.put("address", user.getAddress() != null ? user.getAddress() : "");
        info.put("addressDetail", user.getAddressDetail() != null ? user.getAddressDetail() : "");
        return ResponseEntity.ok(ApiResponse.ok("회원정보가 수정되었습니다.", info));
    }
}
