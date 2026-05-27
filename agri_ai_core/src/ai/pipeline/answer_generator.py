# ════════════════════════════════════════════════════════════════════════════════════════
# 3단계 답변 작성: 수집된 데이터 기반 LLM 답변 생성 및 출처 선별.
# --->
# generate_answer: 3단계: 수집된 데이터 기반 정교한 답변 생성
# _extract_used_sources: LLM 응답에서 <USED_SOURCES>1,3,5</USED_SOURCES> 태그를 파싱합니다
# _remove_source_tags: 응답에서 <USED_SOURCES> 태그와 내용을 제거
# _format_collected_data: format collected data
# _generate_simple_response: generate simple response
# ════════════════════════════════════════════════════════════════════════════════════════
import re
import time
import traceback
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import NUM_PREDICT, NUM_CTX
from agri_ai_core.src.ai.pipeline.prompts import build_answer_system_prompt

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# 3단계: 수집된 데이터 기반 정교한 답변 생성
# 
# LLM이 답변 본문 + 사용한 출처 번호(<USED_SOURCES>)를 출력합니다.
# 시스템은 출처 번호를 파싱하여 실제 사용된 출처만 반환합니다.
# ────────────────────────────────────────────────────────────────────
def generate_answer(user_query, analysis_result, collected_result,
                    conversation_history=None, farm_name=None, farm_info=None,
                    speech_style=None, progress_callback=None):
    t0 = time.time()
    question_type = analysis_result.get("question_type", "general")

    # 도구 불필요 유형 → 간단 LLM 응답
    if question_type == "greeting":
        return _generate_simple_response(user_query, conversation_history, farm_name, speech_style, "greeting")
    if question_type == "casual_chat":
        # 잡담·친교 전용 말벗 페르소나 — 제어·업무 기능과 무관한 대화 모드
        return _generate_casual_response(user_query, conversation_history, farm_name, speech_style)
    if question_type == "conversation_ref":
        return _generate_simple_response(user_query, conversation_history, farm_name, speech_style, "conversation_ref")

    # 결과가 명확한 실행형 유형 → 간결 보고 (LLM 토큰 절약)
    _concise_types = ("farm_control", "farm_knowledge_delete")
    is_concise = question_type in _concise_types
    # general(단위변환·계산·상식·정의 등)은 외부 데이터 불필요 + 짧은 답변으로 충분
    is_general = (question_type == "general")

    # 수집된 데이터와 출처
    all_sources = collected_result.get("sources", [])
    tools_used = collected_result.get("tools_used", [])
    tool_calls_detail = collected_result.get("tool_calls_detail", [])  # 감사 로그 pass-through

    # 수집 데이터를 번호 매긴 텍스트로 포맷
    data_text = _format_collected_data(collected_result)

    # 수집 데이터 유무·is_general 여부에 따라 light/heavy phase 분기
    # → general(단위변환/상식 등)·도구 미사용 케이스는 "수집된 데이터" 표현이 부적절
    if progress_callback:
        if is_general or not collected_result.get("data"):
            progress_callback("답변을 작성하고 있습니다...", "llm_generating_light")
        else:
            progress_callback("수집된 데이터를 종합하여 답변을 작성하고 있습니다...", "llm_generating")

    try:
        from agri_ai_core.src.ai.llm_client import (
            _ollama_chat, _get_model_name, _extract_message_content,
            _finalize_user_facing_answer, _build_structured_result,
            _determine_response_type, _strip_hallucinated_urls,
            _build_conversation_context,
        )

        model_name = _get_model_name()
        now = datetime.now()
        current_dt = now.strftime("%Y년 %m월 %d일 %A %H시 %M분")

        # 3단계 프롬프트 — 1단계 분석 결과 + 출처 목록 포함
        # general은 build_answer_system_prompt 내부에서 경량 프롬프트로 분기되므로
        # 농장 정보/출처 목록 모두 전달하지 않아도 영향 없음 (함수가 무시함).
        system_prompt = build_answer_system_prompt(
            farm_name=farm_name,
            farm_info=farm_info,
            speech_style=speech_style or "male",
            analysis_result=analysis_result,
            current_datetime=current_dt,
            source_list=all_sources,
        )

        # general은 수집 데이터/과거 히스토리 주입 생략 (외부 데이터 불필요 질문)
        if not is_general:
            system_prompt += f"\n\n[수집된 데이터]\n{data_text}"

        messages = [{"role": "system", "content": system_prompt}]

        # 대화 컨텍스트 주입 — general은 생략 (단위변환/상식에 과거 대화 불필요, 토큰 절약)
        if conversation_history and not is_general:
            _build_conversation_context(messages, conversation_history, user_query)

        messages.append({"role": "user", "content": user_query})

        # LLM 호출 (도구 미제공 → 순수 답변만 생성)
        # 유형별 num_predict/num_ctx 조정:
        #   general : 짧은 답변(변환/계산/상식) — 768/4096 (prompt_eval·generate 모두 축소)
        #   concise : 제어/삭제 결과 보고 — 1024/4096
        #   default : RAG/날씨/웹검색 등 길이 보장 — NUM_PREDICT/NUM_CTX
        # ⛔ num_ctx 는 모든 gemma3:27b 소비자와 동일(16384)해야 한다. 값이 다르면
        #   Ollama 가 모델을 리로드하는데, 27b 가 16GB VRAM 에 겨우 들어가(일부 CPU
        #   오프로드) 리로드가 ~90초 걸린다. 과거 분석기(16384)→검증(4096)→답변(8192)
        #   전환마다 90초씩 리로드돼 채팅 한 번이 3분+ 걸렸다(2026-07-19 실측).
        #   num_predict(생성 길이)만 유형별로 조절하고 num_ctx 는 고정한다.
        if is_general:
            answer_num_predict = 768
            answer_num_ctx = NUM_CTX
        elif is_concise:
            answer_num_predict = 1024
            answer_num_ctx = NUM_CTX
        else:
            answer_num_predict = NUM_PREDICT
            answer_num_ctx = NUM_CTX

        t_llm = time.time()
        response = _ollama_chat(
            model=model_name,
            messages=messages,
            tools=None,
            options={
                "temperature": 0.5,
                "top_p": 0.9,
                "top_k": 40,
                "num_predict": answer_num_predict,
                "num_ctx": answer_num_ctx,
                "think": False,
            },
            keep_alive='1h',
        )
        llm_ms = (time.time() - t_llm) * 1000

        raw_answer = _extract_message_content(response)

        # <USED_SOURCES> 태그에서 사용된 출처 번호 추출
        used_source_indices = _extract_used_sources(raw_answer)

        # 사용된 출처만 필터링
        if used_source_indices is not None:
            # LLM이 명시한 출처만 사용
            filtered_sources = []
            for idx in used_source_indices:
                if 0 <= idx < len(all_sources):
                    filtered_sources.append(all_sources[idx])
            logger.info(f"[3단계] LLM 선별 출처: {used_source_indices} → {len(filtered_sources)}건")
        else:
            # <USED_SOURCES> 태그 없음 → 전체 출처 사용 (fallback)
            filtered_sources = all_sources
            logger.info(f"[3단계] USED_SOURCES 태그 없음, 전체 출처 {len(all_sources)}건 사용")

        # <USED_SOURCES> 태그 제거 + 기존 후처리
        clean_answer = _remove_source_tags(raw_answer)
        finalized = _finalize_user_facing_answer(model_name, user_query, farm_name, clean_answer)

        # URL 검증
        verified_urls = {s.get("url", "") for s in filtered_sources if s.get("url")}
        finalized = _strip_hallucinated_urls(finalized, verified_urls)

        # 카메라 이미지 확정 첨부 — get_camera_view 가 촬영 성공(image_url) 시 실제 영상을
        #   답변에 붙인다. LLM 이 URL 을 흘려도 확실히 표시하려 URL 스트리핑 뒤에 append.
        finalized = _append_camera_image(finalized, tools_used, collected_result)
        finalized = _append_relay_truth(finalized, tools_used, collected_result, user_query)
        finalized = _append_sensor_truth(finalized, tools_used, collected_result, user_query)

        response_type = _determine_response_type(tools_used)

        total_ms = (time.time() - t0) * 1000
        logger.info(
            f"[3단계] 답변 생성 완료: {len(finalized)}자, 출처 {len(filtered_sources)}건 "
            f"(LLM={llm_ms:.0f}ms, 전체={total_ms:.0f}ms) type={response_type}"
        )

        return _build_structured_result(finalized, filtered_sources, tools_used,
                                         tool_calls_detail=tool_calls_detail)

    except Exception as e:
        logger.error(f"[3단계] 답변 생성 오류: {e}")
        logger.error(traceback.format_exc())
        return {
            "response": "죄송합니다. 답변 생성 중 오류가 발생했습니다. 다시 시도해 주세요.",
            "sources": [],
            "tools_used": tools_used if 'tools_used' in dir() else [],
            "response_type": "general",
        }


