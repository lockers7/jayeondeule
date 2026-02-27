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
}
