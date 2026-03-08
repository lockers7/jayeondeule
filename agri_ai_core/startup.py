# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 애플리케이션 초기화 모듈
# 시작 시 ChromaDB 연결, 스케줄러 설정 등을 수행합니다.
# --->
# initialize_app: 애플리케이션 시작 초기화
# shutdown_app: 애플리케이션 종료 처리
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import sys
import time
import logging
import traceback

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.chroma import heartbeat, ensure_required_collections_exist
from agri_ai_core.src.control import setup_scheduler, start_scheduler, stop_scheduler, setup_default_jobs, control_all_manual, start_ai_control_loop, stop_ai_control_loop

logger = setup_logger(__name__)

_initialized = False


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 애플리케이션 시작 초기화
# --->
# ChromaDB, 스케줄러 등 시스템 리소스를 초기화합니다.
# 중복 호출을 방지하여 Streamlit 리렌더링 시에도 한 번만 실행됩니다.
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def initialize_app():
    global _initialized
    if _initialized:
        return

    total_start = time.time()

    try:
        logger.info("-" * 50)
        logger.info("=" * 60)
        logger.info("AgriAI Core 시작 초기화")
        logger.info("=" * 60)

        # 환경 정보 출력
        logger.info("[환경정보] Python=%s", sys.version.split()[0])
        logger.info("[환경정보] LOG_LEVEL=%s -> 적용 레벨: %s",
                     os.getenv('LOG_LEVEL', '(미설정)'),
                     logging.getLevelName(logger.level))
        logger.info("[환경정보] MODEL_NAME=%s", os.getenv('MODEL_NAME', '(미설정)'))
        logger.info("[환경정보] OLLAMA_URL=%s", os.getenv('OLLAMA_URL', '(미설정)'))
        logger.info("[환경정보] PGDB_HOST=%s, PGDB_DATABASE=%s",
                     os.getenv('PGDB_HOST', '(미설정)'),
                     os.getenv('PGDB_DATABASE', '(미설정)'))
        logger.info("[환경정보] CHROMA_DB_HTTP_HOST=%s:%s",
                     os.getenv('CHROMA_DB_HTTP_HOST', '(미설정)'),
                     os.getenv('CHROMA_DB_HTTP_PORT', '(미설정)'))
        logger.info("[환경정보] API_PORT=%s", os.getenv('API_PORT', '(미설정)'))

        # -----------------------------------------------------------
        # [1/4] Ollama 연결 확인
        # -----------------------------------------------------------
        logger.info("[1/4] Ollama LLM 서버 연결 확인 중...")
        t0 = time.time()
        try:
            ollama_url = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434')
            from urllib import request as urlrequest
            req = urlrequest.Request(f"{ollama_url}/api/tags", method="GET")
            with urlrequest.urlopen(req, timeout=5) as resp:
                import json
                data = json.loads(resp.read().decode())
                models = data.get("models", [])
                model_names = [m.get("name", "?") for m in models[:5]]
                logger.info("[1/4] Ollama 연결 성공 (%s, %.1fs)", ollama_url, time.time() - t0)
                logger.info("[1/4] Ollama 설치된 모델: %s", model_names)
                try:
                    from agri_ai_core.src.ai.llm_client import _get_model_name
                    actual_model = _get_model_name()
                except Exception:
                    actual_model = os.getenv('MODEL_NAME', '(미설정)')
                logger.info("[1/4] Ollama 설정 모델(MODEL_NAME): %s → 실제 적용 모델: %s",
                            os.getenv('MODEL_NAME', '(미설정)'), actual_model)
                # GPU에 현재 로드된 모델 확인 (ollama /api/ps)
                try:
                    ps_req = urlrequest.Request(f"{ollama_url}/api/ps", method="GET")
                    with urlrequest.urlopen(ps_req, timeout=3) as ps_resp:
                        ps_data = json.loads(ps_resp.read().decode())
                        running = ps_data.get("models", [])
                        if running:
                            loaded = [f"{m.get('name','?')} ({m.get('size_vram',0) // (1024**3)}GB VRAM)" for m in running]
                            logger.info("[1/4] Ollama GPU 로드 모델: %s", loaded)
                        else:
                            logger.info("[1/4] Ollama GPU 로드 모델: 없음 (다음 질문 시 로드)")
                except Exception:
                    pass
        except Exception as e:
            logger.warning("[1/4] Ollama 연결 실패 (%.1fs): %s", time.time() - t0, e)

        # -----------------------------------------------------------
        # [2/4] ChromaDB 연결 확인
        # -----------------------------------------------------------
        logger.info("[2/4] ChromaDB 벡터DB 연결 확인 중...")
        t0 = time.time()
        try:
            status = heartbeat()
            if "error" in status:
                logger.warning("[2/4] ChromaDB 연결 경고 (%.1fs): %s", time.time() - t0, status.get('error'))
            else:
                logger.info("[2/4] ChromaDB 연결 성공 (%.1fs)", time.time() - t0)

                t1 = time.time()
                result = ensure_required_collections_exist()
                if result:
                    logger.info("[2/4] 필수 컬렉션 확인 완료 (%.1fs)", time.time() - t1)
                else:
                    logger.warning("[2/4] 필수 컬렉션 일부 누락 (%.1fs)", time.time() - t1)
        except Exception as e:
            logger.error("[2/4] ChromaDB 연결 실패 (%.1fs): %s", time.time() - t0, e)

        # -----------------------------------------------------------
        # [3/4] PostgreSQL 연결 확인
        # -----------------------------------------------------------
        logger.info("[3/4] PostgreSQL 데이터베이스 연결 확인 중...")
        t0 = time.time()
        try:
            import psycopg2
            from agri_ai_core.config import settings as _settings
            from agri_ai_core.src.postgresql import queries as dbQry

            conn = psycopg2.connect(
                host=_settings.database.host,
                port=_settings.database.port,
                database=_settings.database.database,
                user=_settings.database.user,
                password=_settings.database.password,
                connect_timeout=5,
            )
            conn.autocommit = True

            with conn.cursor() as cursor:
                cursor.execute("SELECT version()")
                pg_version = cursor.fetchone()[0].split(",")[0]
                logger.info("[3/4] PostgreSQL 연결 성공 (%.1fs): %s", time.time() - t0, pg_version)

                # AI 학습 상태/패턴 테이블 자동 생성
                try:
                    cursor.execute(dbQry.CREATE_AI_LEARNING_STATUS_TABLE)
                    cursor.execute(dbQry.CREATE_AI_LEARNING_PATTERN_TABLE)
                    cursor.execute(dbQry.CREATE_AI_LEARNING_PATTERN_INDEX)
                    cursor.execute(dbQry.ALTER_CROPS_ADD_GROWTH_DETAIL_COLUMNS)
                    logger.info("[3/4] AI 학습 테이블 초기화 + 생육 컬럼 확장 완료")
                except Exception as e2:
                    logger.warning("[3/4] AI 학습 테이블 초기화 실패: %s", e2)

            conn.close()

        except Exception as e:
            logger.warning("[3/4] PostgreSQL 연결 실패 (%.1fs): %s", time.time() - t0, e)

        # -----------------------------------------------------------
        # [4/4] 스케줄러 설정 및 시작
        # -----------------------------------------------------------
        logger.info("[4/4] 스케줄러 설정 중...")
        t0 = time.time()
        try:
            from agri_ai_core.src.ai.learning.growth_rag_processor import run_growth_rag

            setup_scheduler()
            setup_default_jobs(
                manual_control_func=control_all_manual,
                growth_rag_func=run_growth_rag,
            )
            start_scheduler()
            logger.info("[4/4] 스케줄러 시작됨 (%.1fs) - 수동/알고리즘 (10초) + 생육RAG (12:00/00:00)", time.time() - t0)

            # AI 순환 제어 루프 시작 (재배사 순환 + 30초 delay)
            start_ai_control_loop()
            logger.info("[4/4] AI 순환 제어 루프 시작됨 (재배사 간 30초 대기)")
        except Exception as e:
            logger.warning("[4/4] 스케줄러 설정 실패 (%.1fs): %s", time.time() - t0, e)

        total_elapsed = time.time() - total_start
        logger.info("=" * 60)
        logger.info("AgriAI Core 시작 초기화 완료 (총 %.1fs)", total_elapsed)
        logger.info("=" * 60)

        _initialized = True

    except Exception as e:
        logger.error("시작 초기화 중 오류: %s", e)
        logger.error(traceback.format_exc())


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 애플리케이션 종료 처리
# --->
# 스케줄러 등 리소스를 정리합니다.
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def shutdown_app():
    try:
        logger.info("=" * 60)
        logger.info("AgriAI Core 종료 처리 시작")
        logger.info("=" * 60)

        # [1/4] AI 순환 루프 정지
        logger.info("[1/4] AI 순환 제어 루프 정지 중...")
        t0 = time.time()
        try:
            stop_ai_control_loop()
            logger.info("[1/4] AI 순환 제어 루프 정지 완료 (%.1fs)", time.time() - t0)
        except Exception as e:
            logger.warning("[1/4] AI 순환 제어 루프 정지 실패 (%.1fs): %s", time.time() - t0, e)

        # [2/4] 스케줄러 중지
        logger.info("[2/4] 스케줄러 중지 중...")
        t0 = time.time()
        try:
            stop_scheduler()
            logger.info("[2/4] 스케줄러 중지 완료 (%.1fs)", time.time() - t0)
        except Exception as e:
            logger.warning("[2/4] 스케줄러 중지 실패 (%.1fs): %s", time.time() - t0, e)

        # [3/4] ChromaDB 연결 정리
        logger.info("[3/4] ChromaDB 연결 정리 중...")
        t0 = time.time()
        try:
            status = heartbeat()
            if "error" not in status:
                logger.info("[3/4] ChromaDB 정상 상태로 종료 (%.1fs)", time.time() - t0)
            else:
                logger.warning("[3/4] ChromaDB 이미 연결 해제 (%.1fs)", time.time() - t0)
        except Exception as e:
            logger.info("[3/4] ChromaDB 연결 해제됨 (%.1fs)", time.time() - t0)

        # [4/4] 기타 리소스 정리
        logger.info("[4/4] 리소스 정리 완료")

        logger.info("=" * 60)
        logger.info("AgriAI Core 종료 처리 완료")
        logger.info("=" * 60)

    except Exception as e:
        logger.error("종료 처리 중 오류: %s", e)
        logger.error(traceback.format_exc())
