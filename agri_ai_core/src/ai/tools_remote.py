# ══════════════════════════════════════════════════════════════════════════════
# 원격 서버 조사 도구 — SSH(키 인증)로 다른 서버의 상태를 로컬처럼 파악
#
# 농장주 지시(2026-07-24): "로컬 LLM이 SSH 접속정보만 알면 원격 서버 접속해서 로컬
#   서버 Status 와 동일한 정보를 파악 가능해야 한다." → 원격 상태조회(read-only)는 자유,
#   변경성 명령은 관리자 승인 후 실행.
#
# 인증: SSH 키만(BatchMode=yes 로 비밀번호 프롬프트 차단 = 키 인증 강제). 기본 키 또는
#   등록 호스트별 identity. 접속정보는 manage_remote_host 로 이름 등록(권장) 또는
#   'user@host:port' 직접 지정.
#
# 안전:
#   · remote_status: 사전 정의된 read-only 명령 배터리만 → 원격 변경 불가.
#   · remote_run: 첫 토큰이 read-only allowlist + 위험패턴 없음 → 즉시 실행. 그 외
#     (변경성/미지)은 실행 보류 + 카카오 승인요청(remote_command_m pending). 승인은
#     approve_remote_command(관리자 전용)로만 집행.
#
# 파일 시작 함수 목록:
#   ensure_tables / _resolve_host / _ssh_exec / _classify_command
#   manage_remote_host   : 원격 호스트 등록/조회
#   remote_status        : 원격 서버 종합 상태(리소스·서비스·로그) read-only
#   remote_run           : 원격 명령 실행(조회 즉시/변경성 승인)
#   approve_remote_command : 보류된 변경성 명령 승인·집행(관리자)
#   TOOL_REGISTRY / TOOL_SPECS / tool_specs_text
# ══════════════════════════════════════════════════════════════════════════════
import os
import re
import subprocess
import time
from typing import Any, Dict, Optional, Tuple

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_DEFAULT_TIMEOUT = 20
_MAX_OUT = 8000

# read-only 명령 첫 토큰 allowlist — 이 목록의 명령만 승인 없이 원격 실행.
_READONLY_VERBS = {
    "cat", "ls", "ll", "df", "du", "free", "uptime", "uname", "hostname", "whoami",
    "id", "ps", "top", "systemctl", "journalctl", "dmesg", "grep", "egrep", "zgrep",
    "tail", "head", "wc", "sort", "uniq", "awk", "cut", "tr", "find", "stat", "file",
    "netstat", "ss", "ip", "ifconfig", "ping", "nslookup", "dig", "env", "printenv",
    "date", "cal", "lsblk", "lscpu", "lsusb", "lspci", "nvidia-smi", "vmstat", "iostat",
    "mpstat", "sar", "pwd", "echo", "which", "type", "readlink", "realpath", "basename",
    "dirname", "getent", "nproc", "uptime", "lsof", "who", "w", "last", "history",
}
# 위험(변경성) 패턴 — 하나라도 매칭되면 승인 필요.
_DANGER_RE = re.compile(
    r"\b(rm|rmdir|mv|dd|mkfs|reboot|shutdown|halt|poweroff|kill|pkill|killall|chmod|"
    r"chown|chgrp|passwd|useradd|userdel|usermod|apt|apt-get|yum|dnf|pip|pip3|npm|"
    r"truncate|shred|tee|crontab|iptables|ufw|mount|umount|insmod|rmmod|modprobe|"
    r"nohup|setsid)\b"
    r"|\bsudo\b|\bsu\b"
    r"|\bsystemctl\s+(start|stop|restart|enable|disable|mask|kill)\b"
    r"|\bservice\s+\S+\s+(start|stop|restart)\b"
    r"|\bgit\s+(push|reset|clean|checkout)\b"
    r"|>\s*\S|>>\s*\S|\|\s*(sh|bash|zsh)\b|`|\$\(",
    re.IGNORECASE)

