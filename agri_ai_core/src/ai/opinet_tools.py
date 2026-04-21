# ═════════════════════════════════════════════════════════════
# Opinet 유가정보 도구 — 전국/시도/시군구 평균 유가, 최저가 조회
# tools_executor.py에서 분리된 독립 모듈.
# 실시간 API 우선 호출, 실패 시 PostgreSQL DB 폴백.
# --->
# _opinet_api_call: Opinet 실시간 API 호출 (실패 시 None)
# _opinet_db_fallback: DB 폴백 (최근 저장 데이터 조회)
# search_gas_price: 메인 진입점 — 실시간 API → DB 폴백
# ═════════════════════════════════════════════════════════════
import os
from typing import Any, Dict, List, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# ═════════════════════════════════════════════════
# Opinet 유가정보 API 조회
# 전국/시도/시군구 평균 유가, 최저가 주유소 등 조회
# ═════════════════════════════════════════════════
_OPINET_API_KEY = os.getenv("OPNET_API", "")
_OPINET_BASE = "http://www.opinet.co.kr/api"

# 시도 코드 매핑 (Opinet 코드)
_SIDO_MAP = {
    "서울": "01", "경기": "02", "강원": "03", "충북": "04", "충남": "05",
    "전북": "06", "전남": "07", "경북": "08", "경남": "09", "부산": "10",
    "제주": "11", "대구": "14", "인천": "15", "광주": "16", "대전": "17",
    "울산": "18", "세종": "19",
}

# 유종 코드 매핑
_PROD_MAP = {
    "휘발유": "B027", "경유": "D047", "고급휘발유": "B034",
    "등유": "C004", "LPG": "K015", "부탄": "K015",
}

# ────────────────────────────────────────────────────────────────────
# Opinet 실시간 API 호출 (실패 시 None)
# ────────────────────────────────────────────────────────────────────
def _opinet_api_call(endpoint: str, params: dict = None) -> Optional[List[Dict]]:
    import requests as _req
    url = f"{_OPINET_BASE}/{endpoint}.do"
    p = {"out": "json", "code": _OPINET_API_KEY}
    if params:
        p.update(params)
    try:
        r = _req.get(url, params=p, timeout=10)
        if r.status_code != 200:
            return None
        text = r.text.strip()
        if text.startswith("<") or "not available" in text:
            return None
        return r.json().get("RESULT", {}).get("OIL", [])
    except Exception:
        return None


# ────────────────────────────────────────────────────────────────────
# DB 폴백: 가장 최근 저장된 데이터 조회
# ────────────────────────────────────────────────────────────────────
def _opinet_db_fallback(query_type: str, prodcd: str, sido_cd: str = None,
                        sigun: str = None) -> Optional[Dict]:
    try:
        from agri_ai_core.src.postgresql.reader import db_session
        with db_session() as db:
            if query_type == "low_price":
                area = sido_cd or "00"
                rows = db.fetch_all(
                    "SELECT os_nm, price, new_adr, poll_div_cd, trade_dt "
                    "FROM opinet_low_price WHERE area_cd=%s AND prod_cd=%s "
                    "AND trade_dt=(SELECT MAX(trade_dt) FROM opinet_low_price WHERE area_cd=%s AND prod_cd=%s) "
                    "ORDER BY price LIMIT 20",
                    (area, prodcd, area, prodcd), as_dict=True
                )
                if rows:
                    return {
                        "success": True, "source": "DB(폴백)", "기준일": str(rows[0]["trade_dt"]),
                        "query_type": "최저가 주유소", "count": len(rows),
                        "stations": [{"주유소명": r["os_nm"], "가격": f"{r['price']}원",
                                      "주소": r["new_adr"] or ""} for r in rows],
                    }
            elif query_type == "avg_sido":
                rows = db.fetch_all(
                    "SELECT a.area_nm as sido_nm, p.price, p.diff, p.trade_dt "
                    "FROM opinet_avg_price p JOIN opinet_area_code a ON p.area_cd=a.area_cd "
                    "WHERE p.prod_cd=%s AND a.parent_cd IS NULL AND p.area_cd!='00' "
                    "AND p.trade_dt=(SELECT MAX(trade_dt) FROM opinet_avg_price WHERE prod_cd=%s AND area_cd!='00') "
                    "ORDER BY a.area_cd",
                    (prodcd, prodcd), as_dict=True
                )
                if sido_cd:
                    rows = [r for r in rows if sido_cd in str(r.get("sido_nm", ""))]
                if rows:
                    return {
                        "success": True, "source": "DB(폴백)", "기준일": str(rows[0]["trade_dt"]),
                        "query_type": "시도별 평균가격", "count": len(rows),
                        "prices": [{"시도": r["sido_nm"], "가격": f"{r['price']}원",
                                    "전일대비": f"{r['diff']}원"} for r in rows],
                    }
            elif query_type == "avg_sigun":
                q = ("SELECT a.area_nm as sigun_nm, p.price, p.diff, p.trade_dt "
                     "FROM opinet_avg_price p JOIN opinet_area_code a ON p.area_cd=a.area_cd "
                     "WHERE p.prod_cd=%s AND a.parent_cd=%s "
                     "AND p.trade_dt=(SELECT MAX(trade_dt) FROM opinet_avg_price WHERE prod_cd=%s) "
                     "ORDER BY p.price")
                rows = db.fetch_all(q, (prodcd, sido_cd, prodcd), as_dict=True)
                if rows:
                    return {
                        "success": True, "source": "DB(폴백)", "기준일": str(rows[0]["trade_dt"]),
                        "query_type": "시군구별 평균가격", "count": len(rows),
                        "prices": [{"시군구": r["sigun_nm"], "가격": f"{r['price']}원",
                                    "전일대비": f"{r['diff']}원"} for r in rows],
                    }
            else:  # avg_national
                rows = db.fetch_all(
                    "SELECT prod_nm, price, diff, trade_dt FROM opinet_avg_price "
                    "WHERE area_cd='00' AND trade_dt=(SELECT MAX(trade_dt) FROM opinet_avg_price WHERE area_cd='00') "
                    "ORDER BY prod_cd",
                    as_dict=True
                )
                if rows:
                    return {
                        "success": True, "source": "DB(폴백)", "기준일": str(rows[0]["trade_dt"]),
                        "query_type": "전국 평균 유가", "count": len(rows),
                        "prices": [{"유종": r["prod_nm"], "가격": f"{r['price']}원",
                                    "전일대비": f"{r['diff']}원"} for r in rows],
                    }
    except Exception as e:
        logger.warning(f"[유가정보] DB 폴백 실패: {e}")
    return None


