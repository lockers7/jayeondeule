# ══════════════════════════════════════════════════════════════════════════════
# MCP 서버 카탈로그 지식 시드 — "정보요구 → 적합 MCP 서버" 매핑(RAG 재활용)
#
# 농장주 지시(2026-07-23): 웹으로 부족하면 "필요한 정보관련 MCP를 찾아서 연결".
#   ANALYZER 가 매 질문 시 system_knowledge 를 회상하므로, 정보요구별 추천 MCP 서버
#   (등록됨/미등록·추가법 command·args·제공정보)를 지식으로 심어두면 LLM 이 이를 보고
#   mcp_call(등록서버) 또는 manage_mcp_server(미등록→add)로 연결해 정확 정보를 가져온다.
#   저장은 system_knowledge(document_collection, category='mcp_catalog'). 각 320자 내.
#
# 파일 시작 함수 목록:
#   seed_mcp_catalog : MCP 카탈로그 문서 일괄 upsert (멱등)
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# (key, text) — 각 text 320자 내. "정보요구 → 서버·도구·추가법·제공정보".
CATALOG_DOCS = [
    ("mcpcat_overview",
     "[MCP 활용 개요] 전용 도구·웹으로 부족한 전문 외부정보는 MCP 로 가져온다. 순서: "
     "①mcp_list_tools 로 등록 서버·도구 확인 →②mcp_call 로 호출. 정보에 맞는 MCP 가 "
     "미등록이면 manage_mcp_server(action='add', name, command, args)로 연결(관리자) 후 "
     "mcp_call. 아래 카탈로그에서 정보요구에 맞는 서버를 고른다."),
    ("mcpcat_paper",
     "[학술·연구논문 정보] server='paper-search'(등록됨). arxiv·pubmed·semantic scholar·"
     "biorxiv 등 57종. tool 예: search_arxiv, search_pubmed. 상황버섯 재배·병해충·효능 등 "
     "연구·논문 근거가 필요할 때. 예: mcp_call server='paper-search' tool='search_arxiv' "
     "args={'query':'Phellinus linteus cultivation'}."),
    ("mcpcat_naver",
     "[지역·쇼핑·지식iN·뉴스·블로그] server='naver-search'(등록됨, 21종). 국내 지역 맛집·"
     "상점·특산물, 지식iN Q&A, 쇼핑 가격, 뉴스, 블로그, DataLab 트렌드. 정읍 등 지역 생활·"
     "상거래 정보에. tool 예: search_local, search_shop, search_news."),
    ("mcpcat_weather",
     "[기상·날씨] server='korea-weather'(등록됨). 기상청 예보·특보. 단 농장 날씨는 전용도구 "
     "get_weather_forecast 가 1순위이고, korea-weather 는 그 외 지역·상세 기상 보완용."),
    ("mcpcat_search",
     "[메타 웹검색] server='searxng'(등록됨). search_web(기본)로 부족할 때 여러 엔진 메타검색"
     "으로 폭넓게 재수집. tool 예: search."),
    ("mcpcat_file",
     "[파일·로그 본문] server='filesystem'(등록됨). 레포 내 파일·로그 읽기(read_file/"
     "list_directory/search_files). ⛔ .env·키·토큰 등 시크릿 경로는 차단됨(읽기 불가)."),
    ("mcpcat_finance",
     "[국내 시세·재무] server='kis-trading'(등록됨, 조회전용). 한국투자증권 주식 시세·재무·"
     "잔고 inquire_* 조회. ⛔ 주문(매수/매도/정정/취소)은 원천 차단."),
    ("mcpcat_dart",
     "[전자공시·기업이벤트] server='dart'(등록됨). 국내 상장사 공시 이벤트 스캔의 핵심. "
     "tool=search_disclosures(기간 공시 검색 — 합병·자기주식·유상증자·실적·공급계약 등 이벤트, "
     "종목코드 포함), company_info(기업개황), financial_statement(재무제표). 자동매매 다음날 "
     "종목 선정용 이벤트 원천. 예: mcp_call server='dart' tool='search_disclosures' "
     "args={'pblntf_ty':'B'} (B=주요사항보고)."),
    ("mcpcat_time_unreg",
     "[시간·타임존] server='time'(등록됨). 현재시각·타임존 변환. "
     "mcp_call server='time' tool='get_current_time' args={'timezone':'Asia/Seoul'} / 'convert_time'."),
    ("mcpcat_github_unreg",
     "[GitHub 코드·이슈(미등록)] 오픈소스 저장소·코드·이슈 조회가 필요하면 manage_mcp_server"
     "(action='add', name='github', command='npx', args=['-y','@modelcontextprotocol/"
     "server-github']) 로 추가 후 mcp_call. (토큰 필요한 도구는 env 에 '${GITHUB_TOKEN}')."),
    ("mcpcat_wikipedia",
     "[백과사전 지식·위키백과(Wikipedia)] server='wikipedia'(등록됨, 한국어 ko 위키백과). 인물·역사·과학·지리·용어·개념 등 "
     "백과사전적 사실·정의·배경지식이 필요할 때 1순위. 22종 도구: search_wikipedia(검색), "
     "get_summary(요약), get_article(본문), extract_key_facts(핵심사실), "
     "summarize_article_for_query(질의맞춤요약), get_related_topics(관련주제), get_sections. "
     "예: mcp_call server='wikipedia' tool='search_wikipedia' args={'query':'상황버섯'}."),
    ("mcpcat_fetch",
     "[임의 웹페이지 본문 읽기] server='fetch'(등록됨, 공식 mcp-server-fetch). 특정 URL 본문을 "
     "마크다운으로 읽는다. 위키트리(wikitree.co.kr) 등 뉴스·일반 웹페이지 전문이 필요할 때. "
     "searxng/naver 로 URL 을 찾은 뒤 본문 전체가 필요하면 fetch 로 읽는다. "
     "tool='fetch' args={'url':'https://...','max_length':5000,'start_index':0}. 긴 문서는 "
     "start_index 로 이어읽기."),
    ("mcpcat_directory",
     "[MCP 서버 디렉토리 — 새 MCP 스스로 발굴·연결] 필요한 정보·기능의 MCP 가 미등록이면, "
     "fetch 로 https://mcpservers.org/ko/ (MCP 서버 목록 디렉토리)를 읽어 적합한 서버를 찾고, "
     "manage_mcp_server(action='add', name, command, args) 로 스스로 연결한 뒤 mcp_call 로 "
     "사용한다. 금융·지도·번역 등 새로운 요구가 오면 이 디렉토리에서 후보를 탐색하라."),
    ("mcpcat_ddg",
     "[웹검색 백업] server='ddg-search'(등록됨, DuckDuckGo·무키). searxng 결과 부족·중복 시 "
     "제2 검색엔진으로 재검색. tool='search' args={'query':'...','max_results':5}, "
     "본문은 'fetch_content'."),
    ("mcpcat_git",
     "[개발·저장소 이력] server='git'(등록됨, 이 레포 /workspace/jayeondeule). 커밋 이력·diff·"
     "blame·상태로 소스 변경 맥락 파악. 코드 자가유지보수·회귀 원인 추적에. tool 예: git_log, "
     "git_diff, git_show, git_status (args.repo_path='/workspace/jayeondeule')."),
    ("mcpcat_context7",
     "[개발·라이브러리 최신문서] server='context7'(등록됨). 파이썬/JS 등 라이브러리의 최신 공식 "
     "문서·API 사용법을 가져온다. 코드 작성·업그레이드 시 환각 방지. tool: resolve-library-id → "
     "get-library-docs."),
    ("mcpcat_memory",
     "[세션 지식그래프 메모리] server='memory'(등록됨). 엔티티-관계 그래프로 임시 작업맥락을 "
     "기억(create_entities/relations, search_nodes, read_graph). ⛔ 영속 지식은 원칙대로 "
     "VectorDB(save_knowledge)가 1순위 — memory 는 복잡 작업 중 임시 맥락 보조용."),
    ("mcpcat_seqthink",
     "[단계적 추론] server='seq-thinking'(등록됨). 복잡한 분석·계획을 단계별 사고로 분해할 때 "
     "tool='sequentialthinking' 사용. 다단계 진단·설계 품질 향상."),
    ("mcpcat_youtube",
     "[유튜브 자막 학습소스] server='youtube-transcript'(등록됨). 영상 자막 추출(tool='get_transcript', "
     "args={'url':...,'lang':'ko'}) → 재배 기술·시장 정보 등 영상 지식을 텍스트로 학습·저장 가능."),
    ("mcpcat_calc",
     "[정밀 계산] server='calculator'(등록됨). 수익률·임계값·통계 등 정확한 수치 계산은 암산 대신 "
     "tool='calculate' args={'expression':'...'} 로 검산하라."),
    ("mcpcat_openmeteo",
     "[세계·농업 기상] server='open-meteo'(등록됨, NOAA+Open-Meteo·무키). 정읍 농장 좌표 "
     "latitude=35.57, longitude=126.78 로 현재·예보·특보 조회(get_current_conditions/get_forecast/"
     "get_weather_summary). 국내 공식 예보는 korea-weather·get_weather_forecast 1순위, "
     "open-meteo 는 시계열·해외·보조 검증용."),
]


def seed_mcp_catalog():
    from agri_ai_core.src.ai.system_knowledge import save_system_knowledge
    n = 0
    for key, text in CATALOG_DOCS:
        if save_system_knowledge(text, category="mcp_catalog", source="seed", key=key).get("success"):
            n += 1
    logger.info(f"[MCP카탈로그] 시드 완료: {n}/{len(CATALOG_DOCS)}건")
    return {"success": True, "seeded": n, "total": len(CATALOG_DOCS)}
