# ══════════════════════════════════════════════════════════════════════════════
# 주식 자동매매 데이터 스토어 — 농장관리와 분리 가능한 트레이딩 전용 저장소
#
# 농장주 지시(2026-07-24): 자동매매 화면의 수치데이터는 PostgreSQL trading_* 테이블,
#   판단·분석·실적·학습 등 AI 관리용 데이터는 전용 VectorDB(trading_knowledge)에.
#   ⛔ 농장관리(farm_*/document_collection)와 완전 분리 — 향후 별도 이관·삭제 가능.
#
# 테이블(수치):
#   trading_candidate   : 선정 종목(매수/목표/손절/기대수익/확신도)  ← Agent 공용
#   trading_performance : 매매 실적(매수가/매도가/수량/손익/수익률)
#   trading_prompt      : 사용자 프롬프트(전략 지시) 단일 활성본
#   trading_userdata    : 사용자 데이터(자본금·리스크한도 등 key-value)
# VectorDB(판단·분석·실적판단·학습): collections.trading_knowledge_collection()
#
# 파일 시작 함수 목록:
#   ensure_tables / _coll
#   save_trading_knowledge / recall_trading_knowledge / list_trading_knowledge
#   list_candidates / list_performance / record_performance
#   get_user_prompt / set_user_prompt / get_user_data / set_user_data
#   save_daily_learning / list_learning
# ══════════════════════════════════════════════════════════════════════════════
import time
import uuid
from typing import Any, Dict, List, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_CATEGORIES = ("판단", "분석", "실적", "학습", "프롬프트", "방법론", "일반")
_MAX_LEN = 1500
_RECALL_TOP_K = 5
_RECALL_MAX_DIST = 0.95

# ── 컨빅션 팩터(우리 이벤트드리븐 철학의 판단 축) — ⛔전통 TA 아님 ──
#   LLM 이 각 축을 0~100 으로 판단(판단 100% LLM). 코드는 저장·가중합산·표시만.
FACTOR_KEYS = ("event_novelty", "magnitude", "persistence", "sentiment",
               "supply_demand", "alt_data", "regime_fit")
FACTOR_LABELS = {
    "event_novelty": "사건 신규성", "magnitude": "규모", "persistence": "지속성",
    "sentiment": "심리(뉴스·공시 톤)", "supply_demand": "수급",
    "alt_data": "대체데이터", "regime_fit": "시장레짐 적합",
}
# ── 근거 데이터 출처(커버리지) — 결측은 보간 없이 신뢰도로 표시 ──
COVERAGE_KEYS = ("disclosure", "news", "supply_demand", "alt_data", "fundamentals")
COVERAGE_LABELS = {
    "disclosure": "공시", "news": "뉴스", "supply_demand": "수급",
    "alt_data": "대체데이터", "fundamentals": "실적/펀더멘털",
}


def _clamp100(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, f))


# ── [A] 팩터 컨빅션 종합점수 — 존재하는 축만 가중평균(투명·결정적, LLM 판단을 표시) ──
def composite_conviction(factor_scores: Dict[str, Any],
                         weights: Dict[str, Any] = None) -> Optional[float]:
    if not isinstance(factor_scores, dict):
        return None
    present = {}
    for k in FACTOR_KEYS:
        v = _clamp100(factor_scores.get(k))
        if v is not None:
            present[k] = v
    if not present:
        return None
    w = {}
    for k in present:
        wv = None
        if isinstance(weights, dict):
            try:
                wv = float(weights.get(k))
            except (TypeError, ValueError):
                wv = None
        w[k] = wv if (wv is not None and wv > 0) else 1.0
    tot = sum(w.values())
    if tot <= 0:
        return None
    return round(sum(present[k] * w[k] for k in present) / tot, 1)


