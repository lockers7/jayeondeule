# ══════════════════════════════════════════════════════════
# LLM 응답 후처리 모듈 — 도구 결과 정제, 응답 필터링, 마크다운 표 정렬.
# ══════════════════════════════════════════════════════════
import os
import re
import json
import unicodedata
from typing import Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# 환경 변수 설정 (웹 검색 결과 정제)
# ══════════════════════════════════════════════════════════
_SEARCH_WEB_REFINE_MAX_RESULTS = max(1, int(os.getenv("SEARCH_WEB_REFINE_MAX_RESULTS", "5")))
_SEARCH_WEB_REFINE_DESC_CHARS = max(80, int(os.getenv("SEARCH_WEB_REFINE_DESC_CHARS", "200")))
_SEARCH_WEB_REFINE_CONTENT_CHARS = max(120, int(os.getenv("SEARCH_WEB_REFINE_CONTENT_CHARS", "400")))
_SEARCH_WEB_REFINE_TOTAL_CHARS = max(1000, int(os.getenv("SEARCH_WEB_REFINE_TOTAL_CHARS", "3200")))

# 노이즈 라인 패턴
# ══════════════════════════════════════════════════════════
_NOISE_LINE_RE = re.compile(
    r"^(검색|로그인|회원가입|메뉴|홈|공유|댓글|구독|광고|쿠키|Copyright|All rights)"
)

# 센서 필드 한글 약어 매핑 (토큰 절감)
_SENSOR_SHORT = {
    "indoor_temperature": "실내온도",
    "indoor_humidity": "실내습도",
    "outdoor_temperature": "외부온도",
    "outdoor_humidity": "외부습도",
    "co2": "CO2",
    "water_temperature": "수온",
    "light_level": "조도",
    "water_level": "수위",
}

# 네비게이션 잡음 패턴 (웹 스크래핑 아티팩트)
_NAV_NOISE_RE = re.compile(
    r"(본문\s*바로가기|주메뉴\s*바로가기|태극기\s*이\s*누리집|국가상징\s*알아보기"
    r"|화면크기\s*작게|통합로그인|전체메뉴|로그인\s*로그아웃|로그인\s*회원가입"
    r"|내\s*검색\s*검색\s*관리\s*글쓰기|메뉴\s*홈\s*태그\s*방명록"
    r"|반응형\s*&nbsp;|본문\s*바로가기\s*글루타민)"
)

# LLM 답변 생성에 불필요한 metadata 키 (출처 표시에 필요한 title, url은 유지)
_UNNECESSARY_META_KEYS = {
    "record_datetime", "data_kind", "distance", "collection", "query",
    "learning_date", "chunk_id", "file_size", "total_chunks",
    "is_learned_flag", "processing_time", "processing_date", "farm_id",
    "file_extension", "document_type", "crop_name",
}

# 허위 URL 링크 필터링 패턴
_HALLUCINATED_URL_RE = re.compile(
    r'\[([^\]]*)\]\(https?://(?:example\.com|placeholder|dummy|fake|localhost)[^\)]*\)',
)
_MARKDOWN_URL_RE = re.compile(
    r'\[([^\]]*출처[^\]]*|[^\]]*)\]\(https?://[^\)]+\)',
)


# 페이지 본문에서 노이즈 제거 후 도입부 추출 (키워드 불필요, LLM이 관련성 판단).
# ══════════════════════════════════════════════════════════
def _clean_page_content(text: str, max_chars: int) -> str:
    if not text or not text.strip():
        return ""
    paragraphs = re.split(r"\n{2,}", text)
    if len(paragraphs) <= 1:
        paragraphs = text.split("\n")
    clean = [p.strip() for p in paragraphs
             if len(p.strip()) >= 10 and not _NOISE_LINE_RE.match(p.strip())]
    if not clean:
        return text[:max_chars].strip()
    result, total = [], 0
    for p in clean:
        if total + len(p) > max_chars:
            remaining = max_chars - total
            if remaining > 50:
                result.append(p[:remaining].strip())
            break
        result.append(p)
        total += len(p) + 1
    return "\n".join(result)


