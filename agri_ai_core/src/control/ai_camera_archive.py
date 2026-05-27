# ════════════════════════════════════════════════════════════════════
# 재배사 카메라 시간별 아카이브 — 캡처/저장/메타/Vision/RAG 통합 모듈.
# 매시간 정각에 task_scheduler 가 호출 → 각 활성 호기 캡처·분석·저장.
# 저장 경로:
#   파일      : UPLOAD_PATH/camera/<farm>/<house>/YYYYMMDD_HH.jpg
#   메타+분석 : PostgreSQL farmhouse_image_history
#   RAG 임베딩: ChromaDB farm_knowledge 컬렉션 (vision_summary 가 있을 때)
# 호출 룰:
#   • task_scheduler 의 cron 잡에서만 호출 (capture_all_active_houses).
#   • ai_control 은 본 모듈의 read_recent_history / format_image_history_block 만 사용.
#   • 동급 control 모듈 import 금지 (단방향 의존).
# --->
# _ensure_dir              : 저장 디렉토리 생성 (mkdir -p)
# _capture_path            : 캡처 시각 → 파일 경로 변환
# _save_image_file         : 바이트 데이터를 파일로 저장
# _insert_metadata         : farmhouse_image_history INSERT
# _embed_to_rag            : vision_summary 를 ChromaDB farm_knowledge 에 임베딩
# capture_one              : 단일 호기 1회 캡처+저장+분석+RAG 일괄 실행
# capture_all_active_houses: 활성 호기 전체 순회 (Scheduler cron 진입점)
# read_recent_history      : 최근 N시간 이력 조회 (LLM 컨텍스트용)
# format_image_history_block : LLM user prompt 한 블록 텍스트
# cleanup_old_images       : 보존정책 — N일 초과 이미지 파일+메타 삭제
# ════════════════════════════════════════════════════════════════════
import os
import time
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.control.ai_camera_vision import (
    capture_image,
    analyze_heuristics,
    analyze_vision_llm,
)

logger = setup_logger(__name__)

# 보존 정책 (기본 1년 — 환경변수로 조정 가능)
IMAGE_RETENTION_DAYS = int(os.getenv('CAMERA_IMAGE_RETENTION_DAYS', '365'))

# 저장 루트 — UPLOAD_PATH 환경변수 사용 (.env LOG_PATH 와 동급)
UPLOAD_BASE = os.getenv('UPLOAD_PATH', '/workspace/jayeondeule/upload')
CAMERA_ARCHIVE_ROOT = os.path.join(UPLOAD_BASE, 'camera')


# ────────────────────────────────────────────────────────────────────
# 디렉토리 mkdir -p (이미 존재 시 무시).
# ────────────────────────────────────────────────────────────────────
def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


# ────────────────────────────────────────────────────────────────────
# 캡처 시각 → 파일 절대경로 변환.
# 형식: <UPLOAD_BASE>/camera/<farm>/<house>/YYYYMMDD_HH.jpg
# ────────────────────────────────────────────────────────────────────
def _capture_path(farm_id, house_id, ts: datetime) -> str:
    dir_path = os.path.join(CAMERA_ARCHIVE_ROOT, str(farm_id), str(house_id))
    _ensure_dir(dir_path)
    fname = ts.strftime('%Y%m%d_%H') + '.jpg'
    return os.path.join(dir_path, fname)


# ────────────────────────────────────────────────────────────────────
# 바이트 데이터를 파일로 저장. 실패 시 예외 raise (호출자가 처리).
# ────────────────────────────────────────────────────────────────────
def _save_image_file(path: str, data: bytes) -> int:
    with open(path, 'wb') as f:
        f.write(data)
    return os.path.getsize(path)


# ────────────────────────────────────────────────────────────────────
# farmhouse_image_history INSERT — image_id 반환. 실패 시 None.
# ────────────────────────────────────────────────────────────────────
def _insert_metadata(farm_id, house_id, captured_at, file_path,
                     file_size, heur, vision_summary, vision_model) -> Optional[int]:
    # connection.py 의 _run_direct 는 commit=True 시 fetchone 결과를 반환하지 않음.
    # INSERT RETURNING 을 한 트랜잭션에서 처리하기 위해 conn 직접 사용.
    from psycopg2.extras import RealDictCursor
    from agri_ai_core.src.postgresql.connection import db

    sql = (
        "INSERT INTO farmhouse_image_history "
        "(farm_id, hous_id, captured_at, file_path, file_size, "
        " width, height, brightness, saturation, dark_ratio, bright_ratio, "
        " vision_summary, vision_model) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "RETURNING image_id"
    )
    vals = (
        int(farm_id), int(house_id), captured_at, file_path, file_size,
        (heur or {}).get('width'), (heur or {}).get('height'),
        (heur or {}).get('brightness'), (heur or {}).get('saturation'),
        (heur or {}).get('dark_ratio'), (heur or {}).get('bright_ratio'),
        vision_summary or None, vision_model or None,
    )
    conn = db._getconn()
    if conn is None:
        logger.error('[카메라아카이브] DB 연결 실패')
        return None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, vals)
            row = cur.fetchone()
            conn.commit()
            return int(row['image_id']) if row else None
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f'[카메라아카이브] DB INSERT 실패 farm={farm_id} house={house_id}: {e}')
        return None
    finally:
        db._putconn(conn)


