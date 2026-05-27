# ══════════════════════════════════════════════════════════════════════════════════
# 2단계 데이터 수집: 도구 실행 및 LLM 기반 충분성 판단.
# --->
# __init__: init
# collect: 메인 수집 + LLM 검증 루프
# _execute_tasks: 태스크 리스트를 순차 실행하고 결과를 수집
# _ensure_admin_directive: ⛔ 관리자 지속지시 세이프티넷 (누락시 자동 등록/해제)
# _ensure_weather_data: 농장 날씨 질문시 내부 기상청 예보 자동 병행 수집
# _farm_id_from_query: 질문에 언급된 등록 농장명 → farm_id 해석 (DB 기반)
# _file_from_last_source_search: source_read 플레이스홀더 구조용 최다매치 파일
# _execute_single_tool: 단일 도구 실행 + 결과 정제
# _merge_args: 도구별 기본 인자와 태스크 인자를 병합
# _encode_url: 한글 포함 URL을 percent-encoding
# _get_search_result_urls: 수집된 search_web 결과에서 URL 목록을 추출하여 LLM에 제공
# _collect_sources: collect sources
# _extract_all_search_sources: search_web 결과의 모든 출처를 수집 (최대 5건)
# _add_fetch_source: fetch_url 출처 추가
# _expand_multi_house: expand multi house
# _add_result: add result
# _build_result: build result
# _report_progress: report progress
# _tool_display: tool display
# ══════════════════════════════════════════════════════════════════════════════════
import json
import re
import time
import traceback
from urllib.parse import quote, urlparse, urlunparse, parse_qs, urlencode

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.utils.json_utils import safe_json_load

logger = setup_logger(__name__)

_MAX_SUPPLEMENT_ROUNDS = 2   # 보충 2라운드: 웹→판단→MCP 에스컬레이션→판단→답변 성립
_RULE_SUFFICIENT_BYTES = 6000  # 수집 데이터 총 길이 이상이면 LLM 검증 없이 통과

# ⛔ 절대 제거 금지 — 관리자 지속지시 세이프티넷 키워드.
# 사용자가 지속 표현으로 제어를 요청했는데 ANALYZER(LLM)가 set_admin_directive
# 계획을 누락하면 _ensure_admin_directive 가 기계적으로 보장한다.
# 프롬프트 절대규칙 유도만으로는 누락을 막을 수 없어 코드로 보장한다.
_PERSIST_KEYWORDS = (
    "유지", "별도 지시", "별도지시", "지시할 때", "지시할때", "지시가 있을",
    "지시 있을", "계속", "재부팅", "꺼둬", "꺼두", "켜둬", "켜두",
    "다시 켜지", "다시 꺼지",
)
_RELEASE_KEYWORDS = ("해제", "풀어", "취소", "자율로", "자율 판단으로", "복귀")

# 날씨 백스톱 키워드: 농장 날씨 질문은 표현("웹에서 검색" 등)과 무관하게
# 내부 기상청 예보(get_weather_forecast)를 반드시 병행 수집 — 웹검색이 실패해도
# 답변 LLM 이 실데이터를 갖도록 하는 읽기전용 데이터 보강.
_WEATHER_KEYWORDS = ("날씨", "기상", "예보", "기온", "강수", "미세먼지")
_FARM_CONTEXT_KEYWORDS = ("농장", "재배사", "우리 지역", "여기")

# ⛔ 절대 제거 금지 — 운용모드 전환 세이프티넷 패턴 (2026-07-15 실사고:
# LLM 이 house_id='0'(세션값)으로 호출해 0호 거부 → 전환 실패했는데 "전환했다"고 답변).
# 명령형 모드전환 발화만 매칭, 의문형은 제외. 호기 미명시 시 'all'.
_MODE_SWITCH_RE = re.compile(
    r'(인공지능|AI|에이아이|알고리즘|수동|사용자\s*직접입력)\s*(?:제어\s*)?모드\s*(?:로|으로)?\s*'
    r'(전환|변경|바꾸|바꿔|운영|운용|제어|해\s*줘|하라|해라)', re.IGNORECASE)
_MODE_QUESTION_RE = re.compile(r'(어때|어떨까|할까|될까|되나|가능|괜찮|무엇|뭐야|뭔가|\?)')
_MODE_NAME_MAP = (("인공지능", "ai"), ("에이아이", "ai"), ("ai", "ai"),
                  ("알고리즘", "algorithm"), ("직접입력", "manual"), ("수동", "manual"))
_MODE_HOUSE_RE = re.compile(r'(\d+)\s*호')


