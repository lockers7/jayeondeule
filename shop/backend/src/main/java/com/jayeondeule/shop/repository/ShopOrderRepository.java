package com.jayeondeule.shop.repository;

import com.jayeondeule.shop.entity.ShopOrder;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import java.util.List;

public interface ShopOrderRepository extends JpaRepository<ShopOrder, String> {
    List<ShopOrder> findByShopUsrIdOrderByOrderDtDesc(String shopUsrId);
    List<ShopOrder> findByFarmIdOrderByOrderDtDesc(Long farmId);
    List<ShopOrder> findByFarmIdAndOrderStatusOrderByOrderDtDesc(Long farmId, String orderStatus);
    long countByFarmIdAndOrderStatus(Long farmId, String orderStatus);

    @Query("SELECT COALESCE(SUM(o.totalAmount), 0) FROM ShopOrder o WHERE o.farmId = :farmId AND o.paymentStatus = 'PAID'")
    long sumPaidAmountByFarmId(Long farmId);

    @Query(value = "SELECT DATE(order_dt) as dt, COUNT(*) as cnt, COALESCE(SUM(total_amount),0) as amt " +
            "FROM shop_order WHERE farm_id = :farmId AND order_dt >= NOW() - INTERVAL '30 days' " +
            "GROUP BY DATE(order_dt) ORDER BY dt", nativeQuery = true)
    List<Object[]> dailyOrderStats(Long farmId);
}
