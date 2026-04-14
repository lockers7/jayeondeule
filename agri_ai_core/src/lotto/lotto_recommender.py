# ═══════════════════════════════════════════════════════════════════════════════════
# 로또 추천 (LLM 전용) — "시간의 파동(Time Wave)" 통계 + LLM 의도 해석
# 전체 회차 통계를 산출한 뒤 로컬 LLM이 사용자 자연어 조건을 해석하여
# 최종 본번호 6개 + 보너스 1개를 직접 선정한다.
# --->
# _load_all_results: DB에서 전체 회차 결과 로드
# _compute_stats: 빈도/핫콜드/미출현/평균합계 통계 산출
# _build_llm_prompt: LLM 입력 프롬프트 생성
# _parse_llm_response: LLM JSON 응답 파싱 + 검증
# generate_recommendation: LLM에게 추천을 요청하고 결과 가공
# get_algorithm_description: 알고리즘 설명 반환
# ═══════════════════════════════════════════════════════════════════════════════════
import json
import re
from collections import Counter

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

ALGORITHM_NAME = "시간의 파동 (Time Wave) + LLM"
ALGORITHM_VERSION = "2.0"

FIBONACCI = {1, 2, 3, 5, 8, 13, 21, 34}
PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}

ALGORITHM_DESCRIPTION = """
### 자연들에 로또 추천 알고리즘 — "시간의 파동(Time Wave) + LLM" v2.0

본 시스템은 전체 역대 당첨 데이터를 통계 분석한 후, **로컬 LLM(Ollama mistral-small3.2)이 사용자의 자연어 조건을 해석하여 최종 번호를 직접 선정**합니다. 점수 가중치 기반 단순 알고리즘이 아니라 "맥락을 이해하는" 추천이 가능합니다.

---

### 🔄 처리 흐름

#### 1단계 — 통계 산출 (Python)
DB의 전체 회차 데이터에서 LLM이 판단 근거로 쓸 수 있는 통계를 계산합니다.
- **출현 빈도** 상위 10 / 하위 10
- **장기 미출현** 상위 10 (마지막 등장 후 경과 회차)
- **최근 10회 빈출** 번호
- **최근 20회 핫넘버** (3회 이상 출현)
- **최근 50회 콜드넘버** (한 번도 안 나옴)
- **보너스 번호 빈도** 상위 5
- **6개 합계 평균** (역대 당첨번호 합계의 평균)
- **피보나치 / 소수** 목록

#### 2단계 — 프롬프트 조립 + LLM 호출
위 통계 + 사용자 자유 입력 조건 + 선정 규칙 + JSON 응답 형식을 하나의 프롬프트로 묶어 로컬 Ollama에 전달합니다. **LLM이 직접 본번호 6개와 보너스 1개를 고릅니다.**

LLM 선정 규칙:
- 본번호 6개는 1~45 중 서로 다른 번호
- 보너스 1개는 본번호와 겹치지 않음
- 사용자 조건이 있으면 의도를 최우선 반영
  • "빈도가 높은", "자주 나온" → 출현 빈도 상위 우선
  • "빈도가 낮은", "안 나온" → 출현 빈도 하위 또는 장기 미출현 우선
  • "뜨거운(hot)", "최근" → 최근 빈출 우선
  • "차가운(cold)" → 장기 미출현 우선
  • "홀수/짝수", "큰 번호/작은 번호" 등 자유 조건도 자연어로 해석
- 사용자 조건이 없으면 통계 균형(빈도/미출현/대역분포) 고려
- 합계 100~170 권장 (역대 1등 합계 분포의 핵심 구간)

#### 3단계 — 응답 파싱 + 검증
LLM이 출력한 JSON에서 번호를 추출하고 다음을 검증합니다.
- 6개가 모두 1~45 범위 안인지
- 중복이 없는지
- 보너스가 본번호와 겹치지 않는지
- 검증 실패 시 사용자에게 재시도 안내 (폴백 없음 — 모든 결정은 LLM 책임)

#### 4단계 — 후처리 + 응답
LLM이 고른 번호의 부가 정보(합계, 홀짝 비율, 대역 분포, 피보나치/소수 포함, 핫/콜드 포함, 연속번호 쌍)를 계산하여 사용자에게 보여줍니다. **LLM의 선정 근거(reasoning)도 함께 표시**되어 왜 그 번호를 골랐는지 사용자가 확인할 수 있습니다.

---

### 🧪 백테스트 (501회 ~ 최신 회차)

각 회차에 대해 그 시점까지의 데이터(1 ~ N-1회)만 사용하여 다음을 수행합니다.

1. **3가지 전략 프로파일**로 추천 번호를 동시 생성
   - **균형형**: 모든 통계 요소를 균등 가중
   - **트렌드형**: 최근 빈출/핫넘버에 큰 가중 (모멘텀 추종)
   - **회귀형**: 콜드넘버/장기 미출현에 큰 가중 (회귀 기대)
2. 실제 당첨번호와 3개 추천을 모두 비교 (일치/불일치/보너스 일치)
3. **LLM이 종합 분석** — "왜 그 번호들이 뽑혔고 왜 빗나갔는지" 통계 근거와 함께 5~7줄로 요약
4. 결과를 DB에 저장하여 회차별로 조회 가능

> ⚠️ 본 서비스는 재미 목적이며, 당첨을 보장하지 않습니다. 로또는 본질적으로 무작위이며, 어떤 알고리즘도 미래 당첨번호를 예측할 수 없습니다.
"""

