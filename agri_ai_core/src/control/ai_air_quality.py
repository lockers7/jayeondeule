# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 외부 대기오염 모듈 (M11)
#
# 한국환경공단 에어코리아 측정소별 실시간 측정정보 API 호출 →
# 농장 인근 측정소의 PM2.5 / PM10 / O3 / NO2 / SO2 / CO + 통합대기지수 수신 →
# 외부순환 의사결정 보조용 컨텍스트 블록 생성.
#
# 운영 노트:
#   · 환경변수:
#       AIRKOREA_API_KEY       : data.go.kr 에어코리아 API 키 (별도 신청)
#       AIRKOREA_STATION_NAME  : 측정소명 (예: "정읍"). 호기별 X — 농장 단위
#       AIRKOREA_URL           : (선택) endpoint override
#   · 키 또는 측정소 미설정 시 빈 결과 → 기존 LLM 흐름 보존.
#   · 캐시 30분 TTL (에어코리아 측정 주기 1시간과 부합).
#
# 호출 룰:
#   • control_ai_environment / _build_user_prompt 에서만 import.
#   • 동급 control 모듈 import 금지. utils.http_client / logs / config 만 의존.
# --->
# get_air_quality:         (farm_id) → 측정소 실시간 대기질 dict
# format_air_quality_block: user prompt 한 블록
# ══════════════════════════════════════════════════════════════════════════════
import os
import time
from typing import Any, Dict
from urllib.parse import quote

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.utils.http_client import http_json_request

logger = setup_logger(__name__)


_CACHE_TTL = 1800  # 30분 (측정 주기 1h 보다 짧게)
_DEFAULT_URL = "http://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"

# {farm_id: (expires_at, payload)}
_CACHE: Dict[int, tuple] = {}


# ────────────────────────────────────────────────────────────────────
# 캐시 조회 — TTL 만료 시 자동 제거.
# ────────────────────────────────────────────────────────────────────
def _cache_get(key):
    e = _CACHE.get(key)
    if not e:
        return None
    if time.time() >= e[0]:
        _CACHE.pop(key, None)
        return None
    return e[1]


# ────────────────────────────────────────────────────────────────────
# 캐시 저장.
# ────────────────────────────────────────────────────────────────────
def _cache_put(key, payload):
    _CACHE[key] = (time.time() + _CACHE_TTL, payload)


# ────────────────────────────────────────────────────────────────────
# 농장별 측정소명 환경변수 조회.
# ────────────────────────────────────────────────────────────────────
def _station_for(farm_id):
    return (
        os.getenv(f"AIRKOREA_STATION_{farm_id}")
        or os.getenv("AIRKOREA_STATION_NAME")
    )


