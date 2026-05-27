# ══════════════════════════════════════════════════════════════════════════════
# Agent Scheduler — 30분 cron 데몬
#
# ai_monitor_agent.run_agent 호출 → DB 영속.
# 운영 scheduler (`agri_ai_core/scheduler.py`) 와 *완전 별개 프로세스*.
#
# 동작:
#   · 매 AGENT_SUB_POLL_SEC 초마다 due agent_subscriptions 을 claim 하여 run_agent 실행
#   · default subscription(__default_cron__) 부트스트랩으로 기본 cron 사이클 유지
#
# 환경변수:
#   AGENT_INTERVAL_MIN  : 사이클 주기 (기본 30분)
#   AGENT_FARM_IDS      : 모니터링 농장 ID 쉼표 구분 (기본 "1")
#   AGENT_INITIAL_DELAY : 시작 시 첫 사이클 대기 (초, 기본 60)
#   AGENT_LLM_MODEL     : LLM 모델 (ai_monitor_agent 와 공유)
#
# 사용법:
#   python -m agri_ai_core.src.control.agent_scheduler
#
# 파일 시작 함수 목록:
#   _next_interval_dt    : 다음 사이클 fire 시각 계산
#   _run_cycle           : 한 사이클 실행 (모든 농장 모니터링)
#   _build_default_task  : 기본 작업 지시문 합성
#   main                 : 무한 loop 엔트리포인트
# ══════════════════════════════════════════════════════════════════════════════
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.control.ai_monitor_agent import run_agent

logger = setup_logger(__name__)

AGENT_INTERVAL_MIN  = int(os.getenv("AGENT_INTERVAL_MIN", "30"))
AGENT_INITIAL_DELAY = int(os.getenv("AGENT_INITIAL_DELAY", "60"))
AGENT_FARM_IDS      = [int(x.strip()) for x in os.getenv("AGENT_FARM_IDS", "1").split(",") if x.strip()]
# subscriptions polling 주기 (초). 기본 60.
AGENT_SUB_POLL_SEC  = int(os.getenv("AGENT_SUB_POLL_SEC", "60"))
# default subscription 자동 부트스트랩 여부 (기존 30분 cron 호환)
AGENT_BOOTSTRAP_DEFAULT = os.getenv("AGENT_BOOTSTRAP_DEFAULT", "1") == "1"
# 자율 웹지식 스캔 — 농장주 지시 없이 주기적으로 외부정보 수집·저장(자율 지식성장)
AGENT_WEB_SCAN_MIN       = int(os.getenv("AGENT_WEB_SCAN_MIN", "1440"))   # 기본 일 1회
AGENT_BOOTSTRAP_WEB_SCAN = os.getenv("AGENT_BOOTSTRAP_WEB_SCAN", "1") == "1"
# 지역 정보 자율 수집 — 농장 소재지 특산물·뉴스·지역정보를 주 2회 한가한 시간에 스캔
AGENT_REGION_SCAN_MIN       = int(os.getenv("AGENT_REGION_SCAN_MIN", "1440"))   # 일단위 due(요일게이트로 주2회)
AGENT_BOOTSTRAP_REGION_SCAN = os.getenv("AGENT_BOOTSTRAP_REGION_SCAN", "1") == "1"
AGENT_OFFPEAK_HOURS = set(int(x) for x in os.getenv("AGENT_OFFPEAK_HOURS", "1,2,3,4").split(",") if x.strip().isdigit())
# 지역 스캔 실행 요일(weekday 0=월) — 기본 월(0)·목(3) = 주 2회
AGENT_REGION_SCAN_DAYS = set(int(x) for x in os.getenv("AGENT_REGION_SCAN_DAYS", "0,3").split(",") if x.strip().isdigit())
# 국내주식 마감스캔 — 평일 장 마감(15:30) 후 공시 이벤트 스캔·후보선정·승인요청.
#   ⛔ bootstrap 기본 OFF — Phase 2(모의주문·리스크한도) 전엔 수동/on-demand. 준비되면 =1 로 ON.
AGENT_TRADE_SCAN_MIN       = int(os.getenv("AGENT_TRADE_SCAN_MIN", "1440"))     # 일단위 due(요일·시각 게이트)
AGENT_BOOTSTRAP_TRADE_SCAN = os.getenv("AGENT_BOOTSTRAP_TRADE_SCAN", "0") == "1"
AGENT_TRADE_SCAN_DAYS  = set(int(x) for x in os.getenv("AGENT_TRADE_SCAN_DAYS", "0,1,2,3,4").split(",") if x.strip().isdigit())
AGENT_TRADE_SCAN_HOURS = set(int(x) for x in os.getenv("AGENT_TRADE_SCAN_HOURS", "15,16").split(",") if x.strip().isdigit())