# ── [B] 근거 데이터 커버리지 요약 — 어떤 출처가 실제 있었는지(정직 표시) ──
def coverage_summary(data_coverage: Dict[str, Any]) -> Dict[str, Any]:
    dc = data_coverage if isinstance(data_coverage, dict) else {}
    available = [k for k in COVERAGE_KEYS if bool(dc.get(k))]
    missing = [k for k in COVERAGE_KEYS if not bool(dc.get(k))]
    ratio = round(len(available) / len(COVERAGE_KEYS), 2)
    level = "높음" if ratio >= 0.6 else ("보통" if ratio >= 0.3 else "낮음")
    return {
        "available": available, "missing": missing,
        "available_labels": [COVERAGE_LABELS[k] for k in available],
        "missing_labels": [COVERAGE_LABELS[k] for k in missing],
        "ratio": ratio, "count": len(available), "total": len(COVERAGE_KEYS),
        "level": level,
    }


# ── [C] 포트폴리오 집중도 — 섹터·이벤트유형 편중 점검(리스크 관점, 결정적) ──
def portfolio_concentration(candidates: List[Dict[str, Any]],
                            warn_threshold: float = 0.4) -> Dict[str, Any]:
    rows = [c for c in (candidates or []) if isinstance(c, dict)]
    n = len(rows)
    out = {"total": n, "by_event_type": {}, "by_sector": {},
           "max_concentration": None, "hhi": None, "warning": False, "notes": []}
    if n == 0:
        return out

    def _dist(field):
        from collections import Counter
        cnt = Counter((str(c.get(field) or "미분류").strip() or "미분류") for c in rows)
        return {g: {"count": v, "share": round(v / n, 3)} for g, v in cnt.most_common()}

    out["by_event_type"] = _dist("event_type")
    out["by_sector"] = _dist("sector")
    # 최대 편중(두 차원 중 가장 큰 그룹) + HHI(허핀달, 이벤트유형 기준)
    best = None
    for dim, dist in (("event_type", out["by_event_type"]), ("sector", out["by_sector"])):
        for g, info in dist.items():
            if best is None or info["share"] > best["share"]:
                best = {"dimension": dim, "group": g, "share": info["share"],
                        "count": info["count"]}
    out["max_concentration"] = best
    out["hhi"] = round(sum(i["share"] ** 2 for i in out["by_event_type"].values()), 3)
    if best and best["share"] >= warn_threshold:
        out["warning"] = True
        out["notes"].append(
            f"{'이벤트유형' if best['dimension']=='event_type' else '섹터'} "
            f"'{best['group']}' 편중 {int(best['share']*100)}% (≥{int(warn_threshold*100)}%) — 분산 검토")
    return out


# ── [D보조] 팩터 가중치(관리자 조정 — 하드공식 아닌 표시/LLM 힌트용) ──
def get_factor_weights() -> Dict[str, float]:
    import json
    raw = get_user_data().get("factor_weights")
    if raw:
        try:
            w = json.loads(raw) if isinstance(raw, str) else raw
            return {k: float(w.get(k, 1.0)) for k in FACTOR_KEYS}
        except Exception:
            pass
    return {k: 1.0 for k in FACTOR_KEYS}


def set_factor_weights(weights: Dict[str, Any]) -> Dict[str, Any]:
    import json
    w = {}
    for k in FACTOR_KEYS:
        try:
            v = float(weights.get(k, 1.0))
        except (TypeError, ValueError):
            v = 1.0
        w[k] = max(0.0, v)
    set_user_data({"factor_weights": json.dumps(w)})
    return {"success": True, "weights": w}