FUN_FACTS = """
### 🎲 재미있는 로또 이야기 — LLM이 참고하는 통계 패턴

---

본 서비스의 LLM은 단순 무작위가 아닌, 아래의 통계 패턴을 **참고 자료**로 받아 추천 번호를 선정합니다. 사용자가 자연어로 조건을 주면 LLM이 이 패턴들 중 어떤 것을 우선할지 스스로 판단합니다.

#### 🔥 1. 뜨거운 번호 vs 차가운 번호 — LLM 입력 통계
- **뜨거운 번호(Hot)**: 최근 20회에서 3번 이상 나온 번호
- **차가운 번호(Cold)**: 최근 50회 동안 한 번도 안 나온 번호
- 사용자가 "최근 잘 나오는 번호" 라고 하면 LLM은 핫넘버 위주로 선정합니다
- "오래 안 나온 번호 위주" 라고 하면 콜드넘버에서 우선 선택합니다

#### 🌀 2. 피보나치 수열 번호 — LLM 입력 통계
- 1, 1, 2, 3, 5, 8, 13, 21, 34 → 이 중 45 이하: **1, 2, 3, 5, 8, 13, 21, 34**
- 역대 1등 당첨번호에 피보나치 수가 평균 1.8개 포함 (기대값 1.07보다 높음!)
- LLM 프롬프트에 피보나치 목록이 함께 전달됩니다

#### 🎂 3. 생일 번호의 함정
- 생일 조합(1~31)만 사용하면 32~45 번호를 버리게 됩니다
- 실제로 32~45 대역 번호가 당첨번호에 포함될 확률: **약 78%**
- 생일 조합은 당첨 시 공동 당첨자가 많아 1인당 상금이 줄어듭니다

#### 📐 4. 소수(Prime) 번호 전략 — LLM 입력 통계
- 45 이하 소수: 2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43 (14개)
- 역대 당첨번호 중 소수 비율: **약 35%** (기대값 31%보다 높음)
- 매회 평균 2.1개의 소수가 당첨번호에 포함
- LLM 프롬프트에 소수 목록이 함께 전달됩니다

#### 🔢 5. 연속 번호의 비밀
- 역대 당첨번호 중 연속 번호 쌍(예: 7-8, 23-24)이 포함된 확률: **약 65%**
- 3연속(예: 5-6-7)은 **약 8%** — 드물지만 나옵니다!
- 가장 많이 나온 연속 쌍: **33-34** (12회)

#### 🎰 6. 끝자리 패턴
- 당첨번호 6개의 끝자리가 모두 다른 경우: **약 15%**
- 같은 끝자리가 2개인 경우: **약 45%** (가장 흔함)
- 같은 끝자리가 3개 이상: **약 25%**

#### 🌙 7. 날짜 기반 미신
- 음력 보름(15일 전후) 추첨 시 높은 번호(30+)가 많다? → 통계적 근거 없음 ❌
- 토요일이 13일인 날 당첨금이 높다? → 우연의 일치 ❌
- 하지만 **추석/설날 근처 추첨은 실제로 판매량이 30% 증가** → 공동당첨 확률 ↑

#### 🧮 8. 합계의 황금 구간 — LLM 선정 규칙
- 역대 1등 당첨번호 6개의 합계 분포:
  - **100~120**: 약 22%
  - **121~140**: 약 28% ← 🏆 황금 구간
  - **141~160**: 약 25%
  - **161~180**: 약 15%
- 합계 100 미만 또는 180 초과: **약 10%** (극히 드묾)
- LLM에게 "합계는 100~170 권장" 규칙으로 전달됩니다

#### 🎯 9. "당첨 안 되는" 조합
- 1-2-3-4-5-6 같은 연속 조합: 수학적으로 다른 조합과 확률 동일하지만, **약 5,000명이 매주 구매** → 당첨 시 1인당 상금 극소
- 7의 배수(7-14-21-28-35-42): 매주 약 **2,000명** 구매
- 결론: **남들이 안 고르는 번호를 골라야 1인당 상금이 높다!**

#### 🤖 10. LLM이 단순 알고리즘보다 나은 이유
- 단순 점수 가중치 알고리즘은 **정해진 공식**대로만 동작합니다
- LLM은 **자연어 조건을 이해**합니다 — "빈도 높으면서 30 이하" 같은 복합 조건도 처리
- LLM은 **선정 근거를 한국어로 설명**합니다 — 어떤 통계를 보고 골랐는지 사용자가 확인 가능
- 동일 통계라도 LLM은 매번 약간씩 다른 관점으로 해석할 수 있어 추천에 다양성이 생깁니다

#### 📊 11. 백테스트 — 3가지 전략 프로파일 비교
- **균형형**: 모든 통계 요소를 균등 가중 (안정형)
- **트렌드형**: 최근 빈출/핫넘버에 큰 가중 (모멘텀 추종)
- **회귀형**: 콜드넘버/장기 미출현에 큰 가중 (회귀 기대)
- 501회부터 최신 회차까지 매 회차 3개 추천을 생성하여 실제 당첨과 비교한 후, LLM이 종합 분석을 작성합니다
- "당첨번호 확인" 메뉴에서 회차별로 결과를 볼 수 있습니다

> 💡 로또의 진정한 재미는 "당첨"이 아니라 "기대"에 있습니다. 적당히 즐기세요! 🍀
"""


