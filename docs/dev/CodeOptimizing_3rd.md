# 시스템 통합 최적화 3차 계획서

> 작성일: 2026-03-01
> 대상: 전체 시스템 (agri_ai_core + Spring Boot + Nginx + RaspberryPi)
> 이전 계획서: 1차 `CodeOptimizing.md` (OPT-01~27), 2차 `CodeOptimizing_2nd.md` (IMP-01~13)
> 원칙: 기존 기능 100% 보존, 1·2차와 중복 없음

---

## 1. 분석 방법론 비교

### 1.1 AI 코드 분석 (자동 분석)

| 특성 | 내용 |
|------|------|
| **관점** | Bottom-Up — 소스코드 → 이슈 발견 |
| **범위** | `agri_ai_core/` Python 코드 내부 |
| **강점** | 코드 레벨 버그, 스레드 안전성, 중복 코드 정밀 탐지 |
| **맹점** | 시스템 간 연동, 명세 vs 구현 정합성, 아키텍처 전체상 미반영 |

### 1.2 사용자 시스템 진단 (수동 분석)

| 특성 | 내용 |
|------|------|
| **관점** | Top-Down — 요구 명세 → 구현 Gap 분석 |
| **범위** | 전체 시스템 스택 (Spring Boot, Nginx, FastAPI, RaspberryPi, 프론트엔드) |
| **강점** | 시스템 간 정합성, 운영 정책, 확장 설계 방향 |
| **맹점** | 개별 함수 내부의 미세 버그까지 추적하지 않음 |

### 1.3 차이점 매트릭스

| 구분 | AI만 발견 | 사용자만 발견 | 양쪽 공통 |
|------|-----------|-------------|----------|
| 코드 버그 | 4건 | 0건 | 3건 |
| 시스템 정합성 | 0건 | 8건 | 0건 |
| 성능/아키텍처 | 3건 | 6건 | 2건 |
| 보안 | 1건 | 2건 | 0건 |
| **합계** | **8건** | **16건** | **5건** |

---

## 2. AI만 발견한 항목 (사용자 분석에 없는 것)

| # | 항목 | 파일 | 심각도 |
|---|------|------|--------|
| A1 | `_KOREAN_CHAR_RE` 동일 상수 2회 정의 (801행, 1564행) | llm_client.py | 낮음 |
| A2 | `import re` 모듈 레벨 + 함수 내부 중복 (70행, 2071행) | llm_client.py | 낮음 |
| A3 | `np.random.seed()` 글로벌 시드 — 멀티스레드 난수 간섭 | embedder.py:136 | 중간 |
| A4 | `get_connection()` 컨텍스트 매니저 `finally: pass` — 리소스 미정리 | connection.py:200-208 | 낮음 |
| A5 | `_to_sql_literal()` 수동 SQL 이스케이프 — injection 불완전 차단 | connection.py:77-87 | 중간 |
| A6 | `process_stats_and_optimal_data()` — 타임스탬프 기록만 남은 dead 함수 | data_analyzer.py:511-551 | 낮음 |
| A7 | `_db_query()` vs `_db_fetch()` — 거의 동일한 DB 래퍼 2곳 중복 | reader.py / growth_rag_processor.py | 낮음 |
| A8 | `filter_llm_response()` vs `clean_llm_response()` — 동일 필터 최대 4회 반복 호출 | llm_client.py | 중간 |

---

## 3. 사용자만 발견한 항목 (AI 분석에 없는 것)

