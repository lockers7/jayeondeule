package com.jayeondeule.shop.controller;

import com.jayeondeule.shop.dto.*;
import com.jayeondeule.shop.entity.ShopUser;
import com.jayeondeule.shop.repository.ShopOrderRepository;
import com.jayeondeule.shop.repository.ShopUserRepository;
import com.jayeondeule.shop.service.OrderService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController
@RequestMapping("/api/shop/orders")
@RequiredArgsConstructor
public class OrderController {
    private final OrderService orderService;
    private final ShopOrderRepository orderRepo;
    private final ShopUserRepository userRepo;

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

    // 배송지 이력 (최근 5개 고유 배송지) + 회원 기본 주소
    @GetMapping("/shipping-info")
    public ResponseEntity<?> shippingInfo(Authentication auth) {
        String userId = auth.getPrincipal().toString();
        ShopUser user = userRepo.findById(userId).orElse(null);

        // 회원 기본 주소
        Map<String, String> defaultAddr = new HashMap<>();
        if (user != null) {
            defaultAddr.put("receiverName", user.getUsrName() != null ? user.getUsrName() : "");
            defaultAddr.put("receiverPhone", user.getPhone() != null ? user.getPhone() : "");
            defaultAddr.put("zipcode", user.getZipcode() != null ? user.getZipcode() : "");
            defaultAddr.put("address", user.getAddress() != null ? user.getAddress() : "");
            defaultAddr.put("addressDetail", user.getAddressDetail() != null ? user.getAddressDetail() : "");
        }

        // 최근 배송지 이력
        List<Map<String, String>> history = new ArrayList<>();
        List<Object[]> rows = orderRepo.findRecentAddresses(userId);
        for (Object[] row : rows) {
            Map<String, String> addr = new HashMap<>();
            addr.put("receiverName", row[0] != null ? row[0].toString() : "");
            addr.put("receiverPhone", row[1] != null ? row[1].toString() : "");
            addr.put("zipcode", row[2] != null ? row[2].toString() : "");
            addr.put("address", row[3] != null ? row[3].toString() : "");
            addr.put("addressDetail", row[4] != null ? row[4].toString() : "");
            addr.put("memo", row[5] != null ? row[5].toString() : "");
            history.add(addr);
        }

        Map<String, Object> result = new HashMap<>();
        result.put("defaultAddress", defaultAddr);
        result.put("history", history);
        return ResponseEntity.ok(ApiResponse.ok(result));
    }

    // 제품수령 확인 (고객이 배송완료 상태에서 수령 확인)
    @PatchMapping("/{orderId}/receive")
    public ResponseEntity<?> receive(Authentication auth, @PathVariable String orderId) {
        try {
            var order = orderService.getOrder(orderId);
            if (!order.getShopUsrId().equals(auth.getPrincipal().toString())) {
                return ResponseEntity.status(403).body(ApiResponse.error("권한이 없습니다."));
            }
            if (!"DELIVERED".equals(order.getOrderStatus())) {
                return ResponseEntity.badRequest().body(ApiResponse.error("배송완료 상태에서만 수령 확인이 가능합니다."));
            }
            return ResponseEntity.ok(ApiResponse.ok("제품수령이 확인되었습니다.", orderService.updateOrderStatus(orderId, "RECEIVED", null)));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(ApiResponse.error(e.getMessage()));
        }
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