_CREATE_HOST = """
CREATE TABLE IF NOT EXISTS remote_host_m (
    name          VARCHAR(60) PRIMARY KEY,
    host_spec     VARCHAR(200) NOT NULL,
    identity_path VARCHAR(300),
    description   TEXT,
    created_by    VARCHAR(40) DEFAULT 'admin',
    updt_dttm     TIMESTAMP NOT NULL DEFAULT now()
)
"""
_CREATE_CMD = """
CREATE TABLE IF NOT EXISTS remote_command_m (
    id         SERIAL PRIMARY KEY,
    host_spec  VARCHAR(200) NOT NULL,
    command    TEXT NOT NULL,
    status     VARCHAR(20) NOT NULL DEFAULT 'pending',
    result     TEXT,
    rgst_dttm  TIMESTAMP NOT NULL DEFAULT now(),
    updt_dttm  TIMESTAMP NOT NULL DEFAULT now()
)
"""
_ensured = False


def ensure_tables():
    global _ensured
    if _ensured:
        return
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        d.execute_query(_CREATE_HOST, ())
        d.execute_query(_CREATE_CMD, ())
    _ensured = True


def _resolve_host(host: str) -> Tuple[Optional[str], str, Optional[int], Optional[str]]:
    """등록 이름이면 registry 조회, 아니면 'user@host:port' 파싱. → (user, host, port, identity)."""
    identity = os.getenv("SSH_REMOTE_IDENTITY", "").strip() or None
    spec = (host or "").strip()
    # 등록 호스트 이름 조회
    if re.match(r"^[a-zA-Z0-9_][a-zA-Z0-9_-]{1,59}$", spec) and "@" not in spec and ":" not in spec:
        try:
            ensure_tables()
            from agri_ai_core.src.postgresql.connection import db_session
            with db_session() as d:
                r = d.fetch_one("SELECT host_spec, identity_path FROM remote_host_m WHERE name=%s", (spec,))
            if r:
                r = dict(r)
                spec = r["host_spec"]
                identity = r.get("identity_path") or identity
        except Exception:
            pass
    user = None
    if "@" in spec:
        user, spec = spec.split("@", 1)
    port = None
    if ":" in spec:
        spec, p = spec.rsplit(":", 1)
        try:
            port = int(p)
        except ValueError:
            port = None
    return user, spec, port, identity


_SSH_CM_DIR = "/tmp/agri_ssh_cm"   # ControlMaster 소켓 디렉토리
_SSH_TRANSIENT = ("Connection refused", "Connection timed out", "Connection reset",
                  "Connection closed", "kex_exchange", "banner exchange", "Broken pipe",
                  "No route to host", "timed out", "port 22")


def _ssh_exec(host: str, command: str, timeout: int = _DEFAULT_TIMEOUT) -> Dict[str, Any]:
    try:
        user, hostname, port, identity = _resolve_host(host)
        if not hostname:
            return {"success": False, "connected": False, "error": "호스트를 확인할 수 없습니다."}
        # 방어적: command 가 list/tuple 이면 합치고 그 외는 str 강제 ('list' object strip 버그 방지)
        if isinstance(command, (list, tuple)):
            command = " ".join(str(x) for x in command)
        else:
            command = str(command or "")
        to = max(5, min(int(timeout or _DEFAULT_TIMEOUT), 60))
        try:
            os.makedirs(_SSH_CM_DIR, exist_ok=True)
        except Exception:
            pass
        opts = ["-o", "BatchMode=yes",                    # 키 인증 강제(비번 프롬프트 차단)
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", f"ConnectTimeout={min(to, 15)}",
                "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3"]
                # ⛔ ControlMaster(연결 다중화)는 이 환경이 unix 도메인 소켓 bind 를 차단해 사용 불가.
                #    대신 아래 재시도-백오프로 일시 접속실패를 자가복구한다.
        if identity:
            opts += ["-i", identity]
        if port:
            opts += ["-p", str(port)]
        target = f"{user}@{hostname}" if user else hostname
        cmd = ["ssh"] + opts + [target, command]
        last_err = ""
        for attempt in range(3):   # 일시 접속오류(거부/타임아웃/reset) 시 백오프 재시도 = 자가복구
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=to)
            except subprocess.TimeoutExpired:
                last_err = f"{to}초 내 응답 없음(원격 접속 지연/차단)"
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1)); continue
                return {"success": False, "connected": False, "transient": True, "error": last_err}
            out = (r.stdout or "")[:_MAX_OUT]
            err = (r.stderr or "")[:2000]
            if r.returncode == 0:
                return {"success": True, "connected": True, "exit_code": 0, "stdout": out, "stderr": err}
            conn_fail = any(k in err for k in _SSH_TRANSIENT)
            if conn_fail and attempt < 2:
                last_err = err
                time.sleep(1.2 * (attempt + 1)); continue     # 접속 자체 실패 → 재시도
            # 접속은 됐으나 명령만 실패(예: find 경로없음)면 connected=True 로 구분 → LLM 오보 방지
            return {"success": False, "connected": (not conn_fail),
                    "exit_code": r.returncode, "stdout": out, "stderr": err,
                    "error": (f"원격 접속 실패(재시도 후에도): {err[:200]}" if conn_fail else None)}
        return {"success": False, "connected": False, "transient": True,
                "error": f"재시도 소진 — 원격 접속 실패: {last_err[:200]}"}
    except Exception as e:
        logger.warning(f"[원격] ssh 실패: {e}")
        return {"success": False, "connected": False, "error": f"SSH 실행 실패: {e}"}


