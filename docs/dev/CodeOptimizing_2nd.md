# agri_ai_core 코드 최적화 2차 계획서 (IMP-01 ~ IMP-13)

> 작성일: 2026-03-01
> 대상: `agri_ai_core/` 카테고리별 심층 분석 기반 개선
> 원칙: 기존 기능 100% 보존, OPT-01~27과 중복 없음
> 이전 계획서: `docs/dev/CodeOptimizing.md` (OPT-01~27, 1차 최적화 완료)

---

## 1. 분석 배경

이전 OPT-01~27 (27개 항목, ~550줄 절감)의 순수 코드 품질 개선이 완료된 상태입니다.
이번 2차 최적화는 **시스템구성 문서의 14개 카테고리**를 기준으로 전체 소스코드를 심층 분석하여
발견된 **안정성, 성능, 보안** 이슈를 해결합니다.

### 분석 범위

| 카테고리 | 분석 파일 | 발견 이슈 |
|---------|----------|----------|
| API통신 (FastAPI) | api/app.py, voice_router.py, models.py | 미들웨어 메모리, CORS |
| LLM대화 | ai/query_handler_simple.py, llm_client.py, conversation_store.py | 상수 불일치 |
| RAG시스템 | ai/rag/embedder.py, reranker.py, chunker.py | 캐시 경합, 헬스체크 TTL, 재시도 |
| 음성처리 | voice/stt_engine.py, tts_engine.py | 모델 로드 race condition, 로그 |
| 릴레이제어 | control/manual_control.py, ai_control.py | N+1 쿼리 (보류) |
| DB관리 | postgresql/connection.py, reader.py | 커넥션 누수 |
| 파일처리 | ai/file_processor.py | 인코딩 감지 |
| 스케줄관리 | control/task_scheduler.py | 매직넘버 |
| 로그관리 | logs.py | 파일 권한 |
| 통계수집 | ai/stats_collector.py | 이미 최적화됨 (변경 불필요) |

---

## 2. 우선순위별 최적화 항목

### 2.1 Phase 1: P0 안정성 (IMP-01 ~ IMP-04) — 4개 파일

#### IMP-01: STT 모델 싱글톤 race condition 방지
- **파일**: `src/voice/stt_engine.py` (20~26줄)
- **문제**: `_get_model()`에 lock이 없어 동시 요청 시 WhisperModel 중복 로드 가능
- **개선**: `threading.Lock()` + double-check locking 패턴 적용
- **변경량**: +4줄
- **변경 코드**:
```python
# 현재
_model = None

def _get_model():
    global _model
    if _model is None:
        _model = WhisperModel("small", device="cpu", compute_type="int8")
    return _model

# 개선
import threading

_model = None
_model_lock = threading.Lock()

def _get_model():
    global _model
    if _model is None:                    # 1차 체크 (빠른 경로)
        with _model_lock:
            if _model is None:            # 2차 체크 (double-check locking)
                _model = WhisperModel("small", device="cpu", compute_type="int8")
    return _model
```

#### IMP-02: 임베딩 캐시 OrderedDict 경합 조건 해결
- **파일**: `src/ai/rag/embedder.py` (32~33줄, 190~195줄, 274~277줄)
- **문제**: `_embedding_cache`(OrderedDict)에 ThreadPoolExecutor 스레드와 메인 스레드가 동시 접근 시 내부 연결 리스트 훼손 가능
- **개선**: `_cache_lock = threading.Lock()` 추가, 캐시 읽기/쓰기를 `with _cache_lock:` 으로 보호
- **변경량**: +6줄
- **변경 코드**:
```python
# 현재
_embedding_cache = OrderedDict()
_EMBEDDING_CACHE_MAX = 256

# 개선 (선언부)
import threading

_embedding_cache = OrderedDict()
_EMBEDDING_CACHE_MAX = 256
_cache_lock = threading.Lock()

# 개선 (캐시 읽기 — embed_text 내부)
with _cache_lock:
    cached = _embedding_cache.get(cache_key)
    if cached is not None:
        _embedding_cache.move_to_end(cache_key)
        return cached

# 개선 (캐시 쓰기 — embed_text 내부)
with _cache_lock:
    _embedding_cache[cache_key] = embedding
    _embedding_cache.move_to_end(cache_key)
    if len(_embedding_cache) > _EMBEDDING_CACHE_MAX:
        _embedding_cache.popitem(last=False)
```

