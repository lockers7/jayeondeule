# AgriAI Core 시스템 개선 로드맵

> 최종 업데이트: 2026-02-23 (5차 업데이트 - 임베딩 업그레이드 + 구조화 응답 + 모니터링)
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
| **사용 모델** | `qwen3:30b-a3b` (30B MoE, 활성 3B) | 30B급 지식 + 8B급 속도 |
| 컨텍스트 길이 | 40,960 tokens | |
| 양자화 | Q4_K_M (4-bit) | |
| VRAM 사용 | ~12GB / 16GB | GPU 100% 오프로드 |
| 임베딩 모델 | bge-m3 | 1024차원, ~2.3GB, 다국어/한국어 특화 |
| Temperature | 0.7 (대화) / 0.0 (재작성) | |
| num_predict | 5120 tokens | 최대 출력 길이 |
| keep_alive | 1h | 모델 GPU 유지 시간 |
| think 모드 | 비활성화 (`"think": False`) | 추론 과정 출력 방지 |

### 1.3 설치된 Ollama 모델
```
qwen3:30b-a3b     (30B MoE, 18GB)         ← 현재 사용 중
qwen3:latest      (8.2B, Q4_K_M, 5.2GB)   ← 이전 모델
qwen3:14b         (14B, 9.3GB)             ← 미사용
qwen3-gpu:latest  (8.2B, 5.2GB)            ← 미사용
smollm2:135m      (135M, 270MB)            ← 테스트용
bge-m3             (임베딩 전용, ~2.3GB)    ← 현재 사용 중 (다국어/한국어 특화)
mxbai-embed-large (임베딩, 669MB)          ← 이전 모델
```

### 1.4 MCP 서버 구성
| 서버 | 구현 | 용도 | API 키 |
|------|------|------|--------|
| web-search | Node.js 커스텀 (cheerio) | Google/Naver/Daum/DuckDuckGo/Bing 통합 스크래핑 | 불필요 |
| fetch | @kazuph/mcp-fetch | URL 본문 가져오기 | 불필요 |
| postgres | @modelcontextprotocol/server-postgres | PostgreSQL 직접 쿼리 | 불필요 |
| filesystem | @modelcontextprotocol/server-filesystem | 파일시스템 접근 | 불필요 |
| brave-search | @modelcontextprotocol/server-brave-search | Brave Search JSON API | `BRAVE_SEARCH_API_KEY` |
| tavily | tavily-mcp | AI 특화 검색 (LLM 최적화) | `TAVILY_API_KEY` |
| exa | exa-mcp-server | 시맨틱/뉴럴 웹 검색 | `EXA_API_KEY` |
| ddg-web-search | @zhafron/mcp-web-search | DuckDuckGo + Bing + Wikipedia | 불필요 |

### 1.5 웹 검색 구현 상세
- **검색 계층 (3-tier hybrid)**:
  - **1차: SearXNG 메타검색** (무료, API 키 불필요, Docker 자체 호스팅)
    - Google/Naver/Bing/DuckDuckGo/Wikipedia 동시 검색
    - JSON API: `http://127.0.0.1:8888/search?q=...&format=json`
    - 15건 결과, 1~2초 응답
  - **2차: Naver/Brave API** (API 키 필요, JSON 응답)
    - 한국어 → Naver 우선, 영어 → Brave 우선
  - **3차: MCP web-search** (HTML 스크래핑 fallback)
    - Google/Naver/Daum/DuckDuckGo/Bing cascade
- **본문 읽기**: 병렬 ThreadPoolExecutor (5 workers, 15초 타임아웃)
- **본문 길이**: URL당 4,000자 제한, fetch_url_content는 8,000자 제한
- **DNS**: 시스템 DNS → Cloudflare/Google fallback (1.1.1.1, 8.8.8.8, 8.8.4.4)
- **중복 제거**: URL 정규화 후 deduplication
- **Naver 스코어링**: 광고/내부링크 필터, 외부 도메인 우선

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
| /api/v1/stats | GET | 질의 통계/모니터링 데이터 |
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
6. `_rewrite_without_reasoning()` - 여전히 추론 남으면 재작성 (최대 1회)

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
| `agri_ai_core/src/ai/stats_collector.py` | 질의 통계 수집기 (인메모리, Thread-safe) |
| `agri_ai_core/src/ai/conversation_store.py` | 멀티턴 대화 저장소 |
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

