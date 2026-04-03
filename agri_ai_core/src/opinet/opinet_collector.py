"""Opinet 유가정보 수집기: 무료 API 데이터 수집 → PostgreSQL 저장."""
import os
import sys
import time
import logging
import requests
from datetime import datetime
from typing import List, Dict, Optional

# 프로젝트 루트 추가
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agri_ai_core.src.postgresql.reader import db_session

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════
# 설정
# ════════════════════════════════════════════════════════════
_API_BASE = "http://www.opinet.co.kr/api"
_API_KEY = os.getenv("OPNET_API", "")
if not _API_KEY:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
    _API_KEY = os.getenv("OPNET_API", "")

# 유종 코드
PROD_CODES = {
    "B034": "고급휘발유",
    "B027": "휘발유",
    "D047": "경유",
    "C004": "등유",
    "K015": "LPG",
}

# ════════════════════════════════════════════════════════════
# 테이블 생성 DDL
# ════════════════════════════════════════════════════════════
_DDL_AREA_CODE = """
CREATE TABLE IF NOT EXISTS opinet_area_code (
    area_cd   VARCHAR(10) NOT NULL,
    area_nm   VARCHAR(50) NOT NULL,
    parent_cd VARCHAR(10),
    PRIMARY KEY (area_cd)
);
"""

_DDL_AVG_PRICE = """
CREATE TABLE IF NOT EXISTS opinet_avg_price (
    trade_dt  DATE        NOT NULL,
    area_cd   VARCHAR(10) NOT NULL DEFAULT '00',
    prod_cd   VARCHAR(10) NOT NULL,
    prod_nm   VARCHAR(30),
    price     NUMERIC(10,2),
    diff      NUMERIC(10,2),
    PRIMARY KEY (trade_dt, area_cd, prod_cd)
);
CREATE INDEX IF NOT EXISTS idx_opinet_avg_dt ON opinet_avg_price (trade_dt);
"""

_DDL_LOW_PRICE = """
CREATE TABLE IF NOT EXISTS opinet_low_price (
    trade_dt    DATE         NOT NULL,
    area_cd     VARCHAR(10)  NOT NULL DEFAULT '00',
    prod_cd     VARCHAR(10)  NOT NULL,
    uni_id      VARCHAR(20)  NOT NULL,
    os_nm       VARCHAR(100),
    poll_div_cd VARCHAR(10),
    price       NUMERIC(10,2),
    van_adr     VARCHAR(200),
    new_adr     VARCHAR(200),
    gis_x       NUMERIC(12,1),
    gis_y       NUMERIC(12,1),
    PRIMARY KEY (trade_dt, area_cd, prod_cd, uni_id)
);
CREATE INDEX IF NOT EXISTS idx_opinet_low_dt ON opinet_low_price (trade_dt);
"""


def _init_tables():
    """테이블 생성 (존재하면 무시)"""
    with db_session() as db:
        for ddl in [_DDL_AREA_CODE, _DDL_AVG_PRICE, _DDL_LOW_PRICE]:
            for stmt in ddl.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    db.execute_query(stmt)
        pass  # execute_query auto-commits
    logger.info("[Opinet] 테이블 초기화 완료")


# ════════════════════════════════════════════════════════════
# API 호출
# ════════════════════════════════════════════════════════════
def _api_call(endpoint: str, params: dict = None) -> Optional[List[Dict]]:
    """Opinet API 호출, 결과 OIL 리스트 반환"""
    url = f"{_API_BASE}/{endpoint}.do"
    p = {"out": "json", "code": _API_KEY}
    if params:
        p.update(params)
    try:
        r = requests.get(url, params=p, timeout=15)
        if r.status_code != 200:
            return None
        # Opinet API는 JSON 반환 시에도 Content-Type: text/html을 사용
        # 실제 에러 페이지는 <html 태그로 시작
        text = r.text.strip()
        if text.startswith("<") or "The service is not available" in text:
            return None
        data = r.json()
        return data.get("RESULT", {}).get("OIL", [])
    except Exception as e:
        logger.warning(f"[Opinet] API 호출 실패 {endpoint}: {e}")
        return None


