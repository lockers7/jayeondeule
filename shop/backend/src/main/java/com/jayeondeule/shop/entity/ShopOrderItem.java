package com.jayeondeule.shop.entity;

import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(name = "shop_order_item")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ShopOrderItem {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "item_id")
    private Integer itemId;

    @Column(name = "order_id", nullable = false)
    private String orderId;

    @Column(name = "product_id", nullable = false)
    private Integer productId;

    @Column(name = "product_name", nullable = false)
    private String productName;

    @Column(nullable = false)
    private Integer quantity;

    @Column(name = "unit_price", nullable = false)
    private Long unitPrice;

    @Column(nullable = false)
    private Long subtotal;
}