### 3.7 ~~[P2] 임베딩 모델 업그레이드~~ ✅ 완료 (2026-02-23)

**변경**: mxbai-embed-large → **bge-m3** (다국어/한국어 특화, 1024차원)
- 기존 108건 문서 전체 재임베딩 완료
- 더미 임베딩([0.0]*1024) → 실제 시맨틱 임베딩으로 교체
- 거리 임계값 5.0→22.0 조정 (bge-m3 비정규화 벡터 특성)

### 3.8 ~~[P3] 응답 포맷 개선~~ ✅ 완료 (2026-02-23)

**변경**: API 응답에 구조화된 메타데이터 추가
- `sources`: 웹 검색 출처 목록 (title + url)
- `tools_used`: 사용된 도구 목록
- `response_type`: 응답 유형 (web_search|farm_data|knowledge|general)

### 3.9 ~~[P3] 로깅/모니터링 강화~~ ✅ 완료 (2026-02-23)

**변경**: 인메모리 통계 수집기 + REST API 엔드포인트
- `/api/v1/stats`: 질의 수/성공률, 응답시간, 도구 사용 빈도, 검색 provider 통계
- 검색 provider별 성공/실패 자동 기록

---

## 4. 즉시 실행 가능한 개선 (Quick Wins) — 모두 완료

### 4.1 ~~모델 변경~~ ✅ 완료 (2026-02-23)
- qwen3:30b-a3b MoE 모델 설치 및 적용

### 4.2 ~~시스템 프롬프트 수정~~ ✅ 완료 (2026-02-23)
- 추천/맛집/장소 질문 → 웹검색 필수, 애매하면 검색 쪽으로 판단

### 4.3 ~~웹 검색 결과 본문 길이 확대~~ ✅ 완료 (2026-02-23)
- 2,500→4,000자, 5,000→8,000자

### 4.4 ~~qwen3 thinking 모드 비활성화~~ ✅ 완료 (2026-02-23)
- `"think": False` 옵션 적용

### 4.5 ~~웹 검색 엔진 확장~~ ✅ 완료 (2026-02-23)
- Google/Naver/Bing → Google/Naver/Daum/DuckDuckGo/Bing (5개)

### 4.6 ~~응답 후처리 경량화~~ ✅ 완료 (2026-02-23)
- rewrite 최대 2회→1회

### 4.7 ~~MCP web-search 소스 동기화~~ ✅ 완료 (2026-02-23)
- build/index.js 직접 수정 → src/index.ts 소스 동기화 + 빌드 + 서브모듈 커밋

---

## 5. 중기 개선 로드맵

| 순서 | 작업 | 예상 효과 | 난이도 | 상태 |
|------|------|----------|--------|------|
| ~~1~~ | ~~LLM 모델 업그레이드 (qwen3:30b-a3b)~~ | ~~대화 자연스러움 대폭 향상~~ | ~~낮음~~ | **완료** |
| ~~2~~ | ~~시스템 프롬프트 도구 판단 개선~~ | ~~웹검색 미호출 문제 해결~~ | ~~낮음~~ | **완료** |
| ~~3~~ | ~~MCP 웹검색 5개 엔진 확장~~ | ~~검색 다양성/안정성 향상~~ | ~~낮음~~ | **완료** |
| ~~4~~ | ~~응답 후처리 경량화~~ | ~~응답 속도 개선~~ | ~~낮음~~ | **완료** |
| ~~5~~ | ~~웹 검색 API 전환 (Brave/Naver)~~ | ~~검색 안정성/품질 향상~~ | ~~중간~~ | **완료** (코드 구현, API 키 대기) |
| ~~5.5~~ | ~~SearXNG 자체 호스팅 통합~~ | ~~무료 무제한 메타검색~~ | ~~중간~~ | **완료** |
| ~~6~~ | ~~멀티턴 대화 지원~~ | ~~자연스러운 연속 대화~~ | ~~중간~~ | **완료** |
| ~~7~~ | ~~임베딩 모델 업그레이드 (bge-m3)~~ | ~~RAG 검색 정확도 향상~~ | ~~낮음~~ | **완료** |
| ~~8~~ | ~~응답 포맷 개선 (구조화 응답)~~ | ~~UI 표현력 향상~~ | ~~중간~~ | **완료** |
| ~~9~~ | ~~로깅/모니터링 강화~~ | ~~문제 조기 감지~~ | ~~중간~~ | **완료** |