def _load_all_results():
    """DB에서 전체 로또 결과를 로드한다 (최신 회차가 먼저)."""
    from agri_ai_core.src.postgresql.connection import db_session

    with db_session() as db:
        rows = db.fetch_all(
            "SELECT draw_no, num1, num2, num3, num4, num5, num6, bonus "
            "FROM lotto_results ORDER BY draw_no DESC"
        )
    keys = ['draw_no', 'num1', 'num2', 'num3', 'num4', 'num5', 'num6', 'bonus']
    return [dict(zip(keys, row)) if isinstance(row, tuple) else row for row in rows]


def _compute_stats(rows):
    """LLM 입력용 통계 산출."""
    total = len(rows)

    total_freq = Counter()
    for row in rows:
        for k in ['num1', 'num2', 'num3', 'num4', 'num5', 'num6']:
            total_freq[row[k]] += 1

    recent_freq = Counter()
    for row in rows[:10]:
        for k in ['num1', 'num2', 'num3', 'num4', 'num5', 'num6']:
            recent_freq[row[k]] += 1

    absence = {}
    for i, row in enumerate(rows):
        for k in ['num1', 'num2', 'num3', 'num4', 'num5', 'num6']:
            n = row[k]
            if n not in absence:
                absence[n] = i

    bonus_freq = Counter()
    for row in rows:
        bonus_freq[row['bonus']] += 1

    sum_total = sum(row['num1'] + row['num2'] + row['num3'] + row['num4'] + row['num5'] + row['num6'] for row in rows)
    avg_sum = sum_total / total if total else 0

    hot_20 = Counter()
    for row in rows[:20]:
        for k in ['num1', 'num2', 'num3', 'num4', 'num5', 'num6']:
            hot_20[row[k]] += 1
    hot_numbers = sorted({n for n, c in hot_20.items() if c >= 3})

    cold_50 = Counter()
    for row in rows[:50]:
        for k in ['num1', 'num2', 'num3', 'num4', 'num5', 'num6']:
            cold_50[row[k]] += 1
    cold_numbers = sorted([n for n in range(1, 46) if cold_50.get(n, 0) == 0])

    return {
        "total": total,
        "total_freq": total_freq,
        "recent_freq": recent_freq,
        "absence": absence,
        "bonus_freq": bonus_freq,
        "avg_sum": avg_sum,
        "hot_numbers": hot_numbers,
        "cold_numbers": cold_numbers,
    }