_CREATE = [
    """CREATE TABLE IF NOT EXISTS trading_candidate (
        id SERIAL PRIMARY KEY, scan_date DATE NOT NULL, stock_code VARCHAR(10) NOT NULL,
        stock_name VARCHAR(80), event_type VARCHAR(120), thesis TEXT,
        target_buy NUMERIC, target_sell NUMERIC, stop_loss NUMERIC,
        expected_return_pct NUMERIC, confidence NUMERIC,
        status VARCHAR(20) NOT NULL DEFAULT 'proposed', account_type VARCHAR(10) NOT NULL DEFAULT 'paper',
        created_by VARCHAR(40) DEFAULT 'agent', rgst_dttm TIMESTAMP NOT NULL DEFAULT now(),
        updt_dttm TIMESTAMP NOT NULL DEFAULT now(), UNIQUE (scan_date, stock_code))""",
    """CREATE TABLE IF NOT EXISTS trading_performance (
        id SERIAL PRIMARY KEY, trade_date DATE NOT NULL, stock_code VARCHAR(10) NOT NULL,
        stock_name VARCHAR(80), buy_price NUMERIC, sell_price NUMERIC, qty INTEGER,
        pnl NUMERIC, return_pct NUMERIC, account_type VARCHAR(10) DEFAULT 'paper',
        status VARCHAR(20) DEFAULT 'closed', note TEXT,
        rgst_dttm TIMESTAMP NOT NULL DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS trading_prompt (
        id SERIAL PRIMARY KEY, prompt_text TEXT NOT NULL, active_yn CHAR(1) DEFAULT 'Y',
        updt_dttm TIMESTAMP NOT NULL DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS trading_userdata (
        data_key VARCHAR(60) PRIMARY KEY, data_value TEXT,
        updt_dttm TIMESTAMP NOT NULL DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS trading_strategy (
        name VARCHAR(60) PRIMARY KEY, prompt_text TEXT NOT NULL,
        active_yn CHAR(1) NOT NULL DEFAULT 'N', updt_dttm TIMESTAMP NOT NULL DEFAULT now())""",
]
_ensured = False

# 후보에 컨빅션 팩터·근거 커버리지·섹터·선정구분 추가(기존 테이블에도 무해 적용).
_ALTER = [
    "ALTER TABLE trading_candidate ADD COLUMN IF NOT EXISTS factor_scores JSONB",
    "ALTER TABLE trading_candidate ADD COLUMN IF NOT EXISTS data_coverage JSONB",
    "ALTER TABLE trading_candidate ADD COLUMN IF NOT EXISTS sector VARCHAR(60)",
    "ALTER TABLE trading_candidate ADD COLUMN IF NOT EXISTS selection_type VARCHAR(10) DEFAULT '추천'",
    "ALTER TABLE trading_candidate ADD COLUMN IF NOT EXISTS rationale TEXT",
]

# 선정 구분 — 추천(호재 근거)·임의(추천 부재 시 재량 선정)·불가(스캔했으나 부적합)
SELECTION_TYPES = ("추천", "임의", "불가")
_NO_EVENT = {"", "없음", "미분류", "-", "none", "미상"}


# 정직 라벨 — '추천'은 실제 호재 이벤트나 근거 커버리지가 있을 때만. 이벤트도 근거도
#   전무한데 '추천'이면 부정직 → '임의'로 강등(농장주 지적 2026-07-26). 판단은 LLM,
#   이 가드는 근거 없는 '추천' 오라벨만 정직 표시로 교정한다.
def honest_selection_type(selection_type, event_type=None,
                          data_coverage=None, thesis=None) -> str:
    sel = selection_type if selection_type in SELECTION_TYPES else "임의"
    if sel == "추천":
        ev = str(event_type or "").strip()
        cov = data_coverage if isinstance(data_coverage, dict) else {}
        has_cov = any(bool(cov.get(k)) for k in COVERAGE_KEYS)
        if (ev in _NO_EVENT) and not has_cov:
            return "임의"
    return sel


def ensure_tables():
    global _ensured
    if _ensured:
        return
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        for q in _CREATE:
            d.execute_query(q, ())
        for q in _ALTER:
            d.execute_query(q, ())
    _ensured = True


def _coll():
    from agri_ai_core.src.chroma.collections import trading_knowledge_collection
    return trading_knowledge_collection()


def _today():
    return time.strftime("%Y-%m-%d")


# ── 트레이딩 지식 RAG (판단·분석·실적판단·학습) — 전용 컬렉션 ──
def save_trading_knowledge(text: str, category: str = "일반",
                           key: str = None, meta_extra: Dict = None) -> Dict[str, Any]:
    try:
        body = (text or "").strip()
        if len(body) < 5:
            return {"success": False, "error": "내용이 너무 짧습니다."}
        cat = category if category in _CATEGORIES else "일반"
        from agri_ai_core.src.chroma.operations import add_document, delete_document
        from agri_ai_core.src.ai.embedder import embed_text
        body = body[:_MAX_LEN]
        emb = embed_text(body)
        if not emb:
            return {"success": False, "error": "임베딩 생성 실패"}
        meta = {"data_type": "trading_knowledge", "category": cat,
                "save_date": _today(), "created_at": time.strftime("%Y-%m-%d %H:%M")}
        if meta_extra:
            meta.update({k: str(v) for k, v in meta_extra.items()})
        if key:
            doc_id = f"trk_{key}"
            try:
                delete_document(_coll(), ids=[doc_id])
            except Exception:
                pass
        else:
            doc_id = f"trk_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        add_document(_coll(), doc_id, body, meta, embedding=emb)
        return {"success": True, "id": doc_id, "category": cat}
    except Exception as e:
        logger.warning(f"[트레이딩지식] 저장 실패: {e}")
        return {"success": False, "error": str(e)}


