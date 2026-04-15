package com.jayeondeule.smartfarm.dto.setting;


import com.jayeondeule.smartfarm.enums.setting.LightIrrigationSettingType;
import lombok.Getter;
import lombok.Setter;

import java.time.LocalDate;
import java.time.LocalTime;

@Getter
@Setter
public class LightIrrigationSettingInsertDTO {
    private LightIrrigationSettingType unitType; // 관수, 조명 타입 설정

    private LocalTime strtTime; // 관수, 조명 시작 시간
    private LocalTime fnshTime; // 관수, 조명 종료 시간

    private String excsType;      // 실행 유형: daily, interval, weekdays
    private Integer excsItvl;     // N일마다 실행 간격
    private LocalDate excsStrtDate; // 주기 시작일
    private String excsWkdy;      // 실행 요일 (1,3,5 = 월/수/금)
}
