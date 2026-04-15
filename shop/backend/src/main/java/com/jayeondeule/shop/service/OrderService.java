package com.jayeondeule.shop.service;

import com.jayeondeule.shop.dto.OrderRequest;
import com.jayeondeule.shop.entity.*;
import com.jayeondeule.shop.repository.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;

@Slf4j
@Service
@RequiredArgsConstructor
public class OrderService {
    private final ShopOrderRepository orderRepo;
    private final BoardPostRepository boardPostRepo;
    private final ShopOrderItemRepository orderItemRepo;
    private final ShopProductRepository productRepo;
    private final ShopUserRepository userRepo;

    @Transactional
    public ShopOrder createOrder(String userId, OrderRequest req) {
        ShopUser user = userRepo.findById(userId)
                .orElseThrow(() -> new RuntimeException("회원 정보를 찾을 수 없습니다."));

        String orderId = generateOrderId();
        long totalAmount = 0;
        List<ShopOrderItem> items = new ArrayList<>();

        for (OrderRequest.OrderItemRequest itemReq : req.getItems()) {
            ShopProduct product = productRepo.findById(itemReq.getProductId())
                    .orElseThrow(() -> new RuntimeException("상품을 찾을 수 없습니다: " + itemReq.getProductId()));

            int decreased = productRepo.decreaseStock(product.getProductId(), itemReq.getQuantity());
            if (decreased == 0)
                throw new RuntimeException("재고가 부족합니다: " + product.getProductName());
            productRepo.increaseSellingQty(product.getProductId(), itemReq.getQuantity());
            // 재고 0이면 품절 처리 (JPQL 직접 — JPA 캐시 무관)
            productRepo.markSoldOutIfEmpty(product.getProductId());

            long subtotal = product.getPrice() * itemReq.getQuantity();
            totalAmount += subtotal;

            items.add(ShopOrderItem.builder()
                    .orderId(orderId)
                    .productId(product.getProductId())
                    .productName(product.getProductName())
                    .quantity(itemReq.getQuantity())
                    .unitPrice(product.getPrice())
                    .subtotal(subtotal)
                    .build());
        }

        ShopOrder order = ShopOrder.builder()
                .orderId(orderId)
                .farmId(user.getFarmId())
                .shopUsrId(userId)
                .totalAmount(totalAmount)
                .receiverName(req.getReceiverName())
                .receiverPhone(req.getReceiverPhone())
                .zipcode(req.getZipcode())
                .address(req.getAddress())
                .addressDetail(req.getAddressDetail())
                .shippingMemo(req.getShippingMemo())
                .build();

        orderRepo.save(order);
        orderItemRepo.saveAll(items);
        order.setItems(items);
        log.info("[주문생성] orderId={}, userId={}, items={}, totalAmount={}", orderId, userId, items.size(), totalAmount);
        return order;
    }

    public List<ShopOrder> getMyOrders(String userId) {
        return orderRepo.findByShopUsrIdOrderByOrderDtDesc(userId);
    }

    public List<ShopOrder> getOrdersByFarm(Long farmId) {
        return orderRepo.findByFarmIdOrderByOrderDtDesc(farmId);
    }

    public ShopOrder getOrder(String orderId) {
        return orderRepo.findById(orderId)
                .orElseThrow(() -> new RuntimeException("주문을 찾을 수 없습니다."));
    }

    @Transactional
    public ShopOrder updateOrderStatus(String orderId, String status, String reason) {
        ShopOrder order = getOrder(orderId);
        log.info("[주문상태변경] orderId={}, {} -> {}", orderId, order.getOrderStatus(), status);
        order.setOrderStatus(status);
        switch (status) {
            case "PAID" -> { order.setPaymentStatus("PAID"); order.setPaidDt(LocalDateTime.now()); }
            case "PREPARING" -> order.setPreparingDt(LocalDateTime.now());
            case "SHIPPED" -> order.setShippedDt(LocalDateTime.now());
            case "DELIVERED" -> order.setDeliveredDt(LocalDateTime.now());
            case "RECEIVED" -> {
                order.setReceivedDt(LocalDateTime.now());
                // 거래완료: 판매중 감소, 판매완료 증가
                List<ShopOrderItem> receivedItems = orderItemRepo.findByOrderId(orderId);
                for (ShopOrderItem item : receivedItems) {
                    productRepo.decreaseSellingQty(item.getProductId(), item.getQuantity());
                    productRepo.increaseSoldQty(item.getProductId(), item.getQuantity());
                }
            }
            case "CANCELLED" -> {
                order.setCancelledDt(LocalDateTime.now());
                order.setCancelReason(reason);
                // 재고 복원 + 판매중 감소 + 품절→판매중 복원
                List<ShopOrderItem> items = orderItemRepo.findByOrderId(orderId);
                for (ShopOrderItem item : items) {
                    ShopProduct product = productRepo.findById(item.getProductId()).orElse(null);
                    if (product != null) {
                        product.setStockQty(product.getStockQty() + item.getQuantity());
                        productRepo.save(product);
                    }
                    productRepo.decreaseSellingQty(item.getProductId(), item.getQuantity());
                    productRepo.markOnSaleIfRestored(item.getProductId());
                }
            }
        }
        return orderRepo.save(order);
    }

    @Transactional
    public ShopOrder updateTrackingNo(String orderId, String trackingNo) {
        ShopOrder order = getOrder(orderId);
        order.setTrackingNo(trackingNo);
        return orderRepo.save(order);
    }

    public Map<String, Object> getDashboardStats(Long farmId) {
        Map<String, Object> stats = new HashMap<>();
        stats.put("totalOrders", orderRepo.countByFarmIdAndOrderStatus(farmId, "ORDERED"));
        stats.put("paidOrders", orderRepo.countByFarmIdAndOrderStatus(farmId, "PAID"));
        stats.put("preparingOrders", orderRepo.countByFarmIdAndOrderStatus(farmId, "PREPARING"));
        stats.put("shippedOrders", orderRepo.countByFarmIdAndOrderStatus(farmId, "SHIPPED"));
        stats.put("deliveredOrders", orderRepo.countByFarmIdAndOrderStatus(farmId, "DELIVERED"));
        stats.put("receivedOrders", orderRepo.countByFarmIdAndOrderStatus(farmId, "RECEIVED"));
        stats.put("cancelledOrders", orderRepo.countByFarmIdAndOrderStatus(farmId, "CANCELLED"));
        stats.put("totalRevenue", orderRepo.sumPaidAmountByFarmId(farmId));
        stats.put("totalMembers", userRepo.countByFarmIdAndUsrGradeAndUsrStatus(farmId, "MEMBER", "ACTIVE"));
        stats.put("productRanking", orderItemRepo.productSalesRanking(farmId));
        // 문의 게시판 현황
        int totalInquiries = boardPostRepo.countByBoardTypeAndDelYn("INQUIRY", "N");
        int pendingInquiries = boardPostRepo.countByBoardTypeAndDelYnAndResolveYn("INQUIRY", "N", "N");
        stats.put("totalInquiries", totalInquiries);
        stats.put("pendingInquiries", pendingInquiries);
        return stats;
    }

    private String generateOrderId() {
        String prefix = "ORD-" + LocalDate.now().format(DateTimeFormatter.ofPattern("yyyyMMdd")) + "-";
        return prefix + String.format("%04d", (int)(Math.random() * 10000));
    }
}
