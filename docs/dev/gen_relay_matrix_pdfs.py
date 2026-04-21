#!/usr/bin/env python3
"""docs/relay_manual_matrix.pdf, docs/relay_llm_ai_control.pdf 생성 스크립트.

기존 docs/manual_relay_matrix.pdf 양식을 그대로 따라 가로 A4 매트릭스 PDF를
재생성한다. 새 결합규칙(_apply_fog_coupling)과 실내히터·히터밸브 미사용을
반영하기 위해 environment_logic 모듈을 직접 호출한 시뮬레이션 결과로
표를 채운다.

사용법:
    sudo /workspace/jayeondeule/venv/bin/python docs/dev/gen_relay_matrix_pdfs.py
"""
import os
import sys
from itertools import product

sys.path.insert(0, '/workspace/jayeondeule')
os.environ.setdefault('PYTHONDONTWRITEBYTECODE', '1')

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
)
from reportlab.platypus.flowables import KeepTogether

from agri_ai_core.src.control.environment_logic import (
    _determine_devices, _determine_circulation, _apply_fog_coupling,
)
from agri_ai_core.src.control.control_common import CIRCULATION_MODES


# ═══════════════════════════════════════════════════════════════════════════
# 한글 폰트 등록
# ═══════════════════════════════════════════════════════════════════════════
KR_REG = 'NanumGothic'
KR_BOLD = 'NanumGothic-Bold'
pdfmetrics.registerFont(TTFont(KR_REG, '/usr/share/fonts/truetype/nanum/NanumGothic.ttf'))
pdfmetrics.registerFont(TTFont(KR_BOLD, '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf'))


# ═══════════════════════════════════════════════════════════════════════════
# 색상 팔레트 (기존 manual_relay_matrix.pdf 참고)
# ═══════════════════════════════════════════════════════════════════════════
HEADER_BG = colors.HexColor('#1F4E79')
HEADER_FG = colors.white
ROW_ODD  = colors.HexColor('#F2F2F2')
ROW_EVEN = colors.white
ON_FG    = colors.HexColor('#C00000')
OFF_FG   = colors.HexColor('#404040')
CIRC_FG  = colors.HexColor('#1F4E79')
GRID     = colors.HexColor('#BFBFBF')


# ═══════════════════════════════════════════════════════════════════════════
# 차원 정의
# ═══════════════════════════════════════════════════════════════════════════
TEMP_STATES = [
    ('낮음(<27℃)',  26, 'low'),
    ('정상(27~30)', 28, 'normal'),
    ('높음(>30℃)', 31, 'high'),
]
EXT_TEMP_STATES = [
    ('정상',   28, 'normal'),
    ('비정상', 20, 'abnormal'),
]
HUMID_STATES = [
    ('낮음(<75%)',  70, 'low'),
    ('정상(75~85)', 80, 'normal'),
    ('높음(>85%)', 90, 'high'),
]
EXT_HUMID_STATES = [
    ('정상',   80, 'normal'),
    ('비정상', 60, 'abnormal'),
]
CO2_STATES = [
    ('정상(≤1200)', 800,  'normal'),
    ('높음(>1200)', 1300, 'high'),
]
EXT_CO2_STATES = [
    ('정상',   'normal'),
    ('비정상', 'abnormal'),
]
WATER_STATES = [
    ('낮음(<40℃)', 38),
    ('정상(≥40℃)', 45),
]


# ═══════════════════════════════════════════════════════════════════════════
# 모든 조합 enumerate → 행 생성
# ═══════════════════════════════════════════════════════════════════════════
def build_rows():
    rows = []
    idx = 0
    for (t_lbl, t_val, t_st), (et_lbl, et_val, et_st), \
        (h_lbl, h_val, h_st), (eh_lbl, eh_val, eh_st), \
        (c_lbl, c_val, c_st), (ec_lbl, ec_st), \
        (w_lbl, w_val) in product(
            TEMP_STATES, EXT_TEMP_STATES,
            HUMID_STATES, EXT_HUMID_STATES,
            CO2_STATES, EXT_CO2_STATES,
            WATER_STATES,
        ):
        idx += 1
        # _determine_devices → (water_heater, fog_pump)
        wh, fog = _determine_devices(t_st, h_st)
        devices = {'water_heater_flag': wh, 'fog_occurs_flag': fog}
        # 결합규칙 후처리
        sensor_data = {
            'indoor_temperature':  t_val,
            'indoor_humidity':     h_val,
            'co2':                 c_val,
            'outdoor_temperature': et_val,
            'outdoor_humidity':    eh_val,
            'water_temperature':   w_val,
        }
        _apply_fog_coupling(devices, sensor_data, scope="")

        # _determine_circulation
        circ = _determine_circulation(t_st, et_st, h_st, eh_st, c_st, ec_st)
        cm = CIRCULATION_MODES[circ]
        circ_v = cm['dampers']['air_circulation_valve_flag']
        in_v   = cm['dampers']['air_intake_valve_flag']
        out_v  = cm['dampers']['air_exhaust_valve_flag']
        in_f   = cm['fans']['intake_fan_flag']
        out_f  = cm['fans']['exhaust_fan_flag']

        rows.append([
            str(idx), t_lbl, et_lbl, h_lbl, eh_lbl, c_lbl, ec_lbl, w_lbl,
            'ON' if devices['water_heater_flag'] else 'OFF',
            'ON' if devices['fog_occurs_flag']   else 'OFF',
            circ,
            'ON' if circ_v else 'OFF',
            'ON' if in_v   else 'OFF',
            'ON' if out_v  else 'OFF',
            'ON' if in_f   else 'OFF',
            'ON' if out_f  else 'OFF',
        ])
    return rows


