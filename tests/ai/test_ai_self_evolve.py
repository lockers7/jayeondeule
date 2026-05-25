# ════════════════════════════════════════════════════════════════════
# [프롬프트 자동화 · Phase 5] ai_self_evolve 단위 테스트.
# DB / HTTP 호출 없이 mock 으로 검증 — CI 안전.
#
# 파일 시작 함수 목록:
#   test_format_candidate_rule_basic   : 정상 후보 1건 → 룰 텍스트 합성 형식 검증
#   test_format_candidate_rule_no_reasons : sample_reasons 비어있을 때 fallback
#   test_format_candidate_rule_title_30 : title 이 30자 이내로 trim 되는지
#   test_analyze_decision_patterns_db_fail : DB 연결 실패 시 빈 리스트 반환
#   test_analyze_decision_patterns_mock : DB cursor mock 으로 정상 흐름 검증
#   test_register_approved_rule_missing : title/content 누락 시 실패 반환
#   test_register_approved_rule_success : upsert 성공 시 rule_id 반환 + 캐시 무효화
#   test_register_approved_rule_upsert_fail : upsert 실패 시 success=False
# ════════════════════════════════════════════════════════════════════
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, '/workspace/jayeondeule')

from agri_ai_core.src.control.ai_self_evolve import (
    analyze_decision_patterns, format_candidate_rule, register_approved_rule,
)


# ────────────────────────────────────────────────────────────────────
# 정상 후보 1건이 title/content/category/frequency 4 키를 가진 dict 로 반환되는지.
# ────────────────────────────────────────────────────────────────────
def test_format_candidate_rule_basic():
    cand = {
        'circulation': '내부순환', 'water_heater': True, 'fog_occurs': True,
        'frequency': 100,
        'sample_reasons': ['저온비상 가열', '저온+고습 가열', '저온비상 다시 가열'],
    }
    result = format_candidate_rule(cand)
    assert set(result.keys()) == {'title', 'content', 'category', 'frequency'}
    assert '내부순환' in result['title']
    assert 'ON' in result['title']
    assert result['frequency'] == 100
    assert '100회' in result['content']
    assert '저온비상' in result['content']
    assert result['category'] == '운영노하우'


# ────────────────────────────────────────────────────────────────────
# sample_reasons 가 비어있어도 KeyError 없이 fallback 텍스트 생성.
# ────────────────────────────────────────────────────────────────────
def test_format_candidate_rule_no_reasons():
    cand = {
        'circulation': '배기순환', 'water_heater': False, 'fog_occurs': False,
        'frequency': 50, 'sample_reasons': [],
    }
    result = format_candidate_rule(cand)
    assert '배기순환' in result['title']
    assert 'OFF' in result['title']
    assert '50회' in result['content']
    assert '대표 사유 표본' not in result['content']


# ────────────────────────────────────────────────────────────────────
# title 길이가 정확히 30자 이하인지 (UI 표시 제약 준수).
# ────────────────────────────────────────────────────────────────────
def test_format_candidate_rule_title_30():
    cand = {
        'circulation': '아주매우긴순환모드이름' * 3,
        'water_heater': True, 'fog_occurs': True, 'frequency': 1, 'sample_reasons': [],
    }
    result = format_candidate_rule(cand)
    assert len(result['title']) <= 30


# ────────────────────────────────────────────────────────────────────
# DB 연결 실패 시 (db._getconn 이 None 반환) 빈 리스트 반환 — 호출자 안전.
# ────────────────────────────────────────────────────────────────────
def test_analyze_decision_patterns_db_fail():
    with patch('agri_ai_core.src.postgresql.connection.db') as mock_db:
        mock_db._getconn.return_value = None
        result = analyze_decision_patterns(farm_id=1)
        assert result == []


# ────────────────────────────────────────────────────────────────────
# 정상 mock cursor 흐름 — 2 패턴 반환 시 dict 형식이 정확한지.
# ────────────────────────────────────────────────────────────────────
def test_analyze_decision_patterns_mock():
    fake_rows = [
        ('change', '내부순환', True, True, 200, ['저온비상 가열', '저온+고습']),
        ('change', '배기순환', False, False, 100, ['고습 배기']),
    ]
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = fake_rows
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch('agri_ai_core.src.postgresql.connection.db') as mock_db:
        mock_db._getconn.return_value = mock_conn
        mock_db._putconn = MagicMock()
        result = analyze_decision_patterns(farm_id=1, days=7, min_freq=10)

    assert len(result) == 2
    assert result[0]['action'] == 'change'
    assert result[0]['circulation'] == '내부순환'
    assert result[0]['water_heater'] is True
    assert result[0]['fog_occurs'] is True
    assert result[0]['frequency'] == 200
    assert result[0]['sample_reasons'] == ['저온비상 가열', '저온+고습']
    assert result[1]['circulation'] == '배기순환'
    assert result[1]['frequency'] == 100


# ────────────────────────────────────────────────────────────────────
# title 또는 content 가 비어있을 때 즉시 실패 — ChromaDB 호출 없이 차단.
# ────────────────────────────────────────────────────────────────────
def test_register_approved_rule_missing():
    r1 = register_approved_rule(title='', content='abc')
    r2 = register_approved_rule(title='abc', content='')
    assert r1['success'] is False
    assert r2['success'] is False
    assert '누락' in r1['error']


# ────────────────────────────────────────────────────────────────────
# upsert 성공 시 rule_id 반환 + prompt_registry 캐시 무효화 호출 검증.
# rule_id 자동 생성 (learned_*) 패턴도 확인.
# ────────────────────────────────────────────────────────────────────
def test_register_approved_rule_success():
    fake_upsert = MagicMock(return_value={'success': True, 'count': 1})
    fake_clear = MagicMock()
    with patch('agri_ai_core.src.chroma.collections.domain_rule_collection',
               return_value='domain_rule'), \
         patch('agri_ai_core.src.chroma.operations.upsert_documents_with_embedding',
               fake_upsert), \
         patch('agri_ai_core.src.prompt_registry.clear_cache', fake_clear):
        result = register_approved_rule(
            title='내부순환 + 수온히터 ON',
            content='최근 7일간 100회 반복',
            farm_id=1, house_id=99,
        )
    assert result['success'] is True
    assert result['rule_id'].startswith('learned_')
    fake_upsert.assert_called_once()
    args, _ = fake_upsert.call_args
    assert args[0] == 'domain_rule'
    docs = args[1]
    assert len(docs) == 1
    assert docs[0]['doc_id'] == result['rule_id']
    assert docs[0]['metadata']['farm_id'] == 1
    assert docs[0]['metadata']['house_id'] == 99
    assert docs[0]['metadata']['source'] == 'self_evolve'
    fake_clear.assert_called_once()


# ────────────────────────────────────────────────────────────────────
# upsert 실패 시 success=False + error 메시지 전달.
# ────────────────────────────────────────────────────────────────────
def test_register_approved_rule_upsert_fail():
    fake_upsert = MagicMock(return_value={'error': '컬렉션 ID 조회 실패'})
    with patch('agri_ai_core.src.chroma.collections.domain_rule_collection',
               return_value='domain_rule'), \
         patch('agri_ai_core.src.chroma.operations.upsert_documents_with_embedding',
               fake_upsert):
        result = register_approved_rule(
            title='t', content='c', rule_id='custom_rule_1',
        )
    assert result['success'] is False
    assert 'error' in result
