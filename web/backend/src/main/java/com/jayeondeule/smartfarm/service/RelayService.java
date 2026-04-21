package com.jayeondeule.smartfarm.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.jayeondeule.smartfarm.dto.relay.RelayDTO;
import com.jayeondeule.smartfarm.dto.relay.RelayInsertDTO;
import com.jayeondeule.smartfarm.dto.relay.RelayWriteResultDTO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import com.jayeondeule.smartfarm.repository.RelayRecordingRepository;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

// ════════════════════════════════════════════════════════════════════════════
// 릴레이 서비스 — 조회는 Spring Boot 가 직접 처리, 쓰기는 FastAPI 의 인터록
// 게이트 (밸브-팬 보호) 를 통과하도록 위임 호출 (POST /api/v1/rpi/relay).
// 이렇게 하면 AI / 알고리즘 / 웹수동 모든 경로가 동일 게이트를 거쳐 안전 규칙
// 단일 소스 보장. FastAPI 가 보정한 최종 16 flag + interlock_violations 를
// 컨트롤러에 그대로 반환해 프론트엔드 팝업으로 사용자에게 안내한다.
// ════════════════════════════════════════════════════════════════════════════
@Service
@RequiredArgsConstructor
@Slf4j
public class RelayService {
    private final RelayRecordingRepository relayRecordingRepository;
    private final ObjectMapper mapper;

    @Value("${agri-ai-core.base-url:http://127.0.0.1:8002}")
    private String coreBaseUrl;

    public RelayDTO getRelay(Long farmId, Long houseId) {
        return mapper.convertValue(relayRecordingRepository.findTopByFarmIdAndHousIdOrderByRecdDttmDesc(farmId, houseId), RelayDTO.class);
    }

    // ────────────────────────────────────────────────────────────────────────
    // 릴레이 쓰기 — FastAPI 게이트 경유 (POST /api/v1/rpi/relay/{farm}/{house})
    // RelayInsertDTO (camelCase relay1stFlag) → relay_*st_flag 16 flag 변환 후
    // RestTemplate 으로 위임. FastAPI 응답의 success / settings / interlock_violations
    // 를 RelayWriteResultDTO 로 매핑해 컨트롤러에 반환.
    // FastAPI 미응답 시: 안전 측면에서 DB 직접 쓰기 fallback 하지 않고 예외 전파.
    // ────────────────────────────────────────────────────────────────────────
    @SuppressWarnings({"rawtypes", "unchecked"})
    public RelayWriteResultDTO insertRelay(Long farmId, Long houseId, RelayInsertDTO insertInfo) {
        Map<String, Boolean> relays = toRelayFlagMap(insertInfo);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("relays", relays);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, headers);

        String url = coreBaseUrl + "/api/v1/rpi/relay/" + farmId + "/" + houseId;
        RestTemplate rt = new RestTemplate();

        try {
            ResponseEntity<Map> resp = rt.postForEntity(url, entity, Map.class);
            Map respBody = resp.getBody();
            if (respBody == null) {
                throw new RuntimeException("FastAPI 빈 응답");
            }

            RelayWriteResultDTO out = new RelayWriteResultDTO();
            out.setSuccess(Boolean.TRUE.equals(respBody.get("success")));
            Object settings = respBody.get("settings");
            if (settings instanceof Map) {
                out.setSettings((Map<String, Boolean>) settings);
            }
            Object viol = respBody.get("interlock_violations");
            if (viol instanceof List) {
                out.setInterlockViolations((List<Map<String, Object>>) viol);
            }
            Object msg = respBody.get("message");
            if (msg != null) {
                out.setMessage(msg.toString());
            }
            return out;
        } catch (Exception e) {
            log.error("[RelayService] FastAPI 릴레이 쓰기 위임 실패 farm={} house={}: {}",
                    farmId, houseId, e.getMessage());
            throw new RuntimeException("릴레이 쓰기 실패: " + e.getMessage(), e);
        }
    }

    // RelayInsertDTO 의 16 boolean 필드 → relay_*st_flag 키 dict
    // [2026-04-27] LinkedHashMap 으로 1..16 순서 보존 — Python set_relay_value 도
    // 1..16 으로 재정렬하지만, JSON 직렬화 단계에서도 순서를 안정화해 디버깅 용이.
    private Map<String, Boolean> toRelayFlagMap(RelayInsertDTO d) {
        Map<String, Boolean> m = new LinkedHashMap<>();
        m.put("relay_1st_flag",  d.isRelay1stFlag());
        m.put("relay_2st_flag",  d.isRelay2stFlag());
        m.put("relay_3st_flag",  d.isRelay3stFlag());
        m.put("relay_4st_flag",  d.isRelay4stFlag());
        m.put("relay_5st_flag",  d.isRelay5stFlag());
        m.put("relay_6st_flag",  d.isRelay6stFlag());
        m.put("relay_7st_flag",  d.isRelay7stFlag());
        m.put("relay_8st_flag",  d.isRelay8stFlag());
        m.put("relay_9st_flag",  d.isRelay9stFlag());
        m.put("relay_10st_flag", d.isRelay10stFlag());
        m.put("relay_11st_flag", d.isRelay11stFlag());
        m.put("relay_12st_flag", d.isRelay12stFlag());
        m.put("relay_13st_flag", d.isRelay13stFlag());
        m.put("relay_14st_flag", d.isRelay14stFlag());
        m.put("relay_15st_flag", d.isRelay15stFlag());
        m.put("relay_16st_flag", d.isRelay16stFlag());
        return m;
    }
}
