package com.jayeondeule.smartfarm.dto.user;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.jayeondeule.smartfarm.enums.user.AuthLvel;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class UserPatchDTO {
    //사용자 수정 정보 전송 객체
    private String userName; // 이름
    private String pstn; // 직위
    private String hpNo; // 전화번호
    private AuthLvel authLvel; // 권한
    private Long farmId; // 소속 농장
    private String passwd; // 비밀번호 (변경 시에만)
}
