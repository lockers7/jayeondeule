package com.jayeondeule.smartfarm.entity.setting;

import lombok.*;

import java.io.Serializable;
import java.time.LocalDateTime;

@Getter
@Setter
@Builder
@NoArgsConstructor
@AllArgsConstructor
@EqualsAndHashCode
public class LightIrrigationSettingId implements Serializable {
    private Long farmId;
    private Long housId;
    private LocalDateTime setnDttm;
}
