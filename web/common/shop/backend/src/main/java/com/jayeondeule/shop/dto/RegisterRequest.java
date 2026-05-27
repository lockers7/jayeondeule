package com.jayeondeule.shop.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class RegisterRequest {
    @NotBlank private String shopUsrId;
    @NotBlank private String passwd;
    @NotBlank private String usrName;
    private String phone;
    private String email;
    private String zipcode;
    private String address;
    private String addressDetail;
}
