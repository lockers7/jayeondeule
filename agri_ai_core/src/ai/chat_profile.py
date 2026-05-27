# ══════════════════════════════════════════════════════════════════════════════
# 농장주 대화 프로필 RAG — 관심사·선호 지속 저장/회상
#
# 목적: 잡담(casual_chat) 발화를 VectorDB(document_collection,
# data_type='farmer_interest')에 임베딩 저장하고, 이후 잡담 시 현재 화제와
# 유사한 과거 관심사를 회상해 페르소나 프롬프트에 주입 — 대화가 쌓일수록
# 농장주 맞춤 말벗이 된다.
#
# 원칙: 전부 best-effort — 어떤 예외도 채팅 흐름을 깨지 않는다.
#       제어(농장제어) 코드와 완전 무관한 대화 모드 전용 모듈.
#
# 파일 시작 함수 목록:
#   remember_async  : 잡담 발화를 백그라운드 스레드로 저장 (즉시 반환)
#   _remember       : 실제 저장 (임베딩 포함, 200자 절단, 짧은 발화 제외)
#   recall          : 현재 발화와 유사한 과거 관심사 top-N 회상 → 프롬프트 블록
# ══════════════════════════════════════════════════════════════════════════════
import time
import uuid
import threading
from typing import Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_MIN_LEN = 6          # "안녕", "ㅎㅎ" 같은 무정보 발화는 저장 안 함
_MAX_LEN = 200
_RECALL_TOP_K = 3
_RECALL_MAX_DIST = 0.75   # 거리 상한 — 무관한 회상 주입 방지


def remember_async(user_query: str, farm_id: Optional[str] = None):
    try:
        threading.Thread(target=_remember, args=(user_query, farm_id), daemon=True).start()
    except Exception:
        pass


def _remember(user_query: str, farm_id: Optional[str] = None):
    try:
        text = (user_query or "").strip()
        if len(text) < _MIN_LEN:
            return
        from agri_ai_core.src.chroma.collections import document_collection
        from agri_ai_core.src.chroma.operations import add_document
        from agri_ai_core.src.ai.embedder import embed_text

        emb = embed_text(text[:_MAX_LEN])
        meta = {
            "data_type": "farmer_interest",
            "source": "casual_chat",
            "created_at": time.strftime("%Y-%m-%d %H:%M"),
        }
        if farm_id:
            meta["farm_id"] = str(farm_id)
        doc_id = f"interest_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        add_document(document_collection(), doc_id, text[:_MAX_LEN], meta, embedding=emb)
        logger.info(f"[대화프로필] 관심사 저장: \"{text[:40]}\"")
    except Exception as e:
        logger.debug(f"[대화프로필] 저장 실패(무시): {e}")


def recall(user_query: str, top_k: int = _RECALL_TOP_K) -> str:
    """현재 발화와 유사한 과거 관심사 → 페르소나 주입용 블록 문자열 ('' 가능)."""
    try:
        from agri_ai_core.src.chroma.collections import document_collection
        from agri_ai_core.src.chroma.operations import query_documents
        from agri_ai_core.src.ai.embedder import embed_text

        emb = embed_text((user_query or "")[:_MAX_LEN])
        if not emb:
            return ""
        res = query_documents(
            document_collection(), query_embeddings=[emb], n_results=top_k,
            where={"data_type": {"$eq": "farmer_interest"}},
            include=["documents", "metadatas", "distances"],
        )
        # query_documents 는 이미 평탄화된 리스트를 반환 (추가 [0] 벗기기 금지)
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        dists = res.get("distances") or []
        lines = []
        for doc, m, dist in zip(docs, metas, dists):
            if dist is not None and dist > _RECALL_MAX_DIST:
                continue
            when = (m or {}).get("created_at", "")
            lines.append(f"- ({when}) \"{doc}\"")
        if not lines:
            return ""
        return ("[농장주님과의 지난 대화에서 파악된 관심사·근황 — 자연스럽게 이어가되 "
                "티내며 나열하지 말 것]\n" + "\n".join(lines))
    except Exception as e:
        logger.debug(f"[대화프로필] 회상 실패(무시): {e}")
        return ""
