package com.jayeondeule.shop.repository;

import com.jayeondeule.shop.entity.ShopProductViewLog;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import java.util.List;

public interface ShopProductViewLogRepository extends JpaRepository<ShopProductViewLog, Long> {

    long countByProductId(Integer productId);

    long countByProductIdAndShopUsrId(Integer productId, String shopUsrId);

    long countByShopUsrId(String shopUsrId);

    @Query("SELECT v.productId, COUNT(v) FROM ShopProductViewLog v GROUP BY v.productId ORDER BY COUNT(v) DESC")
    List<Object[]> productViewRanking();

    @Query("SELECT v.shopUsrId, COUNT(v) FROM ShopProductViewLog v WHERE v.productId = :productId GROUP BY v.shopUsrId ORDER BY COUNT(v) DESC")
    List<Object[]> userViewCountByProduct(Integer productId);
}
