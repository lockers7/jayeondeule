#!/usr/bin/env python3
"""docs/system_prompt.pdf 생성 — A4 세로 출력용.

LLM 환경제어 시스템 프롬프트 전체를 NanumGothic 한국어 폰트로
PDF 변환. _build_system_prompt 의 실시간 결과(USE_DB_BLOCKS=1
이면 DB blocks, 아니면 inline)를 그대로 캡처.

사용법:
    /workspace/jayeondeule/venv/bin/python docs/dev/gen_system_prompt_pdf.py
"""
import os
import sys

sys.path.insert(0, '/workspace/jayeondeule')

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Preformatted,
)

KR_REG = 'NanumGothic'
KR_BOLD = 'NanumGothic-Bold'
pdfmetrics.registerFont(TTFont(KR_REG, '/usr/share/fonts/truetype/nanum/NanumGothic.ttf'))
pdfmetrics.registerFont(TTFont(KR_BOLD, '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf'))

OUT_PATH = '/workspace/jayeondeule/docs/system_prompt.pdf'


def get_system_prompt() -> str:
    from agri_ai_core.src.control.ai_control import _build_system_prompt
    from agri_ai_core.src.control.ai_thresholds import get_thresholds
    ts = get_thresholds(1, 1)
    return _build_system_prompt('생육기', ts)


def build_pdf(prompt_text: str):
    doc = SimpleDocTemplate(
        OUT_PATH,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title='AgriAI Core LLM 환경제어 시스템 프롬프트',
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
    h1_style = ParagraphStyle(
        'H1', fontName=KR_BOLD, fontSize=12, leading=16,
        textColor=colors.HexColor('#1F4E79'),
        spaceBefore=10, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        'Body', fontName=KR_REG, fontSize=8.7, leading=12.5,
    )

    story = []
    story.append(Paragraph('AgriAI Core LLM 환경제어 시스템 프롬프트', title_style))
    import datetime as _dt
    story.append(Paragraph(
        f'(생육기 기준 · 추출 시각 {_dt.datetime.now().strftime("%Y-%m-%d %H:%M")} · '
        f'총 {len(prompt_text):,}자)',
        sub_style,
    ))

    section_buffer = []
    current_heading = None

    def flush_section():
        nonlocal section_buffer, current_heading
        if not section_buffer:
            return
        text_block = '\n'.join(section_buffer).rstrip()
        if not text_block:
            section_buffer = []
            return
        if current_heading:
            story.append(Paragraph(_xml_escape(current_heading), h1_style))
        # Preformatted 로 출력 — 들여쓰기·줄바꿈 보존, A4 가로 폭 안에 맞춰 자동 줄바꿈은 하지 않음.
        # 다만 prompt 자체가 80자 이내로 작성되어 있어 페이지 폭 안에 들어감.
        story.append(Preformatted(text_block, body_style, maxLineLength=110))
        section_buffer = []

    for raw in prompt_text.splitlines():
        if raw.startswith('## '):
            flush_section()
            current_heading = raw[3:].strip()
            section_buffer = []
        else:
            section_buffer.append(raw)

    flush_section()

    doc.build(story)
    print(f'[gen_system_prompt_pdf] 생성 완료: {OUT_PATH}')


def _xml_escape(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


if __name__ == '__main__':
    text = get_system_prompt()
    build_pdf(text)
