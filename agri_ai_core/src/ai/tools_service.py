# ══════════════════════════════════════════════════════════════════════════════
# 서비스 관리 도구 — 로컬 AI 가 스스로 서비스 상태를 보고 재기동한다.
#
# 설계(농장주 지시 2026-07-17, 3단계):
#   LLM 이 "스케줄러가 죽었네 → 재기동" 같은 운영 판단을 직접 수행하게 한다.
#
# 안전 경계 (⛔ 완화 금지):
#   · stop/disable 을 **구현하지 않는다** — LLM 이 농장을 무제어 상태로 만드는 것이
#     이 단계의 최대 위험이다. 코드에 없으면 호출 자체가 불가능하다.
#   · restart/status 만. 서비스 번호 화이트리스트(_ALLOWED) 밖은 거부.
#   · restart 후 헬스체크 → 실패 시 1회 자동 재시도, 그래도 실패면 사유 반환.
#   · 전건 감사기록 (llm_service_audit)
#
# sudo 불필요 (2026-07-17 농장주 지시로 비-root 전환):
#   agri_ai_core 서비스는 전부 1024 초과 포트(FastAPI 8002 등)라 root 가 필요 없다.
#   과거 root 였던 건 `sudo ./agriAiCore` 관행 탓이며, jayeondeule 로 띄우면
#   sudo 자체가 사라져 "LLM 이 root 암호를 자동 주입한다" 는 문제가 소멸한다.
#   ⛔ 다시 sudo 로 띄우지 말 것 — 그 순간 LLM 이 이 도구로 root 를 얻는다.
#
# 파일 시작 함수 목록:
#   _audit          : 감사기록
#   _health         : 서비스별 헬스체크 (포트/프로세스)
#   list_services   : agriAiCore 등록 서비스 전체 + 상태 (조회는 전체, 재기동은 _ALLOWED)
#   service_status  : 특정 서비스 상태
#   restart_service : 재기동 + 헬스체크 + 1회 자동 재시도
# ══════════════════════════════════════════════════════════════════════════════
import subprocess
import time
from typing import Any, Dict, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_ROOT = "/workspace/jayeondeule"
_CTL = f"{_ROOT}/agriAiCore"
_TIMEOUT = 180

# ⛔ 화이트리스트 — 여기 없는 번호는 거부. stop 은 애초에 구현하지 않는다.
#   2(PostgreSQL)·3(ChromaDB) 는 재기동 시 전 서비스가 연쇄 영향을 받으므로 제외.
# ⛔ 조회(_REGISTRY)와 재기동(_ALLOWED)은 목록이 다르다 — 의도된 분리다.
#   조회는 읽기라 무해하므로 agriAiCore 등록 서비스 전체를 보여준다.
#   재기동은 위험하므로 좁게 유지한다(PostgreSQL/Nginx 등은 연쇄영향).
#   2026-07-17: 처음엔 _ALLOWED 를 조회에도 재사용해 6개만 보였다 — 농장주가
#   "각 서비스란 llm·ollama·chromadb·schedule 등 등록된 전체"라고 지적해 분리.
#
# unit 이 있으면 `sudo -n systemctl restart <unit>` 로 직접 재기동한다.
#   agriAiCore 의 restart 는 내부적으로 `systemctl stop` 을 호출하는데, stop 을
#   sudoers 에 넣으면 LLM 이 서비스를 정지시킬 수 있어 3단계 방어가 무너진다.
#   그래서 restart 만 NOPASSWD 로 허용(/etc/sudoers.d/agri_llm)하고 stop 경로를 우회한다.
_ALLOWED: Dict[int, Dict[str, Any]] = {
    1:  {"name": "Ollama",        "health": ("http", "http://127.0.0.1:11434/api/tags")},
    4:  {"name": "Scheduler",     "health": ("proc", "agri_ai_core.scheduler")},
    5:  {"name": "FastAPI",       "health": ("http", "http://127.0.0.1:8002/docs")},
    16: {"name": "Agent Monitor", "unit": "agent_monitor",
         "health": ("proc", "agri_ai_core.src.control.agent_scheduler")},
    17: {"name": "Agent Worker",  "unit": "agent_pending_worker",
         "health": ("proc", "agri_ai_core.src.control.agent_pending_worker")},
    19: {"name": "Event Listener", "unit": "agent_event_listener",
         "health": ("proc", "agent_event_listener")},
}

