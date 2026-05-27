# ══════════════════════════════════════════════════════════════════════════════
# 서버 리소스 조회 도구 (읽기 전용)
#
# 배경(2026-07-17): 농장주가 "서버 리소스 상태 분석해줘" 라고 묻자 LLM 이
#   search_web 으로 리눅스 모니터링 일반론 기사를 233초 걸려 가져왔다.
#   원인은 LLM 이 아니라 **도구 부재** — CPU/메모리/디스크/GPU 를 물어볼 곳이
#   시스템에 없었다. get_system_status 는 농장 정보만 준다.
#   ⛔ 절대 룰 "시스템 내부 질문에 search_web 금지" 를 지키려면 물어볼 도구가 있어야 한다.
#
# 파일 시작 함수 목록:
#   _cpu       : CPU 코어/사용률/부하평균
#   _memory    : RAM/스왑 사용량
#   _disk      : 주요 마운트 사용량
#   _gpu       : nvidia-smi 기반 GPU 별 메모리/사용률/온도
#   _services  : agri_ai_core 서비스 가동 상태 (tools_service 화이트리스트 재사용)
#   get_server_resources : 위 전부를 한 번에 반환
# ══════════════════════════════════════════════════════════════════════════════
import subprocess
from typing import Any, Dict, List

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_DISK_PATHS = ("/workspace", "/", "/home")


# ────────────────────────────────────────────────────────────────────
# CPU — 논리코어/사용률/1·5·15분 부하평균.
# ────────────────────────────────────────────────────────────────────
def _cpu() -> Dict[str, Any]:
    try:
        import psutil, os
        cores = psutil.cpu_count(logical=True)
        pct = psutil.cpu_percent(interval=0.5)
        la1, la5, la15 = os.getloadavg()
        return {"cores": cores, "usage_pct": round(pct, 1),
                "load_avg": [round(la1, 2), round(la5, 2), round(la15, 2)],
                # 부하평균이 코어 수를 넘으면 대기가 생긴다 — 판단 근거로 함께 제공
                "load_per_core": round(la1 / cores, 2) if cores else None}
    except Exception as e:
        return {"error": str(e)}


# ────────────────────────────────────────────────────────────────────
# 메모리 — RAM/스왑 (GB).
# ────────────────────────────────────────────────────────────────────
def _memory() -> Dict[str, Any]:
    try:
        import psutil
        m, s = psutil.virtual_memory(), psutil.swap_memory()
        g = 1073741824
        return {"total_gb": round(m.total / g, 1), "used_gb": round(m.used / g, 1),
                "available_gb": round(m.available / g, 1), "usage_pct": m.percent,
                "swap_total_gb": round(s.total / g, 1),
                "swap_used_gb": round(s.used / g, 1)}
    except Exception as e:
        return {"error": str(e)}


# ────────────────────────────────────────────────────────────────────
# 디스크 — 주요 마운트만 (전 마운트는 노이즈).
# ────────────────────────────────────────────────────────────────────
def _disk() -> List[Dict[str, Any]]:
    out = []
    try:
        import psutil, os
        seen = set()
        for p in _DISK_PATHS:
            if not os.path.exists(p):
                continue
            u = psutil.disk_usage(p)
            key = (u.total, u.used)
            if key in seen:          # 같은 파티션 중복 제거
                continue
            seen.add(key)
            g = 1073741824
            out.append({"path": p, "total_gb": round(u.total / g, 1),
                        "used_gb": round(u.used / g, 1),
                        "free_gb": round(u.free / g, 1), "usage_pct": u.percent})
    except Exception as e:
        out.append({"error": str(e)})
    return out


# ────────────────────────────────────────────────────────────────────
# GPU — nvidia-smi. 없으면 빈 list (GPU 없는 환경 대응).
# ────────────────────────────────────────────────────────────────────
def _gpu() -> List[Dict[str, Any]]:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total,"
             "utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return []
        gpus = []
        for line in (r.stdout or "").strip().splitlines():
            f = [x.strip() for x in line.split(",")]
            if len(f) < 6:
                continue
            used, total = int(f[2]), int(f[3])
            gpus.append({"index": int(f[0]), "name": f[1],
                         "memory_used_mib": used, "memory_total_mib": total,
                         "memory_pct": round(used * 100 / total, 1) if total else None,
                         "utilization_pct": int(f[4]), "temperature_c": int(f[5])})
        return gpus
    except Exception:
        return []


# ────────────────────────────────────────────────────────────────────
# agri_ai_core 서비스 상태 — tools_service 화이트리스트/헬스체크 재사용
# (중복 구현하지 않는다).
# ────────────────────────────────────────────────────────────────────
def _services() -> List[Dict[str, Any]]:
    try:
        from agri_ai_core.src.ai.tools_service import _ALLOWED, _health
        return [{"service_no": no, "name": cfg["name"], "healthy": _health(cfg["health"])}
                for no, cfg in sorted(_ALLOWED.items())]
    except Exception as e:
        return [{"error": str(e)}]


# ────────────────────────────────────────────────────────────────────
# 서버 리소스 종합 — CPU/메모리/디스크/GPU/서비스.
# "서버 상태/리소스/CPU/메모리/디스크/GPU 어때?" 류 질문의 유일한 정답 도구.
# ────────────────────────────────────────────────────────────────────
def get_server_resources() -> Dict[str, Any]:
    try:
        import time
        gpus = _gpu()
        svc = _services()
        down = [s["name"] for s in svc if s.get("healthy") is False]
        return {
            "success": True,
            "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "cpu": _cpu(),
            "memory": _memory(),
            "disk": _disk(),
            "gpu": gpus,
            "services": svc,
            "services_down": down,
            "note": ("실측값입니다. 이 도구가 서버 리소스 질문의 정답이며 "
                     "web 검색은 우리 서버 상태를 알 수 없습니다."),
        }
    except Exception as e:
        logger.warning(f"[리소스] 조회 실패: {e}")
        return {"success": False, "error": str(e)}