# ════════════════════════════════════════════════════════════
# 데이터 수집 함수
# ════════════════════════════════════════════════════════════
def collect_area_codes():
    """시도/시군구 코드 수집 저장"""
    # 시도
    sido_list = _api_call("areaCode")
    if not sido_list:
        logger.warning("[Opinet] 시도 코드 조회 실패")
        return 0
    count = 0
    with db_session() as db:
        for s in sido_list:
            db.execute_query(
                "INSERT INTO opinet_area_code (area_cd, area_nm, parent_cd) "
                "VALUES (%s, %s, NULL) ON CONFLICT (area_cd) DO UPDATE SET area_nm=EXCLUDED.area_nm",
                (s["AREA_CD"], s["AREA_NM"])
            )
            count += 1
            # 시군구
            time.sleep(0.3)
            sigun_list = _api_call("areaCode", {"area": s["AREA_CD"]})
            if sigun_list:
                for sg in sigun_list:
                    db.execute_query(
                        "INSERT INTO opinet_area_code (area_cd, area_nm, parent_cd) "
                        "VALUES (%s, %s, %s) ON CONFLICT (area_cd) DO UPDATE SET area_nm=EXCLUDED.area_nm, parent_cd=EXCLUDED.parent_cd",
                        (sg["AREA_CD"], sg["AREA_NM"], s["AREA_CD"])
                    )
                    count += 1
        pass  # execute_query auto-commits
    logger.info(f"[Opinet] 지역코드 {count}건 저장")
    return count


def collect_avg_national(trade_dt: str = None):
    """전국 평균가격 수집 (전유종)"""
    oils = _api_call("avgAllPrice")
    if not oils:
        return 0
    dt = trade_dt or oils[0].get("TRADE_DT", datetime.now().strftime("%Y%m%d"))
    dt_date = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
    count = 0
    with db_session() as db:
        for o in oils:
            db.execute_query(
                "INSERT INTO opinet_avg_price (trade_dt, area_cd, prod_cd, prod_nm, price, diff) "
                "VALUES (%s, '00', %s, %s, %s, %s) "
                "ON CONFLICT (trade_dt, area_cd, prod_cd) DO UPDATE SET price=EXCLUDED.price, diff=EXCLUDED.diff, prod_nm=EXCLUDED.prod_nm",
                (dt_date, o["PRODCD"], o["PRODNM"], o["PRICE"], o.get("DIFF", "0").replace("+", ""))
            )
            count += 1
        pass  # execute_query auto-commits
    logger.info(f"[Opinet] 전국 평균 {count}건 저장 ({dt_date})")
    return count


def collect_avg_sido(trade_dt: str = None):
    """시도별 평균가격 수집 (전유종)"""
    count = 0
    for prod_cd in PROD_CODES:
        oils = _api_call("avgSidoPrice", {"prodcd": prod_cd})
        if not oils:
            continue
        dt = trade_dt or datetime.now().strftime("%Y%m%d")
        dt_date = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
        with db_session() as db:
            for o in oils:
                area_cd = o.get("SIDOCD", "")
                if not area_cd or o.get("SIDONM") == "전국":
                    continue
                db.execute_query(
                    "INSERT INTO opinet_avg_price (trade_dt, area_cd, prod_cd, prod_nm, price, diff) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (trade_dt, area_cd, prod_cd) DO UPDATE SET price=EXCLUDED.price, diff=EXCLUDED.diff",
                    (dt_date, area_cd, prod_cd, PROD_CODES[prod_cd], o["PRICE"],
                     str(o.get("DIFF", "0")).replace("+", ""))
                )
                count += 1
            pass  # execute_query auto-commits
        time.sleep(0.3)
    logger.info(f"[Opinet] 시도별 평균 {count}건 저장")
    return count


def collect_avg_sigun(sido_cd: str = None, trade_dt: str = None):
    """시군구별 평균가격 수집"""
    # sido 목록 조회
    if sido_cd:
        sido_list = [{"AREA_CD": sido_cd}]
    else:
        sido_list = _api_call("areaCode") or []

    count = 0
    dt = trade_dt or datetime.now().strftime("%Y%m%d")
    dt_date = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"

    for sido in sido_list:
        sid = sido["AREA_CD"]
        for prod_cd in PROD_CODES:
            oils = _api_call("avgSigunPrice", {"prodcd": prod_cd, "sido": sid})
            if not oils:
                continue
            with db_session() as db:
                for o in oils:
                    db.execute_query(
                        "INSERT INTO opinet_avg_price (trade_dt, area_cd, prod_cd, prod_nm, price, diff) "
                        "VALUES (%s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (trade_dt, area_cd, prod_cd) DO UPDATE SET price=EXCLUDED.price, diff=EXCLUDED.diff",
                        (dt_date, o["SIGUNCD"], prod_cd, PROD_CODES[prod_cd], o["PRICE"],
                         str(o.get("DIFF", "0")).replace("+", ""))
                    )
                    count += 1
                pass  # execute_query auto-commits
            time.sleep(0.3)
    logger.info(f"[Opinet] 시군구별 평균 {count}건 저장")
    return count


