package com.jayeondeule.shop.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import lombok.Data;
import java.util.List;

@Data
public class OrderRequest {
    @NotBlank private String receiverName;
    @NotBlank private String receiverPhone;
    private String zipcode;
    @NotBlank private String address;
    private String addressDetail;
    private String shippingMemo;
    @NotEmpty private List<OrderItemRequest> items;

    @Data
    public static class OrderItemRequest {
        private Integer productId;
        private Integer quantity;
    }
}
