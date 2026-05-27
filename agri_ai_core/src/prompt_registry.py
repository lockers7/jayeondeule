# ════════════════════════════════════════════════════════════════════
# PromptRegistry — context 외부화 단일 read API.
#
# 정책 (사용자 지침):
#   · ChromaDB(prompt_chunk / domain_rule) — 학습 진화 (의미 검색)
#   · PostgreSQL(tool_definition_m / prompt_block_m) — 사용자 직접 관리 (정확 일치)
#
# 동작 원칙:
#   · 캐시 invalidate: prompt_block_m / tool_definition_m 의 updt_dttm 비교
#     (BEFORE UPDATE 트리거가 NOW() 자동 갱신 — migration 003). TTL 캐시 금지 —
#     web UI / 관리자 직접 UPDATE 가 즉시 반영되어야 함.
#   · DB/ChromaDB 비어있으면 빈 결과 반환 — 기존 코드 호출자에게 영향 0
#   · 상위 모듈(control/ai/api) 에서 단방향 import. 상호 호출 금지.
#
# 파일 시작 함수 목록:
#   get_block            : prompt_block_m 의 정형 블록 본문 조회 (placeholder 치환)
#   get_tools            : tool_definition_m 의 활성 도구 schema 목록 조회
#   search_rules         : ChromaDB domain_rule 컬렉션 의미 검색 (top_k)
#   search_prompt_chunks : ChromaDB prompt_chunk 컬렉션 의미 검색 (top_k)
#   get_rule_by_id       : ChromaDB domain_rule 컬렉션 id 정확 매치 단건 조회
#   get_chunk_by_id      : ChromaDB prompt_chunk 컬렉션 id 정확 매치 단건 조회
#   clear_cache          : 테스트/관리자용 캐시 강제 무효화
# ════════════════════════════════════════════════════════════════════
import threading
from typing import Any, Dict, List, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# 캐시 invalidate 는 updt_dttm 비교 (TTL 캐시 금지).
# _BLOCK_CACHE: block_id -> {'value': body|None, 'updt_dttm': datetime|None}
# _TOOLS_CACHE: {'value': [rows], 'updt_dttm': datetime|None}
# _CTRL_BLOCK_CACHE: control_prompt_m 전용 캐시 (같은 패턴)
_LOCK = threading.Lock()
_BLOCK_CACHE: Dict[str, Any] = {}
_TOOLS_CACHE: Dict[str, Any] = {'value': None, 'updt_dttm': None}
_CTRL_BLOCK_CACHE: Dict[str, Any] = {}


# ────────────────────────────────────────────────────────────────────
# prompt_block_m 의 정형 블록 본문 조회 + placeholder 치환.
# PROMPT_BLOCK_M.updt_dttm 비교로 캐시 invalidate.
# DB 미존재/비활성 시 None 반환 — 호출자가 fallback 결정.
# placeholders 는 본문의 ${name} 패턴을 kwargs 로 치환.
# ────────────────────────────────────────────────────────────────────
def get_block(block_id: str, **kwargs) -> Optional[str]:
    if not block_id:
        return None

    # 1) 가벼운 updt_dttm 조회 (변경 감지)
    current_updt = None
    try:
        from agri_ai_core.src.postgresql.reader import read_prompt_block_updt
        current_updt = read_prompt_block_updt(block_id)
    except Exception as ee:
        logger.debug(f"[PromptRegistry] block updt 조회 실패 (캐시 fallback): {ee}")

    with _LOCK:
        cached = _BLOCK_CACHE.get(block_id)
        # 2) 캐시 hit — updt_dttm 동일하면 그대로 사용
        if cached is not None and current_updt is not None and cached.get('updt_dttm') == current_updt:
            body = cached['value']
        else:
            # 3) 변경 감지(또는 첫 조회) — 본문 재로드
            body = _load_block_from_db(block_id)
            # DB 실패 + 캐시 있음 → 캐시 fallback
            if body is None and cached is not None and cached.get('value') is not None:
                body = cached['value']
            else:
                _BLOCK_CACHE[block_id] = {'value': body, 'updt_dttm': current_updt}

    if body is None:
        return None
    if not kwargs:
        return body
    out = body
    for k, v in kwargs.items():
        out = out.replace('${' + k + '}', str(v))
    return out


# ────────────────────────────────────────────────────────────────────
# tool_definition_m 활성 도구 목록 조회 (priority 오름차순).
# TOOL_DEFINITION_M.max(updt_dttm) 비교로 캐시 invalidate.
# 각 항목은 {tool_id, schema_json(dict), description, category, priority}.
# ────────────────────────────────────────────────────────────────────
def get_tools(active_only: bool = True) -> List[Dict[str, Any]]:
    current_updt = None
    try:
        from agri_ai_core.src.postgresql.reader import read_tool_definition_max_updt
        current_updt = read_tool_definition_max_updt()
    except Exception as ee:
        logger.debug(f"[PromptRegistry] tool max_updt 조회 실패 (캐시 fallback): {ee}")

    with _LOCK:
        if (_TOOLS_CACHE['value'] is not None
                and current_updt is not None
                and _TOOLS_CACHE['updt_dttm'] == current_updt):
            return list(_TOOLS_CACHE['value'])
        rows = _load_tools_from_db(active_only=active_only)
        # DB 실패 시 기존 캐시 fallback
        if not rows and _TOOLS_CACHE['value'] is not None:
            return list(_TOOLS_CACHE['value'])
        _TOOLS_CACHE['value'] = rows
        _TOOLS_CACHE['updt_dttm'] = current_updt
        return list(rows)