#### IMP-03: JsonLoggingMiddleware 스트리밍 응답 메모리 적재 방지
- **파일**: `api/app.py` (133~142줄)
- **문제**: 바이패스 경로 외의 응답도 전체 body를 메모리에 적재 — `StreamingResponse`가 실수로 통과하면 위험
- **개선**: `isinstance(response, StreamingResponse)` 체크 추가하여 스트리밍은 body 읽기 없이 통과
- **변경량**: +7줄
- **변경 코드**:
```python
# 현재 (133~142줄)
response = await call_next(request)

response_body_bytes = b""
async for chunk in response.body_iterator:
    ...

# 개선
response = await call_next(request)

# StreamingResponse인 경우 body 읽지 않고 통과
if isinstance(response, StreamingResponse):
    elapsed = round(time.time() - start_time, 3)
    api_logger.info(
        "[API 응답] %s %s (status=%d, %.3fs, streaming)",
        request.method, request.url.path, response.status_code, elapsed,
    )
    return response

# 일반 응답만 body 읽기 (기존 코드 유지)
response_body_bytes = b""
async for chunk in response.body_iterator:
    ...
```

#### IMP-04: 커넥션 풀 반환 실패 시 연결 누수 방지
- **파일**: `src/postgresql/connection.py` (174~179줄)
- **문제**: `_putconn()`에서 `putconn()` 예외 시 conn이 풀에도 반환되지 않고 `close()`도 안 됨 → DB 연결 누수
- **개선**: except 블록에서 `conn.close()` 명시적 호출 추가
- **변경량**: +4줄
- **변경 코드**:
```python
# 현재
def _putconn(self, conn):
    if self._pool is not None and conn is not None:
        try:
            self._pool.putconn(conn)
        except Exception as e:
            self.logger.debug(f"풀에 커넥션 반환 중 오류: {e}")

# 개선
def _putconn(self, conn):
    if self._pool is not None and conn is not None:
        try:
            self._pool.putconn(conn)
        except Exception as e:
            self.logger.debug(f"풀에 커넥션 반환 중 오류: {e}")
            try:
                conn.close()
            except Exception:
                pass
```

---

### 2.2 Phase 2: P1 성능 (IMP-05 ~ IMP-07) — 2개 파일

#### IMP-05: 대화 검색 하드코딩 5건 → 상수 사용
- **파일**: `src/ai/query_handler_simple.py` (215줄)
- **문제**: `lines[:5]`로 하드코딩 — 환경변수 `HYBRID_RELATED_RESULTS`(83줄)와 불일치
- **개선**: `lines[:5]` → `lines[:_HYBRID_RELATED_RESULTS]`
- **변경량**: 0줄 (인라인 수정)
- **변경 코드**:
```python
# 현재 (215줄)
return "\n".join(lines[:5])

# 개선
return "\n".join(lines[:_HYBRID_RELATED_RESULTS])
```

#### IMP-06: 임베딩 헬스체크 TTL 60초 → 300초
- **파일**: `src/ai/rag/embedder.py` (47줄)
- **문제**: Ollama 정상 상태에서도 1분마다 HTTP 2회(`/api/version` + `/api/tags`) 불필요한 헬스체크 발생. 장애 시에는 `_disable_embedding()` → 5분 후 자동 재활성화 경로가 이미 있으므로 TTL 증가는 안전함
- **개선**: `_HEALTH_TTL = 60` → `_HEALTH_TTL = 300`
- **변경량**: 0줄 (값 변경만)

#### IMP-07: Reranker 재시도 시 temperature 조정
- **파일**: `src/ai/rag/reranker.py` (105~149줄)
- **문제**: 파싱 실패 재시도 시 `temperature=0`이 동일 → LLM이 같은 (파싱 불가) 응답을 반복 출력
- **개선**: 재시도 시 `payload["options"]["temperature"] = 0.3`으로 변경하여 다른 응답 유도
- **변경량**: +2줄
- **변경 코드**:
```python
# 현재 (148~149줄)
scores = []
continue

# 개선
scores = []
if attempt < RERANK_MAX_RETRIES:
    payload["options"]["temperature"] = 0.3
continue
```

---

### 2.3 Phase 3: P2 보안 + P3 코드 품질 (IMP-08 ~ IMP-13) — 5개 파일

