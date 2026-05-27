# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 외부 기상예보 모듈 (M10)
# 한국기상청 단기예보 API(혹은 호환 소스) 결과를 1~3시간 후
# 외부 온도/습도 예측으로 변환해 LLM 에 제공.
#
# 운영 노트:
#   · 환경변수로 재배사별 GPS 또는 nx/ny 격자 좌표 주입.
#       KMA_API_KEY        : 기상청 API 키
#       KMA_FORECAST_URL   : (선택) 기상청 endpoint override
#       FARM_NX_<farm>_<house>, FARM_NY_<farm>_<house> : 격자 좌표
#   · API 키 또는 좌표 미설정 시 빈 결과 → 기존 LLM 흐름 보존.
#   · 캐시 30분 TTL — 동일 호출 반복 회피.
#
# 호출 룰:
#   • control_ai_environment 에서만 import.
#   • 동급 control 모듈 import 금지.
#   • utils.http_client / logs / config 만 의존.
# --->
# get_forecast:         (farm_id, house_id) → 1~3시간 후 예측 dict
# format_forecast_block: user prompt 한 줄
# ══════════════════════════════════════════════════════════════════════════════
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.utils.http_client import http_json_request

logger = setup_logger(__name__)


_CACHE_TTL = 1800  # 30분
_DEFAULT_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"

# {(farm, house): (expires_at, payload)}
_CACHE: Dict[tuple, tuple] = {}


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
# 캐시 저장 — TTL 만료 시각과 함께 페이로드 보관.
# ────────────────────────────────────────────────────────────────────
def _cache_put(key, payload):
    _CACHE[key] = (time.time() + _CACHE_TTL, payload)


# ────────────────────────────────────────────────────────────────────
# 재배사별 KMA 격자 좌표(nx, ny) 조회.
# 지역정보는 농장 속성 — farm_m_info(kma_nx/ny) 실시간 read 우선
# (농장 추가 시 코드 변경 없이 등록 데이터만으로 확장). env 는 재배사별 특수
# 오버라이드(FARM_NX_{farm}_{house}) 및 DB 미설정 농장 폴백(DEFAULT)으로 유지.
# ────────────────────────────────────────────────────────────────────
def _grid_for(farm_id, house_id):
    nx = os.getenv(f"FARM_NX_{farm_id}_{house_id}")
    ny = os.getenv(f"FARM_NY_{farm_id}_{house_id}")
    if nx and ny:
        return nx, ny
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        import agri_ai_core.src.postgresql.queries as dbQry
        with db_session() as d:
            row = d.fetch_one(dbQry.GET_FARM_GEO, (int(farm_id),))
        if row and row.get("kma_nx") and row.get("kma_ny"):
            return str(row["kma_nx"]), str(row["kma_ny"])
    except Exception as e:
        logger.warning(f"[AI기상예보] 농장 지역정보 조회 실패 farm={farm_id}: {e}")
    return os.getenv("FARM_NX_DEFAULT"), os.getenv("FARM_NY_DEFAULT")


