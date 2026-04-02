package com.jayeondeule.shop.entity;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "shop_product")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ShopProduct {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "product_id")
    private Integer productId;

    @Column(name = "farm_id", nullable = false)
    private Long farmId;

    @Column(name = "category_id")
    private Integer categoryId;

    @Column(name = "product_name", nullable = false)
    private String productName;

    private String subtitle;

    @Column(columnDefinition = "TEXT")
    private String description;

    @Column(nullable = false)
    private Long price;

    @Column(nullable = false)
    private String unit;

    @Column(name = "stock_qty", nullable = false)
    private Integer stockQty;

    @Column(name = "sale_status", nullable = false)
    private String saleStatus;

    @Column(name = "selling_qty", nullable = false)
    private Integer sellingQty;

    @Column(name = "sold_qty", nullable = false)
    private Integer soldQty;

    private String origin;

    @Column(columnDefinition = "TEXT")
    private String features;

    @Column(name = "image_url")
    private String imageUrl;

    @Column(name = "sort_order")
    private Integer sortOrder;

    @Column(name = "view_count")
    private Long viewCount;

    @Column(name = "rgst_dt")
    private LocalDateTime rgstDt;

    @Column(name = "updt_dt")
    private LocalDateTime updtDt;

    @PrePersist
    public void prePersist() {
        if (rgstDt == null) rgstDt = LocalDateTime.now();
        if (saleStatus == null) saleStatus = "ON_SALE";
        if (viewCount == null) viewCount = 0L;
        if (sellingQty == null) sellingQty = 0;
        if (soldQty == null) soldQty = 0;
        if (sortOrder == null) sortOrder = 0;
    }

    @PreUpdate
    public void preUpdate() {
        updtDt = LocalDateTime.now();
    }
}
