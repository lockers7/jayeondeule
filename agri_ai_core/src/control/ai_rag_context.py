# ══════════════════════════════════════════════════════════════════════════════
# AI 환경제어 — RAG 컨텍스트 모듈 (M2)
# [2026-04-28 신규] growth_rag_processor 가 매일 적재하는 farm_knowledge 컬렉션에서
# 현재 상황(센서/생육단계)과 유사한 과거 운영 사례를 1~2건 검색해 LLM 에게 제공.
#
# 호출 룰:
#   • control_ai_environment(ai_control.py) 에서만 import.
#   • 동급 control 모듈 import 금지.
#   • 본 모듈은 chroma.collections / chroma.operations / ai.embedder 만 의존.
#   • 검색 실패는 빈 문자열 반환 — chroma 가 비활성/네트워크 단절이어도 LLM 흐름 보존.
# --->
# query_similar_periods: 현재 상황 임베딩 → farm_knowledge 컬렉션 유사도 검색
# format_rag_block:      검색 결과를 user prompt 한 블록 텍스트로 변환
# ══════════════════════════════════════════════════════════════════════════════
from typing import Any, Dict, List

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)


_RAG_TOP_K = 2
_RAG_DOC_PREVIEW_CHARS = 220


# ────────────────────────────────────────────────────────────────────
# 현재 상황(센서값+생육단계)을 한국어 한 문장으로 압축 — 임베딩 입력 텍스트.
# ────────────────────────────────────────────────────────────────────
def _build_query_text(sensor: Dict[str, Any], growth_stage: str) -> str:
    bits = [f"생육단계 {growth_stage or '생육기'}"]
    for key, label, unit in [
        ('indoor_temperature', '내부온도', '℃'),
        ('indoor_humidity',    '내부습도', '%'),
        ('co2',                'CO2',     'ppm'),
        ('outdoor_temperature','외부온도', '℃'),
        ('water_temperature',  '수온',    '℃'),
    ]:
        v = sensor.get(key) if sensor else None
        if v is not None:
            bits.append(f"{label} {v}{unit}")
    return ", ".join(bits)


# ────────────────────────────────────────────────────────────────────
# farm_knowledge 컬렉션에서 유사 시기 RAG 문서 상위 N건 반환.
# 실패 시 [] — 호출 측이 섹션 생략.
# ────────────────────────────────────────────────────────────────────
def query_similar_periods(farm_id, house_id, sensor: Dict[str, Any],
                          growth_stage: str = "생육기",
                          top_k: int = _RAG_TOP_K) -> List[Dict[str, Any]]:
    try:
        from agri_ai_core.src.ai.embedder import embed_text
        from agri_ai_core.src.chroma.collections import farm_knowledge_collection
        from agri_ai_core.src.chroma.operations import query_documents

        collection_name = farm_knowledge_collection()
        if not collection_name:
            logger.info("[AI-RAG] farm_knowledge 컬렉션 미설정 — 검색 스킵")
            return []

        query_text = _build_query_text(sensor, growth_stage)
        logger.info(
            f"[AI-RAG] 유사시기 검색 시작 farm={farm_id} house={house_id} "
            f"top_k={top_k} query=\"{query_text[:60]}...\""
        )
        embedding = embed_text(query_text)
        if not embedding:
            logger.info("[AI-RAG] 임베딩 생성 실패 — 검색 스킵")
            return []

        # 동일 재배사 사례에 한정 (다른 농장/재배사의 RAG 문서 혼입 방지)
        where = {
            "$and": [
                {"farm_id": str(farm_id)},
                {"house_id": str(house_id)},
                {"data_type": "growth_rag"},
            ]
        }
        result = query_documents(
            collection_name,
            query_embeddings=[embedding],
            n_results=int(top_k),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        if not result:
            return []

        docs_outer = result.get("documents") or []
        metas_outer = result.get("metadatas") or []
        dists_outer = result.get("distances") or []
        docs = docs_outer[0] if docs_outer else []
        metas = metas_outer[0] if metas_outer else []
        dists = dists_outer[0] if dists_outer else []

        out = []
        for i, doc in enumerate(docs):
            out.append({
                "document": doc or "",
                "metadata": metas[i] if i < len(metas) else {},
                "distance": dists[i] if i < len(dists) else None,
            })
        if out:
            best = out[0].get('distance')
            logger.info(
                f"[AI-RAG] 검색 완료 farm={farm_id} house={house_id} → {len(out)}건 "
                f"(top distance={best:.3f})" if isinstance(best, (int, float))
                else f"[AI-RAG] 검색 완료 farm={farm_id} house={house_id} → {len(out)}건"
            )
        else:
            logger.info(f"[AI-RAG] 검색 결과 0건 farm={farm_id} house={house_id}")
        return out
    except Exception as e:
        logger.warning(f"[AI-RAG] 유사 시기 검색 실패 farm={farm_id} house={house_id}: {e}")
        return []


# ────────────────────────────────────────────────────────────────────
# 유사 시기 검색 결과 list → user prompt 한 블록 텍스트. 빈 결과면 "".
# ────────────────────────────────────────────────────────────────────
def format_rag_block(items: List[Dict[str, Any]]) -> str:
    if not items:
        return ""

    lines = [f"[유사 시기 RAG 사례 — 동일 재배사 과거 {len(items)}건]"]
    for idx, it in enumerate(items, 1):
        meta = it.get("metadata") or {}
        rec = meta.get("record_datetime", "")[:10] if meta.get("record_datetime") else "-"
        season = meta.get("season", "-")
        crop = meta.get("crop_level", "-")
        anomaly = meta.get("anomaly_flag", "-")
        quality = meta.get("quality_label") or "-"
        avg_t = meta.get("avg_indoor_temp")
        avg_h = meta.get("avg_indoor_humidity")
        avg_c = meta.get("avg_co2")
        dist = it.get("distance")
        dist_s = f"{dist:.3f}" if isinstance(dist, (int, float)) else "-"
        head = (
            f"  ({idx}) {rec} · {season} · {crop} · 평균 {avg_t}℃/{avg_h}%/{avg_c}ppm · "
            f"품질={quality} · 이상={anomaly} · 거리={dist_s}"
        )
        lines.append(head)
        doc_preview = (it.get("document") or "").strip().replace("\n", " ")
        if doc_preview:
            preview = doc_preview[:_RAG_DOC_PREVIEW_CHARS]
            if len(doc_preview) > _RAG_DOC_PREVIEW_CHARS:
                preview += "…"
            lines.append(f"      └ {preview}")
    return "\n".join(lines)
