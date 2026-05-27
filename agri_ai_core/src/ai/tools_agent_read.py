# ══════════════════════════════════════════════════════════════════════════════
# Agent 전용 read-only 도구 모음
#
# ReAct 패턴의 agent 가 호출하는 read-only 도구 5개:
#   1. get_sensor_window         — 최근 N분 센서 평균/min/max
#   2. get_recent_decisions      — LLM 결정 이력 (ai_decision_log)
#   3. get_relay_state           — 현재 16핀 릴레이 + 시멘틱 라벨
#   4. compare_houses            — 같은 농장 호기 비교 (이상치 검출)
#   5. get_thresholds            — sensor_m_setting 임계값
#
# 설계 원칙 (dev_agent.md §3):
#   · read-only — DB write 일체 없음
#   · args validation — 가벼운 수동 검증
#   · 항상 dict 반환 (성공·실패 모두) — LLM 이 동일 형식으로 파싱
#   · 예외는 잡아서 {"error": "..."} 형태 — agent loop 가 다음 step 결정
#
# 파일 시작 함수 목록:
#   get_sensor_window         : 호기 최근 N분 센서 통계
#   get_recent_decisions      : LLM 결정 이력 (action·circulation·reason)
#   get_relay_state           : 현재 릴레이 시멘틱 ON 셋
#   compare_houses            : 같은 농장 호기 metric 비교 + 이상치
#   get_thresholds            : sensor_m_setting 임계값
#   TOOL_REGISTRY             : 도구명 → 함수 매핑 (agent loop 사용)
#   TOOL_SPECS                : 도구 spec list (LLM 프롬프트 주입용)
#   tool_specs_text           : TOOL_SPECS → 사람 가독 텍스트
# ══════════════════════════════════════════════════════════════════════════════
from typing import Any, Dict, List

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# 1) get_sensor_window — 호기 최근 N분 센서 통계 (평균/min/max)
# ────────────────────────────────────────────────────────────────────
def get_sensor_window(farm: int, house: int, minutes: int) -> Dict[str, Any]:
    if not isinstance(farm, int) or not isinstance(house, int):
        return {"error": "farm, house 는 정수"}
    if not isinstance(minutes, int) or minutes < 1 or minutes > 1440:
        return {"error": "minutes 는 1~1440 사이 정수"}
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as db:
            rows = db.fetch_all(
                "SELECT count(*),"
                " avg(indr_tprt_valu), min(indr_tprt_valu), max(indr_tprt_valu),"
                " avg(indr_hmdt_valu), min(indr_hmdt_valu), max(indr_hmdt_valu),"
                " avg(co2_valu),       min(co2_valu),       max(co2_valu),"
                " avg(watr_tprt_valu), min(watr_tprt_valu), max(watr_tprt_valu),"
                " avg(oudr_tprt_valu), avg(oudr_hmdt_valu) "
                "FROM sensor_l_recording "
                "WHERE farm_id=%s AND hous_id=%s "
                "AND recd_dttm > NOW() - %s::interval",
                (farm, house, f"{minutes} minutes"),
            )
        if not rows or rows[0][0] == 0:
            return {"success": True, "farm": farm, "house": house, "minutes": minutes,
                    "n": 0, "note": "최근 N분 안 데이터 없음"}
        r = rows[0]
        return {
            "success": True, "farm": farm, "house": house, "minutes": minutes, "n": int(r[0]),
            "indoor_temp":  {"avg": _f(r[1]),  "min": _f(r[2]),  "max": _f(r[3])},
            "humidity":     {"avg": _f(r[4]),  "min": _f(r[5]),  "max": _f(r[6])},
            "co2":          {"avg": _f(r[7]),  "min": _f(r[8]),  "max": _f(r[9])},
            "water_temp":   {"avg": _f(r[10]), "min": _f(r[11]), "max": _f(r[12])},
            "outdoor_temp":     {"avg": _f(r[13])},
            "outdoor_humidity": {"avg": _f(r[14])},
        }
    except Exception as e:
        logger.warning(f"[tools_agent_read] get_sensor_window 실패: {e}")
        return {"error": f"DB 조회 실패: {e}"}


