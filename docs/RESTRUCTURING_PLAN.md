# AgriAI Core 리팩토링 구현 계획서

## 목표
현재 45+ 파일, 12+ 폴더 구조를 간소화하여 유지보수성 향상

## 최종 구조
```
agri_ai_core/
├── config.py              # settings + constants + mappers 통합 (~800줄)
├── .env                   # 환경변수 (현재 위치 유지)
├── startup.py             # 초기화/종료 (유지)
├── run_scheduler.py       # 백그라운드 서비스 (유지)
└── src/
    ├── ui/                # Streamlit UI (5개 파일로 축소)
    ├── postgresql/        # PostgreSQL (3개 파일)
    ├── chroma/            # ChromaDB (3개 파일)
    ├── logs.py            # 로깅 (1개 파일로 통합)
    ├── control/           # 릴레이/스케줄러 제어 (4개 파일)
    ├── ai/
    │   ├── llm.py         # LLM 클라이언트 + 쿼리핸들러 (1개 파일)
    │   ├── rag/           # RAG 파이프라인 (3-4개 파일)
    │   └── learning.py    # 학습/분석 (1개 파일)
    └── utils/             # 유틸리티 (3-4개 파일)
```

## 단계별 실행 계획

---

### Phase 0: 준비 및 백업 (5분)
**목적:** 현재 코드 보존 및 테스트 환경 준비

**작업:**
1. 현재 브랜치 상태 확인 및 GitHub 백업
   ```bash
   git add -A
   git commit -m "Backup before restructuring: current working state"
   git push origin safe-cleanup-20250307
   ```

2. 새 작업 브랜치 생성
   ```bash
   git checkout -b refactor-structure-20250307
   ```

3. 테스트 스크립트 작성 (간단한 import 테스트)
   ```python
   # test_imports.py
   try:
       from agri_ai_core.startup import initialize_app, shutdown_app
       from agri_ai_core.database.postgres.connection import db_session
       from agri_ai_core.llm.qa.query_handler import query_llm_unified
       print("✓ All critical imports successful")
   except Exception as e:
       print(f"✗ Import failed: {e}")
   ```

**결과물:**
- GitHub 백업 완료
- 새 브랜치 생성
- 테스트 스크립트 준비

---

### Phase 1: 순환 의존성 해결 (10분)
**목적:** 리팩토링 전 순환 import 문제 제거

**문제:**
- `database/chromadb/client.py` ↔ `database/chromadb/operations.py`
- client.py가 operations.py의 `_sanitize_for_json()` import
- operations.py가 client.py의 `CHROMA_API_BASE`, `get_collection()` import

**해결 방법:**
1. 새 파일 생성: `database/chromadb/utils.py`
2. `_sanitize_for_json()`, `prepare_metadata_for_chroma()`, `restore_metadata_from_chroma()` 이동
3. 상수 `CHROMA_API_BASE`, `TENANT`, `DATABASE` → `database/chromadb/config.py`로 이동
4. 양쪽 파일의 import 수정

**작업 순서:**
```
1. database/chromadb/config.py 생성 (상수 이동)
2. database/chromadb/utils.py 생성 (유틸 함수 이동)
3. operations.py 수정 (utils.py에서 import)
4. client.py 수정 (config.py, utils.py에서 import)
5. 테스트 실행
6. git commit -m "Fix chromadb circular dependency"
```

**테스트:**
```python
from agri_ai_core.database.chromadb.client import heartbeat
from agri_ai_core.database.chromadb.operations import add_document
print("✓ No circular import")
```

---

### Phase 2: 새 폴더 구조 생성 (5분)
**목적:** 빈 src/ 폴더 및 하위 구조 생성

**작업:**
```bash
mkdir -p agri_ai_core/src/{ui,postgresql,chroma,ai/rag,control,utils}
touch agri_ai_core/src/__init__.py
touch agri_ai_core/src/ui/__init__.py
touch agri_ai_core/src/postgresql/__init__.py
touch agri_ai_core/src/chroma/__init__.py
touch agri_ai_core/src/ai/__init__.py
touch agri_ai_core/src/ai/rag/__init__.py
touch agri_ai_core/src/control/__init__.py
touch agri_ai_core/src/utils/__init__.py
```

**결과물:**
- src/ 폴더 트리 준비 완료
- 각 폴더에 __init__.py 생성

---

### Phase 3: config.py 통합 생성 (20분)
**목적:** settings.py + constants.py + mappers.py → config.py