def _classify_command(command: str) -> str:
    """'readonly' | 'mutating'. 안전 리다이렉트(/dev/null·fd복제)는 제외하고, 위험패턴이
    없으며 모든 파이프·체인 세그먼트의 첫 토큰이 read-only allowlist 여야 readonly."""
    c = (command or "").strip()
    if not c:
        return "mutating"
    # ⛔ 2>/dev/null·>/dev/null·2>&1 등 무해한 리다이렉트는 제거 후 판정(오탐 방지)
    c_chk = re.sub(r"\d?>>?\s*/dev/null|\d?>&\d|&>\s*/dev/null", " ", c)
    if _DANGER_RE.search(c_chk):          # 파일 쓰기 리다이렉트·위험 명령은 여기서 차단
        return "mutating"
    # 문장 구분자(;·&&·||·개행)로만 분리 — 파이프(|)는 grep '패턴|패턴' 처럼 따옴표 안에도
    # 흔해 분리 대상 아님(위험 명령은 _DANGER_RE 가 위치 무관 차단). 각 문장 첫 토큰 검사.
    for seg in re.split(r";|&&|\|\||\n", c_chk):
        seg = seg.strip()
        if not seg:
            continue
        v = re.split(r"\s+", seg, 1)[0].split("/")[-1]
        if v not in _READONLY_VERBS:
            return "mutating"
    return "readonly"


def manage_remote_host(action: str, name: str = None, host_spec: str = None,
                       identity_path: str = None, description: str = None,
                       auth_farm_id: str = None) -> Dict[str, Any]:
    """원격 호스트 등록부. list/get 은 누구나, register/remove 는 관리자."""
    try:
        ensure_tables()
        from agri_ai_core.src.postgresql.connection import db_session
        action = (action or "").strip().lower()
        if action == "list":
            with db_session() as d:
                rows = d.fetch_all("SELECT name, host_spec, description FROM remote_host_m ORDER BY name", (), as_dict=True) or []
            return {"success": True, "count": len(rows), "hosts": [dict(r) for r in rows]}
        if not name or not re.match(r"^[a-zA-Z0-9_][a-zA-Z0-9_-]{1,59}$", name):
            return {"success": False, "error": "name 은 영문/숫자로 시작하는 2~60자."}
        if action == "get":
            with db_session() as d:
                r = d.fetch_one("SELECT name, host_spec, description FROM remote_host_m WHERE name=%s", (name,))
            return {"success": bool(r), "host": dict(r) if r else None}
        if auth_farm_id is not None:
            return {"success": False, "error": "원격 호스트 등록/삭제는 시스템관리자 전용입니다."}
        if action in ("register", "add", "update"):
            if not host_spec:
                return {"success": False, "error": "host_spec('user@host:port')이 필요합니다."}
            with db_session() as d:
                d.execute_query(
                    "INSERT INTO remote_host_m (name, host_spec, identity_path, description, updt_dttm) "
                    "VALUES (%s,%s,%s,%s,now()) ON CONFLICT (name) DO UPDATE SET host_spec=EXCLUDED.host_spec, "
                    "identity_path=EXCLUDED.identity_path, description=EXCLUDED.description, updt_dttm=now()",
                    (name, host_spec, identity_path, description))
            return {"success": True, "message": f"원격 호스트 '{name}' 등록. remote_status(host='{name}')로 조회."}
        if action == "remove":
            with db_session() as d:
                d.execute_query("DELETE FROM remote_host_m WHERE name=%s", (name,))
            return {"success": True, "message": f"'{name}' 삭제."}
        return {"success": False, "error": f"지원 action: list/get/register/update/remove (입력: {action})"}
    except Exception as e:
        logger.warning(f"[원격] 호스트 관리 실패: {e}")
        return {"success": False, "error": str(e)}


