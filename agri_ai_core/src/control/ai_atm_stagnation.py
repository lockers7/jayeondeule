# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 대기정체지수 모듈 (M13)
#
# 기상청 생활기상지수(getAirDiffusionIdxV4) — 대기정체지수 조회 →
# 시간대별 (3h 간격) 대기정체 강도 0~100 을 user_prompt 컨텍스트로 주입.
# 정체일은 환풍기 효율 저하 → CO2 배출 가중치 조정 LLM 힌트.
#
# 운영 노트:
#   · 환경변수:
#       ATM_STG_API_KEY    : data.go.kr 키 (미설정 시 KMA_API_KEY 폴백)
#       ATM_STG_AREA_NO    : 행정구역코드 10자리 (정읍 시군구 = 4518000000)
#       ATM_STG_AREA_NAME  : (선택) 로그용 라벨 (예: '정읍시')
#       ATM_STG_URL        : (선택) endpoint override
#   · KMA 발표 시각: 매일 06시, 18시. 가장 가까운 과거 발표 시각으로 호출.
#   · 활용신청 직후엔 KMA 전파 대기로 403 발생 — 빈 결과로 안전 처리.
#   · 캐시 6시간 — 12시간 단위 발표라 충분 여유.
#
# 호출 룰:
#   • control/ai_control 에서만 import. 동급 control 모듈 import 금지.
# --->
# get_atm_stagnation:           (farm_id) → 시간대별 정체지수 dict
# format_atm_stagnation_block:  user prompt 한 블록
# ══════════════════════════════════════════════════════════════════════════════
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.utils.http_client import http_json_request

logger = setup_logger(__name__)


_CACHE_TTL = 21600  # 6시간 (발표 12h 간격 안전 여유)
# V4 는 이 키에 미승인(403) — 반드시 LivingWthrIdxServiceV5 엔드포인트 사용.
_DEFAULT_URL = "https://apis.data.go.kr/1360000/LivingWthrIdxServiceV5/getAirDiffusionIdxV5"

# {farm_id: (expires_at, payload)}
_CACHE: Dict[int, tuple] = {}


def _cache_get(key):
    e = _CACHE.get(key)
    if not e:
        return None
    if time.time() >= e[0]:
        _CACHE.pop(key, None)
        return None
    return e[1]


def _cache_put(key, payload):
    _CACHE[key] = (time.time() + _CACHE_TTL, payload)