# ────────────────────────────────────────────────────────────────────
# vision_summary 를 ChromaDB farm_knowledge 에 임베딩 → 청크 ID 반환.
# 실패/미설치 시 None (RAG 미사용).
# ────────────────────────────────────────────────────────────────────
def _embed_to_rag(farm_id, house_id, captured_at, vision_summary, heur) -> Optional[str]:
    if not (vision_summary and vision_summary.strip()):
        return None
    try:
        from agri_ai_core.src.chroma.operations import add_document
    except Exception as e:
        logger.info(f'[카메라아카이브] ChromaDB 가용 안됨 — RAG 스킵: {e}')
        return None

    chunk_id = f'cam_{farm_id}_{house_id}_{captured_at.strftime("%Y%m%d_%H%M%S")}'
    text = (
        f'[재배사 영상 {captured_at.strftime("%Y-%m-%d %H시")}] '
        f'농장{farm_id} 재배사{house_id} — '
        f'밝기 {(heur or {}).get("brightness", "-")} '
        f'어두움 {(heur or {}).get("dark_ratio", "-")} '
        f'밝음 {(heur or {}).get("bright_ratio", "-")}. '
        f'Vision LLM 묘사: {vision_summary.strip()}'
    )
    metadata = {
        'source': 'camera_vision',
        'farm_id': str(farm_id),
        'hous_id': str(house_id),
        'captured_at': captured_at.isoformat(),
    }
    try:
        ok = add_document(
            collection_name=os.getenv('COLLECTION_FARM_KNOWLEDGE', 'farm_knowledge'),
            doc_id=chunk_id,
            text=text,
            metadata=metadata,
        )
        if ok:
            logger.info(f'[카메라아카이브] RAG 임베딩 OK chunk={chunk_id}')
            return chunk_id
    except Exception as e:
        logger.warning(f'[카메라아카이브] RAG 임베딩 실패 {chunk_id}: {e}')
    return None


# ────────────────────────────────────────────────────────────────────
# 단일 호기 1회 캡처+저장+분석+RAG. 결과 dict 반환 (실패 시 None).
# ────────────────────────────────────────────────────────────────────
def capture_one(farm_id, house_id) -> Optional[Dict[str, Any]]:
    captured_at = datetime.now().replace(minute=0, second=0, microsecond=0)
    log_prefix = f'[카메라아카이브] {farm_id}-{house_id}'

    # 1) 캡처 (ai_camera_vision 의 4단계 우선순위 활용)
    image_bytes = capture_image(farm_id, house_id)
    if not image_bytes:
        logger.warning(f'{log_prefix} 캡처 실패 (영상 소스 없음)')
        return None

    # 2) 파일 저장
    path = _capture_path(farm_id, house_id, captured_at)
    try:
        size = _save_image_file(path, image_bytes)
    except Exception as e:
        logger.error(f'{log_prefix} 파일 저장 실패 path={path}: {e}')
        return None

    # 3) 휴리스틱 분석
    heur = analyze_heuristics(image_bytes) or {}

    # 4) Vision LLM 분석 (옵션 — get_vision_model() 빈 문자열 시 비활성).
    # 시간별 작업이라 timeout 넉넉히 — gemma3:27b 첫 호출 시 모델 로딩 + 추론 60~90s.
    # vision_model 라벨은 "DB 기록용" — get_vision_model()이 메인과 동조해 반환.
    from agri_ai_core.config import get_vision_model
    vision_timeout = int(os.getenv('VISION_TIMEOUT', '180'))
    vision_text = analyze_vision_llm(image_bytes, timeout=vision_timeout) or ''
    vision_model = get_vision_model() if vision_text else None

    # 5) DB 메타 INSERT
    image_id = _insert_metadata(
        farm_id, house_id, captured_at, path, size, heur, vision_text, vision_model,
    )

    # 6) RAG 임베딩 (옵션 — vision_summary 가 있을 때만)
    rag_chunk_id = _embed_to_rag(farm_id, house_id, captured_at, vision_text, heur)
    if rag_chunk_id and image_id:
        try:
            from agri_ai_core.src.postgresql.connection import db_session
            with db_session() as db:
                db.execute_query(
                    'UPDATE farmhouse_image_history SET rag_chunk_id=%s WHERE image_id=%s',
                    (rag_chunk_id, image_id),
                )
        except Exception as e:
            logger.warning(f'{log_prefix} rag_chunk_id 업데이트 실패: {e}')

    logger.info(
        f'{log_prefix} 아카이브 완료 image_id={image_id} size={size}B '
        f'밝기 {heur.get("brightness", "-")} 어두움 {heur.get("dark_ratio", "-")} '
        f'vision={"O" if vision_text else "X"}'
    )
    return {
        'farm_id': farm_id, 'hous_id': house_id, 'captured_at': captured_at,
        'image_id': image_id, 'file_path': path, 'file_size': size,
        'heuristics': heur, 'vision_summary': vision_text, 'rag_chunk_id': rag_chunk_id,
    }


