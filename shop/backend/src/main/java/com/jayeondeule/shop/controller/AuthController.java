package com.jayeondeule.shop.controller;

import com.jayeondeule.shop.dto.*;
import com.jayeondeule.shop.service.AuthService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/shop/auth")
@RequiredArgsConstructor
public class AuthController {
    private final AuthService authService;

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
        return ResponseEntity.ok(ApiResponse.ok(auth.getPrincipal()));
    }
}
