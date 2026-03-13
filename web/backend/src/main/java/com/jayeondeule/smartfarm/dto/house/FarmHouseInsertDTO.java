package com.jayeondeule.smartfarm.dto.house;

import lombok.Getter;
import lombok.Setter;

//재배사 등록 DTO
@Getter
@Setter
public class FarmHouseInsertDTO {
    private long farmId; // 농장과 관계 설정
    // hous_id는 farmId로 찾은 house의 갯수+1로 설정.
    private long housId;
    private String housName; // 재배사 이름
    private String cropKind; // 작물 종류
    private int cropLvel = 2; // 생육단계 (1:발이기, 2:생육기, 3:수확기, 4:휴지기)
    private String snsrRfrsItvl = "3"; // 센서 측정 시간 간격
    private boolean mnulCtrlFlag = false; // 릴레이 수동 조작 여부
    private String ctrlType = "algorithm"; // 제어 유형 (algorithm, ai)
    private boolean rfrsFlag = false; // 수동 센서 측정
}