# ────────────────────────────────────────────────────────────────────
# 활성 호기 전체 순회 — Scheduler cron 진입점 (매시간 정각).
# FARMHOUSE_M_INFO 의 활성 재배사(dlte_yn != 'Y' AND hous_id > 0) 만 대상.
# 호기별 환경변수 FARM_RPI_CAM_URL_<farm>_<house> 또는 FARM_USB_CAM_*
# 가 설정되어 있어야 캡처 시도 — 미설정 호기는 _capture 단에서 자동 스킵.
# ────────────────────────────────────────────────────────────────────
def capture_all_active_houses():
    from agri_ai_core.src.postgresql.connection import db_session

    sql = (
        "SELECT farm_id, hous_id FROM farmhouse_m_info "
        "WHERE COALESCE(dlte_yn,'N')<>'Y' AND hous_id > 0 AND farm_id > 0 "
        "ORDER BY farm_id, hous_id"
    )
    try:
        with db_session() as db:
            rows = db.fetch_all(query=sql, as_dict=True) or []
    except Exception as e:
        logger.error(f'[카메라아카이브] 활성 재배사 조회 실패: {e}')
        return {'success': 0, 'failed': 0, 'skipped': 0}

    success, failed, skipped = 0, 0, 0
    for r in rows:
        farm_id = r.get('farm_id')
        house_id = r.get('hous_id')
        # 환경변수 미설정 호기는 capture_image 가 None 반환 → skipped 카운트
        env_keys = (
            f'FARM_USB_CAM_{farm_id}_{house_id}',
            f'FARM_RPI_CAM_URL_{farm_id}_{house_id}',
            f'FARM_SSH_CAM_{farm_id}_{house_id}',
            f'FARM_STATIC_IMG_{farm_id}_{house_id}',
        )
        if not any(os.getenv(k) for k in env_keys):
            logger.info(f'[카메라아카이브] {farm_id}-{house_id} 영상 소스 미설정 — 스킵')
            skipped += 1
            continue

        res = capture_one(farm_id, house_id)
        if res:
            success += 1
        else:
            failed += 1

    logger.info(
        f'[카메라아카이브] 시간별 캡처 완료 success={success} failed={failed} skipped={skipped}'
    )
    return {'success': success, 'failed': failed, 'skipped': skipped}


# ────────────────────────────────────────────────────────────────────
# 최근 N시간 이력 조회 (기본 24시간) — LLM 컨텍스트용.
# 시간 역순으로 captured_at, 휴리스틱, vision_summary 반환.
# ────────────────────────────────────────────────────────────────────
def read_recent_history(farm_id, house_id, hours: int = 24) -> List[Dict[str, Any]]:
    from psycopg2.extras import RealDictCursor
    from agri_ai_core.src.postgresql.connection import db

    since = datetime.now() - timedelta(hours=hours)
    sql = (
        "SELECT captured_at, brightness, saturation, dark_ratio, bright_ratio, "
        "       vision_summary, file_size "
        "  FROM farmhouse_image_history "
        " WHERE farm_id=%s AND hous_id=%s AND captured_at >= %s "
        " ORDER BY captured_at DESC LIMIT 48"
    )
    conn = db._getconn()
    if conn is None:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (int(farm_id), int(house_id), since))
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.warning(f'[카메라아카이브] 이력 조회 실패 farm={farm_id} house={house_id}: {e}')
        return []
    finally:
        db._putconn(conn)