# ────────────────────────────────────────────────────────────────────
# get_camera_view 촬영 성공 시 실제 카메라 영상을 답변에 마크다운 이미지로 첨부.
#   raw(dict) 또는 raw(json str) 에서 image_url 추출. 중복 첨부 방지.
# ────────────────────────────────────────────────────────────────────
def _append_camera_image(finalized, tools_used, collected_result):
    if "get_camera_view" not in (tools_used or []):
        return finalized
    try:
        url = None
        for d in (collected_result.get("data") or []):
            if d.get("tool") != "get_camera_view":
                continue
            raw = d.get("raw")
            if isinstance(raw, dict):
                url = raw.get("image_url")
            elif isinstance(raw, str) and "image_url" in raw:
                m = re.search(r'"image_url"\s*:\s*"([^"]+)"', raw)
                url = m.group(1) if m else None
            break
        if url and url not in (finalized or ""):
            return f"{finalized}\n\n![재배사 카메라]({url})"
    except Exception as e:
        logger.warning(f"[3단계] 카메라 이미지 첨부 실패: {e}")
    return finalized

# 릴레이 상태 질문에 대해 get_system_status 실측값으로 결정론적 표를 붙인다.
# ⛔ gemma3 가 도구 데이터를 표로 옮기며 ON/OFF 를 오독하는 것(예: 포그 OFF→ON)을
#    코드가 최종 보정. LLM 설명이 틀려도 이 표는 항상 DB 실측과 일치.
_RELAY_Q_RE = re.compile(
    r'릴레이|포그|밸브|흡입팬|배출팬|순환|수온히터|배수|관수|조명|장치\s*상태|제어\s*상태|on[\s/]*off',
    re.I)


