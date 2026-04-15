package com.jayeondeule.shop.controller;

import com.jayeondeule.shop.dto.ApiResponse;
import com.jayeondeule.shop.entity.ShopProduct;
import com.jayeondeule.shop.entity.ShopUser;
import com.jayeondeule.shop.repository.ShopUserRepository;
import com.jayeondeule.shop.service.OrderService;
import com.jayeondeule.shop.service.ProductService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import java.util.Map;

@RestController
@RequestMapping("/api/shop/admin")
@RequiredArgsConstructor
public class AdminController {
    private final OrderService orderService;
    private final ProductService productService;
    private final ShopUserRepository userRepo;

    // ========== 대시보드 ==========
    @GetMapping("/dashboard")
    public ResponseEntity<?> dashboard(@RequestParam(defaultValue = "1") Long farmId) {
        return ResponseEntity.ok(ApiResponse.ok(orderService.getDashboardStats(farmId)));
    }

    // ========== 주문 관리 ==========
    @GetMapping("/orders")
    public ResponseEntity<?> orders(@RequestParam(defaultValue = "1") Long farmId) {
        return ResponseEntity.ok(ApiResponse.ok(orderService.getOrdersByFarm(farmId)));
    }

    @PatchMapping("/orders/{orderId}/status")
    public ResponseEntity<?> updateStatus(@PathVariable String orderId, @RequestBody Map<String, String> body) {
        try {
            return ResponseEntity.ok(ApiResponse.ok(
                    orderService.updateOrderStatus(orderId, body.get("status"), body.get("reason"))));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
    }

    @PatchMapping("/orders/{orderId}/tracking")
    public ResponseEntity<?> updateTracking(@PathVariable String orderId, @RequestBody Map<String, String> body) {
        return ResponseEntity.ok(ApiResponse.ok(orderService.updateTrackingNo(orderId, body.get("trackingNo"))));
    }

    // ========== 상품 관리 ==========
    @GetMapping("/products")
    public ResponseEntity<?> allProducts(@RequestParam(defaultValue = "1") Long farmId) {
        return ResponseEntity.ok(ApiResponse.ok(productService.getProducts(farmId)));
    }

    @PostMapping("/products")
    public ResponseEntity<?> createProduct(@RequestBody ShopProduct product) {
        return ResponseEntity.ok(ApiResponse.ok(productService.saveProduct(product)));
    }

    @PutMapping("/products/{id}")
    public ResponseEntity<?> updateProduct(@PathVariable Integer id, @RequestBody ShopProduct product) {
        product.setProductId(id);
        return ResponseEntity.ok(ApiResponse.ok(productService.saveProduct(product)));
    }

    // 상품 이미지 업로드
    @PostMapping("/products/{id}/image")
    public ResponseEntity<?> uploadProductImage(@PathVariable Integer id, @RequestParam("file") MultipartFile file) {
        try {
            String url = productService.uploadProductImage(id, file);
            return ResponseEntity.ok(ApiResponse.ok("이미지가 업로드되었습니다.", Map.of("imageUrl", url)));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
    }

    @DeleteMapping("/products/{id}")
    public ResponseEntity<?> deleteProduct(@PathVariable Integer id) {
        productService.deleteProduct(id);
        return ResponseEntity.ok(ApiResponse.ok("상품이 판매중지 되었습니다.", null));
    }

    // ========== 회원 관리 ==========
    @GetMapping("/members")
    public ResponseEntity<?> members(@RequestParam(defaultValue = "1") Long farmId) {
        return ResponseEntity.ok(ApiResponse.ok(
                userRepo.findByFarmIdAndUsrStatusOrderByRgstDtDesc(farmId, "ACTIVE")));
    }

    @PatchMapping("/members/{userId}/grade")
    public ResponseEntity<?> changeGrade(@PathVariable String userId, @RequestBody Map<String, String> body) {
        ShopUser user = userRepo.findById(userId).orElseThrow(() -> new RuntimeException("회원 없음"));
        user.setUsrGrade(body.get("grade"));
        userRepo.save(user);
        return ResponseEntity.ok(ApiResponse.ok("회원등급이 변경되었습니다.", null));
    }
}
