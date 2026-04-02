package com.jayeondeule.shop.service;

import com.jayeondeule.shop.entity.ShopOrder;
import com.jayeondeule.shop.entity.ShopOrderItem;
import com.jayeondeule.shop.repository.ShopOrderItemRepository;
import com.jayeondeule.shop.repository.ShopOrderRepository;
import com.jayeondeule.shop.repository.ShopProductRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

@Component
@RequiredArgsConstructor
@Slf4j
public class OrderScheduler {
    private final ShopOrderRepository orderRepo;
    private final ShopOrderItemRepository orderItemRepo;
    private final ShopProductRepository productRepo;

    /**
     * 배송완료 후 5일 경과 시 자동 거래완료(RECEIVED) 처리
     * 매일 02:00에 실행
     */
    @Scheduled(cron = "0 0 2 * * *")
    @Transactional
    public void autoCompleteDeliveredOrders() {
        LocalDateTime cutoff = LocalDateTime.now().minusDays(5);
        List<ShopOrder> orders = orderRepo.findDeliveredBefore(cutoff);

        if (orders.isEmpty()) return;

        for (ShopOrder order : orders) {
            order.setOrderStatus("RECEIVED");
            order.setReceivedDt(LocalDateTime.now());
            orderRepo.save(order);
            // 판매중 감소, 판매완료 증가
            List<ShopOrderItem> items = orderItemRepo.findByOrderId(order.getOrderId());
            for (ShopOrderItem item : items) {
                productRepo.decreaseSellingQty(item.getProductId(), item.getQuantity());
                productRepo.increaseSoldQty(item.getProductId(), item.getQuantity());
            }
            log.info("[자동거래완료] orderId={}, deliveredDt={}", order.getOrderId(), order.getDeliveredDt());
        }
        log.info("[자동거래완료] 총 {}건 처리 완료", orders.size());
    }
}