# 조회 전용 — agriAiCore 등록 서비스 전체. 번호는 agriAiCore 메뉴와 일치.
#   health 판정: ("port", N) 리스닝 여부가 가장 확실하다(HTTP 404/403 도 가동 중).
#                ("proc", 패턴) 포트 없는 데몬. ("docker", 이름) 컨테이너.
#   category: 사용자(농장 운영) / 시스템(인프라) / 패키지(외부 SW)
_REGISTRY = [
    {"no": 1,  "name": "Ollama",           "category": "패키지", "desc": "LLM 서버",
     "health": ("port", 11434)},
    {"no": 2,  "name": "PostgreSQL",       "category": "패키지", "desc": "관계형 DB",
     "health": ("port", 5432)},
    {"no": 3,  "name": "ChromaDB",         "category": "패키지", "desc": "벡터 DB",
     "health": ("port", 8000)},
    {"no": 4,  "name": "Scheduler",        "category": "사용자", "desc": "스케줄·환경제어",
     "health": ("proc", "agri_ai_core.scheduler")},
    {"no": 5,  "name": "FastAPI",          "category": "사용자", "desc": "REST API",
     "health": ("port", 8002)},
    {"no": 6,  "name": "SearXNG",          "category": "패키지", "desc": "메타검색엔진",
     "health": ("port", 8888)},
    {"no": 7,  "name": "Web Backend",      "category": "사용자", "desc": "농장관리 백엔드",
     "health": ("port", 9090)},
    {"no": 8,  "name": "Shop Backend",     "category": "사용자", "desc": "쇼핑몰 백엔드",
     "health": ("port", 9091)},
    {"no": 9,  "name": "Nginx",            "category": "시스템", "desc": "웹서버",
     "health": ("port", 80)},
    # 5199 원격 RPi 보드의 SSH wrapper. 농장주가 보드를 교체하며 setup 검증 중이라
    # 미가동이 곧 장애는 아니다 → optional (down 집계 제외).
    {"no": 13, "name": "RPi Camera",       "category": "사용자",
     "desc": "5199 USB 카메라 (원격 보드 · 셋업 검증 중)",
     "health": ("port", 8095), "optional": True},
    # ⛔ Camera Archive 는 독립 프로세스가 아니라 Scheduler 안에서 도는 작업이다
    #   (2026-07-17 오판: ("proc","camera_archive") 로 찾아 "다운" 오보). 캡처 산출물이
    #   실제 증거 — 최근 2시간 내 이미지가 있으면 정상.
    {"no": 14, "name": "Camera Archive",   "category": "사용자",
     "desc": "시간별 캡처·보존 (Scheduler 내부 작업)",
     "health": ("recent_file", "upload/camera")},
    {"no": 15, "name": "ChromaFlow Studio", "category": "패키지", "desc": "ChromaDB GUI(Docker)",
     "health": ("port", 5000)},
    {"no": 16, "name": "Agent Monitor",    "category": "사용자", "desc": "ReAct 구독 데몬",
     "health": ("proc", "agri_ai_core.src.control.agent_scheduler")},
    {"no": 17, "name": "Agent Worker",     "category": "사용자", "desc": "30초 취소큐 실행",
     "health": ("proc", "agri_ai_core.src.control.agent_pending_worker")},
    {"no": 19, "name": "Event Listener",   "category": "사용자", "desc": "LISTEN/NOTIFY 즉시 agent",
     "health": ("proc", "agent_event_listener")},
]

_CREATE_AUDIT = """
CREATE TABLE IF NOT EXISTS llm_service_audit (
    id          BIGSERIAL PRIMARY KEY,
    executed_at TIMESTAMP NOT NULL DEFAULT now(),
    action      VARCHAR(16),
    service     VARCHAR(40),
    reason      TEXT,
    result      TEXT
)
"""


# ────────────────────────────────────────────────────────────────────
# 감사기록 — best-effort.
# ────────────────────────────────────────────────────────────────────
def _audit(action: str, service: str, reason: str, result: str) -> None:
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            d.execute_query(_CREATE_AUDIT, ())
            d.execute_query(
                "INSERT INTO llm_service_audit (action, service, reason, result) "
                "VALUES (%s, %s, %s, %s)",
                (action, service[:40], (reason or "")[:500], (result or "")[:2000]))
    except Exception as e:
        logger.debug(f"[서비스] 감사기록 실패(무시): {e}")


# ────────────────────────────────────────────────────────────────────
# 헬스체크 — http 는 응답코드, proc 는 프로세스 존재.
# ────────────────────────────────────────────────────────────────────
def _health(spec) -> bool:
    kind, target = spec
    try:
        if kind == "port":
            # 리스닝 여부가 가장 확실 — HTTP 404/403 도 서비스는 가동 중이다.
            r = subprocess.run(["ss", "-tln"], capture_output=True, text=True, timeout=10)
            return f":{target} " in (r.stdout or "")
        if kind == "recent_file":
            # 산출물 기반 판정 — Scheduler 내부 작업처럼 전용 프로세스가 없는 것.
            import os, time as _t
            base = os.path.join(_ROOT, target)
            newest = 0.0
            for root, _d, files in os.walk(base):
                for f in files:
                    try:
                        m = os.path.getmtime(os.path.join(root, f))
                        if m > newest:
                            newest = m
                    except OSError:
                        continue
            return bool(newest) and (_t.time() - newest) < 7200   # 2시간 내
        if kind == "docker":
            r = subprocess.run(["docker", "ps", "--filter", f"name={target}",
                                "--format", "{{.Names}}"],
                               capture_output=True, text=True, timeout=10)
            return bool((r.stdout or "").strip())
        if kind == "http":
            r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", target],
                               capture_output=True, text=True, timeout=15)
            return r.stdout.strip().startswith("2")
        r = subprocess.run(["pgrep", "-f", target], capture_output=True, text=True, timeout=15)
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


