package com.jayeondeule.shop.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class LoginRequest {
    @NotBlank private String shopUsrId;
    @NotBlank private String passwd;
}
