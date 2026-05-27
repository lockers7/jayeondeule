# ════════════════════════════════════════════════════════════════════
# 자체 진화 루프 — 의사결정 패턴 분석.
#
# 목적: ai_decision_log 의 정상 결정(action='change') 빈번 패턴을 추출해
#       사용자 학습 룰 후보로 제시. 농장주 승인 시 ChromaDB domain_rule 에 등록.
#
# 분석 단위:
#   (action, circulation, water_heater, fog_occurs) 조합별 빈도 + 최근 reason 표본.
#   emergency/keep 은 제외 — 정상 LLM 판단의 패턴만 학습 대상.
#
# 파일 시작 함수 목록:
#   analyze_decision_patterns : 최근 N일 의사결정 패턴 → 룰 후보 리스트
#   format_candidate_rule     : 후보 1건을 사용자 학습 가능한 룰 텍스트로 합성
#   register_approved_rule    : 승인된 룰 후보를 ChromaDB domain_rule 에 upsert
# ════════════════════════════════════════════════════════════════════
import time
from typing import Any, Dict, List, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# ai_decision_log 최근 days 일의 정상 결정(action='change') 패턴 집계.
# 반환: [{action, circulation, water_heater, fog_occurs, frequency,
#        sample_reasons[:3]}, ...] — frequency 내림차순.
# min_freq 미만 패턴은 제외 (노이즈 차단).
# ────────────────────────────────────────────────────────────────────
def analyze_decision_patterns(farm_id: int, house_id: Optional[int] = None,
                              days: int = 7, min_freq: int = 10,
                              top_k: int = 20) -> List[Dict[str, Any]]:
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            return []
        try:
            with conn.cursor() as cur:
                where_house = "AND house_id = %s" if house_id is not None else ""
                args = [farm_id, days]
                if house_id is not None:
                    args.append(house_id)
                args.append(min_freq)
                args.append(top_k)
                # reason NOT LIKE '[algorithm_fallback]%' — 장애기간
                # 알고리즘 결정이 룰 후보로 승격되어 LLM 지식으로 굳는 것 방지
                # (AI모드 LLM 100% 원칙). 순수 LLM 결정만 학습 후보로 마이닝한다.
                cur.execute(f"""
                    SELECT action, circulation, water_heater, fog_occurs,
                           COUNT(*) AS freq,
                           ARRAY_AGG(DISTINCT LEFT(reason, 80) ORDER BY LEFT(reason, 80)) AS reasons
                    FROM ai_decision_log
                    WHERE farm_id = %s
                      AND decided_at >= NOW() - (%s || ' days')::INTERVAL
                      AND action = 'change'
                      AND reason NOT LIKE '[algorithm_fallback]%%'
                      {where_house}
                    GROUP BY action, circulation, water_heater, fog_occurs
                    HAVING COUNT(*) >= %s
                    ORDER BY freq DESC
                    LIMIT %s
                """, args)
                rows = cur.fetchall()
                return [
                    {
                        'action': r[0],
                        'circulation': r[1],
                        'water_heater': r[2],
                        'fog_occurs': r[3],
                        'frequency': r[4],
                        'sample_reasons': (r[5] or [])[:3],
                    }
                    for r in rows
                ]
        finally:
            try: db._putconn(conn)
            except Exception: pass
    except Exception as e:
        logger.warning(f"[자체진화] 패턴 분석 실패: {e}")
        return []


# ────────────────────────────────────────────────────────────────────
# 후보 1건을 사용자가 가르치는 룰 텍스트로 합성 — domain_rule 등록 시 본문.
# title (30자 내), content (조건+결과+빈도) 형태.
# ────────────────────────────────────────────────────────────────────
def format_candidate_rule(candidate: Dict[str, Any]) -> Dict[str, str]:
    circ = candidate.get('circulation') or '-'
    wh = 'ON' if candidate.get('water_heater') else 'OFF'
    fog = 'ON' if candidate.get('fog_occurs') else 'OFF'
    freq = candidate.get('frequency', 0)
    reasons = candidate.get('sample_reasons') or []

    title = f"{circ} + 수온히터 {wh} + 포그 {fog}"[:30]
    if reasons:
        sample_lines = "\n".join(f"  · {r}" for r in reasons[:3])
        content = (
            f"순환={circ}, 수온히터={wh}, 포그={fog} 결정이 최근 7일간 {freq}회 반복됨.\n"
            f"대표 사유 표본:\n{sample_lines}"
        )
    else:
        content = f"순환={circ}, 수온히터={wh}, 포그={fog} 결정이 최근 7일간 {freq}회 반복됨."

    return {
        'title': title,
        'content': content,
        'category': '운영노하우',
        'frequency': freq,
    }