def recall_trading_knowledge(query: str, top_k: int = _RECALL_TOP_K) -> List[Dict[str, Any]]:
    try:
        from agri_ai_core.src.chroma.operations import query_documents
        from agri_ai_core.src.ai.embedder import embed_text
        emb = embed_text((query or "")[:_MAX_LEN])
        if not emb:
            return []
        res = query_documents(_coll(), query_embeddings=[emb], n_results=top_k,
                              include=["documents", "metadatas", "distances"])

        # 결과 구조 정규화 — 중첩([[...]]) / 평면([...]) 양쪽 대응(래퍼별 차이 방어)
        def _flat(v):
            v = v or []
            return v[0] if (v and isinstance(v[0], list)) else v
        docs, metas, dists = _flat(res.get("documents")), _flat(res.get("metadatas")), _flat(res.get("distances"))
        out = []
        for doc, m, dist in zip(docs, metas, dists):
            if dist is not None and dist > _RECALL_MAX_DIST:
                continue
            out.append({"text": doc, "category": (m or {}).get("category"),
                        "date": (m or {}).get("save_date")})
        return out
    except Exception as e:
        logger.debug(f"[트레이딩지식] 회상 실패: {e}")
        return []


def list_trading_knowledge(category: str = None, limit: int = 50) -> List[Dict[str, Any]]:
    try:
        from agri_ai_core.src.chroma.operations import get_documents
        where = {"category": {"$eq": category}} if category else None
        res = get_documents(_coll(), where=where, include=["documents", "metadatas"], limit=limit)
        ids = res.get("ids") or []
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        rows = [{"id": i, "text": d, "category": (m or {}).get("category"),
                 "date": (m or {}).get("save_date"), "created_at": (m or {}).get("created_at")}
                for i, d, m in zip(ids, docs, metas)]
        rows.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return rows[:limit]
    except Exception as e:
        logger.debug(f"[트레이딩지식] 목록 실패: {e}")
        return []


# ── 수치 데이터 (PostgreSQL trading_*) ──
def list_candidates(scan_date: str = None, status: str = None) -> List[Dict[str, Any]]:
    ensure_tables()
    from agri_ai_core.src.postgresql.connection import db_session
    q = ("SELECT scan_date, stock_code, stock_name, sector, event_type, thesis, rationale, target_buy, target_sell, "
         "stop_loss, expected_return_pct, confidence, factor_scores, data_coverage, "
         "COALESCE(selection_type,'임의') AS selection_type, status "
         "FROM trading_candidate WHERE scan_date=%s")
    vals = [scan_date or _today()]
    if status:
        q += " AND status=%s"; vals.append(status)
    # 추천 → 임의 → 불가 순, 그 안에서 기대수익 내림차순
    q += (" ORDER BY CASE COALESCE(selection_type,'추천') WHEN '추천' THEN 0 "
          "WHEN '임의' THEN 1 ELSE 2 END, expected_return_pct DESC NULLS LAST")
    with db_session() as d:
        rows = d.fetch_all(q, tuple(vals), as_dict=True) or []
    weights = get_factor_weights()
    out = []
    for r in rows:
        c = dict(r)
        fs = c.get("factor_scores") or {}
        dc = c.get("data_coverage") or {}
        # 근거 없는 '추천' 오라벨을 '임의'로 정직 강등(표시 정직성)
        c["selection_type"] = honest_selection_type(
            c.get("selection_type"), c.get("event_type"), dc, c.get("thesis"))
        # 종합 컨빅션(팩터 가중합산) + 근거 커버리지 요약을 파생 필드로 동봉(표시용)
        c["conviction"] = composite_conviction(fs, weights)
        c["coverage"] = coverage_summary(dc)
        out.append(c)
    return out


