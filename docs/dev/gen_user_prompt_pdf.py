#!/usr/bin/env python3
"""docs/user_prompt.pdf 생성 — A4 세로 출력용.

LLM 환경제어 user_prompt 양식을 NanumGothic 한국어 폰트로 PDF 변환.
실제 운영 user_prompt 와 동일한 빌더(_build_user_prompt)를 mock 데이터로
호출해 양식·섹션 구조를 그대로 캡처. 실값은 예시이며 운영 시점에는
sensor·릴레이·trend·history·rag·extra_blocks 가 실시간 주입된다.

사용법:
    /workspace/jayeondeule/venv/bin/python docs/dev/gen_user_prompt_pdf.py
"""
import datetime as _dt
import sys

sys.path.insert(0, '/workspace/jayeondeule')

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Preformatted

KR_REG = 'NanumGothic'
KR_BOLD = 'NanumGothic-Bold'
pdfmetrics.registerFont(TTFont(KR_REG, '/usr/share/fonts/truetype/nanum/NanumGothic.ttf'))
pdfmetrics.registerFont(TTFont(KR_BOLD, '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf'))

OUT_PATH = '/workspace/jayeondeule/docs/user_prompt.pdf'


# ────────────────────────────────────────────────────────────────────
# 운영과 유사한 mock 데이터 — 1-1 재배사 생육기, 약간 고습 + CO2 상승 시나리오.
# ────────────────────────────────────────────────────────────────────
SENSOR_DATA = {
    'indoor_temperature': 25.013, 'indoor_humidity': 100.0, 'co2': 1120.0,
    'outdoor_temperature': 12.999, 'outdoor_humidity': 88.345, 'water_temperature': 32.625,
}

CURRENT_RELAY = {
    # 양식 표현용 — 실제 pin map 은 농장·호기별로 다름
    'O5': True,  # 배출팬
    'O6': True,  # 배출밸브
}

OPTIMAL = {'온도최저': 25.0, '온도최고': 28.0,
           '습도최저': 70.0, '습도최고': 95.0,
           '수온최저': 20.0, '수온최고': 40.0,
           'CO2최고': 2000.0}

TREND_INFO = '추세 분석: CO2 상승 추세 +13.3ppm/분'

HISTORY_BLOCK = (
    "[직전 5건 결정 이력]\n"
    "- T-25분: change → 배기순환 (CO2 1500ppm 트립)\n"
    "- T-20분: keep (상태 안정)\n"
    "- T-15분: keep\n"
    "- T-10분: change → 흡입순환 추가 (습도 98%)\n"
    "- T- 5분: keep"
)

RAG_BLOCK = (
    "[유사 시기 RAG 사례 — 동일 재배사 작년 5월 평균]\n"
    "- 작년 동시기 야간 외기 평균 11.3℃ — 수온히터 평균 가동률 22%.\n"
    "- 1등급률 0.71 시기 환경: 야간 내부 16.5℃ / 수온 18.5℃ 유지."
)

EXTRA_BLOCKS = [
    "[최근 2개월 운영 통계 — 표본 1,555,026건, 2026-03-17~2026-05-16]\n"
    "내부온도 평균 17.4℃ (min 0.0 / max 31.7 / std 6.4), 내부습도 평균 91.4%, "
    "CO2 평균 825ppm, 수온 평균 19.1℃\n"
    "주야 분리: 주간 18.0℃/89.1%/776ppm · 야간 16.8℃/93.8%/873ppm\n"
    "릴레이 가동률: 수온히터 18.0% · 포그생성 24.7% · 흡입팬 56.0% · 배출팬 73.6% · 순환밸브 62.1%",

    "[알고리즘 참조 결정]\n"
    "- 일반 룰 사유=64케이스(온도:normal, 습도:high, CO2:normal, 계절:warm) → 순환=내부순환, devices keep",

    "[동일 농장 다른 재배사 — 동시점]\n"
    "- 1-2: 내부 24.8℃ / CO2 1080 / 배출팬 ON\n"
    "- 1-3: 내부 26.1℃ / CO2 1450 / 배기순환 + drainage 검토 중",

    "[수확 컨텍스트]\n"
    "- 작기 D-12 (아직 환경 변화 여유 있음)",

    "[60분 raw 시계열 — 분당 (가장 최근 → 과거 순, 일부만 표시)]\n"
    "T  0: 내부 25.01 / 습도 100.0 / CO2 1120 / 수온 32.6\n"
    "T- 5: 내부 24.95 / 습도  99.7 / CO2 1054 / 수온 32.4\n"
    "T-15: 내부 24.81 / 습도  98.9 / CO2  962 / 수온 32.1\n"
    "T-30: 내부 24.50 / 습도  97.2 / CO2  840 / 수온 31.7\n"
    "T-45: 내부 24.20 / 습도  95.8 / CO2  775 / 수온 31.2\n"
    "T-60: 내부 23.95 / 습도  94.3 / CO2  720 / 수온 30.8",

    "[외부 기상 단기예보 — 향후 1~3h (KMA 정읍시 영원면 nx=57 ny=84)]\n"
    "+1h: 외기 13.5℃ / 습도 87% / 강수 0mm\n"
    "+2h: 외기 12.8℃ / 습도 89% / 강수 0mm\n"
    "+3h: 외기 11.9℃ / 습도 91% / 강수 0mm\n"
    "야간 최저 예보 9.5℃ — §3 외기 예보 기반 선행 활용 룰 (밤 외기 < TEMP_LOW) 가동 조건 충족 검토",

    "[전력 — 직전 24h 추정]\n"
    "수온히터 4.2 kWh / 포그생성 1.1 kWh / 환풍기 합계 8.7 kWh",

    "[재배사 카메라 24h 이력]\n"
    "T  0: 정상 (자실체 형성 양호, 곰팡이/결로 미감지)\n"
    "T-12h: 정상\n"
    "T-24h: 정상",
]


