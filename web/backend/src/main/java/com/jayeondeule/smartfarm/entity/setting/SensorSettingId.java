package com.jayeondeule.smartfarm.entity.setting;

import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.Setter;

import java.io.Serializable;
import java.time.LocalDateTime;

@Getter
@Setter
@EqualsAndHashCode
public class SensorSettingId implements Serializable {
    private Long farmId;
    private Long housId;
    private LocalDateTime setnDttm;
}