# ────────────────────────────────────────────────────────────────────
# 2) get_recent_decisions — ai_decision_log 이력 (house_id 컬럼명 주의)
# ────────────────────────────────────────────────────────────────────
def get_recent_decisions(farm: int, house: int, hours: int = 1) -> Dict[str, Any]:
    if not isinstance(farm, int) or not isinstance(house, int):
        return {"error": "farm, house 는 정수"}
    if not isinstance(hours, int) or hours < 1 or hours > 24:
        return {"error": "hours 는 1~24 사이 정수"}
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as db:
            stats = db.fetch_all(
                "SELECT count(*),"
                " count(*) FILTER (WHERE action='change'),"
                " count(*) FILTER (WHERE action='keep') "
                "FROM ai_decision_log "
                "WHERE farm_id=%s AND house_id=%s "
                "AND decided_at > NOW() - %s::interval",
                (farm, house, f"{hours} hours"),
            )
            total, chg, kp = stats[0]
            rows = db.fetch_all(
                "SELECT to_char(decided_at,'YYYY-MM-DD HH24:MI:SS'), action, circulation,"
                " water_heater, fog_occurs, left(reason, 200) "
                "FROM ai_decision_log "
                "WHERE farm_id=%s AND house_id=%s "
                "AND decided_at > NOW() - %s::interval "
                "ORDER BY decided_at DESC LIMIT 20",
                (farm, house, f"{hours} hours"),
            )
        return {
            "success": True, "farm": farm, "house": house, "hours": hours,
            "total": int(total or 0), "change_count": int(chg or 0), "keep_count": int(kp or 0),
            "decisions": [
                {"at": r[0], "action": r[1], "circulation": r[2],
                 "heater": r[3], "fog": r[4], "reason": r[5]}
                for r in rows
            ],
        }
    except Exception as e:
        logger.warning(f"[tools_agent_read] get_recent_decisions 실패: {e}")
        return {"error": f"DB 조회 실패: {e}"}


# ────────────────────────────────────────────────────────────────────
# 3) get_relay_state — 현재 16핀 릴레이 + 시멘틱 ON 셋
# ────────────────────────────────────────────────────────────────────
def get_relay_state(farm: int, house: int) -> Dict[str, Any]:
    if not isinstance(farm, int) or not isinstance(house, int):
        return {"error": "farm, house 는 정수"}
    cols = [f"relay_{i}st_flag" for i in range(1, 17)]
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        from agri_ai_core.src.control.control_common import get_pin_map, SEMANTIC_LABELS
        with db_session() as db:
            rows = db.fetch_all(
                f"SELECT to_char(recd_dttm,'YYYY-MM-DD HH24:MI:SS'), {', '.join(cols)} "
                f"FROM relay_l_recording WHERE farm_id=%s AND hous_id=%s "
                f"ORDER BY recd_dttm DESC LIMIT 1",
                (farm, house),
            )
        if not rows:
            return {"success": True, "farm": farm, "house": house, "note": "릴레이 기록 없음"}
        row = rows[0]
        recorded_at = row[0]
        raw_flags = {cols[i]: _bool_flag(row[i+1]) for i in range(16)}
        pin_map = get_pin_map(house)
        inverse = {pin: sem for sem, pin in pin_map.items()}
        semantic_on: List[str] = []
        for pin, on in raw_flags.items():
            if on:
                sem = inverse.get(pin)
                if sem:
                    label = SEMANTIC_LABELS.get(sem, sem)
                    semantic_on.append(label)
        return {
            "success": True, "farm": farm, "house": house, "recorded_at": recorded_at,
            "raw_flags": raw_flags, "semantic_on": sorted(semantic_on),
        }
    except Exception as e:
        logger.warning(f"[tools_agent_read] get_relay_state 실패: {e}")
        return {"error": f"DB 조회 실패: {e}"}