# search_web 결과를 구조적으로 정제하여 간결한 텍스트로 변환한다 (LLM이 관련성 판단).
# 출처 목록은 LLM이 보는 결과와 동일하게 구성 (별도 키워드 필터 없음).
# Returns: tuple(정제된 텍스트, 출처 리스트[{title, url}])
# ══════════════════════════════════════════════════════════
def _refine_search_web(tool_result: str, user_query: str) -> tuple:
    empty_sources = []
    try:
        data = json.loads(tool_result)
    except (json.JSONDecodeError, TypeError):
        return tool_result, empty_sources

    results = data.get("results", [])
    if not results:
        return tool_result, empty_sources

    selected_results = results[:_SEARCH_WEB_REFINE_MAX_RESULTS]

    # 출처 목록 = LLM이 보는 selected_results와 동일 (별도 키워드 필터 없음)
    filtered_sources = []
    for item in selected_results:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        if title and url:
            filtered_sources.append({"title": title, "url": url})

    lines = [f"[웹검색 결과 {len(results)}건 중 상위 {len(selected_results)}건]", ""]

    for idx, item in enumerate(selected_results, 1):
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        description = (item.get("description") or "").strip()
        page_content = (item.get("page_content") or "").strip()

        lines.append(f"{idx}. 제목: {title}")
        if url:
            lines.append(f"   URL: {url}")
        if description:
            lines.append(f"   요약: {description[:_SEARCH_WEB_REFINE_DESC_CHARS]}")
        if page_content:
            cleaned = _clean_page_content(page_content, _SEARCH_WEB_REFINE_CONTENT_CHARS)
            if cleaned:
                lines.append(f"   본문: {cleaned}")
        lines.append("")

    lines.append(
        "지시: 위 검색 결과를 종합하여 사용자의 원래 질문에 정확히 맞는 답변을 작성하세요. "
        "사용자가 'N곳/N개' 등 구체적 개수를 요청했다면 해당 개수만큼 번호를 매겨 리스트로 답변하되, "
        "검색 결과에서 확인된 것이 부족하면 확인된 것만 답변하고 나머지는 '추가 검색이 필요합니다'라고 안내하세요. "
        "검색 결과에서 핵심 수치, 날짜, 사실 정보를 추출하여 답변에 반드시 포함하세요. "
        "절대 규칙: 위 검색 결과의 제목/URL/요약/본문에 명시적으로 언급된 장소명, 시설명, 주소만 사용하세요. "
        "검색 결과에 없는 장소, 시설, 공원, 교육장, 주소, 전화번호를 만들어내는 것은 엄격히 금지합니다. "
        "검색 결과에 없는 정보를 추측하거나 일반 지식으로 보충하지 마세요."
    )

    refined_text = "\n".join(lines)
    if len(refined_text) > _SEARCH_WEB_REFINE_TOTAL_CHARS:
        refined_text = refined_text[:_SEARCH_WEB_REFINE_TOTAL_CHARS].rstrip() + "\n...(중략)..."
    return refined_text, filtered_sources


# fetch_url_content 결과를 구조적으로 정제한다 (LLM이 관련성 판단).
# ══════════════════════════════════════════════════════════
def _refine_fetch_url(tool_result: str, user_query: str) -> str:
    try:
        data = json.loads(tool_result)
    except (json.JSONDecodeError, TypeError):
        return tool_result

    content = (data.get("content") or "").strip()
    if not content or len(content) <= 2000:
        return tool_result

    refined = _clean_page_content(content, 2000)

    url = data.get("url", "")
    lines = [
        "[URL 본문 정제]",
        f"URL: {url}",
        "본문:",
        refined,
    ]
    return "\n".join(lines)