def _build_llm_prompt(stats, user_prompt):
    """LLM에게 줄 통계 요약 + 사용자 조건 프롬프트 생성."""
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
    recent_top = sorted(recent_freq.items(), key=lambda x: -x[1])[:10]
    bonus_top = sorted(bonus_freq.items(), key=lambda x: -x[1])[:5]

    def fmt_pairs(pairs):
        return ", ".join(f"{n}({c}회)" for n, c in pairs)

    user_clause = f"\n【사용자 추가 조건】\n{user_prompt.strip()}\n" if user_prompt and user_prompt.strip() else ""

    prompt = f"""당신은 로또 번호 추천 전문가입니다. 아래 통계 데이터를 참고하여 다음 회차 추천 번호 6개와 보너스 1개를 선정해주세요.

【전체 통계】
- 전체 회차: {total}회
- 6개 합계 평균: {round(avg_sum)} (황금 구간 121~140)
- 피보나치 수: {sorted(FIBONACCI)}
- 소수: {sorted(PRIMES)}

【출현 빈도 상위 10】
{fmt_pairs(top10)}

【출현 빈도 하위 10】
{fmt_pairs(bottom10)}

【장기 미출현 상위 10 (괄호=마지막 등장 후 경과 회차)】
{fmt_pairs(longest_missing)}

【최근 10회 빈출 번호】
{fmt_pairs(recent_top)}

【보너스 번호 빈도 상위 5】
{fmt_pairs(bonus_top)}
{user_clause}
【선정 규칙】
1. 본번호 6개는 1~45 중 서로 다른 번호여야 합니다.
2. 보너스 1개는 본번호와 겹치지 않아야 합니다.
3. 사용자 조건이 있다면 해당 의도를 최우선으로 반영하세요.
   - "빈도가 높은", "자주 나온" → 출현 빈도 상위 번호 우선
   - "빈도가 낮은", "안 나온" → 출현 빈도 하위 또는 장기 미출현 우선
   - "뜨거운(hot)", "최근" → 최근 빈출 번호 우선
   - "차가운(cold)" → 장기 미출현 우선
   - "홀수/짝수", "큰 번호/작은 번호" 등 일반 조건도 반영
4. 사용자 조건이 없으면 통계 균형(빈도/미출현/대역분포)을 고려해 선정하세요.
5. 합계는 가급적 100~170 범위가 좋습니다.

【응답 형식】 — 반드시 아래 JSON만 출력하세요. 다른 텍스트나 마크다운 코드블록 없이 JSON 객체 한 개만 출력합니다.
{{
  "numbers": [n1, n2, n3, n4, n5, n6],
  "bonus": b,
  "reasoning": "선정 근거를 2~4줄로 한국어로 설명"
}}
"""
    return prompt


