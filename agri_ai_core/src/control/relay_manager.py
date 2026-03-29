# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이 제어 관리자 모듈
# 릴레이 설정값 변경, 상태 모니터링, 제어 이력 관리 등
# 릴레이 제어의 상위 레벨 관리 기능을 제공합니다.
# --->
# _relay_detail_parts: 릴레이 전체 상태를 상세 문자열 리스트로 생성
# log_relay_detail: 릴레이 상세 상태 로그 출력
# _persist_relay_values: LLM/일괄 제어 시 DB에 반복 쓰기하여 IoT 폴링 주기를 생존 (백그라운드 스레드)
# set_relay_value: 릴레이 값 설정 (마이크로초 타임스탬프 + IoT 폴링 생존용 반복 쓰기)
# get_relay_status: 릴레이 상태 조회
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import traceback
import threading

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import get_relay_mapping
from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.postgresql import queries as dbQry
from agri_ai_core.src.postgresql.reader import read_latest_relay_info
from agri_ai_core.src.control.control_common import (
    RELAY_COUNT, get_pin_map, reverse_pin_map, SEMANTIC_LABELS,
)

logger = setup_logger(__name__)


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


def log_relay_detail(farm_id, house_id):
    current = read_latest_relay_info(farm_id, house_id)
    if not current:
        return
    for part in _relay_detail_parts(house_id, current):
        logger.info(part)


# IoT 폴링 생존용 반복 쓰기 설정 (초)
_PERSIST_INTERVAL = 2          # 반복 쓰기 간격 (초)
_PERSIST_COUNT = 7             # 반복 쓰기 횟수 (2초 × 7회 = 14초간 유지)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM/일괄 제어 시 DB에 반복 쓰기하여 IoT 폴링 주기를 생존하는 백그라운드 스레드
# IoT 하드웨어가 4초마다 물리적 릴레이 상태를 DB에 기록하므로,
# LLM이 설정한 값이 IoT 기록에 의해 즉시 덮어써지는 문제를 방지합니다.
# 일정 시간 동안 동일한 값을 반복 쓰기하여, IoT가 LLM의 값을 읽고 물리적 릴레이를 변경할 수 있도록 합니다.
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _persist_relay_values(farm_id, house_id, relay_values, count=_PERSIST_COUNT, interval=_PERSIST_INTERVAL):
    import time
    from datetime import datetime
    for i in range(count):
        time.sleep(interval)
        try:
            recd_dttm = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            params = (farm_id, int(house_id), recd_dttm) + tuple(relay_values.values())
            with db_session() as database:
                database.execute_query(dbQry.SET_RELAY_VALUE, params)
            logger.info(f"[릴레이유지] 반복쓰기 {i + 1}/{count} farm_id={farm_id} house_id={house_id}")
        except Exception as e:
            logger.warning(f"[릴레이유지] 반복쓰기 실패 {i + 1}/{count}: {e}")


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이 값 설정
# IoT 하드웨어가 4초마다 물리적 릴레이 상태를 DB에 기록(RELAY_L_RECORDING)하므로,
# LLM이 DB에 쓴 원하는 릴레이 상태가 IoT 기록에 의해 즉시 덮어써지는 문제를 방지하기 위해:
# 1) 마이크로초 포함 타임스탬프로 같은 초 내에서 IoT 기록보다 항상 "최신"이 되도록 함
# 2) raw_mode=False (LLM/일괄 제어) 시 백그라운드 스레드로 15초간 반복 쓰기하여
#    IoT가 LLM의 값을 읽고 물리적 릴레이를 변경할 수 있도록 함
#
# Args:
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#     relay_settings: 릴레이 설정 딕셔너리
#     raw_mode: True이면 수동환경제어 (16개 relay_*st_flag 직접 전달, 반복쓰기 없음)
#
# Returns:
#     dict: 실행 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def set_relay_value(farm_id, house_id, relay_settings, raw_mode=False):
    try:
        # raw_mode: 수동환경제어에서 16개 relay_*st_flag를 직접 전달할 때 사용
        # raw_mode=True이면 기본값 초기화/별칭 변환/강제 ON 없이 그대로 사용
        if raw_mode:
            relay_values = dict(relay_settings)
        else:
            # 현재 릴레이 상태를 읽어 기존 상태 보존 (부분 갱신)
            current = read_latest_relay_info(farm_id, house_id)

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

        # SQL 파라미터 준비 (farm_id, hous_id, recd_dttm, relay flags...)
        # 마이크로초 포함 타임스탬프: IoT 4초 폴링 기록보다 항상 "최신"이 되도록 함
        from datetime import datetime
        recd_dttm = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        params = (farm_id, int(house_id), recd_dttm) + tuple(relay_values.values())

        # 모든 재배사에 대해 동일한 쿼리 사용
        query = dbQry.SET_RELAY_VALUE

        logger.info(f"[릴레이설정] DB쓰기 farm_id={farm_id} house_id={house_id} params_count={len(params)} recd_dttm={recd_dttm}")
        with db_session() as database:
            result = database.execute_query(query, params)

            if result:
                logger.info(f"[릴레이설정] DB쓰기 성공: farm_id={farm_id}, house_id={house_id}")

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
                    "settings": relay_values
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이 상태 조회
# 릴레이 상태 조회
#
# Args:
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#
# Returns:
#     dict: 릴레이 상태 또는 None
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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
            relay_mapping = get_relay_mapping(house_id)

            relay_status = {}
            for relay_key, relay_info in relay_mapping.items():
                # relay_info는 [UI 표시 이름, 간단한 설명, 상세 기능 설명] 형식
                db_key = relay_key.replace("_flag", "")
                value = result.get(db_key, False)

                # relay_info가 리스트/튜플이면 적절히 추출
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
                    "status": "작동중" if value else "미작동"
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

