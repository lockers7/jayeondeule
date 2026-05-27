# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 기상특보 모듈 (M12)
#
# 기상청 기상특보 조회서비스(getWthrWrnList) 호출 → 농장 광역 특보구역의
# 최근 발효 특보(호우/강풍/폭염/한파/대설/건조 등) 를 user_prompt 컨텍스트로
# 주입. 비상 안전 대응이 아닌 *선제 대응 가이드* 용도 (비상가드 skip 정책 유지).
#
# 운영 노트:
#   · 환경변수:
#       WTHR_WRN_API_KEY    : data.go.kr 키 (미설정 시 KMA_API_KEY 폴백)
#       WTHR_WRN_STN_ID     : 특보구역 stnId (정읍 = 146 전북)
#       WTHR_WRN_AREA_NAME  : (선택) 로그용 라벨 (예: '전북')
#       WTHR_WRN_URL        : (선택) endpoint override
#   · 키/구역 미설정 또는 NO_DATA(특보 없음) 시 빈 결과 → 기존 LLM 흐름 보존.
#   · 캐시 30분 TTL — 발효/해제는 시각 단위 변화이므로 충분.
#
# 호출 룰:
#   • control/ai_control 에서만 import. 동급 control 모듈 import 금지.
# --->
# get_weather_alerts:           (farm_id) → 최근 발효 특보 list
# format_weather_alert_block:   user prompt 한 블록
# ══════════════════════════════════════════════════════════════════════════════
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.utils.http_client import http_json_request

logger = setup_logger(__name__)


_CACHE_TTL = 1800  # 30분
_DEFAULT_URL = "http://apis.data.go.kr/1360000/WthrWrnInfoService/getWthrWrnList"
_LOOKBACK_DAYS = 2  # 최근 2일 발효된 특보까지 조회 (max 6일 정책 안)

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
# 최근 발효 특보 조회 — 농장 광역구역 stnId 기준 최근 _LOOKBACK_DAYS 일.
# 반환: {'stn_id', 'area_name', 'alerts': [{title, tmFc, ...}, ...]}
# ────────────────────────────────────────────────────────────────────
def get_weather_alerts(farm_id) -> Dict[str, Any]:
    cache_key = int(farm_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info(f"[AI기상특보] 캐시 hit farm={farm_id}")
        return cached

    api_key = os.getenv("WTHR_WRN_API_KEY") or os.getenv("KMA_API_KEY")
    stn_id = os.getenv("WTHR_WRN_STN_ID")
    area_name = os.getenv("WTHR_WRN_AREA_NAME", "")
    if not api_key or not stn_id:
        logger.info(
            f"[AI기상특보] 비활성 — WTHR_WRN_API_KEY/WTHR_WRN_STN_ID 환경변수 미설정 "
            f"farm={farm_id}"
        )
        return {}

    url = os.getenv("WTHR_WRN_URL", _DEFAULT_URL)
    today = datetime.now()
    from_d = (today - timedelta(days=_LOOKBACK_DAYS)).strftime("%Y%m%d")
    to_d = today.strftime("%Y%m%d")

    params_url = (
        f"{url}?serviceKey={api_key}&pageNo=1&numOfRows=20&dataType=JSON"
        f"&stnId={stn_id}&fromTmFc={from_d}&toTmFc={to_d}"
    )
    logger.info(
        f"[AI기상특보] API 호출 farm={farm_id} stnId={stn_id}({area_name}) "
        f"range={from_d}~{to_d}"
    )
    try:
        status, data, err = http_json_request("GET", params_url, json_body=None, timeout=8)
    except Exception as e:
        logger.warning(f"[AI기상특보] API 예외 farm={farm_id}: {e}")
        return {}

    if status != 200 or not data:
        logger.warning(f"[AI기상특보] API 실패 status={status} err={err}")
        return {}

    header = (data.get("response", {}) or {}).get("header", {}) if isinstance(data, dict) else {}
    result_code = header.get("resultCode")
    if result_code == "03":   # NO_DATA — 특보 없음 (정상)
        logger.info(f"[AI기상특보] 발효 특보 없음 farm={farm_id} stnId={stn_id}")
        empty = {'stn_id': stn_id, 'area_name': area_name, 'alerts': []}
        _cache_put(cache_key, empty)
        return empty
    if result_code != "00":
        logger.warning(
            f"[AI기상특보] 응답 비정상 resultCode={result_code} msg={header.get('resultMsg')}"
        )
        return {}

    items = (
        data.get("response", {})
            .get("body", {})
            .get("items", {})
    )
    items = items.get("item") if isinstance(items, dict) else items
    items = items or []
    if isinstance(items, dict):
        items = [items]

    alerts: List[Dict[str, Any]] = []
    for it in items[:20]:
        alerts.append({
            'title':  it.get('title'),
            'tmFc':   it.get('tmFc'),
            'tmSeq':  it.get('tmSeq'),
        })

    payload = {'stn_id': stn_id, 'area_name': area_name, 'alerts': alerts}
    _cache_put(cache_key, payload)
    logger.info(
        f"[AI기상특보] 완료 farm={farm_id} stnId={stn_id} → 특보 {len(alerts)}건"
    )
    return payload


# ────────────────────────────────────────────────────────────────────
# 특보 payload → user_prompt 한 블록. 비어있거나 발효 없으면 빈 문자열.
# ────────────────────────────────────────────────────────────────────
def format_weather_alert_block(payload: Dict[str, Any]) -> str:
    if not payload:
        return ""
    alerts = payload.get('alerts') or []
    if not alerts:
        return ""   # 발효 특보 없을 때 LLM 컨텍스트 부담 회피
    area = payload.get('area_name') or f"stnId={payload.get('stn_id')}"
    lines = [f"[기상특보 — {area} (최근 {_LOOKBACK_DAYS}일 발효)]"]
    for a in alerts[:6]:
        title = (a.get('title') or "").strip()
        tmfc = a.get('tmFc')
        # tmFc: 202605181500 → '05/18 15:00'
        when = ""
        try:
            s = str(tmfc)
            when = f"{s[4:6]}/{s[6:8]} {s[8:10]}:{s[10:12]}"
        except Exception:
            when = str(tmfc)
        lines.append(f"  · {when} {title}")
    lines.append("  → 호우/강풍/한파/폭염 특보 발효 시 외부순환·배수·수온히터 선제 대응 검토.")
    return "\n".join(lines)