#### IMP-08: CORS 허용 메서드/헤더 명시화
- **파일**: `api/app.py` (246~247줄)
- **문제**: `allow_methods=["*"]`, `allow_headers=["*"]` — 불필요한 HTTP 메서드(DELETE, PATCH 등)/헤더 허용
- **개선**: 실제 사용하는 메서드/헤더만 명시적 허용
- **변경량**: 0줄 (값 변경만)
- **검증**: 현재 라우트 분석 결과 GET/POST만 사용
- **변경 코드**:
```python
# 현재
allow_methods=["*"],
allow_headers=["*"],

# 개선
allow_methods=["GET", "POST", "OPTIONS"],
allow_headers=["Content-Type", "X-API-Key", "Accept", "Authorization"],
```

#### IMP-09: 로그 파일 권한 0o666 → 0o644
- **파일**: `logs.py` (87줄, 204줄)
- **문제**: `0o666`은 모든 사용자에게 읽기+쓰기 권한 부여 (보안 위험)
- **개선**: `0o644` (소유자 rw, 그룹/기타 r)로 변경 (2곳)
- **변경량**: 0줄 (값 변경만)
- **주의**: `sudo ./agriAiCore`로 root가 실행하므로 0o644로 충분

#### IMP-10: TTS 텍스트 잘림 로그 개선
- **파일**: `src/voice/tts_engine.py` (25~37줄)
- **문제**: 텍스트가 `MAX_TEXT_LENGTH`(2000자) 초과 시 잘리지만, 최종 완료 로그에 잘림 사실이 반영되지 않음
- **개선**: `was_truncated` 플래그 추가, 완료 로그에 `(잘림)` 표시
- **변경량**: +3줄
- **변경 코드**:
```python
# 현재
if len(text) > MAX_TEXT_LENGTH:
    text = text[:MAX_TEXT_LENGTH]
    logger.warning("[TTS] 텍스트 길이 초과, %d자로 잘림", MAX_TEXT_LENGTH)

# ...
logger.info("[TTS] 변환 완료: text_len=%d, mp3_size=%d bytes", len(text), len(mp3_bytes))

# 개선
was_truncated = False
if len(text) > MAX_TEXT_LENGTH:
    text = text[:MAX_TEXT_LENGTH]
    was_truncated = True
    logger.warning("[TTS] 텍스트 길이 초과, %d자로 잘림", MAX_TEXT_LENGTH)

# ...
logger.info("[TTS] 변환 완료: text_len=%d, mp3_size=%d bytes%s",
            len(text), len(mp3_bytes), " (잘림)" if was_truncated else "")
```

#### IMP-11: 텍스트 파일 인코딩 감지 개선 (루프화)
- **파일**: `src/ai/file_processor.py` (94~120줄)
- **문제**: UTF-8 → cp949 폴백만 지원, euc-kr/utf-8-sig/latin-1 미지원, 중복 try-except 코드
- **개선**: 인코딩 목록 루프로 통합 — 중복 코드 제거
- **변경량**: 순감 약 -8줄
- **변경 코드**:
```python
# 현재 (중복 try-except)
def read_text_file(file_path, max_chars=10000):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read(max_chars)
        if len(content) >= max_chars:
            return f"{content}\n\n... (파일이 너무 길어 일부만 표시됩니다)"
        return content
    except UnicodeDecodeError:
        try:
            with open(file_path, 'r', encoding='cp949') as f:
                content = f.read(max_chars)
            if len(content) >= max_chars:
                return f"{content}\n\n... (파일이 너무 길어 일부만 표시됩니다)"
            return content
        except Exception as e:
            ...
    except Exception as e:
        ...

# 개선 (루프화)
_TEXT_ENCODINGS = ("utf-8", "cp949", "euc-kr", "utf-8-sig", "latin-1")

def read_text_file(file_path, max_chars=10000):
    for encoding in _TEXT_ENCODINGS:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read(max_chars)
            if len(content) >= max_chars:
                return f"{content}\n\n... (파일이 너무 길어 일부만 표시됩니다)"
            return content
        except (UnicodeDecodeError, UnicodeError):
            continue

    logger.error(f"텍스트 파일 읽기 오류 ({file_path}): 지원되는 인코딩 없음")
    return "텍스트 파일을 읽을 수 없습니다: 인코딩을 감지할 수 없습니다."
```