| # | 항목 | 범위 | 심각도 |
|---|------|------|--------|
| U1 | Spring Boot 포트 9090 vs 명세 8080 불일치 | Spring Boot / Nginx | 중간 |
| U2 | RBAC `HOUS_MANAGER` 열거형 누락 + JWT authorities 빈 배열 | Spring Boot 보안 | 높음 |
| U3 | 스케줄 명세(통합제어 1분) vs 실제 주기(수동 10초, AI 5분) 불일치 | task_scheduler.py | 중간 |
| U4 | 센서 모니터링 — 시계열 파티셔닝, SSE/WebSocket 전환 검토 | PostgreSQL / API | 중간 |
| U5 | 릴레이 제어 — 상태머신 명시화, sleep 블로킹 제거, 인터락 | control/ | 중간 |
| U6 | LLM 대화 — 도구별 서킷브레이커, 프롬프트 토큰예산, 관측지표 | llm_client.py | 중간 |
| U7 | 음성처리 — 비동기 작업큐, 동일 텍스트 TTS 캐시 | voice/ | 낮음 |
| U8 | 메모/생육기록 — 커서 기반 페이징, 낙관적 락 | Spring Boot | 낮음 |
| U9 | 통계수집 — 인메모리 → 영속 저장, p95/p99 추가 | stats_collector.py | 중간 |
| U10 | 로그관리 — 구조화 JSON + trace_id 통합 | logs.py | 중간 |
| U11 | 시스템서비스 — systemd 의존성 헬스체크, 롤백 정책 | setup/ | 낮음 |
| U12 | RaspberryPi — v1/v2/v3 단일화, 오프라인 버퍼링, ACK 체계 | raspi/ | 중간 |
| U13 | API 계약(OpenAPI) 단일화 — 포트/프리픽스 표준 확정 | 전체 | 중간 |
| U14 | 농장/재배사 ACL 다대다 모델 + 감사이력 | Spring Boot | 중간 |
| U15 | application.properties 비밀번호/JWT secret 평문 저장 | Spring Boot | 높음 |
| U16 | Nginx FastAPI 포트 불일치 (fastapi:8088 vs jayeondeule_web:8002) | Nginx | 중간 |

---

## 4. 양쪽 공통 발견 항목

| # | 항목 | AI 분석 ID | 심각도 |
|---|------|-----------|--------|
| C1 | `str.replace()` 오치환 — 동일 줄 전부 대체 위험 | 1-3 | 높음 |
| C2 | `bare except:` — KeyboardInterrupt/SystemExit 삼킴 | 1-4 | 중간 |
| C3 | dead fallback — 동일 strptime 재호출 (반드시 실패) | 1-5 | 중간 |
| C4 | 파일 업로드 100MB 전체 `read()` 기반 메모리 피크 | U-파일처리 | 높음 |
| C5 | `embedding_dim` 기본값 불일치 (768 vs 1024) | 3-2 | 높음 |

---

## 5. 통합 개선 계획 (카테고리별)

> 이하 각 카테고리별로 **현재 상태**, **발견 이슈 (AI/사용자/공통)**, **개선 방안**을 기술합니다.
> 우선순위: P0(긴급) > P1(중요) > P2(개선) > P3(검토)

---

### 5.1 API통신 REST API

**현재 상태**: FastAPI(:8002) + Spring Boot(:9090) + Nginx 리버스 프록시 동작

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| 문서 확장자 허용 정책 불일치 — API(.md,.json 허용) vs 처리기(미지원) | 검증 확인 | P0 |
| 파일 업로드 100MB 전체 read() 메모리 피크 | 공통 C4 | P1 |
| Nginx FastAPI 포트 불일치 (fastapi:8088 vs jayeondeule_web:8002) | 사용자 U16 | P1 |
| Spring Boot 포트 9090 vs 명세 8080 | 사용자 U1 | P2 |
| API 계약(OpenAPI) 단일화 미완 | 사용자 U13 | P3 |

**개선 방안**:

