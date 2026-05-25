#!/usr/bin/env python3
"""docs/info_for_relay_control.pdf 생성 — A4 세로.

LLM 환경제어가 받는 모든 입력 데이터 + 시스템 프롬프트 + 유저 프롬프트
구조를 한 문서에 정리. 운영자/엔지니어가 LLM 의사결정 근거를 한눈에
파악할 수 있도록 한국어 PDF.

사용법:
    /workspace/jayeondeule/venv/bin/python docs/dev/gen_info_for_relay_control_pdf.py
"""
import os
import sys
import datetime as _dt

sys.path.insert(0, '/workspace/jayeondeule')

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Preformatted, Table,
    TableStyle, KeepTogether,
)

KR_REG = 'NanumGothic'
KR_BOLD = 'NanumGothic-Bold'
pdfmetrics.registerFont(TTFont(KR_REG, '/usr/share/fonts/truetype/nanum/NanumGothic.ttf'))
pdfmetrics.registerFont(TTFont(KR_BOLD, '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf'))

OUT_PATH = '/workspace/jayeondeule/docs/info_for_relay_control.pdf'


# ────────────────────────────────────────────────────────────────────
# 스타일 정의
# ────────────────────────────────────────────────────────────────────
TITLE = ParagraphStyle(
    'Title', fontName=KR_BOLD, fontSize=18, leading=24,
    alignment=1, spaceAfter=6,
)
SUBTITLE = ParagraphStyle(
    'Subtitle', fontName=KR_REG, fontSize=10, leading=14,
    alignment=1, textColor=colors.HexColor('#555555'), spaceAfter=14,
)
H1 = ParagraphStyle(
    'H1', fontName=KR_BOLD, fontSize=14, leading=20,
    textColor=colors.HexColor('#1F4E79'),
    spaceBefore=12, spaceAfter=8,
)
H2 = ParagraphStyle(
    'H2', fontName=KR_BOLD, fontSize=11, leading=16,
    textColor=colors.HexColor('#2E5984'),
    spaceBefore=8, spaceAfter=4,
)
BODY = ParagraphStyle(
    'Body', fontName=KR_REG, fontSize=9.2, leading=13,
    spaceAfter=4,
)
CODE = ParagraphStyle(
    'Code', fontName=KR_REG, fontSize=8.2, leading=11.5,
    textColor=colors.HexColor('#222222'),
    leftIndent=8, rightIndent=4,
    spaceBefore=2, spaceAfter=4,
)


def get_system_prompt() -> str:
    from agri_ai_core.src.control.ai_control import _build_system_prompt
    from agri_ai_core.src.control.ai_thresholds import get_thresholds
    ts = get_thresholds(1, 1)
    return _build_system_prompt('생육기', ts)