# ────────────────────────────────────────────────────────────────────
# 4) compare_houses — 같은 농장 호기 간 metric 비교 + 이상치(±2σ)
# ────────────────────────────────────────────────────────────────────
_METRIC_COL = {
    'indoor_temp':  'indr_tprt_valu',
    'humidity':     'indr_hmdt_valu',
    'co2':          'co2_valu',
    'water_temp':   'watr_tprt_valu',
    'outdoor_temp': 'oudr_tprt_valu',
}

def compare_houses(farm: int, metric: str) -> Dict[str, Any]:
    if not isinstance(farm, int):
        return {"error": "farm 은 정수"}
    if metric not in _METRIC_COL:
        return {"error": f"metric 은 {list(_METRIC_COL)} 중 하나"}
    col = _METRIC_COL[metric]
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as db:
            rows = db.fetch_all(
                f"SELECT h.hous_id, "
                f" (SELECT {col} FROM sensor_l_recording WHERE farm_id=%s AND hous_id=h.hous_id::bigint ORDER BY recd_dttm DESC LIMIT 1),"
                f" (SELECT avg({col}) FROM sensor_l_recording WHERE farm_id=%s AND hous_id=h.hous_id::bigint AND recd_dttm > NOW() - INTERVAL '60 minutes') "
                f"FROM farmhouse_m_info h "
                f"WHERE h.farm_id=%s AND h.hous_id > 0 "
                f"AND COALESCE(h.dlte_yn,'N') <> 'Y' "
                f"ORDER BY h.hous_id",
                (farm, farm, farm),
            )
        houses = []
        for r in rows:
            houses.append({"house": int(r[0]), "current": _f(r[1]), "avg_60min": _f(r[2])})
        currents = [h['current'] for h in houses if h['current'] is not None]
        outliers = []
        if len(currents) >= 3:
            mean = sum(currents) / len(currents)
            var = sum((x - mean) ** 2 for x in currents) / len(currents)
            sigma = var ** 0.5
            for h in houses:
                if h['current'] is not None and sigma > 0 and abs(h['current'] - mean) > 2 * sigma:
                    outliers.append({"house": h['house'], "current": h['current'],
                                     "mean": round(mean, 2), "sigma": round(sigma, 2),
                                     "deviation": round((h['current'] - mean) / sigma, 2)})
        return {"success": True, "farm": farm, "metric": metric,
                "houses": houses, "outliers": outliers}
    except Exception as e:
        logger.warning(f"[tools_agent_read] compare_houses 실패: {e}")
        return {"error": f"DB 조회 실패: {e}"}


# ────────────────────────────────────────────────────────────────────
# 5) get_thresholds — sensor_m_setting 임계값
# ────────────────────────────────────────────────────────────────────
def get_thresholds(farm: int, house: int) -> Dict[str, Any]:
    if not isinstance(farm, int) or not isinstance(house, int):
        return {"error": "farm, house 는 정수"}
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as db:
            # sensor_m_setting 은 (farm_id, hous_id, setn_dttm) PK 로 같은 호기에 여러 row 누적.
            # ORDER BY 없이 LIMIT 하면 임의 옛 row 가 선택되어 LLM 이 잘못된 임계값으로
            # 판단할 수 있으므로 최신 setn_dttm 한 건만 잡도록 명시.
            rows = db.fetch_all(
                "SELECT tprt_min, tprt_otml, tprt_max, tprt_crit_min, tprt_crit_max,"
                " hmdt_min, hmdt_otml, hmdt_max, hmdt_crit_min, hmdt_crit_max,"
                " co2_min, co2_otml, co2_max, co2_crit_max,"
                " watr_tprt_min, watr_tprt_otml, watr_tprt_max, watr_tprt_crit_min, watr_tprt_crit_max,"
                " bud_tprt_min, bud_tprt_max "
                "FROM sensor_m_setting WHERE farm_id=%s AND hous_id=%s "
                "ORDER BY setn_dttm DESC LIMIT 1",
                (farm, house),
            )
        if not rows:
            return {"success": True, "farm": farm, "house": house, "note": "임계 미설정"}
        r = rows[0]
        return {
            "success": True, "farm": farm, "house": house,
            "indoor_temp":  {"min": _f(r[0]), "optimal": _f(r[1]), "max": _f(r[2]),
                             "crit_min": _f(r[3]), "crit_max": _f(r[4])},
            "humidity":     {"min": _f(r[5]), "optimal": _f(r[6]), "max": _f(r[7]),
                             "crit_min": _f(r[8]), "crit_max": _f(r[9])},
            "co2":          {"min": _f(r[10]), "optimal": _f(r[11]), "max": _f(r[12]),
                             "crit_max": _f(r[13])},
            "water_temp":   {"min": _f(r[14]), "optimal": _f(r[15]), "max": _f(r[16]),
                             "crit_min": _f(r[17]), "crit_max": _f(r[18])},
            "budding":      {"min": _f(r[19]), "max": _f(r[20])},
        }
    except Exception as e:
        logger.warning(f"[tools_agent_read] get_thresholds 실패: {e}")
        return {"error": f"DB 조회 실패: {e}"}


