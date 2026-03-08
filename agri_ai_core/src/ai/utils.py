# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# AI 공통 유틸리티
# Think-tag 제거, 한국어 감지 등 여러 모듈에서 공유하는 기능을 제공한다.
# --->
# RE_THINK_TAG: <think>/<thinking> 태그 제거용 컴파일 정규식
# strip_think_tags: 텍스트에서 think 태그를 제거한다
# KOREAN_CHAR_RE: 한국어 문자 감지용 정규식
# has_korean: 텍스트에 한국어가 포함되어 있는지 확인
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import re

# <think>/<thinking> 태그 제거용 컴파일 정규식 (닫히지 않은 태그도 처리)
RE_THINK_TAG = re.compile(
    r"<(?:think|thinking)>.*?</(?:think|thinking)>\s*|<(?:think|thinking)>.*",
    re.DOTALL | re.IGNORECASE,
)


def strip_think_tags(text: str) -> str:
    """텍스트에서 <think>/<thinking> 태그와 내용을 제거한다."""
    if not text:
        return text
    return RE_THINK_TAG.sub("", text).strip()


# 한국어 문자 감지용 정규식
KOREAN_CHAR_RE = re.compile(r"[가-힣]")


def has_korean(text: str) -> bool:
    """텍스트에 한국어(가~힣)가 포함되어 있으면 True."""
    return bool(KOREAN_CHAR_RE.search(text or ""))


# 인사/잡담 감지용 정규식
GREETING_RE = re.compile(
    r"^(안녕|반가|잘\s*지내|하이|헬로|좋은\s*(아침|저녁|하루)|수고|얀녕|고마워|감사)"
)