def list_performance(days: int = 30) -> List[Dict[str, Any]]:
    ensure_tables()
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        rows = d.fetch_all(
            "SELECT trade_date, stock_code, stock_name, buy_price, sell_price, qty, pnl, return_pct, status "
            "FROM trading_performance WHERE trade_date >= (CURRENT_DATE - %s::int) ORDER BY trade_date DESC, id DESC",
            (int(days),), as_dict=True) or []
    return [dict(r) for r in rows]


def record_performance(stock_code: str, stock_name: str = None, buy_price: float = None,
                       sell_price: float = None, qty: int = None, pnl: float = None,
                       return_pct: float = None, note: str = None) -> Dict[str, Any]:
    ensure_tables()
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        d.execute_query(
            "INSERT INTO trading_performance (trade_date, stock_code, stock_name, buy_price, sell_price, "
            "qty, pnl, return_pct, note) VALUES (CURRENT_DATE,%s,%s,%s,%s,%s,%s,%s,%s)",
            (stock_code, stock_name, buy_price, sell_price, qty, pnl, return_pct, note))
    return {"success": True}


def get_user_prompt() -> str:
    ensure_tables()
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        r = d.fetch_one("SELECT prompt_text FROM trading_prompt WHERE active_yn='Y' ORDER BY updt_dttm DESC LIMIT 1", ())
    return (dict(r)["prompt_text"] if r else "")


def set_user_prompt(prompt_text: str) -> Dict[str, Any]:
    ensure_tables()
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        d.execute_query("UPDATE trading_prompt SET active_yn='N' WHERE active_yn='Y'", ())
        d.execute_query("INSERT INTO trading_prompt (prompt_text, active_yn) VALUES (%s,'Y')", (prompt_text or "",))
    return {"success": True}


def get_user_data() -> Dict[str, str]:
    ensure_tables()
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        rows = d.fetch_all("SELECT data_key, data_value FROM trading_userdata ORDER BY data_key", (), as_dict=True) or []
    return {r["data_key"]: r["data_value"] for r in map(dict, rows)}


def set_user_data(data: Dict[str, Any]) -> Dict[str, Any]:
    ensure_tables()
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        for k, v in (data or {}).items():
            d.execute_query(
                "INSERT INTO trading_userdata (data_key, data_value, updt_dttm) VALUES (%s,%s,now()) "
                "ON CONFLICT (data_key) DO UPDATE SET data_value=EXCLUDED.data_value, updt_dttm=now()",
                (str(k)[:60], str(v)))
    return {"success": True, "count": len(data or {})}


def save_daily_learning(summary: str, meta: Dict = None) -> Dict[str, Any]:
    """매일 매매한 데이터 학습 저장 — 판단·실적·교훈을 트레이딩 지식(학습)으로 영속."""
    return save_trading_knowledge(summary, category="학습", meta_extra=meta)


def list_learning(limit: int = 50) -> List[Dict[str, Any]]:
    return list_trading_knowledge(category="학습", limit=limit)


# ── 자가개선(self-improvement) 루프 ──
def build_learning_context(query: str = None, max_items: int = 5) -> str:
    """자가개선 — 과거 학습·판단을 회상해 매매 임무에 주입할 컨텍스트 텍스트를 만든다.
    회상(recall)을 우선하되 비면 최근 학습(list)으로 폴백 → 항상 최근 교훈이 반영되게."""
    items = recall_trading_knowledge(query, top_k=max_items) if query else []
    if not items:
        items = list_trading_knowledge(category="학습", limit=max_items)
    if not items:
        return ""
    lines = ["[과거 매매 학습·교훈 — 이번 종목 선정·판단에 반드시 반영하라]"]
    for it in items[:max_items]:
        lines.append(f"- {(it.get('text') or '')[:220]}")
    return "\n".join(lines)


