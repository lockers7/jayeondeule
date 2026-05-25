# ═══════════════════════════════════════════════════════════
# 릴레이 제어 관리자 모듈.
# 릴레이 설정값 변경, 상태 조회, IoT 폴링 생존용 반복 쓰기 등
# 릴레이 제어의 상위 레벨 관리 기능을 제공한다.
# --->
# _relay_detail_parts: relay detail parts
# log_relay_detail: log relay detail
# _persist_relay_values: persist relay values
# set_relay_value: set relay value
# get_relay_status: get relay status
# ═══════════════════════════════════════════════════════════
import traceback
import threading

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import get_relay_mapping
from agri_ai_core.config.mappers import RelayDef
from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.postgresql import queries as dbQry
from agri_ai_core.src.postgresql.reader import read_latest_relay_info
from agri_ai_core.src.control.control_common import (
    RELAY_COUNT, get_pin_map, reverse_pin_map, SEMANTIC_LABELS,
    force_off_unmapped_relays,
)
from agri_ai_core.src.control.interlock import (
    evaluate_interlock, record_valve_transitions,
)

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# 16개 릴레이 상태를 "relay_Nst_flag(eng-한글): ON/OFF" 문자열 리스트로.
# ────────────────────────────────────────────────────────────────────
def _relay_detail_parts(house_id, relay_values):
    reverse = reverse_pin_map(house_id)
    parts = []
    for i in range(1, RELAY_COUNT + 1):
        key = f"relay_{i}st_flag"
        value = relay_values.get(key, False)
        semantic = reverse.get(key)
        eng = semantic or 'unused'
        kor = SEMANTIC_LABELS.get(semantic, '미사용') if semantic else '미사용'
        status = "ON" if value else "OFF"
        parts.append(f"{key}({eng}-{kor}): {status}")
    return parts


# ────────────────────────────────────────────────────────────────────
# 현재 릴레이 상태를 INFO 라인으로 로깅 (16개 줄 출력).
# ────────────────────────────────────────────────────────────────────
def log_relay_detail(farm_id, house_id):
    current = read_latest_relay_info(farm_id, house_id)
    if not current:
        return
    for part in _relay_detail_parts(house_id, current):
        logger.info(part)


# IoT 폴링 생존용 반복 쓰기 설정 (초)
_PERSIST_INTERVAL = 2          # 반복 쓰기 간격 (초)
_PERSIST_COUNT = 7             # 반복 쓰기 횟수 (2초 × 7회 = 14초간 유지)


# ══════════════════════════════════════════════════════════════════════════════
# LLM/일괄 제어 시 DB에 반복 쓰기하여 IoT 폴링 주기를 생존하는 백그라운드 스레드
# IoT 하드웨어가 4초마다 물리적 릴레이 상태를 DB에 기록하므로,
# LLM이 설정한 값이 IoT 기록에 의해 즉시 덮어써지는 문제를 방지합니다.
# ══════════════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# IoT 폴링(4초) 생존용 백그라운드 반복 쓰기 — 2초 간격 7회.
# LLM 설정값이 IoT 기록에 의해 즉시 덮어써지는 문제 방지.
# ────────────────────────────────────────────────────────────────────
def _persist_relay_values(farm_id, house_id, relay_values, count=_PERSIST_COUNT, interval=_PERSIST_INTERVAL):
    import time
    from datetime import datetime
    # [2026-04-27] SET_RELAY_VALUE SQL 컬럼 순서(relay_1..relay_16)에 맞춰 항상 정렬된
    # tuple 을 생성 — dict 입력 순서 의존성 제거(Java HashMap→JSON 직렬화 등).
    ordered = tuple(bool(relay_values.get(f"relay_{i}st_flag", False))
                    for i in range(1, RELAY_COUNT + 1))
    for i in range(count):
        time.sleep(interval)
        try:
            recd_dttm = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            params = (farm_id, int(house_id), recd_dttm) + ordered
            with db_session() as database:
                database.execute_query(dbQry.SET_RELAY_VALUE, params)
            logger.info(f"[릴레이유지] 반복쓰기 {i + 1}/{count} farm_id={farm_id} house_id={house_id}")
            logger.debug(f"[릴레이유지] 반복쓰기 성공 {i + 1}/{count}")
        except Exception as e:
            logger.error(f"[릴레이유지] 반복쓰기 실패 {i + 1}/{count}: {e}")


