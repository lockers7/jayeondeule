package com.jayeondeule.shop.controller;

import com.jayeondeule.shop.dto.ApiResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;

import java.util.*;

@RestController
@RequestMapping("/api/shop/lotto")
@RequiredArgsConstructor
public class LottoController {
    private final JdbcTemplate jdbc;

    private static final String AI_API = "http://localhost:8002";

    // 최근 N회차 당첨번호 조회 (추천/분석 컬럼 포함 + 회차별 추천 목록 첨부)
    @GetMapping("/results")
    public ResponseEntity<?> getResults(
            @RequestParam(defaultValue = "10") int limit,
            @RequestParam(required = false) Integer drawNo) {
        String cols = "draw_no, draw_date, num1, num2, num3, num4, num5, num6, bonus, " +
                "recommendation_nums, recommendation_bonus, match_count, " +
                "best_match, total_match, total_miss, llm_analysis, analysis_dt";
        String sql;
        Object[] params;
        if (drawNo != null) {
            sql = "SELECT " + cols + " FROM lotto_results WHERE draw_no = ? ORDER BY draw_no DESC";
            params = new Object[]{drawNo};
        } else {
            sql = "SELECT " + cols + " FROM lotto_results ORDER BY draw_no DESC LIMIT ?";
            params = new Object[]{limit};
        }
        var rows = jdbc.queryForList(sql, params);

        // 각 회차의 추천 목록(rec_no=1..3) 조인
        for (var row : rows) {
            Integer dn = (Integer) row.get("draw_no");
            var recs = jdbc.queryForList(
                    "SELECT rec_no, numbers, bonus, match_count, miss_count, bonus_match, matched_nums, source " +
                    "FROM lotto_recommendations WHERE draw_no = ? " +
                    "ORDER BY CASE source WHEN 'llm' THEN 0 ELSE 1 END, rec_no",
                    dn);
            row.put("recommendations", recs);
        }
        return ResponseEntity.ok(ApiResponse.ok(rows));
    }

    // 분석 통계 (전체 분석 결과 요약)
    @GetMapping("/analysis-stats")
    public ResponseEntity<?> analysisStats() {
        var summary = jdbc.queryForMap(
                "SELECT COUNT(*) AS analyzed, " +
                "AVG(match_count)::numeric(10,2) AS avg_match, " +
                "MAX(match_count) AS max_match, " +
                "SUM(CASE WHEN match_count >= 3 THEN 1 ELSE 0 END) AS hit3plus " +
                "FROM lotto_results WHERE llm_analysis IS NOT NULL");
        var dist = jdbc.queryForList(
                "SELECT match_count, COUNT(*) AS cnt FROM lotto_results " +
                "WHERE llm_analysis IS NOT NULL GROUP BY match_count ORDER BY match_count DESC");
        Map<String, Object> data = new HashMap<>();
        data.put("summary", summary);
        data.put("distribution", dist);
        return ResponseEntity.ok(ApiResponse.ok(data));
    }

    // 배치 분석 트리거 (Python에 위임)
    @PostMapping("/analyze-batch")
    public ResponseEntity<?> analyzeBatch(@RequestBody(required = false) Map<String, Object> body) {
        try {
            RestTemplate rest = new RestTemplate();
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body != null ? body : new HashMap<>(), headers);
            @SuppressWarnings("unchecked")
            Map<String, Object> response = rest.postForObject(AI_API + "/api/v1/lotto/analyze-batch", entity, Map.class);
            if (response != null && Boolean.TRUE.equals(response.get("success"))) {
                return ResponseEntity.ok(ApiResponse.ok(response.get("data")));
            }
            return ResponseEntity.ok(ApiResponse.error("배치 분석 시작 실패"));
        } catch (Exception e) {
            return ResponseEntity.ok(ApiResponse.error("AI 서버 연결 실패: " + e.getMessage()));
        }
    }

    // 전체 회차 목록 (콤보용)
    @GetMapping("/draws")
    public ResponseEntity<?> getDraws() {
        var rows = jdbc.queryForList("SELECT draw_no, draw_date FROM lotto_results ORDER BY draw_no DESC");
        return ResponseEntity.ok(ApiResponse.ok(rows));
    }

    // LLM 처리 시간을 고려한 RestTemplate (connect 5s, read 120s)
    private RestTemplate llmRestTemplate() {
        SimpleClientHttpRequestFactory f = new SimpleClientHttpRequestFactory();
        f.setConnectTimeout(5000);
        f.setReadTimeout(120000);
        return new RestTemplate(f);
    }

    // 추천 번호 생성 (Python agri_ai_core에 위임 — LLM 호출로 ~20초 소요)
    @PostMapping("/recommend")
    public ResponseEntity<?> recommend(@RequestBody(required = false) Map<String, String> body) {
        try {
            RestTemplate rest = llmRestTemplate();
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);

            Map<String, String> payload = new HashMap<>();
            payload.put("prompt", body != null ? body.getOrDefault("prompt", "") : "");

            HttpEntity<Map<String, String>> entity = new HttpEntity<>(payload, headers);
            @SuppressWarnings("unchecked")
            Map<String, Object> response = rest.postForObject(AI_API + "/api/v1/lotto/recommend", entity, Map.class);

            if (response != null && Boolean.TRUE.equals(response.get("success"))) {
                return ResponseEntity.ok(ApiResponse.ok(response.get("data")));
            }
            return ResponseEntity.ok(ApiResponse.error("추천 번호 생성 실패"));
        } catch (Exception e) {
            return ResponseEntity.ok(ApiResponse.error("AI 서버 연결 실패: " + e.getMessage()));
        }
    }

    // 알고리즘 설명 (Python에서 가져오기)
    @GetMapping("/algorithm")
    public ResponseEntity<?> algorithm() {
        try {
            RestTemplate rest = new RestTemplate();
            @SuppressWarnings("unchecked")
            Map<String, Object> response = rest.getForObject(AI_API + "/api/v1/lotto/algorithm", Map.class);
            if (response != null && Boolean.TRUE.equals(response.get("success"))) {
                return ResponseEntity.ok(ApiResponse.ok(response.get("data")));
            }
            return ResponseEntity.ok(ApiResponse.error("알고리즘 정보 조회 실패"));
        } catch (Exception e) {
            return ResponseEntity.ok(ApiResponse.error("AI 서버 연결 실패: " + e.getMessage()));
        }
    }
}