def _refine_realtime_data(tool_result: str) -> str:
    """get_farm_realtime_data 결과를 컴팩트 텍스트로 변환.
    ~1.5KB JSON → 압축하여 LLM 컨텍스트 절감.
    - 조회시각 생략 (모든 재배사 동일하므로 중복 제거)
    - OFF 장치 목록 생략 (ON만 표시, 나머지는 OFF로 추론 가능)
    - environment_thresholds: 환경 제어 임계값 (적정 범위) 보존
    - ai_environment_judgment: AI 알고리즘 권장 릴레이 상태 보존
    """
    try:
        data = json.loads(tool_result)
    except (json.JSONDecodeError, TypeError):
        return tool_result

    if not data.get("success"):
        return tool_result

    house_id = data.get("house_id", "?")
    parts = [f"[{house_id}호재배사]"]

    # 센서 데이터 압축
    sensor = data.get("sensor")
    if sensor and isinstance(sensor, dict):
        sensor_items = []
        for key, label in _SENSOR_SHORT.items():
            val = sensor.get(key)
            if val is not None:
                sensor_items.append(f"{label}={val}")
        if sensor_items:
            parts.append("센서: " + ", ".join(sensor_items))

    # 환경 제어 임계값 (적정 범위) — LLM이 센서값 적정 여부 판단에 필수
    # ※ 적정범위는 모든 재배사 공통이므로 병합 시 중복 제거 가능하도록 고정 접두어 사용
    thresholds = data.get("environment_thresholds")
    if thresholds and isinstance(thresholds, dict):
        th_items = []
        for key, th in thresholds.items():
            if isinstance(th, dict):
                label = _SENSOR_SHORT.get(key, key)
                unit = th.get("unit", "")
                th_items.append(f"{label}: 적정{th.get('low','')}{unit}~{th.get('high','')}{unit}, 비상저{th.get('critical_low','')}{unit}/비상고{th.get('critical_high','')}{unit}")
        if th_items:
            parts.append("적정범위(공통): " + ", ".join(th_items))

    # 릴레이 데이터 압축 (relay_mapping 사용 → ON/OFF 장치명)
    relay_mapping = data.get("relay_mapping")
    if relay_mapping and isinstance(relay_mapping, dict):
        on_devices = []
        off_devices = []
        for pin_key, info in relay_mapping.items():
            if isinstance(info, dict):
                label = info.get("name", info.get("device", pin_key))
                if info.get("value"):
                    on_devices.append(label)
                else:
                    off_devices.append(label)
        if on_devices:
            parts.append("ON: " + ", ".join(on_devices))
        if off_devices:
            parts.append("OFF: " + ", ".join(off_devices))
    elif data.get("relay") and isinstance(data["relay"], dict):
        on_pins = [k for k, v in data["relay"].items()
                   if k.startswith("relay_") and k.endswith("_flag") and v]
        off_pins = [k for k, v in data["relay"].items()
                    if k.startswith("relay_") and k.endswith("_flag") and not v]
        if on_pins:
            parts.append(f"ON: {', '.join(on_pins)}")
        if off_pins:
            parts.append(f"OFF: {', '.join(off_pins)}")

    # AI 환경 판단 (알고리즘 권장 릴레이 상태) — 제어값 비교용
    ai_judgment = data.get("ai_environment_judgment")
    if ai_judgment and isinstance(ai_judgment, dict):
        reason = ai_judgment.get("reason", "")
        device_summary = ai_judgment.get("device_summary", "")
        circulation = ai_judgment.get("circulation", "")
        judge_parts = []
        if reason:
            judge_parts.append(f"판단: {reason}")
        if device_summary:
            judge_parts.append(f"권장장치: {device_summary}")
        if circulation:
            judge_parts.append(f"순환모드: {circulation}")
        if judge_parts:
            parts.append("AI알고리즘권장: " + ", ".join(judge_parts))

    return " | ".join(parts)


# 도구 결과를 LLM 메시지에 넣기 전에 도구별 지능형 정제를 수행한다.
# ══════════════════════════════════════════════════════════
def _refine_tool_result(tool_name: str, tool_result: str, user_query: str) -> str:
    if not tool_result:
        return tool_result or ""
    if tool_name == "search_web":
        refined_text, _ = _refine_search_web(tool_result, user_query)
        return refined_text
    if tool_name == "fetch_url_content":
        return _refine_fetch_url(tool_result, user_query)
    if tool_name == "search_farm_knowledge":
        return _refine_farm_knowledge(tool_result)
    if tool_name == "get_farm_realtime_data":
        return _refine_realtime_data(tool_result)
    return tool_result


def _strip_nav_noise(text: str) -> str:
    """웹 스크래핑 네비게이션 잡음을 제거한다."""
    if not text:
        return text
    # 네비게이션 패턴 이후 텍스트를 잘라냄
    parts = _NAV_NOISE_RE.split(text)
    if len(parts) <= 1:
        return text
    # 네비게이션 시작 전까지만 유지
    cleaned = parts[0].rstrip()
    return cleaned if len(cleaned) > 30 else text