```
[P0] 확장자 정책 단일화
  현재: app.py ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".pdf", ".xlsx"}
        file_processor.py 실제 처리 = .txt, .csv, .xlsx/.xls, .pdf
  불일치: .md, .json → 업로드 성공하나 "지원하지 않는 파일 형식" 반환
          .xls → 처리 가능하나 업로드 단계에서 차단
  방안A: app.py에서 .md, .json 제거 + .xls 추가
  방안B: file_processor.py에 .md(텍스트), .json(텍스트) 처리 추가 + app.py에 .xls 추가

[P1] 대용량 파일 스트리밍 업로드
  현재: await upload_file.read() → 전체 메모리 적재 후 크기 검증
  방안: SpooledTemporaryFile 또는 청크 단위 읽기로 전환
        크기 초과 시 조기 중단 (전체 읽기 전에 차단)

[P1] Nginx 포트 설정 정리
  현재: setup/system-configs/nginx/fastapi → 8088 프록시 (레거시 추정)
        setup/system-configs/nginx/jayeondeule_web → 8002 프록시 (현행)
  방안: 레거시 설정 파일 정리 또는 용도 문서화

[P2] Spring Boot 포트 명세 일치화
  현재: 모든 설정이 9090으로 일관됨 (동작에 문제 없음)
  방안: 명세 문서를 9090으로 갱신하거나, 운영 정책에 따라 8080으로 변경

[P3] API 계약 표준화
  방안: FastAPI → /ai-api, Spring Boot → /api 프리픽스 확정
        OpenAPI 스펙 자동 생성/검증 도입
```

---

### 5.2 사용자인증/권한관리 (JWT/RBAC)

**현재 상태**: JWT 인증 동작, RBAC 미완성

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| AuthLvel enum에 HOUS_MANAGER 누락 — User.java 주석과 불일치 | 사용자 U2 | P0 |
| JWT authorities 빈 배열 `List.of()` — 역할 기반 접근 제어 미동작 | 사용자 U2 | P0 |
| application.properties에 JWT secret, DB password 평문 저장 | 사용자 U15 | P1 |
| SecurityConfig에서 역할별 URL 분기 없음 (anyRequest().authenticated()만) | 사용자 U2 | P1 |

**개선 방안**:

```
[P0] RBAC 체계 완성
  1. AuthLvel enum에 HOUS_MANAGER(재배사관리자) 추가
  2. JwtAuthFilter에서 UserClaimDTO의 authLvel을 GrantedAuthority로 매핑
     현재: new UsernamePasswordAuthenticationToken(userInfo, null, List.of())
     개선: new UsernamePasswordAuthenticationToken(userInfo, null,
           List.of(new SimpleGrantedAuthority("ROLE_" + userInfo.getAuthLvel())))
  3. SecurityConfig에 역할별 URL 접근 정책 추가
     예: .requestMatchers("/api/admin/**").hasRole("ADMIN")
         .requestMatchers("/api/setting/**").hasAnyRole("ADMIN", "FARM_ADMIN")

[P1] 민감 정보 보호
  현재: application.properties에 평문 저장
    jwt.secret=jayeondeuleWebService:Wkdusmfdp1@
    spring.datasource.password=Wkdusemfdp1@
  방안: 환경변수 참조로 전환
    jwt.secret=${JWT_SECRET}
    spring.datasource.password=${DB_PASSWORD}
```

---

### 5.3 농장/재배사관리

**현재 상태**: CRUD 존재, 사용자-농장 권한은 단일 필드 중심

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| 사용자-농장-재배사 ACL 확장성 제한 | 사용자 U14 | P2 |
| 권한 변경 감사이력 없음 | 사용자 U14 | P3 |

**개선 방안**:

```
[P2] 사용자-농장 ACL 다대다 모델 설계
  현재: 사용자 테이블에 farm_id 단일 필드
  방안: user_farm_permission 중간 테이블 도입
        (user_id, farm_id, permission_level, granted_at, granted_by)

[P3] 감사이력 추가
  방안: 권한 변경 시 audit_log 테이블에 기록
```

---

### 5.4 센서모니터링