def _append_relay_truth(finalized, tools_used, collected_result, user_query):
    if "get_system_status" not in (tools_used or []):
        return finalized
    if not _RELAY_Q_RE.search(user_query or ""):
        return finalized
    if "시스템 실측 릴레이 상태" in (finalized or ""):
        return finalized
    try:
        import json as _json
        houses = []
        for d in (collected_result.get("data") or []):
            if d.get("tool") != "get_system_status":
                continue
            raw = d.get("raw")
            if isinstance(raw, str):
                try:
                    raw = _json.loads(raw)
                except Exception:
                    raw = None
            if isinstance(raw, dict):
                if raw.get("houses"):
                    houses.extend(raw.get("houses") or [])
                for f in (raw.get("farms") or []):
                    if isinstance(f, dict):
                        houses.extend(f.get("houses") or [])
            break
        houses = [h for h in houses if isinstance(h, dict) and (h.get("relay_on") is not None or h.get("relay_off") is not None)]
        if not houses:
            return finalized
        cols = []
        for h in houses:
            for dv in (h.get("relay_on") or []) + (h.get("relay_off") or []):
                if dv not in cols:
                    cols.append(dv)
        if not cols:
            return finalized
        lines = ["", "■ 시스템 실측 릴레이 상태 (자동 검증값 — 위 설명과 다르면 이 표가 정확합니다)", ""]
        lines.append("| 재배사 | " + " | ".join(cols) + " |")
        lines.append("|" + "---|" * (len(cols) + 1))
        for h in houses:
            on = set(h.get("relay_on") or [])
            nm = h.get("name") or h.get("house_id") or "?"
            cells = ["ON" if c in on else "OFF" for c in cols]
            lines.append(f"| {nm} | " + " | ".join(cells) + " |")
        return f"{finalized}\n" + "\n".join(lines)
    except Exception as e:
        logger.warning(f"[3단계] 릴레이 실측표 첨부 실패: {e}")
    return finalized