# ═══════════════════════════════════════════════════════════════════════════
# 표 헤더 정의 (2줄 헤더)
# ═══════════════════════════════════════════════════════════════════════════
HEADER1 = [
    '#', '내부\n온도', '외부\n온도', '내부\n습도', '외부\n습도', 'CO2',
    '외부\nCO2', '수온',
    '수온\n히터', '포그\n생성',
    '순환모드',
    '순환\n밸브', '흡기\n밸브', '배기\n밸브', '흡기\n팬', '배기\n팬',
]


# ═══════════════════════════════════════════════════════════════════════════
# 본문 표 스타일
# ═══════════════════════════════════════════════════════════════════════════
def make_table_style(n_rows, on_col_indices):
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR',  (0, 0), (-1, 0), HEADER_FG),
        ('FONTNAME',   (0, 0), (-1, 0), KR_BOLD),
        ('FONTSIZE',   (0, 0), (-1, 0), 7.5),
        ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID',       (0, 0), (-1, -1), 0.4, GRID),
        ('FONTNAME',   (0, 1), (-1, -1), KR_REG),
        ('FONTSIZE',   (0, 1), (-1, -1), 6.8),
        ('LEFTPADDING',  (0, 0), (-1, -1), 1),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING',   (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
    ])
    # 줄무늬
    for r in range(1, n_rows + 1):
        bg = ROW_ODD if r % 2 == 1 else ROW_EVEN
        style.add('BACKGROUND', (0, r), (-1, r), bg)
    return style


def colorize_cells(table_style, rows, on_col_indices, circ_col_index):
    """ON 텍스트는 빨강 + Bold, OFF 는 회색, 순환모드 셀은 청색 Bold."""
    for r, row in enumerate(rows, start=1):
        for c in on_col_indices:
            val = row[c]
            if val == 'ON':
                table_style.add('TEXTCOLOR', (c, r), (c, r), ON_FG)
                table_style.add('FONTNAME',  (c, r), (c, r), KR_BOLD)
            else:
                table_style.add('TEXTCOLOR', (c, r), (c, r), OFF_FG)
        # 순환모드 — 청색 Bold
        table_style.add('TEXTCOLOR', (circ_col_index, r), (circ_col_index, r), CIRC_FG)
        table_style.add('FONTNAME',  (circ_col_index, r), (circ_col_index, r), KR_BOLD)