**현재 상태**: 최신값 조회 + 이력 다운샘플링(500) + 웹 5초 폴링

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| 시계열 테이블 파티셔닝/인덱스 미적용 | 사용자 U4 | P2 |
| 실시간 구간 SSE/WebSocket 전환 미검토 | 사용자 U4 | P3 |
| 이상치/결측치 보정 파이프라인 없음 | 사용자 U4 | P3 |

**개선 방안**:

```
[P2] 시계열 테이블 최적화
  방안: 월별 파티셔닝(RANGE 파티션) + record_datetime 인덱스
        오래된 파티션 DROP으로 대량 삭제 성능 개선

[P3] 실시간 전환 검토
  현재: 5초 폴링 (프론트엔드 → Spring Boot → PostgreSQL)
  방안: SSE 또는 WebSocket으로 push 기반 전환
        서버 부하 감소, 즉시 반영

[P3] 이상치/결측치 보정
  방안: 센서 데이터 삽입 시 범위 검증 + 보간 로직
```

---

### 5.5 스케줄관리

**현재 상태**: APScheduler 기반, 8개 잡이 `setup_default_jobs`에 분산 정의

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| 명세 주기(통합제어 1분) vs 실제(수동 10초, AI 5분) 불일치 | 사용자 U3 | P1 |
| `schedule_control_func` 파라미터 선언만 있고 미사용 (dead parameter) | 검증 발견 | P1 |
| 스케줄 레지스트리 단일 설정원 부재 | 사용자 U3 | P2 |
| 잡 실패 시 알림 체계 없음 | 사용자 U3 | P3 |

**개선 방안**:

```
[P1] 스케줄 주기 정합화
  현재: 명세 "통합제어 1분" vs 실제 "수동 10초 + AI 5분"
  방안: 명세를 실제 구현에 맞게 갱신하거나,
        운영 요건에 따라 주기 조정

[P1] dead parameter 제거
  현재: setup_default_jobs(schedule_control_func=None) 선언만 있고 본문에서 미사용
  방안: 파라미터 제거 또는 실제 스케줄 제어 잡 등록

[P2] 스케줄 레지스트리
  방안: 모든 잡의 ID/주기/함수를 딕셔너리 설정으로 관리
        환경변수 또는 config로 주기 조정 가능하게 변경

[P3] 실패 알림
  방안: 잡 실행 실패 시 로그 + 카운터 누적, 임계치 초과 시 알림
```

---

### 5.6 RAG학습방법 (VectorDB)

**현재 상태**: 농장/문서/대화/웹 지식 흐름 구현됨

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| `embedding_dim` 기본값 불일치 (embedder.py:768 vs settings/constants:1024) | 공통 C5 | P0 |
| 청크 정리에서 MCP 불필요 경유 — chroma/operations.py 직접 호출 가능 | AI 분석 | P1 |
| 컬렉션별 메타데이터 스키마 표준 미수립 | 사용자 | P2 |
| 업서트 인터페이스 계약 테스트 없음 | 사용자 | P3 |

**개선 방안**:

```
[P0] embedding_dim 기본값 통일
  현재: embedder.py _get_expected_dim() fallback = 768
        settings.py embedding_dim 기본값 = 1024
        constants.py CHROMA_EMBEDDING_DIM = 1024
  위험: settings 로드 실패 시 768차원 더미 임베딩 → ChromaDB 차원 오류
  방안: embedder.py fallback을 1024로 변경
        또는 constants.CHROMA_EMBEDDING_DIM을 직접 참조

[P1] 청크 정리 MCP 의존성 제거
  현재: task_scheduler._chunk_cleanup_job()이 mcp_http_request로 ChromaDB REST 직접 호출
  방안: chroma/operations.py의 기존 delete 함수 활용으로 전환

[P2] 메타데이터 스키마 표준화
  방안: 컬렉션별 필수 메타데이터 필드 정의 문서화
        farm_id, house_id, data_kind, record_datetime 필수 규칙
```

---

