package com.jayeondeule.shop.repository;

import com.jayeondeule.shop.entity.ShopProduct;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import java.util.List;

public interface ShopProductRepository extends JpaRepository<ShopProduct, Integer> {
    List<ShopProduct> findByFarmIdOrderBySortOrder(Long farmId);
    List<ShopProduct> findByFarmIdAndSaleStatusOrderBySortOrder(Long farmId, String saleStatus);
    List<ShopProduct> findByFarmIdAndCategoryIdOrderBySortOrder(Long farmId, Integer categoryId);

    @Modifying
    @Query("UPDATE ShopProduct p SET p.viewCount = p.viewCount + 1 WHERE p.productId = :productId")
    void incrementViewCount(Integer productId);

    @Modifying
    @Query("UPDATE ShopProduct p SET p.stockQty = p.stockQty - :qty WHERE p.productId = :productId AND p.stockQty >= :qty")
    int decreaseStock(Integer productId, int qty);
}