# ────────────────────────────────────────────────────────────────────
# 에어코리아 API 호출 → 측정소 실시간 대기질 dict 반환. 캐시 30분.
# 키/측정소/네트워크 실패 시 {}.
# 반환 예: {'station': '정읍', 'pm10': '32', 'pm25': '15', 'o3': '0.035',
#          'no2': '0.012', 'so2': '0.003', 'co': '0.4', 'khai': '65',
#          'khai_label': '보통', 'dataTime': '2026-05-17 10:00'}
# ────────────────────────────────────────────────────────────────────
def get_air_quality(farm_id) -> Dict[str, Any]:
    cache_key = int(farm_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info(f"[AI대기질] 캐시 hit farm={farm_id}")
        return cached

    api_key = os.getenv("AIRKOREA_API_KEY")
    station = _station_for(farm_id)
    if not api_key or not station:
        logger.info(
            f"[AI대기질] 비활성 — AIRKOREA_API_KEY/AIRKOREA_STATION_NAME 환경변수 미설정 "
            f"farm={farm_id}"
        )
        return {}

    url = os.getenv("AIRKOREA_URL", _DEFAULT_URL)
    # 측정소별 실시간 — 1시간 단위 최신 1건만 사용.
    # 한글 측정소명 (예: '신태인') 은 반드시 URL-encode 해야 함 — http_client 가
    # ASCII 만 받기 때문에 인코딩 안 하면 'ascii' codec UnicodeEncodeError 발생.
    params_url = (
        f"{url}?serviceKey={api_key}"
        f"&returnType=json&numOfRows=1&pageNo=1&ver=1.3"
        f"&stationName={quote(station, safe='')}&dataTerm=DAILY"
    )
    logger.info(f"[AI대기질] API 호출 farm={farm_id} station={station}")

    try:
        status, data, err = http_json_request("GET", params_url, json_body=None, timeout=8)
    except Exception as e:
        logger.warning(f"[AI대기질] API 예외 farm={farm_id}: {e}")
        return {}

    if status != 200 or not data:
        logger.warning(f"[AI대기질] API 실패 status={status} err={err}")
        return {}

    items = (
        data.get("response", {})
            .get("body", {})
            .get("items", [])
        if isinstance(data, dict) else []
    )
    if not items:
        logger.info(f"[AI대기질] 응답 항목 없음 farm={farm_id}")
        return {}

    it = items[0]
    payload = {
        'station':    station,
        'dataTime':   it.get('dataTime'),
        'pm10':       it.get('pm10Value'),
        'pm25':       it.get('pm25Value'),
        'o3':         it.get('o3Value'),
        'no2':        it.get('no2Value'),
        'so2':        it.get('so2Value'),
        'co':         it.get('coValue'),
        'khai':       it.get('khaiValue'),
        'khai_label': _khai_label(it.get('khaiGrade')),
        'pm10_label': _pm_grade(it.get('pm10Grade'), kind='PM10'),
        'pm25_label': _pm_grade(it.get('pm25Grade'), kind='PM2.5'),
    }
    _cache_put(cache_key, payload)
    logger.info(
        f"[AI대기질] 완료 farm={farm_id} station={station} "
        f"PM2.5={payload['pm25']} PM10={payload['pm10']} 통합={payload['khai_label']}"
    )
    return payload


# ────────────────────────────────────────────────────────────────────
# 통합대기환경지수(KHAI) 등급 → 한글 라벨.
# ────────────────────────────────────────────────────────────────────
def _khai_label(grade) -> str:
    return {'1': '좋음', '2': '보통', '3': '나쁨', '4': '매우나쁨'}.get(
        str(grade), str(grade) if grade else '-'
    )


# ────────────────────────────────────────────────────────────────────
# PM10 / PM2.5 등급 → 한글 라벨.
# ────────────────────────────────────────────────────────────────────
def _pm_grade(grade, kind='PM10') -> str:
    return {'1': '좋음', '2': '보통', '3': '나쁨', '4': '매우나쁨'}.get(
        str(grade), '-' if not grade else str(grade)
    )


# ────────────────────────────────────────────────────────────────────
# 대기질 payload → user prompt 한 블록. 비어 있으면 빈 문자열.
# ────────────────────────────────────────────────────────────────────
def format_air_quality_block(payload: Dict[str, Any]) -> str:
    if not payload:
        return ""
    lines = [
        f"[외부 대기질 — 측정소 {payload.get('station')} ({payload.get('dataTime','-')})]",
        f"  · PM2.5 {payload.get('pm25','-')}㎍/㎥ ({payload.get('pm25_label','-')}) · "
        f"PM10 {payload.get('pm10','-')}㎍/㎥ ({payload.get('pm10_label','-')}) · "
        f"통합대기지수 {payload.get('khai','-')} ({payload.get('khai_label','-')})",
        f"  · O3 {payload.get('o3','-')}ppm · NO2 {payload.get('no2','-')}ppm · "
        f"SO2 {payload.get('so2','-')}ppm · CO {payload.get('co','-')}ppm",
        "  → PM 농도 '나쁨' 이상이면 외부순환 회피(분진 침착·자실체 품질 저하), "
        "'보통' 이하 시각대에 흡입 우선.",
    ]
    return "\n".join(lines)
