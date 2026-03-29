package com.jayeondeule.shop.repository;

import com.jayeondeule.shop.entity.ShopOrderItem;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import java.util.List;

public interface ShopOrderItemRepository extends JpaRepository<ShopOrderItem, Integer> {
    List<ShopOrderItem> findByOrderId(String orderId);

    @Query(value = "SELECT oi.product_id, oi.product_name, SUM(oi.quantity) as total_qty, SUM(oi.subtotal) as total_amt " +
            "FROM shop_order_item oi JOIN shop_order o ON oi.order_id = o.order_id " +
            "WHERE o.farm_id = :farmId AND o.payment_status = 'PAID' " +
            "GROUP BY oi.product_id, oi.product_name ORDER BY total_qty DESC", nativeQuery = true)
    List<Object[]> productSalesRanking(Long farmId);
}