# ────────────────────────────────────────────────────────────────────
# KMA API 호출 → 1~3시간 후 외부 기상예보 dict 반환. 캐시 30분.
# 키/좌표/네트워크 실패 시 {}.
# ────────────────────────────────────────────────────────────────────
def get_forecast(farm_id, house_id) -> Dict[str, Any]:
    cache_key = (int(farm_id), int(house_id))
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info(f"[AI기상예보] 캐시 hit farm={farm_id} house={house_id}")
        return cached

    api_key = os.getenv("KMA_API_KEY")
    nx, ny = _grid_for(farm_id, house_id)
    if not api_key or not nx or not ny:
        logger.info(
            f"[AI기상예보] 비활성 — KMA_API_KEY/FARM_NX_FARM_NY 환경변수 미설정 "
            f"farm={farm_id} house={house_id}"
        )
        return {}

    url = os.getenv("KMA_FORECAST_URL", _DEFAULT_URL)
    # KMA 단기예보 base_time 은 02·05·08·11·14·17·20·23 시(3h 간격)만 유효.
    # 발표 +10분 안전 마진 후, 가장 가까운 과거 발표 시각으로 스냅.
    _BASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)
    ref = datetime.now() - timedelta(minutes=10)
    _valid = [h for h in _BASE_HOURS if h <= ref.hour]
    if _valid:
        base_dt = ref.replace(hour=_valid[-1], minute=0, second=0, microsecond=0)
    else:
        base_dt = (ref - timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)
    base_date = base_dt.strftime("%Y%m%d")
    base_time = base_dt.strftime("%H00")

    params_url = (
        f"{url}?serviceKey={api_key}&pageNo=1&numOfRows=300&dataType=JSON"
        f"&base_date={base_date}&base_time={base_time}&nx={nx}&ny={ny}"
    )
    logger.info(
        f"[AI기상예보] API 호출 farm={farm_id} house={house_id} "
        f"base={base_date} {base_time} nx={nx} ny={ny}"
    )
    try:
        status, data, err = http_json_request("GET", params_url, json_body=None, timeout=8)
    except Exception as e:
        logger.warning(f"[AI기상예보] API 예외 farm={farm_id} house={house_id}: {e}")
        return {}

    if status != 200 or not data:
        logger.warning(f"[AI기상예보] API 실패 status={status} err={err}")
        return {}

    items = (
        data.get("response", {})
            .get("body", {})
            .get("items", {})
            .get("item", [])
        if isinstance(data, dict) else []
    )
    if not items:
        logger.info(f"[AI기상예보] 응답 항목 없음 farm={farm_id} house={house_id}")
        return {}

    # category: TMP=온도, REH=습도, POP=강수확률, PTY=강수형태, WSD=풍속, SKY=하늘
    next_3h = []
    target_categories = {'TMP', 'REH', 'POP', 'PTY', 'WSD', 'SKY'}
    grouped: Dict[str, Dict[str, Any]] = {}
    for it in items[:300]:
        cat = it.get('category')
        if cat not in target_categories:
            continue
        ts = f"{it.get('fcstDate')} {it.get('fcstTime')}"
        slot = grouped.setdefault(ts, {})
        slot[cat] = it.get('fcstValue')

    sorted_slots = sorted(grouped.items())[:3]
    for ts, vals in sorted_slots:
        next_3h.append({'time': ts, **vals})

    payload = {'forecast': next_3h}
    _cache_put(cache_key, payload)
    logger.info(
        f"[AI기상예보] 완료 farm={farm_id} house={house_id} → 향후 {len(next_3h)} 슬롯"
    )
    return payload


# ────────────────────────────────────────────────────────────────────
# KMA PTY(강수형태) 코드 → 한글 라벨.
# ────────────────────────────────────────────────────────────────────
def _pty_label(code) -> str:
    return {'0': '없음', '1': '비', '2': '비/눈', '3': '눈',
            '4': '소나기', '5': '빗방울', '6': '빗방울/눈날림',
            '7': '눈날림'}.get(str(code), str(code))


# ────────────────────────────────────────────────────────────────────
# KMA SKY(하늘) 코드 → 한글 라벨.
# ────────────────────────────────────────────────────────────────────
def _sky_label(code) -> str:
    return {'1': '맑음', '3': '구름많음', '4': '흐림'}.get(str(code), str(code))


# ────────────────────────────────────────────────────────────────────
# 기상예보 payload → user prompt 한 블록 텍스트.
# ────────────────────────────────────────────────────────────────────
def format_forecast_block(payload: Dict[str, Any]) -> str:
    forecast = (payload or {}).get('forecast') or []
    if not forecast:
        return ""
    lines = [f"[외부 기상 단기예보 — 향후 {len(forecast)}시간]"]
    for f in forecast:
        time_s = f.get('time', '')[-4:]  # HHMM
        lines.append(
            f"  · {time_s[:2]}:{time_s[2:]} 온도 {f.get('TMP','-')}℃ · "
            f"습도 {f.get('REH','-')}% · 강수확률 {f.get('POP','-')}% · "
            f"강수형태 {_pty_label(f.get('PTY'))} · 풍속 {f.get('WSD','-')}m/s · "
            f"하늘 {_sky_label(f.get('SKY'))}"
        )
    lines.append("  → 강수확률·강수형태가 높으면 외부순환 회피 / 외부온습도 미리 가늠.")
    return "\n".join(lines)
