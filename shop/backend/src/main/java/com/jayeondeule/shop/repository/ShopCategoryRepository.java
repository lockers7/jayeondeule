package com.jayeondeule.shop.repository;

import com.jayeondeule.shop.entity.ShopCategory;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface ShopCategoryRepository extends JpaRepository<ShopCategory, Integer> {
    List<ShopCategory> findByFarmIdAndUseYnOrderBySortOrder(Long farmId, String useYn);
}
