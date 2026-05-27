# ══════════════════════════════════════════════════════════════════════════════
# MCP 서버 등록부 도구 — LLM 이 요청받은 MCP 서버를 스스로 추가/제거한다.
#
# 설계 의도(농장주 지시 2026-07-23): "어떤 MCP 든 내가 요청하면 스스로 추가".
#   기존엔 mcp_call/mcp_list_tools 가 .vscode/mcp.json 에 이미 등록된 서버만
#   호출할 수 있었다. 이 도구는 그 mcp.json(servers 키)에 신규 서버를 직접
#   써넣어(코드·재기동 불필요) 즉시 사용 가능하게 한다 — _load_mcp_servers 가
#   매 호출 파일을 새로 읽으므로 add 즉시 mcp_list_tools/mcp_call 로 열린다.
#
# 안전 모델:
#   · 변경(add/update/remove)은 시스템관리자(auth_farm_id=None) 전용
#   · command 는 런처 allowlist(npx/uvx/uv/python/node/docker…)만 — 임의 쉘 실행 차단
#   · 쓰기 전 원본을 .bak 백업 + 임시파일에 쓰고 JSON 검증 후 원자적 교체
#   · env 값은 ${VAR}/{ENV:VAR} 플레이스홀더 권장(시크릿을 파일에 평문저장 회피)
#   · 이름 검증, 기존 서버 덮어쓰기는 action='update' 로만
#
# 파일 시작 함수 목록:
#   _config_path       : mcp.json 경로
#   _load_raw          : mcp.json 원본 dict 로드
#   _servers_key       : servers/mcpServers 키 판별(기본 servers)
#   _save_raw          : 백업 + 원자적 쓰기(JSON 검증)
#   _redact_env        : env 표시용 값 마스킹
#   manage_mcp_server  : list/get/add/register/update/remove/test
# ══════════════════════════════════════════════════════════════════════════════
import json
import os
import re
import shutil
import time
import traceback
from typing import Any, Dict, List, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# MCP 서버 런처 allowlist — 임의 명령 실행(RCE) 차단. 실제 MCP 서버는 이 런처들로 뜬다.
_ALLOWED_COMMANDS = {
    x.strip() for x in os.getenv(
        "MCP_ADD_ALLOWED_COMMANDS",
        "npx,uvx,uv,python,python3,node,deno,bunx,docker").split(",") if x.strip()
}
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,59}$")


def _config_path():
    from agri_ai_core.src.ai.mcp_client import MCP_CONFIG_PATH
    return MCP_CONFIG_PATH


