package com.jayeondeule.shop.repository;

import com.jayeondeule.shop.entity.ShopOrder;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import java.time.LocalDateTime;
import java.util.List;

public interface ShopOrderRepository extends JpaRepository<ShopOrder, String> {
    List<ShopOrder> findByShopUsrIdOrderByOrderDtDesc(String shopUsrId);
    List<ShopOrder> findByFarmIdOrderByOrderDtDesc(Long farmId);
    List<ShopOrder> findByFarmIdAndOrderStatusOrderByOrderDtDesc(Long farmId, String orderStatus);
    long countByFarmIdAndOrderStatus(Long farmId, String orderStatus);

    @Query("SELECT COALESCE(SUM(o.totalAmount), 0) FROM ShopOrder o WHERE o.farmId = :farmId AND o.paymentStatus = 'PAID'")
    long sumPaidAmountByFarmId(Long farmId);

    // 최근 배송지 이력 (고유 주소 기준 최대 5건)
    @Query(value = "SELECT DISTINCT ON (zipcode, address, address_detail) " +
            "receiver_name, receiver_phone, zipcode, address, address_detail, shipping_memo " +
            "FROM shop_order WHERE shop_usr_id = :userId AND zipcode IS NOT NULL AND zipcode != '' " +
            "ORDER BY zipcode, address, address_detail, order_dt DESC " +
            "LIMIT 5", nativeQuery = true)
    List<Object[]> findRecentAddresses(String userId);

    // 배송완료 후 5일 경과 주문 (자동 거래완료 대상)
    @Query("SELECT o FROM ShopOrder o WHERE o.orderStatus = 'DELIVERED' AND o.deliveredDt < :cutoff")
    List<ShopOrder> findDeliveredBefore(LocalDateTime cutoff);

    @Query(value = "SELECT DATE(order_dt) as dt, COUNT(*) as cnt, COALESCE(SUM(total_amount),0) as amt " +
            "FROM shop_order WHERE farm_id = :farmId AND order_dt >= NOW() - INTERVAL '30 days' " +
            "GROUP BY DATE(order_dt) ORDER BY dt", nativeQuery = true)
    List<Object[]> dailyOrderStats(Long farmId);
}
