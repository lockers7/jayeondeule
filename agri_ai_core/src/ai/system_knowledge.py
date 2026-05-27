# ══════════════════════════════════════════════════════════════════════════════
# 시스템 자기지식 RAG — 로컬 AI 가 서버 시스템 전반(테이블·로그·소스·서비스·도구)을
# 파악하도록 하는 지식 베이스 + 자동 회상.
#
# 배경: 로컬 AI 는 로그/소스/DB 도구를 모두 가졌으나, "무엇이 어디에 있고 어떤 도구로
#   접근하는지" 를 몰라 오라우팅(로그 요청을 DB 조회로 처리)·컬럼 환각을 냈다.
#   이 모듈이 시스템 지식을 VectorDB(document_collection, data_type='system_knowledge')에
#   저장하고, ANALYZER 가 매 질문마다 유사 지식을 자동 회상·주입한다 —
#   성장은 코드 변경 없이 데이터로만 이루어진다(analysis_lesson 루프와 동형).
#
# 원칙:
#   · 전부 best-effort — 어떤 예외도 채팅 흐름을 깨지 않는다.
#   · 대화 모드 전용. 농장제어(control) 사이클에는 절대 주입하지 않는다
#     (도메인 지식 save_domain_knowledge 와 분리 — 제어 오염 방지).
#   · 자가학습: AI/농장주가 발견한 사실을 save 로 영속 → 이후 자동 재회상.
#
# 파일 시작 함수 목록:
#   save_system_knowledge     : 시스템 지식 1건 저장 (임베딩 명시, 중복키 교체)
#   recall_system_knowledge   : 질문과 유사한 지식 top-N → ANALYZER 주입 블록
#   seed_system_knowledge     : 초기 지식 대량 시드 (실제 DB 스키마 반영, 재시드 가능)
#   list_system_knowledge     : 저장된 지식 목록
#   manage_system_knowledge   : LLM 도구 — learn/list/delete (delete 는 관리자 전용)
# ══════════════════════════════════════════════════════════════════════════════
import time
import uuid
from typing import Optional, Dict, Any, List

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_DATA_TYPE = "system_knowledge"
_MIN_LEN = 8
_MAX_LEN = 700
_RECALL_TOP_K = 4
# 시스템 지식은 질문 표현과 어휘가 다를 수 있어(예: "로그 분석" ↔ "search_logs 도구")
# 느슨하게 회수한다. 각 지식이 적용조건을 담아 비해당 지식은 LLM 이 무시한다.
_RECALL_MAX_DIST = 0.95
_CATEGORIES = ("db_schema", "logs", "source", "services", "tool_routing", "coding", "mcp_catalog", "sysadmin", "general")


def _collection():
    from agri_ai_core.src.chroma.collections import document_collection
    return document_collection()


def save_system_knowledge(text: str, category: str = "general",
                          source: str = "learned",
                          key: Optional[str] = None) -> Dict[str, Any]:
    try:
        body = (text or "").strip()
        if len(body) < _MIN_LEN:
            return {"success": False, "error": f"지식이 너무 짧습니다({_MIN_LEN}자 이상)."}
        cat = (category or "general").strip().lower()
        if cat not in _CATEGORIES:
            cat = "general"
        from agri_ai_core.src.chroma.operations import add_document, delete_document
        from agri_ai_core.src.ai.embedder import embed_text

        body = body[:_MAX_LEN]
        emb = embed_text(body)   # 0벡터 저장(검색 불가) 방지 — 임베딩 명시 필수
        meta = {
            "data_type": _DATA_TYPE,
            "category": cat,
            "source": source,
            "created_at": time.strftime("%Y-%m-%d %H:%M"),
        }
        # key 지정 시 고정 id(재저장=교체) — 시드/갱신용. 미지정 시 신규 학습 id.
        if key:
            doc_id = f"sysk_{key}"
            try:
                delete_document(_collection(), ids=[doc_id])
            except Exception:
                pass
        else:
            doc_id = f"sysk_learned_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        add_document(_collection(), doc_id, body, meta, embedding=emb)
        logger.info(f"[시스템지식] 저장({source}/{cat}): \"{body[:60]}\"")
        return {"success": True, "knowledge_id": doc_id, "category": cat}
    except Exception as e:
        logger.error(f"[시스템지식] 저장 실패: {e}")
        return {"success": False, "error": str(e)}