# ═════════════════════════════════════════════════
# 릴레이 값 설정
# 마이크로초 타임스탬프 + IoT 폴링 생존용 반복 쓰기
# ═════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 릴레이 값 설정 메인 함수 — 인터록 게이트 통과 후 DB 쓰기.
# raw_mode=True: 16개 핀 직접 전달 (수동환경제어). False: 시멘틱 부분갱신.
# skip_emergency_guard=True: 수동 UI 사용자 명령 — 비상 오버라이드 미적용
#   (사용자 정책 2026-05-17). 스케줄·RPI 자동 호출은 False 유지로 기존 비상가드 작동.
# 마이크로초 타임스탬프 + IoT 폴링 생존용 백그라운드 반복 쓰기 자동 트리거.
# ────────────────────────────────────────────────────────────────────
def set_relay_value(farm_id, house_id, relay_settings, raw_mode=False,
                    skip_emergency_guard=True):
    # [2026-05-17] skip_emergency_guard default 를 True 로 변경 — 운용모드 무관
    # 모든 비상제어 skip (사용자 정책). 호출자에서 명시적 False 전달 시만 적용.
    try:
        # 인터록 게이트는 raw_mode 와 무관하게 항상 통과 — 게이트는 현재 DB 상태 대비
        # target 의 OFF→ON 전이만 검사하므로 이미 ON 인 팬은 영향 없음. raw_mode 의
        # "수동환경제어 16개 직접 전달" 시멘틱은 그대로 보존된다.
        current_for_gate = read_latest_relay_info(farm_id, house_id) or {}

        # raw_mode: 수동환경제어에서 16개 relay_*st_flag를 직접 전달할 때 사용
        # raw_mode=True이면 기본값 초기화/별칭 변환/강제 ON 없이 그대로 사용
        # [2026-04-27] dict 입력 순서가 SQL 컬럼 순서와 다른 경우(특히 Java HashMap →
        # JSON 직렬화) 값이 잘못된 컬럼에 들어가던 버그 방지 — 항상 1..16 순서로 재구성.
        if raw_mode:
            relay_values = {
                f"relay_{i}st_flag": bool(relay_settings.get(f"relay_{i}st_flag", False))
                for i in range(1, RELAY_COUNT + 1)
            }
            # ────────────────────────────────────────────────────────────
            # [2026-05-17] 사용자 정책 — 운용모드 무관 모든 비상제어 skip.
            #   skip_emergency_guard default=True 로 모든 호출자에서 자동 건너뜀.
            #   비상가드 복귀 시: default=False 변경 + 본 분기 안 로그 재추가.
            # ────────────────────────────────────────────────────────────
            if not skip_emergency_guard:
                try:
                    from agri_ai_core.src.postgresql.reader import read_current_sensor_info
                    from agri_ai_core.src.control.environment_logic import _emergency_override
                    from agri_ai_core.src.control.ai_thresholds import get_thresholds
                    _sensor = read_current_sensor_info(farm_id, house_id) or {}
                    _ts = get_thresholds(farm_id, house_id)
                    _is_e, _dev_override, _circ_override, _wto = _emergency_override(_sensor, _ts)
                    if _is_e and _dev_override:
                        _pin_map = get_pin_map(house_id)
                        for _sem, _val in _dev_override.items():
                            if _val is None:
                                continue
                            _pin = _pin_map.get(_sem)
                            if _pin and _pin in relay_values:
                                _prev = relay_values[_pin]
                                relay_values[_pin] = bool(_val)
                                logger.warning(
                                    f"[비상가드] 자동 호출 {_sem}({_pin}) {_prev} → {_val} "
                                    f"(스케줄/RPI 경로 — 사용자 원칙: 운용모드 결정 후 비상 오버라이드)"
                                )
                except Exception as _e:
                    logger.error(f"[비상가드] 자동 호출 비상 오버라이드 실패: {_e}")
        else:
            # 현재 릴레이 상태를 읽어 기존 상태 보존 (부분 갱신)
            current = current_for_gate

            if current:
                relay_values = {
                    f"relay_{i}st_flag": bool(current.get(f"relay_{i}st_flag", False))
                    for i in range(1, RELAY_COUNT + 1)
                }
            else:
                # DB에 상태가 없으면 기본값 사용
                relay_values = {f"relay_{i}st_flag": False for i in range(1, RELAY_COUNT + 1)}

            # house_id별 시멘틱→릴레이 핀 매핑 적용
            alias_mapping = get_pin_map(house_id)

            for key, value in relay_settings.items():
                # 별칭을 실제 relay flag로 변환
                actual_key = alias_mapping.get(key, key)
                if actual_key in relay_values:
                    prev = relay_values[actual_key]
                    relay_values[actual_key] = value
                    label = SEMANTIC_LABELS.get(key, key)
                    logger.info(f"[릴레이설정] {label}({key}) → {actual_key}: {prev} → {value}")
                else:
                    logger.warning(f"[릴레이설정] 매핑 실패: {key} → {actual_key} (relay_values에 없음)")

        # ─── 미매핑 릴레이 강제 OFF (모든 모드 공통) ───
        # 핀맵에 등록되지 않은 relay_*st_flag (현재 9, 15 — 다른 용도 예정)는
        # raw_mode 로 들어와도 False 로 강제. 핀맵 자체에서 매핑이 빠진 시멘틱
        # (예: 실내히터·히터밸브) 도 시멘틱 변환 단계에서 자동 제외되므로 이중 차단.
        forced_unmapped = force_off_unmapped_relays(house_id, relay_values)
        for pin in forced_unmapped:
            logger.info(f"[미매핑릴레이] {pin} 강제 OFF — 핀맵 미등록")

        # ─── 밸브-팬 인터록 게이트 (모든 모드 공통) ───
        # 흡입팬/배출팬 OFF→ON 전이 시 선행 밸브 dwell 검증, 위반 시 차단.
        # 밸브 ON→OFF 전이 시 의존 팬 자동 OFF 보정. 위반 사유는 응답에 포함.
        relay_values, interlock_violations = evaluate_interlock(
            farm_id, house_id, current_for_gate, relay_values,
        )
        if interlock_violations:
            for v in interlock_violations:
                logger.warning(f"[인터록] {v.get('reason', v)}")

        # SQL 파라미터 준비 (farm_id, hous_id, recd_dttm, relay flags...)
        # 마이크로초 포함 타임스탬프: IoT 4초 폴링 기록보다 항상 "최신"이 되도록 함
        # [2026-04-27] dict 순서 무관 — 항상 relay_1..16 순서로 정렬된 tuple 생성.
        from datetime import datetime
        recd_dttm = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        ordered_values = tuple(bool(relay_values.get(f"relay_{i}st_flag", False))
                               for i in range(1, RELAY_COUNT + 1))
        params = (farm_id, int(house_id), recd_dttm) + ordered_values

        # 모든 재배사에 대해 동일한 쿼리 사용
        query = dbQry.SET_RELAY_VALUE

        logger.info(f"[릴레이설정] DB쓰기 farm_id={farm_id} house_id={house_id} params_count={len(params)} recd_dttm={recd_dttm}")
        with db_session() as database:
            result = database.execute_query(query, params)

            if result:
                logger.info(f"[릴레이설정] DB쓰기 성공: farm_id={farm_id}, house_id={house_id}")

                # 밸브 OFF→ON 전이 시각 latch 갱신 (DB 쓰기 성공 후)
                record_valve_transitions(farm_id, house_id, current_for_gate, relay_values)

                # LLM/일괄 제어 시 IoT 폴링 주기 생존을 위한 백그라운드 반복 쓰기
                # raw_mode(수동환경제어 10초 주기)는 자체적으로 반복되므로 불필요
                if not raw_mode:
                    t = threading.Thread(
                        target=_persist_relay_values,
                        args=(farm_id, house_id, relay_values),
                        daemon=True,
                    )
                    t.start()
                    logger.info(f"[릴레이설정] IoT 폴링 생존용 반복쓰기 시작 ({_PERSIST_COUNT}회, {_PERSIST_INTERVAL}초 간격)")

                return {
                    "success": True,
                    "message": "릴레이 값이 성공적으로 설정되었습니다.",
                    "farm_id": farm_id,
                    "house_id": house_id,
                    "settings": relay_values,
                    "interlock_violations": interlock_violations,
                }
            else:
                logger.warning(f"릴레이 값 설정 실패: farm_id={farm_id}, house_id={house_id}")
                return {
                    "success": False,
                    "message": "릴레이 값 설정에 실패했습니다."
                }

    except Exception as e:
        logger.error(f"릴레이 값 설정 중 오류: {e}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"오류 발생: {str(e)}"
        }


