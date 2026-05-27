package com.jayeondeule.shop.service;

import com.jayeondeule.shop.entity.ShopProduct;
import com.jayeondeule.shop.entity.ShopProductViewLog;
import com.jayeondeule.shop.repository.ShopProductRepository;
import com.jayeondeule.shop.repository.ShopProductViewLogRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
@RequiredArgsConstructor
@Slf4j
public class ProductService {
    private final ShopProductRepository productRepo;
    private final ShopProductViewLogRepository viewLogRepo;

    @Value("${product.upload.path:/workspace/jayeondeule/shop/uploads/products}")
    private String uploadPath;

    public List<ShopProduct> getProducts(Long farmId) {
        return productRepo.findByFarmIdOrderBySortOrder(farmId);
    }

    public List<ShopProduct> getOnSaleProducts(Long farmId) {
        return productRepo.findByFarmIdOrderBySortOrder(farmId);
    }

    public ShopProduct getProduct(Integer id) {
        return productRepo.findById(id)
                .orElseThrow(() -> new RuntimeException("상품을 찾을 수 없습니다."));
    }

    @Transactional
    public ShopProduct getProductWithView(Integer id, String viewerId) {
        // 무제한 누적: 매번 view_count +1, 로그도 매번 기록
        productRepo.incrementViewCount(id);
        ShopProduct product = getProduct(id);
        try {
            ShopProductViewLog logEntry = ShopProductViewLog.builder()
                    .productId(id)
                    .farmId(product.getFarmId())
                    .shopUsrId(viewerId != null && !viewerId.isEmpty() ? viewerId : "anonymous")
                    .build();
            viewLogRepo.save(logEntry);
        } catch (Exception e) {
            log.warn("[상품조회로그] 저장 실패: {}", e.getMessage());
        }
        return product;
    }

    /** 상품별 조회 통계 (전체 + 사용자별) */
    public Map<String, Object> getProductViewStats(Integer productId) {
        Map<String, Object> stats = new HashMap<>();
        stats.put("productId", productId);
        stats.put("totalViews", viewLogRepo.countByProductId(productId));

        List<Map<String, Object>> userStats = new ArrayList<>();
        for (Object[] row : viewLogRepo.userViewCountByProduct(productId)) {
            Map<String, Object> u = new HashMap<>();
            u.put("userId", row[0]);
            u.put("count", row[1]);
            userStats.add(u);
        }
        stats.put("byUser", userStats);
        return stats;
    }

    /** 전체 상품 조회 랭킹 */
    public List<Map<String, Object>> getProductViewRanking() {
        List<Map<String, Object>> ranking = new ArrayList<>();
        for (Object[] row : viewLogRepo.productViewRanking()) {
            Map<String, Object> r = new HashMap<>();
            Integer pid = (Integer) row[0];
            r.put("productId", pid);
            r.put("totalViews", row[1]);
            try {
                r.put("productName", productRepo.findById(pid).map(ShopProduct::getProductName).orElse("?"));
            } catch (Exception e) { r.put("productName", "?"); }
            ranking.add(r);
        }
        return ranking;
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

    @Transactional
    public String uploadProductImage(Integer productId, MultipartFile file) {
        ShopProduct product = getProduct(productId);
        try {
            Path dir = Paths.get(uploadPath);
            Files.createDirectories(dir);

            String ext = "";
            String origName = file.getOriginalFilename();
            if (origName != null && origName.contains(".")) {
                ext = origName.substring(origName.lastIndexOf('.'));
            }
            String fileName = "product_" + productId + "_" + UUID.randomUUID().toString().substring(0, 8) + ext;
            Path filePath = dir.resolve(fileName);
            file.transferTo(filePath.toFile());

            String url = "/uploads/products/" + fileName;
            product.setImageUrl(url);
            productRepo.save(product);
            log.info("[상품이미지] productId={}, url={}", productId, url);
            return url;
        } catch (IOException e) {
            log.error("[상품이미지] 업로드 실패: {}", e.getMessage());
            throw new RuntimeException("이미지 업로드에 실패했습니다.");
        }
    }
}
