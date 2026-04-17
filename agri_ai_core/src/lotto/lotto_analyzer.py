# ═══════════════════════════════════════════════════════════════════════════
# 로또 추천 vs 당첨 비교 분석기 (LLM 전용)
# 501회부터 마지막 회차까지 LLM이 1~N-1 통계를 보고 직접 추천한 후,
# 실제 당첨번호와 비교하고 LLM이 종합 분석을 작성한다.
# 알고리즘 점수 가중치 추천은 백테스트 결과(703회) LLM과 통계적 동등으로
# 확인되어 폐기되었고, 본 모듈은 LLM 추천 + LLM 분석으로 단일화되었다.
# --->
# _load_results_until: 1~N-1 회차 결과 로드
# _request_llm_pick: LLM에게 N회차 추천 요청
# _request_llm_analysis: LLM에게 차이 분석 요청
# compare_with_actual: 추천 vs 실제 비교
# analyze_draw: 단일 회차 분석 + DB 저장 (LLM 추천 + LLM 분석)
# run_batch: 미분석 회차 일괄 처리
# ═══════════════════════════════════════════════════════════════════════════
import json
import re
from collections import Counter

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

START_DRAW = 501


def _load_results_until(draw_no):
    """draw_no 이전(포함하지 않음)까지의 모든 결과를 로드한다."""
    from agri_ai_core.src.postgresql.connection import db_session

    with db_session() as db:
        rows = db.fetch_all(
            "SELECT draw_no, num1, num2, num3, num4, num5, num6, bonus "
            "FROM lotto_results WHERE draw_no < %s ORDER BY draw_no DESC",
            (draw_no,)
        )
    keys = ['draw_no', 'num1', 'num2', 'num3', 'num4', 'num5', 'num6', 'bonus']
    return [dict(zip(keys, row)) if isinstance(row, tuple) else row for row in rows]


def _request_llm_pick(stats, draw_no):
    """LLM에게 N회차 추천 번호를 요청한다 (1개)."""
    from agri_ai_core.src.lotto.lotto_recommender import _build_llm_prompt, _parse_llm_response
    from agri_ai_core.src.ai.llm_transport import _ollama_chat, _get_model_name
    from agri_ai_core.src.ai.llm_message_utils import extract_message_content as _extract_message_content

    prompt = _build_llm_prompt(stats, "")
    model = _get_model_name()
    messages = [
        {"role": "system", "content": "당신은 로또 번호 통계 전문가입니다. 반드시 지시한 JSON 형식으로만 답변합니다."},
        {"role": "user", "content": prompt},
    ]
    try:
        result = _ollama_chat(messages=messages, model=model, options={"temperature": 0.5, "num_predict": 600})
        content = _extract_message_content(result) or ""
    except Exception as e:
        logger.warning(f"[로또분석] {draw_no}회 LLM 추천 호출 실패: {e}")
        return None

    pick = _parse_llm_response(content)
    if not pick:
        logger.warning(f"[로또분석] {draw_no}회 LLM 응답 파싱 실패: {content[:200]}")
    return pick


def compare_with_actual(rec, actual):
    """추천 vs 실제 비교."""
    rec_set = set(rec["numbers"])
    actual_set = {actual['num1'], actual['num2'], actual['num3'],
                  actual['num4'], actual['num5'], actual['num6']}
    matched = sorted(rec_set & actual_set)
    missed = sorted(actual_set - rec_set)
    extra = sorted(rec_set - actual_set)
    return {
        "match_count": len(matched),
        "matched": matched,
        "missed": missed,
        "extra": extra,
        "bonus_match": rec["bonus"] == actual['bonus'],
    }


