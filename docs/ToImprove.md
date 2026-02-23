# AgriAI Core 시스템 개선 로드맵

> 최종 업데이트: 2026-02-23
> 목적: 대화 자연스러움 개선을 중심으로, 시스템 전반의 업그레이드 방향을 정리한다.

---

## 1. 현재 시스템 구성 요약

### 1.1 하드웨어
| 항목 | 사양 |
|------|------|
| GPU | NVIDIA GeForce RTX 5060 Ti (VRAM 16GB) |
| RAM | 96GB DDR |
| OS | Linux 6.17.0-14-generic |

### 1.2 LLM 모델
| 항목 | 값 | 비고 |
|------|------|------|
| **사용 모델** | `qwen3:latest` (Q4_K_M, 8.2B params) | .env에는 qwen3:32b로 설정되어 있으나, 실제 설치되지 않아 qwen3:latest(8B) 사용 |
| 컨텍스트 길이 | 40,960 tokens | |
| 양자화 | Q4_K_M (4-bit) | |
| VRAM 사용 | ~7.5GB / 16GB | GPU 100% 오프로드 |
| 임베딩 모델 | mxbai-embed-large:latest | 1024차원, 669MB |
| Temperature | 0.7 (대화) / 0.0 (재작성) | |
| num_predict | 5120 tokens | 최대 출력 길이 |
| keep_alive | 1h | 모델 GPU 유지 시간 |

### 1.3 설치된 Ollama 모델
```
qwen3:latest      (8.2B, Q4_K_M, 5.2GB)  ← 현재 사용 중
qwen3:14b         (14B, 9.3GB)            ← 미사용
qwen3-gpu:latest  (8.2B, 5.2GB)           ← 미사용
smollm2:135m      (135M, 270MB)           ← 테스트용
mxbai-embed-large (임베딩 전용, 669MB)
```

### 1.4 MCP 서버 구성
| 서버 | 구현 | 용도 |
|------|------|------|
| web-search | Node.js 커스텀 (cheerio 스크래핑) | Google/Naver/Bing 웹 검색 |
| fetch | @kazuph/mcp-fetch (npx) | URL 본문 가져오기 |
| postgres | @modelcontextprotocol/server-postgres | PostgreSQL 직접 쿼리 |
| filesystem | @modelcontextprotocol/server-filesystem | 파일시스템 접근 |

### 1.5 웹 검색 구현 상세
- **방식**: Google/Naver/Bing HTML 스크래핑 (API 키 없음)
- **파서**: cheerio로 DOM 파싱
- **검색 순서**: Google → Naver → Bing (cascade)
- **결과 수**: 최대 8건 검색 → 상위 5건 본문 자동 읽기
- **본문 읽기**: 병렬 ThreadPoolExecutor (5 workers, 15초 타임아웃)
- **본문 길이**: URL당 2,500자 제한, fetch_url_content는 5,000자 제한
- **DNS**: 시스템 DNS → Cloudflare/Google fallback

### 1.6 LLM Tool Use 구성
| 도구 | 설명 |
|------|------|
| search_farm_knowledge | ChromaDB 벡터 검색 (농업 지식) |
| get_farm_realtime_data | PostgreSQL 실시간 센서/릴레이 데이터 |
| search_web | 웹 검색 (MCP web-search) |
| fetch_url_content | URL 본문 가져오기 (MCP fetch → urllib fallback) |

### 1.7 API 엔드포인트
| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| /api/v1/query | POST | 사용자 질문 → LLM 응답 |
| /api/v1/rag/perform | POST | 문서 업로드 → ChromaDB 저장 |
| /api/v1/rag/save | POST | 대화 저장 → ChromaDB 저장 |
| /health | GET | 헬스체크 |

### 1.8 시스템 프롬프트 구조
- **역할**: "사용자의 친한 친구이자 스마트팜 AI 도우미"
- **어투**: 친근한 반말 ("안녕! 반가워~")
- **도구 사용 판단**: 정보 요청 시만 도구 호출, 잡담은 직접 대화
- **출력 규칙**: 내부 추론 절대 출력 금지, 한글 답변 우선
- **웹 검색 규칙**: page_content 우선 활용, URL만 나열 금지

### 1.9 응답 후처리 파이프라인
1. `filter_llm_response()` - think 태그 제거
2. `clean_llm_response()` - 메타추론 키워드 제거
3. `_strip_reasoning_paragraphs()` - 추론 문단 감지/제거
4. `_strip_non_korean_reasoning_for_korean_query()` - 한국어 질문에 영어 추론 제거
5. `_force_korean_surface_for_korean_query()` - 한국어 강제 출력
6. `_rewrite_without_reasoning()` - 여전히 추론 남으면 재작성 (최대 2회)

