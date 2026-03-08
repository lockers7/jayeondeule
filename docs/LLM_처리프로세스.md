## LLM 처리 프로세스
질문(WEB)
  → api(FastAPI: query_llm / query_llm_stream)
    → [전처리] 하이브리드 컨텍스트 로드
        ├─ PostgreSQL → 최근 2턴 대화 로드
        └─ ChromaDB → 관련 과거 대화 벡터 검색
    → [1차 LLM호출(Ollama)] 시스템프롬프트 + 컨텍스트 + 질문 → 도구결정
        ├─ 도구호출 없음 → 자체응답 → [후처리] → api → 답변(WEB)
        └─ 도구호출 있음:
            ├─ ① get_farm_realtime_data → PostgreSQL(센서/릴레이)
            ├─ ② search_farm_knowledge → ChromaDB(document+web_knowledge)
            ├─ ③ search_web → SearXNG → (Naver/Brave fallback) → (MCP fallback)
            │     └─ 상위 URL 본문 자동 읽기
            └─ ④ fetch_url_content → HTTP 본문 읽기
          → [도구결과 정제] 경량화(metadata/중복/잡음 제거)
          → [2차 LLM호출(Ollama)] 질문 + 정제된 도구결과 → 응답생성
    → [후처리] think태그제거 → 존댓말교정 → 출처추가 → 구조화
    → api(FastAPI) → 답변(WEB)
    → [대화저장] PostgreSQL(동기) + ChromaDB(비동기)

## 함수명/파일명 매핑
질문(WEB: ChatInput.jsx)
  → query_llm(app.py) / query_llm_stream(app.py)
    → [전처리] _load_hybrid_context(query_handler_simple.py)
        ├─ get_recent_turns(conversation_store.py) → PostgreSQL
        └─ _search_related_conversations(query_handler_simple.py) → embed_text(embedder.py) → query_documents(operations.py) → ChromaDB
    → [1차 LLM호출] get_llm_response_with_tools(llm_client.py) → _ollama_chat(llm_client.py) → Ollama(qwen3:32b)
        ├─ 도구호출 없음 → _finalize_user_facing_answer(llm_client.py) → [후처리] → 답변
        └─ 도구호출 있음 → execute_tool(tools_executor.py):
            ├─ ① get_farm_realtime_data(tools_executor.py) → read_current_sensor_info(reader.py) → PostgreSQL
            ├─ ② search_farm_knowledge(tools_executor.py) → embed_text(embedder.py) → query_documents(operations.py) → ChromaDB
            ├─ ③ search_web(tools_executor.py) → _search_via_api(tools_executor.py):
            │     ├─ _search_via_searxng(tools_executor.py) → SearXNG
            │     ├─ _search_via_naver_api(tools_executor.py) → Naver API (fallback)
            │     ├─ _search_via_brave_api(tools_executor.py) → Brave API (fallback)
            │     └─ search_web(mcp_client.py) → MCP web-search (fallback)
            │     └─ _auto_fetch_urls(tools_executor.py) → 상위 URL 본문 읽기
            └─ ④ fetch_url_content(tools_executor.py) → HTTP 본문 읽기
          → [도구결과 정제] _refine_tool_result(llm_client.py):
            ├─ _refine_farm_knowledge(llm_client.py) → metadata/중복/잡음 제거
            ├─ _refine_search_web(llm_client.py) → 웹 검색 결과 정제
            └─ _refine_fetch_url(llm_client.py) → URL 본문 정제
          → [2차 LLM호출] _ollama_chat(llm_client.py) → Ollama(qwen3:32b)
    → [후처리] _finalize_user_facing_answer(llm_client.py):
        ├─ _remove_think_tags(llm_client.py) → think태그 제거
        ├─ _needs_honorific_rewrite(llm_client.py) → 존댓말 교정
        ├─ _append_source_urls(llm_client.py) → 출처 추가
        └─ _build_structured_result(llm_client.py) → 응답 구조화
    → query_llm(app.py) → QueryResponse → 답변(WEB: ChatBubble.jsx)
    → [대화저장] _save_conversation_turn_hybrid(query_handler_simple.py):
        ├─ save_turn(conversation_store.py) → PostgreSQL (동기)
        └─ _async_vectordb_save(query_handler_simple.py) → ChromaDB (비동기)