def auto_learn_from_run(candidates: List[Dict], final: str = None) -> Dict[str, Any]:
    """자가개선 — 스캔·선정 실행 후 결과 요약을 학습 데이터로 자동 저장(다음 실행이 회상)."""
    try:
        n = len(candidates or [])
        top = ", ".join(f"{c.get('stock_name')}({c.get('stock_code')})" for c in (candidates or [])[:5])
        summary = f"[{_today()} 자동선정] {n}종목 선정: {top or '없음'}."
        if final:
            summary += f" 판단요약: {str(final)[:200]}"
        return save_trading_knowledge(summary, category="학습",
                                      meta_extra={"source": "auto_run", "count": str(n)})
    except Exception as e:
        return {"success": False, "error": str(e)}


def learn_from_performance() -> Dict[str, Any]:
    """자가개선 — 매매 실적을 집계해 인사이트를 도출·학습 저장(다음 판단 개선에 반영)."""
    try:
        perf = list_performance(days=30)
        if not perf:
            return {"success": False, "message": "실적 데이터 없음"}
        wins = [p for p in perf if float(p.get("pnl") or 0) > 0]
        total_pnl = sum(float(p.get("pnl") or 0) for p in perf)
        win_rate = round(100 * len(wins) / len(perf), 1) if perf else 0
        insight = (f"[실적 학습 {_today()}] 최근 {len(perf)}건: 승률 {win_rate}%, 누적손익 {total_pnl:,.0f}원. "
                   f"승리 종목의 이벤트 유형을 다음 선정에서 가중하고 패배 유형은 회피하라.")
        return save_trading_knowledge(insight, category="학습", meta_extra={"source": "performance"})
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2 — 다양한 관리자 컨트롤 (AI 제어 우선: 전략·제외·리스크를 '프롬프트'로 주입)
#   ⛔ 코드가 종목을 고르지 않는다. 코드는 관리자 설정을 모아 LLM 임무에 주입만 한다.
#
#   save_strategy/list_strategies/activate_strategy/get_active_strategy : 전략 프리셋
#   set_candidate_status        : 수동 승인/거부(proposed/approved/rejected)
#   get_exclusions/set_exclusions : 제외 종목·섹터(AI 회피)
#   build_control_context       : 전략+제외+리스크+지시 → AI 주입 컨텍스트(제어 허브)
# ══════════════════════════════════════════════════════════════════════════════
def save_strategy(name: str, prompt_text: str) -> Dict[str, Any]:
    ensure_tables()
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        d.execute_query(
            "INSERT INTO trading_strategy (name, prompt_text, updt_dttm) VALUES (%s,%s,now()) "
            "ON CONFLICT (name) DO UPDATE SET prompt_text=EXCLUDED.prompt_text, updt_dttm=now()",
            (str(name)[:60], prompt_text or ""))
    return {"success": True, "name": name}


def list_strategies() -> List[Dict[str, Any]]:
    ensure_tables()
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        rows = d.fetch_all("SELECT name, prompt_text, active_yn FROM trading_strategy "
                           "ORDER BY active_yn DESC, updt_dttm DESC", (), as_dict=True) or []
    return [dict(r) for r in rows]


def activate_strategy(name: str) -> Dict[str, Any]:
    ensure_tables()
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        d.execute_query("UPDATE trading_strategy SET active_yn='N' WHERE active_yn='Y'", ())
        d.execute_query("UPDATE trading_strategy SET active_yn='Y', updt_dttm=now() WHERE name=%s", (name,))
    return {"success": True, "name": name}


def get_active_strategy() -> Dict[str, Any]:
    ensure_tables()
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        r = d.fetch_one("SELECT name, prompt_text FROM trading_strategy WHERE active_yn='Y' "
                        "ORDER BY updt_dttm DESC LIMIT 1", ())
    return dict(r) if r else {}


def set_candidate_status(scan_date: str, stock_code: str, status: str) -> Dict[str, Any]:
    """관리자 수동 승인/거부 — AI 선정 후 사람이 최종 게이트(모의투자도 승인제)."""
    ensure_tables()
    st = status if status in ("proposed", "approved", "rejected") else "proposed"
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        d.execute_query("UPDATE trading_candidate SET status=%s, updt_dttm=now() "
                        "WHERE scan_date=%s AND stock_code=%s", (st, scan_date or _today(), stock_code))
    return {"success": True, "status": st}


