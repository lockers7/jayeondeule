package com.jayeondeule.shop.entity;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "shop_category")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ShopCategory {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "category_id")
    private Integer categoryId;

    @Column(name = "farm_id", nullable = false)
    private Long farmId;

    @Column(name = "category_name", nullable = false)
    private String categoryName;

    @Column(name = "sort_order")
    private Integer sortOrder;

    @Column(name = "use_yn")
    private String useYn;

    @Column(name = "rgst_dt")
    private LocalDateTime rgstDt;
}