class DataCollector:
    """
    2단계 데이터 수집 모듈.

    흐름:
    1) 1단계 분석의 required_data에 따라 도구 실행
    2) 수집된 데이터를 LLM에 전달하여 충분성 판단 (검색 결과 URL 포함)
    3) 부족하면 LLM이 제안한 보충 도구를 추가 실행 (최대 2라운드)
    4) 출처는 필터링 없이 전부 수집 → 3단계 LLM이 선별
    5) 시스템 보정(auto_fetch 등) 없음. 모든 판단은 LLM이 수행.
    """

    def __init__(self, default_tool_args, progress_callback=None, raw_user_query=None):
        self.default_tool_args = default_tool_args or {}
        self.progress_callback = progress_callback
        self.raw_user_query = raw_user_query or ""  # 사용자 원문(세이프티넷 키워드 판정용)
        self.collected_data = []
        self.collected_sources = []
        self.tools_used = []
        self.tool_calls_detail = []   # 도구 호출 감사 로그 (tool/args/success/elapsed_ms)
        self._last_merged_args = {}
        self._executed_tool_keys = set()  # (tool_name, query_key) 중복 실행 방지

    # ────────────────────────────────────────────────────────────────────
    # 메인 수집 + LLM 검증 루프
    # ────────────────────────────────────────────────────────────────────
    def collect(self, analysis_result):
        t0 = time.time()
        required_data = analysis_result.get("required_data", [])
        question_type = analysis_result.get("question_type", "general")
        user_query = analysis_result.get("intent", "")
        multi_house = analysis_result.get("multi_house", False)
        house_ids = analysis_result.get("house_ids", [])

        if not required_data:
            return self._build_result()

        # [1] 1단계 계획에 따라 도구 실행
        expanded_tasks = self._expand_multi_house(required_data, multi_house, house_ids)
        sorted_tasks = sorted(expanded_tasks, key=lambda x: x.get("priority", 99))

        self._report_progress("필요한 데이터를 수집하고 있습니다...", "data_collecting")
        self._execute_tasks(sorted_tasks, user_query)

        # ⛔ 절대 제거 금지 — 관리자 지속지시 세이프티넷
        self._ensure_admin_directive(user_query)

        # 농장 날씨 백스톱 — 내부 기상청 예보 병행 수집 (읽기전용)
        self._ensure_weather_data()

        # ⛔ 절대 제거 금지 — 운용모드 전환 세이프티넷
        self._ensure_control_mode()

        # LLM 검증 스킵 대상:
        # 1) 실행형 유형(farm_control/farm_knowledge_delete): success/fail로 결과 명확
        # 2) 확정 데이터 유형(farm_sensor): DB/API 원본 데이터는 자체로 정답
        #    (검증 LLM이 추가로 판단할 여지가 없음 — 수치가 이미 정확)
        _skip_validation_types = (
            "farm_control", "farm_knowledge_delete",
            "farm_sensor",
            "agent_monitor",  # schedule_monitor 도구는 성공/실패가 확정적
        )
        # 추가로, required_data의 모든 도구가 확정적 소스(DB/제어)만 사용했다면 스킵
        _deterministic_tools = {
            "get_farm_realtime_data", "control_relay",
            "delete_farm_knowledge",
        }
        tools_were_deterministic = (
            bool(self.tools_used)
            and all(t in _deterministic_tools for t in self.tools_used)
        )
        # agent_monitor이지만 즉시 센서 조회도 계획된 복합 패턴은 complex여야 함.
        # LLM이 잘못 분류했을 경우 안전망: get_farm_realtime_data가 required_data에 있으면 skip 안 함.
        _has_sensor_in_plan = any(
            d.get("tool") == "get_farm_realtime_data" for d in required_data
        )
        _do_skip = (question_type in _skip_validation_types or tools_were_deterministic) and not (
            question_type == "agent_monitor" and _has_sensor_in_plan
        )
        if _do_skip:
            reason = question_type if question_type in _skip_validation_types else "확정 도구만 사용"
            logger.info(f"[2단계] LLM 검증 스킵 ({reason})")
            total_ms = (time.time() - t0) * 1000
            logger.info(
                f"[2단계] 수집 완료: {len(self.collected_data)}건 데이터, "
                f"{len(self.tools_used)}개 도구, 출처 {len(self.collected_sources)}건 ({total_ms:.0f}ms)"
            )
            return self._build_result()

        # [2] LLM 검증 + 보충 수집 루프
        for round_num in range(_MAX_SUPPLEMENT_ROUNDS):
            if not self.collected_data:
                logger.warning("[2단계] 수집된 데이터 없음, LLM 검증 건너뜀")
                break

            # Rule-based 사전 통과: 수집 데이터가 충분히 많으면 LLM 검증 생략.
            # ⑤ 단, 외부검색형(search_web 사용)은 수집량이 많아도 rule 통과 금지 —
            #    웹 결과 볼륨↑ ≠ 충분(제목·요약만 길 수 있음). LLM 검증을 거쳐 부족하면
            #    MCP 에스컬레이션(mcp_call/manage_mcp_server) 기회를 준다.
            _total_bytes = sum(len(d.get("result", "")) for d in self.collected_data)
            _web_involved = "search_web" in self.tools_used
            if _total_bytes >= _RULE_SUFFICIENT_BYTES and not _web_involved:
                logger.info(
                    f"[2단계] Rule-based 통과: 수집 총량={_total_bytes}자 >= {_RULE_SUFFICIENT_BYTES}자 "
                    f"→ LLM 검증 스킵"
                )
                break

            self._report_progress("수집된 데이터를 검증하고 있습니다...", "validating")
            logger.info(f"[2단계] === LLM 검증 시작 (라운드 {round_num + 1}) ===")

            try:
                from agri_ai_core.src.ai.pipeline.validators import validate_with_llm, summarize_collected_data

                # 수집 데이터 요약 + 검색 결과 URL 목록 포함 (LLM이 fetch할 URL 선택 가능)
                summary = summarize_collected_data(self.collected_data)

                # 검색 결과에서 URL 목록 추출하여 LLM에 제공
                url_list = self._get_search_result_urls()
                if url_list:
                    summary += f"\n\n[검색 결과 URL 목록 (fetch_url_content로 본문 수집 가능)]\n{url_list}"

                validation = validate_with_llm(user_query, analysis_result, summary)

                sufficient = validation.get("sufficient", True)
                reason = validation.get("reason", "")
                supplements = validation.get("supplement", [])

                logger.info(
                    f"[2단계] LLM 검증 결과: sufficient={sufficient} "
                    f"reason=\"{reason[:100]}\" 보충={len(supplements)}건"
                )

                if sufficient:
                    break

                if not supplements:
                    logger.info("[2단계] LLM: 부족하지만 보충 계획 없음, 현재 데이터로 진행")
                    break

                # 부족 → LLM이 제안한 보충 도구 실행
                logger.info(f"[2단계] LLM 보충 수집 (라운드 {round_num + 1}): {len(supplements)}건")
                self._report_progress("LLM 판단에 따라 추가 데이터를 수집하고 있습니다...", "supplementing")
                self._execute_tasks(supplements, user_query)

            except Exception as e:
                logger.error(f"[2단계] LLM 검증 오류: {e}")
                logger.error(traceback.format_exc())
                break  # 검증 실패해도 수집된 데이터로 진행

        total_ms = (time.time() - t0) * 1000
        logger.info(
            f"[2단계] 수집 완료: {len(self.collected_data)}건 데이터, "
            f"{len(self.tools_used)}개 도구, 출처 {len(self.collected_sources)}건 ({total_ms:.0f}ms)"
        )
        return self._build_result()

    # ════════════════════════════════════════════════════════════
    # 도구 실행
    # ════════════════════════════════════════════════════════════
    def _execute_tasks(self, tasks, user_query):
        for task in tasks:
            tool_name = task.get("tool", "")
            tool_args = task.get("args", {})
            if not tool_name:
                continue

            # 동일 (도구+식별자) 조합 중복 실행 방지
            # 도구별 식별자: 검색은 query, URL 수집은 url,
            # 농장 데이터는 farm_id+house_id+data_type (multi_house fan-out 호환)
            _ident_parts = [
                str(tool_args.get("query", "")),
                str(tool_args.get("url", "")),
                str(tool_args.get("farm_id", "")),
                str(tool_args.get("house_id", "")),
                str(tool_args.get("data_type", "")),
                str(tool_args.get("file_name", "")),
                str(tool_args.get("device_name", "")),  # 제어/지시 도구: 장치별 별도 실행 허용
                str(tool_args.get("host", "")),          # 원격 도구: 호스트별 별도 실행(각 라즈베리파이 fan-out)
                str(tool_args.get("command", "")),       # remote_run: 명령별 별도 실행
            ]
            _exec_key = (tool_name, "|".join(_ident_parts))
            if _exec_key in self._executed_tool_keys:
                logger.info(f"[2단계] {tool_name}(key={_exec_key[1]!r}) 이미 실행됨, 건너뜀")
                continue
            self._executed_tool_keys.add(_exec_key)

            # 도구 시작 메시지 (세부 인자 포함)
            start_msg = self._build_tool_start_message(tool_name, task.get("args", {}))
            self._report_progress(start_msg, "data_collecting", tool_name)

            t_start = time.time()
            raw_result, refined_result = self._execute_single_tool(tool_name, tool_args, user_query)
            elapsed = time.time() - t_start

            # 도구 호출 감사 엔트리 기록 (args 에 auth_farm_id 는 보안상 마스킹)
            self._record_tool_call(
                tool_name=tool_name,
                args=self._sanitize_args_for_audit(self._last_merged_args),
                raw_result=raw_result,
                elapsed=elapsed,
                ok=bool(refined_result and len(refined_result.strip()) > 10),
            )

            if refined_result and len(refined_result.strip()) > 10:
                self._add_result(tool_name, refined_result, raw_result)
                self._collect_sources(tool_name, raw_result)
                # 도구 완료 메시지 (결과 요약 + 소요 시간)
                done_msg = self._build_tool_done_message(
                    tool_name, task.get("args", {}), raw_result, elapsed, ok=True,
                )
                self._report_progress(done_msg, "data_collecting", tool_name)
            else:
                logger.info(f"[2단계] {tool_name} 결과 없음/부실")
                done_msg = self._build_tool_done_message(
                    tool_name, task.get("args", {}), raw_result, elapsed, ok=False,
                )
                self._report_progress(done_msg, "data_collecting", tool_name)

    # ────────────────────────────────────────────────────────────────────
    # ⛔ 절대 제거 금지 — 관리자 지속지시 세이프티넷 (등록+해제 양방향)
    #
    # [등록] "유지/별도 지시까지/계속/꺼둬" 등 지속 표현 요청에서 ANALYZER(LLM)가
    #   set_admin_directive 를 누락하면, 성공한 control_relay 의 인자
    #   (farm/house/device/action)를 그대로 복사해 지시 등록을 기계적으로 보장.
    # [해제] "해제/풀어/취소" 등 해제 표현 요청에서 release_admin_directive 를
    #   누락하면, 동일하게 control_relay 인자를 복사해 해제를 보장.
    #   control_relay 조차 없으면(대상 불명) 개입하지 않고 경고만 남긴다.
    #
    # 코드가 새로 판단하는 것은 없다 — 대상·상태는 전부 LLM 이 이미 뽑은 값의
    # 재사용이다. 프롬프트 유도만으로는 불충분하여 결정론적으로 완결한다.
    # ────────────────────────────────────────────────────────────────────
    def _ensure_admin_directive(self, intent):
        # 키워드 판정은 반드시 "사용자 원문"만 사용한다.
        # intent 는 LLM 생성 요약문이라 유지 요청 요약에 "해제/복귀" 류 표현이
        # 섞여 해제로 오판할 수 있다. 원문 부재 시에만 intent 폴백.
        text = self.raw_user_query or (intent or "")
        has_release = any(k in text for k in _RELEASE_KEYWORDS)
        has_persist = any(k in text for k in _PERSIST_KEYWORDS)
        if not (has_release or has_persist):
            return
        already = {c.get("tool") for c in self.tool_calls_detail}
        # 방향별 가드: 반대 방향 도구가 실행됐어도 사용자 의도 방향은 보장해야 함
        # (LLM 이 유지 요청에 release 를 잘못 호출해도 등록은 누락으로 취급)
        if has_release and "release_admin_directive" in already:
            return
        if not has_release and "set_admin_directive" in already:
            return

        relay_calls = [c for c in self.tool_calls_detail
                       if c.get("tool") == "control_relay" and c.get("success")]
        if not relay_calls:
            if has_release:
                # 해제 요청인데 대상 특정 근거(control_relay 인자)가 없음 —
                # 코드가 임의 판단하지 않고 로그만 남긴다 (LLM 재질의 유도)
                logger.warning(
                    f"[세이프티넷] 해제 표현 감지했으나 release 도구·control_relay 모두 미실행 "
                    f"→ 대상 불명, 개입 보류 (query=\"{self.raw_user_query[:60]}\")"
                )
            return

        tasks = []
        for call in relay_calls:
            a = call.get("args") or {}
            devices = a.get("devices") or [{"device_name": a.get("device_name"),
                                            "action": a.get("action")}]
            for d in devices:
                name = (d or {}).get("device_name")
                act = str((d or {}).get("action", "")).strip().lower()
                if not name:
                    continue
                if has_release:
                    # 해제: 상태 불문 — LLM이 특정한 장치·호기의 지시를 해제
                    tasks.append({
                        "tool": "release_admin_directive",
                        "args": {
                            "farm_id": a.get("farm_id"),
                            "house_id": a.get("house_id"),
                            "device_name": name,
                        },
                        "priority": 3,
                    })
                else:
                    if act not in ("on", "off", "켜기", "끄기"):
                        continue  # toggle 등 상태 불명 액션은 지시화하지 않음
                    state = "ON" if act in ("on", "켜기") else "OFF"
                    tasks.append({
                        "tool": "set_admin_directive",
                        "args": {
                            "farm_id": a.get("farm_id"),
                            "house_id": a.get("house_id"),
                            "device_name": name,
                            "state": state,
                            "note": f"지속 지시 자동 보장: {self.raw_user_query[:80]}",
                        },
                        "priority": 3,
                    })

        if not tasks:
            return
        _mode = "해제" if has_release else "등록"
        logger.warning(
            f"[세이프티넷] ANALYZER가 지속 지시 {_mode} 누락 → "
            f"{tasks[0]['tool']} {len(tasks)}건 자동 실행 (query=\"{self.raw_user_query[:60]}\")"
        )
        self._report_progress(f"관리자 지시를 {_mode}하고 있습니다...", "data_collecting")
        self._execute_tasks(tasks, self.raw_user_query or intent)

    # ────────────────────────────────────────────────────────────────────
    # 농장 날씨 백스톱
    # 질문에 날씨 키워드 + 농장 문맥(농장/재배사 단어 또는 실제 농장명)이 있으면
    # get_weather_forecast 를 자동 병행 수집한다. "웹에서 검색해줘" 같은 표현으로
    # ANALYZER 가 웹검색만 계획해 실패해도 실데이터를 확보하는 데이터 보강.
    # 읽기전용 조회라 판단 개입이 아니며, 웹검색 결과와 함께 3단계 LLM 에 전달된다.
    # ────────────────────────────────────────────────────────────────────
    def _ensure_weather_data(self):
        q = self.raw_user_query or ""
        if not any(k in q for k in _WEATHER_KEYWORDS):
            return
        has_farm_ctx = any(k in q for k in _FARM_CONTEXT_KEYWORDS)
        mentioned_fid = self._farm_id_from_query()
        if not (has_farm_ctx or mentioned_fid):
            return
        if any(c.get("tool") == "get_weather_forecast" for c in self.tool_calls_detail):
            return
        # 질문에 등록 농장명이 언급됐으면 그 농장 예보를 조회 (세션 농장 아님)
        args = {"farm_id": mentioned_fid} if mentioned_fid else {}
        logger.info(
            f"[날씨백스톱] 농장 날씨 질문 감지 → get_weather_forecast 자동 병행 수집"
            f"{f' (질문 언급 농장 farm_id={mentioned_fid})' if mentioned_fid else ''}")
        self._execute_tasks(
            [{"tool": "get_weather_forecast", "args": args, "priority": 1}], q)

    # ────────────────────────────────────────────────────────────────────
    # ⛔ 절대 제거 금지 — 운용모드 전환 세이프티넷
    # 명령형 모드전환 발화인데 set_house_control_mode 가 성공하지 못했으면
    # (미호출 또는 house 오인자로 거부) 기계적으로 보장한다. 판정은 사용자 원문만.
    # ────────────────────────────────────────────────────────────────────
    def _ensure_control_mode(self):
        q = self.raw_user_query or ""
        m = _MODE_SWITCH_RE.search(q)
        if not m or _MODE_QUESTION_RE.search(q):
            return
        succeeded = any(c.get("tool") == "set_house_control_mode" and c.get("success")
                        for c in self.tool_calls_detail)
        if succeeded:
            return
        mode = None
        token = m.group(1).lower()
        for name, val in _MODE_NAME_MAP:
            if name in token:
                mode = val
                break
        if not mode:
            return
        houses = _MODE_HOUSE_RE.findall(q) or ["all"]
        tasks = [{"tool": "set_house_control_mode",
                  "args": {"house_id": h, "mode": mode}, "priority": 2}
                 for h in houses]
        logger.warning(
            f"[세이프티넷] 모드전환({mode}) 미이행 감지 → set_house_control_mode "
            f"{[t['args']['house_id'] for t in tasks]} 자동 실행 (query=\"{q[:60]}\")")
        self._report_progress(f"운용모드를 {mode} 로 전환하고 있습니다...", "data_collecting")
        self._execute_tasks(tasks, q)

    # ────────────────────────────────────────────────────────────────────
    # 직전 source_search 결과에서 최다 매치 파일 추출 (source_read 구조용)
    # ────────────────────────────────────────────────────────────────────
    def _file_from_last_source_search(self):
        try:
            for d in reversed(self.collected_data):
                if d.get("tool") != "source_search":
                    continue
                counts = {}
                # raw(JSON) 의 message 우선 — refined 는 LLM 정제로 형식이 깨질 수 있음
                text = ""
                try:
                    parsed = json.loads(d.get("raw") or "")
                    if isinstance(parsed, dict):
                        text = parsed.get("message") or ""
                except Exception:
                    pass
                text = text or d.get("result") or ""
                for line in text.splitlines():
                    m = re.match(r"([\w./#\-]+\.[a-zA-Z]{1,10}):\d+:", line.strip())
                    if m:
                        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
                if counts:
                    return max(counts, key=counts.get)
        except Exception:
            pass
        return None

    # ────────────────────────────────────────────────────────────────────
    # 질문에 언급된 등록 농장명 → farm_id 해석 (DB 기반, 하드코딩 없음)
    # 정확히 1개 농장만 언급됐을 때 그 ID 반환, 그 외(0개/복수)는 None.
    # 예: "고흥뜰에 날씨" → 세션 농장이 아닌 고흥뜰에(2) 를 대상.
    # ────────────────────────────────────────────────────────────────────
    def _farm_id_from_query(self):
        if hasattr(self, "_query_farm_id_cache"):
            return self._query_farm_id_cache
        result = None
        q = self.raw_user_query or ""
        if q:
            try:
                from agri_ai_core.src.postgresql.connection import db_session
                with db_session() as d:
                    rows = d.fetch_all(
                        "SELECT farm_id, farm_name FROM farm_m_info WHERE farm_id != 0",
                        (), as_dict=True) or []
                hits = [str(r["farm_id"]) for r in rows
                        if (r["farm_name"] or "") and r["farm_name"] in q]
                if len(hits) == 1:
                    result = hits[0]
            except Exception:
                result = None
        self._query_farm_id_cache = result
        return result

    # ────────────────────────────────────────────────────────────────────
    # 단일 도구 실행 + 결과 정제
    # ────────────────────────────────────────────────────────────────────
    def _execute_single_tool(self, tool_name, tool_args, user_query):
        try:
            from agri_ai_core.src.ai.tools_executor import execute_tool
            from agri_ai_core.src.ai.llm_client import _refine_tool_result

            merged_args = self._merge_args(tool_name, tool_args)
            if merged_args is None:
                return None, None
            self._last_merged_args = merged_args

            # fetch_url: 한글 URL 인코딩
            if tool_name == "fetch_url_content" and "url" in merged_args:
                merged_args["url"] = self._encode_url(merged_args["url"])

            t = time.time()
            raw_result = execute_tool(tool_name, merged_args)
            elapsed = time.time() - t
            logger.info(f"[2단계] {tool_name} ({elapsed:.1f}s) 결과={len(raw_result or '')}자")

            if not raw_result:
                return None, None

            refined = _refine_tool_result(tool_name, raw_result, user_query)
            return raw_result, refined

        except Exception as e:
            logger.error(f"[2단계] {tool_name} 오류: {e}")
            logger.debug(traceback.format_exc())
            return None, None

    # ────────────────────────────────────────────────────────────────────
    # 도구별 기본 인자와 태스크 인자를 병합
    # ────────────────────────────────────────────────────────────────────
    def _merge_args(self, tool_name, task_args):
        defaults = self.default_tool_args.get(tool_name, {})
        merged = dict(defaults)
        for key, value in task_args.items():
            if key in ("url_hint", "url_selector", "fallback_urls", "reason"):
                continue
            if value is not None and value != "":
                merged[key] = value

        # source_read: ANALYZER 는 계획 시점에 검색 결과를 모르므로 file_path 에
        # "(source_search 결과로 찾은 파일)" 류 플레이스홀더를 넣는 패턴이 있다.
        # 직전 source_search 결과의 최다 매치 파일로 대체한다.
        if tool_name == "source_read":
            fp = str(merged.get("file_path") or "")
            looks_placeholder = (not fp or "(" in fp or "결과" in fp
                                 or not re.search(r"\.[a-zA-Z]{1,10}$", fp))
            if looks_placeholder:
                resolved = self._file_from_last_source_search()
                if resolved:
                    logger.info(f"[2단계] source_read 플레이스홀더 → 검색 최다매치 파일 대체: {resolved}")
                    merged["file_path"] = resolved

        # get_weather_forecast / get_camera_view: 질문에 특정 농장명이 언급되면
        # 그 농장을 대상 (세션/LLM 산출 farm_id 보다 우선 — 예: 시스템(0) 세션에서
        # "자연들에 1호 카메라 봐줘"는 세션농장 0 이 아닌 자연들에(farm 1) 카메라여야 함.
        # 이게 없으면 farm_id=0 으로 FARM_RPI_CAM_URL_0_1 을 찾다 "영상 소스 없음" 실패).
        if tool_name in ("get_weather_forecast", "get_camera_view"):
            _mentioned = self._farm_id_from_query()
            if _mentioned:
                merged["farm_id"] = _mentioned

        # get_camera_view: 시스템(0) 세션에서 농장명 없이 "1호 재배사 카메라"만 물으면
        #   farm_id=0 이 남아 FARM_RPI_CAM_URL_0_1(없음)로 촬영 실패한다. 시스템농장(0)은
        #   실재배사 카메라가 없으므로(0_99 시스템 카메라만) 실농장으로 대체한다.
        #   단 house_id=99(시스템 카메라)는 farm 0 그대로 둔다. (기존 관례: farm0→실농장)
        if tool_name == "get_camera_view":
            _fid = str(merged.get("farm_id") or "").strip()
            _hid = str(merged.get("house_id") or "").strip()
            if _fid in ("", "0") and _hid and _hid != "99":
                _rt = (self.default_tool_args or {}).get("get_farm_realtime_data", {}) or {}
                _real = str(_rt.get("farm_id") or "").strip()
                merged["farm_id"] = _real if (_real and _real != "0") else "1"

        # 기본값 없는 도구에 farm_id/house_id 자동 보충
        if tool_name in ("control_relay",) and "farm_id" not in merged:
            rt = self.default_tool_args.get("get_farm_realtime_data", {})
            if rt.get("farm_id"):
                merged.setdefault("farm_id", rt["farm_id"])
            if rt.get("house_id"):
                merged.setdefault("house_id", rt["house_id"])

        # fetch_url: URL 없으면 실행 불가
        if tool_name == "fetch_url_content" and not merged.get("url"):
            logger.warning(f"[2단계] fetch_url_content URL 누락, 건너뜀")
            return None

        return merged

    # ────────────────────────────────────────────────────────────────────
    # 한글 포함 URL을 percent-encoding
    # ────────────────────────────────────────────────────────────────────
    @staticmethod
    def _encode_url(url):
        if not url:
            return url
        try:
            url.encode('ascii')
            return url
        except UnicodeEncodeError:
            parsed = urlparse(url)
            if parsed.query:
                params = parse_qs(parsed.query, keep_blank_values=True)
                encoded_query = urlencode(params, doseq=True, quote_via=quote)
                return urlunparse(parsed._replace(query=encoded_query))
            return quote(url, safe=':/?&=#')

    # ════════════════════════════════════════════════════════════
    # 검색 결과 URL 추출 (LLM 검증에 제공)
    # ════════════════════════════════════════════════════════════
    def _get_search_result_urls(self):
        urls = []
        for item in self.collected_data:
            if item.get("tool") != "search_web":
                continue
            raw = item.get("raw", "")
            data = safe_json_load(raw) if isinstance(raw, str) else raw
            if not isinstance(data, dict):
                continue
            for r in data.get("results", [])[:5]:
                title = r.get("title", "")
                url = r.get("url", "")
                if url and title:
                    urls.append(f"- {title}: {url}")
        return "\n".join(urls) if urls else ""

    # ════════════════════════════════════════════════════════════
    # 출처 수집 — 필터링 없이 전부 수집 (3단계 LLM이 선별)
    # ════════════════════════════════════════════════════════════
    def _collect_sources(self, tool_name, raw_result):
        if tool_name == "search_web":
            self._extract_all_search_sources(raw_result)
        elif tool_name == "fetch_url_content" and "url" in self._last_merged_args:
            self._add_fetch_source(self._last_merged_args["url"])

    # ────────────────────────────────────────────────────────────────────
    # search_web 결과의 모든 출처를 수집 (최대 5건)
    # ────────────────────────────────────────────────────────────────────
    def _extract_all_search_sources(self, raw_result):
        data = safe_json_load(raw_result) if isinstance(raw_result, str) else raw_result
        if not isinstance(data, dict):
            return
        added = 0
        for item in data.get("results", []):
            if added >= 5:
                break
            title = item.get("title", "")
            url = item.get("url", "")
            if url and title and not any(s.get("url") == url for s in self.collected_sources):
                self.collected_sources.append({"title": title, "url": url})
                added += 1

    # ────────────────────────────────────────────────────────────────────
    # fetch_url 출처 추가
    # ────────────────────────────────────────────────────────────────────
    def _add_fetch_source(self, url):
        if not url:
            return
        title = url
        if "search.naver.com" in url and "날씨" in url:
            title = "네이버 날씨"
        elif "search.naver.com" in url:
            title = "네이버 검색"
        elif "weather.go.kr" in url:
            title = "기상청"
        elif "weather.naver.com" in url:
            title = "네이버 날씨"
        elif "weather.com" in url:
            title = "The Weather Channel"

        if not any(s.get("url") == url for s in self.collected_sources):
            self.collected_sources.insert(0, {"title": title, "url": url})

    # ════════════════════════════════════════════════════════════
    # multi_house 확장
    # ════════════════════════════════════════════════════════════
    def _expand_multi_house(self, required_data, multi_house, house_ids):
        from agri_ai_core.src.ai.tools_utils import get_farm_house_ids

        rt_default = (self.default_tool_args or {}).get("get_farm_realtime_data", {}) or {}
        default_hid = str(rt_default.get("house_id") or "").strip()
        default_fid = str(rt_default.get("farm_id") or "").strip() or None

        def _all_ids_for(farm_id: str) -> list:
            # farm_id=0(시스템농장)은 재배사 없음 → default_fid도 0이면 "1"로 대체
            fid = farm_id if (farm_id and farm_id != "0") else None
            fid = fid or (default_fid if (default_fid and default_fid != "0") else None) or "1"
            ids = get_farm_house_ids(fid)
            return ids or []

        if multi_house and house_ids:
            if "all" in house_ids:
                actual_ids = _all_ids_for(default_fid)
            else:
                actual_ids = [str(h) for h in house_ids]
        else:
            actual_ids = None

        expanded = []
        for task in required_data:
            tool = task.get("tool", "")
            if tool != "get_farm_realtime_data":
                expanded.append(task)
                continue

            args = task.get("args", {}) or {}
            task_hid = str(args.get("house_id") or "").strip()
            task_fid = str(args.get("farm_id") or "").strip() or default_fid

            # 0) 시스템 세션(farm_id=0) = 전체 실농장 대상 — (farm, house) 쌍 fan-out.
            #    같은 호기 번호가 농장마다 있으므로 farm 을 함께 명시해 모호성 제거.
            #    ANALYZER 가 호기 목록을 명시했으면(all 제외) 그 호기들만 전 농장에 적용.
            if (task_fid or "0") == "0" and (default_fid or "0") == "0":
                if actual_ids and "all" not in (house_ids or []):
                    _hf = set(str(h) for h in actual_ids)
                elif task_hid and task_hid not in ("0", "all"):
                    _hf = {task_hid}
                else:
                    _hf = None
                pairs = self._real_farm_house_pairs(house_filter=_hf)
                if pairs:
                    logger.info(
                        f"[2단계] 시스템 세션 → 전체 농장 fan-out {pairs}"
                        f"{f' (houses={sorted(_hf)})' if _hf else ''}")
                    for f, h in pairs:
                        expanded.append(self._clone_task_with_farm_house(task, f, h))
                    continue

            # 1) analyzer 가 명시한 multi_house fan-out
            if actual_ids and len(actual_ids) > 1:
                for h in actual_ids:
                    expanded.append(self._clone_task_with_house(task, h))
                continue

            # 2) task 에 유효 개별 house_id
            if task_hid and task_hid not in ("0", "all"):
                expanded.append(task)
                continue

            # 3) 사이드바 기본값 (merge 단계에서 적용됨)
            if default_hid and default_hid not in ("0", "all"):
                expanded.append(task)
                continue

            # 4) 유효 house_id 없음 → 해당 농장의 전 재배사 fan-out (DB 동적 조회)
            farm_houses = _all_ids_for(task_fid)
            if not farm_houses:
                logger.warning(
                    f"[2단계] 농장(farm_id={task_fid}) 재배사 조회 실패 → 단건 호출 유지"
                )
                expanded.append(task)
                continue

            logger.info(
                f"[2단계] get_farm_realtime_data house_id 미지정 "
                f"(task='{task_hid}', default='{default_hid}', farm={task_fid}) "
                f"→ DB 조회 재배사 {farm_houses} 전체 fan-out"
            )
            for h in farm_houses:
                expanded.append(self._clone_task_with_house(task, h))

        return expanded

    @staticmethod
    def _clone_task_with_house(task, house_id):
        new_task = dict(task)
        new_args = dict(task.get("args", {}) or {})
        new_args["house_id"] = str(house_id)
        new_task["args"] = new_args
        return new_task

    @staticmethod
    def _clone_task_with_farm_house(task, farm_id, house_id):
        new_task = dict(task)
        new_args = dict(task.get("args", {}) or {})
        new_args["farm_id"] = str(farm_id)
        new_args["house_id"] = str(house_id)
        new_task["args"] = new_args
        return new_task

    # ────────────────────────────────────────────────────────────────────
    # 전체 실농장의 (farm_id, house_id) 쌍 — 시스템 세션 fan-out 용.
    # house_filter 지정 시 해당 호기가 있는 농장만.
    # ────────────────────────────────────────────────────────────────────
    def _real_farm_house_pairs(self, house_filter=None):
        try:
            from agri_ai_core.src.postgresql.connection import db_session
            from agri_ai_core.src.ai.tools_utils import get_farm_house_ids
            with db_session() as d:
                rows = d.fetch_all(
                    "SELECT farm_id FROM farm_m_info WHERE farm_id > 0 ORDER BY farm_id",
                    (), as_dict=True) or []
            pairs = []
            for r in rows:
                fid = str(int(r["farm_id"]))
                for h in get_farm_house_ids(fid):
                    if house_filter is None or str(h) in house_filter:
                        pairs.append((fid, str(h)))
            return pairs
        except Exception as e:
            logger.warning(f"[2단계] 전체 농장 (farm,house) 조회 실패: {e}")
            return []

    # ════════════════════════════════════════════════════════════
    # 헬퍼
    # ════════════════════════════════════════════════════════════
    def _add_result(self, tool_name, refined, raw):
        self.collected_data.append({"tool": tool_name, "result": refined, "raw": raw})
        if tool_name not in self.tools_used:
            self.tools_used.append(tool_name)

    # ════════════════════════════════════════════════════════════
    # 도구 호출 감사 로그 수집
    # ════════════════════════════════════════════════════════════
    _AUDIT_MASK_KEYS = ("auth_farm_id",)   # 감사 로그에서 보안상 마스킹할 키

    # ────────────────────────────────────────────────────────────────────
    # 감사 로그용 args 정제 — 보안 키는 '***' 로 마스킹.
    # ────────────────────────────────────────────────────────────────────
    @classmethod
    def _sanitize_args_for_audit(cls, args: dict) -> dict:
        if not args:
            return {}
        out = {}
        for k, v in args.items():
            if k in cls._AUDIT_MASK_KEYS:
                out[k] = "***" if v else None
            else:
                out[k] = v
        return out

    # ────────────────────────────────────────────────────────────────────
    # 도구 호출 1건의 감사 엔트리를 기록한다. 결과 파싱 실패해도 호출 자체는 기록.
    # ────────────────────────────────────────────────────────────────────
    def _record_tool_call(self, tool_name, args, raw_result, elapsed, ok):
        entry = {
            "tool": tool_name,
            "args": args,
            "success": False,
            "elapsed_ms": round(elapsed * 1000, 1),
        }
        # raw_result 는 JSON 문자열; success/error 만 파싱
        try:
            import json
            if raw_result and isinstance(raw_result, str):
                parsed = json.loads(raw_result)
                if isinstance(parsed, dict):
                    entry["success"] = bool(parsed.get("success", ok))
                    if parsed.get("error"):
                        entry["error"] = str(parsed["error"])[:200]
                    # 제어 도구의 경우 대상 재배사 기록
                    for k in ("house_id", "farm_id", "device_name", "action", "mode"):
                        if parsed.get(k):
                            entry[k] = parsed[k]
        except Exception:
            entry["success"] = ok
        self.tool_calls_detail.append(entry)

    def _build_result(self):
        return {
            "data": self.collected_data,
            "sources": self.collected_sources,
            "tools_used": self.tools_used,
            "tool_calls_detail": self.tool_calls_detail,
            "sufficient": len(self.collected_data) > 0,
        }

    def _report_progress(self, message, phase, tool_name=None):
        if self.progress_callback:
            try:
                self.progress_callback(message, phase, tool_name)
            except Exception as e:
                logger.debug(f"[2단계] 진행 콜백 오류: {e}")

    @staticmethod
    def _tool_display(tool_name):
        return {
            "search_web": "웹 검색", "fetch_url_content": "웹 페이지 수집",
            "get_farm_realtime_data": "센서/릴레이 데이터 조회",
            "search_farm_knowledge": "농장 지식 검색", "control_relay": "릴레이 제어",
            "delete_farm_knowledge": "학습 데이터 삭제",
        }.get(tool_name, tool_name)

    # ════════════════════════════════════════════════════════════
    # 진행 상태 메시지 빌더 — 단계별 세부 정보 포함
    # ════════════════════════════════════════════════════════════
    @staticmethod
    def _shorten(text, n=28):
        s = str(text or "").strip()
        return s if len(s) <= n else s[:n] + "…"

    # ────────────────────────────────────────────────────────────────────
    # house_id를 사용자 친화적 라벨로 변환. 'all' → '전 재배사', '1' → '1호 재배사'.
    # ────────────────────────────────────────────────────────────────────
    @staticmethod
    def _house_label(house_id):
        s = str(house_id or "").strip()
        if not s or s == "?":
            return "재배사"
        if s.lower() == "all":
            return "전 재배사"
        return f"{s}호 재배사"

    @classmethod
    def _build_tool_start_message(cls, tool_name, args):
        args = args or {}
        if tool_name == "search_web":
            q = cls._shorten(args.get("query", ""), 32)
            return f"🔍 웹에서 검색 중: \"{q}\""
        if tool_name == "fetch_url_content":
            url = cls._shorten(args.get("url", ""), 42)
            return f"🌐 웹페이지 내용을 가져오는 중: {url}"
        if tool_name == "get_farm_realtime_data":
            house = cls._house_label(args.get("house_id"))
            dt = args.get("data_type", "all")
            label = {"all": "센서+릴레이", "sensor": "센서", "relay": "릴레이"}.get(dt, dt)
            return f"🏡 {house} {label} 데이터 조회 중..."
        if tool_name == "search_farm_knowledge":
            q = cls._shorten(args.get("query", ""), 30)
            return f"📚 학습된 농장 자료 검색 중: \"{q}\""
        if tool_name == "control_relay":
            house = cls._house_label(args.get("house_id"))
            if args.get("devices"):
                n = len(args["devices"])
                return f"🔌 {house} 릴레이 {n}개 동시 제어 중..."
            dev = cls._shorten(args.get("device_name", ""), 18)
            act = args.get("action", "")
            return f"🔌 {house} '{dev}' {act.upper()} 실행 중..."
        if tool_name == "delete_farm_knowledge":
            fn = cls._shorten(args.get("file_name", ""), 32)
            return f"🗑️ 학습 자료 삭제 중: {fn}"
        return f"{cls._tool_display(tool_name)} 중..."

    @classmethod
    def _build_tool_done_message(cls, tool_name, args, raw_result, elapsed, ok):
        args = args or {}
        size = len(raw_result or "")
        t = f"{elapsed:.1f}초"
        if not ok:
            return f"⚠️ {cls._tool_display(tool_name)} 결과 부족 ({t})"
        if tool_name == "search_web":
            # 결과에서 건수 추출 시도 (실패해도 무관)
            try:
                import re
                m = re.search(r"(\d+)\s*건", raw_result or "")
                hits = f"{m.group(1)}건" if m else f"{size}자"
            except Exception:
                hits = f"{size}자"
            return f"✅ 웹 검색 {hits} 수신 ({t})"
        if tool_name == "fetch_url_content":
            url = cls._shorten(args.get("url", ""), 36)
            return f"✅ 웹페이지 본문 {size:,}자 수집 완료 ({t}) — {url}"
        if tool_name == "get_farm_realtime_data":
            house = cls._house_label(args.get("house_id"))
            return f"✅ {house} 데이터 확인 완료 ({t}, {size:,}자)"
        if tool_name == "search_farm_knowledge":
            return f"✅ 농장 자료 검색 완료 ({t}, {size:,}자)"
        if tool_name == "control_relay":
            return f"✅ 릴레이 제어 명령 완료 ({t})"
        if tool_name == "delete_farm_knowledge":
            return f"✅ 학습 자료 삭제 완료 ({t})"
        return f"✅ {cls._tool_display(tool_name)} 완료 ({t})"