def collect_recent_7days():
    """최근 7일 전국 일일 평균가격 수집 (초기 적재용)"""
    count = 0
    for prod_cd in PROD_CODES:
        oils = _api_call("avgRecentPrice", {"prodcd": prod_cd})
        if not oils:
            continue
        with db_session() as db:
            for o in oils:
                dt = o["DATE"]
                dt_date = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
                db.execute_query(
                    "INSERT INTO opinet_avg_price (trade_dt, area_cd, prod_cd, prod_nm, price, diff) "
                    "VALUES (%s, '00', %s, %s, %s, %s) "
                    "ON CONFLICT (trade_dt, area_cd, prod_cd) DO UPDATE SET price=EXCLUDED.price, diff=EXCLUDED.diff",
                    (dt_date, prod_cd, PROD_CODES[prod_cd], o["PRICE"],
                     str(o.get("DIFF", "0")).replace("+", ""))
                )
                count += 1
            pass  # execute_query auto-commits
        time.sleep(0.3)
    logger.info(f"[Opinet] 최근7일 전국 평균 {count}건 저장")
    return count


def collect_low_price(area_cd: str = None, trade_dt: str = None):
    """최저가 주유소 Top20 수집"""
    dt = trade_dt or datetime.now().strftime("%Y%m%d")
    dt_date = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"

    # 지역 목록
    if area_cd:
        areas = [area_cd]
    else:
        sido_list = _api_call("areaCode") or []
        areas = [""] + [s["AREA_CD"] for s in sido_list]  # 전국 + 시도별

    count = 0
    for area in areas:
        for prod_cd in ["B027", "D047"]:  # 휘발유, 경유만
            oils = _api_call("lowTop10", {"prodcd": prod_cd, "area": area, "cnt": "20"})
            if not oils:
                continue
            a_cd = area or "00"
            with db_session() as db:
                for o in oils:
                    db.execute_query(
                        "INSERT INTO opinet_low_price (trade_dt, area_cd, prod_cd, uni_id, os_nm, poll_div_cd, price, van_adr, new_adr, gis_x, gis_y) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (trade_dt, area_cd, prod_cd, uni_id) DO UPDATE SET price=EXCLUDED.price, os_nm=EXCLUDED.os_nm, new_adr=EXCLUDED.new_adr",
                        (dt_date, a_cd, prod_cd, o["UNI_ID"], o["OS_NM"], o.get("POLL_DIV_CD", ""),
                         o["PRICE"], o.get("VAN_ADR", ""), o.get("NEW_ADR", ""),
                         o.get("GIS_X_COOR"), o.get("GIS_Y_COOR"))
                    )
                    count += 1
                pass  # execute_query auto-commits
            time.sleep(0.3)
    logger.info(f"[Opinet] 최저가 {count}건 저장 ({dt_date})")
    return count


# ════════════════════════════════════════════════════════════
# 전체 수집 (스케줄러/CLI)
# ════════════════════════════════════════════════════════════
def collect_all(target_date: str = None):
    """전체 무료 API 데이터 수집
    Args:
        target_date: YYYYMMDD 형식. None이면 오늘
    """
    start = time.time()
    dt = target_date or datetime.now().strftime("%Y%m%d")
    logger.info(f"[Opinet] ===== 전체 수집 시작 ({dt}) =====")

    _init_tables()

    total = 0
    total += collect_area_codes()
    total += collect_avg_national(dt)
    total += collect_avg_sido(dt)
    total += collect_avg_sigun(trade_dt=dt)
    total += collect_low_price(trade_dt=dt)

    elapsed = time.time() - start
    logger.info(f"[Opinet] ===== 전체 수집 완료: {total}건 ({elapsed:.1f}s) =====")
    return total


def collect_initial(days: int = 7):
    """초기 적재: 최근 N일 데이터 (최근7일 API + 당일 상세)
    Args:
        days: 수집 일수 (기본 7일, 최근7일 API가 7일까지만 지원)
    """
    start = time.time()
    logger.info(f"[Opinet] ===== 초기 적재 시작 (최근 {days}일) =====")

    _init_tables()

    total = 0
    total += collect_area_codes()
    total += collect_recent_7days()  # 최근7일 전국 평균

    # 당일 상세 데이터
    today = datetime.now().strftime("%Y%m%d")
    total += collect_avg_sido(today)
    total += collect_avg_sigun(trade_dt=today)
    total += collect_low_price(trade_dt=today)

    elapsed = time.time() - start
    logger.info(f"[Opinet] ===== 초기 적재 완료: {total}건 ({elapsed:.1f}s) =====")
    return total


# ════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "init":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
            collect_initial(days)
        elif cmd == "daily":
            dt = sys.argv[2] if len(sys.argv) > 2 else None
            collect_all(dt)
        elif cmd == "date":
            # 특정 날짜 수집: python opinet_collector.py date 20260301
            dt = sys.argv[2]
            collect_all(dt)
        else:
            print("사용법:")
            print("  python opinet_collector.py init [days]     # 초기 적재 (기본 7일)")
            print("  python opinet_collector.py daily [YYYYMMDD] # 일일 수집 (기본 오늘)")
            print("  python opinet_collector.py date YYYYMMDD    # 특정 날짜 수집")
    else:
        collect_all()
