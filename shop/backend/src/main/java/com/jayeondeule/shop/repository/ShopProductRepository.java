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

    @Modifying
    @Query("UPDATE ShopProduct p SET p.sellingQty = p.sellingQty + :qty WHERE p.productId = :productId")
    void increaseSellingQty(Integer productId, int qty);

    @Modifying
    @Query("UPDATE ShopProduct p SET p.sellingQty = GREATEST(p.sellingQty - :qty, 0) WHERE p.productId = :productId")
    void decreaseSellingQty(Integer productId, int qty);

    // 재고 0이면 자동 품절, 재고 복원되면 자동 판매중
    @Modifying
    @Query("UPDATE ShopProduct p SET p.saleStatus = 'SOLD_OUT' WHERE p.productId = :productId AND p.stockQty <= 0 AND p.saleStatus = 'ON_SALE'")
    void markSoldOutIfEmpty(Integer productId);

    @Modifying
    @Query("UPDATE ShopProduct p SET p.saleStatus = 'ON_SALE' WHERE p.productId = :productId AND p.stockQty > 0 AND p.saleStatus = 'SOLD_OUT'")
    void markOnSaleIfRestored(Integer productId);

    @Modifying
    @Query("UPDATE ShopProduct p SET p.soldQty = p.soldQty + :qty WHERE p.productId = :productId")
    void increaseSoldQty(Integer productId, int qty);

    @Modifying
    @Query("UPDATE ShopProduct p SET p.soldQty = p.soldQty - :qty WHERE p.productId = :productId AND p.soldQty >= :qty")
    void decreaseSoldQty(Integer productId, int qty);
}
