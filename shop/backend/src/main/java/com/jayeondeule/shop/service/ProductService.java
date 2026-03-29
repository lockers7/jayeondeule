package com.jayeondeule.shop.service;

import com.jayeondeule.shop.entity.ShopProduct;
import com.jayeondeule.shop.repository.ShopProductRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.List;

@Service
@RequiredArgsConstructor
public class ProductService {
    private final ShopProductRepository productRepo;

    public List<ShopProduct> getProducts(Long farmId) {
        return productRepo.findByFarmIdOrderBySortOrder(farmId);
    }

    public List<ShopProduct> getOnSaleProducts(Long farmId) {
        return productRepo.findByFarmIdAndSaleStatusOrderBySortOrder(farmId, "ON_SALE");
    }

    public ShopProduct getProduct(Integer id) {
        return productRepo.findById(id)
                .orElseThrow(() -> new RuntimeException("상품을 찾을 수 없습니다."));
    }

    @Transactional
    public ShopProduct getProductWithView(Integer id) {
        productRepo.incrementViewCount(id);
        return getProduct(id);
    }

    @Transactional
    public ShopProduct saveProduct(ShopProduct product) {
        return productRepo.save(product);
    }

    @Transactional
    public void deleteProduct(Integer id) {
        ShopProduct product = getProduct(id);
        product.setSaleStatus("STOPPED");
        productRepo.save(product);
    }
}