### 5.7 릴레이제어

**현재 상태**: 비상/64케이스/2단계 제어/쿨다운/순환모드 로직 존재

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| 제어규칙 상태머신 명시화 필요 (우선순위 충돌 제거) | 사용자 U5 | P2 |
| sleep 기반 블로킹 구간 존재 | 사용자 U5 | P2 |
| 하드웨어 보호 인터락 (최소 ON/OFF 보장) 미흡 | 사용자 U5 | P2 |

**개선 방안**:

```
[P2] 상태머신 명시화
  현재: 비상/AI/수동/스케줄 우선순위가 코드 분기로 암묵 처리
  방안: ControlMode enum + 우선순위 매트릭스 명시 정의
        모드 전환 시 이전 상태 기록, 충돌 감지 로직 추가

[P2] 블로킹 제거
  현재: 릴레이 전환 시 time.sleep() 사용
  방안: APScheduler 이벤트 기반 비동기 처리 또는 최소한의 sleep으로 전환

[P2] 인터락 보호
  방안: 릴레이 ON→OFF 최소 간격 설정 (예: 5초), 짧은 주기 반복 전환 차단
```

---

### 5.8 LLM대화

**현재 상태**: Tool Use, Rerank, 응답필터, SSE, 멀티턴 저장 동작

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| `str.replace()` 오치환 — 동일 텍스트 줄이 여러 곳에 있으면 전부 대체 | 공통 C1 | P0 |
| `filter_llm_response` vs `clean_llm_response` 동일 필터 최대 4회 반복 | AI A8 | P1 |
| `_KOREAN_CHAR_RE` 동일 상수 2회 정의 (801행, 1564행) | AI A1 | P1 |
| `import re` 모듈 레벨 + 함수 내부 중복 | AI A2 | P2 |
| llm_client.py 2400행 — 단일 파일에 5개 관심사 혼재 | 공통 | P3 |
| 도구별 서킷브레이커/타임아웃 미적용 | 사용자 U6 | P3 |
| 프롬프트 토큰예산 관리 없음 | 사용자 U6 | P3 |

**개선 방안**:

```
[P0] str.replace 오치환 수정
  현재: response_text = response_text.replace(line, new_line)
  위험: "온도가 높습니다." 같은 줄이 2회 나오면 둘 다 대체됨
  방안: 줄 단위 리스트 처리로 전환
    lines = response_text.split('\n')
    processed_lines = [process(line) for line in lines]
    response_text = '\n'.join(processed_lines)

[P1] 응답 필터 통합
  현재: filter_llm_response → clean_llm_response → _strip_reasoning_paragraphs
        → _strip_non_korean_reasoning → _force_korean_surface 가 최대 4회 반복
  방안: 단일 파이프라인으로 통합, 1회만 적용
    def process_llm_response(text, is_korean_query):
        text = _remove_think_tags(text)
        text = _remove_reasoning_patterns(text)
        if is_korean_query:
            text = _enforce_korean_surface(text)
        text = _normalize_whitespace(text)
        return text

[P1] 중복 상수 제거
  현재: _KOREAN_CHAR_RE 2회 정의 (801행, 1564행)
  방안: 모듈 상단 1회 정의로 통합

[P3] 모듈 분리 (대규모 리팩터링)
  방안: llm_client.py → 3개 모듈 분리
    - ollama_transport.py (통신 계층, ~300행)
    - response_filter.py (응답 후처리, ~800행)
    - llm_client.py (비즈니스 로직, ~1300행)
  주의: 변경 범위가 크므로 충분한 테스트 후 진행
```

---

### 5.9 음성처리 (STT/TTS)

**현재 상태**: faster-whisper small, edge-tts 경로 구성

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| 비동기 작업큐 없음 — 동시 요청 시 순차 처리 | 사용자 U7 | P3 |
| 동일 텍스트 TTS 캐시 없음 | 사용자 U7 | P3 |
| 음성 길이 제한/분할 정책 미흡 | 사용자 U7 | P3 |