**파일 구조:**
```python
# agri_ai_core/config.py (~800줄)

# Part 1: Settings (원래 settings.py 내용)
from dataclasses import dataclass
from functools import lru_cache
# ... settings 관련 17개 dataclass

# Part 2: Constants (원래 constants.py 내용)
CHROMA_EMBEDDING_DIM = 1024
# ... 187개 상수

# Part 3: Mappers (원래 mappers.py 내용)
SENSOR_MAPPING = {...}
RELAY_MAPPING = {...}
# ... 매핑 딕셔너리

# Part 4: Exports
__all__ = [
    "settings", "get_settings",
    "CHROMA_EMBEDDING_DIM", "SENSOR_MAPPING", ...
]
```

**작업 순서:**
1. `agri_ai_core/config.py` 생성
2. `shared_modules/config/settings.py` 내용 복사 → Part 1
3. `shared_modules/common/constants.py` 내용 복사 → Part 2
4. `shared_modules/common/mappers.py` 내용 복사 → Part 3
5. Import 경로 내부 수정 (상호참조 해결)
6. `__all__` 리스트 작성
7. 테스트

**테스트:**
```python
from agri_ai_core.config import settings, SENSOR_MAPPING, get_relay_name
print(f"✓ Config merged: {settings.model_name}")
```

**커밋:**
```bash
git add agri_ai_core/config.py
git commit -m "Create unified config.py (settings + constants + mappers)"
```

---

### Phase 4: logs.py 통합 생성 (10분)
**목적:** log_config.py + log_handlers.py → logs.py

**작업:**
1. `agri_ai_core/src/logs.py` 생성
2. `log_utils/log_config.py` 상수 복사
3. `log_utils/log_handlers.py` 함수 복사
4. Import 수정 (`agri_ai_core.config` 사용)
5. 테스트

**테스트:**
```python
from agri_ai_core.src.logs import setup_logger
logger = setup_logger(__name__)
logger.info("✓ Logger working")
```

**커밋:**
```bash
git add agri_ai_core/src/logs.py
git commit -m "Create unified logs.py"
```

---

