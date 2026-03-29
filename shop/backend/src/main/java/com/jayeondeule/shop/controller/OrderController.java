package com.jayeondeule.shop.controller;

import com.jayeondeule.shop.dto.*;
import com.jayeondeule.shop.service.OrderService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/shop/orders")
@RequiredArgsConstructor
public class OrderController {
    private final OrderService orderService;

    @PostMapping
    public ResponseEntity<?> create(Authentication auth, @Valid @RequestBody OrderRequest req) {
        try {
            var order = orderService.createOrder(auth.getPrincipal().toString(), req);
            return ResponseEntity.ok(ApiResponse.ok("주문이 완료되었습니다.", order));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
    }

    @GetMapping
    public ResponseEntity<?> myOrders(Authentication auth) {
        return ResponseEntity.ok(ApiResponse.ok(orderService.getMyOrders(auth.getPrincipal().toString())));
    }

    @GetMapping("/{orderId}")
    public ResponseEntity<?> detail(@PathVariable String orderId) {
        return ResponseEntity.ok(ApiResponse.ok(orderService.getOrder(orderId)));
    }

    @PatchMapping("/{orderId}/cancel")
    public ResponseEntity<?> cancel(@PathVariable String orderId, @RequestBody(required = false) java.util.Map<String, String> body) {
        try {
            String reason = body != null ? body.get("reason") : null;
            return ResponseEntity.ok(ApiResponse.ok(orderService.updateOrderStatus(orderId, "CANCELLED", reason)));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
    }
}
