package com.jayeondeule.smartfarm.entity.memo;

import lombok.*;

import java.io.Serializable;
import java.time.LocalDateTime;

@Getter
@Setter
@Builder
@NoArgsConstructor
@AllArgsConstructor
@EqualsAndHashCode
public class FarmHouseCropsId implements Serializable {
    private Long farmId;
    private Long housId;
    private LocalDateTime recdDttm;
}