def recall_system_knowledge(user_query: str, top_k: int = _RECALL_TOP_K) -> str:
    try:
        from agri_ai_core.src.chroma.operations import query_documents
        from agri_ai_core.src.ai.embedder import embed_text

        emb = embed_text((user_query or "")[:_MAX_LEN])
        if not emb:
            return ""
        res = query_documents(
            _collection(), query_embeddings=[emb], n_results=top_k,
            where={"data_type": {"$eq": _DATA_TYPE}},
            include=["documents", "metadatas", "distances"],
        )
        # query_documents 는 이미 평탄화된 리스트 반환 (추가 [0] 벗기기 금지)
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        dists = res.get("distances") or []
        lines = []
        for doc, m, dist in zip(docs, metas, dists):
            if dist is not None and dist > _RECALL_MAX_DIST:
                continue
            cat = (m or {}).get("category", "")
            # 주입 프롬프트 비대화 방지 — 지식당 320자 상한(num_ctx 초과→빈응답 예방)
            snippet = doc if len(doc) <= 320 else doc[:317] + "…"
            lines.append(f"- [{cat}] {snippet}")
        if not lines:
            return ""
        return ("[시스템 자기지식 — 이 서버의 구조/테이블/로그/소스/도구 사용법]\n"
                "아래는 이번 질문과 관련된 서버 시스템 사실이다. 도구 선택·SQL 컬럼·데이터 위치를 "
                "여기에 맞춰라(추측·환각 금지). 해당 없는 항목은 무시하라.\n"
                + "\n".join(lines))
    except Exception as e:
        logger.debug(f"[시스템지식] 회상 실패(무시): {e}")
        return ""


def list_system_knowledge() -> List[Dict[str, Any]]:
    try:
        from agri_ai_core.src.chroma.operations import get_documents
        res = get_documents(_collection(),
                            where={"data_type": {"$eq": _DATA_TYPE}},
                            include=["documents", "metadatas"], limit=1000)
        ids = res.get("ids") or []
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        out = [{"knowledge_id": i,
                "category": (m or {}).get("category", ""),
                "source": (m or {}).get("source", ""),
                "text": d}
               for i, d, m in zip(ids, docs, metas)]
        out.sort(key=lambda x: (x["category"], x["knowledge_id"]))
        return out
    except Exception as e:
        logger.error(f"[시스템지식] 목록 실패: {e}")
        return []


def manage_system_knowledge(action: str, text: str = None,
                            category: str = "general",
                            knowledge_id: str = None,
                            auth_farm_id: str = None) -> Dict[str, Any]:
    try:
        action = (action or "").strip().lower()
        if action in ("learn", "register", "save", "add"):
            r = save_system_knowledge(text, category=category, source="learned")
            if r.get("success"):
                r["message"] = ("시스템 지식으로 저장했습니다. 이후 유사한 질문을 분석할 때 "
                                "자동으로 회상·반영됩니다(코드 변경 불필요).")
            return r
        if action == "list":
            items = list_system_knowledge()
            return {"success": True, "count": len(items), "knowledge": items}
        if action == "audit":
            rep = audit_system_knowledge()
            return {"success": True, "audit": rep,
                    "message": f"시스템 지식 자율 감사 완료: {rep}"}
        if action == "delete":
            # 삭제는 시스템관리자 전용(auth_farm_id 없음 = 시스템관리자)
            if auth_farm_id is not None:
                return {"success": False, "error": "시스템 지식 삭제는 시스템관리자 전용입니다."}
            if not knowledge_id or not str(knowledge_id).startswith("sysk_"):
                return {"success": False,
                        "error": "knowledge_id 는 'sysk_' 로 시작해야 합니다 (list 로 확인)."}
            from agri_ai_core.src.chroma.operations import delete_document
            delete_document(_collection(), ids=[knowledge_id])
            logger.info(f"[시스템지식] 삭제: {knowledge_id}")
            return {"success": True, "message": f"시스템 지식 {knowledge_id} 삭제 완료."}
        return {"success": False, "error": f"지원 action: learn/list/delete/audit (입력: {action})"}
    except Exception as e:
        logger.error(f"[시스템지식] 관리 실패: {e}")
        return {"success": False, "error": str(e)}