# ────────────────────────────────────────────────────────────────────
# 6) get_all_house_status — 전체 호기 상태를 한 번에 요약
# ────────────────────────────────────────────────────────────────────
def get_all_house_status(
    farm: int,
    minutes: int = 10,
    decision_hours: int = 2,
) -> Dict[str, Any]:
    """농장 전체 호기의 센서·릴레이·최근 제어판단·임계값을 read-only 로 조회."""
    if not isinstance(farm, int):
        return {"error": "farm 은 정수"}
    if not isinstance(minutes, int) or minutes < 1 or minutes > 1440:
        return {"error": "minutes 는 1~1440 사이 정수"}
    if not isinstance(decision_hours, int) or decision_hours < 1 or decision_hours > 24:
        return {"error": "decision_hours 는 1~24 사이 정수"}

    relay_cols = [f"relay_{i}st_flag" for i in range(1, 17)]
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        from agri_ai_core.src.control.control_common import get_pin_map, SEMANTIC_LABELS

        with db_session() as db:
            sensor_rows = db.fetch_all(
                "SELECT h.hous_id, COALESCE(h.hous_name, h.hous_id::text) AS house_name, "
                "       TO_CHAR(s.recd_dttm,'YYYY-MM-DD HH24:MI:SS') AS sensor_at, "
                "       s.indr_tprt_valu, s.indr_hmdt_valu, s.co2_valu, "
                "       s.watr_tprt_valu, s.oudr_tprt_valu, s.oudr_hmdt_valu "
                "FROM farmhouse_m_info h "
                "LEFT JOIN LATERAL ( "
                "    SELECT recd_dttm, indr_tprt_valu, indr_hmdt_valu, co2_valu, "
                "           watr_tprt_valu, oudr_tprt_valu, oudr_hmdt_valu "
                "    FROM sensor_l_recording "
                "    WHERE farm_id=%s AND hous_id=h.hous_id::bigint "
                "    ORDER BY recd_dttm DESC LIMIT 1 "
                ") s ON TRUE "
                "WHERE h.farm_id=%s AND h.hous_id > 0 "
                "  AND COALESCE(h.dlte_yn,'N') <> 'Y' "
                "ORDER BY h.hous_id",
                (farm, farm),
                as_dict=True,
            )
            window_rows = db.fetch_all(
                "SELECT hous_id, COUNT(*) AS n, "
                "       AVG(indr_tprt_valu) AS indoor_temp_avg, "
                "       AVG(indr_hmdt_valu) AS humidity_avg, "
                "       AVG(co2_valu) AS co2_avg, "
                "       AVG(watr_tprt_valu) AS water_temp_avg "
                "FROM sensor_l_recording "
                "WHERE farm_id=%s AND recd_dttm > NOW() - %s::interval "
                "GROUP BY hous_id",
                (farm, f"{minutes} minutes"),
                as_dict=True,
            )
            relay_rows = db.fetch_all(
                f"SELECT h.hous_id, TO_CHAR(r.recd_dttm,'YYYY-MM-DD HH24:MI:SS') AS relay_at, "
                f"       {', '.join('r.' + c for c in relay_cols)} "
                f"FROM farmhouse_m_info h "
                f"LEFT JOIN LATERAL ( "
                f"    SELECT recd_dttm, {', '.join(relay_cols)} "
                f"    FROM relay_l_recording "
                f"    WHERE farm_id=%s AND hous_id=h.hous_id::bigint "
                f"    ORDER BY recd_dttm DESC LIMIT 1 "
                f") r ON TRUE "
                f"WHERE h.farm_id=%s AND h.hous_id > 0 "
                f"  AND COALESCE(h.dlte_yn,'N') <> 'Y' "
                f"ORDER BY h.hous_id",
                (farm, farm),
                as_dict=True,
            )
            decision_rows = db.fetch_all(
                "SELECT h.hous_id, TO_CHAR(d.decided_at,'YYYY-MM-DD HH24:MI:SS') AS decided_at, "
                "       d.action, d.circulation, d.water_heater, d.fog_occurs, "
                "       d.drainage_motor, LEFT(COALESCE(d.reason,''), 240) AS reason "
                "FROM farmhouse_m_info h "
                "LEFT JOIN LATERAL ( "
                "    SELECT decided_at, action, circulation, water_heater, fog_occurs, "
                "           drainage_motor, reason "
                "    FROM ai_decision_log "
                "    WHERE farm_id=%s AND house_id=h.hous_id::integer "
                "    ORDER BY decided_at DESC LIMIT 1 "
                ") d ON TRUE "
                "WHERE h.farm_id=%s AND h.hous_id > 0 "
                "  AND COALESCE(h.dlte_yn,'N') <> 'Y' "
                "ORDER BY h.hous_id",
                (farm, farm),
                as_dict=True,
            )
            decision_count_rows = db.fetch_all(
                "SELECT house_id, COUNT(*) AS total, "
                "       COUNT(*) FILTER (WHERE action='change') AS change_count, "
                "       COUNT(*) FILTER (WHERE action='keep') AS keep_count "
                "FROM ai_decision_log "
                "WHERE farm_id=%s AND decided_at > NOW() - %s::interval "
                "GROUP BY house_id",
                (farm, f"{decision_hours} hours"),
                as_dict=True,
            )
            threshold_rows = db.fetch_all(
                "SELECT h.hous_id, t.tprt_min, t.tprt_otml, t.tprt_max, "
                "       t.hmdt_min, t.hmdt_otml, t.hmdt_max, "
                "       t.co2_min, t.co2_otml, t.co2_max, "
                "       t.watr_tprt_min, t.watr_tprt_otml, t.watr_tprt_max "
                "FROM farmhouse_m_info h "
                "LEFT JOIN LATERAL ( "
                "    SELECT tprt_min, tprt_otml, tprt_max, "
                "           hmdt_min, hmdt_otml, hmdt_max, "
                "           co2_min, co2_otml, co2_max, "
                "           watr_tprt_min, watr_tprt_otml, watr_tprt_max "
                "    FROM sensor_m_setting "
                "    WHERE farm_id=%s AND hous_id=h.hous_id::bigint "
                "    ORDER BY setn_dttm DESC LIMIT 1 "
                ") t ON TRUE "
                "WHERE h.farm_id=%s AND h.hous_id > 0 "
                "  AND COALESCE(h.dlte_yn,'N') <> 'Y' "
                "ORDER BY h.hous_id",
                (farm, farm),
                as_dict=True,
            )

        windows = {int(r["hous_id"]): r for r in window_rows}
        relays = {int(r["hous_id"]): r for r in relay_rows}
        decisions = {int(r["hous_id"]): r for r in decision_rows}
        decision_counts = {int(r["house_id"]): r for r in decision_count_rows if r.get("house_id") is not None}
        thresholds = {int(r["hous_id"]): r for r in threshold_rows}

        houses = []
        for s in sensor_rows:
            house = int(s["hous_id"])
            threshold = _compact_thresholds(thresholds.get(house))
            current = {
                "at": s.get("sensor_at"),
                "indoor_temp": _f(s.get("indr_tprt_valu")),
                "humidity": _f(s.get("indr_hmdt_valu")),
                "co2": _f(s.get("co2_valu")),
                "water_temp": _f(s.get("watr_tprt_valu")),
                "outdoor_temp": _f(s.get("oudr_tprt_valu")),
                "outdoor_humidity": _f(s.get("oudr_hmdt_valu")),
            }
            w = windows.get(house) or {}
            relay = relays.get(house) or {}
            pin_map = get_pin_map(house)
            inverse = {pin: sem for sem, pin in pin_map.items()}
            semantic_on: List[str] = []
            raw_flags: Dict[str, bool] = {}
            for col in relay_cols:
                on = _bool_flag(relay.get(col))
                raw_flags[col] = on
                if on:
                    sem = inverse.get(col)
                    if sem:
                        semantic_on.append(SEMANTIC_LABELS.get(sem, sem))
            d = decisions.get(house) or {}
            dc = decision_counts.get(house) or {}
            houses.append({
                "house": house,
                "name": s.get("house_name"),
                "sensor_current": current,
                "sensor_window": {
                    "minutes": minutes,
                    "n": int(w.get("n") or 0),
                    "indoor_temp_avg": _f(w.get("indoor_temp_avg")),
                    "humidity_avg": _f(w.get("humidity_avg")),
                    "co2_avg": _f(w.get("co2_avg")),
                    "water_temp_avg": _f(w.get("water_temp_avg")),
                },
                "relay": {
                    "at": relay.get("relay_at"),
                    "semantic_on": sorted(semantic_on),
                    "raw_flags": raw_flags,
                },
                "latest_decision": {
                    "at": d.get("decided_at"),
                    "action": d.get("action"),
                    "circulation": d.get("circulation"),
                    "heater": d.get("water_heater"),
                    "fog": d.get("fog_occurs"),
                    "drain": d.get("drainage_motor"),
                    "reason": d.get("reason"),
                    "recent_hours": decision_hours,
                    "recent_total": int(dc.get("total") or 0),
                    "recent_change_count": int(dc.get("change_count") or 0),
                    "recent_keep_count": int(dc.get("keep_count") or 0),
                },
                "thresholds": threshold,
                "status_flags": _status_flags(current, threshold),
            })
        return {
            "success": True,
            "farm": farm,
            "minutes": minutes,
            "decision_hours": decision_hours,
            "house_count": len(houses),
            "houses": houses,
            "note": "전체 재배사의 센서·릴레이·최근 LLM 판단·임계값을 한 번에 조회한 read-only 결과",
        }
    except Exception as e:
        logger.warning(f"[tools_agent_read] get_all_house_status 실패: {e}")
        return {"error": f"DB 조회 실패: {e}"}


