# ══════════════════════════════════════════════════════════════════════════════
# DART(전자공시) MCP 서버 — 국내 상장사 공시·기업개황·재무 조회(자동매매 이벤트 스캔용)
#
# 실행: uv run --with mcp --with requests python server.py  (stdio)
# 인증: 환경변수 DART_API_KEY (Open DART 인증키). mcp.json env 로 ${DART_API_KEY} 주입.
#
# 도구:
#   search_disclosures : 기간 공시 검색(이벤트 스캔 핵심) — 종목코드·공시유형 포함
#   company_info       : 기업개황(회사명·업종·상장·대표)
#   financial_statement: 단일회사 주요계정 재무제표
# ══════════════════════════════════════════════════════════════════════════════
import datetime
import os

import requests
from mcp.server.fastmcp import FastMCP

_API = "https://opendart.fss.or.kr/api"
_KEY = os.getenv("DART_API_KEY", "")
_TIMEOUT = 15

mcp = FastMCP("dart")


def _get(path: str, params: dict) -> dict:
    try:
        r = requests.get(f"{_API}/{path}",
                         params={"crtfc_key": _KEY, **params}, timeout=_TIMEOUT)
        return r.json()
    except Exception as e:
        return {"status": "ERR", "message": f"DART 호출 실패: {e}"}


@mcp.tool()
def search_disclosures(bgn_de: str = "", end_de: str = "", corp_code: str = "",
                       pblntf_ty: str = "", page_no: int = 1,
                       page_count: int = 100) -> dict:
    """전자공시 검색(이벤트 스캔 핵심). 기간의 공시를 반환하며 각 항목에 종목코드(stock_code)·
    회사명·보고서명·접수일이 포함된다. bgn_de/end_de=YYYYMMDD(생략 시 오늘).
    pblntf_ty 공시유형: A=정기공시 B=주요사항보고 C=발행공시 D=지분공시 E=기타 F=외부감사 등.
    corp_code(DART 8자리) 지정 시 특정기업만."""
    if not bgn_de:
        bgn_de = end_de = datetime.date.today().strftime("%Y%m%d")
    p = {"bgn_de": bgn_de, "end_de": end_de or bgn_de,
         "page_no": max(1, int(page_no or 1)),
         "page_count": min(max(1, int(page_count or 100)), 100)}
    if corp_code:
        p["corp_code"] = corp_code
    if pblntf_ty:
        p["pblntf_ty"] = pblntf_ty
    d = _get("list.json", p)
    return {"status": d.get("status"), "message": d.get("message"),
            "total_count": d.get("total_count"), "total_page": d.get("total_page"),
            "list": d.get("list", [])}


@mcp.tool()
def company_info(corp_code: str) -> dict:
    """기업개황 — 회사명·영문명·종목코드·업종·대표자·상장구분·설립일 등. corp_code=DART 8자리."""
    return _get("company.json", {"corp_code": corp_code})


@mcp.tool()
def financial_statement(corp_code: str, bsns_year: str,
                        reprt_code: str = "11011") -> dict:
    """단일회사 주요계정 재무제표. bsns_year=사업연도(YYYY).
    reprt_code: 11011=사업보고서 11012=반기 11013=1분기 11014=3분기."""
    d = _get("fnlttSinglAcnt.json",
             {"corp_code": corp_code, "bsns_year": bsns_year, "reprt_code": reprt_code})
    return {"status": d.get("status"), "message": d.get("message"),
            "list": d.get("list", [])}


if __name__ == "__main__":
    mcp.run(transport="stdio")
