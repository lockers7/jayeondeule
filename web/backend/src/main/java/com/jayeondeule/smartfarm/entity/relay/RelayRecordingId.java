package com.jayeondeule.smartfarm.entity.relay;

import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.Setter;

import java.io.Serializable;
import java.time.LocalDateTime;

@Getter
@Setter
@EqualsAndHashCode
public class RelayRecordingId implements Serializable {
    private Long farmId;
    private Long housId;
    private LocalDateTime recdDttm;
}