### Phase 5: PostgreSQL 모듈 이동 (15분)
**목적:** database/postgres/* + data_ingestion/postgres_reader.py → src/postgresql/

**최종 구조:**
```
src/postgresql/
├── __init__.py
├── connection.py   # 원래 database/postgres/connection.py
├── queries.py      # 원래 database/postgres/queries.py
└── reader.py       # 원래 data_ingestion/postgres_reader.py
```

**작업 순서:**
1. 파일 복사 (이동 아님, 아직)
   ```bash
   cp agri_ai_core/database/postgres/connection.py agri_ai_core/src/postgresql/connection.py
   cp agri_ai_core/database/postgres/queries.py agri_ai_core/src/postgresql/queries.py
   cp agri_ai_core/data_ingestion/postgres_reader.py agri_ai_core/src/postgresql/reader.py
   ```

2. 각 파일 내부 import 수정
   - `agri_ai_core.log_utils.log_handlers` → `agri_ai_core.src.logs`
   - `agri_ai_core.shared_modules.config.settings` → `agri_ai_core.config`
   - `agri_ai_core.database.postgres.*` → `agri_ai_core.src.postgresql.*`

3. `src/postgresql/__init__.py` 작성
   ```python
   from agri_ai_core.src.postgresql.connection import db_session, DatabaseHandler
   from agri_ai_core.src.postgresql.reader import read_units_data, read_crops_data
   __all__ = ["db_session", "DatabaseHandler", "read_units_data", ...]
   ```

4. 테스트
   ```python
   from agri_ai_core.src.postgresql import db_session
   with db_session() as db:
       result = db.fetch_one("SELECT 1 as test")
   print(f"✓ PostgreSQL module: {result}")
   ```

5. 커밋
   ```bash
   git add agri_ai_core/src/postgresql/
   git commit -m "Migrate PostgreSQL module to src/postgresql/"
   ```

---

### Phase 6: ChromaDB 모듈 통합 (25분)
**목적:** database/chromadb/* + data_pipeline/chroma_loader.py → src/chroma/

**최종 구조:**
```
src/chroma/
├── __init__.py
├── client.py       # 원래 database/chromadb/client.py (순환 의존성 해결됨)
├── operations.py   # 원래 operations.py + 원래 collections.py 통합
└── loader.py       # 원래 data_pipeline/chroma_loader.py
```

**작업 순서:**
1. 파일 복사
   ```bash
   cp agri_ai_core/database/chromadb/client.py agri_ai_core/src/chroma/client.py
   cp agri_ai_core/database/chromadb/operations.py agri_ai_core/src/chroma/operations.py
   cp agri_ai_core/data_pipeline/chroma_loader.py agri_ai_core/src/chroma/loader.py
   ```

2. `collections.py` 내용을 `operations.py`에 통합
   - `get_collection_name()` 함수들을 operations.py 상단에 추가

3. Import 수정
   - `agri_ai_core.log_utils.log_handlers` → `agri_ai_core.src.logs`
   - `agri_ai_core.shared_modules.config.settings` → `agri_ai_core.config`
   - `agri_ai_core.database.chromadb.*` → `agri_ai_core.src.chroma.*`

4. `src/chroma/__init__.py` 작성

5. 테스트
   ```python
   from agri_ai_core.src.chroma import heartbeat, get_collection
   status = heartbeat()
   print(f"✓ ChromaDB module: {status}")
   ```

6. 커밋
   ```bash
   git add agri_ai_core/src/chroma/
   git commit -m "Migrate and consolidate ChromaDB module to src/chroma/"
   ```

---

### Phase 7: Utils 모듈 통합 (15분)
**목적:** shared_modules/common/* + shared_modules/utils/* → src/utils/

**최종 구조:**
```
src/utils/
├── __init__.py
├── validators.py   # 원래 shared_modules/common/validators.py
├── conversion.py   # 원래 shared_modules/utils/conversion.py + date_utils.py
├── exceptions.py   # 원래 shared_modules/exceptions/custom_exceptions.py
└── schemas.py      # 원래 data_ingestion/schemas/* 통합
```

**작업 순서:**
1. 파일 복사 및 통합
2. Import 수정
3. `src/utils/__init__.py` 작성
4. 테스트
5. 커밋

---

### Phase 8: Control 모듈 이동 (15분)
**목적:** control/* → src/control/

**최종 구조:**
```
src/control/
├── __init__.py
├── relay.py        # relay_controller.py + relay_manager.py + schedule_control.py 통합
└── scheduler.py    # task_scheduler.py
```

**작업 순서:**
1. 파일 복사 및 통합
2. Import 수정
3. 테스트
4. 커밋

---

### Phase 9: AI 모듈 통합 (45분) - 가장 복잡
**목적:** llm/*, learning/*, data_pipeline/* → src/ai/

**최종 구조:**
```
src/ai/
├── __init__.py
├── llm.py          # llm/core/llm_client.py + llm/qa/query_handler.py +
│                   # llm/routing/query_classifier.py 통합
├── rag/
│   ├── __init__.py
│   ├── embedder.py     # data_pipeline/vectorization/embedder.py
│   ├── chunker.py      # data_pipeline/vectorization/chunker.py
│   ├── processor.py    # document_processor.py + data_processor.py 통합
│   └── loader.py       # json_loader.py
└── learning.py     # model_trainer.py + data_analyzer.py + qa_generator.py 통합
```

**작업 순서:**
1. llm.py 생성 (3개 파일 통합)
   - `llm/core/llm_client.py` → LLM 클라이언트 부분
   - `llm/qa/query_handler.py` → 쿼리 핸들러 부분
   - `llm/routing/query_classifier.py` → 분류기 부분
   - context_collector.py, response_generator.py는 query_handler에 인라인 통합

2. rag/ 폴더 구성

3. learning.py 생성 (3개 파일 통합)

4. Import 수정 (매우 많음)

5. 테스트
   ```python
   from agri_ai_core.src.ai.llm import get_llm_response, query_llm_unified
   from agri_ai_core.src.ai.rag import embed_text
   from agri_ai_core.src.ai.learning import verify_chroma_connection
   print("✓ AI modules working")
   ```

6. 커밋
   ```bash
   git add agri_ai_core/src/ai/
   git commit -m "Consolidate AI modules (LLM, RAG, Learning)"
   ```

---

### Phase 10: UI 모듈 정리 (20분)
**목적:** ui/streamlit_app/* → src/ui/

**최종 구조:**
```
src/ui/
├── __init__.py
├── main.py         # 원래 main.py
├── chat.py         # chat_handler.py + session_manager.py 통합
├── sidebar.py      # 원래 sidebar.py
├── handlers.py     # file_handler.py + location_handler.py 통합
└── styles.py       # 원래 styles.py
```

**작업 순서:**
1. 파일 복사 및 통합
2. Import 수정
   - `agri_ai_core.llm.qa.query_handler` → `agri_ai_core.src.ai.llm`
   - `agri_ai_core.database.postgres.*` → `agri_ai_core.src.postgresql.*`
3. 테스트 (Streamlit 앱 실행)
4. 커밋

---

### Phase 11: 진입점 업데이트 (10분)
**목적:** startup.py, run_scheduler.py import 경로 수정

**작업:**
1. `agri_ai_core/startup.py` 수정
   ```python
   # OLD
   from agri_ai_core.log_utils.log_handlers import setup_logger
   from agri_ai_core.database.chromadb.client import heartbeat
   from agri_ai_core.control.scheduler.task_scheduler import setup_scheduler
   from agri_ai_core.control.relay.schedule_control import control_all_schedules

   # NEW
   from agri_ai_core.src.logs import setup_logger
   from agri_ai_core.src.chroma import heartbeat
   from agri_ai_core.src.control import setup_scheduler
   from agri_ai_core.src.control import control_all_schedules
   ```

2. `agri_ai_core/run_scheduler.py` 수정

3. `agri_ai_core/__init__.py` 수정

4. 테스트
   ```bash
   python -m agri_ai_core.run_scheduler &
   sleep 5
   ps aux | grep run_scheduler
   kill %1
   ```

5. 커밋
   ```bash
   git add agri_ai_core/startup.py agri_ai_core/run_scheduler.py agri_ai_core/__init__.py
   git commit -m "Update entry points to use new src/ structure"
   ```

---

### Phase 12: setup 스크립트 업데이트 (5분)
**목적:** setup/run_services.sh의 경로가 올바른지 확인

**작업:**
1. `setup/run_services.sh` 확인
   - `python -m agri_ai_core.run_scheduler` (모듈로 실행하므로 경로 변경 불필요)
   - `streamlit run` 경로 확인 필요

2. 필요시 수정

3. 커밋

---

### Phase 13: 전체 테스트 (30분)
**목적:** 모든 기능 작동 확인

**테스트 항목:**
1. **Import 테스트**
   ```python
   # test_all_imports.py
   from agri_ai_core.config import settings, SENSOR_MAPPING
   from agri_ai_core.src.logs import setup_logger
   from agri_ai_core.src.postgresql import db_session
   from agri_ai_core.src.chroma import heartbeat
   from agri_ai_core.src.ai.llm import get_llm_response
   from agri_ai_core.src.ai.rag import embed_text
   from agri_ai_core.src.control import setup_scheduler
   print("✓ All imports successful")
   ```

2. **DB 연결 테스트**
   ```python
   from agri_ai_core.src.postgresql import db_session
   from agri_ai_core.src.chroma import heartbeat

   with db_session() as db:
       result = db.fetch_one("SELECT NOW()")
       print(f"✓ PostgreSQL: {result}")

   status = heartbeat()
   print(f"✓ ChromaDB: {status}")
   ```

3. **스케줄러 테스트**
   ```bash
   python -m agri_ai_core.run_scheduler &
   sleep 10
   tail -20 logs/scheduler.log
   kill %1
   ```

4. **Streamlit UI 테스트**
   ```bash
   streamlit run agri_ai_core/src/ui/main.py &
   sleep 10
   curl http://localhost:8501
   kill %1
   ```

5. **LLM 쿼리 테스트**
   ```python
   from agri_ai_core.src.ai.llm import get_llm_response
   response = get_llm_response("안녕하세요", max_tokens=50)
   print(f"✓ LLM response: {response[:100]}")
   ```

**오류 발생 시:**
- 로그 확인 (`logs/*.log`)
- Import 경로 재점검
- 필요시 수정 후 재테스트

---

### Phase 14: 구 파일 삭제 (10분)
**목적:** 중복 파일 제거

**삭제 대상:**
```bash
rm -rf agri_ai_core/shared_modules/
rm -rf agri_ai_core/database/
rm -rf agri_ai_core/data_ingestion/
rm -rf agri_ai_core/data_pipeline/
rm -rf agri_ai_core/control/
rm -rf agri_ai_core/llm/
rm -rf agri_ai_core/learning/
rm -rf agri_ai_core/ui/
rm -rf agri_ai_core/log_utils/
```

**작업:**
1. 테스트 통과 확인 후에만 삭제
2. 삭제 전 백업 커밋
   ```bash
   git add -A
   git commit -m "Backup before deleting old structure"
   ```
3. 삭제 실행
4. 재테스트 (import 확인)
5. 커밋
   ```bash
   git add -A
   git commit -m "Remove old directory structure"
   ```

---

### Phase 15: 최종 정리 및 문서화 (20분)
**목적:** 프로젝트 완결

**작업:**
1. `agri_ai_core/src/__init__.py` 최종 정리
   ```python
   # src/__init__.py
   from agri_ai_core.config import settings, get_settings
   from agri_ai_core.src.logs import setup_logger
   from agri_ai_core.src.postgresql import db_session
   from agri_ai_core.src.chroma import heartbeat

   __all__ = ["settings", "get_settings", "setup_logger", "db_session", "heartbeat"]
   ```

2. README 업데이트 (구조 변경 사항 문서화)

3. CHANGELOG 작성

4. 최종 커밋
   ```bash
   git add -A
   git commit -m "Complete restructuring: 45+ files → ~25 files"
   git push origin refactor-structure-20250307
   ```

5. PR 생성 (GitHub에서)
   - base: safe-cleanup-20250307
   - head: refactor-structure-20250307
   - 제목: "Major refactoring: Simplify project structure"
   - 설명: 변경 사항, 파일 수 감소, 테스트 결과

---

## 예상 파일 감소

**Before:** 45+ .py 파일
**After:** ~25 .py 파일

**구체적 감소:**
- shared_modules/ (8개) → config.py (1개)
- log_utils/ (2개) → logs.py (1개)
- database/ (5개) → src/postgresql/ (3개) + src/chroma/ (3개)
- data_ingestion/ (4개) → src/postgresql/reader.py (1개) + src/utils/schemas.py (1개)
- data_pipeline/ (7개) → src/ai/rag/ (4개)
- llm/ (6개) → src/ai/llm.py (1개)
- learning/ (3개) → src/ai/learning.py (1개)
- control/ (4개) → src/control/ (2개)
- ui/ (7개) → src/ui/ (5개)

**Total:** 45 → 25 (약 44% 감소)

---

## 리스크 관리

### 높은 리스크
1. **Import 경로 대량 변경** → 단계별 테스트로 완화
2. **파일 통합 시 함수명 충돌** → 미리 확인 및 rename

### 중간 리스크
1. **순환 의존성 재발** → Phase 1에서 근본 해결
2. **Streamlit 캐시 이슈** → 캐시 클리어 명령 실행

### 낮은 리스크
1. **Git conflict** → 단독 브랜치 작업으로 회피
2. **성능 저하** → 파일 수 감소로 오히려 개선 예상

---

## 예상 소요 시간
- **Phase 0-2:** 20분 (준비)
- **Phase 3-8:** 110분 (모듈 통합)
- **Phase 9:** 45분 (AI 모듈 - 가장 복잡)
- **Phase 10-12:** 35분 (UI 및 진입점)
- **Phase 13:** 30분 (테스트)
- **Phase 14-15:** 30분 (정리)

**총 예상 시간:** 약 4-5시간 (천천히 정확하게 진행)

---

## 체크리스트

### Phase 0-2 (준비)
- [ ] GitHub 백업 완료
- [ ] 새 브랜치 생성
- [ ] 순환 의존성 해결
- [ ] 빈 src/ 구조 생성

### Phase 3-8 (기본 모듈)
- [ ] config.py 통합 완료
- [ ] logs.py 통합 완료
- [ ] PostgreSQL 모듈 이동
- [ ] ChromaDB 모듈 통합
- [ ] Utils 모듈 통합
- [ ] Control 모듈 이동

### Phase 9-10 (AI 및 UI)
- [ ] AI 모듈 통합 완료
- [ ] UI 모듈 정리

### Phase 11-15 (완결)
- [ ] 진입점 업데이트
- [ ] 전체 테스트 통과
- [ ] 구 파일 삭제
- [ ] 문서화 완료
- [ ] GitHub PR 생성

---

## 성공 기준
1. 모든 import 테스트 통과
2. DB 연결 (PostgreSQL + ChromaDB) 정상
3. 스케줄러 백그라운드 실행 정상
4. Streamlit UI 정상 작동
5. LLM 쿼리 응답 정상
6. 파일 수 45개 → 25개 이하 달성
