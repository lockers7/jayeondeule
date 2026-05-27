# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 전력 사용량 추정 모듈 (M17)
# 실측 전력계가 없으므로, 최근 24h 릴레이 ON 비율을 기반으로
# 추정 가동 시간(시간 단위)을 산출. 장비별 정격 소비전력 매핑은 환경변수
# (POWER_W_<semantic>) 로 주입 가능 — 미설정 시 라벨만 제공.
#
# 호출 룰:
#   • control_ai_environment 에서만 import.
#   • 동급 control 모듈 import 금지.
# --->
# get_power_usage_24h: 24h 릴레이별 추정 가동시간 + (옵션) Wh
# format_power_block:  user prompt 한 블록
# ══════════════════════════════════════════════════════════════════════════════
import os
from typing import Any, Dict

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
import agri_ai_core.src.postgresql.queries as dbQry

logger = setup_logger(__name__)


# 정격 W 환경변수 키 매핑
_POWER_KEYS = {
    'heater_hours':       ('수온히터',  'POWER_W_HEATER'),
    'misting_hours':      ('포그생성',  'POWER_W_FOG'),
    'intake_fan_hours':   ('흡입팬',    'POWER_W_INTAKE_FAN'),
    'exhaust_fan_hours':  ('배출팬',    'POWER_W_EXHAUST_FAN'),
    'lighting_hours':     ('조명',      'POWER_W_LIGHTING'),
    'irrigation_hours':   ('관수',      'POWER_W_IRRIGATION'),
}


# ────────────────────────────────────────────────────────────────────
# 환경변수 값을 float 으로 안전 변환. 미설정/실패 시 None.
# ────────────────────────────────────────────────────────────────────
def _safe_float(env_key: str):
    v = os.getenv(env_key)
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


# ────────────────────────────────────────────────────────────────────
# 24h 릴레이별 추정 가동시간 + (옵션) Wh dict 반환.
# 표본 없을 시 {}.
# ────────────────────────────────────────────────────────────────────
def get_power_usage_24h(farm_id, house_id) -> Dict[str, Any]:
    logger.info(f"[AI전력] 24h 가동시간 조회 farm={farm_id} house={house_id}")
    try:
        with db_session() as database:
            row = database.fetch_one(
                query=dbQry.GET_POWER_USAGE_24H,
                vals=(int(farm_id), int(house_id)),
            )
    except Exception as e:
        logger.warning(f"[AI전력] 조회 실패 farm={farm_id} house={house_id}: {e}")
        return {}
    if not row or not row.get('sample_count'):
        logger.info(f"[AI전력] 표본 없음 farm={farm_id} house={house_id}")
        return {}

    devices = []
    total_wh = 0.0
    has_wh = False
    for hkey, (label, env_key) in _POWER_KEYS.items():
        hours = row.get(hkey)
        if hours is None:
            continue
        try:
            hours_f = float(hours)
        except (TypeError, ValueError):
            continue
        watt = _safe_float(env_key)
        wh = round(hours_f * watt, 1) if watt is not None else None
        if wh is not None:
            total_wh += wh
            has_wh = True
        devices.append({'label': label, 'hours': round(hours_f, 2), 'watt': watt, 'wh': wh})

    payload = {
        'sample_count': int(row.get('sample_count') or 0),
        'devices':      devices,
        'total_wh':     round(total_wh, 1) if has_wh else None,
    }
    logger.info(
        f"[AI전력] 완료 표본={payload['sample_count']} 항목={len(devices)} "
        f"총={payload['total_wh']}Wh"
    )
    return payload


# ────────────────────────────────────────────────────────────────────
# 전력 사용량 payload → user prompt 한 블록 텍스트.
# ────────────────────────────────────────────────────────────────────
def format_power_block(payload: Dict[str, Any]) -> str:
    if not payload or not payload.get('devices'):
        return ""
    devices = payload['devices']
    lines = [f"[24h 추정 전력/가동시간 (표본 {payload.get('sample_count','-')})]"]
    for d in devices:
        wh_str = f" / {d['wh']}Wh" if d.get('wh') is not None else ""
        watt_str = f" ({d['watt']}W)" if d.get('watt') is not None else ""
        lines.append(f"  · {d['label']}: {d['hours']}h{watt_str}{wh_str}")
    if payload.get('total_wh') is not None:
        lines.append(f"  · 총 추정 사용량: {payload['total_wh']}Wh")
    lines.append("  → 동일 효과면 가동시간이 짧은 옵션을 우선 고려.")
    return "\n".join(lines)
