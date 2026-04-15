package com.jayeondeule.smartfarm.dto.memo;

import lombok.Getter;
import lombok.Setter;

//재배사 메모 DTO
@Getter
@Setter
public class FarmHouseCropsInsertDTO {
    private String memo; // 메모내용
    private int cropStat; // 생육상태 코드 (0:미정의, 10:양호, 20:갈변, 30:물방울, 40:생육더딤, 50:벌레)
}