def _load_raw() -> Dict[str, Any]:
    p = _config_path()
    if not p.exists():
        return {"servers": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def _servers_key(raw: Dict[str, Any]) -> str:
    # 우리 파일은 VSCode 소유라 "servers". mcpServers 가 있으면 그걸 존중.
    if isinstance(raw.get("mcpServers"), dict):
        return "mcpServers"
    return "servers"


def _save_raw(raw: Dict[str, Any]) -> None:
    p = _config_path()
    text = json.dumps(raw, ensure_ascii=False, indent=2) + "\n"
    json.loads(text)                                   # 쓰기 전 유효성 재확인
    if p.exists():
        try:
            shutil.copy2(str(p), str(p) + ".bak")      # 롤백용 백업(best-effort)
        except Exception as e:
            logger.warning(f"[MCP등록부] 백업 생략(권한 등): {e}")   # 백업 실패가 add 를 막지 않게
    tmp = str(p) + f".tmp{int(time.time())}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, str(p))                            # 원자적 교체


def _redact_env(env: Any) -> Dict[str, str]:
    out = {}
    if isinstance(env, dict):
        for k, v in env.items():
            sv = str(v)
            # ${VAR}/{ENV:VAR} 플레이스홀더는 그대로, 그 외 값은 마스킹
            out[k] = sv if ("${" in sv or "{ENV:" in sv) else "***"
    return out


def manage_mcp_server(action: str, name: str = None, command: str = None,
                      args: Any = None, env: Any = None, url: str = None,
                      transport: str = None, auth_farm_id: str = None) -> Dict[str, Any]:
    try:
        action = (action or "").strip().lower()
        raw = _load_raw()
        skey = _servers_key(raw)
        servers = raw.setdefault(skey, {})
        if not isinstance(servers, dict):
            return {"success": False, "error": f"mcp.json 의 {skey} 형식이 올바르지 않습니다."}

        # ── 조회(누구나) ──
        if action == "list":
            out = []
            for n, cfg in sorted(servers.items()):
                cfg = cfg or {}
                out.append({"name": n,
                            "command": cfg.get("command") or cfg.get("type") or "-",
                            "args_count": len(cfg.get("args", []) or []),
                            "has_url": bool(cfg.get("url"))})
            return {"success": True, "count": len(out), "servers": out,
                    "message": "도구 확인은 mcp_list_tools(server='이름'), 호출은 mcp_call."}

        if not name or not _NAME_RE.match(name):
            return {"success": False,
                    "error": "name 은 영문/숫자로 시작하는 2~60자(영문·숫자·_·-)여야 합니다."}

        if action == "get":
            cfg = servers.get(name)
            if not cfg:
                return {"success": False, "error": f"미등록 MCP 서버: {name}"}
            shown = dict(cfg)
            if "env" in shown:
                shown["env"] = _redact_env(shown.get("env"))
            return {"success": True, "server": name, "config": shown}

        if action == "test":
            if name not in servers:
                return {"success": False, "error": f"미등록 MCP 서버: {name} — 먼저 add 하세요."}
            from agri_ai_core.src.ai.tools_mcp_gateway import mcp_list_tools
            res = mcp_list_tools(server=name)
            if res.get("success"):
                return {"success": True, "server": name, "connected": True,
                        "tool_count": res.get("count", 0), "tools": res.get("tools", [])[:20]}
            return {"success": False, "server": name, "connected": False,
                    "error": res.get("error", "연결 실패")}

        # ── 이하 변경(add/update/remove): 시스템관리자 전용 ──
        if auth_farm_id is not None:
            return {"success": False,
                    "error": "MCP 서버 등록/제거는 시스템관리자 전용입니다."}

        if action == "remove" or action == "delete":
            if name not in servers:
                return {"success": False, "error": f"미등록 MCP 서버: {name}"}
            removed = servers.pop(name)
            _save_raw(raw)
            logger.info(f"[MCP등록부] 제거: {name}")
            return {"success": True, "removed": name,
                    "message": f"MCP 서버 '{name}' 제거 완료(백업 mcp.json.bak). "
                               f"command={ (removed or {}).get('command') }"}

        if action in ("add", "register", "update"):
            exists = name in servers
            if exists and action in ("add", "register"):
                return {"success": False,
                        "error": f"'{name}' 은 이미 등록돼 있습니다. 덮어쓰려면 action='update'."}

            # 인자 정규화
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = [a for a in args.split() if a]
            if args is None:
                args = []
            if not isinstance(args, list):
                return {"success": False, "error": "args 는 문자열 배열(리스트)이어야 합니다."}
            args = [str(a) for a in args]

            if isinstance(env, str):
                try:
                    env = json.loads(env)
                except Exception:
                    return {"success": False, "error": "env 는 JSON 객체여야 합니다."}
            if env is not None and not isinstance(env, dict):
                return {"success": False, "error": "env 는 문자열 키/값 객체여야 합니다."}

            # stdio(command) 또는 http(url) 두 형태 지원
            cfg: Dict[str, Any] = {}
            if url:
                if not str(url).lower().startswith(("http://", "https://")):
                    return {"success": False, "error": "url 은 http(s):// 로 시작해야 합니다."}
                cfg["type"] = (transport or "http")
                cfg["url"] = str(url)
            else:
                if not command:
                    return {"success": False,
                            "error": "command(런처) 또는 url 중 하나는 필수입니다. "
                                     f"허용 command: {sorted(_ALLOWED_COMMANDS)}"}
                if command not in _ALLOWED_COMMANDS:
                    return {"success": False,
                            "error": f"command '{command}' 은 허용되지 않습니다(임의 실행 차단). "
                                     f"허용 런처: {sorted(_ALLOWED_COMMANDS)}"}
                cfg["command"] = command
                cfg["args"] = args
            if env:
                cfg["env"] = {str(k): str(v) for k, v in env.items()}

            servers[name] = cfg
            _save_raw(raw)
            logger.info(f"[MCP등록부] {action}: {name} — {cfg.get('command') or cfg.get('url')}")
            return {"success": True, "server": name, "action": action,
                    "config": {**cfg, "env": _redact_env(cfg.get("env"))} if cfg.get("env") else cfg,
                    "message": f"MCP 서버 '{name}' {action} 완료. "
                               f"연결 확인은 manage_mcp_server(action='test', name='{name}') "
                               f"또는 mcp_list_tools(server='{name}'). 코드/재기동 불필요."}

        return {"success": False,
                "error": f"지원 action: list/get/add/update/remove/test (입력: {action})"}
    except Exception as e:
        logger.error(f"[MCP등록부] 실패: {e}\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}
