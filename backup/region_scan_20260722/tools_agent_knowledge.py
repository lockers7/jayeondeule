# ══════════════════════════════════════════════════════════════════════════════
# Agent 전용 지식저장 도구 — 자율 지식성장(웹 발견 → 스스로 저장)
#
# 주기 Agent 가 웹/MCP 에서 찾은 농장 도움정보를 스스로 저장가치 판단 후 저장한다.
# ⛔ 저장 대상 = web_knowledge_collection (채팅 search_farm_knowledge 는 회수하나
#    제어 사이클 query_domain_knowledge 는 읽지 않음) → 검증 안 된 웹정보가 릴레이
#    제어 LLM 을 오염시키지 않는다(모드분리·농장 안전). 제어에 쓸 룰은 농장주가
#    검토 후 save_domain_knowledge 로 승격(human-in-the-loop).
#
# 안전장치:
#   · 일일 저장 한도(AGENT_WEB_KNOWLEDGE_DAILY_LIMIT, 기본 8) — 폭주·오염 차단
#   · 중복 dedup — 임베딩 근접(<_DEDUP_DIST) 시 저장 생략
#   · 출처 URL·수집일·카테고리 메타 필수(농장주 신뢰·사후검토)
#   · file_name='자율웹지식' 그룹핑 → delete_farm_knowledge('자율웹지식') 로 일괄 삭제
#   · 전부 best-effort dict 반환(agent loop 보호)
#
# 파일 시작 함수 목록:
#   _today                  : 오늘 날짜(YYYY-MM-DD)
#   _saved_today_count      : 오늘 자율저장 건수(일일한도용)
#   _is_duplicate           : 임베딩 근접 중복 판정
#   agent_save_knowledge    : 웹 발견 지식 저장(한도·중복 가드)
#   TOOL_REGISTRY / TOOL_SPECS / tool_specs_text
# ══════════════════════════════════════════════════════════════════════════════
import os
import time
import uuid
from typing import Any, Dict

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_GROUP_FILE = "자율웹지식"          # delete_farm_knowledge 그룹 파일명
_SOURCE = "agent_web_scan"
_DAILY_LIMIT = int(os.getenv("AGENT_WEB_KNOWLEDGE_DAILY_LIMIT", "8"))
_DEDUP_DIST = float(os.getenv("AGENT_WEB_KNOWLEDGE_DEDUP_DIST", "0.15"))
_MIN_LEN = 20
_MAX_LEN = 1500
_CATEGORIES = ("재배정보", "병해충", "시세", "기상", "일반")


def _collection():
    from agri_ai_core.src.chroma.collections import web_knowledge_collection
    return web_knowledge_collection()


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _saved_today_count() -> int:
    try:
        from agri_ai_core.src.chroma.operations import get_documents
        res = get_documents(_collection(),
                            where={"$and": [{"source": {"$eq": _SOURCE}},
                                            {"save_date": {"$eq": _today()}}]},
                            include=["metadatas"], limit=10000)
        return len(res.get("ids") or [])
    except Exception as e:
        logger.debug(f"[Agent지식] 일일카운트 실패(0 처리): {e}")
        return 0


def _is_duplicate(embedding) -> bool:
    try:
        from agri_ai_core.src.chroma.operations import query_documents
        res = query_documents(_collection(), query_embeddings=[embedding], n_results=1,
                              where={"source": {"$eq": _SOURCE}}, include=["distances"])
        dists = res.get("distances") or []
        return bool(dists and dists[0] is not None and dists[0] < _DEDUP_DIST)
    except Exception:
        return False


def agent_save_knowledge(title: str = None, content: str = None,
                         category: str = "재배정보", source_url: str = None,
                         farm: Any = None) -> Dict[str, Any]:
    try:
        title = (title or "").strip()
        content = (content or "").strip()
        if len(content) < _MIN_LEN:
            return {"success": False, "error": f"content 는 {_MIN_LEN}자 이상 실질 내용이어야 합니다."}
        cat = (category or "일반").strip()
        if cat not in _CATEGORIES:
            cat = "일반"

        # 일일 한도 — 폭주·오염 차단
        if _saved_today_count() >= _DAILY_LIMIT:
            return {"success": False, "skipped": True,
                    "message": f"오늘 자율저장 한도({_DAILY_LIMIT}건) 도달 — 저장 생략(통지는 가능)."}

        from agri_ai_core.src.chroma.operations import add_document
        from agri_ai_core.src.ai.embedder import embed_text

        body = (f"[{cat}] {title}\n\n{content}")[:_MAX_LEN]
        if source_url:
            body = body + f"\n\n(출처: {source_url})"
        emb = embed_text(body)          # 0벡터 저장(검색불가) 방지 — 명시 필수
        if not emb:
            return {"success": False, "error": "임베딩 생성 실패"}

        # 중복 dedup — 이미 유사 지식 있으면 생략
        if _is_duplicate(emb):
            return {"success": False, "skipped": True,
                    "message": "이미 유사한 지식이 저장돼 있어 생략(중복 방지)."}

        meta = {
            "data_type": "web_knowledge_auto",
            "source": _SOURCE,
            "file_name": _GROUP_FILE,       # delete_farm_knowledge 그룹 삭제 키
            "category": cat,
            "title": title[:120],
            "save_date": _today(),
            "created_at": time.strftime("%Y-%m-%d %H:%M"),
        }
        if source_url:
            meta["source_url"] = str(source_url)[:300]
        if farm is not None:
            meta["farm_id"] = str(farm)
        doc_id = f"webk_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        add_document(_collection(), doc_id, body, meta, embedding=emb)
        logger.info(f"[Agent지식] 자율저장({cat}): \"{title[:50]}\" src={source_url or '-'}")
        return {"success": True, "knowledge_id": doc_id, "category": cat,
                "message": "농장 도움정보를 지식으로 저장했습니다. 이후 채팅 질문에 자동 반영됩니다."}
    except Exception as e:
        logger.warning(f"[Agent지식] 저장 실패: {e}")
        return {"success": False, "error": str(e)}


TOOL_REGISTRY = {"save_knowledge": agent_save_knowledge}

TOOL_SPECS = [
    {
        "name": "save_knowledge",
        "description": "웹/MCP 로 찾은 정보 중 상황버섯 재배·이 농장 관리에 지속 도움될 지식을 저장한다(자율 지식성장). 저장분은 이후 농장주 채팅 질문에 자동 회상된다. ⛔ 저장가치 3조건(재배 실질도움·지속 재사용가치·기존에 없음) 충족 시에만. 일회성 시황/잡정보는 저장 말고 통지만.",
        "args": {
            "title": {"type": "str", "desc": "30자 내 요약 제목"},
            "content": {"type": "str", "desc": "핵심 내용(임계치·조건·방법 포함, 20자↑)"},
            "category": {"type": "str", "desc": "재배정보|병해충|시세|기상|일반"},
            "source_url": {"type": "str", "desc": "출처 URL(신뢰·검토용, 가능하면 필수)"},
        },
    },
]


def tool_specs_text() -> str:
    lines = ["\n[지식저장 도구 — 자율 지식성장(웹발견→저장)]"]
    for spec in TOOL_SPECS:
        arg = ", ".join(f"{k}({v.get('type','')})" for k, v in spec["args"].items())
        lines.append(f"- {spec['name']}({arg}): {spec['description']}")
    return "\n".join(lines) + "\n"