# 센서 상태 질문에 get_system_status 실측 센서값으로 결정론적 표를 붙인다.
# ⛔ gemma3 가 도구에 센서값이 없거나 헷갈리면 'N/A' 를 지어내던 것(2026-07-26 실측)을
#    코드가 최종 보정 — 센서는 항상 실측되므로 N/A 는 잘못된 표현이다. 값이 없는 센서만 '-'.
_SENSOR_Q_RE = re.compile(
    r'센서|온도|습도|co2|이산화탄소|수온|외기|조도|수위|환경\s*값|측정', re.I)
_SENSOR_COLS = [
    ("indoor_temperature", "실내온도(℃)", 1),
    ("indoor_humidity", "실내습도(%)", 0),
    ("co2", "CO2(ppm)", 0),
    ("water_temperature", "수온(℃)", 1),
    ("outdoor_temperature", "외기온(℃)", 1),
    ("outdoor_humidity", "외기습도(%)", 0),
]


def _append_sensor_truth(finalized, tools_used, collected_result, user_query):
    if "get_system_status" not in (tools_used or []):
        return finalized
    if not _SENSOR_Q_RE.search(user_query or ""):
        return finalized
    if "시스템 실측 센서값" in (finalized or ""):
        return finalized
    try:
        import json as _json
        houses = []
        for d in (collected_result.get("data") or []):
            if d.get("tool") != "get_system_status":
                continue
            raw = d.get("raw")
            if isinstance(raw, str):
                try:
                    raw = _json.loads(raw)
                except Exception:
                    raw = None
            if isinstance(raw, dict):
                if raw.get("houses"):
                    houses.extend(raw.get("houses") or [])
                for f in (raw.get("farms") or []):
                    if isinstance(f, dict):
                        houses.extend(f.get("houses") or [])
            break
        houses = [h for h in houses if isinstance(h, dict) and isinstance(h.get("sensor"), dict) and h.get("sensor")]
        if not houses:
            return finalized

        def _fmt(v, nd):
            if v is None or v == "":
                return "-"          # 결측 센서만 '-' (⛔ N/A 금지)
            try:
                return f"{round(float(v), nd):g}"
            except (TypeError, ValueError):
                return str(v)

        lines = ["", "■ 시스템 실측 센서값 (자동 검증값 — 위 설명과 다르면 이 표가 정확합니다)", ""]
        lines.append("| 재배사 | " + " | ".join(c[1] for c in _SENSOR_COLS) + " |")
        lines.append("|" + "---|" * (len(_SENSOR_COLS) + 1))
        for h in houses:
            s = h.get("sensor") or {}
            nm = h.get("name") or h.get("house_id") or "?"
            cells = [_fmt(s.get(k), nd) for k, _lab, nd in _SENSOR_COLS]
            lines.append(f"| {nm} | " + " | ".join(cells) + " |")
        return f"{finalized}\n" + "\n".join(lines)
    except Exception as e:
        logger.warning(f"[3단계] 센서 실측표 첨부 실패: {e}")
    return finalized