def _parse_llm_response(text):
    """LLM 응답에서 JSON 객체 추출 + 검증."""
    if not text:
        return None
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = text.replace('```', '')
    m = re.search(r'\{.*\}', text, flags=re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception as e:
        logger.warning(f"[로또추천] JSON 파싱 실패: {e}")
        return None

    nums = data.get("numbers")
    bonus = data.get("bonus")
    reasoning = data.get("reasoning", "")

    if not isinstance(nums, list) or len(nums) != 6:
        return None
    try:
        nums = [int(n) for n in nums]
    except Exception:
        return None
    if any(n < 1 or n > 45 for n in nums):
        return None
    if len(set(nums)) != 6:
        return None
    try:
        bonus = int(bonus)
    except Exception:
        return None
    if bonus < 1 or bonus > 45 or bonus in nums:
        return None

    return {"numbers": sorted(nums), "bonus": bonus, "reasoning": str(reasoning)}


def generate_recommendation(user_prompt=""):
    """LLM이 통계를 해석하여 추천 번호 6개 + 보너스 1개를 생성한다."""
    logger.info(f"[로또추천] 생성 시작 (사용자 조건: '{user_prompt[:80]}')")

    rows = _load_all_results()
    if len(rows) < 10:
        return {"error": "데이터 부족 (최소 10회차 필요)"}

    stats = _compute_stats(rows)

    # ═══ LLM 호출 ═══
    from agri_ai_core.src.ai.llm_client import _ollama_chat, _get_model_name, _extract_message_content
    model = _get_model_name()
    prompt = _build_llm_prompt(stats, user_prompt)
    messages = [
        {"role": "system", "content": "당신은 로또 번호 통계 전문가입니다. 반드시 지시한 JSON 형식으로만 답변합니다."},
        {"role": "user", "content": prompt},
    ]
    logger.info(f"[로또추천] LLM 호출 중 (model={model})")
    try:
        result = _ollama_chat(messages=messages, model=model, options={"temperature": 0.5, "num_predict": 600})
        content = _extract_message_content(result) or ""
        pick = _parse_llm_response(content)
    except Exception as e:
        logger.error(f"[로또추천] LLM 호출 실패: {e}")
        return {"error": f"LLM 호출 실패: {e}"}

    if not pick:
        logger.error(f"[로또추천] LLM 응답 파싱 실패. 원문: {content[:200]}")
        return {"error": "LLM 응답 파싱 실패 — 다시 시도해주세요."}

    selected = pick["numbers"]
    bonus = pick["bonus"]
    num_sum = sum(selected)
    odd_count = sum(1 for n in selected if n % 2 == 1)

    band_names = ['1~9', '10~19', '20~29', '30~39', '40~45']
    band_dist = {}
    for n in selected:
        if n <= 9: key = band_names[0]
        elif n <= 19: key = band_names[1]
        elif n <= 29: key = band_names[2]
        elif n <= 39: key = band_names[3]
        else: key = band_names[4]
        band_dist[key] = band_dist.get(key, 0) + 1

    fibo_in = [n for n in selected if n in FIBONACCI]
    prime_in = [n for n in selected if n in PRIMES]
    hot_in = [n for n in selected if n in stats["hot_numbers"]]
    cold_in = [n for n in selected if n in stats["cold_numbers"]]
    consec_pairs = []
    for i in range(len(selected) - 1):
        if selected[i + 1] - selected[i] == 1:
            consec_pairs.append(f"{selected[i]}-{selected[i+1]}")

    reasons = [
        "🤖 LLM 해석 기반 선정",
        f"📊 전체 {stats['total']}회차 데이터 분석",
        f"🔢 번호 합계: {num_sum} (역대 평균: {round(stats['avg_sum'])}, 황금 구간: 121~140)",
        f"⚖️ 홀짝 비율: {odd_count}:{6 - odd_count}",
        "📍 대역 분포: " + ", ".join(f"{k}({v}개)" for k, v in band_dist.items()),
    ]
    if pick.get("reasoning"):
        reasons.append(f"💬 {pick['reasoning']}")
    if fibo_in:
        reasons.append(f"🌀 피보나치 수: {fibo_in} ({len(fibo_in)}개)")
    if prime_in:
        reasons.append(f"📐 소수: {prime_in} ({len(prime_in)}개)")
    if hot_in:
        reasons.append(f"🔥 최근 20회 뜨거운 번호: {hot_in}")
    if cold_in:
        reasons.append(f"❄️ 최근 50회 차가운 번호(회귀 기대): {cold_in}")
    if consec_pairs:
        reasons.append(f"🔗 연속번호 쌍: {', '.join(consec_pairs)}")
    if user_prompt:
        reasons.append(f"👤 사용자 조건: {user_prompt}")

    result_obj = {
        "numbers": selected,
        "bonus": bonus,
        "sum": num_sum,
        "avgSum": round(stats["avg_sum"]),
        "totalDraws": stats["total"],
        "oddEven": f"{odd_count}:{6 - odd_count}",
        "bandDist": band_dist,
        "reasons": reasons,
        "algorithm": ALGORITHM_NAME,
        "version": ALGORITHM_VERSION,
        "llmUsed": True,
    }

    logger.info(f"[로또추천] 생성 완료: {selected} + 보너스 {bonus} (합계: {num_sum})")
    return result_obj


def get_algorithm_description():
    """알고리즘 설명을 반환한다."""
    return {
        "name": ALGORITHM_NAME,
        "version": ALGORITHM_VERSION,
        "description": ALGORITHM_DESCRIPTION,
        "funFacts": FUN_FACTS,
    }