def _summarize_stats_for_llm(stats):
    """1~N-1 통계를 LLM 분석 프롬프트용 텍스트로 요약한다."""
    total = stats["total"]
    total_freq = stats["total_freq"]
    recent_freq = stats["recent_freq"]
    absence = stats["absence"]
    bonus_freq = stats["bonus_freq"]
    avg_sum = stats["avg_sum"]

    freq_rank = sorted(total_freq.items(), key=lambda x: -x[1])
    top10 = freq_rank[:10]
    bottom10 = freq_rank[-10:]
    longest_missing = sorted(absence.items(), key=lambda x: -x[1])[:10]
    recent_top = sorted(recent_freq.items(), key=lambda x: -x[1])[:8]
    bonus_top = sorted(bonus_freq.items(), key=lambda x: -x[1])[:5]

    def fmt(pairs):
        return ", ".join(f"{n}({c})" for n, c in pairs)

    return (
        f"- 학습 데이터: 1회 ~ {total}회 (총 {total}회차)\n"
        f"- 6개 합계 평균: {round(avg_sum)}\n"
        f"- 출현빈도 상위10: {fmt(top10)}\n"
        f"- 출현빈도 하위10: {fmt(bottom10)}\n"
        f"- 장기 미출현 상위10 (괄호=경과회차): {fmt(longest_missing)}\n"
        f"- 최근 10회 빈출 번호: {fmt(recent_top)}\n"
        f"- 최근 20회 핫넘버(3회+): {stats['hot_numbers']}\n"
        f"- 최근 50회 콜드넘버(미출현): {stats['cold_numbers']}\n"
        f"- 보너스 빈도 상위5: {fmt(bonus_top)}"
    )


def _request_llm_analysis(draw_no, rec, actual, comparison, stats):
    """LLM에게 추천 vs 실제 차이 분석을 요청한다."""
    from agri_ai_core.src.ai.llm_transport import _ollama_chat, _get_model_name
    from agri_ai_core.src.ai.llm_message_utils import extract_message_content as _extract_message_content

    actual_sorted = sorted([actual['num1'], actual['num2'], actual['num3'],
                            actual['num4'], actual['num5'], actual['num6']])
    stats_block = _summarize_stats_for_llm(stats)

    prompt = f"""당신은 로또 번호 추천 결과의 분석가입니다. 아래 회차에 대해 LLM이 통계를 보고 추천한 번호와 실제 당첨번호의 차이를 통계적/수학적 관점에서 분석해주세요.

【LLM이 학습한 통계 (1~{draw_no - 1}회차)】
{stats_block}

【대상 회차】 {draw_no}회
【LLM 추천】 {rec['numbers']} + 보너스 {rec['bonus']}
【실제 당첨】 {actual_sorted} + 보너스 {actual['bonus']}
【일치 본번호】 {comparison['matched']} ({comparison['match_count']}개)
【놓친 번호】 {comparison['missed']}
【과추천 번호】 {comparison['extra']}
【보너스 일치】 {'예' if comparison['bonus_match'] else '아니오'}

분석 형식 (한국어, 5~7줄):
1. 일치율 평가 (몇 개 맞췄는지)
2. LLM이 추천한 번호의 통계적 근거 추정 (어떤 패턴/규칙을 보고 골랐는지 — 예: 빈도 상위, 핫넘버, 미출현 회귀 등)
3. 놓친 번호의 패턴 (대역/홀짝/소수/통계 위치)
4. 과추천 번호의 특징
5. 무작위성 또는 LLM 한계로 인한 불가피성

간결하고 통찰력 있게 답변해주세요."""

    model = _get_model_name()
    messages = [
        {"role": "system", "content": "당신은 로또 통계 분석가입니다. 간결하고 통찰력 있게 답변하세요."},
        {"role": "user", "content": prompt},
    ]
    try:
        result = _ollama_chat(messages=messages, model=model, options={"temperature": 0.3, "num_predict": 700})
        if not result:
            return None
        content = _extract_message_content(result) or ""
        if not content:
            return None
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        return content or None
    except Exception as e:
        logger.warning(f"[로또분석] {draw_no}회 LLM 분석 호출 실패: {e}")
        return None


