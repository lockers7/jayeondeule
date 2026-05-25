package com.jayeondeule.smartfarm.entity.setting;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.time.LocalDateTime;

@Getter
@Entity
@IdClass(SensorSettingId.class)
@Table(name = "SENSOR_M_SETTING")
public class SensorSetting {
    //SENSORM_SETTING 테이블 (온도, 습도, co2 등 설정 값)
    @Setter
    @Id
    private long farmId;

    @Setter
    @Id
    private long housId; // 설정이 속한 재배사

    @Id
    @Column(columnDefinition = "TIMESTAMP(6) WITHOUT TIME ZONE")
    private LocalDateTime setnDttm = LocalDateTime.now(); // 설정일자

    @Column(nullable = false)
    private double tprtMin = 0;

    @Column(nullable = false)
    private double tprtMax = 0;

    @Column(nullable = false)
    private double hmdtMin = 0;

    @Column(nullable = false)
    private double hmdtMax = 0;

    @Column(nullable = false, name="co2_min")
    private double co2Min = 0;

    @Column(nullable = false, name="co2_max")
    private double co2Max = 0;

    @Column(nullable = false)
    private double watrTprtMin = 0;

    @Column(nullable = false)
    private double watrTprtMax = 0;

    @Column(nullable = false)
    private double heatTprtMin = 0;

    @Column(nullable = false)
    private double heatTprtMax = 0;

    // ────────────────────────────────────────────────────────────────────
    // 비상 임계 — 정상 범위 밖, 강제 emergency 자동제어 트리거 임계.
    // 컬럼은 마이그레이션 2026_04_28_sensor_setting_thresholds.sql 로 추가됨.
    // 기존 행은 NULL 가능 → Double 박싱 타입으로 NULL 허용.
    // ────────────────────────────────────────────────────────────────────
    @Setter
    @Column(name = "tprt_crit_min")
    private Double tprtCritMin;

    @Setter
    @Column(name = "tprt_crit_max")
    private Double tprtCritMax;

    @Setter
    @Column(name = "hmdt_crit_min")
    private Double hmdtCritMin;

    @Setter
    @Column(name = "hmdt_crit_max")
    private Double hmdtCritMax;

    @Setter
    @Column(name = "co2_crit_max")
    private Double co2CritMax;

    @Setter
    @Column(name = "watr_tprt_crit_min")
    private Double watrTprtCritMin;

    @Setter
    @Column(name = "watr_tprt_crit_max")
    private Double watrTprtCritMax;

    // ────────────────────────────────────────────────────────────────────
    // 적정값 (otml) — LLM 제어 시 optimal 기준 (정상 범위 안의 목표값).
    // ai_thresholds.py 의 temp_optimal/humidity_optimal/co2_optimal/water_temp_optimal 매핑.
    // ────────────────────────────────────────────────────────────────────
    @Setter
    @Column(name = "tprt_otml")
    private Double tprtOtml;

    @Setter
    @Column(name = "hmdt_otml")
    private Double hmdtOtml;

    @Setter
    @Column(name = "co2_otml")
    private Double co2Otml;

    @Setter
    @Column(name = "watr_tprt_otml")
    private Double watrTprtOtml;

    // 발이기 임계 — 생육단계=발이기 시 적용되는 별도 온도 범위
    @Setter
    @Column(name = "bud_tprt_min")
    private Double budTprtMin;

    @Setter
    @Column(name = "bud_tprt_max")
    private Double budTprtMax;
}
