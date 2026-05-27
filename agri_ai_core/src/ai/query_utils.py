# ════════════════════════════════════════════════════════════════
# 질의 처리 공용 유틸 — 상태/통신 없는 pure helper (query_handler_simple.py 에서 사용)
# 중복 제거, 스트리밍 단위 분할 등.
# --->
# dedupe_list: 순서 유지 중복 제거 (타입 체크 + key 함수 기반)
# split_for_streaming: 긴 텍스트를 자연스러운 구분점에서 청크 단위로 yield
# ════════════════════════════════════════════════════════════════
from typing import Any, Callable, Generator, Iterable, List, Optional, Type


# ────────────────────────────────────────────────────────────────────
# 타입 체크 + key 함수로 순서 유지 중복 제거.
# Args:
#     items: 입력 iterable (None 허용)
#     type_check: isinstance 체크할 타입
#     key_fn: 중복 판정용 key 추출 함수
#     value_fn: 결과 변환 함수 (None이면 원본 그대로)
# ────────────────────────────────────────────────────────────────────
def dedupe_list(items: Optional[Iterable],
                type_check: Type,
                key_fn: Callable[[Any], Any],
                value_fn: Optional[Callable[[Any], Any]] = None) -> List[Any]:
    deduped, seen = [], set()
    for item in items or []:
        if not isinstance(item, type_check):
            continue
        key = key_fn(item)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(value_fn(item) if value_fn else item)
    return deduped


# ────────────────────────────────────────────────────────────────────
# 긴 텍스트를 자연스러운 구분점(줄바꿈/문장부호/쉼표/공백)에서 나누어 yield.
# LLM 답변을 UI로 스트리밍할 때 덩어리 단위로 전송.
# ────────────────────────────────────────────────────────────────────
def split_for_streaming(text: Optional[str], target_size: int = 30) -> Generator[str, None, None]:
    if not text:
        return
    i = 0
    text_len = len(text)
    while i < text_len:
        if i + target_size >= text_len:
            yield text[i:]
            break
        end = i + target_size
        best = -1
        for delim in ['\n', '. ', '? ', '! ', ', ', ' ']:
            pos = text.rfind(delim, i + 5, end + 10)
            if pos > i:
                best = pos + len(delim)
                break
        if best > i:
            yield text[i:best]
            i = best
        else:
            yield text[i:end]
            i = end