# ────────────────────────────────────────────────────────────────────
# 가장 가까운 과거 발표시각(YYYYMMDDHH) 산출. KMA 발표 = 매일 06,18시.
# ────────────────────────────────────────────────────────────────────
def _nearest_base_time() -> str:
    now = datetime.now()
    if now.hour >= 18:
        base = now.replace(hour=18, minute=0, second=0, microsecond=0)
    elif now.hour >= 6:
        base = now.replace(hour=6, minute=0, second=0, microsecond=0)
    else:
        base = (now - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
    return base.strftime("%Y%m%d%H")


# ────────────────────────────────────────────────────────────────────
# 대기정체지수 0~100 → 등급 라벨.
# ────────────────────────────────────────────────────────────────────
def _stg_label(v) -> str:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return "-"
    if n < 25: return "낮음"
    if n < 50: return "보통"
    if n < 75: return "높음"
    return "매우높음"


# ────────────────────────────────────────────────────────────────────
# 대기정체지수 조회 — 농장 시군구 areaNo 의 시간대별 (h3~h78) 정체 강도.
# 반환: {'area_no', 'area_name', 'base_time', 'slots': [(label, value), ...]}
# ────────────────────────────────────────────────────────────────────
def get_atm_stagnation(farm_id) -> Dict[str, Any]:
    cache_key = int(farm_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info(f"[AI대기정체] 캐시 hit farm={farm_id}")
        return cached

    api_key = os.getenv("ATM_STG_API_KEY") or os.getenv("KMA_API_KEY")
    # 지역정보는 농장 속성 — farm_m_info(kma_area_no) 실시간 read.
    # env(ATM_STG_AREA_NO/NAME)는 DB 미설정 농장의 폴백으로만 사용.
    area_no, area_name = None, ""
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        import agri_ai_core.src.postgresql.queries as dbQry
        with db_session() as d:
            row = d.fetch_one(dbQry.GET_FARM_GEO, (int(farm_id),))
        if row and row.get("kma_area_no"):
            area_no = str(row["kma_area_no"])
            area_name = str(row.get("farm_name") or "")
    except Exception as e:
        logger.warning(f"[AI대기정체] 농장 지역정보 조회 실패 farm={farm_id}: {e}")
    if not area_no:
        area_no = os.getenv("ATM_STG_AREA_NO")
        area_name = os.getenv("ATM_STG_AREA_NAME", "")
    if not api_key or not area_no:
        logger.info(
            f"[AI대기정체] 비활성 — farm_m_info.kma_area_no/ATM_STG_API_KEY 미설정 "
            f"farm={farm_id}"
        )
        return {}

    url = os.getenv("ATM_STG_URL", _DEFAULT_URL)
    base_time = _nearest_base_time()
    params_url = (
        f"{url}?serviceKey={api_key}&areaNo={area_no}&time={base_time}"
        f"&dataType=JSON&numOfRows=1&pageNo=1"
    )
    logger.info(
        f"[AI대기정체] API 호출 farm={farm_id} areaNo={area_no}({area_name}) "
        f"base={base_time}"
    )
    try:
        status, data, err = http_json_request("GET", params_url, json_body=None, timeout=8)
    except Exception as e:
        logger.warning(f"[AI대기정체] API 예외 farm={farm_id}: {e}")
        return {}

    if status != 200 or not data:
        logger.warning(f"[AI대기정체] API 실패 status={status} err={err}")
        return {}

    header = (data.get("response", {}) or {}).get("header", {}) if isinstance(data, dict) else {}
    if header.get("resultCode") not in ("00", "0"):
        logger.warning(
            f"[AI대기정체] 응답 비정상 resultCode={header.get('resultCode')} msg={header.get('resultMsg')}"
        )
        return {}

    items = (
        data.get("response", {})
            .get("body", {})
            .get("items", [])
    )
    if isinstance(items, dict):
        items = items.get("item") or []
    items = items or []
    if not items:
        logger.info(f"[AI대기정체] 응답 항목 없음 farm={farm_id}")
        return {}

    it = items[0] if isinstance(items, list) else items
    # h3, h6, h9, ..., h78 (3시간 간격) 추출 — 처음 8개(=24h) 만 사용
    slots: List[Tuple[str, Any]] = []
    for h in range(3, 25, 3):
        key = f"h{h}"
        v = it.get(key)
        if v is not None:
            slots.append((f"+{h}h", v))

    payload = {
        'area_no': area_no,
        'area_name': area_name,
        'base_time': base_time,
        'slots': slots,
    }
    _cache_put(cache_key, payload)
    if slots:
        logger.info(
            f"[AI대기정체] 완료 farm={farm_id} areaNo={area_no} → "
            f"slots={len(slots)} 첫값={slots[0][1]}({_stg_label(slots[0][1])})"
        )
    return payload


# ────────────────────────────────────────────────────────────────────
# 대기정체 payload → user_prompt 한 블록. 비어있으면 빈 문자열.
# ────────────────────────────────────────────────────────────────────
def format_atm_stagnation_block(payload: Dict[str, Any]) -> str:
    if not payload:
        return ""
    slots = payload.get('slots') or []
    if not slots:
        return ""
    area = payload.get('area_name') or f"areaNo={payload.get('area_no')}"
    base = payload.get('base_time', '')
    base_disp = f"{base[:8]} {base[8:10]}시" if len(str(base)) >= 10 else base
    lines = [f"[대기정체지수 — {area} (발표 {base_disp})]"]
    parts = []
    for label, v in slots[:8]:
        parts.append(f"{label} {v}({_stg_label(v)})")
    lines.append("  " + " · ".join(parts))
    lines.append(
        "  → '높음/매우높음' 시각대는 환풍기 효율 저하 — CO2 임계 근접 시 가동시간 가중 (1.5x), "
        "외부순환 보다 흡입/배기 순환 우선."
    )
    return "\n".join(lines)
