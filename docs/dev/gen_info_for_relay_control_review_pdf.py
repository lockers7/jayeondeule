#!/usr/bin/env python3
"""docs/info_for_relay_control_review.pdf 생성 — 개선 검토 제안서.

info_for_relay_control.pdf 의 모든 섹션 (§1~§7) 을 재분석하고,
중복/모순/혼란/verbosity 영역을 분류하여 개선안을 제안.
사용자 검토 후 적용 여부 결정용.

A4 세로 · 한국어 NanumGothic.
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
    TableStyle,
)

KR_REG = 'NanumGothic'
KR_BOLD = 'NanumGothic-Bold'
pdfmetrics.registerFont(TTFont(KR_REG, '/usr/share/fonts/truetype/nanum/NanumGothic.ttf'))
pdfmetrics.registerFont(TTFont(KR_BOLD, '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf'))

OUT_PATH = '/workspace/jayeondeule/docs/info_for_relay_control_review.pdf'


# ────────────────────────────────────────────────────────────────────
# 스타일 정의
# ────────────────────────────────────────────────────────────────────
TITLE = ParagraphStyle('Title', fontName=KR_BOLD, fontSize=18, leading=24,
                       alignment=1, spaceAfter=6)
SUBTITLE = ParagraphStyle('Subtitle', fontName=KR_REG, fontSize=10, leading=14,
                          alignment=1, textColor=colors.HexColor('#555555'),
                          spaceAfter=14)
H1 = ParagraphStyle('H1', fontName=KR_BOLD, fontSize=14, leading=20,
                    textColor=colors.HexColor('#1F4E79'),
                    spaceBefore=14, spaceAfter=8)
H2 = ParagraphStyle('H2', fontName=KR_BOLD, fontSize=11, leading=16,
                    textColor=colors.HexColor('#2E5984'),
                    spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle('Body', fontName=KR_REG, fontSize=9.2, leading=13,
                      spaceAfter=4)
CODE = ParagraphStyle('Code', fontName=KR_REG, fontSize=8.0, leading=11,
                      textColor=colors.HexColor('#222222'),
                      leftIndent=8, rightIndent=4,
                      spaceBefore=2, spaceAfter=4)
NOTE = ParagraphStyle('Note', fontName=KR_REG, fontSize=8.5, leading=12,
                      textColor=colors.HexColor('#7B3F00'),
                      spaceAfter=4, leftIndent=4)


def make_table(rows, col_widths=None, header=True, font_size=8.3,
               first_col_bold=False):
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
    if first_col_bold:
        style_cmds.append(('FONTNAME', (0, 1), (0, -1), KR_BOLD))
    t = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
    t.setStyle(TableStyle(style_cmds))
    return t


# ────────────────────────────────────────────────────────────────────
# 컨텐츠 데이터
# ────────────────────────────────────────────────────────────────────

EXEC_SUMMARY = (
    "현재 시스템 프롬프트는 <b>9,300자 (약 5,000~9,000 토큰)</b> 으로, gemma3:27b "
    "27B 모델 기준 LLM 응답 시간 75-150초의 한 원인입니다. 분석 결과 "
    "<b>중복 8건, 빈 블록 1건, 미치환 placeholder 4건</b> 이 발견되어 "
    "이를 통합/제거하면 약 <b>4,000자 (50% 이하)</b> 로 단축 가능합니다.<br/><br/>"
    "본 문서는 모든 섹션을 재분석하여 개선안을 제시합니다. 적용은 단계적으로 "
    "(Phase 1~4) 진행하며, 각 단계마다 LLM 결정 분포 검증 후 다음 단계로 "
    "진행합니다. 사용자의 핵심 원칙 — '현재 기능을 위협하지 않을 것' — 을 준수하기 "
    "위해 <b>위험 등급 낮음 항목부터 우선 적용</b>합니다."
)

CURRENT_STRUCTURE = [
    ['섹션', '내용', '길이', '평가'],
    ['§1', '시설 구조',          '~250자', '✓ 명료'],
    ['§2', '제어 장치 매핑',     '~600자', '✓ 자동 생성'],
    ['§3', '결합 규칙 (포그-수온)', '~700자', '⚠ §15와 중복'],
    ['§4', '순환 모드 5종',      '~800자', '✓ 명료 표'],
    ['§5', '제어 우선순위',      '~1,400자', '⚠ §10/§13과 중복'],
    ['§6', '외부순환 제한',      '~250자', '⚠ §10 비상 #2/#7과 분산'],
    ['§7', '현재 생육단계',      '~250자', '✓ 동적 주입'],
    ['§8', '비상 임계 처리 정책', '~30자',  '✗ 빈 헤더 (본문 없음)'],
    ['§9', '운용·비상 분리 원칙', '~700자', '✓ 명료'],
    ['§10', '7개 비상 정책',     '~2,400자', '⚠ ${TEMP_LOW} 미치환 4곳'],
    ['§11', '일반 보조 룰',      '~80자',  '✗ §3 결합 룰과 중복'],
    ['§12', '선행 조치 규칙',    '~350자', '✓ 명료'],
    ['§13', '수온히터 가동 정책', '~1,200자', '⚠ §5/§10과 중복'],
    ['§14', '컨텍스트 활용 가이드', '~1,800자', '⚠ 16종 명시 vs 실 발송 11종'],
    ['§15', '응답 형식 + 가열시퀀스', '~2,100자', '⚠ §3 결합 룰과 hysteresis 중복'],
]

ISSUES = [
    ['#', '분류',     '위치',                 '내용',                                   '심각도'],
    ['1', '중복',     '§3 + §15',            '포그 결정 룰 2개 (단일조건 vs hysteresis)', '높음'],
    ['2', '중복',     '§5 + §10 + §13',      '저온 → heater ON 룰 4번 반복',             '중'],
    ['3', '혼란',     '§5 (38℃) vs §10 (32℃)', '고온 임계 적정상한 vs 임계상한 분산',     '중'],
    ['4', '분산',     '§6 + §10 #2/#7',      '외부순환 가능 조건 3곳 분산',              '중'],
    ['5', '빈 블록',  '§8',                  '"비상 임계 처리 정책" 헤더만 있고 본문 없음', '낮음'],
    ['6', '미치환',   '§10 #2/#3/#4/#7',     '${TEMP_LOW}/${TEMP_HIGH} placeholder 그대로', '높음'],
    ['7', '중복',     '§3 + §13 + §15',      'hysteresis 룰 (실내+5℃) 3곳 반복',         '중'],
    ['8', '불일치',   '§14 (16종) vs 실 발송 (11종)', '컨텍스트 가이드와 실 데이터 어긋남', '낮음'],
]

REPLACE_HEAT = [
    ['', 'Before (현재)', 'After (개선안)'],
    ['길이', '약 600+700+1200 = 2,500자 (3개 섹션 분산)', '약 350자 (1개 섹션 통합)'],
    ['위치', '§3, §13, §15 분산',                      '§3 단일 (포그 + 수온히터 룰 통합)'],
    ['내용', '단일 임계(20℃) vs hysteresis(+5℃) 모순 가능', '단일 hysteresis 룰만 유지'],
    ['LLM 영향', '판단 충돌 가능 — 어느 룰을 따라야?',         '명확한 단일 출처'],
]

REPLACE_PRIORITY = [
    ['', 'Before (현재)', 'After (개선안)'],
    ['길이', '약 1,400+2,400+1,200 = 5,000자',           '약 1,500자'],
    ['위치', '§5 (우선순위) + §10 (비상 정책) + §13 (수온히터)', '§2 (결정 우선순위) + §5 (비상)'],
    ['내용',
       '저온 → heater ON 룰이 4번 (§5 1순위, §10 #1, §13 ON#1, §13 ON#2) 반복',
       '저온 → heater ON 룰이 §2 1순위 한 번만'],
    ['LLM 영향', '같은 정보 4번 처리 → token 낭비',          '단일 출처 → token 효율화'],
]

REPLACE_OUTSIDE = [
    ['', 'Before (현재)', 'After (개선안)'],
    ['길이', '§6 (250자) + §10 #2 외기 분기 (300자) + §10 #7 (200자) = 750자', '약 200자'],
    ['위치', '§6 (외부순환 제한) + §10 #2 (고온비상 외기 분기) + §10 #7 (CO2 외기 분기)', '§4 (외부순환 단일 룰)'],
    ['내용', '외부순환 가능 조건이 3곳에 분산',             '하나의 표로 통합'],
    ['LLM 영향', '비상 시 어느 룰 따라야? 헷갈림',          '명확'],
]

REPLACE_PLACEHOLDER = [
    ['', 'Before (현재)', 'After (개선안)'],
    ['길이', '동일',                                     '동일'],
    ['위치', '§10 #2/#3/#4/#7 4곳에 ${TEMP_LOW}/${TEMP_HIGH} 미치환', '4곳 모두 호기별 동적 주입'],
    ['내용', 'LLM 이 §7 생육단계에서 추론해야 함',         '명시적 수치로 한 번에 명확'],
    ['LLM 영향', '추론 시 일관성 부족 위험',                '바로 정확한 수치 사용'],
]

NEW_STRUCTURE = [
    ['#',  '섹션',                          '대략 길이', '비고'],
    ['1',  '시설 구조 + 5종 순환 모드',       '~600자',   '§1+§2+§4 통합'],
    ['2',  '결정 우선순위 (온도>습도>CO2)',   '~700자',   '§5 그대로 + §13 ON 사유 흡수'],
    ['3',  '포그 단일 룰 (hysteresis)',      '~250자',   '§3+§15 통합 (모순 제거)'],
    ['4',  '외부순환 제한',                   '~200자',   '§6+§10 #2/#7 통합'],
    ['5',  '비상 자동 오버라이드 (5종)',     '~700자',   '§9 + §10 강제 항목만 요약'],
    ['6',  '현재 호기 임계 (동적 주입)',     '~250자',   '§7 그대로'],
    ['7',  '추가 컨텍스트 (user_prompt 11블록)', '~500자', '§14 - 미발송 4종 제거'],
    ['8',  '결합 후처리 (자동)',              '~150자',   '§11 흡수 (heater ON ↔ drainage OFF)'],
    ['9',  '응답 JSON 스키마',               '~600자',   '§15 핵심만 (예시 4개 → 2개)'],
]

PHASES = [
    ['Phase', '변경',                          '예상 효과',                            '위험', '검증'],
    ['1',     '포그 단일 룰 (§3+§15→§3)',      '650자 절감 · 모순 제거',                '낮',  '5cycle LLM 비교'],
    ['2',     '외부순환 통합 (§6+§10→§4)',     '550자 절감 · 분산 해소',                '낮',  '5cycle LLM 비교'],
    ['3',     'placeholder 치환 (§10 4곳)',    '명확성 ↑',                              '낮',  '추론 정확도 비교'],
    ['4',     '우선순위 통합 (§5+§10+§13→§2)', '3,500자 절감 · 핵심 단일 출처',         '중',  '14일 운영 분포'],
    ['5',     '컨텍스트 가이드 정리 (§14)',     '900자 절감 · 실 데이터 일치',            '낮',  '5cycle 비교'],
    ['6',     '응답 형식 압축 (§15)',           '500자 절감 · 핵심 보존',                 '낮',  '응답 스키마 검증'],
]

RISK_ANALYSIS = [
    ['항목',           '위험도', '잠재 영향',                                    '완화책'],
    ['§3 결합 룰 통합', '낮',    '단일 룰로 LLM 명확',                           'Phase 1 우선 + 즉시 롤백'],
    ['§4 외부순환 통합', '낮',   '판단 일관성 ↑',                                'Phase 2'],
    ['placeholder 치환', '낮',  '수치 명시로 LLM 추론 부담 ↓',                  'Phase 3'],
    ['§2 우선순위 통합', '중',   '복합 상황 6예시 제거 → 직관 매칭 손실 가능',     'Phase 4 — 14일 모니터링'],
    ['§7 컨텍스트 정리', '낮',  '미사용 항목 제거',                              'Phase 5'],
    ['§9 응답 형식 압축', '낮', '예시 줄여도 스키마는 유지',                     'Phase 6'],
]

VALIDATION_PROTOCOL = (
    "<b>각 Phase 적용 후 다음 검증 절차:</b><br/>"
    "1. <b>코드 + DB 변경</b> — prompt_block_m UPDATE + ai_control.py inline 동기화<br/>"
    "2. <b>scheduler 재시작</b> — 새 프롬프트 로드<br/>"
    "3. <b>5 cycle 운영</b> (1호+3호 각 5회 × 약 200초 = 약 30분)<br/>"
    "4. <b>LLM 결정 분포 비교</b>:<br/>"
    "   • action change/keep 비율 (변경 전후)<br/>"
    "   • circulation 분포 (5종)<br/>"
    "   • devices ON/OFF 패턴<br/>"
    "   • 응답 시간 평균 · 90백분위<br/>"
    "5. <b>이상 시 롤백</b> — 직전 prompt_block_m 백업으로 즉시 복원<br/>"
    "6. <b>정상 시 다음 Phase</b> 진행<br/><br/>"
    "<b>Phase 4 (우선순위 통합) 만 14일 운영 모니터링</b> — 가장 큰 변경이므로 충분한 표본 확보."
)


# ────────────────────────────────────────────────────────────────────
# 빌드
# ────────────────────────────────────────────────────────────────────
def build():
    doc = SimpleDocTemplate(
        OUT_PATH,
        pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm,  bottomMargin=18 * mm,
        title='AgriAI Core LLM 프롬프트·입력 데이터 개선 검토 제안서',
        author='AgriAI Core',
    )

    story = []
    now = _dt.datetime.now().strftime('%Y-%m-%d %H:%M')

    # 표지
    story.append(Paragraph('AgriAI Core LLM 환경제어', TITLE))
    story.append(Paragraph('프롬프트·입력 데이터 개선 검토 제안서', TITLE))
    story.append(Paragraph(
        f'분석 대상: docs/info_for_relay_control.pdf · 생성 {now} · A4 세로',
        SUBTITLE,
    ))

    # 요약
    story.append(Paragraph('§ 0. Executive Summary', H1))
    story.append(Paragraph(EXEC_SUMMARY, BODY))

    # 1. 현재 구조 종합 평가
    story.append(Paragraph('§ 1. 현재 시스템 프롬프트 구조 종합 평가', H1))
    story.append(Paragraph(
        '15개 섹션을 모두 분석. ⚠ = 개선 필요, ✓ = 유지, ✗ = 제거 권장.',
        BODY))
    story.append(Spacer(1, 4))
    story.append(make_table(CURRENT_STRUCTURE,
                            col_widths=[12*mm, 50*mm, 22*mm, 80*mm], font_size=8.0))

    # 2. 발견된 문제
    story.append(Paragraph('§ 2. 발견된 문제 8건 (분류별)', H1))
    story.append(Paragraph(
        '심각도 = LLM 결정 품질에 미치는 영향. <b>높음</b> = 모순 가능성, '
        '<b>중</b> = 토큰 낭비/혼란, <b>낮음</b> = 가독성 저하만.',
        BODY))
    story.append(Spacer(1, 4))
    story.append(make_table(ISSUES,
                            col_widths=[8*mm, 16*mm, 38*mm, 80*mm, 22*mm],
                            font_size=7.8))

    # 3. 개선안 비교
    story.append(PageBreak())
    story.append(Paragraph('§ 3. 영역별 개선안 (Before/After 비교)', H1))

    story.append(Paragraph('3-1. 포그·수온히터 룰 통합', H2))
    story.append(make_table(REPLACE_HEAT,
                            col_widths=[16*mm, 80*mm, 80*mm], font_size=8.5,
                            first_col_bold=True))

    story.append(Paragraph('3-2. 우선순위·비상·수온히터 정책 통합', H2))
    story.append(make_table(REPLACE_PRIORITY,
                            col_widths=[16*mm, 80*mm, 80*mm], font_size=8.5,
                            first_col_bold=True))

    story.append(Paragraph('3-3. 외부순환 룰 단일화', H2))
    story.append(make_table(REPLACE_OUTSIDE,
                            col_widths=[16*mm, 80*mm, 80*mm], font_size=8.5,
                            first_col_bold=True))

    story.append(Paragraph('3-4. placeholder 동적 치환', H2))
    story.append(make_table(REPLACE_PLACEHOLDER,
                            col_widths=[16*mm, 80*mm, 80*mm], font_size=8.5,
                            first_col_bold=True))

    # 4. 새 구조
    story.append(PageBreak())
    story.append(Paragraph('§ 4. 새 시스템 프롬프트 9개 섹션 구조 (제안)', H1))
    story.append(Paragraph(
        '15섹션 → 9섹션. 길이 약 9,300자 → <b>약 4,000자</b> (57% 단축).<br/>'
        'LLM 응답 시간 단축 효과 + 명료성 향상 기대.',
        BODY))
    story.append(Spacer(1, 4))
    story.append(make_table(NEW_STRUCTURE,
                            col_widths=[10*mm, 70*mm, 22*mm, 70*mm], font_size=8.5))

    # 5. 단계적 적용 로드맵
    story.append(Paragraph('§ 5. 단계적 적용 로드맵 (Phase 1~6)', H1))
    story.append(Paragraph(
        '<b>위험도 낮음 항목부터 우선 적용</b>. 각 단계 검증 후 다음 단계로. '
        '사용자 핵심 원칙 — "현재 기능을 위협하지 않을 것" 준수.',
        BODY))
    story.append(Spacer(1, 4))
    story.append(make_table(PHASES,
                            col_widths=[14*mm, 50*mm, 50*mm, 16*mm, 38*mm],
                            font_size=8.0))

    # 6. 위험 분석
    story.append(Paragraph('§ 6. 위험 분석 + 완화 전략', H1))
    story.append(make_table(RISK_ANALYSIS,
                            col_widths=[36*mm, 18*mm, 60*mm, 54*mm], font_size=8.3))

    # 7. 검증 프로토콜
    story.append(Paragraph('§ 7. 검증 프로토콜', H1))
    story.append(Paragraph(VALIDATION_PROTOCOL, BODY))

    # 8. 결론 + 사용자 결정 요청
    story.append(PageBreak())
    story.append(Paragraph('§ 8. 결론 및 사용자 결정 요청', H1))
    story.append(Paragraph(
        '<b>현재 시스템 프롬프트는 기능적으로 정상 작동 중</b>이지만 다음 비효율이 '
        '존재합니다:<br/>'
        '• 9,300자 (약 5,000~9,000 토큰) → LLM 응답 시간 75-150초의 한 원인<br/>'
        '• 8건 중복/혼란 → LLM 추론 부담<br/>'
        '• 4곳 placeholder 미치환 → LLM 추론 의존<br/><br/>'
        '<b>제안 적용 시 예상 효과</b>:<br/>'
        '• 프롬프트 길이 57% 감소 (4,000자) → 응답 시간 20-40% 단축 가능<br/>'
        '• 룰 모순 제거 → LLM 결정 일관성 향상<br/>'
        '• 명시적 수치 → LLM 추론 정확도 향상<br/><br/>'
        '<b>위험</b>:<br/>'
        '• Phase 4 (우선순위 통합) 만 중간 위험 — 복합 상황 6예시 제거로 직관 매칭 손실 가능<br/>'
        '• 다른 모든 Phase 는 낮음 — 실질 LLM 결정에 영향 없음 또는 긍정적<br/><br/>'
        '<b>진행 옵션</b>:<br/>'
        '<b>(A) 단계적 적용</b> — Phase 1~6 순차, 각 단계 검증 후 다음. 안전·시간 소요.<br/>'
        '<b>(B) Phase 1~3+5+6 일괄 적용 후 Phase 4 만 별도</b> — 안전 항목 묶음 처리. 권장.<br/>'
        '<b>(C) 전체 일괄 + 14일 모니터링</b> — 빠른 적용, 위험 통합 검증.<br/>'
        '<b>(D) 현재 상태 유지</b> — 정상 작동 중이므로 변경 없음.<br/><br/>'
        '<b>사용자 결정 요청</b>: 위 옵션 중 선택 또는 부분 채택을 지시해 주십시오. '
        'Phase별 코드 + DB 변경 사양은 결정 후 별도 작성 후 적용합니다.',
        BODY))

    story.append(Spacer(1, 14))
    story.append(Paragraph(
        f'<para alignment="center"><font color="#888888">— 끝 — '
        f'AgriAI Core 검토 제안서 · 자동 생성 {now}</font></para>',
        BODY))

    doc.build(story)
    print(f'[gen_info_for_relay_control_review_pdf] 생성 완료: {OUT_PATH}')


if __name__ == '__main__':
    build()
