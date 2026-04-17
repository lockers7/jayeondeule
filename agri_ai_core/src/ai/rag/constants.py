# ═══════════════════
# RAG 모듈 공통 상수.
# 순환 참조 방지를 위해 이 파일이 단일 원천(single source of truth)이다.
# document_processor, document_enricher는 이 파일을 import한다.
# ═══════════════════

# 문서 유형 한글 라벨 (RAG 모듈 공용 상수)
DOC_TYPE_LABELS = {
    "crop_info": "작물 정보",
    "disease_info": "병해충 정보",
    "general": "일반 문서",
}

__all__ = ["DOC_TYPE_LABELS"]
