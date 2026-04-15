package com.jayeondeule.smartfarm.entity.setting;

import com.jayeondeule.smartfarm.enums.setting.LightIrrigationSettingType;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;

@Getter
@Entity
@IdClass(LightIrrigationSettingId.class)
@Table(name = "LIGHT_IRRIGATION_S_SETTING")
public class LightIrrigationSetting {
    //LIGHT_IRRIGATION_S_SETTING 테이블 (관수, 조명 시간 설정)
    @Setter
    @Id
    private long farmId;

    @Setter
    @Id
    private long housId; // 설정이 속한 재배사

    @Id
    @Column(columnDefinition = "TIMESTAMP(6) WITHOUT TIME ZONE")
    private LocalDateTime setnDttm = LocalDateTime.now(); // 설정일자

    @Setter
    @Column(nullable = false)
    private boolean dlteYn = false; // 설정 삭제 상태

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private LightIrrigationSettingType unitType; // 관수, 조명 타입 설정

    @Setter
    @Column(nullable = false)
    private LocalTime strtTime; // 관수, 조명 시작 시간

    @Setter
    @Column(nullable = false)
    private LocalTime fnshTime; // 관수, 조명 종료 시간

    @Setter
    @Column(length = 20)
    private String excsType = "daily"; // 실행 유형: daily, interval, weekdays

    @Setter
    private Integer excsItvl; // N일마다 실행 간격

    @Setter
    private LocalDate excsStrtDate; // 주기 시작일

    @Setter
    @Column(length = 50)
    private String excsWkdy; // 실행 요일 (1,3,5 = 월/수/금)
}
