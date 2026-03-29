package com.jayeondeule.shop.controller;

import com.jayeondeule.shop.dto.ApiResponse;
import com.jayeondeule.shop.entity.ShopProduct;
import com.jayeondeule.shop.repository.ShopCategoryRepository;
import com.jayeondeule.shop.service.ProductService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/shop")
@RequiredArgsConstructor
public class ProductController {
    private final ProductService productService;
    private final ShopCategoryRepository categoryRepo;

    @GetMapping("/products")
    public ResponseEntity<?> list(@RequestParam(defaultValue = "1") Long farmId) {
        return ResponseEntity.ok(ApiResponse.ok(productService.getOnSaleProducts(farmId)));
    }

    @GetMapping("/products/{id}")
    public ResponseEntity<?> detail(@PathVariable Integer id) {
        return ResponseEntity.ok(ApiResponse.ok(productService.getProductWithView(id)));
    }

    @GetMapping("/categories")
    public ResponseEntity<?> categories(@RequestParam(defaultValue = "1") Long farmId) {
        return ResponseEntity.ok(ApiResponse.ok(categoryRepo.findByFarmIdAndUseYnOrderBySortOrder(farmId, "Y")));
    }
}