# ────────────────────────────────────────────────────────────────────
# ChromaDB domain_rule 컬렉션 의미 검색.
# query 텍스트와 의미 유사한 룰 top_k 건 반환. 빈 컬렉션 시 빈 list.
# 반환: [{rule_id, content, metadata, distance}, ...]
# ────────────────────────────────────────────────────────────────────
def search_rules(query: str, top_k: int = 5, where: Optional[Dict] = None) -> List[Dict[str, Any]]:
    if not query:
        return []
    try:
        from agri_ai_core.src.chroma.collections import domain_rule_collection
        from agri_ai_core.src.chroma.operations import query_documents
        from agri_ai_core.src.ai.embedder import embed_text

        coll = domain_rule_collection()
        if not coll:
            return []
        emb = embed_text(query)
        if emb is None:
            return []
        result = query_documents(
            coll, query_embeddings=[emb], n_results=top_k, where=where,
            include=['documents', 'metadatas', 'distances'],
        )
        return _flatten_chroma_result(result, id_field='rule_id')
    except Exception as e:
        logger.warning(f"[PromptRegistry] search_rules 실패: {e}")
        return []


# ────────────────────────────────────────────────────────────────────
# ChromaDB prompt_chunk 컬렉션 의미 검색 (시스템/유저/분석/답변 chunk).
# 반환: [{chunk_id, content, metadata, distance}, ...]
# ────────────────────────────────────────────────────────────────────
def search_prompt_chunks(query: str, top_k: int = 5, where: Optional[Dict] = None) -> List[Dict[str, Any]]:
    if not query:
        return []
    try:
        from agri_ai_core.src.chroma.collections import prompt_chunk_collection
        from agri_ai_core.src.chroma.operations import query_documents
        from agri_ai_core.src.ai.embedder import embed_text

        coll = prompt_chunk_collection()
        if not coll:
            return []
        emb = embed_text(query)
        if emb is None:
            return []
        result = query_documents(
            coll, query_embeddings=[emb], n_results=top_k, where=where,
            include=['documents', 'metadatas', 'distances'],
        )
        return _flatten_chroma_result(result, id_field='chunk_id')
    except Exception as e:
        logger.warning(f"[PromptRegistry] search_prompt_chunks 실패: {e}")
        return []


# ────────────────────────────────────────────────────────────────────
# ChromaDB domain_rule 컬렉션 metadata.rule_id 정확 매치 단건 조회.
# 의미 검색이 아니라 metadata where 필터 — _RELAY_DESCRIPTIONS 같은 sem-키 룰 조회용.
# 첫 문서의 documents 본문 반환. 없으면 None.
# ────────────────────────────────────────────────────────────────────
def get_rule_by_id(rule_id: str) -> Optional[str]:
    if not rule_id:
        return None
    try:
        from agri_ai_core.src.chroma.collections import domain_rule_collection
        from agri_ai_core.src.chroma.operations import get_documents
        coll = domain_rule_collection()
        if not coll:
            return None
        result = get_documents(
            coll, where={'rule_id': rule_id}, limit=1,
            include=['documents', 'metadatas'],
        )
        if not isinstance(result, dict):
            return None
        docs = result.get('documents') or []
        if docs and docs[0]:
            return docs[0]
        return None
    except Exception as e:
        logger.warning(f"[PromptRegistry] get_rule_by_id({rule_id}) 실패: {e}")
        return None


# ────────────────────────────────────────────────────────────────────
# ChromaDB prompt_chunk 컬렉션 metadata.chunk_id 정확 매치 단건 조회.
# 대화 모드(query_handler) 의 ANALYZER/VALIDATOR/ANSWER 프롬프트 본문을
# 정확 read 로 가져옴. 의미 검색 X — id 매치만.
# ────────────────────────────────────────────────────────────────────
def get_chunk_by_id(chunk_id: str) -> Optional[str]:
    if not chunk_id:
        return None
    try:
        from agri_ai_core.src.chroma.collections import prompt_chunk_collection
        from agri_ai_core.src.chroma.operations import get_documents
        coll = prompt_chunk_collection()
        if not coll:
            return None
        result = get_documents(
            coll, where={'chunk_id': chunk_id}, limit=1,
            include=['documents', 'metadatas'],
        )
        if not isinstance(result, dict):
            return None
        docs = result.get('documents') or []
        if docs and docs[0]:
            return docs[0]
        return None
    except Exception as e:
        logger.warning(f"[PromptRegistry] get_chunk_by_id({chunk_id}) 실패: {e}")
        return None