**개선 방안**:

```
[P3] 동일 텍스트 TTS 캐시
  방안: 텍스트 해시 → mp3 파일 캐시, TTL 24시간
        동일 응답 재요청 시 즉시 반환

[P3] 음성 길이 분할
  방안: 긴 텍스트 → 문장 단위 분할 후 결합
        개별 실패 시 부분 결과 반환
```

---

### 5.10 파일처리

**현재 상태**: CSV, Excel, TXT, PDF 지원, 업로드 최대 100MB

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| 확장자 정책 불일치 (API vs 처리기) — 5.1 API통신에서 상세 기술 | 공통 | P0 |
| 100MB 전체 read() 메모리 피크 — 5.1 API통신에서 상세 기술 | 공통 C4 | P1 |

---

### 5.11 통계수집

**현재 상태**: 성공률/처리시간/도구 사용량 인메모리 수집

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| 서비스 재시작 시 통계 초기화됨 | 사용자 U9 | P2 |
| p95/p99 지표 없음 | 사용자 U9 | P3 |

**개선 방안**:

```
[P2] 영속 통계 저장
  방안: 서비스 종료 시 PostgreSQL에 스냅샷 저장
        시작 시 최근 스냅샷 로드하여 누적 통계 유지

[P3] p95/p99 지표 추가
  방안: 응답 시간 히스토그램에서 백분위수 계산
```

---

### 5.12 로그관리

**현재 상태**: 일별 로테이션/정리 작업 존재

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| 서비스 간 trace_id 연계 부족 | 사용자 U10 | P2 |
| 구조화 JSON 로그 미적용 | 사용자 U10 | P3 |

**개선 방안**:

```
[P2] trace_id 통합
  방안: FastAPI 미들웨어에서 X-Request-ID 생성/전파
        모든 로그에 trace_id 포함, LLM/도구/스케줄 로그까지 연계

[P3] 구조화 JSON 로그
  방안: 운영 환경에서 JSON 포맷 로그 옵션 추가
        ELK/Loki 등 로그 수집 시스템 연동 용이
```

---

### 5.13 시스템서비스관리

**현재 상태**: `agriAiCore` → `agriCoreCtrl.sh` 8개 서비스 통합 관리

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| systemd 의존성/헬스체크 기반 기동 미적용 | 사용자 U11 | P3 |
| 장애 시 롤백/재기동 정책 문서 없음 | 사용자 U11 | P3 |

**개선 방안**:

```
[P3] 헬스체크 기반 기동
  방안: 각 서비스 시작 후 health endpoint 확인 후 다음 서비스 기동
        현재 sleep 기반 대기를 능동적 헬스체크로 전환
```

---

### 5.14 RaspberryPi 디바이스계층

**현재 상태**: v1/v2/v3 세 버전 공존, v2만 활성 관리

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| v1/v3 레거시 버전 미정리 | 사용자 U12 | P2 |
| 오프라인 버퍼링 (네트워크 단절 대응) 없음 | 사용자 U12 | P2 |
| 센서 read 실패 재시도/보정 미흡 | 사용자 U12 | P2 |
| 제어명령 ACK/재전송 체계 없음 | 사용자 U12 | P3 |

**개선 방안**:

```
[P2] 버전 단일화
  방안: v2를 운영 표준으로 확정, v1/v3을 archive로 이동
        프로토콜 인터페이스 문서화

[P2] 오프라인 버퍼링
  방안: 서버 연결 실패 시 로컬 SQLite/파일에 센서 데이터 임시 저장
        연결 복구 시 일괄 전송

[P3] ACK 체계
  방안: 제어명령 전송 → 디바이스 ACK 응답 → 미응답 시 재전송 (최대 3회)
```

---

### 5.15 학습 모듈 (코드 버그)

