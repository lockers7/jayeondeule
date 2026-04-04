package com.jayeondeule.shop.service;

import com.jayeondeule.shop.entity.ShopProduct;
import com.jayeondeule.shop.repository.ShopProductRepository;
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
import java.util.List;
import java.util.UUID;

@Service
@RequiredArgsConstructor
@SuppressWarnings("null")
@Slf4j
public class ProductService {
    private final ShopProductRepository productRepo;

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