_STOP = False


def _on_signal(signum, frame):
    """SIGTERM/SIGINT 우아한 종료."""
    global _STOP
    logger.info(f"[Agent Scheduler] signal {signum} 수신 — 다음 cycle 후 종료")
    _STOP = True


# ────────────────────────────────────────────────────────────────────
# 다음 cycle 시각 — 정각 기준 AGENT_INTERVAL_MIN 단위로 정렬.
# 예: 현재 12:17 / 30분 주기 → 12:30. 현재 12:31 → 13:00.
# ────────────────────────────────────────────────────────────────────
def _next_interval_dt(now: datetime = None) -> datetime:
    now = now or datetime.now()
    # 현재 분을 AGENT_INTERVAL_MIN 으로 나눠 다음 boundary 찾기
    minutes = (now.minute // AGENT_INTERVAL_MIN + 1) * AGENT_INTERVAL_MIN
    if minutes >= 60:
        # 다음 시간 정각
        nxt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        nxt = now.replace(minute=minutes, second=0, microsecond=0)
    return nxt


# ────────────────────────────────────────────────────────────────────
# 기본 작업 지시문 — 자율 환경제어 사이클.
# ────────────────────────────────────────────────────────────────────
def _build_default_task(farm_id: int) -> str:
    now = datetime.now().strftime("%H:%M")
    return (
        f"농장 {farm_id} 자율 환경 제어 사이클 ({now} 기준).\n"
        f"각 호기의 센서값(수온/내부온도/CO2/습도)을 읽고 임계값과 비교하라.\n"
        f"임계 초과 호기는 set_relay 로 릴레이를 직접 제어하고 send_user_alert 로 알려라.\n"
        f"모든 호기 순찰 후 제어 조치 결과를 최종 보고하라."
    )


# 자율 웹지식 스캔 task — 외부 키워드 포함 → _is_external_info_task 매칭 →
# CTRL_AGENT_EXTERNAL 프롬프트로 라우팅(제어 아닌 외부수집·저장 흐름).
def _build_web_scan_task(farm_id: int) -> str:
    return (
        f"[외부 지식 자율 수집] 웹 검색과 전문 검색(논문 paper-search, 지역/시세 naver-search, 기상)으로 "
        f"상황버섯(Phellinus linteus) 재배기술·생육관리·병해충·기상특보 등 농장 {farm_id} 운영에 도움될 "
        f"최신 정보를 조사하라. 저장가치 3조건(재배 실질도움·지속 재사용가치·기존에 없음)을 충족하는 새 정보는 "
        f"save_knowledge 로 저장(출처 URL 포함)하고, 핵심을 send_user_alert 로 알려라. 유용한 새 정보 없으면 통지 말라."
    )


# 농장 소재지 주소(farm_m_info.addr) 조회 — 지역 스캔용.
def _region_addr(farm_id: int) -> str:
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            r = d.fetch_one("SELECT addr FROM farm_m_info WHERE farm_id=%s", (farm_id,))
        return (dict(r).get("addr") or "").strip() if r else ""
    except Exception:
        return ""


# 지역 정보 자율 수집 task — 외부 키워드 포함 → CTRL_AGENT_EXTERNAL 라우팅.
def _build_region_scan_task(farm_id: int) -> str:
    addr = _region_addr(farm_id) or "농장 소재 지역"
    return (
        f"[지역 정보 자율 수집] 우리 농장은 '{addr}' 에 있다. 이 주소의 시·도 / 시·군·구 / 읍·면·동 각 단위로 "
        f"웹 검색(search_web)과 지역 검색(mcp_call server='naver-search')을 하여 특산물, 새로 떠오르는 지역 뉴스, "
        f"축제·행사, 명소·맛집, 지역 소식 등 다양한 분야의 흥미로운 정보를 조사하라. 그중 농장주와의 대화에 응용할 "
        f"가치가 있는 새 정보는 save_knowledge(category='지역정보'|'특산물'|'뉴스', source_url 포함)로 요약 저장하고, "
        f"핵심을 send_user_alert 로 간단히 알려라. 유용한 새 정보 없으면 통지 말라."
    )


# 지역 스캔 실행 창(window) = 지정 요일(AGENT_REGION_SCAN_DAYS, 0=월) + 한가한 시간(AGENT_OFFPEAK_HOURS).
# interval_min 캡(≤1440)이라 일단위 due + 요일·시간 게이트로 "주 2회 한가한 시간"을 구현한다.
def _in_scan_window(now: datetime = None) -> bool:
    now = now or datetime.now()
    return now.weekday() in AGENT_REGION_SCAN_DAYS and now.hour in AGENT_OFFPEAK_HOURS


def _next_region_window(now: datetime = None) -> datetime:
    now = now or datetime.now()
    start = min(AGENT_OFFPEAK_HOURS) if AGENT_OFFPEAK_HOURS else 3
    days = AGENT_REGION_SCAN_DAYS or {0, 3}
    for add in range(0, 9):
        cand = (now + timedelta(days=add)).replace(hour=start, minute=0, second=0, microsecond=0)
        if cand.weekday() in days and cand > now:
            return cand
    return now.replace(hour=start, minute=0, second=0, microsecond=0) + timedelta(days=1)


# 국내주식 마감스캔 task — 트레이딩 키워드 포함 → CTRL_AGENT_TRADE 라우팅.
def _build_trade_scan_task(farm_id: int) -> str:
    return (
        "[국내주식 자동매매 마감스캔] 장이 마감되었다. 오늘 공시(주요사항보고 등) 이벤트를 "
        "scan_stock_events 로 스캔해, 호재성 이벤트(자기주식취득·합병·공급계약·실적개선 등) 중심으로 "
        "내일 매매할 후보 3~7종목을 선정하라. 필요하면 mcp_call 로 종목 뉴스(naver-search)·시세(kis-trading)를 "
        "확인해 각 종목의 매수가·목표가·손절가·기대수익률·확신도를 산정하고 save_trade_candidate 로 저장한 뒤, "
        "request_trade_approval 로 관리자 승인요청하고 최종 보고하라. ⛔ 실제 주문은 하지 말 것(모의·승인 게이트)."
    )


# 마감스캔 실행 창 = 평일(AGENT_TRADE_SCAN_DAYS) + 장 마감 시간대(AGENT_TRADE_SCAN_HOURS).
def _in_trade_window(now: datetime = None) -> bool:
    now = now or datetime.now()
    return now.weekday() in AGENT_TRADE_SCAN_DAYS and now.hour in AGENT_TRADE_SCAN_HOURS


def _next_trade_window(now: datetime = None) -> datetime:
    now = now or datetime.now()
    start = min(AGENT_TRADE_SCAN_HOURS) if AGENT_TRADE_SCAN_HOURS else 15
    days = AGENT_TRADE_SCAN_DAYS or {0, 1, 2, 3, 4}
    for add in range(0, 9):
        cand = (now + timedelta(days=add)).replace(hour=start, minute=40, second=0, microsecond=0)
        if cand.weekday() in days and cand > now:
            return cand
    return now.replace(hour=start, minute=40, second=0, microsecond=0) + timedelta(days=1)


_OFFPEAK_INTENTS = {"__default_region_scan__", "__default_trade_scan__"}
# intent → (실행창 판정, 다음창 계산). 창 밖 due 면 다음 창으로 연기.
_WINDOW_GATES = {
    "__default_region_scan__": (_in_scan_window, _next_region_window),
    "__default_trade_scan__":  (_in_trade_window, _next_trade_window),
}


def _defer_if_not_scan_window(sub: dict) -> bool:
    """스캔이 실행 창(요일+시간) 밖에서 due 면 다음 창으로 연기(실행 skip). True=연기."""
    gate = _WINDOW_GATES.get(sub.get("intent"))
    if not gate:
        return False
    in_window, next_window = gate
    if in_window():
        return False
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        with conn.cursor() as cur:
            cur.execute("UPDATE agent_subscriptions SET next_run_at=%s WHERE id=%s",
                        (next_window(), int(sub["id"])))
            conn.commit()
        db._putconn(conn)
    except Exception as e:
        logger.debug(f"[Agent Scheduler] 스캔 연기 실패: {e}")
    return True


# ────────────────────────────────────────────────────────────────────
# 한 cycle — 모든 농장에 대해 agent 실행. 결과는 자동 DB 영속.
# ────────────────────────────────────────────────────────────────────
def _run_cycle():
    cycle_start = time.time()
    logger.info(f"[Agent Scheduler] === cycle 시작 {datetime.now():%Y-%m-%d %H:%M:%S} ===")

    for farm_id in AGENT_FARM_IDS:
        if _STOP:
            logger.info("[Agent Scheduler] 종료 신호 — cycle 중단")
            return
        task = _build_default_task(farm_id)
        try:
            result = run_agent(task=task, farm_id=farm_id, trigger_type="schedule")
            ok = result.get("success")
            duration = result.get("duration_sec")
            log_id = result.get("log_id")
            final_preview = (result.get("final") or "")[:120]
            logger.info(
                f"[Agent Scheduler] farm={farm_id} 완료 success={ok} duration={duration}s "
                f"log_id={log_id} | {final_preview}"
            )
        except Exception as e:
            logger.warning(f"[Agent Scheduler] farm={farm_id} 예외: {e}")

    cycle_duration = time.time() - cycle_start
    logger.info(f"[Agent Scheduler] === cycle 완료 ({cycle_duration:.1f}s) ===")


# ════════════════════════════════════════════════════════════════════
# Subscriptions polling — 사용자 채팅 등록 반복 task
# ════════════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────────────
# default subscription 부트스트랩 — 30분 cron 기본 사이클 보장.
# AGENT_FARM_IDS 각 농장에 대해 *시스템 default* subscription 이 없으면 생성.
# 표시자: user_id=NULL, intent='__default_cron__'.
# ────────────────────────────────────────────────────────────────────
def _bootstrap_default_subscriptions():
    if not AGENT_BOOTSTRAP_DEFAULT:
        return
    try:
        from agri_ai_core.src.postgresql.connection import db
    except Exception:
        return
    conn = db._getconn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            for farm_id in AGENT_FARM_IDS:
                cur.execute(
                    "SELECT id FROM agent_subscriptions "
                    "WHERE farm_id=%s AND user_id IS NULL "
                    "  AND intent='__default_cron__' AND active=TRUE LIMIT 1",
                    (farm_id,))
                row = cur.fetchone()
                if row:
                    continue
                task = _build_default_task(farm_id)
                cur.execute(
                    "INSERT INTO agent_subscriptions "
                    "(user_id, farm_id, house_id, interval_min, task, intent, next_run_at) "
                    "VALUES (NULL, %s, NULL, %s, %s, '__default_cron__', NOW())",
                    (farm_id, AGENT_INTERVAL_MIN, task))
                logger.info(f"[Agent Scheduler] default subscription 생성: farm={farm_id} interval={AGENT_INTERVAL_MIN}분")
            if AGENT_BOOTSTRAP_WEB_SCAN:
                for farm_id in AGENT_FARM_IDS:
                    cur.execute(
                        "SELECT id FROM agent_subscriptions "
                        "WHERE farm_id=%s AND user_id IS NULL "
                        "  AND intent='__default_web_scan__' AND active=TRUE LIMIT 1",
                        (farm_id,))
                    if cur.fetchone():
                        continue
                    cur.execute(
                        "INSERT INTO agent_subscriptions "
                        "(user_id, farm_id, house_id, interval_min, task, intent, next_run_at) "
                        "VALUES (NULL, %s, NULL, %s, %s, '__default_web_scan__', NOW())",
                        (farm_id, AGENT_WEB_SCAN_MIN, _build_web_scan_task(farm_id)))
                    logger.info(f"[Agent Scheduler] web_scan subscription 생성: farm={farm_id} interval={AGENT_WEB_SCAN_MIN}분")
            if AGENT_BOOTSTRAP_REGION_SCAN:
                for farm_id in AGENT_FARM_IDS:
                    cur.execute(
                        "SELECT id FROM agent_subscriptions "
                        "WHERE farm_id=%s AND user_id IS NULL "
                        "  AND intent='__default_region_scan__' AND active=TRUE LIMIT 1",
                        (farm_id,))
                    if cur.fetchone():
                        continue
                    cur.execute(
                        "INSERT INTO agent_subscriptions "
                        "(user_id, farm_id, house_id, interval_min, task, intent, next_run_at) "
                        "VALUES (NULL, %s, NULL, %s, %s, '__default_region_scan__', %s)",
                        (farm_id, AGENT_REGION_SCAN_MIN, _build_region_scan_task(farm_id), _next_region_window()))
                    logger.info(f"[Agent Scheduler] region_scan subscription 생성: farm={farm_id} interval={AGENT_REGION_SCAN_MIN}분 (off-peak)")
            if AGENT_BOOTSTRAP_TRADE_SCAN:
                for farm_id in AGENT_FARM_IDS:
                    cur.execute(
                        "SELECT id FROM agent_subscriptions "
                        "WHERE farm_id=%s AND user_id IS NULL "
                        "  AND intent='__default_trade_scan__' AND active=TRUE LIMIT 1",
                        (farm_id,))
                    if cur.fetchone():
                        continue
                    cur.execute(
                        "INSERT INTO agent_subscriptions "
                        "(user_id, farm_id, house_id, interval_min, task, intent, next_run_at) "
                        "VALUES (NULL, %s, NULL, %s, %s, '__default_trade_scan__', %s)",
                        (farm_id, AGENT_TRADE_SCAN_MIN, _build_trade_scan_task(farm_id), _next_trade_window()))
                    logger.info(f"[Agent Scheduler] trade_scan subscription 생성: farm={farm_id} (평일 장마감)")
            conn.commit()
    except Exception as e:
        logger.warning(f"[Agent Scheduler] bootstrap 실패: {e}")
        try: conn.rollback()
        except Exception: pass
    finally:
        try: db._putconn(conn)
        except Exception: pass


# ────────────────────────────────────────────────────────────────────
# polling: active + next_run_at <= NOW() 인 row 잡아옴.
# SKIP LOCKED 로 race-free (다중 scheduler 실행 시도 시).
# ────────────────────────────────────────────────────────────────────
def _claim_due_subscriptions(limit: int = 5):
    try:
        from agri_ai_core.src.postgresql.connection import db
        from psycopg2.extras import RealDictCursor
    except Exception:
        return []
    conn = db._getconn()
    if conn is None:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, user_id, farm_id, house_id, interval_min, task, intent "
                "FROM agent_subscriptions "
                "WHERE active=TRUE AND next_run_at <= NOW() "
                "ORDER BY next_run_at "
                "FOR UPDATE SKIP LOCKED LIMIT %s",
                (limit,))
            rows = cur.fetchall()
            conn.commit()
        return [dict(r) for r in rows] if rows else []
    except Exception as e:
        logger.warning(f"[Agent Scheduler] _claim_due_subscriptions 실패: {e}")
        try: conn.rollback()
        except Exception: pass
        return []
    finally:
        try: db._putconn(conn)
        except Exception: pass