# ═════════════════════════════════════
# LLM 응답에서 <USED_SOURCES> 태그 파싱
# ═════════════════════════════════════
def _extract_used_sources(raw_answer):
    if not raw_answer:
        return None

    match = re.search(r'<USED_SOURCES>(.*?)</USED_SOURCES>', raw_answer, re.IGNORECASE | re.DOTALL)
    if not match:
        return None

    content = match.group(1).strip()
    if not content:
        return []  # 빈 태그 = 출처 미사용

    indices = []
    for part in content.split(","):
        part = part.strip()
        if part.isdigit():
            indices.append(int(part) - 1)  # 1-based → 0-based 변환

    return indices


# ────────────────────────────────────────────────────────────────────
# 응답에서 <USED_SOURCES> 태그와 내용을 제거
# ────────────────────────────────────────────────────────────────────
def _remove_source_tags(text):
    if not text:
        return text
    return re.sub(r'\s*<USED_SOURCES>.*?</USED_SOURCES>\s*', '', text, flags=re.IGNORECASE | re.DOTALL).strip()


# ══════════════════
# 수집 데이터 포맷
# ══════════════════
def _format_collected_data(collected_result):
    if not collected_result:
        return "(수집된 데이터 없음)"

    data_list = collected_result.get("data", [])
    if not data_list:
        return "(수집된 데이터 없음)"

    parts = []
    for i, item in enumerate(data_list, 1):
        tool = item.get("tool", "unknown")
        result = item.get("result", "")

        tool_display = {
            "search_web": "웹 검색 결과",
            "fetch_url_content": "웹 페이지 본문",
            "get_farm_realtime_data": "센서/릴레이 실시간 데이터",
            "search_farm_knowledge": "농장 지식 검색 결과",
            "control_relay": "릴레이 제어 결과",
            "delete_farm_knowledge": "학습 데이터 삭제 결과",
        }.get(tool, tool)

        parts.append(f"--- [{i}] {tool_display} ---\n{result}")

    return "\n\n".join(parts)


# ══════════════════════════
# 인사 — LLM 호출 없는 정형 응답
# Ollama 가 환경제어/agent 사이클 처리 중이면 LLM 큐 대기로 응답 hang.
# 인사는 정형 응답으로 즉시 반환해 사용자 체감 응답 시간 ↓.
# ══════════════════════════
def _greeting_quick_response(user_query, farm_name, speech_style):
    from datetime import datetime
    q = (user_query or "").strip()
    farm_part = f"{farm_name} 농장의 AI 도우미입니다. " if farm_name else ""
    h = datetime.now().hour
    tod = "아침" if 5 <= h < 11 else "낮" if 11 <= h < 18 else "저녁" if 18 <= h < 22 else "밤"

    qlow = q.lower().replace(" ", "")
    if any(t in qlow for t in ['감사', '고마', 'thank']):
        return "감사합니다. 도움이 됐다니 다행입니다."
    if any(t in qlow for t in ['수고', '잘자', '잘있어', 'bye', '안녕히']):
        return "네, 수고하세요. 농장 안전 우선으로 잘 살펴드리겠습니다."
    if any(t in qlow for t in ['좋은아침', '굿모닝', 'morning']):
        return f"좋은 아침입니다. {farm_part}무엇을 도와드릴까요?"
    if any(t in qlow for t in ['좋은하루', '좋은저녁', '좋은밤', '잘지내']):
        return f"좋은 {tod} 보내세요. {farm_part}무엇을 도와드릴까요?"
    # 일반 인사 (안녕/hi/hello 등)
    if speech_style == 'female':
        return f"안녕하세요~ {farm_part}무엇을 도와드릴까요?"
    return f"안녕하세요. {farm_part}무엇을 도와드릴까요?"


