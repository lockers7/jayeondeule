# ══════════════════════════════════════════════════════════════════════════════
# 단계별 로그 포맷터 (M3, 통합)
# [2026-04-28 신규] 알고리즘 모드의 "[1/N] 농장 X, 재배사 Y" 와 동일한 형태로
# AI LLM·알고리즘·LLM 대화 모든 의사결정 흐름을 동일 포맷 단계 로그로 출력.
# prefix 인자에 따라 [AI N/M] / [ALGO N/M] / [LLM N/M] 등으로 사용 — 운영 시
# log_view.sh 의 카테고리 분류와 직결.
#
# 호출 룰:
#   • control 모듈/대화 라우터 등 어디서든 import 가능.
#   • logs 모듈 외 다른 의존성 없음.
#   • 단계 수가 변해도 호출 측만 total 을 바꾸면 되도록 인스턴스 기반.
# --->
# AiStepLogger: 단계 카운터 + scope + prefix 보유
#   - step(label, extra="")
#   - skip(label, reason="")
#   - warn(label, reason)
#   - done(summary=None)
#   - detail(*lines, max_chars=800)  ← 직전 단계의 본문을 들여쓰기로 자세히
# ══════════════════════════════════════════════════════════════════════════════
from typing import Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# 제어 1회 사이클 단계 로그를 [<prefix> i/N] 형식으로 출력하는 카운터 클래스.
# 사용 예:
#   AI 환경제어:    steps = AiStepLogger(scope="[1/3] 농장 1, 재배사 2", total=14)
#   알고리즘 환경:  steps = AiStepLogger(scope=..., total=7, prefix='ALGO')
#   LLM 대화:       steps = AiStepLogger(scope="[대화 abc12]", total=5, prefix='LLM')
# ────────────────────────────────────────────────────────────────────
class AiStepLogger:

    # ────────────────────────────────────────────────────────────────
    # 인스턴스 초기화 — scope/total/prefix 보관, idx=0 시작.
    # ────────────────────────────────────────────────────────────────
    def __init__(self, scope: str, total: int, prefix: str = "AI"):
        self.scope = scope or ""
        self.total = max(1, int(total))
        self.idx = 0
        self.prefix = (prefix or "AI").upper()

    # ────────────────────────────────────────────────────────────────
    # 로그 라인 헤더 문자열 생성 — "[<prefix> idx/total] scope".
    # ────────────────────────────────────────────────────────────────
    def _head(self) -> str:
        # [2026-04-28] 사용자 요청 — step prefix 가 메인이 되도록 순서 변경:
        # "[AI 1/14] 0-99: 라벨" 형식. scope 가 비어 있으면 "[AI 1/14]: 라벨".
        if self.scope:
            return f"[{self.prefix} {self.idx}/{self.total}] {self.scope}"
        return f"[{self.prefix} {self.idx}/{self.total}]"

    # ────────────────────────────────────────────────────────────────
    # 단계 진입 — idx 증가 후 INFO 라인 한 줄 출력.
    # ────────────────────────────────────────────────────────────────
    def step(self, label: str, extra: str = "") -> None:
        self.idx += 1
        head = self._head()
        if extra:
            logger.info(f"{head} {label} → {extra}")
        else:
            logger.info(f"{head} {label}")

    # ────────────────────────────────────────────────────────────────
    # 단계 스킵 — INFO. 데이터 없음/조건 미충족 등 의도된 스킵.
    # ────────────────────────────────────────────────────────────────
    def skip(self, label: str, reason: str = "") -> None:
        self.idx += 1
        head = self._head()
        if reason:
            logger.info(f"{head} {label} 스킵 ({reason})")
        else:
            logger.info(f"{head} {label} 스킵")

    # ────────────────────────────────────────────────────────────────
    # 단계 진행 중 비치명 오류 — WARNING 라인 출력.
    # ────────────────────────────────────────────────────────────────
    def warn(self, label: str, reason: str) -> None:
        self.idx += 1
        head = self._head()
        logger.warning(f"{head} {label} 경고: {reason}")

    # ────────────────────────────────────────────────────────────────
    # 마지막 단계 종료 알림 — 카운터 증가 없이 요약만 출력.
    # ────────────────────────────────────────────────────────────────
    def done(self, summary: Optional[str] = None) -> None:
        head = self._head()
        if summary:
            logger.info(f"{head} 완료 — {summary}")
        else:
            logger.info(f"{head} 완료")

    # ────────────────────────────────────────────────────────────────
    # [2026-04-28] 직전 step()/skip()/warn() 본문을 여러 줄로 자세히 출력.
    # "[AI n/N] 단계명" 한 줄 후 "└ 내용" 들여쓰기 형식 — 운영 추적 시
    # LLM 의사결정 흐름·프롬프트·응답·릴레이 결과까지 한눈에 보기 위함.
    # 멀티라인 입력은 자동 분할되어 각 줄에 prefix 부착.
    # 매우 긴 입력은 max_chars 로 truncate (기본 800자).
    # ────────────────────────────────────────────────────────────────
    def detail(self, *lines, max_chars: int = 800) -> None:
        # [2026-04-28] step 헤더와 일관된 prefix 로 detail 라인도 [{prefix} N/M] 시작.
        # log_view.sh 와 카테고리 분류가 detail 라인도 단계 prefix 로 정확히 매칭됨.
        head_label = f"[{self.prefix} {self.idx}/{self.total}]"
        indent = " " * 4 + "└ "
        for entry in lines:
            if entry is None or entry == "":
                continue
            text = str(entry)
            if len(text) > max_chars:
                text = text[:max_chars] + f"… (truncated, total {len(str(entry))}자)"
            for sub in text.splitlines():
                if sub.strip():
                    if self.scope:
                        logger.info(f"{head_label} {self.scope}:{indent}{sub}")
                    else:
                        logger.info(f"{head_label}:{indent}{sub}")
