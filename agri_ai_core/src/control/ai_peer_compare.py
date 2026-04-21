# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 재배사간 시점 비교 모듈 (M7)
# [2026-04-28 신규] 동일 농장 내 다른 재배사의 최신 10분 이내 센서/릴레이
# 스냅샷을 LLM 에 제공 → 합의/이상치 검출, 결정 일관성 향상.
#
# 호출 룰:
#   • control_ai_environment 에서만 import.
#   • 동급 control 모듈 import 금지.
#   • postgresql + logs 만 의존.
# --->
# get_peer_snapshot:    sensor + relay 한 번에 조회 (dict)
# format_peer_block:    user prompt 한 블록 텍스트
# ══════════════════════════════════════════════════════════════════════════════
from typing import Any, Dict, List

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
import agri_ai_core.src.postgresql.queries as dbQry

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# fetch_all 안전 래퍼 — 예외 시 WARNING 로그 후 [].
# ────────────────────────────────────────────────────────────────────
def _safe_fetch_all(query, vals, msg):
    try:
        with db_session() as database:
            return database.fetch_all(query=query, vals=vals, as_dict=True) or []
    except Exception as e:
        logger.warning(f"{msg}: {e}")
        return []


# ────────────────────────────────────────────────────────────────────
# 동일 농장 다른 재배사의 최신 센서/릴레이를 dict 로 반환.
# ────────────────────────────────────────────────────────────────────
def get_peer_snapshot(farm_id, house_id) -> Dict[str, Any]:
    logger.info(f"[AI재배사간] 비교 스냅샷 조회 시작 farm={farm_id} 기준 house={house_id}")
    sensors = _safe_fetch_all(
        dbQry.GET_PEER_HOUSES_LATEST_SENSOR,
        (int(farm_id), int(house_id)),
        f"[AI재배사간] 센서 조회 실패 farm={farm_id}",
    )
    relays = _safe_fetch_all(
        dbQry.GET_PEER_HOUSES_LATEST_RELAY,
        (int(farm_id), int(house_id)),
        f"[AI재배사간] 릴레이 조회 실패 farm={farm_id}",
    )
    relay_by_house = {int(r['hous_id']): dict(r) for r in relays if r.get('hous_id') is not None}
    out: Dict[str, Any] = {'sensors': [dict(s) for s in sensors], 'relays': relay_by_house}
    logger.info(
        f"[AI재배사간] 스냅샷 완료 farm={farm_id} 비교대상={len(sensors)}개 "
        f"릴레이={len(relay_by_house)}개"
    )
    return out


# ────────────────────────────────────────────────────────────────────
# 릴레이 dict → ON 장치 라벨 요약 문자열 ("ON=[히터,포그]").
# ────────────────────────────────────────────────────────────────────
def _relay_summary(r: Dict[str, Any]) -> str:
    if not r:
        return "릴레이 ?"
    on = []
    pairs = [
        ('relay_1st_flag', '히터'),
        ('relay_2st_flag', '포그'),
        ('relay_5st_flag', '흡팬'),
        ('relay_6st_flag', '배팬'),
        ('relay_7st_flag', '조명'),
        ('relay_10st_flag', '순환밸'),
        ('relay_11st_flag', '배기밸'),
        ('relay_14st_flag', '흡기밸'),
    ]
    for k, label in pairs:
        if r.get(k):
            on.append(label)
    return f"ON=[{','.join(on)}]" if on else "ON=[없음]"


# ────────────────────────────────────────────────────────────────────
# peer 스냅샷 dict → user prompt 한 블록 텍스트. 비어 있으면 "".
# ────────────────────────────────────────────────────────────────────
def format_peer_block(snapshot: Dict[str, Any]) -> str:
    sensors = snapshot.get('sensors') or [] if snapshot else []
    if not sensors:
        return ""
    relays = snapshot.get('relays') or {}
    lines = [f"[동일 농장 다른 재배사 동시점({len(sensors)}개) 센서/릴레이]"]
    for s in sensors:
        h = s.get('hous_id')
        rec = (s.get('record_datetime') or '')[-8:]  # HH:MM:SS
        lines.append(
            f"  · 재배사 {h} ({rec}): "
            f"내부 {s.get('indoor_temp')}℃/{s.get('indoor_humidity')}% · "
            f"CO2 {s.get('co2')}ppm · 수온 {s.get('water_temp')}℃ · "
            f"{_relay_summary(relays.get(int(h), {}))}"
        )
    return "\n".join(lines)