---

## 5-1. [과제 5] 웹 검색 API 전환 (Brave + Naver API) ✅ 구현 완료

### 상태: 코드 구현 완료, API 키 발급 대기

### 구현 내용

#### 수정된 파일
| 파일 | 변경 내용 |
|------|----------|
| `agri_ai_core/src/ai/tools_executor.py` | SearXNG/Naver/Brave API 검색 모듈 + search_web() 3-tier 구조 |
| `.env` | `SEARXNG_URL`, `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `BRAVE_SEARCH_API_KEY` 설정 추가 |
| `setup/searxng/docker-compose.yml` | SearXNG Docker 컨테이너 설정 |
| `setup/searxng/settings.yml` | SearXNG 검색엔진 설정 (Google/Naver/DuckDuckGo/Bing) |
| `setup/agriCoreCtrl.sh` | SearXNG 서비스 관리 (#6) 추가, 서비스 번호 재배정 |
| `setup/run_services.sh` | SearXNG 시작/종료 함수 추가 |

#### 구현된 함수
| 함수 | 설명 |
|------|------|
| `_is_korean_query(query)` | 한국어 포함 여부 판별 |
| `_search_via_searxng(query, count)` | SearXNG 메타검색 (무료, Docker 자체 호스팅) |
| `_search_via_naver_api(query, display)` | Naver 검색 API (블로그+웹 통합) |
| `_search_via_brave_api(query, count)` | Brave Search API (글로벌 웹) |
| `_search_via_api(query)` | 통합 라우터: SearXNG→Naver/Brave→None(MCP fallback) |

#### 검색 흐름
```
사용자 질문
    ↓
search_web(query)
    ↓
[1단계] _search_via_api(query)
    ├─ SearXNG 메타검색 (무료, 최우선) ← 2026-02-23 추가
    ├─ 한국어 질문 → Naver API → Brave API
    └─ 영어 질문 → Brave API → Naver API
    ↓ (모든 API 실패)
[2단계] MCP web-search (기존 5개 엔진 스크래핑)
    ↓
[3단계] 상위 5건 본문 자동 읽기 (_auto_fetch_urls)
    ↓
LLM에 결과 전달
```

#### 로그 출력 예시
```
[API검색] 모든 API 실패 또는 미설정 (0.0s) → MCP fallback
[웹검색] MCP 스크래핑 fallback 성공
[웹검색] 검색완료 (1.4s) provider=mcp_scraping results=8건
```

#### Naver API 상세
- 엔드포인트: `openapi.naver.com/v1/search/blog.json` + `webkeyword.json`
- 인증: `X-Naver-Client-Id`, `X-Naver-Client-Secret` 헤더
- 블로그+웹 2개 카테고리 병합 검색, HTML 태그 자동 제거
- 429 (Too Many Requests) 에러 핸들링

#### Brave API 상세
- 엔드포인트: `api.search.brave.com/res/v1/web/search`
- 인증: `X-Subscription-Token` 헤더
- gzip 응답 자동 처리, `search_lang=ko`, `country=KR`

### 남은 작업: API 키 발급 (사용자 액션)

```
1. Naver 검색 API (권장 - 무료 25,000건/일):
   - https://developers.naver.com/ 접속
   - 로그인 → Application → 애플리케이션 등록
   - "검색" API 선택 → Client ID/Secret 발급
   - .env에 입력:
     NAVER_CLIENT_ID=발급받은_ID
     NAVER_CLIENT_SECRET=발급받은_SECRET