### 1.10 주요 소스 파일 경로
| 파일 | 설명 |
|------|------|
| `agri_ai_core/src/ai/llm_client.py` | LLM 클라이언트 핵심 (도구 루프, 응답 정제) |
| `agri_ai_core/src/ai/tools_definition.py` | 도구 정의 + 시스템 프롬프트 |
| `agri_ai_core/src/ai/tools_executor.py` | 도구 실행 (웹검색, 지식검색 등) |
| `agri_ai_core/src/ai/mcp_client.py` | MCP 서버 호출 클라이언트 |
| `agri_ai_core/src/ai/query_handler_simple.py` | 쿼리 처리 진입점 |
| `agri_ai_core/src/ai/rag/embedder.py` | 임베딩 서비스 |
| `agri_ai_core/src/ai/rag/document_processor.py` | 문서 처리/청킹 |
| `agri_ai_core/config.py` | 전체 설정 관리 |
| `agri_ai_core/startup.py` | 앱 초기화 |
| `agri_ai_core/api/app.py` | REST API 엔드포인트 |
| `.mcp/web-search/build/index.js` | 웹 검색 MCP 서버 (빌드) |
| `.mcp/web-search/src/index.ts` | 웹 검색 MCP 서버 (소스) |
| `.vscode/mcp.json` | MCP 서버 설정 |

---

## 2. 현재 문제점 진단

### 2.1 대화 부자연스러움의 근본 원인

스크린샷 분석 ("여의도 점심 추천" 질문):
- 응답이 **일반적이고 구체성이 없다** ("한국식 랍스터 토스트", "아메리칸 레스토랑" 등 실재하지 않는 메뉴/가게)
- **웹 검색 결과를 제대로 활용하지 못하고** LLM이 자체 지식으로 답변하는 것으로 보임
- 또는 웹 검색 자체가 실패하여 도구 없이 답변한 것

#### 원인 1: LLM 모델 크기 부족 (핵심 원인)
- **qwen3:latest = 8.2B Q4_K_M** → 한국어 대화 능력이 부족
- 8B 모델은 Tool Use 판단력, 한국어 자연스러움, 맥락 이해 모두 약함
- `.env`에는 `MODEL_NAME=qwen3:32b`이지만 **실제 설치되어 있지 않음**
- qwen3:14b가 설치되어 있으나 사용되지 않음

#### 원인 2: 웹 검색 품질 한계
- HTML 스크래핑 방식 → Google/Naver의 봇 차단에 취약
- 검색 결과 파싱이 DOM 구조 변경에 민감
- 본문 읽기 2,500자 제한 → 핵심 정보 잘림
- MCP subprocess 방식 → 매 호출마다 Node.js 프로세스 시작/종료 (느림)

#### 원인 3: 도구 사용 판단 오류
- 8B 모델이 "여의도 점심 추천"을 **잡담으로 오분류**할 수 있음
- 시스템 프롬프트에 "추천 요청 등 사교적 대화: 도구를 사용하지 말고 직접 친구처럼 대화한다" → 모델이 웹검색 없이 답변
- 실제로 웹 검색이 필요한 질문인데 도구를 호출하지 않음

#### 원인 4: 응답 후처리 과다
- 6단계 필터링 → 유용한 내용까지 삭제될 수 있음
- 한국어 강제 변환 시 출처 URL 등이 잘릴 수 있음
- 재작성(rewrite) 호출 시 추가 LLM 호출로 지연 + 품질 저하

---

## 3. 개선 방안 (우선순위순)

### 3.1 [P0] LLM 모델 업그레이드 ★★★★★

**현재 상태**: qwen3:latest (8.2B Q4_K_M) — RTX 5060 Ti 16GB VRAM

**방안 A: qwen3:14b 활성화 (즉시 가능)**
```bash
# .env 수정
MODEL_NAME=qwen3:14b
```
- 이미 설치됨 (9.3GB), VRAM 16GB에 맞음
- 8B → 14B: 한국어 품질/Tool Use 판단력 향상
- **효과: 중간** — 8B보다 낫지만 여전히 한계

**방안 B: qwen3:30b-a3b MoE 모델 (권장)**
```bash
ollama pull qwen3:30b-a3b
# .env 수정
MODEL_NAME=qwen3:30b-a3b
```
- 30B 파라미터 중 3B만 활성화 (MoE) → 실제 VRAM ~5GB
- 30B급 지식량 + 8B급 속도 → 최적의 가성비
- 한국어 대화/Tool Use 판단/정보 종합 능력 대폭 향상
- **효과: 높음** — 비용 대비 최고 효율