# ────────────────────────────────────────────────────────────────────
# Opinet 유가정보 조회 — 실시간 API 우선, 실패 시 DB 폴백
# ────────────────────────────────────────────────────────────────────
def search_gas_price(query_type: str = "avg_national", sido: str = None,
                     sigun: str = None, prodcd: str = "B027",
                     fuel_name: str = None) -> Dict[str, Any]:
    if not _OPINET_API_KEY:
        return {"success": False, "error": "OPNET_API 키가 설정되지 않았습니다."}

    # 유종명 → 코드 변환
    if fuel_name:
        prodcd = _PROD_MAP.get(fuel_name, prodcd)

    # 시도명 → 코드 변환
    sido_cd = None
    if sido:
        for name, code in _SIDO_MAP.items():
            if name in sido or sido in name:
                sido_cd = code
                break
        if not sido_cd:
            sido_cd = sido

    fuel_label = fuel_name or prodcd
    api_result = None

    try:
        if query_type == "low_price":
            params = {"prodcd": prodcd, "cnt": "20"}
            if sido_cd:
                params["area"] = sido_cd
            oils = _opinet_api_call("lowTop10", params)
            if oils:
                stations = [{"주유소명": o.get("OS_NM", ""), "가격": f"{o.get('PRICE', '')}원",
                             "주소": o.get("NEW_ADR") or o.get("VAN_ADR", ""),
                             "상표": o.get("POLL_DIV_CD", "")} for o in oils[:20]]
                api_result = {"success": True, "source": "실시간", "query_type": "최저가 주유소",
                              "유종": fuel_label, "지역": sido or "전국",
                              "count": len(stations), "stations": stations}

        elif query_type == "avg_sido":
            oils = _opinet_api_call("avgSidoPrice", {"prodcd": prodcd})
            if oils:
                prices = []
                for o in oils:
                    if sido_cd and o.get("SIDOCD") != sido_cd:
                        continue
                    prices.append({"시도": o.get("SIDONM", ""), "가격": f"{o.get('PRICE', '')}원",
                                   "전일대비": f"{o.get('DIFF', '')}원"})
                api_result = {"success": True, "source": "실시간", "query_type": "시도별 평균가격",
                              "유종": fuel_label, "count": len(prices), "prices": prices}

        elif query_type == "avg_sigun":
            if not sido_cd:
                return {"success": False, "error": "시도를 지정해주세요 (예: sido='전북')"}
            params = {"prodcd": prodcd, "sido": sido_cd}
            if sigun:
                params["sigun"] = sigun
            oils = _opinet_api_call("avgSigunPrice", params)
            if oils:
                prices = [{"시군구": o.get("SIGUNNM", ""),
                           "가격": f"{o.get('PRICE', '')}원" if o.get("PRICE") else "정보없음",
                           "전일대비": f"{o.get('DIFF', '')}원" if o.get("DIFF") else ""}
                          for o in oils]
                api_result = {"success": True, "source": "실시간", "query_type": "시군구별 평균가격",
                              "유종": fuel_label, "count": len(prices), "prices": prices}

        else:  # avg_national
            oils = _opinet_api_call("avgAllPrice")
            if oils:
                prices = [{"유종": o.get("PRODNM", ""), "가격": f"{o.get('PRICE', '')}원",
                           "전일대비": f"{o.get('DIFF', '')}원",
                           "기준일": o.get("TRADE_DT", "")} for o in oils]
                api_result = {"success": True, "source": "실시간", "query_type": "전국 평균 유가",
                              "count": len(prices), "prices": prices}

    except Exception as e:
        logger.warning(f"[유가정보] 실시간 API 실패: {e}")

    # 실시간 성공 시 반환
    if api_result:
        logger.info(f"[유가정보] 실시간 API 성공: {query_type} {api_result.get('count', 0)}건")
        return api_result

    # DB 폴백
    logger.info(f"[유가정보] 실시간 API 실패 → DB 폴백: {query_type}")
    db_result = _opinet_db_fallback(query_type, prodcd, sido_cd, sigun)
    if db_result:
        return db_result

    return {"success": False, "error": "유가 정보를 조회할 수 없습니다 (API 장애 + DB 데이터 없음)"}