def _xml_escape(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def make_table(rows, col_widths=None, header=True, font_size=8.5):
    style_cmds = [
        ('FONTNAME', (0, 0), (-1, -1), KR_REG),
        ('FONTSIZE', (0, 0), (-1, -1), font_size),
        ('VALIGN',   (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING',  (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING',   (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#CCCCCC')),
    ]
    if header:
        style_cmds.extend([
            ('FONTNAME',   (0, 0), (-1, 0), KR_BOLD),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E7EEF7')),
            ('TEXTCOLOR',  (0, 0), (-1, 0), colors.HexColor('#1F4E79')),
        ])
    t = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
    t.setStyle(TableStyle(style_cmds))
    return t


# ────────────────────────────────────────────────────────────────────
# 본문 데이터 정의
# ────────────────────────────────────────────────────────────────────

CALL_OVERVIEW = (
    "AgriAI Core 의 환경제어 LLM 은 직렬 호출 구조입니다 — 정해진 주기가 아니라 "
    "‘한 재배사 cycle 종료 → 60초 대기 → 다음 재배사 cycle 시작’ 패턴으로 운용. "
    "Ollama (로컬) 의 gemma3:27b 모델에 system_prompt + user_prompt 결합문을 보내고 "
    "응답 JSON 을 받아 릴레이 제어를 결정합니다. 호출 후 시스템이 비상 임계 위반 항목만 "
    "강제로 덮어쓰는 emergency_override 가 적용됩니다."
    "<br/><br/>"
    "<b>실측 시간 흐름 (1호+3호 운용 시):</b><br/>"
    "T=0 1호 cycle 시작 → LLM 처리 (75~150초, 변동) → T=130 1호 종료 → 60초 대기 → "
    "T=190 3호 cycle 시작 → 처리 → T=320 3호 종료 → 60초 대기 → T=380 다시 1호 시작.<br/>"
    "<b>호기 간 시작 간격 = LLM 처리 시간(변동) + 60초(고정).</b>"
)

CALL_PARAMS = [
    ['항목', '값', '비고'],
    ['모델',         'gemma3:27b',                       'VRAM 19.8GB · 4비트 양자화 Q4_K_M'],
    ['컨텍스트 길이', 'num_ctx = 16384',                  '16K 토큰 (확장)'],
    ['응답 토큰',    'num_predict = 400',                'JSON 한 객체 < 200 토큰이면 충분'],
    ['타임아웃',     '600초',                            '큐 대기 후 응답 수신까지 허용'],
    ['응답 형식',    'JSON Schema 강제 (Ollama format)', 'schema 단일 시도 후 실패 시 algorithm_fallback'],
    ['호출 구조',     '직렬 (cycle 종료 후 다음 cycle)',  '정해진 주기 없음 — LLM 처리 후 60초 대기'],
    ['호기 간 대기',  '60초 (고정)',                      'AI_CONTROL_LOOP_DELAY_SEC=60'],
    ['실측 cycle',   '약 190~660초/호기',                 'LLM 처리 75~150s (정상) ~ 600s (timeout)'],
    ['병렬',         'OLLAMA_NUM_PARALLEL = 2',          '동시 처리 슬롯 2개 (LLM/임베딩 공유)'],
]

INPUT_DATA = [
    ['#', '데이터 종류', '출처', '용도'],
    ['1',  '센서값 (실시간 6종)',
       'DB sensor_l_recording', '내부온도/습도, CO2, 외부온도/습도, 수온'],
    ['2',  '현재 릴레이 상태',
       'DB relay_l_recording', '현재 ON 장치들 (보호장치 제외)'],
    ['3',  '추세 분석',
       '메모리 deque + sensor 시계열', '분당 변화율 (실내온도/CO2)'],
    ['4',  '생육단계',
       'DB farmhouse_l_crops + 계산', '발이기/생육기/수확기 + 작기 D-N'],
    ['5',  '적정·임계 임계값',
       'DB sensor_m_setting',         '온도/습도/CO2/수온 정상·임계 범위'],
    ['6',  '직전 LLM 결정 이력 5건',
       'DB ai_decision_log',          'oscillation 방지'],
    ['7',  '알고리즘 참조 결정 (64-케이스)',
       '_determine_environment_action',  'LLM 결정과의 일관성 비교'],
    ['8',  '재배사간 동시점 비교',
       'sensor_l_recording (peer 호기)','동일 농장 다른 호기 sensors/relays'],
    ['9',  '수확 컨텍스트',
       'DB farmhouse_l_crops',           '작기 D-N · D-3 이내 보수적 결정'],
    ['10', '이상사건 직전 환경 패턴',
       'DB anomaly_event 등',            '병해 발생 직전 24h 평균 (회피)'],
    ['11', '외부 기상예보',
       'KMA API (현재 비활성)',          '향후 1~3시간 외부 온/습/강수'],
    ['12', '재배사 영상 분석 (24h 이력)',
       'DB farmhouse_image_history (Vision LLM)', '자실체/곰팡이/결로 이상 감지'],
    ['13', '유사 시기 RAG 사례',
       'ChromaDB farm_knowledge',        'anomaly/품질 라벨 회피'],
    ['14', '도메인 지식 RAG',
       'ChromaDB document_collection',   '매뉴얼/논문 발췌 · 사용자 입력 노하우'],
    ['15', '수확 성공 패턴',
       'DB farmhouse_l_harvest',         '1등급률 ≥0.6 시기 환경 복원'],
    ['16', '단기 예측 (5분/1시간 후)',
       '_get_ts_forecast (시계열 모델)', '임계 근접 시 사전 조치'],
    ['17', '다년치 동월 평균',
       'sensor_l_recording 통계',        '같은 월 연도별 평균'],
    ['18', '24h 추정 가동시간/전력',
       'relay_l_recording 통계',         '동일 효과면 가동시간 짧은 옵션 우선'],
    ['19', '60분 raw 시계열',
       'sensor_l_recording recent samples', 'LLM 직접 분당 변화율 계산용'],
]

USER_PROMPT_BLOCKS = [
    ['#', 'AI 단계',  '블록',                       '내용'],
    ['1',  '-',          '현재 센서값 (고정 헤드)',
       '내부온도/습도/CO2/외부온도/습도/수온 6종 단일 라인'],
    ['2',  '-',          '생육단계 (고정 헤드)',     '발이기/생육기/수확기'],
    ['3',  'AI 3/14',    '최적조건 (고정 헤드)',
       '온도/습도/수온 적정 범위 (None 포함 시 가드로 생략)'],
    ['4',  '-',          '현재 릴레이 (고정 헤드)',
       'ON=[수온히터, 포그생성, …] (보호장치 제외)'],
    ['5',  '-',          '추세 분석 (고정 헤드)',
       '분당 변화율 (실내온도/CO2 등)'],
    ['6',  'AI 4/14',    '최근 2개월 + 1년 전 기준점',
       '평균/표본·릴레이 가동률, 1년 전 동시기 셋팅·결과'],
    ['7',  'AI 5/14',    '알고리즘 참조 결정',
       '동일 센서값에서 64-케이스가 내릴 결정 (LLM 비교용)'],
    ['8',  'AI 6/14',    '직전 LLM 결정 이력 5건',
       '최신→과거 순. 5분 단위 ON↔OFF 진동 회피'],
    ['9',  'AI 7/14',    '동일 농장 다른 재배사 동시점',
       '센서/릴레이 비교 — 합의/이상치 검출'],
    ['10', 'AI 8/14',    '수확 컨텍스트 + 이상사건',
       '작기 D-N · 병해 직전 24h 패턴 회피'],
    ['11', 'AI 9/14',    '외부 기상 단기예보',
       '향후 1~3시간 외부 온/습/강수 (KMA, 현재 비활성)'],
    ['12', 'AI 10/14',   '재배사 카메라 24시간 이력',
       '밝기·어두움 추세 + 직전 Vision 묘사 (자실체/결로 이상)'],
    ['13', 'AI 11/14',   '유사 시기 RAG (캐시 5분)',
       '동일 재배사 과거 운영 사례 (anomaly/품질 라벨 회피)'],
    ['14', 'AI 11/14',   '도메인 지식 RAG (캐시 5분)',
       '매뉴얼/논문 발췌 · 사용자 채팅 입력 노하우'],
    ['15', 'AI 12/14',   '수확 성공 패턴 + 단기 예측 + 계절성 + 전력 + 60분 raw',
       '5종 분석 통합 — 1등급률 시기 환경, 5분/1시간 후 예측 등'],
]

RESPONSE_SCHEMA = (
    '{"action":"change","reason":"<사유 텍스트>",\n'
    ' "devices":{"water_heater_flag":<true|false>,\n'
    '            "fog_occurs_flag":<true|false>,\n'
    '            "drainage_motor_flag":<true|false>},\n'
    ' "circulation":"<5종 중 1>"}\n'
    '\n'
    '{"action":"keep","reason":"<사유>"}    ← 변경 없음'
)

CIRCULATION_5 = [
    ['모드', '밸브 (순환·흡입·배출)', '팬 (흡입·배출)', '효과'],
    ['순환정지', 'ON·ON·ON',  'OFF·OFF', '모든 흐름 정지'],
    ['내부순환', 'ON·OFF·OFF', 'ON·ON',  '내부 공기 순환 (외부 격리)'],
    ['외부순환', 'OFF·ON·ON',  'ON·ON',  '내부공기 → 외부공기 대체 (전면 환기)'],
    ['흡입순환', 'OFF·ON·OFF', 'ON·OFF', '외기 유입 → CO2 하락 (양압)'],
    ['배기순환', 'OFF·OFF·ON', 'OFF·ON', '내부공기 배출 → CO2 하락 (음압)'],
]

EMERGENCY_OVERRIDES = [
    ['비상 종류', '트립 임계', 'water_heater', 'circulation', '기타'],
    ['저온비상',     'indoor_temp < 20℃ (생육기)',  'ON 강제',  '내부순환 강제', '-'],
    ['고온비상',     'indoor_temp > 32℃ (생육기)',  'OFF 강제', '외부/배기순환 강제', '-'],
    ['수온저온비상', 'water_temp < 15℃',           'ON 강제',  '-',             'drainage OFF 강제'],
    ['수온과열비상', 'water_temp > 45℃',           'OFF 강제', '-',             '실내고온 시 drainage ON'],
    ['고CO2비상',    'co2 > 3000ppm',                '-',        '외부/배기순환 강제', '-'],
    ['저습비상',     'humidity < 50% (생육기)',     'LLM 자율', 'LLM 자율',      '시스템 강제 없음'],
    ['고습비상',     'humidity > 101%',             'LLM 자율', 'LLM 자율',      '시스템 강제 없음'],
]


# ────────────────────────────────────────────────────────────────────
# PDF 빌드
# ────────────────────────────────────────────────────────────────────
def build():
    doc = SimpleDocTemplate(
        OUT_PATH,
        pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm,  bottomMargin=18 * mm,
        title='AgriAI Core LLM 환경제어 입력 데이터·프롬프트 종합',
        author='AgriAI Core',
    )

    story = []
    now = _dt.datetime.now().strftime('%Y-%m-%d %H:%M')

    # 표지
    story.append(Paragraph('AgriAI Core LLM 환경제어', TITLE))
    story.append(Paragraph('입력 데이터 · 프롬프트 종합 문서', TITLE))
    story.append(Paragraph(f'생성: {now} · 모델 gemma3:27b · A4 세로', SUBTITLE))

    story.append(Paragraph('§ 1. LLM 호출 구조 개요', H1))
    # [2026-05-04] CALL_OVERVIEW 는 reportlab 미니 HTML 태그(<br/>, <b>) 포함 → escape 금지.
    story.append(Paragraph(CALL_OVERVIEW, BODY))
    story.append(Spacer(1, 4))
    story.append(make_table(CALL_PARAMS, col_widths=[35*mm, 50*mm, 90*mm]))

    # 입력 데이터 종류
    story.append(PageBreak())
    story.append(Paragraph('§ 2. LLM 에 제공되는 입력 데이터 19종', H1))
    story.append(Paragraph(
        'LLM 호출 cycle 14 단계 동안 다음 19종 데이터가 사전 처리되어 user_prompt 에 '
        '병합됩니다. 각 데이터는 빈 결과면 자동 생략 (해당 블록 미포함).', BODY))
    story.append(Spacer(1, 4))
    story.append(make_table(INPUT_DATA, col_widths=[8*mm, 50*mm, 56*mm, 60*mm], font_size=8.0))

    # 시스템 프롬프트
    story.append(PageBreak())
    story.append(Paragraph('§ 3. 시스템 프롬프트 전문 (15개 블록)', H1))
    story.append(Paragraph(
        'LLM 의 결정 룰. USE_DB_BLOCKS=1 환경에서는 prompt_block_m DB 의 블록이 우선 '
        '사용되며, 미존재 시 inline fallback. 아래는 _build_system_prompt(\'생육기\') '
        '실시간 출력.', BODY))
    story.append(Spacer(1, 4))

    sp_text = get_system_prompt()
    section_buffer = []
    current_heading = None

    def flush_section():
        nonlocal section_buffer, current_heading
        text_block = '\n'.join(section_buffer).rstrip()
        if not text_block and not current_heading:
            section_buffer = []
            return
        if current_heading:
            story.append(Paragraph(_xml_escape(current_heading), H2))
        if text_block:
            story.append(Preformatted(text_block, CODE, maxLineLength=110))
        section_buffer = []

    for raw in sp_text.splitlines():
        if raw.startswith('## '):
            flush_section()
            current_heading = raw[3:].strip()
            section_buffer = []
        else:
            section_buffer.append(raw)
    flush_section()

    # 유저 프롬프트 구조
    story.append(PageBreak())
    story.append(Paragraph('§ 4. 유저 프롬프트 구조 — 14단계 사전 처리 + 15개 블록', H1))
    story.append(Paragraph(
        '_build_user_prompt() 가 다음 순서로 블록을 결합합니다. 각 블록은 빈 결과면 '
        '자동 생략. 전체 prompt 길이는 약 13,000자 (한국어 약 5,000~9,000 토큰).', BODY))
    story.append(Spacer(1, 4))
    story.append(make_table(USER_PROMPT_BLOCKS,
                            col_widths=[8*mm, 18*mm, 60*mm, 88*mm], font_size=7.8))

    # 응답 형식
    story.append(PageBreak())
    story.append(Paragraph('§ 5. LLM 응답 형식 (출력 스키마)', H1))
    story.append(Paragraph(
        'Ollama format=schema 로 강제 검증되며 위반 시 응답 거부. action 은 change 또는 '
        'keep 만 허용. devices 는 3개 키 (water_heater/fog_occurs/drainage_motor) 만 허용.', BODY))
    story.append(Spacer(1, 4))
    story.append(Preformatted(RESPONSE_SCHEMA, CODE, maxLineLength=80))

    story.append(Paragraph('5종 순환 모드 (circulation 키)', H2))
    story.append(make_table(CIRCULATION_5,
                            col_widths=[20*mm, 38*mm, 38*mm, 78*mm], font_size=8.5))

    # 비상 오버라이드
    story.append(Paragraph('§ 6. 시스템 emergency_override (LLM 결정 후 자동 적용)', H1))
    story.append(Paragraph(
        'LLM 결정 위에 비상 위반 항목만 강제 덮어쓰기. 사용자 정의 7개 정책. 비상 미트립 시 '
        '운용 결정 그대로 보존. 알고리즘 모드와 AI 모드 양쪽 동일 적용.', BODY))
    story.append(Spacer(1, 4))
    story.append(make_table(EMERGENCY_OVERRIDES,
                            col_widths=[24*mm, 40*mm, 28*mm, 30*mm, 50*mm], font_size=8.0))

    # 결합 룰
    story.append(Paragraph('§ 7. 결합 룰 (자동 후처리)', H1))
    story.append(Paragraph(
        '• <b>수온히터 ON ↔ 배수밸브 OFF</b> — 가온을 위해 물 가둠 (mappers.py 룰)<br/>'
        '• <b>포그-수온 결합</b> — 수온 ≥ 20℃ 에서만 fog ON 허용 (가열된 수증기 분사)<br/>'
        '• <b>수온 &gt; 45℃ → fog OFF 강제</b> (안전 — 뜨거운 물 분사 방지)<br/>'
        '• <b>가열 시퀀스 hysteresis</b> — fog 토글: 수온 ≥ (실내 + 5℃) (채터링 방지)<br/>'
        '• <b>밸브-팬 인터록</b> — 팬 ON 시 해당 밸브 최소 10초 선행 ON 필수',
        BODY))

    # 푸터
    story.append(Spacer(1, 14))
    story.append(Paragraph(
        f'<para alignment="center"><font color="#888888">— 끝 — '
        f'AgriAI Core · 자동 생성 {now}</font></para>', BODY))

    doc.build(story)
    print(f'[gen_info_for_relay_control_pdf] 생성 완료: {OUT_PATH}')


if __name__ == '__main__':
    build()
