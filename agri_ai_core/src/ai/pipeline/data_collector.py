# ══════════════════════════════════════════════════════════════════════════════════
# 2단계 데이터 수집: 도구 실행 및 LLM 기반 충분성 판단.
# --->
# __init__: init
# collect: 메인 수집 + LLM 검증 루프
# _execute_tasks: 태스크 리스트를 순차 실행하고 결과를 수집
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
import time
import traceback
from urllib.parse import quote, urlparse, urlunparse, parse_qs, urlencode

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.utils.json_utils import safe_json_load

logger = setup_logger(__name__)

_MAX_SUPPLEMENT_ROUNDS = 1   # 보충 수집은 1라운드만: 보충 후 무조건 3단계 진행
_RULE_SUFFICIENT_BYTES = 6000  # 수집 데이터 총 길이 이상이면 LLM 검증 없이 통과


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

    def __init__(self, default_tool_args, progress_callback=None):
        self.default_tool_args = default_tool_args or {}
        self.progress_callback = progress_callback
        self.collected_data = []
        self.collected_sources = []
        self.tools_used = []
        self._last_merged_args = {}
        self._executed_tool_keys = set()  # (tool_name, query_key) 중복 실행 방지

    def collect(self, analysis_result):
        """메인 수집 + LLM 검증 루프"""
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

        # 실행형 유형(제어/삭제)은 결과가 success/fail로 명확 → LLM 검증 스킵
        _skip_validation_types = ("farm_control", "farm_knowledge_delete")
        if question_type in _skip_validation_types:
            logger.info(f"[2단계] 실행형 유형({question_type}) → LLM 검증 스킵")
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

            # Rule-based 사전 통과: 수집 데이터가 충분히 많으면 LLM 검증 생략
            _total_bytes = sum(len(d.get("result", "")) for d in self.collected_data)
            if _total_bytes >= _RULE_SUFFICIENT_BYTES:
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
        """태스크 리스트를 순차 실행하고 결과를 수집"""
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
            ]
            _exec_key = (tool_name, "|".join(_ident_parts))
            if _exec_key in self._executed_tool_keys:
                logger.info(f"[2단계] {tool_name}(key={_exec_key[1]!r}) 이미 실행됨, 건너뜀")
                continue
            self._executed_tool_keys.add(_exec_key)

            self._report_progress(f"{self._tool_display(tool_name)} 중...", "data_collecting", tool_name)
            raw_result, refined_result = self._execute_single_tool(tool_name, tool_args, user_query)

            if refined_result and len(refined_result.strip()) > 10:
                self._add_result(tool_name, refined_result, raw_result)
                self._collect_sources(tool_name, raw_result)
            else:
                logger.info(f"[2단계] {tool_name} 결과 없음/부실")

    def _execute_single_tool(self, tool_name, tool_args, user_query):
        """단일 도구 실행 + 결과 정제"""
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

    def _merge_args(self, tool_name, task_args):
        """도구별 기본 인자와 태스크 인자를 병합"""
        defaults = self.default_tool_args.get(tool_name, {})
        merged = dict(defaults)
        for key, value in task_args.items():
            if key in ("url_hint", "url_selector", "fallback_urls", "reason"):
                continue
            if value is not None and value != "":
                merged[key] = value

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

    @staticmethod
    def _encode_url(url):
        """한글 포함 URL을 percent-encoding"""
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
        """수집된 search_web 결과에서 URL 목록을 추출하여 LLM에 제공"""
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

    def _extract_all_search_sources(self, raw_result):
        """search_web 결과의 모든 출처를 수집 (최대 5건)"""
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

    def _add_fetch_source(self, url):
        """fetch_url 출처 추가"""
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
        if not multi_house or not house_ids:
            return list(required_data)
        actual_ids = ["1", "2", "3"] if "all" in house_ids else house_ids
        expanded = []
        for task in required_data:
            tool = task.get("tool", "")
            if tool == "get_farm_realtime_data" and len(actual_ids) > 1:
                for hid in actual_ids:
                    new_task = dict(task)
                    new_args = dict(task.get("args", {}))
                    new_args["house_id"] = hid
                    new_task["args"] = new_args
                    expanded.append(new_task)
            else:
                expanded.append(task)
        return expanded

    # ════════════════════════════════════════════════════════════
    # 헬퍼
    # ════════════════════════════════════════════════════════════
    def _add_result(self, tool_name, refined, raw):
        self.collected_data.append({"tool": tool_name, "result": refined, "raw": raw})
        if tool_name not in self.tools_used:
            self.tools_used.append(tool_name)

    def _build_result(self):
        return {
            "data": self.collected_data,
            "sources": self.collected_sources,
            "tools_used": self.tools_used,
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
            "delete_farm_knowledge": "학습 데이터 삭제", "search_gas_price": "주유소 가격 조회",
        }.get(tool_name, tool_name)