_NCM_MIN = 3   # next_check_minutes 하한 (분)
_NCM_MAX = 60  # next_check_minutes 상한 (분)


def _advance_subscription(sub_id: int, interval_min: int,
                          override_minutes: int = None):
    """사이클 끝나면 next_run_at 갱신, total_runs += 1.

    override_minutes: LLM 이 반환한 next_check_minutes.
      - 있으면 NOW() + override_minutes (동적 재스케줄)
      - 없으면 GREATEST(NOW(), next_run_at) + interval_min (경계 정렬)
    override_minutes 는 _NCM_MIN~_NCM_MAX 로 클램프된 값이어야 함.
    """
    if override_minutes is not None:
        try:
            actual = max(_NCM_MIN, min(_NCM_MAX, int(override_minutes)))
        except (TypeError, ValueError):
            actual = interval_min
            logger.warning(f"[Agent Scheduler] override_minutes 변환 실패({override_minutes!r}) → 기본값 {actual}분")
    else:
        actual = None  # SQL 분기용

    try:
        from agri_ai_core.src.postgresql.connection import db
    except Exception:
        return
    conn = db._getconn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            if actual is not None:
                # 동적 재스케줄 — 지금 기준으로 actual분 후
                cur.execute(
                    "UPDATE agent_subscriptions "
                    "SET last_run_at = NOW(), "
                    "    next_run_at = NOW() + (%s || ' minutes')::interval, "
                    "    total_runs = total_runs + 1 "
                    "WHERE id=%s",
                    (str(actual), sub_id))
                logger.info(
                    f"[Agent Scheduler] sub #{sub_id} 동적 재스케줄: {actual}분 후 "
                    f"(LLM 지정={override_minutes}, 기본={interval_min})"
                )
            else:
                # boundary-aligned 재스케줄
                cur.execute(
                    "UPDATE agent_subscriptions "
                    "SET last_run_at = NOW(), "
                    "    next_run_at = GREATEST(NOW(), next_run_at) + (%s || ' minutes')::interval, "
                    "    total_runs = total_runs + 1 "
                    "WHERE id=%s",
                    (str(interval_min), sub_id))
            conn.commit()
    except Exception as e:
        logger.warning(f"[Agent Scheduler] _advance_subscription({sub_id}) 실패: {e}")
        try: conn.rollback()
        except Exception: pass
    finally:
        try: db._putconn(conn)
        except Exception: pass