# ────────────────────────────────────────────────────────────────────
# 관리 가능한 서비스 목록 + 현재 헬스.
# ────────────────────────────────────────────────────────────────────
def list_services() -> Dict[str, Any]:
    rows = []
    for c in _REGISTRY:
        ok = _health(c["health"])
        rows.append({"service_no": c["no"], "name": c["name"],
                     "category": c["category"], "desc": c["desc"],
                     "healthy": ok,
                     "restartable": c["no"] in _ALLOWED,
                     "optional": bool(c.get("optional"))})
    down = [r["name"] for r in rows if not r["healthy"] and not r["optional"]]
    return {"success": True, "count": len(rows), "services": rows,
            "running": sum(1 for r in rows if r["healthy"]),
            "down": down,
            "note": ("agriAiCore 등록 서비스 전체(사용자/시스템/패키지). "
                     "restartable=true 인 것만 restart_service 가능하며 "
                     "정지(stop)는 제공하지 않습니다 — 농장 무제어 방지. "
                     "optional=true 서비스는 미가동이 정상입니다.")}


# ────────────────────────────────────────────────────────────────────
# 특정 서비스 상태.
# ────────────────────────────────────────────────────────────────────
def service_status(service_no: int) -> Dict[str, Any]:
    try:
        no = int(service_no)
    except (TypeError, ValueError):
        return {"success": False, "error": "service_no 는 정수여야 합니다."}
    cfg = _ALLOWED.get(no)
    if not cfg:
        return {"success": False,
                "error": f"관리 대상이 아닙니다: {no}. list_services 로 확인하세요."}
    ok = _health(cfg["health"])
    return {"success": True, "service_no": no, "name": cfg["name"],
            "healthy": ok, "message": f"{cfg['name']}: {'정상' if ok else '응답 없음'}"}


# ────────────────────────────────────────────────────────────────────
# 재기동 + 헬스체크. 실패 시 1회 자동 재시도 후 사유 반환.
# ────────────────────────────────────────────────────────────────────
def restart_service(service_no: int, reason: str = "") -> Dict[str, Any]:
    try:
        no = int(service_no)
    except (TypeError, ValueError):
        return {"success": False, "error": "service_no 는 정수여야 합니다."}
    cfg = _ALLOWED.get(no)
    if not cfg:
        return {"success": False,
                "error": f"재기동 대상이 아닙니다: {no}. list_services 로 확인하세요. "
                         f"(PostgreSQL/ChromaDB 는 연쇄 영향으로 제외)"}

    name = cfg["name"]
    for attempt in (1, 2):
        try:
            # systemd 유닛은 systemctl restart 직접(sudoers NOPASSWD 화이트리스트).
            # 그 외는 agriAiCore — 서비스가 jayeondeule 로 도므로 sudo 불필요.
            unit = cfg.get("unit")
            cmd = (["sudo", "-n", "systemctl", "restart", unit] if unit
                   else [_CTL, "restart", str(no)])
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=_TIMEOUT, cwd=_ROOT)
            out = ((r.stdout or "") + (r.stderr or ""))[-1500:]
        except subprocess.TimeoutExpired:
            out = f"{_TIMEOUT}초 초과"
        except Exception as e:
            out = str(e)

        time.sleep(6)
        if _health(cfg["health"]):
            _audit("restart", name, reason, f"attempt={attempt} healthy")
            logger.info(f"[서비스] {name} 재기동 성공 (시도 {attempt}) 사유={reason[:60]!r}")
            return {"success": True, "service_no": no, "name": name,
                    "attempts": attempt,
                    "message": f"{name} 재기동 완료 — 헬스체크 정상."}
        logger.warning(f"[서비스] {name} 재기동 후 헬스체크 실패 (시도 {attempt})")

    _audit("restart", name, reason, "헬스체크 실패 (2회)")
    return {"success": False, "service_no": no, "name": name,
            "error": f"{name} 재기동했으나 헬스체크가 2회 실패했습니다. "
                     f"search_logs(level='ERROR') 로 원인을 확인하세요."}