# ────────────────────────────────────────────────────────────────────
# 캐시 강제 무효화 — 관리자가 DB row 직접 수정한 직후 즉시 반영용.
# ────────────────────────────────────────────────────────────────────
def clear_cache() -> None:
    with _LOCK:
        _BLOCK_CACHE.clear()
        _TOOLS_CACHE['value'] = None
        _TOOLS_CACHE['updt_dttm'] = None
        _CTRL_BLOCK_CACHE.clear()


# ────────────────────────────────────────────────────────────────────
# control_prompt_m 블록 본문 조회 + placeholder 치환.
# updt_dttm 비교 캐시 invalidate (기존 get_block 동일 패턴).
# DB 미존재/비활성 시 None 반환.
# ────────────────────────────────────────────────────────────────────
def get_control_block(block_id: str, **kwargs) -> Optional[str]:
    if not block_id:
        return None

    current_updt = None
    try:
        from agri_ai_core.src.postgresql.reader import read_control_prompt_updt
        current_updt = read_control_prompt_updt(block_id)
    except Exception as ee:
        logger.debug(f"[PromptRegistry] control block updt 조회 실패 (캐시 fallback): {ee}")

    with _LOCK:
        cached = _CTRL_BLOCK_CACHE.get(block_id)
        if cached is not None and current_updt is not None and cached.get('updt_dttm') == current_updt:
            body = cached['value']
        else:
            body = _load_control_block_from_db(block_id)
            if body is None and cached is not None and cached.get('value') is not None:
                body = cached['value']
            else:
                _CTRL_BLOCK_CACHE[block_id] = {'value': body, 'updt_dttm': current_updt}

    if body is None:
        return None
    if not kwargs:
        return body
    out = body
    for k, v in kwargs.items():
        out = out.replace('${' + k + '}', str(v))
    return out


# ════════════════════════════════════════════════════════════════════
# 내부 helper — DB / Chroma 직접 호출은 본 영역에 한정 (단방향)
# ════════════════════════════════════════════════════════════════════


def _load_control_block_from_db(block_id: str) -> Optional[str]:
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT body_text FROM control_prompt_m "
                    "WHERE block_id=%s AND active_yn='Y' LIMIT 1",
                    (block_id,),
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            try: db._putconn(conn)
            except Exception: pass
    except Exception as e:
        logger.warning(f"[PromptRegistry] _load_control_block_from_db({block_id}) 실패: {e}")
        return None

# ────────────────────────────────────────────────────────────────────
# prompt_block_m 단건 조회. 활성(active_yn='Y') 행의 body_text 반환.
# ────────────────────────────────────────────────────────────────────
def _load_block_from_db(block_id: str) -> Optional[str]:
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT body_text FROM prompt_block_m "
                    "WHERE block_id=%s AND active_yn='Y' LIMIT 1",
                    (block_id,),
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            try: db._putconn(conn)
            except Exception: pass
    except Exception as e:
        logger.warning(f"[PromptRegistry] _load_block_from_db({block_id}) 실패: {e}")
        return None


# ────────────────────────────────────────────────────────────────────
# tool_definition_m 활성 행 전체 조회. priority 오름차순.
# ────────────────────────────────────────────────────────────────────
def _load_tools_from_db(active_only: bool = True) -> List[Dict[str, Any]]:
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            return []
        try:
            with conn.cursor() as cur:
                where = "WHERE active_yn='Y'" if active_only else ""
                cur.execute(
                    f"SELECT tool_id, schema_json, description, category, priority "
                    f"FROM tool_definition_m {where} ORDER BY priority ASC, tool_id ASC"
                )
                rows = cur.fetchall()
                return [
                    {
                        'tool_id': r[0],
                        'schema_json': r[1],
                        'description': r[2],
                        'category': r[3],
                        'priority': r[4],
                    }
                    for r in rows
                ]
        finally:
            try: db._putconn(conn)
            except Exception: pass
    except Exception as e:
        logger.warning(f"[PromptRegistry] _load_tools_from_db 실패: {e}")
        return []


# ────────────────────────────────────────────────────────────────────
# ChromaDB query 결과를 [{id_field, content, metadata, distance}, ...] 로 평탄화.
# 결과가 비어 있거나 키가 없으면 빈 list 반환 (호출자 안전).
# ────────────────────────────────────────────────────────────────────
def _flatten_chroma_result(result: Any, id_field: str) -> List[Dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    ids = (result.get('ids') or [[]])[0]
    docs = (result.get('documents') or [[]])[0]
    metas = (result.get('metadatas') or [[]])[0]
    dists = (result.get('distances') or [[]])[0]
    out = []
    for i, _id in enumerate(ids):
        out.append({
            id_field: _id,
            'content': docs[i] if i < len(docs) else '',
            'metadata': metas[i] if i < len(metas) else {},
            'distance': dists[i] if i < len(dists) else None,
        })
    return out