2. Brave Search API (선택 - 무료 2,000건/월):
   - https://brave.com/search/api/ 접속
   - Free 플랜 가입 → API Key 발급
   - .env에 입력:
     BRAVE_SEARCH_API_KEY=발급받은_KEY

3. API 키 입력 후 서비스 재시작:
   agriCoreCtrl restart 5
```

### SearXNG 상세 (2026-02-23 추가)
- **Docker**: `docker compose -f setup/searxng/docker-compose.yml up -d`
- **포트**: 8888 (→ 컨테이너 내부 8080)
- **엔진**: Google, Naver, DuckDuckGo, Bing, Wikipedia
- **API**: `GET http://127.0.0.1:8888/search?q={query}&format=json&language=ko-KR`
- **장점**: 무료, API 키 불필요, 무제한, 다중 엔진 동시 검색
- **성능**: 1~2초 응답, 15~47건 결과 (이전 MCP 스크래핑 대비 6.7배 빠름)
- **관리**: `agriCoreCtrl start|stop|restart 6`

#### SearXNG 관리 명령
```bash
# 시작/종료/재시작
agriCoreCtrl start 6
agriCoreCtrl stop 6
agriCoreCtrl restart 6

# 직접 Docker 관리
docker compose -f setup/searxng/docker-compose.yml up -d
docker stop searxng
docker start searxng
docker logs searxng

# 검색엔진 설정 변경 후 재시작
vi setup/searxng/settings.yml
docker restart searxng
```

### 테스트 검증 결과 (2026-02-23)
- [x] Python import 성공
- [x] 한국어 판별 정상 동작 (`_is_korean_query`)
- [x] SearXNG 검색 정상 동작 (한국어 15건, 영어 15건)
- [x] SearXNG 멀티엔진 확인 (Google, Brave, Bing 동시 결과)
- [x] API 키 없이 실행 시 graceful None 반환 → MCP fallback
- [x] MCP fallback 경로 정상 동작 (8건 검색, 2건 본문 확보)
- [x] REST API end-to-end 테스트 성공 (SearXNG 경로, 1.8초 검색+본문)
- [x] 로그에 provider 경로 명확 추적 가능 (provider=searxng)

---

## 5-2. [과제 6] 멀티턴 대화 지원 ✅ 구현 완료

### 상태: 백엔드 구현 완료, 테스트 통과

### 아키텍처
```
프론트엔드                         백엔드
┌──────────┐    session_id     ┌──────────────┐
│  React   │ ───────────────→ │  FastAPI      │
│  Chat UI │ ←─────────────── │  /api/v1/query│
└──────────┘                   └──────┬───────┘
                                      │
                               ┌──────▼───────┐
                               │ ConversationStore │
                               │ (메모리, TTL 30분) │
                               └──────────────┘
```

### 구현 내용

#### 수정/생성된 파일
| 파일 | 변경 내용 |
|------|----------|
| `agri_ai_core/src/ai/conversation_store.py` | **신규** — 인메모리 대화 저장소 (Thread-safe, TTL 30분, 최대 10턴) |
| `agri_ai_core/api/models.py` | QueryRequest/QueryResponse에 `session_id` 필드 추가 |
| `agri_ai_core/api/app.py` | session_id 자동 생성(UUID), query_llm_simple에 전달, 응답에 포함 |
| `agri_ai_core/src/ai/query_handler_simple.py` | conversation_history 로드/저장 로직 추가 |
| `agri_ai_core/src/ai/llm_client.py` | get_llm_response_with_tools()에 conversation_history 주입 |

#### ConversationStore 상세
```python
# agri_ai_core/src/ai/conversation_store.py
class ConversationStore:
    # Thread-safe 싱글턴 패턴
    max_turns: 10        # session당 최대 10턴 (user+assistant 각 1턴)
    ttl_seconds: 1800    # 30분 비활성 시 자동 만료

    add_turn(session_id, role, content)    # 턴 추가 + 만료 세션 정리
    get_history(session_id) → List[Dict]   # [{"role": "user", "content": "..."}]
    clear_session(session_id)              # 세션 명시적 삭제
    active_sessions() → int               # 활성 세션 수

# 글로벌 접근
get_conversation_store() → ConversationStore  # 싱글턴
```