def _refine_farm_knowledge(tool_result: str) -> str:
    """search_farm_knowledge 결과를 경량화한다.
    - description이 content와 중복이면 제거
    - 불필요한 metadata 키 제거
    - 네비게이션 잡음 제거
    - content 개별 항목 5000자 제한 + 전체 결과 20000자 제한 (A4 30장 대응)
    기존: 1500자 제한 → A4 1장도 못 채우는 빈약한 답변
    변경: 20000자로 확장하여 대용량 문서 학습 내용 기반 상세 답변 지원
    """
    # 참조 자료 크기 고정 — num_ctx(16384)에서 시스템프롬프트+대화+도구결과+답변 공간 확보
    # 시스템프롬프트 ~3000토큰 + 대화 ~2000토큰 + 답변 ~8192토큰 = ~13000 → 참조 자료 ~3000토큰 ≈ 4500자
    _MAX_TOTAL_REFINED = 4500   # 전체 참조 자료 최대 (3/14 안정화 1500 → RAG 대응 4500)
    _MAX_CONTENT_PER_ITEM = 1500  # 개별 항목 content 최대

    try:
        data = json.loads(tool_result)
    except (json.JSONDecodeError, TypeError):
        return tool_result[:_MAX_TOTAL_REFINED] if len(tool_result or "") > _MAX_TOTAL_REFINED else (tool_result or "")

    results = data.get("results")
    if not results or not isinstance(results, list):
        return tool_result[:_MAX_TOTAL_REFINED] if len(tool_result or "") > _MAX_TOTAL_REFINED else (tool_result or "")

    # 동일 content가 document/farm_knowledge 두 컬렉션에 중복 포함되는 경우 제거
    seen_contents: set = set()
    deduped = []
    for item in results:
        content_key = (item.get("content") or "")[:100]
        if content_key and content_key in seen_contents:
            continue
        seen_contents.add(content_key)
        deduped.append(item)
    data["results"] = deduped
    results = deduped

    # 결과가 많으면(파일명 검색 등) content를 하나로 합쳐 전달 — 메타데이터 오버헤드 제거
    if len(results) > 5:
        merged_content = ""
        first_meta = {}
        for item in results:
            content = _strip_nav_noise(item.get("content", ""))
            if content:
                merged_content += content + "\n\n"
            if not first_meta:
                first_meta = {k: v for k, v in item.get("metadata", {}).items()
                              if k not in _UNNECESSARY_META_KEYS}
        if len(merged_content) > _MAX_TOTAL_REFINED:
            merged_content = merged_content[:_MAX_TOTAL_REFINED] + "..."
        data["results"] = [{"content": merged_content.strip(), "metadata": first_meta}]
        logger.info(f"[RAG정제] {len(results)}건 → 1건 병합 ({len(merged_content)}자)")
    else:
        for item in results:
            # 1) 네비게이션 잡음 제거
            content = item.get("content", "")
            if content:
                content = _strip_nav_noise(content)
                # 2) 개별 content 길이 제한
                if len(content) > _MAX_CONTENT_PER_ITEM:
                    content = content[:_MAX_CONTENT_PER_ITEM] + "..."
                item["content"] = content

            # 3) description이 content와 중복이면 제거
            meta = item.get("metadata", {})
            desc = meta.get("description", "")
            if desc and content and desc[:50] in content:
                del meta["description"]

            # 4) 불필요한 metadata 키 제거
            for key in _UNNECESSARY_META_KEYS:
                meta.pop(key, None)

    # [FIX] file_list가 있으면 (메타 질문: 학습/파일/목록 등) 파일 목록을 우선 포함
    # file_list 중심으로 전달하고, results(검색 내용)는 최소화하여 LLM이 file_list에 집중하도록 함
    _file_list = data.get("file_list")
    if _file_list and isinstance(_file_list, list):
        # results에서 growth_rag 제거 (파일 목록 질문에 센서 데이터 혼입 방지)
        data["results"] = [
            r for r in data.get("results", [])
            if (r.get("metadata") or {}).get("data_type") != "growth_rag"
        ][:3]  # 최대 3건만 유지 (file_list가 주요 정보)
        for item in data.get("results", []):
            c = item.get("content", "")
            if len(c) > 500:
                item["content"] = c[:500] + "..."
        refined = json.dumps(data, ensure_ascii=False)
        if len(refined) > _MAX_TOTAL_REFINED:
            data["results"] = []
            refined = json.dumps(data, ensure_ascii=False)
        return refined

    refined = json.dumps(data, ensure_ascii=False)
    if len(refined) > _MAX_TOTAL_REFINED:
        refined = refined[:_MAX_TOTAL_REFINED] + "..."
    return refined


