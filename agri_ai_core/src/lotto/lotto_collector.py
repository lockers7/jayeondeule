# ═══════════════════════════════════════════════════════════════════════════
# 로또 당첨번호 수집기 — 동행복권 API에서 최신 당첨번호를 수집하여 DB에 저장.
# --->
# _create_session: 동행복권 세션 생성 (쿠키 획득)
# fetch_results: 특정 회차부터 10건씩 당첨번호를 조회한다
# update_lotto_db: DB에 없는 최신 로또 결과를 수집하여 저장한다
# ═══════════════════════════════════════════════════════════════════════════
import time
import requests

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

API_URL = "https://www.dhlottery.co.kr/lt645/selectPstLt645InfoNew.do"
RESULT_PAGE = "https://www.dhlottery.co.kr/lt645/result"


def _create_session():
    """동행복권 세션 생성 (쿠키 획득)."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': RESULT_PAGE,
    })
    logger.debug("[로또수집] 동행복권 세션 생성 중...")
    session.get(RESULT_PAGE, timeout=15)
    logger.debug("[로또수집] 세션 생성 완료 (쿠키 획득)")
    return session


def fetch_results(session, start_epsd):
    """특정 회차부터 10건씩 당첨번호를 조회한다."""
    try:
        logger.debug(f"[로또수집] API 요청: epsd={start_epsd}")
        resp = session.get(f"{API_URL}?srchLtEpsd={start_epsd}", timeout=15)
        data = resp.json()
        return data.get('data', {}).get('list', [])
    except Exception as e:
        logger.warning(f"[로또수집] API 호출 실패 (epsd={start_epsd}): {e}")
        return []


def update_lotto_db():
    """DB에 없는 최신 로또 결과를 수집하여 저장한다."""
    from agri_ai_core.src.postgresql.connection import db_session

    # 마지막 회차 확인
    logger.debug("[로또수집] DB에서 마지막 회차 조회 중...")
    with db_session() as db:
        rows = db.execute_query("SELECT MAX(draw_no) FROM lotto_results")
        last_draw = rows[0][0] if rows and rows[0][0] else 0

    logger.info(f"[로또수집] DB 마지막 회차: {last_draw}, 최신 데이터 수집 시작...")

    session = _create_session()
    added = 0
    epsd = last_draw + 1

    while True:
        items = fetch_results(session, epsd)
        if not items:
            break

        new_items = [it for it in items if it['ltEpsd'] > last_draw]
        if not new_items:
            break

        with db_session() as db:
            for item in new_items:
                draw_no = item['ltEpsd']
                ymd = str(item['ltRflYmd'])
                draw_date = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
                nums = [item[f'tm{i}WnNo'] for i in range(1, 7)]
                bonus = item['bnsWnNo']

                try:
                    db.execute_query(
                        "INSERT INTO lotto_results (draw_no, draw_date, num1, num2, num3, num4, num5, num6, bonus) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (draw_no) DO NOTHING",
                        (draw_no, draw_date, *nums, bonus)
                    )
                    added += 1
                    logger.info(f"[로또수집] {draw_no}회 ({draw_date}): {nums} + 보너스 {bonus}")
                except Exception as e:
                    logger.error(f"[로또수집] {draw_no}회 저장 실패: {e}")

        max_epsd = max(it['ltEpsd'] for it in items)
        epsd = max_epsd + 1
        time.sleep(0.5)

    logger.info(f"[로또수집] 완료: {added}건 추가")
    return added
