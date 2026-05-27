package com.jayeondeule.shop.entity;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;
import java.util.List;

@Entity
@Table(name = "shop_order")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ShopOrder {
    @Id
    @Column(name = "order_id")
    private String orderId;

    @Column(name = "farm_id", nullable = false)
    private Long farmId;

    @Column(name = "shop_usr_id", nullable = false)
    private String shopUsrId;

    @Column(name = "total_amount", nullable = false)
    private Long totalAmount;

    @Column(name = "payment_method")
    private String paymentMethod;

    @Column(name = "payment_status")
    private String paymentStatus;

    @Column(name = "order_status")
    private String orderStatus;

    @Column(name = "receiver_name")
    private String receiverName;

    @Column(name = "receiver_phone")
    private String receiverPhone;

    private String zipcode;
    private String address;

    @Column(name = "address_detail")
    private String addressDetail;

    @Column(name = "shipping_memo")
    private String shippingMemo;

    @Column(name = "tracking_no")
    private String trackingNo;

    @Column(name = "cancel_reason")
    private String cancelReason;

    @Column(name = "order_dt")
    private LocalDateTime orderDt;

    @Column(name = "paid_dt")
    private LocalDateTime paidDt;

    @Column(name = "preparing_dt")
    private LocalDateTime preparingDt;

    @Column(name = "shipped_dt")
    private LocalDateTime shippedDt;

    @Column(name = "delivered_dt")
    private LocalDateTime deliveredDt;

    @Column(name = "cancelled_dt")
    private LocalDateTime cancelledDt;

    @Column(name = "received_dt")
    private LocalDateTime receivedDt;

    @OneToMany(mappedBy = "orderId", cascade = CascadeType.ALL, fetch = FetchType.EAGER)
    private List<ShopOrderItem> items;

    @PrePersist
    public void prePersist() {
        if (orderDt == null) orderDt = LocalDateTime.now();
        if (paymentStatus == null) paymentStatus = "UNPAID";
        if (orderStatus == null) orderStatus = "ORDERED";
        if (paymentMethod == null) paymentMethod = "BANK_TRANSFER";
    }
}