# ────────────────────────────────────────────────────────────────────
# 승인된 룰을 ChromaDB domain_rule 컬렉션에 upsert.
# rule_id 가 비어있으면 freq+ts 기반 자동 생성. 본문은 title + content.
# 반환: {success, rule_id} 또는 {success=False, error}.
# ────────────────────────────────────────────────────────────────────
def register_approved_rule(title: str, content: str, category: str = '운영노하우',
                           rule_id: Optional[str] = None,
                           farm_id: Optional[int] = None,
                           house_id: Optional[int] = None,
                           source: str = 'self_evolve') -> Dict[str, Any]:
    if not (title and content):
        return {'success': False, 'error': 'title/content 누락'}
    try:
        from agri_ai_core.src.chroma.collections import domain_rule_collection
        from agri_ai_core.src.chroma.operations import upsert_documents_with_embedding

        coll = domain_rule_collection()
        if not coll:
            return {'success': False, 'error': 'domain_rule 컬렉션 미설정'}

        rid = rule_id or f"learned_{int(time.time() * 1000)}"
        text = f"[{title}]\n{content}"
        metadata = {
            'rule_id': rid,
            'category': category,
            'source': source,
            'title': title,
            'created_at': int(time.time()),
        }
        if farm_id is not None:
            metadata['farm_id'] = farm_id
        if house_id is not None:
            metadata['house_id'] = house_id

        result = upsert_documents_with_embedding(coll, [{
            'doc_id': rid,
            'text': text,
            'metadata': metadata,
        }])
        if isinstance(result, dict) and result.get('success'):
            logger.info(f"[자체진화] 룰 등록 완료: rule_id={rid}, title={title!r}")

            # 승인 룰 → 제어 LLM 반영: domain_rule 컬렉션은 제어가 직접 소비하지
            # 않으므로, 제어 도메인RAG(query_domain_knowledge: document_collection /
            # data_type=domain_knowledge)가 즉시 소비하도록 동일 룰을
            # document_collection 에도 upsert. doc_id=rule_{rid} 로 재승인 시
            # 멱등(중복 없이 갱신). 실패 시 승인 전체를 실패로 반환해 관리자가
            # 재시도할 수 있게 한다(제어 반영이 승인의 핵심 목적).
            try:
                from agri_ai_core.src.chroma.collections import document_collection
                doc_coll = document_collection()
                if not doc_coll:
                    return {'success': False,
                            'error': 'document_collection 미설정 — 제어RAG 반영 불가'}
                doc_meta = dict(metadata)
                doc_meta['data_type'] = 'domain_knowledge'
                doc_result = upsert_documents_with_embedding(doc_coll, [{
                    'doc_id': f"rule_{rid}",
                    'text': text,
                    'metadata': doc_meta,
                }])
                if not (isinstance(doc_result, dict) and doc_result.get('success')):
                    logger.warning(f"[자체진화] 제어RAG 반영 실패: {doc_result}")
                    return {'success': False,
                            'error': f'제어RAG 반영 실패(재승인 시 재시도): {doc_result}'}
                logger.info(f"[자체진화] 제어RAG 반영 완료: doc_id=rule_{rid} — 다음 제어 사이클부터 참조")
            except Exception as e:
                logger.warning(f"[자체진화] 제어RAG 반영 예외: {e}")
                return {'success': False, 'error': f'제어RAG 반영 예외: {e}'}

            try:
                from agri_ai_core.src.prompt_registry import clear_cache
                clear_cache()
            except Exception:
                pass
            return {'success': True, 'rule_id': rid}
        return {'success': False, 'error': str(result)}
    except Exception as e:
        logger.warning(f"[자체진화] 룰 등록 실패: {e}")
        return {'success': False, 'error': str(e)}