# ══════════════════════════
# 인사/대화참조 등 단순 응답
# ══════════════════════════
# ────────────────────────────────────────────────────────────────────
# 잡담·친교 전용 응답 — 말벗 페르소나
# - 페르소나 본문은 prompt_chunk 'chat_casual_persona' 가 코드 기본값을 대체
#   (USE_DB_PROMPTS 체계 — 농장주가 채팅 지시로 말투/화제 조정 가능)
# - 과거 관심사 회상(chat_profile.recall) 주입 + 이번 발화 백그라운드 저장
# - temperature 0.8 (표현 다양화 — 제어 LLM 의 0 과 무관한 대화 모드 전용)
# ────────────────────────────────────────────────────────────────────
CASUAL_PERSONA_RAW = (
    "당신은 {farm} 농장주님의 오랜 친구 같은 말벗 AI입니다. 지금은 업무가 아니라 "
    "편한 잡담 시간입니다.\n"
    "{tone}\n"
    "대화 원칙:\n"
    "- 2~5문장, 따뜻하고 생기있게. 마지막은 대화가 이어지도록 자연스러운 되물음이나 공감으로.\n"
    "- 화제를 풍부하게: 상황버섯·농사 상식, 계절과 시골 풍경, 정읍·고흥 지역 이야기, "
    "여행길 말동무, 가벼운 유머나 퀴즈, 농장주님 근황 되묻기 등 상황에 맞게 골라 쓰세요.\n"
    "- 같은 인사말·상투구 반복 금지. \"필요한 정보가 있으시면 말씀해주세요\" 같은 업무 마무리 금지.\n"
    "- 농장 데이터·제어 얘기는 농장주님이 먼저 꺼내지 않는 한 하지 마세요 "
    "(꺼내면 \"확인해 드릴까요?\"로 자연스럽게 업무 전환 제안만).\n"
    "- 모르는 사실을 지어내지 마세요. 내부 추론/think 태그 금지, 순수 답변만 출력.\n/no_think"
)


def _get_casual_persona(farm_name, tone):
    import os as _os
    raw = CASUAL_PERSONA_RAW
    if _os.getenv("USE_DB_PROMPTS", "0") == "1":
        try:
            from agri_ai_core.src.prompt_registry import get_chunk_by_id as _get
            db_text = _get("chat_casual_persona")
            if db_text:
                raw = db_text
        except Exception:
            pass
    return raw.replace("{farm}", farm_name or "우리").replace("{tone}", tone)


def _generate_casual_response(user_query, conversation_history, farm_name, speech_style):
    try:
        from agri_ai_core.src.ai.llm_client import (
            _ollama_chat, _get_model_name, _extract_message_content,
            _finalize_user_facing_answer, _build_structured_result,
            _build_conversation_context,
        )
        from agri_ai_core.src.ai import chat_profile

        model_name = _get_model_name()
        if speech_style == "female":
            tone = "부드러운 해요체(~예요, ~네요, ~해요)로 따뜻하게. 물결(~)을 자연스럽게 사용."
        else:
            tone = "존댓말(~합니다, ~입니다)로 친근하고 편안하게."

        system_prompt = _get_casual_persona(farm_name, tone)

        # 과거 관심사 회상 주입 (없으면 생략)
        interests = chat_profile.recall(user_query)
        if interests:
            system_prompt += "\n\n" + interests

        messages = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            _build_conversation_context(messages, conversation_history, user_query)
        messages.append({"role": "user", "content": user_query})

        response = _ollama_chat(
            model=model_name, messages=messages, tools=None,
            options={"temperature": 0.8, "top_p": 0.95, "num_predict": 512,
                     "num_ctx": NUM_CTX, "think": False},
            keep_alive='1h',
        )
        raw = _extract_message_content(response)
        finalized = _finalize_user_facing_answer(model_name, user_query, farm_name, raw)

        # 이번 발화를 관심사로 축적 (백그라운드, 실패 무시)
        chat_profile.remember_async(user_query)

        result = _build_structured_result(finalized, [], [])
        result["response_type"] = "casual_chat"
        return result
    except Exception as e:
        logger.error(f"[3단계] 잡담 응답 오류: {e}")
        return {"response": "네~ 말씀 편하게 이어가 주세요!", "sources": [],
                "tools_used": [], "response_type": "casual_chat"}