# ────────────────────────────────────────────────────────────────────
# 이력 dict 리스트 → LLM user prompt 한 블록 텍스트.
# 시간 추세(밝기·어두움)와 직전 vision_summary 를 결합해 짧게 노출.
# 빈 리스트면 빈 문자열 반환 (호출자 user prompt 에서 자동 생략).
# ────────────────────────────────────────────────────────────────────
def format_image_history_block(records: List[Dict[str, Any]]) -> str:
    if not records:
        return ''
    latest = records[0]
    cap = latest.get('captured_at')
    lines = [f'[재배사 카메라 24시간 이력 — 최근 {len(records)}건]']
    if cap:
        lines.append(
            f'  · 직전 캡처 ({cap.strftime("%Y-%m-%d %H시")}): '
            f'밝기 {latest.get("brightness")} '
            f'어두움 {latest.get("dark_ratio")} '
            f'밝음 {latest.get("bright_ratio")}'
        )
    # 24시간 추세 — 첫(현재)·마지막(24시간 전) 비교
    if len(records) >= 2:
        oldest = records[-1]
        try:
            delta_dark = float(latest.get('dark_ratio') or 0) - float(oldest.get('dark_ratio') or 0)
            delta_bright = float(latest.get('brightness') or 0) - float(oldest.get('brightness') or 0)
            lines.append(
                f'  · 24시간 추세: 어두움비율 {delta_dark:+.2f} '
                f'(자실체 형성 진행 가늠), 밝기 {delta_bright:+.0f} '
                f'(조명/광량 변화)'
            )
        except (TypeError, ValueError):
            pass
    # Vision LLM 묘사 (있을 때)
    vs = (latest.get('vision_summary') or '').strip()
    if vs:
        lines.append(f'  · Vision LLM 묘사: {vs[:480]}')
    lines.append(
        '  → 자실체 형성도·곰팡이·결로·조명 이상이 보이거나 추세 변화가 비정상이면 환경 결정에 반영.'
    )
    return '\n'.join(lines)


# ────────────────────────────────────────────────────────────────────
# 보존정책 — N일(기본 365) 초과 이미지 파일 + 메타 + RAG 청크 삭제.
# Scheduler cron 매일 새벽 4시 호출 권장.
# ────────────────────────────────────────────────────────────────────
def cleanup_old_images(days: int = None) -> Dict[str, int]:
    from agri_ai_core.src.postgresql.connection import db_session

    days = days if days is not None else IMAGE_RETENTION_DAYS
    cutoff = datetime.now() - timedelta(days=days)

    sql_select = (
        "SELECT image_id, file_path, rag_chunk_id "
        "  FROM farmhouse_image_history WHERE captured_at < %s"
    )
    deleted_files, deleted_rows, deleted_rag = 0, 0, 0
    try:
        with db_session() as db:
            old = db.fetch_all(query=sql_select, vals=(cutoff,)) or []

            # 파일 삭제
            for r in old:
                fp = r.get('file_path')
                if fp and os.path.isfile(fp):
                    try:
                        os.remove(fp)
                        deleted_files += 1
                    except OSError as e:
                        logger.warning(f'[카메라아카이브] 파일 삭제 실패 {fp}: {e}')

            # RAG 청크 삭제 (ChromaDB)
            try:
                from agri_ai_core.src.chroma.operations import delete_document
                rag_ids = [r['rag_chunk_id'] for r in old if r.get('rag_chunk_id')]
                if rag_ids:
                    delete_document(
                        collection_name=os.getenv('COLLECTION_FARM_KNOWLEDGE', 'farm_knowledge'),
                        ids=rag_ids,
                    )
                    deleted_rag = len(rag_ids)
            except Exception as e:
                logger.warning(f'[카메라아카이브] RAG 청크 정리 실패: {e}')

            # DB 메타 삭제
            db.execute_query(
                'DELETE FROM farmhouse_image_history WHERE captured_at < %s',
                (cutoff,),
            )
            deleted_rows = len(old)

        logger.info(
            f'[카메라아카이브] 보존정책 정리 ({days}일 초과) '
            f'파일={deleted_files} 메타={deleted_rows} RAG={deleted_rag}'
        )
    except Exception as e:
        logger.error(f'[카메라아카이브] 보존정책 정리 실패: {e}\n{traceback.format_exc()}')

    return {
        'deleted_files': deleted_files,
        'deleted_rows': deleted_rows,
        'deleted_rag': deleted_rag,
    }