# ══════════════════
# 릴레이 상태 조회
# ══════════════════
# ────────────────────────────────────────────────────────────────────
# 현재 릴레이 상태 조회 — house_id 별 RELAY_FIELD_MAPPING 으로 응답 구성.
# STANDARD: 컬럼명·시멘틱 양쪽 키 포함. E타입: 매핑 키 그대로.
# ────────────────────────────────────────────────────────────────────
def get_relay_status(farm_id, house_id):
    try:
        with db_session() as database:
            result = database.fetch_one(
                query=dbQry.GET_LATEST_RELAY_INFO,
                vals=(farm_id, house_id)
            )

            if not result:
                logger.warning(f"릴레이 상태 조회 실패: farm_id={farm_id}, house_id={house_id}")
                return None

            # house_id에 따라 적절한 릴레이 매핑 선택
            #   STANDARD (1·3호): RelayDef 5-tuple — sem/col 양쪽 키로 응답 포함
            #   E타입 (2호):       3-tuple — 매핑 키 그대로 응답 포함
            relay_mapping = get_relay_mapping(house_id)

            relay_status = {}
            for relay_key, relay_info in relay_mapping.items():
                if isinstance(relay_info, RelayDef):
                    # STANDARD: 컬럼명·시멘틱 양쪽 키 모두 응답에 포함 (외부 호환)
                    db_key = relay_info.col.replace("_flag", "")
                    value = result.get(db_key, False)
                    payload = {
                        "name": relay_info.kor_func,
                        "description": relay_info.desc,
                        "value": value,
                        "status": "작동중" if value else "미작동",
                    }
                    relay_status[relay_info.col] = payload
                    relay_status[relay_info.sem] = payload
                else:
                    # E (기존 3-tuple): 매핑 키 그대로 응답
                    db_key = relay_key.replace("_flag", "")
                    value = result.get(db_key, False)
                    if isinstance(relay_info, (list, tuple)):
                        relay_name = relay_info[1] if len(relay_info) > 1 else relay_key
                        relay_desc = relay_info[2] if len(relay_info) > 2 else ""
                    else:
                        relay_name = relay_key
                        relay_desc = ""
                    relay_status[relay_key] = {
                        "name": relay_name,
                        "description": relay_desc,
                        "value": value,
                        "status": "작동중" if value else "미작동",
                    }

            return {
                "farm_id": farm_id,
                "house_id": house_id,
                "record_datetime": result.get("기록일시"),
                "relays": relay_status
            }

    except Exception as e:
        logger.error(f"릴레이 상태 조회 중 오류: {e}")
        logger.error(traceback.format_exc())
        return None