def _generate_simple_response(user_query, conversation_history, farm_name, speech_style, response_type):
    # 절대 룰 — ANALYZER LLM 이 greeting 으로 분류한
    # 케이스 (애매한 자연어, 예: "안녕.. 오늘 날씨는?") 까지 키워드 응답하면 안 됨.
    # query_handler_simple 의 fast_classify (단독 일상 인사) 만 키워드 우회 허용.
    # 여기는 ANALYZER 결과로 진입한 케이스 → 모두 LLM 합성으로 답변.
    try:
        from agri_ai_core.src.ai.llm_client import (
            _ollama_chat, _get_model_name, _extract_message_content,
            _finalize_user_facing_answer, _build_structured_result,
            _build_conversation_context,
        )

        model_name = _get_model_name()

        if speech_style == "female":
            tone = "부드러운 해요체(~예요, ~네요, ~해요)로 따뜻하게 응대하세요. 물결(~)을 자연스럽게 사용하세요."
        else:
            tone = "존댓말(~합니다, ~입니다)로 친절하게 응대하세요."

        if response_type == "conversation_ref":
            task = (
                "사용자가 이전 대화의 내용을 다시 묻거나, 이전 답변을 다른 형식(표/요약/자세히/간단히)으로 "
                "재표현해 달라고 요청하고 있습니다.\n"
                "[직전 대화 맥락]의 마지막 assistant 답변에 포함된 모든 수치·센서값·재배사 이름·상태 판단을 "
                "**그대로 유지**한 채, 사용자가 원하는 형식으로만 재구성하세요.\n"
                "**절대 규칙:**\n"
                "- 이전 답변에 없는 숫자·항목을 새로 만들어내지 마세요(환각 금지).\n"
                "- 이전 답변의 숫자를 다른 값으로 바꾸거나 반올림하지 마세요.\n"
                "- 이전 답변에 포함된 재배사 전부를 그대로 포함하세요(1호만·일부만 금지).\n"
                "- 새로운 도구 호출·실시간 조회 없이, 이전 맥락만으로 재구성하세요."
            )
            num_predict = NUM_PREDICT
            temperature = 0.2  # 재포맷은 결정적으로 (환각 억제)
        else:
            task = "인사나 일상 대화에 짧고 따뜻하게 응답하세요."
            num_predict = 256
            temperature = 0.7

        system_prompt = (
            f"당신은 {farm_name + ' 농장의 ' if farm_name else ''}AI 도우미입니다.\n"
            f"{tone}\n{task}\n"
            "내부 추론/think 태그 사용 금지. 순수 답변만 출력.\n/no_think"
        )

        messages = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            _build_conversation_context(messages, conversation_history, user_query)
        messages.append({"role": "user", "content": user_query})

        response = _ollama_chat(
            model=model_name, messages=messages, tools=None,
            options={"temperature": temperature, "num_predict": num_predict, "num_ctx": NUM_CTX, "think": False},
            keep_alive='1h',
        )

        raw = _extract_message_content(response)
        finalized = _finalize_user_facing_answer(model_name, user_query, farm_name, raw)
        return _build_structured_result(finalized, [], [])

    except Exception as e:
        logger.error(f"[3단계] 단순 응답 오류: {e}")
        fallback = "안녕하세요!" if response_type == "greeting" else "이전 대화 내용을 확인하지 못했습니다."
        return {"response": fallback, "sources": [], "tools_used": [], "response_type": "general"}
