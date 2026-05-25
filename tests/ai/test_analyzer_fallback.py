# ══════════════════════════════════════════════════════════════════════════════
# test_analyzer_fallback — Ollama 503 fallback 의 키워드 기반 분기 검증
#                          [2026-05-25 C 단계 hotfix3]
#
# 대상: agri_ai_core.src.ai.pipeline.question_analyzer._build_safe_fallback
#   · 기존 (사고 시점): 무조건 web_search
#   · 수정: 모니터링/농장 키워드 매칭 시 합리적 type 으로 분기
#
# 이 회귀 테스트가 PASS 하지 않으면 채팅창에서 "릴레이/재배사/모니터링"
# 같은 명백한 농장 쿼리가 Ollama 503 시 외부 web_search 로 떨어져
# 무의미한 답변을 받게 됨 (2026-05-25 19:42 사고 이력).
#
# 파일 시작 함수 목록:
#   TestMonitorTimeBranch     : 모니터링 + 시간 → agent_monitor
#   TestFarmSensorBranch      : 농장 센서/릴레이/제어 → farm_sensor
#   TestWebSearchDefault      : 그 외 일반 검색 → web_search (기존 보전)
#   TestPlanStructure         : 반환 dict 의 필수 필드 보전
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai.pipeline.question_analyzer import _build_safe_fallback


# ────────────────────────────────────────────────────────────────────
# 1) 모니터링 + 시간 키워드 → agent_monitor + list_monitors
# ────────────────────────────────────────────────────────────────────
class TestMonitorTimeBranch:
    def test_5min_monitoring(self):
        p = _build_safe_fallback("1호 재배사를 5분 단위로 모니터링하라", 1, 1)
        assert p["question_type"] == "agent_monitor"
        tools = [d["tool"] for d in p["required_data"]]
        assert "list_monitors" in tools

    def test_5min_monitoring_typo(self):
        # 실 사용자 쿼리 (2026-05-25 19:40) — "모티터링" 오타 + "5분단위"
        p = _build_safe_fallback("1호 재배사의 릴레이 세싱을 5분단위로 모티터링하고 결과 출력하라.", 1, 1)
        assert p["question_type"] == "agent_monitor", \
            f"오타 '모티터링' 도 agent_monitor 로 분기되어야 함 (got {p['question_type']})"

    def test_1hour_monitoring(self):
        p = _build_safe_fallback("1시간 단위로 각 재배사 감시하라", 1, None)
        assert p["question_type"] == "agent_monitor"

    def test_jiyeobwa_keyword(self):
        # 사용자가 실제 19:48 보낸 쿼리 (오타 포함)
        p = _build_safe_fallback("지금부터 1시간 단위로각 재배사의 릴레이 제어 상태를 모니터링하고 요약해서 내게 설명하라", None, None)
        assert p["question_type"] == "agent_monitor", \
            f"실 사용자 쿼리가 agent_monitor 로 분기되어야 함 (got {p['question_type']})"

    def test_overnight_watch(self):
        p = _build_safe_fallback("오늘 밤 재배사 지켜봐", 1, 1)
        assert p["question_type"] == "agent_monitor"


# ────────────────────────────────────────────────────────────────────
# 2) 농장 데이터/제어 키워드 → farm_sensor + get_farm_realtime_data
# ────────────────────────────────────────────────────────────────────
class TestFarmSensorBranch:
    def test_relay_keyword(self):
        # 사용자가 실제 19:40 보낸 쿼리 — 모니터링은 없지만 릴레이 키워드
        p = _build_safe_fallback("1호 재배사의 릴레이 상태 알려줘", 1, 1)
        assert p["question_type"] == "farm_sensor"
        tools = [d["tool"] for d in p["required_data"]]
        assert "get_farm_realtime_data" in tools
        # 도구 args 에 farm_id/house_id 포함
        args = p["required_data"][0]["args"]
        assert args["data_type"] == "all"
        assert args["farm_id"] == "1"
        assert args["house_id"] == "1"

    def test_sensor_keyword(self):
        p = _build_safe_fallback("센서값 보여줘", 1, 2)
        assert p["question_type"] == "farm_sensor"

    def test_temperature_keyword(self):
        p = _build_safe_fallback("내부온도 어때?", 1, 3)
        assert p["question_type"] == "farm_sensor"

    def test_co2_keyword(self):
        p = _build_safe_fallback("CO2 농도가 어떤가요", 1, 1)
        assert p["question_type"] == "farm_sensor"

    def test_house_keyword(self):
        p = _build_safe_fallback("2호기 상태 알려줘", 1, None)
        assert p["question_type"] == "farm_sensor"

    def test_control_keyword(self):
        # 장치 제어 키워드도 farm_sensor 로 — 현재 상태 먼저 보고 결정
        p = _build_safe_fallback("히터 켜줘", 1, 1)
        assert p["question_type"] == "farm_sensor"

    def test_house_id_all_when_unspecified(self):
        p = _build_safe_fallback("재배사 상태 알려줘", 1, None)
        args = p["required_data"][0]["args"]
        assert args["house_id"] == "all"
        assert p["multi_house"] is True
        assert p["house_ids"] == ["all"]


# ────────────────────────────────────────────────────────────────────
# 3) 그 외 → 기존 web_search 보전 (회귀 방지)
# ────────────────────────────────────────────────────────────────────
class TestWebSearchDefault:
    def test_weather_question(self):
        # 농장 키워드 없음 → web_search default 유지
        p = _build_safe_fallback("성남시 내일 날씨 어때?", None, None)
        assert p["question_type"] == "web_search"
        tools = [d["tool"] for d in p["required_data"]]
        assert "search_web" in tools

    def test_general_search(self):
        p = _build_safe_fallback("느타리버섯 키우는 법", None, None)
        assert p["question_type"] == "web_search"

    def test_empty_query(self):
        p = _build_safe_fallback("", None, None)
        assert p["question_type"] == "web_search"

    def test_none_query(self):
        p = _build_safe_fallback(None, None, None)
        assert p["question_type"] == "web_search"


# ────────────────────────────────────────────────────────────────────
# 4) 반환 dict 의 필수 필드 보전 (기존 호출자 계약)
# ────────────────────────────────────────────────────────────────────
class TestPlanStructure:
    REQUIRED_KEYS = {
        "question_type", "intent", "required_data", "data_freshness",
        "answer_format", "multi_house", "house_ids",
    }

    def test_keys_present_for_all_branches(self):
        for query in ("1호기 릴레이 보여줘", "5분마다 모니터링", "오늘 날씨"):
            p = _build_safe_fallback(query, 1, 1)
            missing = self.REQUIRED_KEYS - set(p.keys())
            assert not missing, f"query={query!r}: 누락 키 {missing}"

    def test_intent_truncated_to_100(self):
        long_query = "릴레이 " + "x" * 200
        p = _build_safe_fallback(long_query, 1, 1)
        assert len(p["intent"]) <= 100


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
