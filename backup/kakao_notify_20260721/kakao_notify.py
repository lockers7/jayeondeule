# ══════════════════════════════════════════════════════════════════════════════
# 카카오톡 "나에게 보내기" 실시간 알림
#
# Agent/비상 알림을 카카오 메모 API("나에게 보내기")로 실시간 푸시한다.
#
# 구조:
#   - 토큰은 kakao_token_m(단일행)에 영속 — access(6h)/refresh(2개월) 자동 갱신,
#     갱신 응답에 새 refresh_token 이 오면 즉시 교체 저장(만료 임박 회전 대응).
#   - 발송은 전부 best-effort: 실패해도 예외를 밖으로 내지 않음(알림 저장 흐름 보호).
#   - 미설정(REST 키/토큰 없음) 시 조용히 no-op — 기존 동작 100% 보전.
#
# 환경변수:
#   KAKAO_REST_API_KEY   : Kakao Developers 앱 REST API 키 (필수)
#   KAKAO_REDIRECT_URI   : 인증 콜백 URI (기본: 운영 도메인 /ai-api 콜백)
#   KAKAO_PUSH_MIN_LEVEL : 푸시 최소 레벨 info|warning|critical (기본 info)
#
# 발송 정책(kakao_notify_config 단일행) — 값은 LLM 이 농장주 요청을 받아 기록하고
# 코드는 이행만 한다. critical(비상) 은 정책과 무관하게 항상 즉시 발송(농장주 지시).
#
# 파일 시작 함수 목록:
#   ensure_table         : kakao_token_m 테이블 보장
#   ensure_policy_table  : kakao_notify_config(발송 정책) 테이블 보장
#   get_notify_policy    : 발송 정책 실시간 조회 (캐시 금지)
#   set_notify_cooldown  : 최소 발송 간격(분) 기록 — LLM set_alert_interval 이 호출
#   set_notify_min_level : 최소 심각도 기록 — LLM set_alert_level 이 호출
#   _stamp_sent          : 실제 발송 시각 기록 (쿨다운 창 기준점)
#   build_auth_url       : 관리자 1회 인증용 카카오 동의 URL 생성
#   exchange_code        : 인증 code → 토큰 발급·저장 (연동 개시)
#   get_status           : 연동 상태(토큰 유효기한) 조회
#   _split_chunks        : 200자 제한 대응 줄 단위 분할 (최대 4조각, (i/n) 표기)
#   send_to_me           : 텍스트 메모 발송 (분할 발송 + 401 시 1회 갱신 재시도)
#   push_alert           : 정책 이행(심각도·쿨다운) + 포맷 발송 (알림 훅 진입점)
#   _load_tokens/_save_tokens/_refresh/_get_valid_access_token : 토큰 수명 관리
# ══════════════════════════════════════════════════════════════════════════════
import os
import json
import threading
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_AUTH_HOST = "https://kauth.kakao.com"
_API_HOST = "https://kapi.kakao.com"
_TIMEOUT = 5
_TEXT_LIMIT = 200          # 카카오 text 템플릿 최대 길이
_LEVEL_ORDER = {"info": 0, "warning": 1, "critical": 2}