def _save_alert(user_id, sub_id, log_id, level, title, body):
    """agent_user_alerts 에 결과 영속. 채팅 프론트엔드가 폴링/SSE 로 받음."""
    if not body:
        return
    try:
        from agri_ai_core.src.postgresql.connection import db
    except Exception:
        return
    conn = db._getconn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_user_alerts "
                "(user_id, subscription_id, agent_log_id, level, title, body) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, sub_id, log_id, level, (title or "")[:200], body))
            conn.commit()
        # 카카오 '나에게 보내기' 실시간 푸시 (best-effort — 미연동 시 no-op).
        # 구독별 카카오 쿨다운: 제어·채팅 알림(위 INSERT)은 매번 유지하되, 카카오만
        # alert_cooldown_min 안에는 발송 억제 — "제어는 계속, 카카오만 N분 간격" 요구 대응.
        try:
            _push_kakao = True
            if sub_id:
                with conn.cursor() as _cc:
                    _cc.execute("SELECT alert_cooldown_min, last_kakao_at "
                                "FROM agent_subscriptions WHERE id=%s", (int(sub_id),))
                    _cr = _cc.fetchone()
                if _cr and _cr[0] and int(_cr[0]) > 0 and _cr[1] is not None:
                    from datetime import datetime, timedelta
                    if datetime.now() - _cr[1] < timedelta(minutes=int(_cr[0])):
                        _push_kakao = False
                        logger.info(f"[Agent Scheduler] 카카오 쿨다운 — sub={sub_id} "
                                    f"{_cr[0]}분 이내 재발송 억제")
            if _push_kakao:
                from agri_ai_core.src.ai.kakao_notify import push_alert
                push_alert(level, title, body)
                if sub_id:
                    with conn.cursor() as _uc:
                        _uc.execute("UPDATE agent_subscriptions SET last_kakao_at=NOW() "
                                    "WHERE id=%s", (int(sub_id),))
                        conn.commit()
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"[Agent Scheduler] _save_alert 실패: {e}")
        try: conn.rollback()
        except Exception: pass
    finally:
        try: db._putconn(conn)
        except Exception: pass