#### API 변경사항
```json
// 요청 (session_id 선택 — 없으면 서버에서 UUID 자동 생성)
POST /api/v1/query
{
  "query": "딸기 재배 적정 온도는?",
  "session_id": "abc-123-def"     // ← 추가 (Optional)
}

// 응답 (session_id 항상 포함)
{
  "success": true,
  "response": "...",
  "processing_time": 12.3,
  "session_id": "abc-123-def"     // ← 추가
}
```

#### LLM 메시지 구조 (멀티턴)
```
messages = [
    {"role": "system", "content": "시스템 프롬프트..."},
    {"role": "user", "content": "1턴 질문..."},           // ← history
    {"role": "assistant", "content": "1턴 답변(500자)"},   // ← history (truncated)
    {"role": "user", "content": "현재 질문..."}            // ← current
]
```
- 이전 대화 assistant 답변은 **500자로 truncate** (컨텍스트 절약)
- 최대 10턴 (20개 메시지)까지 주입

#### 프론트엔드 연동 방법
```
React 채팅 컴포넌트에서:
1. 페이지 로드 시 session_id = uuid.v4() 생성
2. API 호출 시 session_id 포함
3. 응답의 session_id를 이후 요청에 재사용
4. "새 대화" 버튼 → session_id 재생성
```

### 테스트 검증 결과 (2026-02-23)
- [x] ConversationStore 단위 테스트: add_turn, get_history, TTL 만료, 턴 제한 정상
- [x] 직접 Python 2턴 테스트:
  - 1턴: "딸기 재배에서 적정 온도는 몇 도야?" → 2327자 응답
  - 2턴: "그러면 습도는 어떻게 관리해야 해?" → 3523자 응답
  - 2턴 응답에 "딸기" 키워드 포함 → 이전 대화 컨텍스트 유지 확인
  - 대화 저장소에 4턴 정상 저장 (user 2 + assistant 2)
- [x] 멀티턴 로그 추적: `[멀티턴] session=xxx... 이전 대화 N턴 로드/주입/저장` 확인

### 남은 작업
- 프론트엔드(React) 채팅 컴포넌트에 session_id 연동 (과제 6의 프론트엔드 파트)
- 필요 시 Redis 전환 (현재 메모리 기반 — 서버 재시작 시 대화 초기화)

---

## 5-3. [과제 7] 임베딩 모델 업그레이드 ✅ 구현 완료

### 상태: 모델 교체 + 전체 재임베딩 완료

### 구현 내용

#### 수정된 파일
| 파일 | 변경 내용 |
|------|----------|
| `.env` | `EMBEDDING_MODEL_NAME=bge-m3` (기존: mxbai-embed-large:latest) |
| `agri_ai_core/config.py` | 기본 상수 `bge-m3`로 변경 |
| `agri_ai_core/src/ai/rag/chunker.py` | 더미 임베딩 → 실제 임베딩 생성 로직으로 교체 |
| `agri_ai_core/src/ai/tools_executor.py` | `MAX_DISTANCE` 5.0→22.0 (bge-m3 비정규화 벡터 보정) |

#### 핵심 변경사항
1. **모델 교체**: mxbai-embed-large → bge-m3 (다국어/한국어 특화, 1024차원)
2. **치명적 버그 수정**: 기존 문서가 더미 임베딩 `[0.0]*1024`로 저장되어 있었음 → 의미적 벡터 검색이 불가능한 상태였음
3. **전체 재임베딩**: 108건 문서를 bge-m3로 재임베딩 (17.4초, 100% 성공)
4. **거리 임계값 조정**: bge-m3는 비정규화 벡터(노름 ~3.0)를 생성하므로 L2 거리가 커짐
   - 유사: 0~10, 관련: 10~20, 무관: 20+
   - `MAX_DISTANCE`: 5.0 → 22.0