**방안 C: 더 큰 모델 검토 (장기)**
- `qwen3:32b` (Q4_K_M ~20GB) → VRAM 부족, CPU 오프로드 필요 → 느림
- `qwen2.5:14b-instruct` → Tool Use는 약하나 대화 자연스러움 우수
- `llama3.3:70b-instruct-q2` → 극한 양자화, 실험적
- GPU 업그레이드(24GB+) 시: gemma3:27b, qwen3:32b 등 고려

### 3.2 [P0] 시스템 프롬프트 도구 판단 기준 개선 ★★★★★

**문제**: "추천" 질문을 잡담으로 오분류 → 웹검색 미호출

**개선안**: `tools_definition.py` 시스템 프롬프트 수정

```
[현재]
- 도구 사용 X: "안녕", "심심해", "뭐 하면 좋을까?", ...

[개선]
- 도구 사용 O: "오늘 날씨", "딸기 병해충", "여의도 맛집", "점심 추천", "환율",
  "최신 뉴스", "~가격", "~방법", "~어디", "~뭐가 좋아"
- 도구 사용 X: "안녕", "고마워", "기분이 안 좋아" (순수 감정/인사만)
- **장소/음식/가격/최신정보 추천은 반드시 웹 검색을 사용한다.**
```

### 3.3 [P1] 웹 검색 API 전환 ★★★★

**현재**: HTML 스크래핑 (Google/Naver/Bing) → 봇 차단/파싱 불안정

**방안 A: Brave Search API (권장)**
- 무료 2,000건/월, 유료 $3/1,000건
- JSON API → 파싱 불필요, 안정적
- snippet + page_content 직접 제공
- MCP 서버: `@anthropics/mcp-server-brave-search` 또는 직접 HTTP 호출

**방안 B: SerpAPI / Serper.dev**
- Google 검색 결과 JSON API
- Serper.dev: 무료 2,500건/월, $50/50,000건
- 한국어 검색 품질 우수 (Google 기반)

**방안 C: Tavily Search API**
- AI 특화 검색 API
- 자동으로 page_content 추출/요약 제공
- 무료 1,000건/월
- LLM 통합에 최적화됨

**방안 D: Naver 검색 API (한국어 특화)**
- 네이버 개발자센터: 무료 25,000건/일
- 블로그/뉴스/지식인 카테고리별 검색
- 한국 로컬 정보(맛집, 장소 등)에 강함
- 현재 스크래핑과 병행 가능

### 3.4 [P1] MCP 호출 방식 최적화 ★★★

**현재**: subprocess 방식 → 매번 Node.js 프로세스 시작/종료

**개선안 A: MCP 서버 상주 (StreamableHTTP)**
- web-search를 HTTP 서버로 전환 (port 3001 등)
- subprocess 대신 HTTP 호출 → 첫 호출 시간 단축
- warm 상태 유지 → DNS 캐시/연결 재사용

**개선안 B: Python 네이티브 웹검색**
- MCP 의존 제거, Python 직접 구현
- `httpx` + `beautifulsoup4`로 검색 파싱
- 또는 검색 API 직접 호출 (Brave/Serper)
- 프로세스 오버헤드 제거

### 3.5 [P2] 대화 히스토리 (멀티턴) 지원 ★★★

**현재**: 단일 턴 → 매 질문이 독립적 (이전 대화 기억 못함)

**개선안**:
- API에 `session_id` 파라미터 추가
- Redis 또는 메모리 캐시로 최근 N턴 대화 저장
- 시스템 프롬프트에 이전 대화 컨텍스트 주입
- 자연스러운 연속 대화 가능 ("아까 그거 말이야~" 등)

### 3.6 [P2] 응답 후처리 파이프라인 경량화 ★★★

**현재**: 6단계 필터링 + 재작성(rewrite) 최대 2회

**개선안**:
- 모델 크기 업그레이드 시 추론 누출이 줄어들어 필터링 필요성 감소
- qwen3 14B+ 모델은 `/no_think` 모드 지원 → thinking 자체를 비활성화 가능
- 후처리를 단순화: think 태그 제거 + 출처 URL 추가만 유지
- 불필요한 rewrite 호출 제거 → 응답 속도 개선

### 3.7 [P2] 임베딩 모델 업그레이드 ★★

**현재**: mxbai-embed-large (1024차원)

**개선안**:
- `snowflake-arctic-embed2:latest` → 다국어 지원, 한국어 성능 우수
- `bge-m3:latest` → 한국어 특화, 다국어 임베딩
- RAG 검색 정확도 향상 → 더 관련성 높은 지식 제공

