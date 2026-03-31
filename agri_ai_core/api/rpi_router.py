# ------------------------------------------------------------------------------------------------------------
# 라즈베리파이 관리 API
# SSH를 통해 재배사별 라즈베리파이 서비스를 재시작
# ------------------------------------------------------------------------------------------------------------
import subprocess
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agri_ai_core.logs import setup_logger

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
