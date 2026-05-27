# ══════════════════════════════════════════════════════════════════════════════
# 파이썬 코딩 수준 지식 시드 — 로컬 AI(gemma3)가 코딩 태스크 시 회상할 방법론.
#
# 농장주 지시(2026-07-23): "Claude 수준의 파이썬 코딩 방법론을 VectorDB 지식으로
#   저장해, 로컬 AI가 그 수준으로 코딩하도록". 각 문서는 320자 이내 핵심(회상 상한)
#   + 전체 700자 이내(저장 상한). system_knowledge(document_collection)에 upsert →
#   ANALYZER 가 코딩 관련 질문에 자동 회상. category='coding'.
#
# 파일 시작 함수 목록:
#   seed_coding_knowledge : 코딩 방법론 문서 일괄 upsert (멱등)
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# (key, text) — 각 text 는 320자 내 핵심 front-load. 주제별로 분리해 코딩 질의에 매칭.
CODING_DOCS = [
    ("pycode_method",
     "[코딩 방법론] ①요구를 정확히 이해(모호하면 가정 대신 확인) ②최소 단위로 변경 "
     "③각 단계 즉시 검증. 증상이 아니라 근본원인을 고친다. 추측 금지 — 모르면 "
     "source_read·db_describe·run_script 로 사실 확인 후 코딩. 변경 전후를 대조해 "
     "기존 기능·출력·필드가 사라지지 않게 한다."),
    ("pycode_defensive",
     "[방어적 코딩] 함수 초입에서 입력 검증(가드절→조기 반환). None·빈값·타입·범위를 "
     "먼저 체크. 예외는 잡아 의미 있는 메시지로 반환하되, 이 프로젝트는 항상 "
     "dict({success, error/…})를 돌려줘 호출 흐름이 죽지 않게 한다(best-effort). "
     "파일·DB·네트워크·외부호출은 늘 실패할 수 있다고 가정하고 감싼다."),
    ("pycode_errors",
     "[오류처리·디버깅] traceback 은 끝줄(실제 예외)부터 읽어 원인 파악 → 최소 재현 → "
     "격리 → 근본 수정. ⛔ 조용한 except: pass 금지 — 최소 logger 로 남겨 원인이 은폐되지 "
     "않게. 에러코드/메시지를 그대로 활용(예: DB 42703 없는컬럼 → 실제 컬럼 확인 후 재시도)."),
    ("pycode_testing",
     "[테스트 규율] 변경하면 반드시 단위테스트 작성·실행. 정상 경로 + 엣지케이스"
     "(0·빈값·음수·경계·중복·None). '된다'고 말하기 전에 실제로 실행해 결과로 확인한다"
     "(pytest -q, 또는 write_script+run_script). 실패하면 stderr 를 읽고 고쳐 재시도."),
    ("pycode_idioms",
     "[파이썬 관용구] 조기 반환으로 중첩을 줄이고, with(컨텍스트매니저)로 파일·커넥션을 "
     "확실히 닫는다. f-string, pathlib, 컴프리헨션, enumerate/zip 활용. "
     "⛔ 가변 기본인자 금지: def f(x=[])/{}→ None 으로 받고 내부에서 생성. "
     "매직넘버는 상수화, 이름은 의도가 드러나게."),
    ("pycode_perf",
     "[성능] 대용량은 한 번에 메모리로 올리지 말고 제너레이터·스트리밍. DB 는 배치로 "
     "(반복 쿼리 N+1 금지), 정규식은 re.compile 재사용, 반복 계산은 캐시. 다만 실시간 "
     "센서·설정값은 캐시 금지(항상 실시간 read — 실시간성 정책). 우선 정확·명료, 그다음 최적화."),
    ("pycode_safety",
     "[안전한 변경] 운영소스(agri_ai_core)는 edit_source 로만(구문검증→테스트→실패 시 "
     "자동 원복). 파괴적 작업 전 백업하고, 파일 쓰기는 tmp 에 쓴 뒤 os.replace 로 원자적 "
     "교체. ⛔ '제거하라'고 명시하지 않은 기존 기능·UI·필드는 지우지 말고 유지·추가만. "
     "안전장치(비상·인터록·관리자지시)는 손대지 않는다."),
    ("pycode_readfirst",
     "[개발 전 필독] 고치기 전에 대상 코드를 source_read 로 정독하고, 호출부·의존성을 "
     "source_search 로 확인한다. 주변의 기존 패턴·명명·주석 밀도를 따라 일관성을 지킨다. "
     "큰 파일은 필요한 범위만 읽는다. 유사 기능이 이미 있으면 재사용 — 중복 구현 금지."),
    ("pycode_algo",
     "[알고리즘·자료구조] 명확·정확을 우선하고, 경계조건(0·1·빈·최대)을 먼저 처리한다. "
     "멤버십은 set, 카운트는 dict/Counter, 정렬·이분탐색 적절히. 복잡한 로직은 작은 순수 "
     "함수로 분해해 테스트 가능하게. 시간·공간 복잡도를 의식하되 조기 최적화는 피한다."),
    ("pycode_convention",
     "[이 프로젝트 코딩 규약] 함수 위에 박스 헤더 주석 + 파일 시작에 함수 목록을 둔다. "
     "docstring·이력주석은 넣지 않는다. 도구/RAG 결과는 dict 로 반환. 신규 채팅도구는 "
     "5중 등록(구현+tools_definition 스펙+tools_executor 디스패치+analyzer 화이트리스트+"
     "tool_definition_m). USE_DB_TOOLS/USE_DB_PROMPTS=1 이라 코드만 고치면 안 되고 DB 동기화."),
]


def seed_coding_knowledge():
    from agri_ai_core.src.ai.system_knowledge import save_system_knowledge
    n = 0
    for key, text in CODING_DOCS:
        if save_system_knowledge(text, category="coding", source="seed", key=key).get("success"):
            n += 1
    logger.info(f"[코딩지식] 시드 완료: {n}/{len(CODING_DOCS)}건")
    return {"success": True, "seeded": n, "total": len(CODING_DOCS)}