**현재 상태**: model_trainer.py + data_analyzer.py

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| `bare except:` — KeyboardInterrupt/SystemExit 삼킴 | 공통 C2 | P0 |
| dead fallback — 동일 strptime 재호출 | 공통 C3 | P1 |
| `process_stats_and_optimal_data()` 실질 empty 함수 | AI A6 | P2 |

**개선 방안**:

```
[P0] bare except 수정
  현재: model_trainer.py:138
    except:
        continue
  방안:
    except Exception:
        continue

[P1] dead fallback 제거
  현재: data_analyzer.py:209-217
    try:
        if isinstance(unit_datetime, str):
            unit_datetime = datetime.strptime(unit_datetime, "%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            unit_datetime = datetime.strptime(unit_datetime, "%Y-%m-%d %H:%M:%S")  # 동일 호출
        except Exception as e2: ...
  방안:
    if isinstance(unit_datetime, str):
        try:
            unit_datetime = datetime.strptime(unit_datetime, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError) as e:
            logger.debug(f"날짜 변환 오류: {e}")
            continue
    elif not isinstance(unit_datetime, datetime):
        continue

[P2] dead 함수 정리
  현재: process_stats_and_optimal_data() — 타임스탬프 기록만 수행
  방안: 함수명을 update_learning_timestamp()로 변경하거나, 호출부에서 인라인 처리
```

---

### 5.16 DB/인프라 (코드 레벨)

**현재 상태**: PostgreSQL 커넥션 풀, MCP 경유 옵션

**발견 이슈**:

| 이슈 | 출처 | 우선순위 |
|------|------|---------|
| DatabaseHandler 싱글톤 `__new__` race condition | AI 분석 | P1 |
| `np.random.seed()` 글로벌 시드 스레드 간섭 | AI A3 | P1 |
| `_to_sql_literal()` 수동 SQL 이스케이프 불완전 | AI A5 | P2 |
| `_db_query()` vs `_db_fetch()` 거의 동일 래퍼 중복 | AI A7 | P2 |
| `get_connection()` no-op 컨텍스트 매니저 | AI A4 | P3 |
| startup.py 풀 외부 직접 커넥션 생성 | AI 분석 | P3 |

**개선 방안**:

```
[P1] DatabaseHandler 싱글톤 보호
  현재: __new__에 Lock 없음
  방안:
    _instance_lock = threading.Lock()
    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

[P1] numpy 글로벌 시드 제거
  현재: np.random.seed(seed) → 다른 스레드 난수 영향
  방안: rng = np.random.default_rng(seed)
        dummy_embedding = rng.normal(0, 0.1, expected_dim).tolist()

[P2] SQL 이스케이프 개선
  현재: replace("'", "''")만으로 이스케이프
  방안: MCP postgres 경로에서도 parameterized query 지원 검토
        또는 psycopg2.extensions.adapt() 활용

[P2] DB 래퍼 통합
  현재: reader.py _db_query() ≈ growth_rag_processor.py _db_fetch()
  방안: postgresql/queries.py 또는 connection.py에 공통 래퍼 정의
```

---

## 6. 전체 요약

### 우선순위별 항목 수

| 우선순위 | 건수 | 핵심 항목 |
|---------|------|----------|
| **P0 (긴급)** | **5건** | 확장자 불일치, embedding_dim 불일치, str.replace 버그, bare except, RBAC 미완성 |
| **P1 (중요)** | **11건** | 메모리 피크, 필터 중복, 싱글톤 race, 스케줄 정합, 포트 정리, 민감정보 등 |
| **P2 (개선)** | **14건** | 시계열 최적화, 상태머신, 오프라인 버퍼링, 통계 영속화 등 |
| **P3 (검토)** | **12건** | 모듈 분리, 서킷브레이커, JSON 로그, 커서 페이징 등 |
| **합계** | **42건** | - |

### 카테고리별 이슈 분포