def _finalize_user_facing_answer(
    model_name: str,
    user_query: str,
    farm_name: Optional[str],
    raw_answer: str,
) -> str:
    """LLM 응답 후처리: think 태그 제거 + 기본 포맷 정리만 수행."""
    logger.info(f"[필터링전-원본] len={len(raw_answer or '')}자")
    logger.info(f"[필터링전-원본내용]\n{raw_answer}")

    candidate = clean_llm_response(raw_answer)

    diff = len(raw_answer or '') - len(candidate)
    logger.info(f"[필터링완료] {len(raw_answer or '')}자→{len(candidate)}자 ({diff}자 삭제)")
    logger.info(f"[최종답변내용]\n{candidate}")
    return candidate


# 마크다운 표 정렬 유틸리티 (한글 너비 고려)
# ══════════════════════════════════════════════════════════
def _display_width(text: str) -> int:
    """문자열의 터미널 표시 너비를 계산한다 (한글=2, 영문=1)."""
    width = 0
    for ch in text:
        eaw = unicodedata.east_asian_width(ch)
        width += 2 if eaw in ('W', 'F') else 1
    return width


def _pad_to_width(text: str, target_width: int) -> str:
    """문자열을 target_width 너비로 패딩한다."""
    current = _display_width(text)
    pad = target_width - current
    return text + (' ' * max(0, pad))


# LLM 응답 내 마크다운 표의 컬럼 구분자(|)를 정렬한다 (한글 너비 고려).
# ══════════════════════════════════════════════════════════
def _align_markdown_tables(text: str) -> str:
    """텍스트 내 모든 마크다운 표의 | 구분자 위치를 정렬한다."""
    if '|' not in text:
        return text

    lines = text.split('\n')
    result = []
    i = 0

    while i < len(lines):
        if lines[i].strip().startswith('|') and lines[i].strip().endswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|') and lines[i].strip().endswith('|'):
                table_lines.append(lines[i])
                i += 1

            if len(table_lines) < 2:
                result.extend(table_lines)
                continue

            parsed_rows = []
            separator_indices = []
            for row_idx, row in enumerate(table_lines):
                stripped = row.strip()
                inner = stripped[1:-1] if stripped.startswith('|') and stripped.endswith('|') else stripped
                cells = [c.strip() for c in inner.split('|')]

                is_sep = all(re.match(r'^:?-+:?$', c) for c in cells if c)
                if is_sep:
                    separator_indices.append(row_idx)

                parsed_rows.append(cells)

            if not parsed_rows:
                result.extend(table_lines)
                continue

            max_cols = max(len(row) for row in parsed_rows)
            for row in parsed_rows:
                while len(row) < max_cols:
                    row.append('')

            col_widths = [0] * max_cols
            for row_idx, row in enumerate(parsed_rows):
                if row_idx in separator_indices:
                    continue
                for col_idx, cell in enumerate(row):
                    w = _display_width(cell)
                    if w > col_widths[col_idx]:
                        col_widths[col_idx] = w

            col_widths = [max(w, 3) for w in col_widths]

            for row_idx, row in enumerate(parsed_rows):
                if row_idx in separator_indices:
                    sep_cells = ['-' * col_widths[c] for c in range(max_cols)]
                    result.append('| ' + ' | '.join(sep_cells) + ' |')
                else:
                    padded_cells = [_pad_to_width(row[c], col_widths[c]) for c in range(max_cols)]
                    result.append('| ' + ' | '.join(padded_cells) + ' |')
        else:
            result.append(lines[i])
            i += 1

    return '\n'.join(result)