_DEFAULT_REDIRECT = "https://lockers7.iptime.org/ai-api/api/v1/admin/kakao/callback"
_DEFAULT_LINK = "https://lockers7.iptime.org/agent-history"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS kakao_token_m (
    id                 INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    access_token       TEXT,
    refresh_token      TEXT,
    access_expires_at  TIMESTAMP,
    refresh_expires_at TIMESTAMP,
    updt_dttm          TIMESTAMP NOT NULL DEFAULT now()
)
"""

# 발송 정책(단일행) — 값은 전적으로 LLM 이 농장주 요청을 받아 도구로 기록한다.
# 코드는 정책을 정하지 않고 기록된 값을 이행만 한다(농장주 지시: LLM 자율).
#   cooldown_min : 카카오 최소 발송 간격(분). NULL/0 = 해제(매번 발송).
#   min_level    : 발송 최소 심각도. NULL = 미설정(env KAKAO_PUSH_MIN_LEVEL 폴백).
#   last_sent_at : 마지막 실제 발송 시각 — 쿨다운 판정 기준.
_CREATE_POLICY_TABLE = """
CREATE TABLE IF NOT EXISTS kakao_notify_config (
    id           INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    cooldown_min INTEGER,
    min_level    VARCHAR(16),
    last_sent_at TIMESTAMP,
    updt_dttm    TIMESTAMP NOT NULL DEFAULT now()
);
INSERT INTO kakao_notify_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
"""

_ensured = False
_policy_ensured = False
_lock = threading.Lock()


def _rest_key() -> str:
    return (os.getenv("KAKAO_REST_API_KEY") or "").strip()


def _redirect_uri() -> str:
    return (os.getenv("KAKAO_REDIRECT_URI") or _DEFAULT_REDIRECT).strip()


def _secret_params() -> dict:
    # 키에 '클라이언트 시크릿 — 사용함' 설정 시 토큰 요청에 필수 (KOE010 대응)
    sec = (os.getenv("KAKAO_CLIENT_SECRET") or "").strip()
    return {"client_secret": sec} if sec else {}


def ensure_table():
    global _ensured
    if _ensured:
        return
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        d.execute_query(_CREATE_TABLE, ())
    _ensured = True


# ────────────────────────────────────────────────────────────────────
# kakao_notify_config(단일행) 테이블 보장 — idempotent.
# ────────────────────────────────────────────────────────────────────
def ensure_policy_table():
    global _policy_ensured
    if _policy_ensured:
        return
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        d.execute_query(_CREATE_POLICY_TABLE, ())
    _policy_ensured = True


# ────────────────────────────────────────────────────────────────────
# 발송 정책 실시간 조회 — 캐시 금지(농장주 정책: setting 은 DB 실시간 read).
# 조회 실패 시 {} 반환 → 호출측이 기존 동작(무제한 발송)으로 폴백.
# ────────────────────────────────────────────────────────────────────
def get_notify_policy() -> Dict[str, Any]:
    try:
        ensure_policy_table()
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            row = d.fetch_one(
                "SELECT cooldown_min, min_level, last_sent_at "
                "FROM kakao_notify_config WHERE id = 1", ())
        return dict(row) if row else {}
    except Exception as e:
        logger.debug(f"[카카오알림] 정책 조회 실패 — 무제한 발송 폴백: {e}")
        return {}


# ────────────────────────────────────────────────────────────────────
# 카카오 최소 발송 간격(분) 기록 — LLM 의 set_alert_interval 이 호출.
# interval_min <= 0 이면 NULL(쿨다운 해제).
# ────────────────────────────────────────────────────────────────────
def set_notify_cooldown(interval_min: Optional[int]) -> bool:
    try:
        ensure_policy_table()
        cd = int(interval_min) if interval_min and int(interval_min) > 0 else None
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            d.execute_query(
                "UPDATE kakao_notify_config SET cooldown_min = %s, updt_dttm = now() "
                "WHERE id = 1", (cd,))
        logger.info(f"[카카오알림] 발송 간격 정책 기록 — {cd if cd else '해제(매번 발송)'}")
        return True
    except Exception as e:
        logger.warning(f"[카카오알림] set_notify_cooldown 실패: {e}")
        return False


# ────────────────────────────────────────────────────────────────────
# 발송 최소 심각도 기록 — LLM 의 set_alert_level 이 호출.
# level=None/'' 이면 NULL(미설정 → env 폴백). critical 은 항상 예외 통과이므로
# min_level 을 critical 로 두면 "심각한 문제만 알림" 이 된다.
# ────────────────────────────────────────────────────────────────────
def set_notify_min_level(level: Optional[str]) -> bool:
    try:
        ensure_policy_table()
        lv = (level or "").strip().lower() or None
        if lv is not None and lv not in _LEVEL_ORDER:
            return False
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            d.execute_query(
                "UPDATE kakao_notify_config SET min_level = %s, updt_dttm = now() "
                "WHERE id = 1", (lv,))
        logger.info(f"[카카오알림] 최소 심각도 정책 기록 — {lv or '미설정(env 폴백)'}")
        return True
    except Exception as e:
        logger.warning(f"[카카오알림] set_notify_min_level 실패: {e}")
        return False


# ────────────────────────────────────────────────────────────────────
# 실제 발송 확정 시각 기록 — 쿨다운 창의 기준점.
# ────────────────────────────────────────────────────────────────────
def _stamp_sent():
    try:
        ensure_policy_table()
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            d.execute_query(
                "UPDATE kakao_notify_config SET last_sent_at = now() WHERE id = 1", ())
    except Exception as e:
        logger.debug(f"[카카오알림] last_sent_at 기록 실패(발송은 진행): {e}")


def _load_tokens() -> Optional[Dict[str, Any]]:
    ensure_table()
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        row = d.fetch_one(
            "SELECT access_token, refresh_token, access_expires_at, refresh_expires_at "
            "FROM kakao_token_m WHERE id = 1", ())
    return dict(row) if row and row.get("refresh_token") else None


def _save_tokens(access_token: str, access_expires_in: int,
                 refresh_token: Optional[str] = None,
                 refresh_expires_in: Optional[int] = None):
    ensure_table()
    from agri_ai_core.src.postgresql.connection import db_session
    now = datetime.now()
    with db_session() as d:
        if refresh_token:
            d.execute_query(
                "INSERT INTO kakao_token_m (id, access_token, refresh_token, "
                "access_expires_at, refresh_expires_at, updt_dttm) "
                "VALUES (1, %s, %s, %s, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET access_token = EXCLUDED.access_token, "
                "refresh_token = EXCLUDED.refresh_token, "
                "access_expires_at = EXCLUDED.access_expires_at, "
                "refresh_expires_at = EXCLUDED.refresh_expires_at, updt_dttm = now()",
                (access_token, refresh_token,
                 now + timedelta(seconds=access_expires_in or 21599),
                 now + timedelta(seconds=refresh_expires_in or 5184000)))
        else:
            d.execute_query(
                "UPDATE kakao_token_m SET access_token = %s, "
                "access_expires_at = %s, updt_dttm = now() WHERE id = 1",
                (access_token, now + timedelta(seconds=access_expires_in or 21599)))


def build_auth_url() -> Dict[str, Any]:
    key = _rest_key()
    if not key:
        return {"success": False,
                "error": "KAKAO_REST_API_KEY 미설정 — Kakao Developers 앱의 REST API 키를 .env 에 넣어주세요."}
    from urllib.parse import urlencode
    url = f"{_AUTH_HOST}/oauth/authorize?" + urlencode({
        "client_id": key,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": "talk_message",
    })
    return {"success": True, "auth_url": url, "redirect_uri": _redirect_uri()}


def exchange_code(code: str) -> Dict[str, Any]:
    try:
        import requests
        r = requests.post(f"{_AUTH_HOST}/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": _rest_key(),
            "redirect_uri": _redirect_uri(),
            "code": code,
            **_secret_params(),
        }, timeout=_TIMEOUT)
        body = r.json()
        if r.status_code != 200 or "access_token" not in body:
            return {"success": False, "error": f"토큰 발급 실패: {body}"}
        _save_tokens(body["access_token"], body.get("expires_in", 21599),
                     body.get("refresh_token"),
                     body.get("refresh_token_expires_in"))
        logger.info("[카카오알림] 연동 완료 — 토큰 저장")
        return {"success": True, "message": "카카오 '나에게 보내기' 연동 완료"}
    except Exception as e:
        logger.error(f"[카카오알림] exchange_code 실패: {e}")
        return {"success": False, "error": str(e)}


def _refresh(tokens: Dict[str, Any]) -> Optional[str]:
    try:
        import requests
        r = requests.post(f"{_AUTH_HOST}/oauth/token", data={
            "grant_type": "refresh_token",
            "client_id": _rest_key(),
            "refresh_token": tokens["refresh_token"],
            **_secret_params(),
        }, timeout=_TIMEOUT)
        body = r.json()
        if r.status_code != 200 or "access_token" not in body:
            logger.warning(f"[카카오알림] 토큰 갱신 실패: {body} — 재인증 필요 가능")
            return None
        # 만료 임박 시에만 새 refresh_token 이 옴 — 오면 반드시 교체 저장
        _save_tokens(body["access_token"], body.get("expires_in", 21599),
                     body.get("refresh_token"),
                     body.get("refresh_token_expires_in"))
        return body["access_token"]
    except Exception as e:
        logger.warning(f"[카카오알림] 토큰 갱신 예외: {e}")
        return None


def _get_valid_access_token() -> Optional[str]:
    tokens = _load_tokens()
    if not tokens:
        return None
    exp = tokens.get("access_expires_at")
    if tokens.get("access_token") and exp and exp > datetime.now() + timedelta(minutes=10):
        return tokens["access_token"]
    with _lock:
        return _refresh(tokens)


def get_status() -> Dict[str, Any]:
    if not _rest_key():
        return {"configured": False, "reason": "KAKAO_REST_API_KEY 미설정"}
    tokens = _load_tokens()
    if not tokens:
        return {"configured": False, "reason": "미인증 — auth-url 로 1회 동의 필요"}
    return {"configured": True,
            "access_expires_at": str(tokens.get("access_expires_at")),
            "refresh_expires_at": str(tokens.get("refresh_expires_at")),
            "min_level": os.getenv("KAKAO_PUSH_MIN_LEVEL", "info")}


def _split_chunks(text: str, limit: int = _TEXT_LIMIT, max_parts: int = 4):
    # 카카오 text 템플릿 200자 제한 대응 — 줄 단위 우선 분할, 최대 max_parts 조각.
    text = (text or "").strip()
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for line in text.splitlines():
        while len(line) > limit:          # 한 줄 자체가 초과하면 강제 절단
            parts.append(line[:limit]); line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            if cur:
                parts.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        parts.append(cur)
    if len(parts) > max_parts:
        parts = parts[:max_parts]
        parts[-1] = parts[-1][: limit - 12] + "\n…(이하 생략)"
    return parts


def send_to_me(text: str, web_url: str = None) -> Dict[str, Any]:
    try:
        import requests
        token = _get_valid_access_token()
        if not token:
            return {"success": False, "error": "카카오 미연동(토큰 없음)"}

        def _post(tk, body):
            template = {
                "object_type": "text",
                "text": body,
                "link": {"web_url": web_url or _DEFAULT_LINK,
                         "mobile_web_url": web_url or _DEFAULT_LINK},
                "button_title": "농장 확인",
            }
            return requests.post(
                f"{_API_HOST}/v2/api/talk/memo/default/send",
                headers={"Authorization": f"Bearer {tk}"},
                data={"template_object": json.dumps(template, ensure_ascii=False)},
                timeout=_TIMEOUT)

        # "(i/n) " 접두어(최대 8자) 공간을 예약해 분할 — 접두어로 인한 재절단 방지
        chunks = _split_chunks(text, limit=_TEXT_LIMIT - 8)
        n = len(chunks)
        last_status = 0
        for i, chunk in enumerate(chunks, 1):
            body = f"({i}/{n}) {chunk}" if n > 1 else chunk
            r = _post(token, body)
            if r.status_code == 401:   # 만료 경합 — 1회 강제 갱신 재시도
                tokens = _load_tokens()
                token = _refresh(tokens) if tokens else None
                if not token:
                    return {"success": False, "error": "토큰 갱신 실패"}
                r = _post(token, body)
            last_status = r.status_code
            if r.status_code != 200:
                logger.warning(f"[카카오알림] 발송 실패({i}/{n}) status={r.status_code} body={r.text[:150]}")
                return {"success": False, "status_code": r.status_code, "sent_parts": i - 1}
        return {"success": True, "status_code": last_status, "sent_parts": n}
    except Exception as e:
        logger.warning(f"[카카오알림] 발송 예외: {e}")
        return {"success": False, "error": str(e)}


# ────────────────────────────────────────────────────────────────────
# 알림 훅 진입점 — _save_alert(agent)/alert_bus(비상) 에서 호출.
# 반드시 예외를 삼킨다(알림 저장·발행 흐름을 절대 깨지 않음).
# 발송은 데몬 스레드로 — 스케줄러/버스를 네트워크 지연으로 막지 않음.
# ────────────────────────────────────────────────────────────────────
def push_alert(level: str, title: str, body: str, web_url: str = None):
    try:
        if not _rest_key():
            return
        lv = (level or "info").lower()

        # 농장주 지시: critical(비상) 은 어떤 정책에도 억제되지 않고 즉시 발송.
        # 그 외 레벨만 LLM 이 기록한 심각도·간격 정책을 이행한다.
        if lv != "critical":
            pol = get_notify_policy()

            min_lv = (pol.get("min_level")
                      or (os.getenv("KAKAO_PUSH_MIN_LEVEL", "info") or "info").lower())
            if _LEVEL_ORDER.get(lv, 0) < _LEVEL_ORDER.get(min_lv, 0):
                logger.info(f"[카카오알림] 심각도 미달 억제 — level={lv} < 최소={min_lv}")
                return

            cd = pol.get("cooldown_min") or 0
            last = pol.get("last_sent_at")
            if cd > 0 and last is not None:
                elapsed = datetime.now() - last
                if elapsed < timedelta(minutes=int(cd)):
                    left = int(cd) - int(elapsed.total_seconds() // 60)
                    logger.info(f"[카카오알림] 쿨다운 억제 — 간격 {cd}분, "
                                f"{left}분 후 발송 가능 (level={lv})")
                    return

        icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(lv, "ℹ️")
        text = f"{icon} [{lv.upper()}] {title or '농장 알림'}\n{body or ''}"
        _stamp_sent()

        def _bg():
            try:
                send_to_me(text, web_url=web_url)
            except Exception:
                pass
        threading.Thread(target=_bg, daemon=True).start()
    except Exception as e:
        logger.debug(f"[카카오알림] push_alert 무시된 오류: {e}\n{traceback.format_exc()}")