# ────────────────────────────────────────────────────────────────────
# user_prompt 빌드 — 실제 운영 빌더 사용 (양식 일치 보장).
# pin_map / SEMANTIC_LABELS 는 ai_control 의존 → mock 형태로 라벨화.
# ────────────────────────────────────────────────────────────────────
def get_user_prompt() -> str:
    # _build_user_prompt 는 pin_map 을 농장 DB 에서 읽어와 동작 — house_id=1 사용.
    # mock CURRENT_RELAY 의 키('O5','O6')가 매칭 안 되어도 양식상 빈 ON 으로 표시될 수 있음.
    # 표시용 보조 라벨 합성으로 통일.
    from agri_ai_core.src.control.ai_control import _build_user_prompt
    return _build_user_prompt(
        SENSOR_DATA, CURRENT_RELAY, '생육기', OPTIMAL,
        TREND_INFO, 1,
        history_block=HISTORY_BLOCK, rag_block=RAG_BLOCK,
        extra_blocks=EXTRA_BLOCKS,
    )


def build_pdf(prompt_text: str):
    doc = SimpleDocTemplate(
        OUT_PATH, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title='AgriAI Core LLM 환경제어 user_prompt (양식)',
        author='AgriAI Core',
    )
    title_style = ParagraphStyle(
        'Title', fontName=KR_BOLD, fontSize=16, leading=22,
        alignment=1, spaceAfter=8,
    )
    sub_style = ParagraphStyle(
        'Sub', fontName=KR_REG, fontSize=10, leading=14,
        alignment=1, textColor=colors.HexColor('#555555'), spaceAfter=14,
    )
    note_style = ParagraphStyle(
        'Note', fontName=KR_REG, fontSize=8.7, leading=12,
        textColor=colors.HexColor('#666666'), spaceAfter=10,
    )
    body_style = ParagraphStyle(
        'Body', fontName=KR_REG, fontSize=8.7, leading=12.5,
    )

    story = []
    story.append(Paragraph(
        'AgriAI Core LLM 환경제어 user_prompt — 양식 (생육기 · 1-1호 시나리오)',
        title_style,
    ))
    story.append(Paragraph(
        f'(추출 시각 {_dt.datetime.now().strftime("%Y-%m-%d %H:%M")} · 총 {len(prompt_text):,}자 · '
        f'mock 데이터 + 실 빌더 _build_user_prompt 사용)',
        sub_style,
    ))
    story.append(Paragraph(
        '주의 — 본 PDF 는 user_prompt 의 <b>섹션 구성·표현 양식</b>을 보여주는 양식 캡처입니다. '
        '운영 시점에는 sensor·릴레이·trend·history·rag·extra_blocks 가 농장 DB / 카메라 / KMA 예보 / '
        'RAG / 알고리즘 참조 등에서 실시간 주입됩니다. extra_blocks 의 외부 기상 단기예보 섹션은 '
        'KMA_API_KEY 환경변수 설정 후부터 자동 추가됩니다.',
        note_style,
    ))
    story.append(Preformatted(prompt_text, body_style, maxLineLength=110))
    doc.build(story)
    print(f'[gen_user_prompt_pdf] 생성 완료: {OUT_PATH}')


if __name__ == '__main__':
    text = get_user_prompt()
    build_pdf(text)