def _fmt_value(value: Any, suffix: str = "") -> str:
    if value is None:
        return "-"
    try:
        if isinstance(value, float):
            return f"{value:.1f}{suffix}"
        return f"{float(value):.1f}{suffix}"
    except (TypeError, ValueError):
        return f"{value}{suffix}"


def _build_minimal_fallback_report(sub: dict, result: Dict[str, Any]) -> str:
    """Build a deterministic status report when the LLM did not finish.

    This is a last-resort user-facing report.  It must not decide or execute
    relay control because the LLM judgment failed.
    """
    farm_id = int(sub.get("farm_id") or 1)
    reason = result.get("reason") or "LLM 응답 실패"
    try:
        from agri_ai_core.src.ai.tools_agent_read import get_all_house_status
        status = get_all_house_status(farm=farm_id, minutes=10, decision_hours=2)
    except Exception as e:
        status = {"success": False, "error": str(e)}

    lines = [
        "[LLM Agent 최소 상태 보고]",
        f"- 구독 ID: {sub.get('id')}",
        f"- 농장: {farm_id}",
        f"- LLM 실패 원인: {reason}",
        "- 성격: LLM 판단 실패 시 남기는 최소 센서/릴레이 스냅샷입니다.",
        "- 제한: 이 보고는 릴레이 제어 판단을 대체하지 않으며, 임의 제어를 수행하지 않았습니다.",
    ]

    if not status.get("success"):
        lines.append(f"- 상태 조회 실패: {status.get('error') or status.get('message') or 'unknown'}")
        return "\n".join(lines)

    houses = status.get("houses") or []
    lines.append(f"- 조회 범위: 최근 {status.get('minutes', 10)}분, 재배사 {len(houses)}개")
    for house in houses:
        sensor = house.get("sensor_current") or {}
        relay = house.get("relay") or {}
        decision = house.get("latest_decision") or {}
        on_list = relay.get("semantic_on") or []
        on_text = ", ".join(on_list) if on_list else "없음"
        lines.append(
            f"- {house.get('house')}호기({sensor.get('at') or '-'}) "
            f"온도 {_fmt_value(sensor.get('indoor_temp'), '℃')} / "
            f"습도 {_fmt_value(sensor.get('humidity'), '%')} / "
            f"CO2 {_fmt_value(sensor.get('co2'), 'ppm')} / "
            f"수온 {_fmt_value(sensor.get('water_temp'), '℃')} / "
            f"릴레이 ON [{on_text}]"
        )
        if decision.get("at"):
            lines.append(
                f"  · 최근 LLM 판단 {decision.get('at')}: "
                f"action={decision.get('action') or '-'}, "
                f"circulation={decision.get('circulation') or '-'}, "
                f"reason={(decision.get('reason') or '-')[:120]}"
            )
    return "\n".join(lines)


