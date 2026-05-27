# ══════════════════════════════════════════════════════════════════════════════
# 범용 외부 API 도구 — 코드 변경 없는 신규 외부 연동
#
# 관리자가 채팅(manage_external_api)으로 API 를 external_api_m 에 등록하면
# LLM 이 call_external_api 로 즉시 호출 — 신규 연동은 데이터 등록 1건으로 완료.
#
# 보안 모델:
#   - URL 의 호스트/경로는 관리자 등록 템플릿에 고정 — LLM 은 {param} 값만 채움
#     (값은 URL 인코딩되어 주입 → 호스트 변조/SSRF 불가)
#   - {ENV:이름} 플레이스홀더는 서버 환경변수로 치환 (API 키를 DB 에 두지 않음)
#   - 사설/루프백 대역 호스트 등록·호출 차단, GET 전용, timeout 10s, 응답 8000자 캡
#   - register/update/disable 은 시스템관리자(auth_farm_id=None) 전용
#
# 파일 시작 함수 목록:
#   ensure_table          : external_api_m 테이블 보장
#   _is_private_host      : 사설/루프백 호스트 차단 판정
#   _render_url           : 템플릿 + params + ENV 치환 (값 URL 인코딩)
#   manage_external_api   : list/get/register/update/disable (변경은 관리자 전용)
#   call_external_api     : 등록 API 호출 (GET, JSON 정형화, 크기 캡)
# ══════════════════════════════════════════════════════════════════════════════
import os
import re
import json
import traceback
from typing import Dict, Any
from urllib.parse import quote, urlparse

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_MAX_RESPONSE_CHARS = 8000
_TIMEOUT_SEC = 10

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS external_api_m (
    api_name      VARCHAR(60) PRIMARY KEY,
    description   TEXT        NOT NULL,
    url_template  TEXT        NOT NULL,
    response_hint TEXT,
    use_yn        CHAR(1)     NOT NULL DEFAULT 'Y',
    created_by    VARCHAR(40),
    updt_dttm     TIMESTAMP   NOT NULL DEFAULT now()
)
"""

_ensured = False


def ensure_table():
    global _ensured
    if _ensured:
        return
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        d.execute_query(_CREATE_TABLE, ())
    _ensured = True


def _is_private_host(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return True
    if not host or host in ("localhost", "0.0.0.0", "::1"):
        return True
    return bool(re.match(
        r"^(127\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2[0-9]|3[01])\.)", host))


def _render_url(template: str, params: Dict[str, Any]) -> str:
    # {ENV:이름} → 서버 환경변수 (API 키 등, DB 미보관)
    def _env_sub(m):
        v = os.getenv(m.group(1), "")
        return quote(str(v), safe="")
    url = re.sub(r"\{ENV:([A-Za-z0-9_]+)\}", _env_sub, template)

    # {param} → LLM 전달 값 (URL 인코딩 — 호스트/경로 변조 불가)
    missing = []
    def _param_sub(m):
        key = m.group(1)
        if key not in params or params[key] in (None, ""):
            missing.append(key)
            return m.group(0)
        return quote(str(params[key]), safe="")
    url = re.sub(r"\{([A-Za-z0-9_]+)\}", _param_sub, url)
    if missing:
        raise ValueError(f"필수 파라미터 누락: {', '.join(sorted(set(missing)))}")
    return url


def manage_external_api(action: str, api_name: str = None, description: str = None,
                        url_template: str = None, response_hint: str = None,
                        auth_farm_id: str = None) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        ensure_table()
        action = (action or "").strip().lower()

        if action == "list":
            with db_session() as d:
                rows = d.fetch_all(
                    "SELECT api_name, description, use_yn FROM external_api_m ORDER BY api_name",
                    (), as_dict=True) or []
            return {"success": True,
                    "apis": [dict(r) for r in rows],
                    "count": len(rows),
                    "message": "호출은 call_external_api, 상세는 action='get' 을 사용하세요."}

        if not api_name or not re.match(r"^[a-z0-9_]{2,60}$", api_name):
            return {"success": False, "error": "api_name 은 소문자/숫자/밑줄 2~60자여야 합니다."}

        if action == "get":
            with db_session() as d:
                row = d.fetch_one(
                    "SELECT api_name, description, url_template, response_hint, use_yn, updt_dttm "
                    "FROM external_api_m WHERE api_name = %s", (api_name,))
            if not row:
                return {"success": False, "error": f"미등록 API: {api_name}"}
            out = dict(row)
            out["updt_dttm"] = str(out.get("updt_dttm"))
            return {"success": True, "api": out}

        # ── 이하 변경 작업: 시스템관리자 전용 ──
        if auth_farm_id is not None:
            return {"success": False,
                    "error": "외부 API 등록/변경은 시스템관리자 전용입니다."}

        if action in ("register", "update"):
            if not description or not url_template:
                return {"success": False, "error": "description, url_template 이 필요합니다."}
            if not url_template.lower().startswith(("http://", "https://")):
                return {"success": False, "error": "url_template 은 http(s):// 로 시작해야 합니다."}
            if _is_private_host(url_template):
                return {"success": False, "error": "사설/루프백 호스트는 등록할 수 없습니다."}
            with db_session() as d:
                d.execute_query(
                    "INSERT INTO external_api_m (api_name, description, url_template, response_hint, use_yn, created_by, updt_dttm) "
                    "VALUES (%s, %s, %s, %s, 'Y', %s, now()) "
                    "ON CONFLICT (api_name) DO UPDATE SET description = EXCLUDED.description, "
                    "url_template = EXCLUDED.url_template, response_hint = EXCLUDED.response_hint, "
                    "use_yn = 'Y', updt_dttm = now()",
                    (api_name, description, url_template, response_hint or "", "admin"))
            logger.info(f"[외부API] {action}: {api_name} — {description[:60]}")
            return {"success": True,
                    "message": f"외부 API '{api_name}' 등록 완료. call_external_api 로 즉시 호출 가능합니다."}

        if action == "disable":
            with db_session() as d:
                d.execute_query(
                    "UPDATE external_api_m SET use_yn = 'N', updt_dttm = now() WHERE api_name = %s",
                    (api_name,))
            return {"success": True, "message": f"'{api_name}' 비활성화 완료."}

        return {"success": False,
                "error": f"지원 action: list/get/register/update/disable (입력: {action})"}
    except Exception as e:
        logger.error(f"[외부API 관리] 실패: {e}\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}


def call_external_api(api_name: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    try:
        import requests
        from agri_ai_core.src.postgresql.connection import db_session
        ensure_table()

        if not api_name:
            r = manage_external_api("list")
            r["message"] = "api_name 이 필요합니다. 아래 등록 목록에서 선택하세요."
            return r

        with db_session() as d:
            row = d.fetch_one(
                "SELECT url_template, description, response_hint FROM external_api_m "
                "WHERE api_name = %s AND use_yn = 'Y'", (api_name,))
        if not row:
            avail = manage_external_api("list").get("apis", [])
            return {"success": False,
                    "error": f"미등록/비활성 API: {api_name}. 등록 목록: "
                             f"{[a['api_name'] for a in avail] or '없음'}"}

        url = _render_url(row["url_template"], params or {})
        if _is_private_host(url):
            return {"success": False, "error": "사설/루프백 호스트 호출이 차단되었습니다."}

        resp = requests.get(url, timeout=_TIMEOUT_SEC)
        body = resp.text or ""
        try:
            body = json.dumps(resp.json(), ensure_ascii=False, indent=1)
        except Exception:
            pass
        if len(body) > _MAX_RESPONSE_CHARS:
            body = body[:_MAX_RESPONSE_CHARS] + "\n...(응답 잘림)"

        hint = f"\n[해석 힌트] {row['response_hint']}" if row.get("response_hint") else ""
        return {"success": resp.status_code == 200,
                "status_code": resp.status_code,
                "message": f"[{api_name} — {row['description']}]{hint}\n{body}"}
    except ValueError as ve:
        return {"success": False, "error": str(ve)}
    except Exception as e:
        logger.error(f"[외부API 호출] {api_name} 실패: {e}")
        return {"success": False, "error": str(e)}
