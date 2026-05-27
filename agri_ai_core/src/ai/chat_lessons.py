# ══════════════════════════════════════════════════════════════════════════════
# 분석 자가학습 루프 — 질문 처리 교훈 저장/회상
#
# 농장주가 채팅으로 가르치거나("앞으로 ~ 질문에는 ~ 하라") 오답을 정정하면
# 교훈이 VectorDB(document_collection, data_type='analysis_lesson')에 저장되고,
# 이후 모든 질문 분석(ANALYZER)에서 유사 교훈이 자동 회상·주입된다 —
# 성장은 코드 변경 없이 데이터로만 이루어진다.
#
# 원칙: 전부 best-effort — 어떤 예외도 채팅 흐름을 깨지 않는다.
#       농장제어(control) 코드와 완전 무관한 대화 모드 전용 모듈.
#
# 파일 시작 함수 목록:
#   save_lesson            : 교훈 저장 (임베딩 명시 생성, 400자 절단)
#   manage_analysis_lesson : LLM 도구 — register/list/delete(삭제는 관리자 전용)
#   recall_lessons         : 현재 질문과 유사한 교훈 top-N → ANALYZER 주입 블록
#   detect_teaching        : 가르침 발화 여부 판정 (runner 세이프티넷 트리거)
#   detect_correction      : 정정 발화 여부 판정 (자가학습 트리거)
#   learn_correction_async : 직전 질문+정정을 교훈으로 백그라운드 저장
# ══════════════════════════════════════════════════════════════════════════════
import time
import uuid
import threading
from typing import Optional, Dict, Any

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_MIN_LEN = 8
_MAX_LEN = 400
_RECALL_TOP_K = 3
# 교훈은 명령형("~물으면 ~하라"), 질문은 의문형 — 표현 차이가 커서 관심사(0.75)
# 보다 느슨하게 회수한다. 교훈 본문이 자체 적용조건을 담고 있어 ANALYZER 가
# 비해당 교훈을 무시할 수 있으므로 과회수 부작용이 작다.
_RECALL_MAX_DIST = 0.9

# 가르침 발화 표지 — 미래표지 + 질문응대표지 가 모두 있어야 교훈으로 판정.
# 관리자지시("별도 지시까지 꺼둬")나 제어룰 학습("다음부터 20도 넘으면 히터
# 꺼라" → save_domain_knowledge 영역)에는 응대표지가 없어 겹치지 않는다.
_TEACH_FUTURE_MARKERS = ("앞으로", "다음부터", "이제부터", "매번", "때마다", "항상")
_TEACH_QA_MARKERS = ("질문", "물으면", "물어보면", "묻는", "물을 때",
                     "답변", "대답", "답해", "요청하면", "요청에는")

# 정정 발화 표지 — 직전 답변이 의도와 달랐음을 알리는 표현만 (일반 불만/잡담 제외)
_CORRECTION_MARKERS = (
    "그게 아니라", "그것이 아니라", "그런 뜻이 아니", "그 뜻이 아니",
    "내 말은", "내 질문은", "질문의 의도", "질문 의도",
    "다른 대답", "엉뚱한", "동문서답", "잘못 이해", "잘못 알아",
    "다시 물을게", "제대로 답",
)