5. **chunker.py 개선**: `store_document_with_chunks()` 함수에 `embed_text()` + `upsert_documents_with_embedding()` 배치 처리 적용

#### 검증 결과
- [x] bge-m3 모델 설치 및 1024차원 임베딩 확인
- [x] 기존 108건 문서 전체 재임베딩 성공 (17.4초)
- [x] 벡터 검색 정상 동작: "상황버섯" 질의 시 관련 문서가 최상위 랭킹
- [x] 거리 기반 필터링 정상 동작 (MAX_DISTANCE=22.0)

---

## 5-4. [과제 8] 응답 포맷 개선 (구조화 응답) ✅ 구현 완료

### 상태: 백엔드 구조화 응답 구현 완료

### 구현 내용

#### 수정된 파일
| 파일 | 변경 내용 |
|------|----------|
| `agri_ai_core/api/models.py` | `SourceItem` 모델 추가, `QueryResponse`에 `sources`/`tools_used`/`response_type` 필드 추가 |
| `agri_ai_core/src/ai/llm_client.py` | 반환 타입 `str` → `Dict[str, Any]`, 도구 추적, `_build_structured_result()` 헬퍼 |
| `agri_ai_core/src/ai/query_handler_simple.py` | 구조화 dict 응답 처리, 웹 로그에 메타데이터 기록 |
| `agri_ai_core/api/app.py` | 구조화 응답 전달, API 응답에 메타데이터 포함 |

#### API 응답 구조
```json
{
  "success": true,
  "response": "답변 텍스트...",
  "processing_time": 12.3,
  "session_id": "abc-123",
  "sources": [{"title": "출처 제목", "url": "https://..."}],
  "tools_used": ["search_web", "fetch_url_content"],
  "response_type": "web_search"
}
```

#### 응답 유형 분류 로직
| response_type | 조건 |
|---------------|------|
| `web_search` | search_web 또는 fetch_url_content 사용 |
| `farm_data` | get_farm_realtime_data 사용 |
| `knowledge` | search_farm_knowledge 사용 |
| `general` | 도구 미사용 (일반 대화) |

#### 핵심 변경사항
1. **llm_client.py**: `get_llm_response_with_tools()` 반환 타입을 `str` → `Dict[str, Any]`로 변경
2. **도구 추적**: 루프 내에서 `_tools_used` 리스트로 사용된 도구 누적
3. **출처 수집**: 웹 검색 시 `_collected_sources` 리스트로 출처 정보 수집
4. **헬퍼 함수**: `_determine_response_type()`, `_build_structured_result()` 추가
5. **모든 반환 경로**에서 구조화된 dict 반환 보장

#### 검증 결과
- [x] 일반 대화: `response_type="general"`, `tools_used=[]`
- [x] 웹 검색: `response_type="web_search"`, `tools_used=["search_web"]`, `sources` 포함
- [x] API 응답 JSON 스키마 유효

### 남은 작업
- 프론트엔드(React)에서 `response_type`별 차별화된 렌더링 구현

---

## 5-5. [과제 9] 로깅/모니터링 강화 ✅ 구현 완료

### 상태: 통계 수집 모듈 + REST API 엔드포인트 구현 완료

### 구현 내용

#### 수정/생성된 파일
| 파일 | 변경 내용 |
|------|----------|
| `agri_ai_core/src/ai/stats_collector.py` | **신규** — 인메모리 통계 수집기 (Thread-safe, 싱글턴) |
| `agri_ai_core/api/app.py` | `/api/v1/stats` GET 엔드포인트 추가, 질의 성공/실패 통계 기록 |
| `agri_ai_core/src/ai/tools_executor.py` | `_search_via_api()`에 검색 provider 성공/실패 통계 기록 |

