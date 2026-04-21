# ════════════════════════════════════════════════════════════════════
# 라즈베리파이 관리 API — SSH 재시작·센서 상태·인터록·릴레이 쓰기.
# --->
# get_server_time       : GET  /api/v1/rpi/server-time          — 서버 현재 시각
# restart_rpi           : POST /api/v1/rpi/restart              — RPi 서비스 재시작 (SSH)
# get_all_sensor_status : GET  /api/v1/rpi/sensor-status        — 전체 농장/재배사 최신 센서 기록 시각
# get_interlock_state   : GET  /api/v1/rpi/interlock/{f}/{h}    — 흡입팬/배출팬 ON 가능 잔여시간
# write_relay           : POST /api/v1/rpi/relay/{f}/{h}        — 수동제어 릴레이 쓰기 (인터록 적용)
# ════════════════════════════════════════════════════════════════════
import subprocess
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.postgresql.reader import read_latest_relay_info
from agri_ai_core.src.control.interlock import (
    get_interlock_status, bootstrap_valve_state, get_valve_dwell_sec,
    VALVE_FAN_INTERLOCK_SEC,
)
from agri_ai_core.src.control.control_common import SEMANTIC_LABELS

logger = setup_logger(__name__)

rpi_router = APIRouter(prefix="/api/v1/rpi", tags=["rpi"])

# 재배사 ID → SSH 포트 매핑
_RPI_SSH_HOST = "jayeondeule.iptime.org"
_RPI_SSH_USER = "jayeondeule"
_RPI_SSH_PASS = "Wkdusemfdp1@"
_RPI_PORT_MAP = {
    1: 5101,
    2: 5102,
    3: 5103,
    99: 5199,
}
_RPI_SERVICE_NAME = "jayeondeule_ctrl"


class RpiActionRequest(BaseModel):
    farm_id: int
    house_id: int


# ────────────────────────────────────────────────────────────────────
# 서버 현재 시각 반환 — RPi 와 시각 동기화 확인용 단순 핑.
# ────────────────────────────────────────────────────────────────────
@rpi_router.get("/server-time")
async def get_server_time():
    from datetime import datetime
    return {"time": datetime.now().isoformat()}


# ────────────────────────────────────────────────────────────────────
# 재배사 RPi 서비스 재시작 — sshpass + SSH 로 jayeondeule_ctrl 재시작.
# house_id → _RPI_PORT_MAP 으로 포트 결정. 미등록 시 400, 타임아웃 504.
# ────────────────────────────────────────────────────────────────────
@rpi_router.post("/restart")
async def restart_rpi(request: RpiActionRequest):
    port = _RPI_PORT_MAP.get(request.house_id)
    if not port:
        raise HTTPException(400, f"등록되지 않은 재배사입니다: house_id={request.house_id}")

    logger.info(f"[RPi관리] 재시작 요청: farm_id={request.farm_id} house_id={request.house_id} port={port}")

    try:
        result = subprocess.run(
            [
                "sshpass", "-p", _RPI_SSH_PASS,
                "ssh", "-p", str(port),
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
                f"{_RPI_SSH_USER}@{_RPI_SSH_HOST}",
                f"sudo systemctl restart {_RPI_SERVICE_NAME}",
            ],
            capture_output=True, text=True, timeout=20,
        )

        if result.returncode == 0:
            logger.info(f"[RPi관리] 재시작 성공: house_id={request.house_id}")
            return {"success": True, "message": f"{request.house_id}호 재배사 RPi 재시작 완료"}
        else:
            error_msg = result.stderr.strip() or "알 수 없는 오류"
            logger.error(f"[RPi관리] 재시작 실패: house_id={request.house_id} error={error_msg}")
            raise HTTPException(500, f"재시작 실패: {error_msg}")

    except subprocess.TimeoutExpired:
        logger.error(f"[RPi관리] 재시작 타임아웃: house_id={request.house_id}")
        raise HTTPException(504, "RPi 연결 시간 초과")
    except FileNotFoundError:
        logger.error("[RPi관리] sshpass 미설치")
        raise HTTPException(500, "서버에 sshpass가 설치되지 않았습니다")
    except Exception as e:
        logger.error(f"[RPi관리] 재시작 오류: {e}")
        raise HTTPException(500, f"오류: {str(e)}")