# 원격 종합 상태 배터리 — 로컬 get_server_resources/get_system_status 미러(read-only).
_STATUS_SCRIPT = (
    "echo '##HOST##'; hostname 2>/dev/null; uname -sr 2>/dev/null; "
    "echo '##UPTIME##'; uptime 2>/dev/null; "
    "echo '##CPU##'; nproc 2>/dev/null; cat /proc/loadavg 2>/dev/null; "
    "echo '##MEM##'; free -m 2>/dev/null | head -3; "
    "echo '##DISK##'; df -h 2>/dev/null | grep -vE 'tmpfs|udev|loop' | head -12; "
    "echo '##TOPPROC##'; ps -eo pid,pcpu,pmem,comm --sort=-pcpu 2>/dev/null | head -8; "
    "echo '##SVC_RUNNING##'; systemctl list-units --type=service --state=running --no-legend --no-pager 2>/dev/null | wc -l; "
    "echo '##SVC_FAILED##'; systemctl list-units --type=service --state=failed --no-legend --no-pager 2>/dev/null | head -10; "
    "echo '##GPU##'; nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null; "
    "echo '##END##'"
)


def remote_status(host: str = None, timeout: int = 25) -> Dict[str, Any]:
    """원격 서버(SSH)의 종합 상태를 로컬처럼 조회 — 호스트·가동시간·부하·CPU·메모리·디스크·
    상위 프로세스·서비스(running 수/failed)·GPU. 전부 read-only. host='등록이름' 또는
    'user@host:port'. SSH 키 인증."""
    if not host:
        return {"success": False, "error": "host 는 필수입니다(등록이름 또는 user@host:port)."}
    r = _ssh_exec(host, _STATUS_SCRIPT, timeout=timeout)
    if not r.get("success"):
        return {"success": False, "host": host,
                "error": r.get("error") or r.get("stderr") or "원격 상태 조회 실패"}
    out = r.get("stdout", "")
    # 마커별 섹션 파싱
    sections, cur = {}, None
    for line in out.splitlines():
        m = re.match(r"^##([A-Z_]+)##$", line.strip())
        if m:
            cur = m.group(1)
            if cur != "END":
                sections[cur] = []
            continue
        if cur and cur != "END":
            sections[cur].append(line)
    parsed = {k: "\n".join(v).strip() for k, v in sections.items()}
    return {"success": True, "host": host,
            "hostname": parsed.get("HOST", ""),
            "uptime": parsed.get("UPTIME", ""),
            "cpu": parsed.get("CPU", ""),
            "memory_mb": parsed.get("MEM", ""),
            "disk": parsed.get("DISK", ""),
            "top_processes": parsed.get("TOPPROC", ""),
            "services_running": parsed.get("SVC_RUNNING", ""),
            "services_failed": parsed.get("SVC_FAILED", "") or "(없음)",
            "gpu": parsed.get("GPU", "") or "(GPU 없음/조회불가)"}