#### StatsCollector 상세
```python
class StatsCollector:
    # Thread-safe 싱글턴 패턴
    max_recent: 100          # 최근 100건 응답 시간 슬라이딩 윈도우

    record_query(success, processing_time, tools_used, response_type)
    record_search(provider, success)     # searxng/naver/brave 검색 기록
    get_stats() → Dict                   # 전체 통계 반환
    reset()                              # 통계 초기화

get_stats_collector() → StatsCollector  # 글로벌 싱글턴
```

#### /api/v1/stats 응답 구조
```json
{
  "uptime_seconds": 29.9,
  "queries": {
    "total": 1,
    "success": 1,
    "error": 0,
    "success_rate": 100.0
  },
  "response_time": {
    "avg": 21.09,
    "min": 21.09,
    "max": 21.09,
    "recent_count": 1
  },
  "tools": {"search_web": 3, "fetch_url_content": 5},
  "response_types": {"general": 1, "web_search": 3},
  "search": {
    "providers": {"searxng": 3, "naver": 1},
    "failures": 0
  }
}
```

#### 통계 수집 지점
| 위치 | 수집 항목 |
|------|----------|
| `app.py` (query 성공) | 질의 수, 처리시간, 도구 목록, 응답 유형 |
| `app.py` (query 실패) | 질의 수, 처리시간, 실패 카운트 |
| `tools_executor.py` (검색 성공) | provider명, 성공 카운트 |
| `tools_executor.py` (검색 실패) | provider명, 실패 카운트 |

#### 검증 결과
- [x] 서버 시작 직후 빈 통계 반환 정상
- [x] 질의 후 `queries.total=1, success=1, response_types.general=1` 정상 기록
- [x] 응답 시간 통계 (avg/min/max) 정상 계산

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
ChromaDB (localhost:8000)    SearXNG (localhost:8888, Docker)
Spring Boot (localhost:9090) FastAPI (localhost:8002)
Nginx (localhost:80)
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
| 2026-02-23 | MCP web-search 소스 동기화: src/index.ts ← build/index.js + 서브모듈 커밋 | 완료 |
| 2026-02-23 | 웹 검색 API 전환: Naver/Brave API 모듈 구현 + search_web API 우선 구조 | 완료 (키 대기) |
| 2026-02-23 | MCP 서버 확장: brave-search, tavily, exa, ddg-web-search 4개 추가 | 완료 (키 대기) |
| 2026-02-23 | SearXNG Docker 자체 호스팅 설치 및 통합 | 완료 |
| 2026-02-23 | 검색 구조 3-tier 전환: SearXNG(무료)→API(유료)→MCP(스크래핑) | 완료 |
| 2026-02-23 | agriCoreCtrl/run_services에 SearXNG 서비스 관리(#6) 추가 | 완료 |
| 2026-02-23 | 멀티턴 대화 지원: conversation_store.py + API/핸들러/LLM 클라이언트 수정 | 완료 |
| 2026-02-23 | 멀티턴 테스트 통과: 2턴 연속 대화, 이전 컨텍스트 유지 확인 | 완료 |
| 2026-02-23 | 임베딩 모델 업그레이드: mxbai-embed-large → bge-m3 (다국어/한국어 특화) | 완료 |
| 2026-02-23 | 치명적 버그 수정: 더미 임베딩 [0.0]*1024 → 실제 시맨틱 임베딩으로 교체 | 완료 |
| 2026-02-23 | 기존 108건 문서 전체 bge-m3 재임베딩 (17.4초, 100% 성공) | 완료 |
| 2026-02-23 | 벡터 거리 임계값 조정: MAX_DISTANCE 5.0→22.0 (bge-m3 비정규화 벡터 보정) | 완료 |
| 2026-02-23 | 구조화 응답 포맷: sources/tools_used/response_type 메타데이터 추가 | 완료 |
| 2026-02-23 | llm_client 반환 타입 str→Dict 전환, 도구 추적 및 응답 유형 분류 | 완료 |
| 2026-02-23 | 통계 수집기 stats_collector.py 신규 생성 (Thread-safe, 싱글턴) | 완료 |
| 2026-02-23 | /api/v1/stats 엔드포인트 추가: 질의 통계/응답시간/검색 provider 모니터링 | 완료 |
