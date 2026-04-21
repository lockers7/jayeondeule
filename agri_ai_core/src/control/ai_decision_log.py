# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — 자기결정 이력 모듈 (M6)
# [2026-04-28 신규] LLM 의 모든 의사결정을 ai_decision_log 테이블에 기록.
# 다음 호출 시 직전 N건을 user prompt 에 주입 → oscillation 방지·일관성 향상.
# 사용자 피드백(좋아요/싫어요)은 별도 모듈 M15 에서 update_feedback() 호출.
#
# 호출 룰:
#   • control_ai_environment 에서만 record_decision / format_recent_block 호출.
#   • 동급 control 모듈 import 금지 — 본 모듈은 postgresql 만 의존.
#   • 테이블 부재 시 자동 생성(IF NOT EXISTS) — 첫 실행 안전.
# --->
# ensure_table:          최초 1회 테이블 생성 시도 (idempotent)
# record_decision:       의사결정 1건 INSERT → id 반환
# get_recent:            직전 N건 조회 list[dict]
# format_recent_block:   user prompt 한 블록 텍스트로 변환
# update_feedback:       사용자 피드백 라벨 갱신 (M15 에서 호출)
# ══════════════════════════════════════════════════════════════════════════════
import json
import threading
from typing import Any, Dict, List, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
import agri_ai_core.src.postgresql.queries as dbQry

logger = setup_logger(__name__)

_DEFAULT_RECENT_N = 5
_table_ready_lock = threading.Lock()
_table_ready = False


# ────────────────────────────────────────────────────────────────────
# ai_decision_log 테이블 생성 시도(idempotent).
# 한 프로세스에서 1회만 실제 SQL 실행 — 첫 호출 안전.
# ────────────────────────────────────────────────────────────────────
def ensure_table() -> bool:
    global _table_ready
    if _table_ready:
        return True
    with _table_ready_lock:
        if _table_ready:
            return True
        try:
            with db_session() as database:
                database.execute_query(dbQry.CREATE_AI_DECISION_LOG_TABLE, ())
            _table_ready = True
            logger.info("[AI결정이력] ai_decision_log 테이블 보장 완료(IF NOT EXISTS)")
            return True
        except Exception as e:
            logger.warning(f"[AI결정이력] 테이블 보장 실패: {e}")
            return False


# ────────────────────────────────────────────────────────────────────
# LLM 의사결정 1건 INSERT → id 반환. 실패해도 LLM 흐름 보존(None 반환).
# [버그수정 · 2026-05-01] 기존 db.fetch_one(INSERT...RETURNING) 은 connection.py 가
#   commit 호출을 안 하므로 트랜잭션 종료 시 자동 롤백 — sequence 만 진행되고
#   row 가 사라져 ai_decision_log 가 항상 비어 있던 원인. ai_camera_archive 와
#   동일한 _getconn() 직접 패턴(execute + fetchone + commit)으로 교체.
# ────────────────────────────────────────────────────────────────────
def record_decision(farm_id, house_id, *,
                    growth_stage: str,
                    action: str,
                    circulation: Optional[str],
                    water_heater: Optional[bool],
                    fog_occurs: Optional[bool],
                    reason: str,
                    sensor_snapshot: Optional[Dict[str, Any]] = None) -> Optional[int]:
    if not ensure_table():
        return None

    from psycopg2.extras import RealDictCursor
    from agri_ai_core.src.postgresql.connection import db

    snap_json = json.dumps(sensor_snapshot or {}, ensure_ascii=False, default=str)
    vals = (
        int(farm_id), int(house_id),
        str(growth_stage or ''),
        str(action or 'unknown'),
        str(circulation) if circulation else None,
        bool(water_heater) if water_heater is not None else None,
        bool(fog_occurs) if fog_occurs is not None else None,
        str(reason or '')[:256],
        snap_json,
    )

    conn = db._getconn()
    if conn is None:
        logger.warning(f"[AI결정이력] DB 연결 실패 farm={farm_id} house={house_id}")
        return None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(dbQry.INSERT_AI_DECISION_LOG, vals)
            row = cur.fetchone()
            conn.commit()
        new_id = int(row['id']) if row and 'id' in row else None
        if new_id is not None:
            logger.info(
                f"[AI결정이력] 기록 farm={farm_id} house={house_id} id={new_id} "
                f"action={action} circ={circulation} 히터={water_heater} 포그={fog_occurs}"
            )
        return new_id
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"[AI결정이력] 기록 실패 farm={farm_id} house={house_id}: {e}")
        return None
    finally:
        db._putconn(conn)


# ────────────────────────────────────────────────────────────────────
# 직전 N건 LLM 결정 이력 조회 list[dict]. 실패 시 [].
# ────────────────────────────────────────────────────────────────────
def get_recent(farm_id, house_id, limit: int = _DEFAULT_RECENT_N) -> List[Dict[str, Any]]:
    if not ensure_table():
        return []
    try:
        with db_session() as database:
            rows = database.fetch_all(
                query=dbQry.GET_RECENT_AI_DECISIONS_SQL,
                vals=(int(farm_id), int(house_id), int(limit)),
                as_dict=True,
            ) or []
        out = [dict(r) for r in rows]
        logger.info(f"[AI결정이력] 조회 farm={farm_id} house={house_id} → {len(out)}건")
        return out
    except Exception as e:
        logger.warning(f"[AI결정이력] 조회 실패 farm={farm_id} house={house_id}: {e}")
        return []


# ────────────────────────────────────────────────────────────────────
# 직전 결정 이력 list 를 user prompt 한 블록 텍스트로 변환. 빈 결과면 "".
# ────────────────────────────────────────────────────────────────────
def format_recent_block(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return ""
    lines = [f"[직전 LLM 결정 이력 — 최근 {len(rows)}건, 최신 → 과거 순]"]
    for r in rows:
        ts = (r.get('decided_at') or '')[:16]
        action = r.get('action') or '-'
        circ = r.get('circulation') or '-'
        wh = 'ON' if r.get('water_heater') else 'OFF'
        fg = 'ON' if r.get('fog_occurs') else 'OFF'
        reason = (r.get('reason') or '')[:30]
        fb = r.get('feedback') or ''
        fb_str = f" [피드백={fb}]" if fb else ""
        lines.append(
            f"  · {ts} · {action} · {circ} · 히터={wh} 포그={fg} · {reason}{fb_str}"
        )
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────
# [M15 사용] 사용자 피드백 라벨 갱신. feedback ∈ {'good','bad'}.
# ────────────────────────────────────────────────────────────────────
def update_feedback(decision_id: int, feedback: str) -> bool:
    if feedback not in ('good', 'bad'):
        return False
    if not ensure_table():
        return False
    try:
        with db_session() as database:
            database.execute_query(
                dbQry.UPDATE_AI_DECISION_FEEDBACK, (feedback, int(decision_id))
            )
        logger.info(f"[AI결정이력] 피드백 갱신 id={decision_id} feedback={feedback}")
        return True
    except Exception as e:
        logger.warning(f"[AI결정이력] 피드백 갱신 실패 id={decision_id}: {e}")
        return False