def remote_run(host: str = None, command: str = None, timeout: int = _DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """원격 서버에서 명령 실행. 조회(read-only)는 즉시 실행, 변경성 명령은 실행 보류 후
    관리자 카카오 승인요청(승인 시 approve_remote_command 로 집행). host='이름'|'user@host:port'."""
    if not host or not command:
        return {"success": False, "error": "host 와 command 는 필수입니다."}
    kind = _classify_command(command)
    if kind == "readonly":
        r = _ssh_exec(host, command, timeout=timeout)
        r["host"] = host
        r["command"] = command
        r["kind"] = "readonly"
        return r
    # 변경성 → 실행 보류 + 승인요청
    try:
        ensure_tables()
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            row = d.fetch_one(
                "INSERT INTO remote_command_m (host_spec, command, status) VALUES (%s,%s,'pending') RETURNING id",
                (host, command))
        req_id = dict(row)["id"] if row else None
        from agri_ai_core.src.ai.kakao_notify import push_alert
        push_alert(level="warn", title="[원격명령] 승인요청",
                   body=f"원격 서버 '{host}' 에 변경성 명령 승인요청:\n$ {command}\n\n승인 시 approve_remote_command(id={req_id}).")
        logger.info(f"[원격] 변경성 명령 승인보류: host={host} cmd={command[:60]} id={req_id}")
        return {"success": False, "approval_required": True, "request_id": req_id,
                "kind": "mutating", "host": host, "command": command,
                "message": "변경성 명령이라 즉시 실행하지 않고 관리자 승인요청을 보냈습니다. "
                           "승인 시에만 집행됩니다."}
    except Exception as e:
        return {"success": False, "error": f"승인요청 실패: {e}"}


def approve_remote_command(request_id: int = None, auth_farm_id: str = None) -> Dict[str, Any]:
    """보류된 변경성 원격 명령을 승인·집행(시스템관리자 전용)."""
    if auth_farm_id is not None:
        return {"success": False, "error": "원격 명령 승인은 시스템관리자 전용입니다."}
    if not request_id:
        return {"success": False, "error": "request_id 가 필요합니다."}
    try:
        ensure_tables()
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            r = d.fetch_one("SELECT host_spec, command, status FROM remote_command_m WHERE id=%s", (int(request_id),))
        if not r:
            return {"success": False, "error": f"요청 {request_id} 없음."}
        r = dict(r)
        if r["status"] != "pending":
            return {"success": False, "error": f"이미 처리됨(status={r['status']})."}
        res = _ssh_exec(r["host_spec"], r["command"], timeout=_DEFAULT_TIMEOUT)
        summary = (res.get("stdout") or res.get("error") or "")[:1000]
        with db_session() as d:
            d.execute_query("UPDATE remote_command_m SET status='executed', result=%s, updt_dttm=now() WHERE id=%s",
                            (summary, int(request_id)))
        return {"success": res.get("success"), "request_id": request_id,
                "host": r["host_spec"], "command": r["command"],
                "stdout": res.get("stdout", ""), "stderr": res.get("stderr", "")}
    except Exception as e:
        return {"success": False, "error": str(e)}



# ──────────────────────────────────────────────────────────────────────────────
# 두 원격 호스트의 소스 디렉토리를 결정적으로 비교 — 다단계(접속→해시수집→대조)를
# 코드로 캡슐화. LLM 이 13개 해시를 눈으로 대조하다 틀리는 문제 제거.
# remote_run(find+md5sum, read-only) 로 양쪽 수집 → 파일 존재/내용 차이 계산.
# ──────────────────────────────────────────────────────────────────────────────
def compare_remote_sources(host_a: str = None, host_b: str = None,
                           path: str = None, path_a: str = None, path_b: str = None,
                           pattern: str = "*.py", show_diff: bool = False) -> Dict[str, Any]:
    """두 원격 호스트의 소스(농장관리 프로그램)를 결정적으로 비교. 각 호스트의 소스 루트가
    다를 수 있어(1·3호=~/FarmUnits, 2호=~/SmartFarm) 호스트별 경로를 자동탐지한다.
    path_a/path_b 로 호스트별 지정, path 로 공통 지정 가능. 미지정 시 후보를 자동탐지.
    각 소스 루트 상대경로로 정규화해 비교 → 디렉토리명이 달라도 같은 파일끼리 대조."""
    if not host_a or not host_b:
        return {"success": False, "error": "host_a 와 host_b 는 필수입니다."}
    import re as _re
    import difflib
    _CANDS = ["~/FarmUnits", "~/SmartFarm"]

    def _norm_candidates(explicit):
        # 명시 경로를 정규화한 후보들 + 자동탐지 후보. 앞선 것부터 시도.
        c = []
        if explicit:
            e = str(explicit).strip().rstrip("/")
            c.append(e)
            base = e.split("/")[-1]
            if not e.startswith("~") and not e.startswith("/home"):
                c.append("~/" + base)           # /FarmUnits·FarmUnits → ~/FarmUnits (~ 보정)
            c.append("~/" + base)
        c += _CANDS
        seen = set(); return [x for x in c if not (x in seen or seen.add(x))]

    def _collect(h, explicit):
        roots = _norm_candidates(explicit)              # 후보 경로들(명시+자동탐지)
        bases = [rt.rstrip("/").split("/")[-1] for rt in roots]
        # 한 번의 find 로 모든 후보 경로 동시 탐색 → 호스트당 SSH 1회(접속 최소화).
        cmd = f"find {' '.join(roots)} -maxdepth 6 -name '{pattern}' -type f -exec md5sum {{}} + 2>/dev/null"
        r = remote_run(host=h, command=cmd)
        out = r.get("stdout") or r.get("output") or r.get("result") or ""
        hashes, fulls = {}, {}
        used = None
        for line in str(out).strip().split("\n"):
            p = line.split(None, 1)
            if len(p) == 2 and _re.fullmatch(r"[0-9a-f]{32}", p[0].strip()):
                full = p[1].strip()
                rel = full.split("/")[-1]
                for base in bases:                      # 어떤 후보 루트에 속하든 상대경로 정규화
                    idx = full.rfind("/" + base + "/")
                    if idx >= 0:
                        rel = full[idx + len(base) + 2:]; used = "~/" + base; break
                hashes[rel] = p[0].strip(); fulls[rel] = full
        if hashes:
            return hashes, fulls, used or roots[0], r
        return None, None, None, r

    ha, fa, root_a, ra = _collect(host_a, path_a or path)
    hb, fb, root_b, rb = _collect(host_b, path_b or path)
    if ha is None or hb is None:
        fails = []
        if ha is None: fails.append(f"{host_a}(경로탐지 실패: {str((ra or {}).get('error') or (ra or {}).get('stderr') or 'find 결과 없음')[:80]})")
        if hb is None: fails.append(f"{host_b}(경로탐지 실패: {str((rb or {}).get('error') or (rb or {}).get('stderr') or 'find 결과 없음')[:80]})")
        return {"success": False, "error": "소스 수집 실패: " + "; ".join(fails),
                "hint": "경로를 path_a/path_b 로 명시하거나, 해당 호스트에 소스 디렉토리가 있는지 확인하세요."}

    only_a = sorted(set(ha) - set(hb))
    only_b = sorted(set(hb) - set(ha))
    differ = sorted([k for k in set(ha) & set(hb) if ha[k] != hb[k]])
    res = {
        "success": True, "host_a": host_a, "host_b": host_b,
        "root_a": root_a, "root_b": root_b, "pattern": pattern,
        "file_count_a": len(ha), "file_count_b": len(hb),
        "only_in_a": only_a, "only_in_b": only_b, "differing_files": differ,
        "identical": (not only_a and not only_b and not differ),
        "summary": (f"{host_a}({root_a}) {len(ha)}개 · {host_b}({root_b}) {len(hb)}개 파일. "
                    f"{host_a}에만 {len(only_a)}개, {host_b}에만 {len(only_b)}개, "
                    f"이름같고 내용다름 {len(differ)}개."),
    }
    if show_diff and differ:
        diffs = {}
        for rel in differ[:5]:
            ca = remote_run(host=host_a, command=f"cat '{fa[rel]}'")
            cb = remote_run(host=host_b, command=f"cat '{fb[rel]}'")
            ta = str(ca.get("stdout") or ca.get("output") or "").splitlines()
            tb = str(cb.get("stdout") or cb.get("output") or "").splitlines()
            ud = list(difflib.unified_diff(ta, tb, fromfile=f"{host_a}:{rel}", tofile=f"{host_b}:{rel}", lineterm=""))
            diffs[rel] = "\n".join(ud[:120])
        res["diffs"] = diffs
    return res


TOOL_REGISTRY = {
    "remote_status":          remote_status,
    "remote_run":             remote_run,
    "compare_remote_sources": compare_remote_sources,
    "manage_remote_host":     manage_remote_host,
    "approve_remote_command": approve_remote_command,
}

TOOL_SPECS = [
    {"name": "remote_status",
     "description": "원격 서버에 SSH(키 인증)로 접속해 종합 상태를 로컬처럼 조회한다 — 호스트·가동시간·부하·CPU·메모리·디스크·상위 프로세스·서비스(running/failed)·GPU. 전부 read-only 라 승인 불필요. host 는 등록이름 또는 'user@host:port'.",
     "args": {"host": {"type": "str", "desc": "등록이름 또는 user@host:port"}}},
    {"name": "remote_run",
     "description": "원격 서버에서 명령 실행. 조회 명령(cat/df/ps/systemctl status/journalctl 등)은 즉시 실행. 변경성 명령(rm/systemctl restart/설치 등)은 실행하지 않고 관리자 카카오 승인요청 후 승인 시에만 집행.",
     "args": {"host": {"type": "str", "desc": "등록이름 또는 user@host:port"},
              "command": {"type": "str", "desc": "실행할 셸 명령"}}},
    {"name": "compare_remote_sources",
     "description": "두 재배사 라즈베리파이의 소스(농장관리 프로그램)를 결정적으로 비교한다. host_a·host_b 의 path 디렉토리에서 pattern 파일들의 해시를 수집해 '한쪽에만 있는 파일'과 '이름 같고 내용 다른 파일'을 정확히 반환(LLM 대조 불필요). 호기별 경로: 1·3호=~/FarmUnits, 2호=~/SmartFarm. 소스 차이·비교·틀린 파일 요청에 이 도구를 1순위로 써라.",
     "args": {"host_a": {"type": "str", "desc": "비교 대상 A(예: jaebaesa1)"},
              "host_b": {"type": "str", "desc": "비교 대상 B(예: jaebaesa3)"},
              "path": {"type": "str", "desc": "소스 루트(기본 ~/FarmUnits, 2호는 ~/SmartFarm)"},
              "pattern": {"type": "str", "desc": "파일 패턴(기본 *.py)"},
              "show_diff": {"type": "bool", "desc": "내용 다른 파일의 라인 diff 첨부(선택)"}}},
    {"name": "manage_remote_host",
     "description": "원격 서버 접속정보 등록부. action: list/get/register/remove. register 시 name·host_spec('user@host:port')·identity_path(SSH 키 경로, 선택). 등록/삭제는 관리자. 등록 후 remote_status/remote_run 에서 name 으로 참조.",
     "args": {"action": {"type": "str", "desc": "list|get|register|remove"},
              "name": {"type": "str", "desc": "호스트 별칭"},
              "host_spec": {"type": "str", "desc": "user@host:port"},
              "identity_path": {"type": "str", "desc": "SSH 개인키 경로(선택)"}}},
    {"name": "approve_remote_command",
     "description": "보류된 변경성 원격 명령(remote_run 이 승인요청한 것)을 승인·집행한다(관리자 전용).",
     "args": {"request_id": {"type": "int", "desc": "승인할 요청 id"}}},
]


def tool_specs_text() -> str:
    lines = ["\n[원격 서버 조사 도구 — SSH 키 인증, 조회 read-only·변경성은 승인 후]"]
    for spec in TOOL_SPECS:
        arg = ", ".join(f"{k}({v.get('type','')})" for k, v in spec["args"].items())
        lines.append(f"- {spec['name']}({arg}): {spec['description']}")
    return "\n".join(lines) + "\n"