| 카테고리 | P0 | P1 | P2 | P3 | 합계 |
|---------|:--:|:--:|:--:|:--:|:----:|
| API통신 | 1 | 2 | 1 | 1 | 5 |
| 인증/권한 | 1 | 2 | 0 | 0 | 3 |
| 농장/재배사 | 0 | 0 | 1 | 1 | 2 |
| 센서모니터링 | 0 | 0 | 1 | 2 | 3 |
| 스케줄관리 | 0 | 2 | 1 | 1 | 4 |
| RAG/VectorDB | 1 | 1 | 1 | 1 | 4 |
| 릴레이제어 | 0 | 0 | 3 | 0 | 3 |
| LLM대화 | 1 | 2 | 1 | 3 | 7 |
| 음성처리 | 0 | 0 | 0 | 3 | 3 |
| 파일처리 | 0 | 0 | 0 | 0 | 0* |
| 통계수집 | 0 | 0 | 1 | 1 | 2 |
| 로그관리 | 0 | 0 | 1 | 1 | 2 |
| 시스템서비스 | 0 | 0 | 0 | 1 | 1 |
| RaspberryPi | 0 | 0 | 2 | 1 | 3 |
| 학습모듈 | 1 | 1 | 1 | 0 | 3 |
| DB/인프라 | 0 | 2 | 2 | 2 | 6 |
| **합계** | **5** | **12** | **16** | **18** | **51** |

*파일처리 이슈는 API통신 카테고리에서 합산

### 분석 관점별 기여도

| 관점 | 발견 비율 | 주요 기여 영역 |
|------|----------|---------------|
| AI 코드 분석 단독 | 8건 (19%) | 코드 버그, 스레드 안전성, 중복 코드 |
| 사용자 시스템 진단 단독 | 16건 (38%) | 시스템 정합성, 아키텍처, 운영 정책 |
| 양쪽 공통 발견 | 5건 (12%) | 고위험 버그, 성능 병목 |
| 통합 검증에서 추가 | 13건 (31%) | 교차 검증으로 구체화된 이슈 |

---

## 7. 권장 실행 순서

```
Phase 1 — P0 긴급 수정 (5건, 즉시)
  ├─ C1: str.replace 오치환 수정 (llm_client.py)
  ├─ C2: bare except → except Exception (model_trainer.py)
  ├─ C5: embedding_dim fallback 1024로 통일 (embedder.py)
  ├─ API 확장자 정책 단일화 (app.py + file_processor.py)
  └─ RBAC enum + JWT authorities 완성 (Spring Boot)

Phase 2 — P1 중요 개선 (11건, 1~2주)
  ├─ 파일 업로드 스트리밍 전환
  ├─ 응답 필터 통합 (filter + clean → 단일 파이프라인)
  ├─ DatabaseHandler 싱글톤 Lock 추가
  ├─ numpy 글로벌 시드 제거
  ├─ 중복 상수/import 정리
  ├─ 스케줄 주기 정합화 + dead parameter 제거
  ├─ 청크 정리 MCP 의존성 제거
  ├─ dead fallback 제거 (data_analyzer.py)
  ├─ Nginx 포트 설정 정리
  └─ 민감정보 환경변수 전환

Phase 3 — P2 점진 개선 (14건, 월 단위)
  ├─ 시계열 테이블 파티셔닝
  ├─ 릴레이 상태머신 명시화
  ├─ RaspberryPi 버전 단일화 + 오프라인 버퍼링
  ├─ 통계 영속 저장
  ├─ trace_id 통합
  ├─ SQL 이스케이프/DB 래퍼 통합
  └─ 기타

Phase 4 — P3 장기 검토 (12건, 분기 단위)
  ├─ llm_client.py 모듈 분리
  ├─ 서킷브레이커, 토큰예산
  ├─ SSE/WebSocket 전환
  ├─ 구조화 JSON 로그
  └─ 기타
```
