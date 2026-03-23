package com.jayeondeule.smartfarm.enums.user;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;
import lombok.Getter;
import lombok.RequiredArgsConstructor;

@Getter
@RequiredArgsConstructor
public enum AuthLvel {
    ADMIN(0, "ADMIN"),               // 시스템관리자
    SYS_MONITOR(1, "SYS_MONITOR"),   // 시스템모니터링
    FARM_ADMIN(2, "FARM_ADMIN"),     // 농장관리자
    FARM_MONITOR(3, "FARM_MONITOR"); // 농장모니터링

    private final int code;
    private final String name;

    // React ↔ Spring 통신 시 문자열로 변환
    @JsonValue
    public String getName() {
        return name;
    }

    // React → Spring (String → Enum)
    @JsonCreator
    public static AuthLvel from(String name) {
        for (AuthLvel level : values()) {
            if (level.name.equalsIgnoreCase(name)) {
                return level;
            }
        }
        throw new IllegalArgumentException("Unknown auth level: " + name);
    }
}