## RAG 처리 프로세스

### A. 문서 업로드 RAG (파일 학습)
파일 업로드(WEB)
  → api(FastAPI: POST /api/v1/rag/perform)
    → 파일 저장 (UUID 접두사 + 확장자 검증 + 크기 제한)
    → 첨부 파일 처리 (파일별 반복)
        ├─ 지원 형식 확인 (txt, md, csv, json, pdf)
        └─ 문서 처리 파이프라인:
            ├─ [1단계] 문서 읽기
            │     ├─ PDF → 페이지별 텍스트 추출
            │     └─ 텍스트 파일 → 인코딩 자동 감지 후 읽기
            ├─ [2단계] 문서 유형 감지
            │     ├─ 작물 키워드 매칭 (빈도 기반: 가장 많이 등장하는 작물)
            │     ├─ 병해충 키워드 매칭
            │     └─ 일반 문서 기본값
            ├─ [3단계] 청크 분할 + 임베딩 + document_collection 저장
            │     ├─ 문단 기반 분할 (1000자/200자 오버랩)
            │     ├─ 각 청크 임베딩 생성 (Ollama 임베딩 모델)
            │     └─ 배치 upsert → ChromaDB(document)
            ├─ [4단계] 구조화 데이터 저장
            │     ├─ farm_knowledge_collection → 생육 최적 집계 데이터
            │     └─ document_collection → 원문 일부(5000자) 저장
            ├─ [5단계] 작물/병해충 문서 → farm_knowledge 이중 저장
            │     ├─ 청크 분할 + 임베딩
            │     └─ farm_knowledge_collection에 별도 저장 (farm_id 기반 검색 지원)
            └─ [6단계] LLM enrichment (백그라운드 스레드)
                  ├─ 문서 요약 생성 (LLM 호출 1회, 300~500자)
                  ├─ QA 쌍 생성 (LLM 호출 1회, 3~5쌍)
                  └─ 요약/QA 임베딩 → farm_knowledge_collection 저장
    → 처리 결과 메시지 반환 → api → WEB

### B. 대화 저장 RAG (대화 학습)
대화 저장 버튼(WEB)
  → api(FastAPI: POST /api/v1/rag/save)
    → 대화 메시지 → 텍스트 변환 (농장명/재배사명/시간 포함)
    → 문서 처리 파이프라인 (위 A와 동일한 llm_document_process 사용)
        ├─ 문서 유형 감지 (대화 내용 기반)
        ├─ 청크 분할 + 임베딩 → document_collection 저장
        ├─ 구조화 데이터 저장
        └─ 작물/병해충 관련 대화 → farm_knowledge 이중 저장
    → 결과 포맷팅 → api → WEB

### C. 생육 RAG (스케줄러 자동 학습)
스케줄러 (12:00, 00:00 자동 실행)
  → 마지막 RAG 처리 시점 조회 (PostgreSQL)
  → 활성 농장-재배사 목록 조회 (PostgreSQL)
  → 농장-재배사별 반복:
      ├─ 새 생육 입력 조회 (마지막 RAG 시점 이후)
      │   └─ 생육 데이터 있음 → 생육 입력별 반복:
      │       ├─ 센서 통계 조회 (이전 시점 ~ 생육 입력 시점)
      │       ├─ 릴레이 가동 비율 조회
      │       ├─ 주야간 분리 센서 통계 조회
      │       ├─ 이동평균 트렌드 조회
      │       ├─ 생육 컨텍스트 구성 (계절, 시간대, 재배일수 등)
      │       ├─ RAG 문서 텍스트 생성 (환경 + 릴레이 + 트렌드 + 생육결과)
      │       ├─ 메타데이터 구성 (이상 상태/품질 라벨 포함)
      │       └─ 임베딩 → farm_knowledge_collection 저장
      └─ 생육 데이터 없음 + 자정 실행 → 일일 보장 RAG:
          ├─ 최근 24시간 센서/릴레이 통계 조회
          ├─ 가상 생육 entry 생성 (양호 추정)
          └─ RAG 문서 + 메타데이터 → 임베딩 → farm_knowledge_collection 저장
  → 처리 시점 갱신 (PostgreSQL)