#### IMP-12: 청크 upsert count 불일치 경고 추가
- **파일**: `src/ai/rag/chunker.py` (175~177줄)
- **문제**: `batch_result.get("count", len(batch_docs))`에서 부분 실패 감지 불가
- **개선**: `reported_count != len(batch_docs)` 시 warning 로그 추가
- **변경량**: +4줄
- **변경 코드**:
```python
# 현재
if isinstance(batch_result, dict) and batch_result.get("success"):
    success_count = batch_result.get("count", len(batch_docs))
    logger.info(f"[청크저장] 배치 upsert 성공: {success_count}건 (임베딩 포함)")

# 개선
if isinstance(batch_result, dict) and batch_result.get("success"):
    reported_count = batch_result.get("count", len(batch_docs))
    if reported_count != len(batch_docs):
        logger.warning(
            f"[청크저장] 배치 upsert 부분 성공: "
            f"요청={len(batch_docs)}건, 처리={reported_count}건"
        )
    success_count = reported_count
    logger.info(f"[청크저장] 배치 upsert 성공: {success_count}건 (임베딩 포함)")
```

#### IMP-13: 청크 정리 배치 크기 상수화
- **파일**: `src/control/task_scheduler.py` (276줄)
- **문제**: 매직넘버 100이 2곳에 하드코딩
- **개선**: `_CHUNK_DELETE_BATCH_SIZE = 100` 상수 선언 후 참조
- **변경량**: +1줄
- **변경 코드**:
```python
# 현재
for i in range(0, len(delete_ids), 100):
    batch = delete_ids[i:i + 100]

# 개선
_CHUNK_DELETE_BATCH_SIZE = 100

for i in range(0, len(delete_ids), _CHUNK_DELETE_BATCH_SIZE):
    batch = delete_ids[i:i + _CHUNK_DELETE_BATCH_SIZE]
```

---

## 3. 제외 항목 및 사유

| 항목 | 사유 |
|------|------|
| stats_collector.py deque 변환 | 이미 `deque(maxlen=max_recent)` 사용 중 — 변경 불필요 |
| N+1 쿼리 (control_all_manual) | 재배사 2~8개로 과도한 엔지니어링 — 보류 |
| conversation_store.py 정규식 | 실제 검증 결과 정상 동작 (`re.DOTALL` + `.*?` 조합 정상) — 변경 불필요 |

---

## 4. 전체 요약

| Phase | 항목 수 | 파일 수 | 순 변경줄 | 위험도 |
|-------|---------|---------|----------|--------|
| Phase 1 (안정성) | IMP-01~04 | 4 | +21줄 | 낮음 |
| Phase 2 (성능) | IMP-05~07 | 2 | +2줄 | 낮음 |
| Phase 3 (보안/품질) | IMP-08~13 | 5 | +0줄 | 매우 낮음 |
| **합계** | **13개** | **10개** | **약 +23줄** | - |

---

## 5. 작업 순서 및 검증 방법

### 실행 순서
1. Phase 1 (IMP-01~04) → 구문 검증 → 서비스 기동 테스트
2. Phase 2 (IMP-05~07) → 구문 검증 → 서비스 기동 테스트
3. Phase 3 (IMP-08~13) → 구문 검증 → 서비스 기동 테스트

### 검증 방법
각 Phase 완료 후:
1. **구문 검증**: `python -c "import py_compile; py_compile.compile('파일경로')"` — 변경 파일 전체
2. **서비스 기동**: `sudo ./agriAiCore start all` → 전체 서비스 정상 기동 확인
3. **API 응답**: `/health` 엔드포인트 200 확인
4. **Phase별 추가 검증**:
   - Phase 1: 동시 STT 요청 시 모델 중복 로드 없음, DB 커넥션 누수 없음
   - Phase 2: 헬스체크 로그 빈도 감소 확인 (60초→300초), Reranker 파싱 성공률 확인
   - Phase 3: React 프론트엔드 CORS 정상 동작, 다양한 인코딩 파일 업로드 테스트

---

## 6. 주의사항

- 모든 변경은 **기존 기능 100% 보존** 필수
- OPT-01~27 (1차 최적화)과 **중복 없음** 확인 완료
- 함수 시그니처(인자, 반환 타입) 변경 없음
- 외부 모듈에서 import하는 경로 변경 없음
- 새로운 외부 의존성 추가 없음
