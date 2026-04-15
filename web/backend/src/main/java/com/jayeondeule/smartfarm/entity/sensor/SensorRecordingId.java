package com.jayeondeule.smartfarm.entity.sensor;

import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.Setter;

import java.io.Serializable;
import java.time.LocalDateTime;

@Getter
@Setter
@EqualsAndHashCode
public class SensorRecordingId implements Serializable {
    private Long farmId;
    private Long housId;
    private LocalDateTime recdDttm;
}
