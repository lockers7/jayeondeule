"""
LangChain Tool 정의 (ReAct 에이전트용)
- 웹 검색 (SearXNG)
- 비료량 계산
- 재배 일정 조회
"""
import httpx
from langchain_core.tools import tool

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SEARXNG_URL


@tool
def search_web(query: str) -> str:
    """웹에서 최신 농업 정보, 날씨, 시세, 뉴스 등을 검색합니다.
    Args:
        query: 검색할 키워드 (한국어 권장)
    Returns:
        검색 결과 상위 5개 요약
    """
    try:
        params = {
            "q": query,
            "format": "json",
            "language": "ko",
            "categories": "general",
        }
        resp = httpx.get(
            f"{SEARXNG_URL}/search",
            params=params,
            timeout=10.0,
        )
        if resp.status_code != 200:
            return f"웹 검색 실패 (HTTP {resp.status_code})"

        data = resp.json()
        results = data.get("results", [])[:5]
        if not results:
            return "검색 결과가 없습니다."

        output = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "제목 없음")
            content = r.get("content", "내용 없음")
            url = r.get("url", "")
            output.append(f"{i}. **{title}**\n   {content}\n   출처: {url}")
        return "\n\n".join(output)

    except Exception as e:
        return f"웹 검색 중 오류 발생: {str(e)}"


@tool
def calculate_fertilizer(crop: str, area_pyeong: float) -> str:
    """작물별 표준 시비량(비료량)을 계산합니다.
    Args:
        crop: 작물명 (토마토, 딸기, 파프리카, 상추)
        area_pyeong: 재배 면적 (평 단위)
    Returns:
        권장 시비량 (kg 단위)
    """
    # 표준 시비량 (10a = 300평 기준, kg)
    fertilizer_standards = {
        "토마토": {"질소(N)": 20, "인산(P)": 15, "칼륨(K)": 22, "석회": 200, "퇴비": 2000},
        "딸기": {"질소(N)": 12, "인산(P)": 10, "칼륨(K)": 12, "석회": 150, "퇴비": 3000},
        "파프리카": {"질소(N)": 18, "인산(P)": 14, "칼륨(K)": 20, "석회": 180, "퇴비": 2500},
        "상추": {"질소(N)": 15, "인산(P)": 10, "칼륨(K)": 13, "석회": 150, "퇴비": 2000},
    }

    crop = crop.strip()
    if crop not in fertilizer_standards:
        available = ", ".join(fertilizer_standards.keys())
        return f"'{crop}'의 시비 기준이 없습니다. 지원 작물: {available}"

    standard = fertilizer_standards[crop]
    ratio = area_pyeong / 300  # 10a(300평) 기준 비율

    lines = [f"## {crop} 시비량 계산 ({area_pyeong}평 기준)\n"]
    lines.append(f"| 비료 종류 | 표준량(10a) | 계산량({area_pyeong}평) |")
    lines.append("|-----------|------------|-------------------|")
    for name, amount in standard.items():
        calc = round(amount * ratio, 1)
        unit = "kg"
        lines.append(f"| {name} | {amount}{unit} | **{calc}{unit}** |")

    lines.append(f"\n※ 토양 검정 결과에 따라 ±20% 조정 권장")
    lines.append(f"※ 기비(밑거름)와 추비(웃거름)를 6:4 비율로 분시 권장")
    return "\n".join(lines)


@tool
def get_crop_calendar(crop: str) -> str:
    """작물별 월별 재배 일정(파종~수확)을 조회합니다.
    Args:
        crop: 작물명 (토마토, 딸기, 파프리카, 상추)
    Returns:
        월별 주요 작업 일정
    """
    calendars = {
        "토마토": {
            "1월": "육묘 관리, 보온 관리",
            "2월": "파종(봄작), 육묘 관리",
            "3월": "정식 준비, 하우스 소독",
            "4월": "정식, 유인 작업 시작",
            "5월": "적심·적엽, 1차 수확 시작",
            "6월": "수확 최성기, 병해충 방제",
            "7월": "고온기 관리, 파종(가을작)",
            "8월": "가을작 정식, 차광 관리",
            "9월": "가을작 생육 관리",
            "10월": "가을작 수확 시작",
            "11월": "수확, 보온 관리 강화",
            "12월": "수확 마무리, 다음 작기 준비",
        },
        "딸기": {
            "1월": "수확 최성기, 보온 관리",
            "2월": "수확, 추비 시작",
            "3월": "수확, 병해충 방제",
            "4월": "수확, 러너(런너) 발생",
            "5월": "수확 마무리, 모주 관리",
            "6월": "런너 채취, 자묘 육성",
            "7월": "자묘 관리, 화아분화 유도",
            "8월": "자묘 관리, 야냉처리",
            "9월": "정식, 활착 관리",
            "10월": "생육 관리, 보온 시작",
            "11월": "개화·착과, 보온 관리",
            "12월": "수확 시작, 온도 관리",
        },
        "파프리카": {
            "1월": "수확, 보온 관리",
            "2월": "수확, 영양 관리",
            "3월": "수확, 병해충 방제",
            "4월": "수확, 적엽 작업",
            "5월": "수확, 환기 관리",
            "6월": "고온기 관리, 차광",
            "7월": "파종(가을작), 육묘",
            "8월": "정식, 활착 관리",
            "9월": "생육 관리, 유인",
            "10월": "착과 관리, 보온 시작",
            "11월": "수확 시작",
            "12월": "수확, 보온 관리",
        },
        "상추": {
            "연중": "파종 후 30~40일 수확, 연중 재배 가능",
            "봄(3~5월)": "노지·시설 파종 적기, 생육 양호",
            "여름(6~8월)": "고온 주의, 차광재배 필요, 추대 위험",
            "가을(9~11월)": "최적 생육기, 품질 우수",
            "겨울(12~2월)": "시설재배, 보온 필수, 생육 지연",
        },
    }

    crop = crop.strip()
    if crop not in calendars:
        available = ", ".join(calendars.keys())
        return f"'{crop}'의 재배 일정이 없습니다. 지원 작물: {available}"

    cal = calendars[crop]
    lines = [f"## {crop} 재배 일정\n"]
    for month, task in cal.items():
        lines.append(f"- **{month}**: {task}")

    return "\n".join(lines)


# 도구 목록 (에이전트에서 사용)
ALL_TOOLS = [search_web, calculate_fertilizer, get_crop_calendar]