def save_lesson(lesson_text: str, source: str = "teach",
                farm_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        text = (lesson_text or "").strip()
        if len(text) < _MIN_LEN:
            return {"success": False, "error": f"교훈이 너무 짧습니다({_MIN_LEN}자 이상)."}
        from agri_ai_core.src.chroma.collections import document_collection
        from agri_ai_core.src.chroma.operations import add_document
        from agri_ai_core.src.ai.embedder import embed_text

        text = text[:_MAX_LEN]
        emb = embed_text(text)   # 0벡터 저장(검색 불가) 방지 — 임베딩 명시 필수
        meta = {
            "data_type": "analysis_lesson",
            "source": source,
            "created_at": time.strftime("%Y-%m-%d %H:%M"),
        }
        if farm_id:
            meta["farm_id"] = str(farm_id)
        lesson_id = f"lesson_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        add_document(document_collection(), lesson_id, text, meta, embedding=emb)
        logger.info(f"[분석교훈] 저장({source}): \"{text[:60]}\"")
        return {"success": True, "lesson_id": lesson_id}
    except Exception as e:
        logger.error(f"[분석교훈] 저장 실패: {e}")
        return {"success": False, "error": str(e)}


def manage_analysis_lesson(action: str, lesson_text: str = None,
                           lesson_id: str = None,
                           auth_farm_id: str = None) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.chroma.collections import document_collection
        from agri_ai_core.src.chroma.operations import get_documents, delete_document
        action = (action or "").strip().lower()

        if action == "register":
            r = save_lesson(lesson_text, source="teach", farm_id=auth_farm_id)
            if r.get("success"):
                r["message"] = ("분석 교훈으로 저장했습니다. 지금부터 유사한 질문을 "
                                "분석할 때 자동으로 반영됩니다 (코드 변경 불필요).")
            return r

        if action == "list":
            res = get_documents(document_collection(),
                                where={"data_type": {"$eq": "analysis_lesson"}},
                                include=["documents", "metadatas"], limit=100)
            ids = res.get("ids") or []
            docs = res.get("documents") or []
            metas = res.get("metadatas") or []
            lessons = [{"lesson_id": i, "text": d,
                        "created_at": (m or {}).get("created_at", ""),
                        "source": (m or {}).get("source", "")}
                       for i, d, m in zip(ids, docs, metas)]
            lessons.sort(key=lambda x: x["created_at"], reverse=True)
            return {"success": True, "count": len(lessons), "lessons": lessons}

        if action == "delete":
            if auth_farm_id is not None:
                return {"success": False, "error": "교훈 삭제는 시스템관리자 전용입니다."}
            if not lesson_id or not str(lesson_id).startswith("lesson_"):
                return {"success": False,
                        "error": "lesson_id 는 'lesson_' 으로 시작해야 합니다 (list 로 확인)."}
            delete_document(document_collection(), ids=[lesson_id])
            logger.info(f"[분석교훈] 삭제: {lesson_id}")
            return {"success": True, "message": f"교훈 {lesson_id} 삭제 완료."}

        return {"success": False, "error": f"지원 action: register/list/delete (입력: {action})"}
    except Exception as e:
        logger.error(f"[분석교훈] 관리 실패: {e}")
        return {"success": False, "error": str(e)}


def recall_lessons(user_query: str, top_k: int = _RECALL_TOP_K) -> str:
    try:
        from agri_ai_core.src.chroma.collections import document_collection
        from agri_ai_core.src.chroma.operations import query_documents
        from agri_ai_core.src.ai.embedder import embed_text

        emb = embed_text((user_query or "")[:_MAX_LEN])
        if not emb:
            return ""
        res = query_documents(
            document_collection(), query_embeddings=[emb], n_results=top_k,
            where={"data_type": {"$eq": "analysis_lesson"}},
            include=["documents", "metadatas", "distances"],
        )
        # query_documents 는 이미 평탄화된 리스트 반환 (추가 [0] 벗기기 금지)
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        dists = res.get("distances") or []
        lines = []
        for doc, m, dist in zip(docs, metas, dists):
            if dist is not None and dist > _RECALL_MAX_DIST:
                continue
            when = (m or {}).get("created_at", "")[:10]
            lines.append(f"- ({when}) {doc}")
        if not lines:
            return ""
        return ("[축적된 분석 교훈 — 농장주가 직접 가르친 질문 처리 규칙]\n"
                "아래 교훈 중 이번 질문에 해당하는 것이 있으면 반드시 계획"
                "(question_type/required_data)에 반영하라. 해당 없는 교훈은 무시하라.\n"
                + "\n".join(lines))
    except Exception as e:
        logger.debug(f"[분석교훈] 회상 실패(무시): {e}")
        return ""


def detect_teaching(user_query: str) -> bool:
    q = (user_query or "").strip()
    if len(q) < _MIN_LEN:
        return False
    return (any(m in q for m in _TEACH_FUTURE_MARKERS)
            and any(m in q for m in _TEACH_QA_MARKERS))


def detect_correction(user_query: str) -> bool:
    q = (user_query or "").strip()
    if len(q) < _MIN_LEN:
        return False
    return any(m in q for m in _CORRECTION_MARKERS)


def learn_correction_async(prev_question: str, correction_text: str,
                           farm_id: Optional[str] = None):
    try:
        prev = (prev_question or "").strip()
        corr = (correction_text or "").strip()
        if not prev or not corr:
            return
        lesson = (f"질문 「{prev[:120]}」 에 대한 이전 답변이 농장주 의도와 달랐음. "
                  f"농장주 정정: 「{corr[:200]}」 — 유사한 질문을 분석할 때 이 정정 "
                  f"의도를 반영해 데이터 수집을 계획하라.")
        threading.Thread(target=save_lesson,
                         args=(lesson, "correction", farm_id), daemon=True).start()
    except Exception:
        pass