# ═══════════════════════════════════════════════════════════════════════════
# manual_relay_matrix.pdf 생성
# ═══════════════════════════════════════════════════════════════════════════
def gen_manual_matrix(out_path):
    rows = build_rows()
    n = len(rows)

    page_w, page_h = landscape(A4)
    margin = 8 * mm

    doc = SimpleDocTemplate(
        out_path, pagesize=landscape(A4),
        leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'title', parent=styles['Title'],
        fontName=KR_BOLD, fontSize=14, leading=18, alignment=1,
        textColor=colors.HexColor('#1F4E79'),
    )
    subtitle_style = ParagraphStyle(
        'subtitle', parent=styles['Normal'],
        fontName=KR_REG, fontSize=8.5, leading=11, alignment=1,
        textColor=colors.HexColor('#404040'),
    )
    legend_style = ParagraphStyle(
        'legend', parent=styles['Normal'],
        fontName=KR_REG, fontSize=7.8, leading=10,
    )
    legend_h_style = ParagraphStyle(
        'legend_h', parent=legend_style,
        fontName=KR_BOLD, fontSize=8.5, textColor=colors.HexColor('#1F4E79'),
    )

    story = [
        Paragraph('자연들에 — 알고리즘 모드 전조합 센서→릴레이 제어 매트릭스', title_style),
        Paragraph(
            'environment_logic 실제 호출 기반 시뮬레이션 | '
            f'총 조합 = 3(내부온도) × 2(외부온도) × 3(내부습도) × 2(외부습도) × '
            f'2(CO2) × 2(외부CO2) × 2(수온) = {n} | 작성일: 2026-04-28',
            subtitle_style,
        ),
        Spacer(1, 4 * mm),
        Paragraph('범례 / 판정 기준', legend_h_style),
        Paragraph(
            '• 내부온도: 낮음&lt;27℃ · 정상 27~30℃ · 높음&gt;30℃ &nbsp;&nbsp; '
            '• 내부습도: 낮음&lt;75% · 정상 75~85% · 높음&gt;85% &nbsp;&nbsp; '
            '• CO2: 정상≤1200ppm · 높음&gt;1200ppm &nbsp;&nbsp; '
            '• 수온: 낮음&lt;40℃ · 정상≥40℃ (정상범위 35~55℃, 비상 &lt;35/&gt;60℃)',
            legend_style,
        ),
        Paragraph(
            '• 외부온도/외부습도/외부CO2: 정상(해당 센서 정상 범위 내) / 비정상(범위 이탈 또는 None)',
            legend_style,
        ),
        Paragraph(
            '• 출력 장치: 수온히터·포그생성은 _determine_devices + _apply_fog_coupling(결합규칙) 결과 / '
            '순환모드(내부·외부·흡입·배기·정지)와 5개 순환 출력(순환밸브·흡기밸브·배기밸브·흡기팬·배기팬)은 '
            '_determine_circulation + CIRCULATION_MODES 결과',
            legend_style,
        ),
        Paragraph(
            '• <b>결합규칙([2026-04-28] _apply_fog_coupling)</b>: '
            '수온히터 ON 또는 수온 ≥ 40℃ ⟹ 포그생성 강제 ON · 수온 &gt; 60℃ ⟹ 포그생성 강제 OFF · '
            '실내온도 &gt; 33℃ 고온비상은 결합 보류(안전 우선)',
            legend_style,
        ),
        Paragraph(
            '• 비상제어(임계 저/고)는 본 표에 포함되지 않음 — 일반 제어보다 우선하여 강제 적용됨 '
            '(sensor_relay_matrix.pdf 참조)',
            legend_style,
        ),
        Paragraph(
            '• 실내히터·히터밸브는 [2026-04-27] 모든 재배사에서 미사용으로 핀맵에서 제외됨 — 표 컬럼 없음',
            legend_style,
        ),
        Spacer(1, 4 * mm),
    ]

    # 표 폭 분배 (가로 A4 280mm 가용 폭에 맞춤)
    col_widths = [
        7*mm,    # #
        18*mm,   # 내부온도
        12*mm,   # 외부온도
        18*mm,   # 내부습도
        12*mm,   # 외부습도
        20*mm,   # CO2
        12*mm,   # 외부CO2
        18*mm,   # 수온
        13*mm,   # 수온히터
        13*mm,   # 포그생성
        20*mm,   # 순환모드
        13*mm,   # 순환밸브
        13*mm,   # 흡기밸브
        13*mm,   # 배기밸브
        12*mm,   # 흡기팬
        12*mm,   # 배기팬
    ]

    # 페이지당 행 수 (헤더 반복)
    ROWS_PER_PAGE = 36
    on_cols = [8, 9, 11, 12, 13, 14, 15]  # ON/OFF 컬럼들
    circ_col = 10

    for page_start in range(0, n, ROWS_PER_PAGE):
        page_rows = rows[page_start: page_start + ROWS_PER_PAGE]
        data = [HEADER1] + page_rows
        t = Table(data, colWidths=col_widths, repeatRows=1)
        ts = make_table_style(len(page_rows), on_cols)
        colorize_cells(ts, page_rows, on_cols, circ_col)
        t.setStyle(ts)
        story.append(t)
        if page_start + ROWS_PER_PAGE < n:
            story.append(PageBreak())

    doc.build(story)
    print(f'[OK] {out_path} (페이지 {(n + ROWS_PER_PAGE - 1)//ROWS_PER_PAGE}, 총 {n}행)')