# ────────────────────────────────────────────────────────────────────
# 초기 지식 시드 — 실제 DB 스키마를 조회해 정확한 컬럼을 반영한다.
# 고정 key 로 저장하므로 재실행 시 교체(idempotent).
# ────────────────────────────────────────────────────────────────────
def _real_columns(table: str) -> List[str]:
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            rows = d.fetch_all(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name=%s ORDER BY ordinal_position", (table,), as_dict=True)
        return [r["column_name"] for r in (rows or [])]
    except Exception:
        return []


def seed_system_knowledge() -> Dict[str, Any]:
    seeded = 0
    # ── 핵심 테이블 스키마(실제 컬럼 조회) ── 컬럼 환각 근본 차단.
    table_notes = {
        "relay_l_recording":
            "릴레이(장치) ON/OFF 실측 상태 기록. ⛔ 호기 컬럼은 hous_id(house_id 아님). "
            "값은 relay_1st_flag~relay_16st_flag(불리언). 릴레이번호→장치 매핑은 호기마다 "
            "다르므로 relay_manager.get_pin_map(house_id)로 해석(예 1호 relay_6=배기팬, "
            "2호 relay_8=배기팬). '릴레이/장치 제어상태' 질문은 로그가 아니라 이 테이블을 "
            "db_read_query 로 조회한다.",
        "sensor_l_recording":
            "센서 실측 기록. 호기 컬럼 hous_id. 실내온도 indr_tprt_valu, 실내습도 "
            "indr_hmdt_valu, 외기온 oudr_tprt_valu, 외기습도 oudr_hmdt_valu, CO2 co2_valu, "
            "수온 watr_tprt_valu, 조도 ligt_lvel_valu, 수위 watr_lvel_valu.",
        "ai_decision_log":
            "AI/Agent 제어 결정 이력. 호기 컬럼 house_id, 시각 decided_at. action, "
            "circulation(배기순환 등), water_heater/fog_occurs/drainage_motor(불리언), "
            "reason, growth_stage, sensor_snapshot. '무슨 제어를 왜 했나'는 이 테이블.",
        "agent_subscriptions":
            "구독형 Agent 모니터링 등록. interval_min(주기), intent, active, "
            "alert_cooldown_min·last_kakao_at(카카오 발송 제어), house_id, farm_id. "
            "'__default_cron__'은 자율제어 크론(카카오 미발송).",
        "alert_l_log":
            "비상/경고 알림 이력. level(info/warning/critical), category, hous_id, "
            "title, message, recd_dttm.",
    }
    for tbl, note in table_notes.items():
        cols = _real_columns(tbl)
        col_txt = (", ".join(cols)) if cols else "(조회실패)"
        text = f"[DB테이블 {tbl}] {note}\n실제 컬럼: {col_txt}"
        if save_system_knowledge(text, category="db_schema", source="seed",
                                 key=f"db_{tbl}").get("success"):
            seeded += 1

    # ── DB 내성/조회 도구 ──
    statics = {
        "db_tools":
            ("[DB 조회 방법] 테이블 목록은 db_list_tables, 컬럼 확인은 "
             "db_describe_table(table), 조회는 db_read_query(sql). ⛔ 컬럼을 추측하지 말고 "
             "모르면 db_describe_table 로 먼저 확인. 없는 컬럼 오류(42703)는 자가교정 힌트가 "
             "실제 컬럼을 알려주니 그걸로 재작성.", "db_schema"),
        # ── 로그 ──
        "logs_howto":
            ("[로그 분석 방법] 운영 로그 검색·분석은 search_logs(query, level, date, "
             "log_type, max_results) 도구를 반드시 사용(읽기전용, 3GB 규모라 전체읽기 불가). "
             "파일 목록은 list_log_files. log_type 종류: ai(제어/AI 기본), web, scheduler, "
             "api. '오늘 에러', 'LLM 실패 몇 건', '무슨 일 있었나', '○○ 로그' 류는 search_logs. "
             "matched 가 전체 매칭 건수.", "logs"),
        "logs_vs_db":
            ("[로그 vs DB 구분] 텍스트 로그에는 이벤트·오류·처리흐름이 있다. 그러나 릴레이 "
             "ON/OFF '값'이나 센서 '값'은 로그에 없고 relay_l_recording·sensor_l_recording "
             "DB 에 있다. 로그엔 '[릴레이설정] DB쓰기 성공' 같은 사실만 기록된다. "
             "'릴레이 제어상태 요약'은 DB(db_read_query), '제어 중 오류/이벤트'는 로그"
             "(search_logs). 요청에 '로그'가 있어도 값이 필요하면 DB 를 병행하고, 어느 "
             "소스를 썼는지 답변에 밝혀라.", "logs"),
        # ── 소스코드 ──
        "source_howto":
            ("[소스코드 분석 방법] 운영 소스(agri_ai_core)는 source_list(dir 목록), "
             "source_search(키워드로 코드 검색), source_read(file_path, start_line, "
             "end_line 로 본문 읽기)로 분석한다. 수정은 edit_source(테스트 실패 시 자동원복), "
             "되돌리기 revert_source. '이 기능 코드 어디있나', '어떻게 구현됐나' 류는 "
             "source_search→source_read.", "source"),
        "source_structure":
            ("[소스 구조] 루트 agri_ai_core/. src/control(환경제어·비상·릴레이·Agent 스케줄러), "
             "src/ai(채팅 파이프라인·도구·RAG·MCP·카카오), src/ai/pipeline(ANALYZER·수집·답변), "
             "src/postgresql(DB), src/chroma(VectorDB), api(FastAPI 라우터). 제어 진입 "
             "control/ai_control.py·manual_control.py, 채팅 진입 ai/pipeline/runner.py.", "source"),
        "code_dev_workflow":
            ("[코드 개발 워크플로우] 소스를 읽고 개발하는 표준 절차: ①위치찾기 source_search"
             "(키워드로 파일:줄 검색) ②정독 source_read(file_path·start_line·end_line) ③수정 "
             "edit_source(구문검증→쓰기→관련 pytest 자동실행→실패 시 자동 원복) ④검증 run_script "
             "또는 재조회. 일회성 계산·집계·점검은 운영소스를 건드리지 말고 write_script(scripts/llm/)"
             "+run_script 로 별도 코딩. 큰 변경은 최소 단위로 나눠 각 단계 테스트.", "source"),
        "code_edit_safety":
            ("[edit_source 안전메커니즘] 운영소스(agri_ai_core) 변경은 edit_source 로만 한다. "
             "변경 전 자동 백업→구문검증(깨진 코드 저장 거부)→저장 후 연관 단위테스트 실행→테스트 "
             "실패 시 자동 원복(변경 무효화)한다. 이력은 list_source_edits, 수동 롤백은 revert_source. "
             "비상제어·인터록·관리자지시·apply_water_safety·알고리즘 본체 등 안전장치 소스는 "
             "deny-list 로 변경 자체가 차단된다(우회 금지). 변경 사유(reason)를 꼭 남긴다.", "source"),
        "sql_dev_howto":
            ("[SQL 개발 방법] ①db_list_tables 로 테이블 파악 ②db_describe_table 로 컬럼·타입 확인 "
             "③db_read_query 로 SELECT 작성(단일문·읽기전용, farm_id 격리). 없는 컬럼/타입오류면 "
             "반환 error 의 💡 hint(self_heal)에 실제 컬럼이 실려오니 그걸로 즉시 재작성한다(추측 금지). "
             "데이터 변경은 db_write_query(UPDATE/INSERT 만, WHERE 필수, 100행 상한, 변경 전 백업). "
             "relay_l_recording·sensor_l_recording·kakao_token_m·db_write_audit 는 보호테이블(쓰기 차단).",
             "source"),
        "python_dev_howto":
            ("[Python 개발 방법] 전용 도구·db_read_query 로 안 되는 계산·집계·시스템점검은 "
             "write_script 로 scripts/llm/ 안에 .py 를 짜고(구문검증됨) run_script 로 실행"
             "(sudo 없음·timeout·경로이탈 불가). 실패하면 stderr 를 read 해 write_script 로 고쳐 "
             "재시도. 설치 패키지·버전은 importlib.metadata 로 확인. 운영 로직 변경은 edit_source.",
             "source"),
        "mcp_add_howto":
            ("[MCP 서버 자체추가] 'MCP 서버를 추가/등록해달라'는 요청은 반드시 manage_mcp_server "
             "(action='add', name, command, args)를 쓴다. ⛔ manage_external_api(그건 REST API "
             "등록부라 MCP 와 무관) 와 혼동 금지. manage_mcp_server 가 .vscode/mcp.json 에 직접 "
             "등록한다(코드·재기동 불필요). stdio 서버는 command(npx/uvx/uv/python/node/docker 런처)"
             "+args, HTTP 서버는 url. 시크릿(API키)은 env 에 '${환경변수명}' 플레이스홀더로. 등록 후 "
             "manage_mcp_server(action='test',name=) 로 연결 확인→ mcp_list_tools/mcp_call 로 사용. "
             "action: list/get/add/update/remove/test. 등록·제거는 시스템관리자 전용.", "source"),
        "code_read_map":
            ("[코드 위치 지도] 채팅 3단계는 ai/pipeline/(runner·question_analyzer·data_collector·"
             "answer_generator), 환경제어는 control/ai_control.py·manual_control.py, 도구는 "
             "ai/tools_*.py + 디스패치 ai/tools_executor.py + 스펙 ai/tools_definition.py, RAG 는 "
             "ai/system_knowledge.py·chroma/, MCP 는 ai/mcp_client.py·tools_mcp_gateway.py·"
             "tools_mcp_registry.py. ⛔신규 채팅도구는 5중 등록: 구현함수+tools_definition.py 스펙+"
             "tools_executor.py 디스패치+question_analyzer 화이트리스트+tool_definition_m 테이블 INSERT"
             "(USE_DB_TOOLS=1 라 테이블이 1순위).", "source"),
        # ── 서비스/시스템 상태 ──
        "services_howto":
            ("[서비스/시스템 상태] 등록 서비스 가동상태는 list_services, 개별은 "
             "service_status(no), 재기동 restart_service(no). 서버 리소스(CPU/메모리/"
             "디스크/GPU)는 get_server_resources. 재배사 운영상태(제어모드·생육단계·"
             "AI루프)는 get_system_status. 카메라 현재화면은 get_camera_view(house_id).",
             "services"),
        "remote_howto":
            ("[원격 서버 조사] 다른 서버의 상태를 이 서버처럼 파악하려면 remote_status(host)로 "
             "SSH(키 인증) 접속해 리소스·서비스·로그·GPU를 조회한다(read-only, 승인 불필요). "
             "임의 명령은 remote_run(host, command) — 조회 명령은 즉시, 변경성(rm·재시작·설치)은 "
             "관리자 카카오 승인요청 후 approve_remote_command 로만 집행. 접속정보는 "
             "manage_remote_host(action='register', name, host_spec='user@host:port', identity_path)로 "
             "등록해두고 host=이름으로 참조(또는 host='user@host:port' 직접). SSH 키 인증만.", "services"),
        # ── 도구 라우팅 맵(핵심) ──
        "routing_map":
            ("[질문→도구 라우팅 지도] "
             "릴레이/장치 제어상태 값→db_read_query(relay_l_recording). "
             "제어 결정·사유→db_read_query(ai_decision_log). "
             "센서 값→db_read_query(sensor_l_recording) 또는 get_farm_realtime_data. "
             "로그·에러·이벤트→search_logs. 소스코드→source_search/source_read. "
             "시스템 운영상태→get_system_status. 서버 리소스→get_server_resources. "
             "서비스 가동→list_services. 알림 이력→db_read_query(alert_l_log). "
             "농장 재배지식→search_farm_knowledge. 웹→search_web.", "tool_routing"),
        "self_learn":
            ("[자가학습 — 능동] 서버를 탐색(source_search/read·db_describe·search_logs)하다 "
             "재사용가치 있는 '지속적 시스템 사실'을 알아내면 스스로 manage_system_knowledge"
             "(action='learn', text, category)로 저장하라 — 지시 없이도. 예: '카카오 발송은 "
             "kakao_notify.push_alert 가 담당', '○○ 테이블 시각 컬럼은 recd_dttm'. DB 컬럼/타입 "
             "오류 자가교정과 테이블 조사는 이미 자동 학습되니 중복 저장 말 것. 일회성/유동 값"
             "(특정 조회결과·센서값)은 저장 금지. 농장 재배·제어 룰은 save_domain_knowledge, "
             "질문응대 방식은 manage_analysis_lesson.", "general"),
        "pkg_howto":
            ("[패키지 점검] 설치 파이썬 패키지·버전은 run_script 로 확인한다. write_script 로 "
             "importlib.metadata.distributions() 를 출력하는 스크립트를 짜고 run_script 로 실행. "
             "특정 패키지는 importlib.metadata.version('패키지명'). 운영 venv 기준, 전용 도구는 "
             "없다.", "services"),
        "scripts_howto":
            ("[스크립트 실행 역량] write_script(scripts/llm/ 안 .py 작성)+run_script(실행, sudo "
             "없음, timeout 60s, 경로이탈 불가)로 전용 도구·db_read_query 로 안 되는 계산·집계·"
             "시스템 점검(패키지·파일·프로세스·리소스)을 직접 코딩해 수행. 운영 소스 수정은 "
             "edit_source 로만.", "source"),
        # ── 자율 성장(스케줄·구독·학습유형) ── 재시드에도 영속(환각 근본 차단)
        "selfgrow_schedule":
            ("[자율 성장 스케줄 — 실제 테이블: schedule_m_setting] ⛔테이블명은 "
             "'schedule_m_setting'이다(schedule_m 아님). APScheduler cron/interval 로 자동 "
             "실행되는 학습·수집 잡: ①camera_archive_hourly = 매시간 정각(cron '0 * * * *') "
             "재배사 카메라 아카이브+Vision LLM 재배환경 분석→farm_knowledge. "
             "②growth_rag_job_midnight = 매일 00:05, growth_rag_job_noon = 매일 12:00 생육 "
             "RAG 수집→farm_knowledge. ③learning_job = 매일 04:00 학습 작업. "
             "④chunk_cleanup_job = 매일 03:00 RAG 청크 180일 정리. ⑤relay_control_job = 5초 "
             "제어, ai_control_loop = 60초. 조회는 db_read_query(schedule_m_setting).",
             "services"),
        "selfgrow_subscriptions":
            ("[자율 학습 작업 — agent_subscriptions 테이블] 스케줄러가 due 구독을 자동 "
             "실행(run_agent). ①intent='__default_cron__' 10분마다 농장 자율 환경제어 "
             "사이클(센서분석→제어→학습). ②intent='__default_web_scan__' 하루 1회 외부지식 "
             "자율수집(웹·논문·심리 조사→save_knowledge→web_knowledge). "
             "③intent='__default_region_scan__' 하루 1회 지역정보 자율수집. 조회: "
             "db_read_query(agent_subscriptions) — 컬럼 intent, interval_min, total_runs, "
             "last_run_at, task.", "services"),
        "selfgrow_learning_types":
            ("[자율 성장 학습 유형별 저장소(VectorDB)] 로컬 LLM 자율 성장은 7가지: ①웹지식 "
             "자율수집→web_knowledge 컬렉션(save_knowledge). ②Vision LLM 재배분석·생육 "
             "RAG→farm_knowledge. ③질문분석 교훈(사용자가 가르친 처리방식)→document_collection"
             "(analysis_lesson, save_lesson/recall_lessons). ④시스템 자기지식(서버·DB·도구 "
             "사용법)→system_knowledge(manage_system_knowledge). ⑤트레이딩 자가학습→"
             "trading_knowledge(auto_learn_from_run/learn_from_performance). ⑥대화 장기기억→"
             "conversation_collection. ⑦농장주가 가르친 재배·제어 운영룰→document_collection"
             "(domain_knowledge, save_domain_knowledge 저장·AI 제어사이클이 query_domain_knowledge "
             "로 회상·반영). 저장 지식은 매 질문·제어에 회상 주입되어 재사용(bge-m3 임베더라 "
             "타 LLM도 읽음).", "services"),
    }
    for key, (text, cat) in statics.items():
        if save_system_knowledge(text, category=cat, source="seed", key=key).get("success"):
            seeded += 1

    # 파이썬 코딩 방법론 지식(로컬 AI 코딩수준 이식) 동반 시드 — 재시드에도 영속
    try:
        from agri_ai_core.src.ai.coding_knowledge import seed_coding_knowledge
        seeded += seed_coding_knowledge().get("seeded", 0)
    except Exception as e:
        logger.warning(f"[시스템지식] 코딩지식 시드 실패(무해): {e}")

    # MCP 서버 카탈로그(정보요구→적합 MCP) 동반 시드 — 재시드에도 영속
    try:
        from agri_ai_core.src.ai.mcp_catalog import seed_mcp_catalog
        seeded += seed_mcp_catalog().get("seeded", 0)
    except Exception as e:
        logger.warning(f"[시스템지식] MCP카탈로그 시드 실패(무해): {e}")

    # 시스템관리 SSH 명령 지식(원격 Windows/Linux/RPi 유지보수) 동반 시드 — 재시드에도 영속
    try:
        from agri_ai_core.src.ai.sysadmin_knowledge import seed_sysadmin_knowledge
        seeded += seed_sysadmin_knowledge().get("seeded", 0)
    except Exception as e:
        logger.warning(f"[시스템지식] 시스템관리지식 시드 실패(무해): {e}")

    logger.info(f"[시스템지식] 시드 완료: {seeded}건")
    return {"success": True, "seeded": seeded}


# ────────────────────────────────────────────────────────────────────
# 자율 지식 감사(GAP4) — 저장된 DB 스키마 지식을 실제 information_schema 와 대조.
#   · 테이블 소멸 → 관련 지식 삭제
#   · 컬럼 드리프트(추가/삭제) → cols_ 지식 재생성(변경분만 재임베딩 — 낭비 방지)
# 스키마가 바뀌어도 지식이 낡지 않게 스스로 유지한다. best-effort.
# ────────────────────────────────────────────────────────────────────
def _parse_learned_cols(text: str) -> Optional[List[str]]:
    # "…실제 컬럼(자가학습): a, b, c. …" 에서 컬럼 리스트 추출. 실패 시 None.
    marker = "자가학습): "
    i = text.find(marker)
    if i < 0:
        return None
    seg = text[i + len(marker):]
    seg = seg.split(".", 1)[0]
    return [c.strip() for c in seg.split(",") if c.strip()]


def audit_system_knowledge() -> Dict[str, Any]:
    report = {"checked": 0, "refreshed": 0, "removed": 0, "ok": 0, "errors": 0}
    try:
        from agri_ai_core.src.chroma.operations import delete_document
        items = list_system_knowledge()
        # cols_ 문서 = 내가 만든 '테이블→컬럼' 확정 사실(삭제/갱신 대상).
        # db_ 문서에는 표 스키마(db_<table>)와 안내문(db_tools 등)이 섞여 있으므로
        # 테이블 후보로만 쓰고 절대 삭제하지 않는다(안내문 오삭제 방지).
        cols_ids = {it["knowledge_id"] for it in items
                    if it["knowledge_id"].startswith("sysk_cols_")}
        tables = set()
        for it in items:
            kid = it["knowledge_id"]
            for pref in ("sysk_cols_", "sysk_db_"):
                if kid.startswith(pref):
                    tables.add(kid[len(pref):])
                    break
        for tbl in sorted(tables):
            report["checked"] += 1
            cols = _real_columns(tbl)
            if not cols:
                # 컬럼 없음 = 테이블 소멸 또는 비-테이블 안내문(db_tools 등).
                # cols_ 확정 사실이 있을 때만 삭제. db_ 안내문서는 불가침.
                if f"sysk_cols_{tbl}" in cols_ids:
                    try:
                        delete_document(_collection(), ids=[f"sysk_cols_{tbl}"])
                        report["removed"] += 1
                    except Exception:
                        pass
                continue
            cur = next((it for it in items if it["knowledge_id"] == f"sysk_cols_{tbl}"), None)
            parsed = _parse_learned_cols(cur["text"]) if cur else None
            if parsed is not None and set(parsed) == set(cols):
                report["ok"] += 1                       # 일치 — 재임베딩 생략
                continue
            # 신규 or 드리프트 → cols_ 지식 재생성
            text = (f"[DB테이블 {tbl}] 실제 컬럼(자가학습): {', '.join(cols)}. "
                    f"이 테이블 조회 시 이 컬럼만 사용 — 존재하지 않는 컬럼 환각 금지.")
            if save_system_knowledge(text, category="db_schema",
                                     source="audit", key=f"cols_{tbl}").get("success"):
                report["refreshed"] += 1
    except Exception as e:
        report["errors"] += 1
        logger.error(f"[시스템지식] 자율 감사 실패: {e}")
    logger.info(f"[시스템지식] 자율 감사 완료: {report}")
    return report


# ────────────────────────────────────────────────────────────────────
# 기동 자율 초기화 — 지식이 비었으면 시드, 있으면 감사(드리프트 갱신).
# 서비스 시작 시 1회 호출(백그라운드) — 스스로 초기화·유지.
# ────────────────────────────────────────────────────────────────────
def ensure_system_knowledge() -> Dict[str, Any]:
    try:
        existing = list_system_knowledge()
        if not existing:
            return seed_system_knowledge()
        return audit_system_knowledge()
    except Exception as e:
        logger.error(f"[시스템지식] 기동 초기화 실패: {e}")
        return {"success": False, "error": str(e)}