# LLM 응답 필터링
# ══════════════════════════════════════════════════════════
def clean_llm_response(response_text):
    """LLM 응답 기본 정리: Think 태그 제거, 마크다운 헤더/코드블록 제거, 빈 줄 정리, 표 정렬."""
    if not response_text:
        return response_text

    original_text = response_text
    original_length = len(response_text)

    # 1. Think 태그 제거
    response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'<thinking>.*?</thinking>', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'<think>.*', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'<thinking>.*', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'</?think[^>]*>', '', response_text, flags=re.IGNORECASE)
    response_text = re.sub(r'<meta[^>]*>', '', response_text, flags=re.IGNORECASE)

    # 1-2. SPECIAL 내부 마커 제거 (모델이 학습으로 재생성하는 내부 도구 호출 마커 필터)
    # 예: <SPECIAL_27>search_farm_knowledge[ARGS]{"query": "..."} 형태
    response_text = re.sub(r'<SPECIAL_\d+>.*?(?=\n|$)', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'</?SPECIAL[^>]*>', '', response_text, flags=re.IGNORECASE)

    # 2. 마크다운 헤더 제거
    for hdr in (r"^(### )?Final Answer:?\s*", r"^(### )?Final Output:?\s*",
                r"^(### )?Response:?\s*", r"^(### )?Answer:?\s*", r"^(### )?결론:?\s*"):
        response_text = re.sub(hdr, "", response_text, flags=re.MULTILINE | re.IGNORECASE)

    # 3. 코드 블록 마커 제거
    response_text = re.sub(r"^```[a-zA-Z]*\s*$", "", response_text, flags=re.MULTILINE)
    response_text = re.sub(r"^```\s*$", "", response_text, flags=re.MULTILINE)

    # 4. 출처/참고 섹션 제거 (LLM이 답변 끝에 출처를 붙이는 경우 — 시스템이 별도 표시)
    response_text = re.sub(
        r'\n+(?:#{1,4}\s*)?(?:\*{0,2})(?:출처(?:\s*링크)?|참고\s*(?:링크|자료|문헌)?|References?|Sources?)\s*[:：]?\s*(?:\*{0,2})\s*\n.*$',
        '', response_text, flags=re.DOTALL | re.IGNORECASE
    )

    # 5. 빈 줄 정리 + 다중 공백 축소
    response_text = re.sub(r'(\n\s*){3,}', '\n\n', response_text)
    response_text = re.sub(r'[ \t]{2,}(?!\n)', ' ', response_text)
    response_text = response_text.strip()

    # 5-2. 최종 빈 줄 정리
    response_text = re.sub(r'(\n\s*){3,}', '\n\n', response_text)
    response_text = response_text.strip()

    # 6. 마크다운 표 정렬 (한글 너비 고려, | 위치 일치)
    response_text = _align_markdown_tables(response_text)

    # 7. 과도한 제거 검사 (90% 이상 제거 시 폴백)
    final_length = len(response_text)
    if original_length > 0:
        removal_ratio = (original_length - final_length) / original_length
        if removal_ratio > 0.9:
            logger.warning(f"필터링으로 인해 응답의 {removal_ratio*100:.1f}%가 제거됨")
            if final_length < 10:
                fallback = re.sub(r"<think>.*?</think>\s*", "", original_text, flags=re.DOTALL | re.IGNORECASE)
                if len(fallback.strip()) > final_length:
                    response_text = fallback.strip()
        elif removal_ratio > 0.1:
            removed_chars = original_length - final_length
            logger.debug(f"[필터] LLM 응답 정리: {removed_chars}자 제거 ({original_length} → {final_length})")

    return response_text


def _strip_hallucinated_urls(answer: str, verified_urls: set) -> str:
    """LLM이 만든 가짜 URL을 제거. verified_urls는 도구가 반환한 실제 URL 집합."""
    if not answer or ("http://" not in answer and "https://" not in answer):
        return answer

    # 1단계: example.com 등 명백한 가짜 도메인 제거
    answer = _HALLUCINATED_URL_RE.sub(r'\1', answer)

    # 2단계: 모든 마크다운 링크를 검증된 URL과 대조
    def _check_url(match):
        full = match.group(0)
        url_match = re.search(r'\((https?://[^\)]+)\)', full)
        if url_match:
            url = url_match.group(1)
            # verified_urls가 있으면 도메인 일치 여부로 판단
            if verified_urls:
                for verified in verified_urls:
                    if url.split('/')[2] == verified.split('/')[2]:
                        return full  # 검증된 URL → 유지
            # verified_urls가 비어있으면 = 도구 호출 없이 LLM이 생성한 URL → 제거
        # 링크 텍스트만 남기고 URL 제거
        return match.group(1)
    answer = _MARKDOWN_URL_RE.sub(_check_url, answer)

    return answer