def _compact_thresholds(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return {}
    return {
        "indoor_temp": {"min": _f(row.get("tprt_min")), "optimal": _f(row.get("tprt_otml")), "max": _f(row.get("tprt_max"))},
        "humidity": {"min": _f(row.get("hmdt_min")), "optimal": _f(row.get("hmdt_otml")), "max": _f(row.get("hmdt_max"))},
        "co2": {"min": _f(row.get("co2_min")), "optimal": _f(row.get("co2_otml")), "max": _f(row.get("co2_max"))},
        "water_temp": {"min": _f(row.get("watr_tprt_min")), "optimal": _f(row.get("watr_tprt_otml")), "max": _f(row.get("watr_tprt_max"))},
    }


def _status_flags(current: Dict[str, Any], thresholds: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    labels = {
        "indoor_temp": "내부온도",
        "humidity": "습도",
        "co2": "CO2",
        "water_temp": "수온",
    }
    for key, label in labels.items():
        value = current.get(key)
        limit = thresholds.get(key) or {}
        if value is None or not limit:
            continue
        low = limit.get("min")
        high = limit.get("max")
        if low is not None and value < low:
            flags.append(f"{label} 낮음({value} < {low})")
        if high is not None and value > high:
            flags.append(f"{label} 높음({value} > {high})")
    return flags


def _bool_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("1", "t", "true", "y", "yes", "on")


# ────────────────────────────────────────────────────────────────────
# Float 안전 변환 — Decimal/None 모두 처리
# ────────────────────────────────────────────────────────────────────
def _f(v):
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════
# Tool 등록 — agent loop 가 사용
# ════════════════════════════════════════════════════════════════════

TOOL_REGISTRY = {
    "get_sensor_window":    get_sensor_window,
    "get_recent_decisions": get_recent_decisions,
    "get_relay_state":      get_relay_state,
    "compare_houses":       compare_houses,
    "get_thresholds":       get_thresholds,
    "get_all_house_status": get_all_house_status,
}

TOOL_SPECS = [
    {
        "name": "get_sensor_window",
        "description": "특정 호기의 최근 N분 센서 통계 (평균/min/max) — 내부온도·습도·CO2·수온·외기",
        "args": {
            "farm":    {"type": "int", "desc": "농장 ID (예: 1)"},
            "house":   {"type": "int", "desc": "호기 ID (예: 1, 2, 3)"},
            "minutes": {"type": "int", "desc": "조회 윈도우(분), 1~1440"},
        },
    },
    {
        "name": "get_recent_decisions",
        "description": "특정 호기의 LLM 결정 이력 — action(change/keep), circulation, heater, fog, reason. 최대 20건",
        "args": {
            "farm":  {"type": "int"},
            "house": {"type": "int"},
            "hours": {"type": "int", "desc": "조회 윈도우(시간), 1~24"},
        },
    },
    {
        "name": "get_relay_state",
        "description": "특정 호기의 현재 16개 릴레이 상태 (시멘틱 ON 셋: 수온히터/포그/배수밸브/...)",
        "args": {
            "farm":  {"type": "int"},
            "house": {"type": "int"},
        },
    },
    {
        "name": "compare_houses",
        "description": "같은 농장의 호기 간 metric 비교. 평균에서 ±2σ 벗어난 호기는 outliers 에 표시 (이상치 검출)",
        "args": {
            "farm":   {"type": "int"},
            "metric": {"type": "str", "enum": ["indoor_temp", "humidity", "co2", "water_temp", "outdoor_temp"]},
        },
    },
    {
        "name": "get_thresholds",
        "description": "특정 호기의 임계값 (sensor_m_setting) — 정상범위·임계 상하한",
        "args": {
            "farm":  {"type": "int"},
            "house": {"type": "int"},
        },
    },
    {
        "name": "get_all_house_status",
        "description": "농장 전체 호기의 최신 센서, 최근 N분 평균, 현재 릴레이 ON 목록, 최근 LLM 제어 판단, 임계값을 한 번에 조회",
        "args": {
            "farm": {"type": "int"},
            "minutes": {"type": "int", "desc": "센서 평균 조회 윈도우(분), 기본 10, 1~1440"},
            "decision_hours": {"type": "int", "desc": "최근 LLM 판단 카운트 윈도우(시간), 기본 2, 1~24"},
        },
    },
]


def tool_specs_text() -> str:
    """LLM 시스템 프롬프트 주입용 사람 가독 텍스트."""
    lines = []
    for spec in TOOL_SPECS:
        args_desc = ", ".join(
            f"{k}({v.get('type')})" + (f"={v.get('desc')}" if v.get('desc') else "")
            for k, v in spec['args'].items()
        )
        lines.append(f"- {spec['name']}({args_desc}): {spec['description']}")
    return "\n".join(lines)