# ────────────────────────────────────────────────────────────────────
# 전체 농장/재배사의 최신 센서 기록 시각을 한 번에 조회.
# 농장 관리 페이지에서 RPi 에러 여부(센서 stall) 판단에 사용.
# 응답: [{farm_id, hous_id, hous_name, last_recd_dttm}, ...]
# ────────────────────────────────────────────────────────────────────
@rpi_router.get("/sensor-status")
async def get_all_sensor_status():
    try:
        QUERY = """
            SELECT f.farm_id, f.hous_id, f.hous_name,
                   (SELECT MAX(s.recd_dttm)
                    FROM sensor_l_recording s
                    WHERE s.farm_id = f.farm_id AND s.hous_id = f.hous_id
                   ) AS last_recd_dttm
            FROM farmhouse_m_info f
            WHERE f.dlte_yn = 'N' AND f.hous_id != 0
            ORDER BY f.farm_id, f.hous_id
        """
        with db_session() as database:
            rows = database.fetch_all(QUERY, as_dict=True)

        result = []
        for row in (rows or []):
            last_dt = row.get("last_recd_dttm")
            result.append({
                "farm_id": row.get("farm_id"),
                "hous_id": row.get("hous_id"),
                "hous_name": row.get("hous_name", ""),
                "last_recd_dttm": last_dt.isoformat() if last_dt else None,
            })

        return {"success": True, "data": result}

    except Exception as e:
        logger.error(f"[RPi관리] 센서 상태 조회 오류: {e}")
        raise HTTPException(500, f"센서 상태 조회 오류: {str(e)}")


# ────────────────────────────────────────────────────────────────────
# 흡입팬/배출팬 ON 가능 잔여시간 (밸브-팬 인터록 UI 표시용).
# 프론트엔드 RelayDashboard 가 폴링하여 버튼 라벨에 (잔여 N초) 빨간색 표시.
# latch 가 비어 있고 밸브가 현재 ON 이면 DB 의 최신 RELAY_L_RECORDING 으로
# 1회 bootstrap 한 후 응답 (서비스 재시작 직후 누적 ON 인 밸브 누락 방지).
# ────────────────────────────────────────────────────────────────────
@rpi_router.get("/interlock/{farm_id}/{house_id}")
async def get_interlock_state(farm_id: int, house_id: int):
    try:
        latest = read_latest_relay_info(farm_id, house_id) or {}

        # latch 미초기화 + 밸브 ON 인 케이스에 한해 bootstrap 1회
        from agri_ai_core.src.control.interlock import VALVE_DEPENDENT_FANS
        from agri_ai_core.src.control.control_common import get_pin_map
        pin_map = get_pin_map(house_id)
        need_bootstrap = False
        for valve_flag in VALVE_DEPENDENT_FANS.keys():
            pin = pin_map.get(valve_flag)
            if pin and bool(latest.get(pin, False)):
                if get_valve_dwell_sec(farm_id, house_id, valve_flag) is None:
                    need_bootstrap = True
                    break
        if need_bootstrap:
            bootstrap_valve_state(farm_id, house_id, latest_relay=latest)

        st = get_interlock_status(farm_id, house_id, current=latest)
        # 시멘틱 → UI 라벨 추가
        out = {}
        for fan_flag, info in st.items():
            out[fan_flag] = {
                **info,
                "label": SEMANTIC_LABELS.get(fan_flag, fan_flag),
                "gate_via_label": SEMANTIC_LABELS.get(info.get("gate_via"), None) if info.get("gate_via") else None,
            }
        return {
            "success": True,
            "farm_id": farm_id,
            "house_id": house_id,
            "threshold_sec": VALVE_FAN_INTERLOCK_SEC,
            "fans": out,
        }
    except Exception as e:
        logger.error(f"[인터록상태] 조회 오류 farm={farm_id} house={house_id}: {e}")
        raise HTTPException(500, f"인터록 상태 조회 오류: {str(e)}")


# ════════════════════════════════════════════════════════════════════
# 수동제어 릴레이 쓰기 — Spring Boot 가 위임 호출하는 단일 진입점.
# 본 엔드포인트를 통과해야 인터록 게이트(밸브-팬 보호)가 적용된 후 DB 에 기록.
# 입력: { "relays": {"relay_1st_flag": bool, ..., "relay_16st_flag": bool} } (16 flag)
# 응답: { success, settings, interlock_violations: [...] }
# ════════════════════════════════════════════════════════════════════
class RelayWriteRequest(BaseModel):
    relays: dict   # {relay_*st_flag: bool} 16개


# ────────────────────────────────────────────────────────────────────
# 릴레이 쓰기 — relay_manager.set_relay_value(raw_mode=True) 위임.
# 인터록 위반 항목은 응답 interlock_violations 에 누적 반환.
# ────────────────────────────────────────────────────────────────────
@rpi_router.post("/relay/{farm_id}/{house_id}")
async def write_relay(farm_id: int, house_id: int, request: RelayWriteRequest):
    try:
        from agri_ai_core.src.control.relay_manager import set_relay_value
        result = set_relay_value(farm_id, house_id, request.relays, raw_mode=True)
        return result
    except Exception as e:
        logger.error(f"[릴레이쓰기] 오류 farm={farm_id} house={house_id}: {e}")
        raise HTTPException(500, f"릴레이 쓰기 오류: {str(e)}")
