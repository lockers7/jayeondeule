# ══════════════════════════════════════════════════════════════════════════════
# 최신 매매 방법론 시드 — 전용 VectorDB(trading_knowledge, category='방법론')
#
# 농장주 지시(2026-07-24): "매우 주식매매 최신 트렌드를 최대한 반영. 과거 매매 프로그램처럼
#   종목 선정하고 상하 가격, 그래프 분석 같은 단순한 일반적인 방법론은 아예 배제."
# → 최신 AI/LLM 기반(이벤트·공시·뉴스·심리·대체데이터·팩터·리스크) 방법론을 지식으로 저장,
#   로컬 LLM 이 매매 판단 시 회상·적용. ⛔전통 TA(차트/이동평균/지지저항) 배제.
#
# 파일 시작 함수 목록:
#   seed_trading_trends : 방법론 문서 시드(중복 시 건너뜀, force 로 갱신)
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# (key, text)
TREND_DOCS = [
    ("evt_catalyst",
     "이벤트 드리븐 카탈리스트 매매: 자사주취득·무상증자·대규모 공급계약·M&A·실적 서프라이즈 등 "
     "공시/뉴스 '사건'을 트리거로 매매한다. 사건의 신규성·규모·지속성을 평가하고, 시장이 아직 "
     "가격에 반영하지 못한 정보 비대칭 구간을 노린다. 차트가 아니라 '사건의 의미'로 판단한다."),
    ("pead_drift",
     "실적서프라이즈 후 주가 드리프트(PEAD): 어닝 서프라이즈 종목은 발표 후 수일~수주간 같은 방향으로 "
     "완만히 추세가 이어지는 경향이 있다. 서프라이즈 강도(컨센서스 대비)와 가이던스 상향 여부를 "
     "핵심 신호로 삼는다."),
    ("news_sentiment",
     "뉴스·공시 심리(sentiment) 분석: LLM 으로 기사/공시 톤을 긍정/부정/불확실로 정량화하고, "
     "심리 급변(뉴스 플로우 가속)과 실제 펀더멘털 변화를 구분한다. 단순 언급량이 아니라 '내용의 "
     "질'과 신뢰도 가중이 핵심."),
    ("theme_rotation",
     "테마·내러티브 로테이션: AI·2차전지·바이오·원전 등 시장 주도 테마의 자금 순환을 LLM 으로 "
     "포착한다. 초기 국면 진입·과열 회피가 목표이며, 테마 수명주기(태동→확산→과열→소멸)를 판단한다."),
    ("supply_demand",
     "수급·주체별 흐름: 기관·외국인 순매수 지속성, 공매도 잔고 변화, 대주주/자사주 매매를 신호로 "
     "쓴다. 가격이 아니라 '누가 사고 파는가'의 구조적 흐름을 본다."),
    ("alt_data",
     "대체 데이터: 검색트렌드·앱설치·고용공고·항만/물동량·카드결제 등 비전통 데이터로 실적을 "
     "선행 추정한다. 공식 실적 발표 전 펀더멘털 변화를 앞서 읽는 것이 목표."),
    ("multifactor",
     "멀티팩터: 퀄리티(ROE·부채)·모멘텀(이익추정 상향)·저변동·밸류를 결합해 종목을 스코어링한다. "
     "단일 지표가 아니라 팩터 조합의 견고성을 본다. 차트 기반 모멘텀이 아니라 '이익 모멘텀'."),
    ("risk_sizing",
     "리스크 관리·포지션 사이징: 변동성 타깃팅과 켈리 비중 축소판으로 종목별 비중을 정하고, "
     "종목당 한도·일일 손실한도를 엄격히 지킨다. 손절은 가격선이 아니라 '투자 논리 훼손' 시 실행한다."),
    ("regime",
     "시장 레짐 적응: 위험선호(risk-on)/회피(risk-off), 금리·환율 국면에 따라 이벤트 전략의 노출을 "
     "가감한다. 같은 신호라도 레짐에 따라 기대수익이 달라짐을 반영한다."),
    ("exclude_ta",
     "⛔ 배제 원칙: 단순 차트 패턴, 이동평균 크로스, 지지/저항선, 상하 가격밴드, 단순 그래프 분석 등 "
     "전통적 기술적 분석(TA)만으로의 종목 선정은 배제한다. 판단의 근거는 '사건·펀더멘털·심리·수급·"
     "대체데이터'여야 한다."),
]


def seed_trading_trends(force: bool = False) -> dict:
    from agri_ai_core.src.ai.trading_store import save_trading_knowledge, list_trading_knowledge
    existing = set()
    if not force:
        for it in list_trading_knowledge(category="방법론", limit=100):
            existing.add((it.get("id") or "").replace("trk_", ""))
    saved = 0
    for key, text in TREND_DOCS:
        if not force and key in existing:
            continue
        r = save_trading_knowledge(text, category="방법론", key=key)
        if r.get("success"):
            saved += 1
    logger.info(f"[매매방법론 시드] {saved}종 저장(force={force})")
    return {"success": True, "seeded": saved, "total": len(TREND_DOCS)}