def analyze_draw(draw_no):
    """단일 회차 분석: LLM 추천 → 비교 → LLM 분석 → DB 저장."""
    from agri_ai_core.src.postgresql.connection import db_session
    from agri_ai_core.src.lotto.lotto_recommender import _compute_stats

    # 실제 당첨번호 조회
    with db_session() as db:
        rows = db.fetch_all(
            "SELECT num1, num2, num3, num4, num5, num6, bonus FROM lotto_results WHERE draw_no = %s",
            (draw_no,)
        )
    if not rows:
        logger.warning(f"[로또분석] {draw_no}회 데이터 없음")
        return False

    actual_keys = ['num1', 'num2', 'num3', 'num4', 'num5', 'num6', 'bonus']
    actual = dict(zip(actual_keys, rows[0]))

    # 1~N-1 통계 계산
    history = _load_results_until(draw_no)
    if len(history) < 10:
        logger.warning(f"[로또분석] {draw_no}회 학습 데이터 부족")
        return False
    stats = _compute_stats(history)

    # LLM에게 추천 요청
    pick = _request_llm_pick(stats, draw_no)
    if not pick:
        return False
    rec = {"numbers": pick["numbers"], "bonus": pick["bonus"]}

    # 비교
    comparison = compare_with_actual(rec, actual)
    actual_main = sorted([actual[k] for k in actual_keys[:6]])
    logger.info(f"[로또분석] {draw_no}회 LLM={rec['numbers']}+B{rec['bonus']} vs 당첨={actual_main}+B{actual['bonus']} → 일치 {comparison['match_count']}/6")

    # LLM 분석 요청
    analysis = _request_llm_analysis(draw_no, rec, actual, comparison, stats)
    if not analysis:
        analysis = (
            f"[자동 분석] LLM 추천 {rec['numbers']}+B{rec['bonus']} vs 실제 {actual_main}+B{actual['bonus']}. "
            f"일치 {comparison['match_count']}/6개. "
            f"놓친 번호: {comparison['missed']}, 과추천: {comparison['extra']}"
        )

    miss_count = 6 - comparison['match_count']
    with db_session() as db:
        # lotto_recommendations에 LLM 추천 저장 (rec_no=1, source='llm')
        db.execute_query(
            "DELETE FROM lotto_recommendations WHERE draw_no = %s AND source = 'llm'",
            (draw_no,)
        )
        db.execute_query(
            "INSERT INTO lotto_recommendations "
            "(draw_no, rec_no, numbers, bonus, match_count, miss_count, bonus_match, matched_nums, source) "
            "VALUES (%s, 1, %s, %s, %s, %s, %s, %s, 'llm')",
            (draw_no, json.dumps(rec['numbers']), rec['bonus'],
             comparison['match_count'], miss_count, comparison['bonus_match'],
             json.dumps(comparison['matched']))
        )
        # lotto_results: 종합 컬럼 + 분석 텍스트
        db.execute_query(
            "UPDATE lotto_results SET recommendation_nums = %s, recommendation_bonus = %s, "
            "match_count = %s, best_match = %s, total_match = %s, total_miss = %s, "
            "llm_analysis = %s, analysis_dt = NOW() WHERE draw_no = %s",
            (json.dumps(rec['numbers']), rec['bonus'],
             comparison['match_count'], comparison['match_count'],
             comparison['match_count'], miss_count, analysis, draw_no)
        )

    logger.info(f"[로또분석] {draw_no}회 완료 (일치 {comparison['match_count']}/6, 분석 {len(analysis)}자)")
    return True


def run_batch(start=START_DRAW, end=None, redo=False):
    """start~end 회차를 LLM 단일 추천 + LLM 분석으로 처리한다.
    redo=False면 llm_analysis가 있는 회차는 건너뛴다."""
    from agri_ai_core.src.postgresql.connection import db_session

    if end is None:
        with db_session() as db:
            rows = db.fetch_all("SELECT MAX(draw_no) FROM lotto_results")
            end = rows[0][0] if rows else 0

    with db_session() as db:
        if redo:
            rows = db.fetch_all(
                "SELECT draw_no FROM lotto_results WHERE draw_no >= %s AND draw_no <= %s ORDER BY draw_no",
                (start, end)
            )
        else:
            rows = db.fetch_all(
                "SELECT draw_no FROM lotto_results WHERE draw_no >= %s AND draw_no <= %s "
                "AND llm_analysis IS NULL ORDER BY draw_no",
                (start, end)
            )
    targets = [row[0] for row in rows]

    logger.info(f"[로또분석] 배치 시작: {start}~{end}, 처리대상 {len(targets)}건 (redo={redo})")

    success = 0
    for i, draw_no in enumerate(targets, 1):
        try:
            if analyze_draw(draw_no):
                success += 1
            if i % 10 == 0:
                logger.info(f"[로또분석] 진행 {i}/{len(targets)} ({success}건 성공)")
        except Exception as e:
            logger.error(f"[로또분석] {draw_no}회 처리 중 오류: {e}")

    logger.info(f"[로또분석] 배치 완료: {success}/{len(targets)}건 성공")
    return success
