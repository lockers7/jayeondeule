# ════════════════════════════════════════════════════════
# 라즈베리파이 관리 API: SSH 재시작 및 센서 상태 모니터링.
# ════════════════════════════════════════════════════════
import subprocess
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session

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


@rpi_router.get("/server-time")
async def get_server_time():
    """서버 현재 시각 반환"""
    from datetime import datetime
    return {"time": datetime.now().isoformat()}


@rpi_router.post("/restart")
async def restart_rpi(request: RpiActionRequest):
    """재배사 라즈베리파이 서비스 재시작"""
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


@rpi_router.get("/sensor-status")
async def get_all_sensor_status():
    """
    전체 농장/재배사의 최신 센서 기록 시각을 한 번에 조회.
    농장 관리 페이지에서 RPi 에러 여부를 판단하는 데 사용.

    Returns:
        [{"farm_id": 1, "hous_id": 1, "hous_name": "...", "last_recd_dttm": "..."}, ...]
    """
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