## 함수명/파일명 매핑

### A. 문서 업로드 RAG
파일 업로드(WEB: FileUpload.jsx)
  → rag_perform(app.py)
    → process_attached_files(document_processor.py)
        └─ llm_document_process(document_processor.py):
            ├─ [1단계] 문서 읽기
            │     ├─ read_pdf_file(file_processor.py) → PyPDF2
            │     └─ open() (텍스트 파일)
            ├─ [2단계] detect_document_type(document_processor.py)
            ├─ [3단계] store_document_with_chunks(chunker.py):
            │     ├─ chunk_document(chunker.py) → 문단/크기 기반 분할
            │     ├─ get_documents(operations.py) → 기존 청크 조회 (중복 방지)
            │     ├─ delete_document(operations.py) → 기존 청크 삭제
            │     ├─ embed_text(embedder.py) → Ollama 임베딩 모델
            │     └─ upsert_documents_with_embedding(operations.py) → ChromaDB(document)
            ├─ [4단계] upsert_collection_data(operations.py) → ChromaDB(farm_knowledge + document)
            ├─ [5단계] _store_crop_chunks_to_farm_knowledge(document_processor.py):
            │     ├─ chunk_document(chunker.py)
            │     ├─ embed_text(embedder.py)
            │     └─ upsert_documents_with_embedding(operations.py) → ChromaDB(farm_knowledge)
            └─ [6단계] _background_enrich(document_processor.py) → 스레드:
                  └─ enrich_document(document_enricher.py):
                      ├─ _generate_summary(document_enricher.py) → _call_llm() → Ollama
                      ├─ _generate_qa_pairs(document_enricher.py) → _call_llm() → Ollama
                      │     └─ _parse_qa_response(document_enricher.py)
                      └─ _store_enriched_data(document_enricher.py):
                            ├─ embed_text(embedder.py)
                            └─ upsert_documents_with_embedding(operations.py) → ChromaDB(farm_knowledge)

### B. 대화 저장 RAG
대화 저장 버튼(WEB: ChatInput.jsx)
  → rag_save(app.py)
    → messages_to_text(document_processor.py) → 대화→텍스트 변환
    → llm_document_process(document_processor.py) → (위 A의 동일 파이프라인)
    → format_rag_save_result(document_processor.py) → 결과 포맷팅

### C. 생육 RAG
스케줄러(scheduler.py)
  → run_growth_rag(growth_rag_processor.py):
      ├─ _get_last_rag_datetime(growth_rag_processor.py) → db_session(connection.py) → PostgreSQL
      ├─ _get_active_farm_houses(growth_rag_processor.py) → db_session(connection.py) → PostgreSQL
      └─ 농장-재배사별:
          ├─ _get_new_crop_entries(growth_rag_processor.py) → PostgreSQL
          │   └─ 생육 입력별:
          │       ├─ _get_sensor_stats(growth_rag_processor.py) → PostgreSQL
          │       ├─ _get_relay_stats(growth_rag_processor.py) → PostgreSQL
          │       ├─ _get_day_night_stats(growth_rag_processor.py) → PostgreSQL
          │       ├─ _get_moving_averages(growth_rag_processor.py) → PostgreSQL
          │       ├─ _build_growth_context(growth_rag_processor.py)
          │       ├─ _build_rag_document(growth_rag_processor.py)
          │       ├─ _build_rag_metadata(growth_rag_processor.py)
          │       └─ _store_growth_rag(growth_rag_processor.py):
          │             ├─ embed_text(embedder.py) → Ollama 임베딩 모델
          │             └─ upsert_documents_with_embedding(operations.py) → ChromaDB(farm_knowledge)
          └─ _ensure_daily_rag(growth_rag_processor.py):
                ├─ _check_today_crops(growth_rag_processor.py) → PostgreSQL
                ├─ _get_sensor_stats / _get_relay_stats / _get_day_night_stats / _get_moving_averages → PostgreSQL
                ├─ _build_growth_context / _build_rag_document / _build_rag_metadata
                └─ _store_growth_rag → embed_text → ChromaDB(farm_knowledge)
