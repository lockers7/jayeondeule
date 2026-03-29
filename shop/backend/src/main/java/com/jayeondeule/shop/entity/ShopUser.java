package com.jayeondeule.shop.entity;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "shop_user")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ShopUser {
    @Id
    @Column(name = "shop_usr_id")
    private String shopUsrId;

    @Column(name = "farm_id", nullable = false)
    private Long farmId;

    @Column(nullable = false)
    private String passwd;

    @Column(name = "usr_name", nullable = false)
    private String usrName;

    @Column(name = "usr_grade", nullable = false)
    private String usrGrade;

    @Column(name = "usr_status", nullable = false)
    private String usrStatus;

    private String phone;
    private String email;
    private String zipcode;
    private String address;

    @Column(name = "address_detail")
    private String addressDetail;

    @Column(name = "last_login_dt")
    private LocalDateTime lastLoginDt;

    @Column(name = "rgst_dt", nullable = false)
    private LocalDateTime rgstDt;

    @Column(name = "withdraw_dt")
    private LocalDateTime withdrawDt;

    @PrePersist
    public void prePersist() {
        if (rgstDt == null) rgstDt = LocalDateTime.now();
        if (usrGrade == null) usrGrade = "MEMBER";
        if (usrStatus == null) usrStatus = "ACTIVE";
    }
}