def get_exclusions() -> List[str]:
    raw = get_user_data().get("exclusions") or ""
    return [x.strip() for x in raw.split(",") if x.strip()]


def set_exclusions(items) -> Dict[str, Any]:
    """제외 종목/섹터(관리자 컨트롤) — 코드가 막지 않고 AI 임무에 '회피 지시'로 주입."""
    if isinstance(items, str):
        lst = [x.strip() for x in items.split(",") if x.strip()]
    else:
        lst = [str(x).strip() for x in (items or []) if str(x).strip()]
    set_user_data({"exclusions": ",".join(lst)})
    return {"success": True, "exclusions": lst}


def build_control_context() -> str:
    """관리자 컨트롤 통합 — 활성 전략·제외·리스크·사용자 지시를 하나의 AI 주입 지침으로.
    ⛔ 판단은 전부 LLM. 이 함수는 '관리자가 무엇을 원하는지'를 프롬프트로 전할 뿐이다."""
    parts = []
    strat = get_active_strategy()
    if strat.get("prompt_text"):
        parts.append(f"[관리자 활성 전략 '{strat.get('name')}'] {strat['prompt_text'][:400]}")
    excl = get_exclusions()
    if excl:
        parts.append(f"[제외 종목/섹터 — 절대 선정 금지] {', '.join(excl)}")
    ud = get_user_data()
    risk = {k: ud[k] for k in ("capital", "max_per_stock", "daily_loss_limit") if ud.get(k)}
    if risk:
        parts.append("[리스크 한도] " + ", ".join(f"{k}={v}" for k, v in risk.items())
                     + " — 이 한도 내에서만 판단하라.")
    up = get_user_prompt()
    if up:
        parts.append(f"[사용자 지시] {up[:300]}")
    if not parts:
        return ""
    return "[관리자 컨트롤 — 반드시 준수]\n" + "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3 — 최신 매매 트렌드 판단 강화 (AI 제어 우선: 방법론을 RAG로 회상·주입)
#   ⛔ 전통 TA(차트패턴·이동평균·지지저항·상하 가격밴드) 배제 지침을 항상 포함.
#   판단은 전부 LLM — 코드는 '최신 방법론 관점'을 프롬프트로 전할 뿐이다.
# ══════════════════════════════════════════════════════════════════════════════
def build_trend_context(query: str = "이벤트 공시 뉴스 심리 카탈리스트 테마 최신 매매 방법론") -> str:
    items = recall_trading_knowledge(query, top_k=6)
    meth = [it for it in items if it.get("category") == "방법론"]
    if not meth:
        meth = list_trading_knowledge(category="방법론", limit=6)
    lines = ["[최신 매매 방법론 — 반드시 이 관점으로 판단하라. "
             "⛔전통 TA(차트패턴·이동평균·지지저항·상하 가격밴드·단순 그래프분석) 전면 배제]"]
    for it in meth[:6]:
        lines.append(f"- {(it.get('text') or '')[:200]}")
    return "\n".join(lines)


# ── 자연어 매매전략 설정 (채팅으로 '말로 한' 전략을 활성 전략으로) ──
def set_trading_strategy(strategy: str, name: str = None) -> Dict[str, Any]:
    """농장주가 채팅으로 말한 매매 전략(철학)을 활성 전략으로 저장 → 다음 스캔부터 LLM 판단에 주입.
    build_control_context 가 이 활성 전략을 매 실행에 반영. 코드 변경 없이 자연어로 전략 교체."""
    body = (strategy or "").strip()
    if len(body) < 4:
        return {"success": False, "error": "전략 내용이 너무 짧습니다."}
    nm = (name or "").strip() or f"전략_{_today()}"
    save_strategy(nm, body)
    activate_strategy(nm)
    return {"success": True, "name": nm, "active": True,
            "message": f"매매 전략 '{nm}' 을(를) 활성 전략으로 저장했습니다. "
                       f"다음 자동매매 스캔부터 이 전략(철학)으로 종목을 판단합니다."}
