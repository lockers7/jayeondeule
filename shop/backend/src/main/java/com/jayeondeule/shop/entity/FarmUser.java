package com.jayeondeule.shop.entity;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "user_m_info")
@Getter @Setter @NoArgsConstructor
public class FarmUser {
    @Id
    @Column(name = "user_id")
    private String userId;

    @Column(name = "farm_id")
    private Long farmId;

    @Column(nullable = false)
    private String passwd;

    @Column(name = "user_name", nullable = false)
    private String userName;

    @Column(name = "auth_lvel", nullable = false)
    private Integer authLvel;  // 0=ADMIN, 1=SYS_MONITOR, 2=FARM_ADMIN, 3=FARM_MONITOR

    @Column(name = "hp_no")
    private String hpNo;

    @Column(name = "dlte_yn", nullable = false)
    private String dlteYn;

    @Column(name = "rgst_dttm", nullable = false)
    private LocalDateTime rgstDttm;

    public String toShopGrade() {
        return switch (authLvel) {
            case 0 -> "SYSTEM_ADMIN";
            case 2 -> "SHOP_ADMIN";
            case 1, 3 -> "MONITOR";   // 읽기 전용
            default -> null;
        };
    }
}
