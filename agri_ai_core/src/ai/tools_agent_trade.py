# ══════════════════════════════════════════════════════════════════════════════
# Agent 전용 트레이딩 도구 — 국내주식 자동매매(Phase 1: 이벤트 스캔·후보 선정·승인요청)
#
# 농장주 지시(2026-07-23): "모든 관리 기능은 로컬 AI Agent". 장 마감 후 로컬 AI Agent 가
#   전종목 공시 이벤트를 스캔 → 손익 예측으로 종목 선정 → 매수가/목표가/손절가 산정 →
#   관리자 승인요청. 데이터 취득은 기존 mcp_call(dart/naver/kis), 여기서는 결정·상태 도구.
#
# 안전(Phase 1):
#   · 실제 주문 없음 — 후보 제안·저장·승인요청까지만(주문 실행은 Phase 2, 모의투자·승인 게이트)
#   · account_type 기본 'paper'(모의투자) 강제
#   · 전부 dict 반환(agent ReAct loop 보호)
#
# 파일 시작 함수 목록:
#   ensure_table            : trade_candidate 테이블 보장
#   agent_scan_stock_events : DART 공시 이벤트 스캔(종목코드 포함) — mcp_call 위임·정규화
#   agent_save_trade_candidate : 매매 후보 저장(upsert, 매수/목표/손절/기대수익/확신도)
#   agent_list_trade_candidates: 후보 조회
#   agent_request_trade_approval : 제안 후보를 관리자에게 승인요청(카카오)
#   TOOL_REGISTRY / TOOL_SPECS / tool_specs_text
# ══════════════════════════════════════════════════════════════════════════════
import json
from typing import Any, Dict

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_EVENT_TYPES = {  # DART pblntf_ty
    "A": "정기공시", "B": "주요사항보고", "C": "발행공시",
    "D": "지분공시", "E": "기타", "F": "외부감사", "": "전체",
}

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS trading_candidate (
    id                  SERIAL PRIMARY KEY,
    scan_date           DATE        NOT NULL,
    stock_code          VARCHAR(10) NOT NULL,
    stock_name          VARCHAR(80),
    event_type          VARCHAR(120),
    thesis              TEXT,
    target_buy          NUMERIC,
    target_sell         NUMERIC,
    stop_loss           NUMERIC,
    expected_return_pct NUMERIC,
    confidence          NUMERIC,
    status              VARCHAR(20) NOT NULL DEFAULT 'proposed',
    account_type        VARCHAR(10) NOT NULL DEFAULT 'paper',
    created_by          VARCHAR(40) DEFAULT 'agent',
    rgst_dttm           TIMESTAMP   NOT NULL DEFAULT now(),
    updt_dttm           TIMESTAMP   NOT NULL DEFAULT now(),
    UNIQUE (scan_date, stock_code)
)
"""

_ALTER_TABLE = [
    "ALTER TABLE trading_candidate ADD COLUMN IF NOT EXISTS factor_scores JSONB",
    "ALTER TABLE trading_candidate ADD COLUMN IF NOT EXISTS data_coverage JSONB",
    "ALTER TABLE trading_candidate ADD COLUMN IF NOT EXISTS sector VARCHAR(60)",
    "ALTER TABLE trading_candidate ADD COLUMN IF NOT EXISTS selection_type VARCHAR(10) DEFAULT '추천'",
    "ALTER TABLE trading_candidate ADD COLUMN IF NOT EXISTS rationale TEXT",
]

_ensured = False


def ensure_table():
    global _ensured
    if _ensured:
        return
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        d.execute_query(_CREATE_TABLE, ())
        for q in _ALTER_TABLE:
            d.execute_query(q, ())
    _ensured = True


def _today():
    import time
    return time.strftime("%Y-%m-%d")


def _today_compact():
    import time
    return time.strftime("%Y%m%d")


def agent_scan_stock_events(scan_type: str = "B", date: str = None,
                            page_count: int = 100) -> Dict[str, Any]:
    """DART 공시 이벤트 스캔(다음날 매매 후보 원천). scan_type: A정기 B주요사항 C발행 D지분.
    각 종목의 종목코드·회사명·보고서명(이벤트) 반환."""
    try:
        from agri_ai_core.src.ai.tools_mcp_gateway import mcp_call
        d = date or _today_compact()
        ty = scan_type if scan_type in _EVENT_TYPES else "B"
        res = mcp_call(server="dart", tool="search_disclosures",
                       args={"bgn_de": d, "end_de": d, "pblntf_ty": ty,
                             "page_count": min(max(int(page_count or 100), 1), 100)})
        if not res.get("success"):
            return {"success": False, "error": res.get("error", "DART 스캔 실패")}
        try:
            data = json.loads(res.get("result", "{}"))
        except Exception:
            return {"success": False, "error": "DART 결과 파싱 실패"}
        events = []
        for it in (data.get("list") or []):
            sc = (it.get("stock_code") or "").strip()
            if not sc:                  # 종목코드 없는 공시(비상장 등) 제외
                continue
            events.append({"code": sc, "name": it.get("corp_name"),
                           "event": (it.get("report_nm") or "").strip()})
        # LLM 컨텍스트(도구결과 트림) 대비 — 컴팩트 한 줄 요약 + 상위 N만 노출.
        _cap_n = 25
        summary = " / ".join(f"{e['name']}({e['code']}):{e['event']}" for e in events[:_cap_n])
        return {"success": True, "scan_type": _EVENT_TYPES[ty], "date": d,
                "total_count": data.get("total_count"), "count": len(events),
                "note": f"이벤트 {len(events)}건(상위 {min(len(events), _cap_n)} 표시). 호재(자기주식취득·합병·"
                        f"공급계약·실적개선) 위주로 선별하고 save_trade_candidate 로 저장하세요.",
                "events": summary[:1400]}
    except Exception as e:
        logger.warning(f"[Agent트레이딩] scan_stock_events 실패: {e}")
        return {"success": False, "error": f"이벤트 스캔 실패: {e}"}


def agent_save_trade_candidate(stock_code: str = None, stock_name: str = None,
                               event_type: str = None, thesis: str = None,
                               target_buy: float = None, target_sell: float = None,
                               stop_loss: float = None, expected_return_pct: float = None,
                               confidence: float = None, factor_scores: Any = None,
                               data_coverage: Any = None, sector: str = None,
                               selection_type: str = None, rationale: str = None,
                               **_ignore) -> Dict[str, Any]:
    """매매 후보 저장(모의투자). 종목코드·이벤트·논거·매수가/목표가/손절가/기대수익%/확신도.
    같은 날 같은 종목은 갱신(upsert). 실제 주문 아님 — 승인 후 Phase 2 에서 집행.
    factor_scores: 컨빅션 팩터 0~100 dict(event_novelty·magnitude·persistence·sentiment·
      supply_demand·alt_data·regime_fit) — 네가 판단한 축별 점수.
    data_coverage: 근거 출처 유무 dict(disclosure·news·supply_demand·alt_data·fundamentals)
      — 실제로 확인된 근거만 true(없는 건 지어내지 말 것). sector: 섹터명.
    thesis: 한 줄 요약(이벤트/핵심).
    rationale: ⭐ 사용자·관리자·트레이더가 읽고 매매를 판단할 수 있도록 '왜 이 종목을 이 구분으로
      선정했는지'를 **여러 문장 자연어 서술**로 작성 — 사건 내용·판단 근거·기대 시나리오·핵심 리스크·
      매매 참고를 사람이 읽는 글로. ⛔수치 나열이 아니라 설명하는 글. 근거 약하면 솔직히 그렇게 서술."""
    try:
        if not stock_code or not str(stock_code).strip():
            return {"success": False, "error": "stock_code(종목코드)는 필수입니다."}
        ensure_table()
        from agri_ai_core.src.postgresql.connection import db_session

        def _num(v):
            try:
                return float(v) if v is not None and str(v) != "" else None
            except (TypeError, ValueError):
                return None

        import json as _json
        def _jsonb(v):
            if v is None or v == "":
                return None
            if isinstance(v, str):
                try:
                    v = _json.loads(v)
                except Exception:
                    return None
            return _json.dumps(v) if isinstance(v, dict) else None
        sel = str(selection_type).strip() if selection_type else "임의"
        if sel not in ("추천", "임의", "불가"):
            sel = "임의"
        # 근거(호재 이벤트·커버리지) 없는 '추천'은 '임의'로 정직 강등
        try:
            from agri_ai_core.src.ai.trading_store import honest_selection_type
            _dc = data_coverage if isinstance(data_coverage, dict) else None
            sel = honest_selection_type(sel, event_type, _dc, thesis)
        except Exception:
            pass
        with db_session() as d:
            d.execute_query(
                "INSERT INTO trading_candidate (scan_date, stock_code, stock_name, sector, event_type, "
                "thesis, rationale, target_buy, target_sell, stop_loss, expected_return_pct, confidence, "
                "factor_scores, data_coverage, selection_type, "
                "status, account_type, created_by, rgst_dttm, updt_dttm) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'proposed','paper','agent',now(),now()) "
                "ON CONFLICT (scan_date, stock_code) DO UPDATE SET stock_name=EXCLUDED.stock_name, "
                "sector=EXCLUDED.sector, event_type=EXCLUDED.event_type, thesis=EXCLUDED.thesis, "
                "rationale=COALESCE(EXCLUDED.rationale, trading_candidate.rationale), "
                "target_buy=EXCLUDED.target_buy, target_sell=EXCLUDED.target_sell, stop_loss=EXCLUDED.stop_loss, "
                "expected_return_pct=EXCLUDED.expected_return_pct, confidence=EXCLUDED.confidence, "
                "factor_scores=COALESCE(EXCLUDED.factor_scores, trading_candidate.factor_scores), "
                "data_coverage=COALESCE(EXCLUDED.data_coverage, trading_candidate.data_coverage), "
                "selection_type=EXCLUDED.selection_type, "
                "updt_dttm=now()",
                (_today(), str(stock_code).strip(), stock_name, sector, event_type, thesis,
                 (str(rationale).strip() if rationale else None),
                 _num(target_buy), _num(target_sell), _num(stop_loss),
                 _num(expected_return_pct), _num(confidence),
                 _jsonb(factor_scores), _jsonb(data_coverage), sel))
        logger.info(f"[Agent트레이딩] 후보저장: {stock_code} {stock_name} "
                    f"매수 {target_buy}→목표 {target_sell} 기대 {expected_return_pct}%")
        return {"success": True, "stock_code": str(stock_code).strip(),
                "message": "매매 후보(모의)로 저장했습니다. 관리자 승인 후 집행됩니다."}
    except Exception as e:
        logger.warning(f"[Agent트레이딩] 후보저장 실패: {e}")
        return {"success": False, "error": str(e)}


def agent_list_trade_candidates(scan_date: str = None,
                                status: str = None) -> Dict[str, Any]:
    """저장된 매매 후보 조회. scan_date(YYYY-MM-DD, 생략 시 오늘), status(proposed/approved 등)."""
    try:
        ensure_table()
        from agri_ai_core.src.postgresql.connection import db_session
        q = ("SELECT stock_code, stock_name, event_type, target_buy, target_sell, stop_loss, "
             "expected_return_pct, confidence, status FROM trading_candidate WHERE scan_date=%s")
        vals = [scan_date or _today()]
        if status:
            q += " AND status=%s"
            vals.append(status)
        q += " ORDER BY expected_return_pct DESC NULLS LAST"
        with db_session() as d:
            rows = d.fetch_all(q, tuple(vals), as_dict=True) or []
        return {"success": True, "scan_date": scan_date or _today(),
                "count": len(rows), "candidates": [dict(r) for r in rows]}
    except Exception as e:
        logger.warning(f"[Agent트레이딩] 후보조회 실패: {e}")
        return {"success": False, "error": str(e)}


def agent_request_trade_approval(scan_date: str = None, note: str = "") -> Dict[str, Any]:
    """제안된 매매 후보를 관리자에게 카카오로 승인요청. 승인 시에만 Phase 2 에서 집행."""
    try:
        listed = agent_list_trade_candidates(scan_date=scan_date, status="proposed")
        cands = listed.get("candidates", []) if listed.get("success") else []
        if not cands:
            return {"success": False, "error": "승인요청할 제안 후보가 없습니다. 먼저 save_trade_candidate."}
        lines = [f"📈 매매 후보 승인요청 ({scan_date or _today()}) — 모의투자"]
        for c in cands[:10]:
            lines.append(f"· {c.get('stock_name')}({c.get('stock_code')}) {c.get('event_type') or ''} "
                         f"매수 {c.get('target_buy')}→목표 {c.get('target_sell')} "
                         f"(기대 {c.get('expected_return_pct')}%, 확신 {c.get('confidence')})")
        if note:
            lines.append(f"메모: {note}")
        body = "\n".join(lines)
        from agri_ai_core.src.ai.kakao_notify import push_alert
        push_alert(level="info", title=f"[자동매매] {len(cands)}종목 승인요청", body=body)
        logger.info(f"[Agent트레이딩] 승인요청 발송: {len(cands)}종목")
        return {"success": True, "requested": len(cands),
                "message": f"{len(cands)}종목 승인요청을 관리자에게 발송했습니다."}
    except Exception as e:
        logger.warning(f"[Agent트레이딩] 승인요청 실패: {e}")
        return {"success": False, "error": str(e)}


TOOL_REGISTRY = {
    "scan_stock_events":     agent_scan_stock_events,
    "save_trade_candidate":  agent_save_trade_candidate,
    "list_trade_candidates": agent_list_trade_candidates,
    "request_trade_approval": agent_request_trade_approval,
}

TOOL_SPECS = [
    {"name": "scan_stock_events",
     "description": "DART 전자공시로 국내 상장사 이벤트를 스캔(다음날 매매 후보 원천). scan_type: A정기 B주요사항 C발행 D지분. 각 종목의 종목코드·회사명·이벤트(보고서명) 반환. 자기주식취득·합병·공급계약·실적 등이 매매 이벤트.",
     "args": {"scan_type": {"type": "str", "desc": "A|B|C|D (기본 B=주요사항보고)"},
              "date": {"type": "str", "desc": "YYYYMMDD (생략 시 오늘)"}}},
    {"name": "save_trade_candidate",
     "description": "매매 후보를 저장(모의투자). 종목코드·이벤트·논거·매수가·목표가·손절가·기대수익%·확신도·선정구분·판단근거서술. 같은 날 같은 종목은 갱신. ⛔ 실제 주문 아님 — 관리자 승인 후 Phase2 집행.",
     "args": {"stock_code": {"type": "str", "desc": "6자리 종목코드(필수, 실제 정확한 코드)"},
              "stock_name": {"type": "str", "desc": "종목명"},
              "sector": {"type": "str", "desc": "섹터(예: 반도체·2차전지·바이오)"},
              "event_type": {"type": "str", "desc": "이벤트(예: 자기주식취득결정). 없으면 '없음'"},
              "thesis": {"type": "str", "desc": "한 줄 요약(이벤트/핵심)"},
              "rationale": {"type": "str", "desc": "⭐필수: 사용자·관리자·트레이더가 읽고 매매를 판단하도록 '왜 이 종목을 이 구분으로 선정했는지'를 여러 문장 자연어 서술(사건·근거·기대 시나리오·리스크·매매 참고). ⛔수치 나열 아니라 설명하는 글"},
              "selection_type": {"type": "str", "desc": "선정구분: '추천'(실제 호재+근거) | '임의'(호재 없어 재량) | '불가'(부적합)"},
              "factor_scores": {"type": "dict", "desc": "판단 축별 0~100: event_novelty·magnitude·persistence·sentiment·supply_demand·alt_data·regime_fit(판단한 축만, placeholder 금지)"},
              "data_coverage": {"type": "dict", "desc": "확인된 근거만 true: disclosure·news·supply_demand·alt_data·fundamentals"},
              "target_buy": {"type": "float", "desc": "목표 매수가"},
              "target_sell": {"type": "float", "desc": "목표 매도가"},
              "stop_loss": {"type": "float", "desc": "손절가"},
              "expected_return_pct": {"type": "float", "desc": "기대수익률(%)"},
              "confidence": {"type": "float", "desc": "확신도 0~1"}}},
    {"name": "list_trade_candidates",
     "description": "저장된 매매 후보 조회(기대수익 내림차순). scan_date·status 필터.",
     "args": {"scan_date": {"type": "str", "desc": "YYYY-MM-DD (생략 시 오늘)"},
              "status": {"type": "str", "desc": "proposed|approved 등(선택)"}}},
    {"name": "request_trade_approval",
     "description": "제안된 매매 후보를 관리자에게 카카오로 승인요청. 승인 시에만 실제 집행(Phase2). 후보 선정·저장을 마친 뒤 호출.",
     "args": {"note": {"type": "str", "desc": "관리자에게 전할 메모(선택)"}}},
]


def tool_specs_text() -> str:
    lines = ["\n[트레이딩 도구 — 국내주식 자동매매(모의): 이벤트 스캔·후보 선정·승인요청]"]
    for spec in TOOL_SPECS:
        arg = ", ".join(f"{k}({v.get('type','')})" for k, v in spec["args"].items())
        lines.append(f"- {spec['name']}({arg}): {spec['description']}")
    return "\n".join(lines) + "\n"
