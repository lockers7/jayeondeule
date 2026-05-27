package com.jayeondeule.shop.entity;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "shop_product_view_log")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ShopProductViewLog {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "log_id")
    private Long logId;

    @Column(name = "farm_id")
    private Long farmId;

    @Column(name = "product_id", nullable = false)
    private Integer productId;

    @Column(name = "shop_usr_id", nullable = false)
    private String shopUsrId;

    @Column(name = "view_dt", nullable = false)
    private LocalDateTime viewDt;

    @PrePersist
    public void prePersist() {
        if (viewDt == null) viewDt = LocalDateTime.now();
        if (farmId == null) farmId = 1L;
    }
}
