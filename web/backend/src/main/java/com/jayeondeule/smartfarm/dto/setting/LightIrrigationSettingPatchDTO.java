package com.jayeondeule.smartfarm.dto.setting;

import lombok.Getter;
import lombok.Setter;

import java.time.LocalDate;
import java.time.LocalTime;

@Getter
@Setter
public class LightIrrigationSettingPatchDTO {
    private boolean dlteYn; // 관수, 조명 삭제 상태

    private LocalTime strtTime; // 관수, 조명 시작 시간
    private LocalTime fnshTime; // 관수, 조명 종료 시간

    private String excsType;      // 실행 유형: daily, interval, weekdays
    private Integer excsItvl;     // N일마다 실행 간격
    private LocalDate excsStrtDate; // 주기 시작일
    private String excsWkdy;      // 실행 요일 (1,3,5 = 월/수/금)
}