### 3.8 [P3] 응답 포맷 개선 ★★

**현재**: 마크다운 텍스트 출력

**개선안**:
- 웹 검색 결과에 구조화된 카드 형식 응답
- 출처 링크를 인라인이 아닌 별도 섹션으로 분리
- 이미지 URL 포함 지원 (맛집/장소 추천 시)

### 3.9 [P3] 로깅/모니터링 강화 ★★

**현재**: 파일 기반 로깅 (logs/)

**개선안**:
- 웹 검색 성공/실패율 모니터링
- LLM 응답 시간 통계
- 도구 호출 패턴 분석 (어떤 질문에 어떤 도구를 호출하는지)
- 후처리에서 삭제된 내용 추적 → 과도한 필터링 감지

---

## 4. 즉시 실행 가능한 개선 (Quick Wins)

### 4.1 모델 변경 (5분)
```bash
# .env에서 MODEL_NAME 변경
MODEL_NAME=qwen3:14b
# 또는 MoE 모델 설치 후
ollama pull qwen3:30b-a3b
MODEL_NAME=qwen3:30b-a3b
```

### 4.2 시스템 프롬프트 수정 (10분)
`agri_ai_core/src/ai/tools_definition.py` 수정:
- "추천", "맛집", "어디", "뭐가 좋아" 등을 도구 사용 O 목록에 추가
- "장소/음식/가격/최신정보 추천은 반드시 웹 검색 사용" 규칙 추가

### 4.3 웹 검색 결과 본문 길이 확대 (5분)
`agri_ai_core/src/ai/tools_executor.py` 수정:
- `_auto_fetch_urls` 본문 제한: 2,500 → 4,000자
- `fetch_url_content` 제한: 5,000 → 8,000자

### 4.4 qwen3 thinking 모드 비활성화 (5분)
- qwen3는 기본적으로 thinking(추론 과정) 출력
- Ollama 호출 시 `options`에 `"think": false` 추가하거나
- 프롬프트에 `/no_think` 접두사 추가

---

## 5. 중기 개선 로드맵 (1~2주)

| 순서 | 작업 | 예상 효과 | 난이도 |
|------|------|----------|--------|
| 1 | LLM 모델 업그레이드 (qwen3:30b-a3b) | 대화 자연스러움 대폭 향상 | 낮음 |
| 2 | 시스템 프롬프트 도구 판단 개선 | 웹검색 미호출 문제 해결 | 낮음 |
| 3 | 웹 검색 API 전환 (Brave/Naver) | 검색 안정성/품질 향상 | 중간 |
| 4 | 멀티턴 대화 지원 | 자연스러운 연속 대화 | 중간 |
| 5 | 응답 후처리 경량화 | 응답 속도 개선 | 낮음 |
| 6 | 임베딩 모델 업그레이드 | RAG 검색 정확도 향상 | 낮음 |

---

## 6. 패키지/의존성 현황

### Python (venv)
```
fastapi==0.129.0       uvicorn==0.40.0        pydantic==2.12.5
ollama==0.6.1          chromadb==1.5.1        psycopg2-binary
numpy                  pandas                 apscheduler
python-dotenv          requests
```

### Node.js (MCP web-search)
```
@modelcontextprotocol/sdk    axios    cheerio
```

### 외부 서비스
```
Ollama (localhost:11434)     PostgreSQL (localhost:5432)
ChromaDB (localhost:8000)    Spring Boot (localhost:9090)
Nginx (localhost:80)         FastAPI (localhost:8002)
```

---

## 7. 변경 이력

| 날짜 | 작업 | 상태 |
|------|------|------|
| 2026-02-23 | 최초 작성 - 시스템 분석 및 개선 방안 도출 | 완료 |
| 2026-02-23 | Reflex UI 완전 삭제 (React 전환) | 완료 |
| 2026-02-23 | LLM 모델 업그레이드: qwen3:latest(8B) → qwen3:30b-a3b(30B MoE) | 완료 |
| 2026-02-23 | 시스템 프롬프트 개선: 추천/맛집/장소 질문 → 웹검색 필수 | 완료 |
| 2026-02-23 | 웹 검색 본문 길이 확대: 2,500→4,000자, 5,000→8,000자 | 완료 |
| 2026-02-23 | qwen3 thinking 모드 비활성화 (think: false) | 완료 |
| 2026-02-23 | 응답 후처리 경량화: rewrite 최대 2회→1회 | 완료 |
| 2026-02-23 | MCP 웹검색 확장: Google/Naver/Bing → +DuckDuckGo/Daum (5개 엔진) | 완료 |