def _is_quiet_final(final: str) -> bool:
    # 조건부 알림 프로토콜 판정 — final 이 NO_ALERT 로 시작하면 "정상, 알림 불요".
    # 마커는 구독 task 의 [보고 규칙] 으로 agent 에게 지시되는 결정론적 약속이다.
    return bool(final) and final.strip().upper().startswith("NO_ALERT")


def _run_subscription(sub: dict):
    """단일 subscription 실행 — run_agent 호출 + advance + alert."""
    sub_id = int(sub["id"])
    farm_id = int(sub["farm_id"]) if sub.get("farm_id") else 1
    task = sub["task"]
    user_id = sub.get("user_id")
    interval_min = int(sub.get("interval_min") or AGENT_INTERVAL_MIN)
    is_default = (sub.get("intent") == "__default_cron__")

    if _defer_if_not_scan_window(sub):
        logger.info(f"[Agent Scheduler] #{sub_id} 지역스캔 대기 — {_next_region_window():%m-%d(%a) %H:%M} 로 연기")
        return
    logger.info(
        f"[Agent Scheduler] subscription #{sub_id} 실행 farm={farm_id} "
        f"user={user_id or '-'} interval={interval_min}분 default={is_default}"
    )
    next_min = None  # LLM 동적 재스케줄 값
    result: Dict[str, Any] = {"success": False, "reason": "not_started"}
    try:
        result = run_agent(task=task, farm_id=farm_id, trigger_type="subscription")
        ok = result.get("success")
        log_id = result.get("log_id")
        final = result.get("final") or ""
        next_min = result.get("next_check_minutes")  # None 이면 기본 interval 유지
        if not is_default and not final:
            final = _build_minimal_fallback_report(sub, result)
            result["fallback_report"] = True
            logger.warning(f"[Agent Scheduler] sub #{sub_id} LLM final 없음 → 최소 상태 보고 fallback 생성")
        logger.info(
            f"[Agent Scheduler] sub #{sub_id} 완료 success={ok} "
            f"log_id={log_id} next_check={next_min}min | {final[:100]}"
        )
        # 사용자 등록 subscription 만 alert 영속 (default 는 운영 로그/DB 이력 충분).
        # user_id 가 없는 채팅 등록은 NULL 사용자 공통 알림으로 저장해 보고 유실을 막는다.
        # 조건부 알림 프로토콜: "특이사항 있을 때만" 구독은 task 에
        # NO_ALERT 규칙이 포함되며, agent 가 정상 상태를 NO_ALERT 로 보고하면
        # 알림 저장·카카오 푸시를 생략한다 (사이클 이력 로그는 유지).
        if _is_quiet_final(final):
            logger.info(f"[Agent Scheduler] sub #{sub_id} 정상(NO_ALERT) — 알림 생략")
        elif not is_default and final:
            level = "info" if ok else "warning"
            title = f"농장 {farm_id} Agent 결과" if ok else f"농장 {farm_id} Agent 최소 상태 보고"
            _save_alert(user_id, sub_id, log_id, level, title, final)
    except Exception as e:
        logger.warning(f"[Agent Scheduler] sub #{sub_id} 예외: {e}")
        if not is_default:
            result = {"success": False, "reason": f"scheduler exception: {e}"}
            final = _build_minimal_fallback_report(sub, result)
            _save_alert(user_id, sub_id, None, "warning", f"농장 {farm_id} Agent 최소 상태 보고", final)
    finally:
        # 사용자 등록 구독은 사용자가 명시한 주기(=관리자 지시)가 LLM 의
        # next_check 제안보다 우선한다. 동적 재스케줄(LLM 제안)은 시스템 기본
        # 사이클(__default_cron__)에만 허용.
        _advance_subscription(sub_id, interval_min,
                              override_minutes=next_min if is_default else None)


