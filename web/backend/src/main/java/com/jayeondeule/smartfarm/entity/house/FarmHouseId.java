package com.jayeondeule.smartfarm.entity.house;

import lombok.*;

import java.io.Serializable;

@Getter
@Setter
@Builder
@NoArgsConstructor
@AllArgsConstructor
@EqualsAndHashCode
public class FarmHouseId implements Serializable {
    private Long farmId;
    private Long housId;
}