# ═══════════════════════════════════════════════════════════════════════════
# relay_llm_ai_control.pdf 생성
# ═══════════════════════════════════════════════════════════════════════════
def gen_ai_control(out_path):
    page_w, page_h = landscape(A4)
    margin = 12 * mm
    doc = SimpleDocTemplate(
        out_path, pagesize=landscape(A4),
        leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'title', parent=styles['Title'],
        fontName=KR_BOLD, fontSize=15, leading=20, alignment=1,
        textColor=colors.HexColor('#1F4E79'),
    )
    subtitle_style = ParagraphStyle(
        'subtitle', parent=styles['Normal'],
        fontName=KR_REG, fontSize=9, leading=12, alignment=1,
        textColor=colors.HexColor('#404040'),
    )
    h2 = ParagraphStyle(
        'h2', parent=styles['Heading2'],
        fontName=KR_BOLD, fontSize=11, leading=15,
        textColor=colors.HexColor('#1F4E79'),
        spaceBefore=8, spaceAfter=4,
    )
    h3 = ParagraphStyle(
        'h3', parent=styles['Heading3'],
        fontName=KR_BOLD, fontSize=9.5, leading=13,
        textColor=colors.HexColor('#2E5C8A'),
        spaceBefore=4, spaceAfter=2,
    )
    body = ParagraphStyle(
        'body', parent=styles['Normal'],
        fontName=KR_REG, fontSize=8.5, leading=12,
    )
    code = ParagraphStyle(
        'code', parent=styles['Code'],
        fontName='Courier', fontSize=8, leading=11,
        leftIndent=6, textColor=colors.HexColor('#222'),
    )

    story = [
        Paragraph('자연들에 — 인공지능(LLM) 제어 메커니즘 명세', title_style),
        Paragraph(
            'agri_ai_core.src.control.ai_control 기반 | 호출 흐름 · 프롬프트 구조 · '
            '학습/맥락 데이터 · 안전검증 · 보호장치 | 작성일: 2026-04-28',
            subtitle_style,
        ),
        Spacer(1, 4 * mm),

        # ── 1. 개요 ──
        Paragraph('1. 개요', h2),
        Paragraph(
            'AI 제어 모드는 알고리즘 모드의 모든 안전장치(비상제어·인터록 게이트·결합규칙·'
            '미매핑 강제 OFF·보호장치)를 그대로 유지한 채, 그 위에 LLM 의사결정 계층을 '
            '얹은 구조이다. LLM 출력은 반드시 _validate_safety 6단계를 통과한 후에만 '
            '_execute_control(2-phase 시퀀스)로 전달된다. '
            '<b>본 문서가 다루는 환경제어 LLM 호출 경로(control_ai_environment)에 한해서는</b> '
            '외부 학습 데이터·RAG·벡터DB·fine-tuning을 사용하지 않으며, '
            '매 호출마다 시스템 프롬프트 + 유저 프롬프트를 stateless로 재생성한다. '
            '(주의: 코드베이스 전체에는 별도 목적의 RAG·Chroma·learning 모듈이 존재하나 '
            '환경제어 의사결정 경로에서는 import·호출되지 않는다 — 8장 참조)',
            body,
        ),

        # ── 2. 호출 트리거 ──
        Paragraph('2. LLM 호출 트리거 (3계층)', h2),
    ]
    trig_data = [
        ['계층', '주체', '주기', '호출 조건', 'LLM 호출'],
        ['L1', 'control_all_manual (스케줄러)', '10초', 'AI 모드 재배사 순회 — 비상제어 + 모니터링만', '아니오'],
        ['L2', 'monitor_ai_emergency', '10초', '임계치 80% 근접 OR 트렌드 5분 후 비상 도달 예측', '예 (즉시)'],
        ['L3', '_ai_control_loop (별도 스레드)', '재배사 간 30초', 'AI 모드 재배사 순환, 정기 LLM 호출', '예'],
    ]
    trig_t = Table(trig_data, colWidths=[15*mm, 65*mm, 25*mm, 110*mm, 25*mm])
    trig_t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR',  (0, 0), (-1, 0), HEADER_FG),
        ('FONTNAME',   (0, 0), (-1, 0), KR_BOLD),
        ('FONTSIZE',   (0, 0), (-1, 0), 8.5),
        ('FONTNAME',   (0, 1), (-1, -1), KR_REG),
        ('FONTSIZE',   (0, 1), (-1, -1), 8),
        ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN',      (3, 0), (3, -1), 'LEFT'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID',       (0, 0), (-1, -1), 0.4, GRID),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(trig_t)
    story.append(Paragraph(
        '호출 파라미터: <b>Ollama /api/generate</b> · temperature=0(결정론) · num_predict=200 · '
        'stream=false · AI_CONTROL_TIMEOUT=60s · AI_PROXIMITY_RATIO=0.8 · AI_CONTROL_LOOP_DELAY_SEC=30s',
        body,
    ))

    # ── 3. 시스템 프롬프트 ──
    story.append(Paragraph('3. 시스템 프롬프트 — LLM에 정적 주입되는 도메인 지식', h2))
    story.append(Paragraph(
        '_build_system_prompt(growth_stage)이 매 호출마다 재구성. 생육단계별 가이드 섹션만 동적 분기.',
        body,
    ))
    sys_data = [
        ['섹션', '내용'],
        ['재배사 구조', '공기흐름: 바닥 흡입덕트 → 환풍기 → 열냉가습기 → 환풍기 → 상단 배출덕트 / '
                       '열냉가습기 = 지하수 탱크 + 수온히터 + 포그생성'],
        ['제어 장치 8종',
         'water_heater · fog_occurs · intake_fan · exhaust_fan · '
         'air_circulation_valve · air_intake_valve · air_exhaust_valve · '
         '보호장치 3종(lighting/irrigation/drainage_motor — 변경 금지)'],
        ['결합 규칙\n(2026-04-28 신규)',
         'water_heater_flag=true ⟹ fog_occurs_flag=true · 수온 ≥ 40℃ ⟹ fog ON · '
         '수온 > 60℃ ⟹ fog OFF · 온도 우선 → 고습 시에도 결합 적용 / 실내온도 > 33℃ 고온비상은 결합 보류'],
        ['순환모드 5종',
         '내부·외부·흡입·배기·순환정지 — 각 모드별 밸브/팬 ON·OFF 매핑. "밸브 후 15초 → 팬" 시퀀스 명시'],
        ['우선순위', '온도 > 습도 > CO2 (상위 결정을 하위가 뒤집지 않음)'],
        ['1순위 온도', '저온(<27): 수온히터+포그ON, 내부순환 / 고온(>30): 가열 OFF, 배기순환'],
        ['2순위 습도', '저습(<75): 포그ON 내부순환 / 고습(>85): 포그OFF 배기순환 (단, 저온이면 결합규칙 우선)'],
        ['3순위 CO2',  '고(>1200): 배기순환 (단, 저온이면 내부순환 유지)'],
        ['복합 상황 예시', '저온+고습 / 저온+저습 / 고온+저습 / 고온+고습 / 정상+고습+고CO2 / 정상+저습+고CO2 (6가지)'],
        ['외부순환 제한', '외부온 27~30 + 외부습 75~85 만족 시에만 가동 가능 — 그 외는 거부'],
        ['생육단계별 가이드',
         '발이기(29~33℃ 단독 판단) / 수확기(관수 OFF, 배기 우선) / 생육기(전체 임계값 적용)'],
        ['비상 임계값',
         '온도 <25/>33 · 습도 <70/>95 · CO2 >1500 · 수온 <35/>60 — 모든 케이스 고정 응답 명시'],
        ['선행 조치 규칙',
         '정상범위 경계 접근 시 비상 도달 전 예방 조치 (외부순환 / 포그 가동) — 트렌드 분석 결과 활용'],
        ['응답 형식',
         'JSON 1개만, 키: action(keep/change) · reason · devices · circulation. 설명 없이 JSON만'],
    ]
    sys_t = Table(sys_data, colWidths=[40*mm, 200*mm])
    sys_t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR',  (0, 0), (-1, 0), HEADER_FG),
        ('FONTNAME',   (0, 0), (-1, 0), KR_BOLD),
        ('FONTSIZE',   (0, 0), (-1, 0), 8.5),
        ('FONTNAME',   (0, 1), (0, -1), KR_BOLD),
        ('FONTNAME',   (1, 1), (1, -1), KR_REG),
        ('FONTSIZE',   (0, 1), (-1, -1), 8),
        ('ALIGN',      (0, 0), (0, -1), 'CENTER'),
        ('ALIGN',      (1, 0), (1, -1), 'LEFT'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID',       (0, 0), (-1, -1), 0.4, GRID),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING',   (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 2.5),
    ]))
    story.append(sys_t)

    # 페이지 분리
    story.append(PageBreak())

    # ── 4. 유저 프롬프트 ──
    story.append(Paragraph('4. 유저 프롬프트 — 매 호출마다 동적 주입되는 현재 상태', h2))
    user_data = [
        ['데이터', '출처', '용도'],
        ['현재 센서값 6종', 'read_current_sensor_info\n(DB sensor_l_recording 최신 행)',
         '내부 온/습/CO2, 외부 온/습, 수온 — 모든 의사결정의 입력'],
        ['생육단계',     'read_current_growth_stage\n(재배사별 진행 일자 기준)',
         '발이기/생육기/수확기 — 적정 임계값과 제어 정책 분기'],
        ['최적조건',     'read_optimal_condition\n(DB OPTIMAL_TBL)',
         '재배사·생육단계별 온도/습도 최저·최고 — 정적 룩업 형태로 제공'],
        ['현재 릴레이 ON 목록', 'read_latest_relay_info\n→ pin_map 역변환 → 시멘틱',
         '보호장치(조명·관수·배수)는 의도적 제외 → LLM 변경 차단'],
        ['트렌드 분석',  '_detect_trend\n(인메모리 deque, 재배사별 30회)',
         '분당 변화율 + 5분 후 예측 — 비상 도달 예측 시 텍스트로 주입'],
    ]
    user_t = Table(user_data, colWidths=[40*mm, 65*mm, 135*mm])
    user_t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR',  (0, 0), (-1, 0), HEADER_FG),
        ('FONTNAME',   (0, 0), (-1, 0), KR_BOLD),
        ('FONTSIZE',   (0, 0), (-1, 0), 8.5),
        ('FONTNAME',   (0, 1), (0, -1), KR_BOLD),
        ('FONTNAME',   (1, 1), (-1, -1), KR_REG),
        ('FONTSIZE',   (0, 1), (-1, -1), 8),
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN',      (0, 1), (-1, -1), 'LEFT'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID',       (0, 0), (-1, -1), 0.4, GRID),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING',   (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
    ]))
    story.append(user_t)

    # ── 5. 트렌드/근접 분석 ──
    story.append(Paragraph('5. 트렌드 / 임계치 근접 분석 (LLM 호출 트리거 + 컨텍스트)', h2))
    trend_data = [
        ['분석',         '함수',                     '입력',                                '출력'],
        ['트렌드 감지',  '_detect_trend',            '최근 30회 (온/습/CO2, timestamp)',
         '(감지여부, 텍스트) — 예: "온도 상승 추세 +0.4℃/분 (5분 후 32.1℃ 예측)"'],
        ['임계치 근접',  '_check_threshold_proximity', '현재 센서 + 임계상수',
         '정상범위 이탈 후 비상 임계까지 진행률 ≥ 80% (AI_PROXIMITY_RATIO=0.8)'],
        ['긴급 개입 판단', 'monitor_ai_emergency',     '위 두 결과 OR',
         'True 면 정기 30초 주기를 무시하고 즉시 LLM 호출'],
    ]
    trend_t = Table(trend_data, colWidths=[35*mm, 50*mm, 60*mm, 100*mm])
    trend_t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR',  (0, 0), (-1, 0), HEADER_FG),
        ('FONTNAME',   (0, 0), (-1, 0), KR_BOLD),
        ('FONTSIZE',   (0, 0), (-1, 0), 8.5),
        ('FONTNAME',   (0, 1), (0, -1), KR_BOLD),
        ('FONTNAME',   (1, 1), (-1, -1), KR_REG),
        ('FONTSIZE',   (0, 1), (-1, -1), 8),
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN',      (0, 1), (-1, -1), 'LEFT'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID',       (0, 0), (-1, -1), 0.4, GRID),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(trend_t)

    # ── 6. 안전검증 ──
    story.append(Paragraph('6. LLM 응답 안전검증 (_validate_safety) — 6단계', h2))
    safe_data = [
        ['#', '단계',            '처리 내용'],
        ['1', '비상 온도 위반 방지',
         '실내온도 > 33℃: 가열장치(수온히터) 강제 OFF + 순환모드 배기순환 강제 / '
         '실내온도 < 25℃: 수온히터 강제 ON'],
        ['2', '비상 습도 위반 방지',
         '실내습도 > 95%: 포그생성 강제 OFF / 실내습도 < 70%: 포그생성 강제 ON'],
        ['3', '수온 비상 위반 방지',
         '수온 > 60℃: 수온히터 강제 OFF / 수온 < 35℃: 수온히터 강제 ON'],
        ['4', '외부순환 제한 검증',
         '외부 온도 27~30℃ 또는 외부 습도 75~85% 범위 밖이면 LLM이 외부순환 결정해도 내부순환으로 자동 전환'],
        ['5', '결합 규칙 (2026-04-28 신규)',
         '_apply_fog_coupling 위임 — (a) 수온히터 ON ⟹ 포그 ON, '
         '(b) 수온 ≥ 40℃ ⟹ 포그 ON, (c) 수온 > 60℃ ⟹ 포그 OFF, '
         '(d) 실내온도 > 33℃ 고온비상은 결합 보류(안전 우선)'],
        ['6', '순환모드 유효성',
         'VALID_CIRCULATIONS 5종(내부·외부·흡입·배기·정지) 외 응답은 거부 → action="keep"으로 폴백'],
    ]
    safe_t = Table(safe_data, colWidths=[8*mm, 50*mm, 195*mm])
    safe_t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR',  (0, 0), (-1, 0), HEADER_FG),
        ('FONTNAME',   (0, 0), (-1, 0), KR_BOLD),
        ('FONTSIZE',   (0, 0), (-1, 0), 8.5),
        ('FONTNAME',   (0, 1), (1, -1), KR_BOLD),
        ('FONTNAME',   (2, 1), (2, -1), KR_REG),
        ('FONTSIZE',   (0, 1), (-1, -1), 8),
        ('ALIGN',      (0, 0), (1, -1), 'CENTER'),
        ('ALIGN',      (2, 1), (2, -1), 'LEFT'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID',       (0, 0), (-1, -1), 0.4, GRID),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING',   (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
    ]))
    story.append(safe_t)

    # 페이지 분리
    story.append(PageBreak())

    # ── 7. 보호장치 ──
    story.append(Paragraph('7. 보호장치 / 미매핑 차단', h2))
    prot_data = [
        ['메커니즘', '구현', '효과'],
        ['PROTECTED_DEVICES', "{'lighting_flag', 'irrigation_flag', 'drainage_motor_flag'}",
         'LLM 응답에 해당 키가 들어와도 변경 적용 안함 — 별도 스케줄(조명/관수)·상시 ON(배수밸브) 보장'],
        ['force_off_unmapped_relays', 'control_common 헬퍼 (모든 모드 공통)',
         '핀맵 미등록 릴레이(현재 1·3호의 9·15번 = 실내히터/히터밸브)는 항상 강제 OFF — DB 쓰기 단계에서 적용'],
        ['evaluate_interlock\n(밸브-팬 인터록 게이트)', 'interlock.py — Rule 1~5',
         '흡입팬/배출팬 OFF→ON 전이 시 선행 밸브 dwell(15초) 검증 — 위반 시 ON 차단 / '
         '밸브 ON→OFF 시 의존 팬 자동 OFF 보정 / Rule 5: ¬FI∨VI ∧ ¬FE∨VE 형태로 동시 ON 안전성 보장'],
        ['raw_mode + 16개 일괄 쓰기', 'set_relay_value(raw_mode=True)',
         'AI/알고리즘 결정은 raw_mode=False로 별칭→핀 매핑 적용 / 수동제어는 raw_mode=True 16개 직접 쓰기'],
    ]
    prot_t = Table(prot_data, colWidths=[45*mm, 65*mm, 145*mm])
    prot_t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR',  (0, 0), (-1, 0), HEADER_FG),
        ('FONTNAME',   (0, 0), (-1, 0), KR_BOLD),
        ('FONTSIZE',   (0, 0), (-1, 0), 8.5),
        ('FONTNAME',   (0, 1), (0, -1), KR_BOLD),
        ('FONTNAME',   (1, 1), (-1, -1), KR_REG),
        ('FONTSIZE',   (0, 1), (-1, -1), 8),
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN',      (0, 1), (-1, -1), 'LEFT'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID',       (0, 0), (-1, -1), 0.4, GRID),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING',   (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
    ]))
    story.append(prot_t)

    # ── 8. 학습 데이터/RAG 정책 ──
    story.append(Paragraph('8. 학습 데이터 / RAG 정책 (환경제어 LLM 경로 한정)', h2))
    story.append(Paragraph(
        '<b>본 명세가 다루는 환경제어 LLM 호출 경로(agri_ai_core/src/control/ai_control.py)에 한해서는 '
        '외부 학습 데이터 · RAG · 벡터DB · fine-tuning을 사용하지 않는다.</b> '
        'ai_control.py 의 import 그래프를 검증한 결과, chroma · embedder · rag · learning 패키지를 '
        'import 하지 않으며 Ollama generate API 직접 호출만으로 의사결정을 수행한다. '
        '환경제어 LLM에 주입되는 모든 "지식"은 다음 두 가지로만 구성된다.',
        body,
    ))
    story.append(Paragraph(
        '(a) <b>시스템 프롬프트</b>의 정적 규칙 — 재배사 구조, 결합 규칙, 우선순위, 비상 임계값, 응답 형식 등 '
        '_build_system_prompt에 하드코딩됨.',
        body,
    ))
    story.append(Paragraph(
        '(b) <b>유저 프롬프트</b>의 현재 스냅샷 — read_current_sensor_info / read_latest_relay_info / '
        'read_optimal_condition / _detect_trend의 결과를 매 호출마다 새로 빌드.',
        body,
    ))
    story.append(Paragraph(
        '즉 환경제어 LLM은 매 호출마다 동일한 룰북을 다시 읽고, 현재 스냅샷만 가지고 판단한다. '
        '과거 의사결정 이력은 트렌드 분석 deque(재배사별 30회 센서값)을 제외하면 LLM에 전달되지 않는다. '
        '모델 파일은 Ollama 로컬 저장소(/workspace/jayeondeule/.ollama/models)에서 로드되며, 호스트 외부와의 '
        '데이터 송수신은 없다.',
        body,
    ))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph('8-1. 코드베이스 내 별도 RAG / 학습 모듈 (환경제어와 무관)', h3))
    story.append(Paragraph(
        '코드베이스 전체에는 환경제어와 별개 목적의 RAG/학습 인프라가 존재한다. 본 문서의 환경제어 '
        '의사결정 경로에서는 호출되지 않으나, 시스템 전체상으로 "RAG/벡터DB가 전혀 없다"고 오해하지 '
        '않도록 명시한다. 환경제어와의 격리 여부는 ai_control.py 의 import 그래프로 보증된다.',
        body,
    ))
    rag_data = [
        ['모듈 / 패키지', '경로', '주요 용도 (환경제어 외)'],
        ['Chroma 벡터DB', 'agri_ai_core/src/chroma/',
         '벡터 컬렉션 관리 · 임베딩 저장 · 유사도 검색'],
        ['RAG 청커/상수', 'agri_ai_core/src/ai/rag/',
         '문서 청킹 / RAG 파라미터 정의'],
        ['Embedder',     'agri_ai_core/src/ai/embedder.py',
         '텍스트 임베딩 생성 (Chroma 적재용)'],
        ['Learning · Trainer', 'agri_ai_core/src/ai/learning/model_trainer.py',
         '모델 학습/적응 파이프라인 (별도 트리거 시)'],
        ['Tools Data',   'agri_ai_core/src/ai/tools_data.py',
         'LLM 도구(tool-use) 데이터 핸들링'],
    ]
    rag_t = Table(rag_data, colWidths=[40*mm, 65*mm, 130*mm])
    rag_t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR',  (0, 0), (-1, 0), HEADER_FG),
        ('FONTNAME',   (0, 0), (-1, 0), KR_BOLD),
        ('FONTSIZE',   (0, 0), (-1, 0), 8.5),
        ('FONTNAME',   (0, 1), (0, -1), KR_BOLD),
        ('FONTNAME',   (1, 1), (-1, -1), KR_REG),
        ('FONTSIZE',   (0, 1), (-1, -1), 8),
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN',      (0, 1), (-1, -1), 'LEFT'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID',       (0, 0), (-1, -1), 0.4, GRID),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING',   (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 2.5),
    ]))
    story.append(rag_t)
    story.append(Paragraph(
        '<b>격리 검증</b>: <font face="Courier">grep -E "chroma|rag|embed|vector"</font> 를 '
        '환경제어 결정에 관여하는 3개 모듈(<font face="Courier">ai_control.py · manual_control.py · '
        'environment_logic.py</font>)에 대해 실행한 결과 모두 매칭 없음. '
        '단 같은 control 패키지의 <font face="Courier">task_scheduler.py</font> 는 별도의 '
        'growth_rag_job(매일 정오/자정 스케줄)을 등록하기 위해 chroma.collections / chroma.operations 를 '
        'import 하지만, 이는 환경제어 의사결정 경로와 직접 연결되지 않는 독립 스케줄 작업이다.',
        body,
    ))

    # ── 9. 의사결정 흐름도 (텍스트) ──
    story.append(Paragraph('9. 종합 의사결정 흐름', h2))
    flow_data = [
        ['단계', '주체', '동작', '실패/거부 시'],
        ['1', '스케줄러 (10초)',
         'control_all_manual → AI 모드 재배사 식별 → _handle_ai_emergency 호출',
         '비상 트리거 → 비상제어 즉시 실행 (LLM 미호출)'],
        ['2', 'monitor_ai_emergency',
         '_check_threshold_proximity OR _detect_trend (5분 후 비상 예측)',
         '정상이면 종료 (정기 30초 루프 대기)'],
        ['3', 'L3 _ai_control_loop',
         '재배사 순환 → control_ai_environment 호출',
         '센서 데이터 없음 → action="keep" 반환'],
        ['4', '_call_llm',
         'Ollama /api/generate (system + user 프롬프트, temp=0, num_predict=200)',
         '60s 타임아웃 또는 에러 → action="keep"'],
        ['5', '_parse_relay_response',
         'JSON 추출 (1단계 중첩 정규식) → action/devices/circulation 정규화',
         '파싱 실패 → action="keep"'],
        ['6', '_validate_safety',
         '6단계 안전 검증 + 결합규칙 + 외부순환 제한',
         '검증 실패 → action="keep"'],
        ['7', '_execute_control',
         'Phase 1: 밸브 + heater/fog 즉시 적용 → 15초 대기 → Phase 2: 팬 최종 상태',
         'evaluate_interlock 위반 → 자동 보정 + interlockViolations 응답'],
        ['8', 'set_relay_value\n→ DB SET_RELAY_VALUE',
         'raw_mode=False로 16개 정렬 tuple 쓰기 + 14초 반복 쓰기 스레드 (IoT 폴링 생존)',
         '쓰기 실패 → 다음 주기에서 재시도'],
    ]
    flow_t = Table(flow_data, colWidths=[10*mm, 45*mm, 110*mm, 90*mm])
    flow_t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR',  (0, 0), (-1, 0), HEADER_FG),
        ('FONTNAME',   (0, 0), (-1, 0), KR_BOLD),
        ('FONTSIZE',   (0, 0), (-1, 0), 8.5),
        ('FONTNAME',   (0, 1), (1, -1), KR_BOLD),
        ('FONTNAME',   (2, 1), (-1, -1), KR_REG),
        ('FONTSIZE',   (0, 1), (-1, -1), 7.8),
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN',      (0, 1), (1, -1), 'CENTER'),
        ('ALIGN',      (2, 1), (-1, -1), 'LEFT'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID',       (0, 0), (-1, -1), 0.4, GRID),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING',   (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 2.5),
    ]))
    story.append(flow_t)

    doc.build(story)
    print(f'[OK] {out_path}')


# ═══════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    out_dir = '/workspace/jayeondeule/docs'
    gen_manual_matrix(os.path.join(out_dir, 'relay_manual_matrix.pdf'))
    gen_ai_control(os.path.join(out_dir, 'relay_llm_ai_control.pdf'))