def _run_due_subscriptions():
    """매 polling 사이클: due subscription 모두 처리."""
    rows = _claim_due_subscriptions(limit=5)
    if not rows:
        return
    logger.info(f"[Agent Scheduler] due subscriptions = {len(rows)}건")
    for row in rows:
        if _STOP:
            return
        _run_subscription(row)


# ────────────────────────────────────────────────────────────────────
# 메인 — 매 분 polling. subscriptions 처리 + (option) 30분 boundary cron.
# 30분 cron 동작은 default subscription 으로 유지 (_bootstrap_default).
# ────────────────────────────────────────────────────────────────────
def main():
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT,  _on_signal)

    logger.info(
        f"[Agent Scheduler] 시작 interval={AGENT_INTERVAL_MIN}분 (default cron) "
        f"farms={AGENT_FARM_IDS} sub_poll={AGENT_SUB_POLL_SEC}s "
        f"initial_delay={AGENT_INITIAL_DELAY}s"
    )

    # 시작 직후 즉시 사이클 도는 것 방지 (Ollama 준비 대기)
    if AGENT_INITIAL_DELAY > 0:
        for _ in range(AGENT_INITIAL_DELAY):
            if _STOP:
                return
            time.sleep(1)

    # default subscription 부트스트랩 (30분 cron 기본 사이클)
    _bootstrap_default_subscriptions()

    # 메인 loop — 매 AGENT_SUB_POLL_SEC 초마다 due subscriptions 처리
    while not _STOP:
        try:
            _run_due_subscriptions()
        except Exception as e:
            logger.error(f"[Agent Scheduler] polling 사이클 예외: {e}")

        # 1초 단위 sleep + 종료 신호 체크 (즉시 반응)
        slept = 0
        while slept < AGENT_SUB_POLL_SEC and not _STOP:
            time.sleep(1)
            slept += 1

    logger.info("[Agent Scheduler] 정상 종료")


if __name__ == "__main__":
    sys.exit(main() or 0)
