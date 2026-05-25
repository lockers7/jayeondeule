package com.jayeondeule.smartfarm.dto.setting;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class SensorSettingInsertDTO {
    private double tprtMin;
    private double tprtMax;

    private double hmdtMin;
    private double hmdtMax;

    private double co2Min;
    private double co2Max;

    private double watrTprtMin;
    private double watrTprtMax;

    private double heatTprtMin;
    private double heatTprtMax;

    // 비상 임계 (NULL 허용 — 신규 필드)
    private Double tprtCritMin;
    private Double tprtCritMax;
    private Double hmdtCritMin;
    private Double hmdtCritMax;
    private Double co2CritMax;
    private Double watrTprtCritMin;
    private Double watrTprtCritMax;

    // 적정값 (LLM optimal 매핑) + 발이기 임계
    private Double tprtOtml;
    private Double hmdtOtml;
    private Double co2Otml;
    private Double watrTprtOtml;
    private Double budTprtMin;
    private Double budTprtMax;
}
