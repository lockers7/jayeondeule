package com.jayeondeule.shop.controller;

import com.jayeondeule.shop.dto.ApiResponse;
import com.jayeondeule.shop.repository.ShopCategoryRepository;
import com.jayeondeule.shop.service.ProductService;
import com.jayeondeule.shop.util.JwtUtil;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/shop")
@RequiredArgsConstructor
public class ProductController {
    private final ProductService productService;
    private final ShopCategoryRepository categoryRepo;
    private final JwtUtil jwtUtil;

    @GetMapping("/products")
    public ResponseEntity<?> list(@RequestParam(defaultValue = "1") Long farmId) {
        return ResponseEntity.ok(ApiResponse.ok(productService.getOnSaleProducts(farmId)));
    }

    @GetMapping("/products/{id}")
    public ResponseEntity<?> detail(
            @PathVariable Integer id,
            @RequestHeader(value = "Authorization", required = false) String authHeader,
            HttpServletRequest request) {
        // viewerId: 로그인 사용자는 userId, 비로그인은 IP
        String viewerId = null;
        if (authHeader != null && authHeader.startsWith("Bearer ")) {
            try { viewerId = jwtUtil.getUserId(authHeader.substring(7)); } catch (Exception ignored) {}
        }
        if (viewerId == null || viewerId.isEmpty()) {
            String xff = request.getHeader("X-Forwarded-For");
            viewerId = (xff != null && !xff.isEmpty()) ? xff.split(",")[0].trim() : request.getRemoteAddr();
        }
        return ResponseEntity.ok(ApiResponse.ok(productService.getProductWithView(id, viewerId)));
    }

    @GetMapping("/products/{id}/view-stats")
    public ResponseEntity<?> productViewStats(@PathVariable Integer id) {
        return ResponseEntity.ok(ApiResponse.ok(productService.getProductViewStats(id)));
    }

    @GetMapping("/products/view-ranking")
    public ResponseEntity<?> productViewRanking() {
        return ResponseEntity.ok(ApiResponse.ok(productService.getProductViewRanking()));
    }

    @GetMapping("/categories")
    public ResponseEntity<?> categories(@RequestParam(defaultValue = "1") Long farmId) {
        return ResponseEntity.ok(ApiResponse.ok(categoryRepo.findByFarmIdAndUseYnOrderBySortOrder(farmId, "Y")));
    }
}
