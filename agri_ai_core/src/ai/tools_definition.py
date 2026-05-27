# ══════════════════════════════════════════════════════════
# LLM Tool Use 도구 정의
# Ollama Function Calling을 위한 도구 정의
# --->
# get_available_tools: get available tools
# get_system_prompt_with_tools: get system prompt with tools
# ══════════════════════════════════════════════════════════
from datetime import datetime
from typing import List, Dict, Any

# 장치명 매핑은 mappers.device_mapping_text() 자동 생성을 사용.
from agri_ai_core.config.mappers import (
    device_mapping_text as _device_mapping_text,
    device_detail_text as _device_detail_text,
    SYSTEM_GLOSSARY_TEXT as _SYSTEM_GLOSSARY_TEXT,
    circulation_modes_text as _circulation_modes_text,
    growth_stages_enum as _growth_stages_enum,
    control_modes_enum as _control_modes_enum,
    circulation_mode_enum as _circulation_mode_enum,
)


# ═════════════════════════════════════════════════════
# 사용 가능한 도구 목록
# LLM이 사용할 수 있는 도구 목록 반환
# Returns: List[Dict]: Ollama Tool Use 형식의 도구 정의
# ═════════════════════════════════════════════════════
def get_available_tools() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "save_domain_knowledge",
                "description": (
                    "사용자가 채팅으로 알려주는 운영 노하우·룰·도메인 지식을 ChromaDB 도메인 RAG에 영속 저장합니다. "
                    "저장 즉시 다음 AI 환경제어 사이클부터 LLM이 자동 검색·참조하므로, 사용자가 룰을 채팅 한 번으로 시스템에 가르치는 채널입니다. "
                    "사용자 발화에 다음 의도가 보이면 반드시 호출: '학습해/기억해/저장해/다음부터 적용/룰로 추가/방침으로/규칙으로'. "
                    "title은 30자 내 식별용 요약, content는 풀 텍스트(가능한 정확한 임계치·조건·예시 포함). "
                    "category는 '운영노하우/제어룰/안전룰/생육관리/장치사용법' 등 자유 입력."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "30자 내 식별용 요약 (예: '수온 가열 시 -5℃ 히스테리시스 룰')"
                        },
                        "content": {
                            "type": "string",
                            "description": "지식 본문 — 임계치·조건·예시·근거 포함. 길수록 검색 품질 향상."
                        },
                        "category": {
                            "type": "string",
                            "description": "분류 (예: '운영노하우', '제어룰', '안전룰', '생육관리', '장치사용법'). 기본 '운영노하우'.",
                            "default": "운영노하우"
                        },
                        "farm_id": {
                            "type": "string",
                            "description": "특정 농장에만 적용되는 지식이면 농장ID. 전체 적용은 생략."
                        },
                        "house_id": {
                            "type": "string",
                            "description": "특정 재배사에만 적용되는 지식이면 재배사ID. 전체 적용은 생략."
                        },
                        "tags": {
                            "type": "string",
                            "description": "쉼표 구분 태그 (검색 보조용, 선택). 예: '수온,히터,포그,히스테리시스'"
                        }
                    },
                    "required": ["title", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "delete_farm_knowledge",
                "description": "학습(RAG) 데이터를 파일명으로 삭제합니다. 해당 파일의 모든 청크를 ChromaDB에서 영구 삭제합니다. 삭제 전 확인 없이 즉시 실행하세요. 삭제 완료 후 search_farm_knowledge를 재호출하여 확인하지 마세요 — 도구가 반환한 success/deleted_count를 신뢰하세요. file_name='all'이면 전체 문서 삭제, 복수 파일은 파이프(|)로 구분 (예: 'a.pdf|b.pdf').",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_name": {
                            "type": "string",
                            "description": "삭제할 파일명. 전체삭제='all', 복수파일='파일1.pdf|파일2.pdf' (파이프 구분). 파일명에 쉼표가 포함될 수 있으므로 구분자는 반드시 파이프(|) 사용."
                        },
                        "farm_id": {
                            "type": "string",
                            "description": "농장 ID (농장관리자: 자기 농장 ID, 시스템관리자: 생략 가능)"
                        }
                    },
                    "required": ["file_name"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_farm_knowledge",
                "description": "스마트팜 벡터 데이터베이스(ChromaDB)에서 관련 정보를 검색합니다. 학습(RAG)된 문서 지식, 파일 내용, 농장 시계열 데이터를 함께 조회합니다. 파일명으로도 검색 가능합니다. 응답의 file_list 각 항목에 farm_scope 필드가 포함되며, '시스템 농장'은 전체 공용 학습 데이터, '농장ID:xxx'는 해당 농장 전용 데이터입니다. 파일 목록 표시 시 반드시 farm_scope 값을 그대로 사용하세요.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "검색할 질문 또는 키워드. 파일 검색 시 파일명을 포함하세요."
                        },
                        "n_results": {
                            "type": "integer",
                            "description": "가져올 결과 개수 (기본값: 5, 상세 답변 필요 시 10~20으로 증가)",
                            "default": 5
                        },
                        "file_name": {
                            "type": "string",
                            "description": "검색할 파일명 (선택사항, 지정 시 해당 파일의 청크만 검색)"
                        },
                        "farm_id": {
                            "type": "string",
                            "description": "농장 ID (선택사항, 지정 시 해당 농장 데이터 우선 검색)"
                        },
                        "house_id": {
                            "type": "string",
                            "description": "재배사 ID (선택사항, 지정 시 해당 재배사 데이터 우선 검색)"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_farm_realtime_data",
                "description": "농장의 실시간 센서+릴레이 데이터와 환경 제어 임계값, AI 환경 판단을 가져옵니다. data_type='all'(기본값)로 센서+릴레이를 한 번에 조회하세요. 응답에 environment_thresholds(적정 범위)와 ai_environment_judgment(알고리즘 권장 릴레이 상태)가 포함됩니다. 센서값 적절성 판단, AI vs 알고리즘 제어값 비교 시 반드시 이 도구를 사용하세요.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "farm_id": {
                            "type": "string",
                            "description": "농장 ID (선택사항)"
                        },
                        "house_id": {
                            "type": "string",
                            "description": "재배사 ID (예: '1재배사' → '1')"
                        },
                        "data_type": {
                            "type": "string",
                            "description": "데이터 유형. all: 센서+릴레이 동시 조회(권장), sensor: 센서만, relay: 릴레이만",
                            "enum": ["sensor", "relay", "all"],
                            "default": "all"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_weather_forecast",
                "description": "농장 소재지의 기상청 단기예보(온도/습도/강수확률/강수형태/풍속/하늘상태)를 조회합니다. 농장/재배사/지역 날씨 질문에는 search_web 보다 이 도구를 우선 사용하세요. 농장 등록 주소의 기상청 격자 기반이라 즉시(1초 내) 정확한 예보를 반환합니다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "farm_id": {
                            "type": "string",
                            "description": "농장 ID (선택사항 — 세션 농장 자동 적용)"
                        },
                        "house_id": {
                            "type": "string",
                            "description": "재배사 ID (선택사항)"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "call_external_api",
                "description": "관리자가 등록해 둔 외부 API를 호출합니다(GET 전용). api_name 없이 호출하면 사용 가능한 API 목록을 반환합니다. 전용 도구(get_weather_forecast 등)로 안 되는 외부 데이터가 필요할 때 목록을 먼저 확인 후 사용하세요.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "api_name": {
                            "type": "string",
                            "description": "등록된 API 이름 (생략 시 목록 조회)"
                        },
                        "params": {
                            "type": "object",
                            "description": "URL 템플릿의 {파라미터} 값들 (예: {\"area_no\":\"5218000000\"})"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "manage_external_api",
                "description": "외부 API 등록부 관리. list/get 은 누구나, register/update/disable 은 시스템관리자 전용. 사용자가 '○○ API를 등록해달라'고 하면 url_template(값 자리에 {파라미터}, 서버 키는 {ENV:환경변수명})과 설명으로 register 하세요. 등록 즉시 call_external_api 로 사용 가능 — 코드 변경 불필요.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["list", "get", "register", "update", "disable"],
                            "description": "수행 작업"
                        },
                        "api_name": {
                            "type": "string",
                            "description": "API 이름 (소문자/숫자/밑줄)"
                        },
                        "description": {
                            "type": "string",
                            "description": "API 설명 (무엇을 반환하는지)"
                        },
                        "url_template": {
                            "type": "string",
                            "description": "전체 URL 템플릿. 예: https://apis.data.go.kr/...?serviceKey={ENV:KMA_API_KEY}&areaNo={area_no}"
                        },
                        "response_hint": {
                            "type": "string",
                            "description": "응답 해석 힌트 (선택)"
                        }
                    },
                    "required": ["action"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "manage_system_knowledge",
                "description": "시스템 자기지식(서버 구조·DB테이블/컬럼·로그·소스·도구 사용법) 관리. 서버를 분석하다 새로 알아낸 사실을 learn 으로 저장하면 이후 유사 질문 분석에 자동 회상·반영(코드 변경 불필요). 아는 지식 목록은 list, 삭제는 delete(시스템관리자 전용). 농장 재배/제어 노하우는 save_domain_knowledge, 질문 응대 방식은 manage_analysis_lesson 으로 구분.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["learn", "list", "delete", "audit"], "description": "수행 작업(audit=실제 스키마와 대조·자동갱신)"},
                        "text": {"type": "string", "description": "learn 시 지식 본문 — 사실과 적용조건(어떤 질문일 때 어떤 테이블/도구/컬럼)이 드러나게"},
                        "category": {"type": "string", "enum": ["db_schema", "logs", "source", "services", "tool_routing", "general"], "description": "지식 분류(기본 general)"},
                        "knowledge_id": {"type": "string", "description": "delete 시 대상 id(sysk_...) — list 로 확인"}
                    },
                    "required": ["action"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "set_trading_strategy",
                "description": "국내주식 자동매매 전략(철학) 설정. 농장주가 '앞으로 ~한 방식/철학으로 매매해줘, 이런 원칙으로 종목을 골라줘'처럼 주식 매매 전략·원칙·철학을 자연어로 말하면 strategy 에 그 원문을 담아 저장 — 즉시 활성 전략이 되어 다음 자동매매 스캔부터 반영(코드 변경 불필요). ⛔ 농장 재배/제어와 무관한 '주식 매매' 전략 전용.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "strategy": {"type": "string", "description": "매매 전략·철학 원문(자연어). 농장주 발화를 그대로 담되 판단 기준이 드러나게."},
                        "name": {"type": "string", "description": "전략 이름(선택). 미지정 시 날짜로 자동 명명."}
                    },
                    "required": ["strategy"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "manage_analysis_lesson",
                "description": "질문 분석 교훈 관리. 사용자가 '앞으로/다음부터 ~한 질문(요청)에는 ~하라'처럼 향후 질문 처리 방식을 가르치면 register 로 저장 — 등록 즉시 이후 모든 질문 분석에 자동 반영(코드 변경 불필요). '가르친 규칙/교훈 목록'은 list, 삭제는 delete(시스템관리자 전용).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["register", "list", "delete"],
                            "description": "수행 작업"
                        },
                        "lesson_text": {
                            "type": "string",
                            "description": "register 시 교훈 본문 — 사용자 지시 원문을 그대로 담되 적용 조건(어떤 질문일 때)과 행동(무엇을 하라)이 드러나게"
                        },
                        "lesson_id": {
                            "type": "string",
                            "description": "delete 시 대상 교훈 ID (lesson_...)"
                        }
                    },
                    "required": ["action"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "db_write_query",
                "description": "DB 데이터/스키마 변경(관리자 전용). UPDATE·INSERT·DELETE·DDL(CREATE/ALTER/DROP/TRUNCATE) 전부 가능합니다. 반드시 db_describe_table 로 구조 확인 후 작성하세요. UPDATE/DELETE 는 변경 전 자동 백업(최대 5000행)되고 전건 감사기록이 남습니다. ⛔ 보호 테이블 4개만 차단: relay_l_recording/sensor_l_recording(제어·실측 원본), kakao_token_m(시크릿), db_write_audit(감사). 그 외 모든 테이블은 자유롭게 변경 가능.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "단일 UPDATE 또는 INSERT 문"},
                        "reason": {"type": "string", "description": "변경 사유 (감사 기록용)"}
                    },
                    "required": ["sql"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "source_search",
                "description": "농장 시스템 소스코드 전역 검색(읽기 전용). 특정 기능/문구가 어느 파일·줄에 있는지 찾을 때 사용. 결과는 파일:줄:내용 형식.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "검색어(고정 문자열, 2자 이상)"},
                        "path": {"type": "string", "description": "검색 범위 디렉토리 (기본: 프로젝트 전체)"}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "source_read",
                "description": "소스 파일 내용 읽기(읽기 전용, 줄번호 포함, 1회 최대 400줄). source_search 로 찾은 위치의 코드를 분석·설명할 때 사용.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "프로젝트 상대 경로 (예: agri_ai_core/src/control/interlock.py)"},
                        "start_line": {"type": "integer", "description": "시작 줄 (기본 1)"},
                        "end_line": {"type": "integer", "description": "끝 줄 (기본 start+399)"}
                    },
                    "required": ["file_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "source_list",
                "description": "소스 파일 목록 조회(읽기 전용). 시스템 구조 파악이나 파일 위치 탐색에 사용.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "디렉토리 (기본: 프로젝트 루트)"},
                        "pattern": {"type": "string", "description": "파일명 필터 (부분 일치)"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "control_relay",
                "description": "재배사의 릴레이(장치)를 제어합니다. 단건 제어: device_name+action 사용. 일괄 제어: mode 사용 (reverse_all=전체반전, all_on=전체켜기, all_off=전체끄기). house_id='all'로 모든 재배사에 동시 일괄 제어 가능 (전 재배사 요청 시 사용). 사전 상태 조회 없이 즉시 제어 가능합니다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "farm_id": {
                            "type": "string",
                            "description": "농장 ID (선택사항)"
                        },
                        "house_id": {
                            "type": "string",
                            "description": "재배사 ID. 특정 재배사: '1', '2', '3'. 모든 재배사 일괄 제어: 'all'"
                        },
                        "device_name": {
                            "type": "string",
                            "description": "단건 제어 시 장치명 (relay_mapping의 device 값 사용)"
                        },
                        "action": {
                            "type": "string",
                            "description": "단건 제어 동작 (on: 켜기, off: 끄기, reverse: 현재 상태 반전)",
                            "enum": ["on", "off", "reverse"]
                        },
                        "mode": {
                            "type": "string",
                            "description": "일괄 제어 모드. reverse_all: 전체 반전, all_on: 전체 켜기, all_off: 전체 끄기",
                            "enum": ["reverse_all", "all_on", "all_off"]
                        }
                    },
                    "required": ["house_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "인터넷에서 최신 정보를 검색합니다. 날씨/뉴스/환율/주가/맛집/장소 추천/가격/제품 정보 등 실제 데이터가 필요한 질문에 우선 사용합니다. Google, Naver, Daum, DuckDuckGo, Bing 5개 검색엔진을 통합 검색합니다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "검색할 키워드(반드시 한국어로 작성). 사용자 질문의 핵심 의도를 구체적으로 포함하세요. 예: '정읍 날씨' → '정읍 오늘 날씨 기온'. 중국어/영어/일본어 등 외국어 query 절대 금지."
                        },
                        "n_results": {
                            "type": "integer",
                            "description": "검색 결과 개수 (선택, 3~20 권장)"
                        },
                        "auto_fetch_max": {
                            "type": "integer",
                            "description": "본문 자동 읽기 URL 개수 (선택, 1~5 권장)"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_url_content",
                "description": "URL의 웹페이지 본문 텍스트를 가져옵니다. 검색 결과의 상세 내용을 확인하거나, 사용자가 제공한 URL의 본문을 읽을 때 사용합니다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "읽어올 웹페이지 URL"
                        }
                    },
                    "required": ["url"]
                }
            }
        }
    ]



# ════════════════════════════════════════════════════════════════════════════
# 관리 도구 스키마 — get_available_tools() 에 병합
# ════════════════════════════════════════════════════════════════════════════
_ADMIN_TOOLS: List[Dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "set_house_control_mode",
        "description": "재배사 제어 모드를 수동(manual)/알고리즘(algorithm)/인공지능(ai) 중 하나로 전환합니다. 사용자가 '운용방식/제어모드를 ○○으로 바꿔달라'고 할 때 반드시 이 도구를 호출하세요. control_relay로는 모드 전환이 되지 않습니다.",
        "parameters": {"type": "object", "properties": {
            "house_id": {"type": "string", "description": "'1','2','3' 또는 'all' (전 재배사)"},
            "mode": {"type": "string", "enum": _control_modes_enum()},
            "farm_id": {"type": "string", "description": "농장 ID (생략 시 기본 농장)"}
        }, "required": ["house_id", "mode"]}}},
    {"type": "function", "function": {
        "name": "set_admin_directive",
        "description": ("관리자 강제 지시 등록 — 특정 장치를 지정 상태(ON/OFF)로 '해제 전까지' 강제 유지합니다. "
                        "사용자가 '유지해라/계속 꺼둬라/재부팅 후에도/별도 지시 전까지' 등 지속 요청을 하면 "
                        "control_relay(1회성)만으로는 자율 제어가 되돌리므로 반드시 이 도구를 호출하세요. "
                        "등록 즉시 LLM/agent/비상가드 판단보다 우선 적용됩니다(물리 인터록만 예외)."),
        "parameters": {"type": "object", "properties": {
            "house_id": {"type": "string", "description": "'1','2','3' 또는 'all'"},
            "device_name": {"type": "string", "description": "수온히터/포그생성/배수밸브/흡입팬/배출팬/조명/관수/순환밸브/흡입밸브/배출밸브 또는 시멘틱 flag"},
            "state": {"type": "string", "enum": ["ON", "OFF"]},
            "note": {"type": "string", "description": "지시 사유 (사용자 요청 요약)"},
            "farm_id": {"type": "string"}
        }, "required": ["house_id", "device_name", "state"]}}},
    {"type": "function", "function": {
        "name": "release_admin_directive",
        "description": ("관리자 강제 지시 해제 — 강제 유지 중인 장치를 자율 제어(LLM 판단)로 복귀시킵니다. "
                        "사용자가 '이제 풀어라/자동으로 돌려라/유지 해제' 요청 시 호출하세요."),
        "parameters": {"type": "object", "properties": {
            "house_id": {"type": "string", "description": "'1','2','3' 또는 'all'"},
            "device_name": {"type": "string"},
            "farm_id": {"type": "string"}
        }, "required": ["house_id", "device_name"]}}},
    {"type": "function", "function": {
        "name": "db_list_tables",
        "description": "시스템 DB(public 스키마)의 전체 테이블 목록과 추정 행수를 조회합니다. 사용자가 '어떤 테이블/데이터가 있나' 물으면 먼저 호출하세요.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "db_describe_table",
        "description": "특정 테이블의 컬럼 구조(이름/타입/널허용)를 조회합니다. db_read_query 작성 전 구조 파악에 사용하세요.",
        "parameters": {"type": "object", "properties": {
            "table_name": {"type": "string"}
        }, "required": ["table_name"]}}},
    {"type": "function", "function": {
        "name": "db_read_query",
        "description": ("읽기전용 SELECT 쿼리를 실행해 시스템 데이터를 직접 조회합니다(최대 200행, 5초 제한). "
                        "기존 전용 도구(get_farm_realtime_data 등)로 안 되는 임의 데이터 질문에 사용. "
                        "쓰기/DDL 은 자동 거부됩니다."),
        "parameters": {"type": "object", "properties": {
            "sql": {"type": "string", "description": "단일 SELECT/WITH 문"},
            "limit": {"type": "integer", "description": "최대 행수 (기본 50, 상한 200)"}
        }, "required": ["sql"]}}},
    {"type": "function", "function": {
        "name": "manage_control_prompt",
        "description": ("농장제어/agent LLM 의 시스템 프롬프트(control_prompt_m)를 조회·갱신합니다. "
                        "action=list(블록 목록)|get(본문 조회)|update(본문 교체, 관리자 전용, 즉시 반영). "
                        "사용자가 제어 룰/프롬프트 변경을 요청하면 get 으로 현재 본문 확인 후 update 하세요."),
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "get", "update"]},
            "block_id": {"type": "string"},
            "body_text": {"type": "string", "description": "update 시 새 본문 전문"}
        }, "required": ["action"]}}},
    {"type": "function", "function": {
        "name": "set_growth_stage",
        "description": "재배사의 생육단계를 변경합니다(발아기/생육기/수확기/휴지기). 사용자 요청이 있을 때만 호출하세요.",
        "parameters": {"type": "object", "properties": {
            "house_id": {"type": "string"},
            "stage": {"type": "string", "enum": _growth_stages_enum()},
            "farm_id": {"type": "string"}
        }, "required": ["house_id", "stage"]}}},
    {"type": "function", "function": {
        "name": "set_circulation_mode",
        "description": "순환모드를 강제합니다(내부순환/외부순환/흡입순환/배기순환/순환정지). 댐퍼+팬 조합을 자동 계산해 즉시 릴레이에 반영합니다. ctrl_type='manual'일 때 영속적입니다 (algorithm/ai 모드는 다음 주기에 재계산됨).",
        "parameters": {"type": "object", "properties": {
            "house_id": {"type": "string"},
            "mode": {"type": "string", "enum": _circulation_mode_enum()},
            "farm_id": {"type": "string"}
        }, "required": ["house_id", "mode"]}}},
    {"type": "function", "function": {
        "name": "set_schedule",
        "description": "조명/관수 자동 스케줄을 추가·삭제·조회합니다. action=list로 현재 스케줄 확인 후 add/delete를 권장.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["add", "delete", "list"]},
            "house_id": {"type": "string", "description": "특정 재배사 필수 (all 불가)"},
            "unit_type": {"type": "string", "enum": ["light", "water"]},
            "start_time": {"type": "string", "description": "'HH:MM' (add·delete 필수)"},
            "end_time": {"type": "string", "description": "'HH:MM' (add 필수)"},
            "interval_min": {"type": "integer", "description": "관수 반복 간격(분). 조명은 null"},
            "weekdays": {"type": "string", "description": "'daily' 또는 'mon,tue,wed,...'"},
            "farm_id": {"type": "string"}
        }, "required": ["action", "house_id", "unit_type"]}}},
    {"type": "function", "function": {
        "name": "override_ai_thresholds",
        "description": "재배사별 환경 임계값(SENSOR_M_SETTING)을 조회(get)/변경(set)/초기화(reset). set 은 DB 즉시 반영되어 다음 제어 사이클부터 적용. 사용자가 'CO2는 2000 넘지 않게', '온도 상한을 30도로' 처럼 기준값 변경을 지시하면 set 호출 (예: key=CO2_HIGH value=2000). house_id 'all'=전 재배사.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["get", "set", "reset"]},
            "key": {"type": "string", "description": "TEMP_LOW/TEMP_HIGH/TEMP_CRITICAL_LOW/TEMP_CRITICAL_HIGH/HUMIDITY_LOW/HUMIDITY_HIGH/HUMIDITY_CRITICAL_LOW/HUMIDITY_CRITICAL_HIGH/CO2_LOW/CO2_HIGH/CO2_CRITICAL_HIGH/WATER_TEMP_LOW/WATER_TEMP_HIGH/WATER_TEMP_CRITICAL_LOW/WATER_TEMP_CRITICAL_HIGH/BUDDING_TEMP_LOW/BUDDING_TEMP_HIGH"},
            "value": {"type": "number", "description": "set 시 새 값"},
            "house_id": {"type": "string", "description": "재배사 번호 또는 'all'(기본 — 전 재배사)"}
        }, "required": ["action"]}}},
    {"type": "function", "function": {
        "name": "set_alert_interval",
        "description": "카카오톡 알림 발송 최소 간격(분)을 설정합니다. ⛔ 제어와 채팅 알림은 그대로 유지되고 카카오 발송 빈도만 낮춥니다 — '제어는 계속하되 카카오 알림만 N시간마다' 요구에 사용. farm_id 지정 시 그 농장 전체 구독(자율제어 구독 포함)에 일괄 적용. 예: '알림을 2시간마다로' → interval_min=120. interval_min=0 은 쿨다운 해제(매번).",
        "parameters": {"type": "object", "properties": {
            "interval_min": {"type": "integer", "description": "카카오 발송 최소 간격(분). 2시간=120, 해제=0"},
            "farm_id": {"type": "string", "description": "농장 전체 적용(기본 — 세션 농장 자동)"},
            "subscription_id": {"type": "integer", "description": "특정 구독만 적용(선택)"}
        }, "required": ["interval_min"]}}},
    {"type": "function", "function": {
        "name": "edit_source",
        "description": "운영 소스(agri_ai_core)를 변경합니다. 반드시 source_read 로 현재 전문을 확인한 뒤 전문을 넘기세요. 구문 검증 → 쓰기 → pytest 순으로 진행하며 **테스트 실패 시 자동 원복**됩니다. 성공해도 서비스 반영은 restart_service 를 따로 호출해야 합니다. ⛔ 안전장치(인터록·비상가드·수온안전·관리자지시·보호테이블·스크립트/서비스 경계·이 도구 자신)와 시크릿은 변경 불가 — 필요하면 농장주에게 요청하세요.",
        "parameters": {"type": "object", "required": ["path", "content"], "properties": {"path": {"type": "string", "description": "프로젝트 상대경로 (.py). 예: agri_ai_core/src/ai/tools_logs.py"}, "content": {"type": "string", "description": "파일 전문(부분 패치 아님). source_read 로 현재 내용을 먼저 확인하라"}, "reason": {"type": "string", "description": "변경 사유"}, "test_target": {"type": "string", "description": "검증할 테스트 경로(기본 tests/ 전체)"}}}}},
    {"type": "function", "function": {
        "name": "revert_source",
        "description": "소스 변경을 감사기록의 '변경 전' 내용으로 되돌립니다. 변경 후 문제가 발견됐을 때 사용.",
        "parameters": {"type": "object", "required": ["audit_id"], "properties": {"audit_id": {"type": "integer", "description": "list_source_edits 의 감사기록 id"}, "reason": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "list_source_edits",
        "description": "최근 소스 변경 이력(경로·사유·테스트통과·원복여부). revert_source 대상 확인용.",
        "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "description": "기본 10, 최대 50"}}}}},
    {"type": "function", "function": {
        "name": "get_server_resources",
        "description": "농장관리 서버의 실제 리소스를 조회합니다 — CPU(코어·사용률·부하평균), 메모리(RAM·스왑), 디스크(경로별 사용량·여유), GPU(모델·메모리·사용률·온도), agri_ai_core 서비스 가동 상태. ⛔ '서버 리소스/상태', 'CPU·메모리·디스크·GPU 어때', '서버 점검' 류 질문은 반드시 이 도구를 쓰세요 — search_web 은 우리 서버 상태를 알 수 없어 일반론 기사만 나옵니다(2026-07-17 실제 오답 사례).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "restart_service",
        "description": "서비스를 재기동하고 헬스체크합니다(실패 시 1회 자동 재시도). 서비스가 죽었거나 응답이 없을 때 사용. ⛔ 정지(stop)는 제공하지 않습니다 — 농장 무제어 방지. PostgreSQL/ChromaDB 는 연쇄영향으로 대상에서 제외됩니다.",
        "parameters": {"type": "object", "required": ["service_no"], "properties": {"service_no": {"type": "integer", "description": "1=Ollama 4=Scheduler 5=FastAPI 16=Agent Monitor 17=Agent Worker 19=Event Listener"}, "reason": {"type": "string", "description": "재기동 사유"}}}}},
    {"type": "function", "function": {
        "name": "service_status",
        "description": "특정 서비스의 현재 상태(헬스체크) 조회.",
        "parameters": {"type": "object", "required": ["service_no"], "properties": {"service_no": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "list_services",
        "description": "agriAiCore 에 등록된 **전체 서비스**의 가동 상태 — 사용자 서비스(Scheduler·FastAPI·Web/Shop Backend·Agent Monitor/Worker·Event Listener·Camera), 시스템 서비스(Nginx), 패키지 서비스(Ollama·PostgreSQL·ChromaDB·SearXNG·ChromaFlow) 15개. '서비스 상태 확인/보고', '어떤 서비스가 돌고 있나', '시스템 서비스 점검' 류 질문에 사용. restartable=true 인 것만 restart_service 로 재기동 가능합니다. CPU/메모리/디스크/GPU 까지 필요하면 get_server_resources 를 쓰세요.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "write_script",
        "description": "python 분석 스크립트를 작성/수정합니다(scripts/llm/ 한정). 전용 도구·db_read_query 로 안 되는 계산·집계·가공이 필요할 때 직접 짜서 run_script 로 실행하세요. 작성 전 구문 검증되어 깨진 코드는 저장되지 않습니다. 운영 소스(agri_ai_core)는 이 도구로 못 바꿉니다.",
        "parameters": {"type": "object", "required": ["script", "content"], "properties": {"script": {"type": "string", "description": "파일명 (.py). scripts/llm/ 안에만 가능"}, "content": {"type": "string", "description": "python 소스 전문. 작성 전 구문 검증됨"}, "reason": {"type": "string", "description": "작성 사유"}}}}},
    {"type": "function", "function": {
        "name": "run_script",
        "description": "작성한 스크립트를 실행하고 stdout/stderr 를 돌려줍니다(sudo 없음, timeout 제한). 실패하면 stderr 를 읽고 write_script 로 고쳐 재시도하세요.",
        "parameters": {"type": "object", "required": ["script"], "properties": {"script": {"type": "string", "description": "실행할 파일명 (.py)"}, "args": {"type": "array", "items": {"type": "string"}, "description": "명령행 인자(선택)"}, "timeout": {"type": "integer", "description": "초 (기본 60, 최대 300)"}, "reason": {"type": "string", "description": "실행 사유"}}}}},
    {"type": "function", "function": {
        "name": "list_scripts",
        "description": "scripts/llm/ 의 스크립트 목록(이름·크기·수정시각).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "read_script",
        "description": "스크립트 본문을 읽습니다. 수정 전 현재 내용 확인용.",
        "parameters": {"type": "object", "required": ["script"], "properties": {"script": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "mcp_call",
        "description": "등록된 MCP 서버의 도구를 직접 호출합니다. 웹/지역/쇼핑/지식iN 검색(naver-search 21종), 학술논문 검색·다운로드(paper-search 57종 — arxiv/pubmed/semantic scholar), 파일·로그 읽기(filesystem), 메타검색(searxng) 등 전용 도구로 못 하는 일에 사용. args 를 모르면 mcp_list_tools(server=...) 로 먼저 스키마를 확인하세요. 예: 상황버섯 재배 논문 → server='paper-search', tool='search_arxiv', args={'query':'Phellinus linteus cultivation'}. 예: 정읍 농자재상 → server='naver-search', tool='search_local', args={'query':'정읍 농자재'}.",
        "parameters": {"type": "object", "required": ["server", "tool"], "properties": {"server": {"type": "string", "description": "MCP 서버명 (naver-search, paper-search, filesystem, searxng 등)"}, "tool": {"type": "string", "description": "그 서버의 도구명"}, "args": {"type": "object", "description": "도구 인자 (스키마는 mcp_list_tools 로 확인)"}, "timeout": {"type": "integer", "description": "초 (기본 45, 최대 120)"}}}}},
    {"type": "function", "function": {
        "name": "mcp_list_tools",
        "description": "등록된 MCP 서버 목록과 각 서버의 도구·스키마를 조회합니다. server 생략 시 서버 이름만, 지정 시 그 서버의 도구 전체. mcp_call 호출 전에 도구명·인자를 확인하는 용도.",
        "parameters": {"type": "object", "properties": {"server": {"type": "string", "description": "생략 시 서버 목록, 지정 시 그 서버의 도구 상세"}}}}},
    {"type": "function", "function": {
        "name": "manage_mcp_server",
        "description": "MCP 서버를 스스로 추가/제거/확인합니다(.vscode/mcp.json 직접 등록 — 코드·재기동 불필요). 사용자가 '○○ MCP 를 추가/등록해달라'고 하면 이 도구로 add 하세요. add 후 mcp_call/mcp_list_tools 로 즉시 사용 가능. action: list(등록 목록), get(설정 조회), add/update(추가·수정), remove(제거), test(연결·도구 확인). stdio 서버는 command(런처)+args, HTTP 서버는 url 로 등록. API 키 등 시크릿은 env 에 '${환경변수명}' 플레이스홀더로 넣으세요(평문 금지). 예: add name='time', command='uvx', args=['mcp-server-time']. 등록/제거는 시스템관리자 전용.",
        "parameters": {"type": "object", "required": ["action"], "properties": {
            "action": {"type": "string", "enum": ["list", "get", "add", "update", "remove", "test"], "description": "수행 동작"},
            "name": {"type": "string", "description": "서버 이름(영문/숫자로 시작, 2~60자). list 외 필수"},
            "command": {"type": "string", "description": "stdio 런처: npx/uvx/uv/python/node/deno/bunx/docker 중 하나"},
            "args": {"type": "array", "items": {"type": "string"}, "description": "command 인자 배열 (예: ['mcp-server-time'])"},
            "env": {"type": "object", "description": "환경변수 {키:값}. 시크릿은 '${VAR}' 형태 플레이스홀더 권장"},
            "url": {"type": "string", "description": "HTTP 형 MCP 서버 URL(command 대신)"},
            "transport": {"type": "string", "description": "url 형의 전송 타입(기본 http)"}
        }}}},
    {"type": "function", "function": {
        "name": "remote_status",
        "description": "원격 서버에 SSH(키 인증)로 접속해 종합 상태를 이 서버처럼 조회합니다 — 호스트·가동시간·부하·CPU·메모리·디스크·상위 프로세스·서비스(running/failed)·GPU. 전부 read-only. 사용자가 '○○ 서버 상태 봐줘', '원격 서버 리소스 확인'을 요청하면 사용. host 는 등록이름(manage_remote_host) 또는 'user@host:port'.",
        "parameters": {"type": "object", "required": ["host"], "properties": {
            "host": {"type": "string", "description": "등록이름 또는 user@host:port"}}}}},
    {"type": "function", "function": {
        "name": "remote_run",
        "description": "원격 서버에서 명령을 실행합니다. 조회 명령(cat/df/ps/systemctl status/journalctl 등)은 즉시 실행, 변경성 명령(rm/systemctl restart/설치 등)은 실행하지 않고 관리자 카카오 승인요청 후 승인 시에만 집행합니다.",
        "parameters": {"type": "object", "required": ["host", "command"], "properties": {
            "host": {"type": "string", "description": "등록이름 또는 user@host:port"},
            "command": {"type": "string", "description": "실행할 셸 명령"}}}}},
    {"type": "function", "function": {
        "name": "compare_remote_sources",
        "description": "두 재배사 라즈베리파이의 소스(농장관리 프로그램)를 결정적으로 비교. host_a·host_b 만 주면 각 호스트의 소스 경로를 자동탐지(1·3호=~/FarmUnits, 2호=~/SmartFarm)해 한쪽에만 있는 파일과 이름 같고 내용 다른 파일을 정확히 반환(LLM 대조 불필요). 경로는 자동이라 보통 지정 불필요(필요시 path_a/path_b). 소스 비교·틀린 파일·재배사 프로그램 차이 요청에 1순위.",
        "parameters": {"type": "object", "required": ["host_a", "host_b"], "properties": {
            "host_a": {"type": "string", "description": "비교 대상 A(예: jaebaesa1)"},
            "host_b": {"type": "string", "description": "비교 대상 B(예: jaebaesa3)"},
            "path": {"type": "string", "description": "소스 루트(기본 ~/FarmUnits, 2호는 ~/SmartFarm)"},
            "pattern": {"type": "string", "description": "파일 패턴(기본 *.py)"},
            "show_diff": {"type": "boolean", "description": "내용 다른 파일의 라인 diff 첨부(선택)"}}}}},
    {"type": "function", "function": {
        "name": "manage_remote_host",
        "description": "원격 서버 접속정보 등록부. action: list/get/register/remove. register 시 name·host_spec('user@host:port')·identity_path(SSH 키 경로, 선택). 등록/삭제는 시스템관리자. 등록 후 remote_status/remote_run 에서 name 으로 참조. SSH 키 인증만 사용.",
        "parameters": {"type": "object", "required": ["action"], "properties": {
            "action": {"type": "string", "enum": ["list", "get", "register", "remove"]},
            "name": {"type": "string", "description": "호스트 별칭"},
            "host_spec": {"type": "string", "description": "user@host:port"},
            "identity_path": {"type": "string", "description": "SSH 개인키 경로(선택)"}}}}},
    {"type": "function", "function": {
        "name": "approve_remote_command",
        "description": "보류된 변경성 원격 명령(remote_run 이 승인요청한 것)을 승인·집행합니다(시스템관리자 전용).",
        "parameters": {"type": "object", "required": ["request_id"], "properties": {
            "request_id": {"type": "integer", "description": "승인할 요청 id"}}}}},
    {"type": "function", "function": {
        "name": "search_logs",
        "description": "운영 로그를 검색·분석합니다(읽기 전용). 사용자가 '오늘 에러 있었나', '○○ 로그 보여줘', 'LLM 실패 몇 건', '무슨 일이 있었나'처럼 시스템에서 실제 일어난 일을 물으면 반드시 이 도구를 사용하세요 — 추측 금지. matched 가 전체 매칭 건수이므로 '몇 건' 질문은 그 값으로 답하세요. 로그가 3GB 규모라 전체 읽기는 불가하며 검색/필터로만 접근합니다.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "검색어. 공백으로 나눈 여러 단어는 AND 조건 (예: '순환밸브 relay_10')"},
            "level": {"type": "string", "enum": ["ERROR", "WARNING", "INFO", "DEBUG", "CRITICAL"], "description": "로그 레벨 필터. '에러/오류' 질문이면 ERROR"},
            "date": {"type": "string", "description": "'today' 또는 'YYYY-MM-DD'. 생략 시 최신 로그"},
            "log_type": {"type": "string", "description": "로그 종류. 기본 'ai'(제어/AI). 예: ai, web, scheduler, api. 모르면 list_log_files 로 확인"},
            "max_results": {"type": "integer", "description": "반환 줄수 (기본 50, 최대 200)"}
        }}}},
    {"type": "function", "function": {
        "name": "list_log_files",
        "description": "조회 가능한 로그 파일 목록(이름·크기·최종수정)을 반환합니다. search_logs 의 log_type/date 를 정하기 어려울 때 먼저 호출하세요.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "set_alert_level",
        "description": "카카오톡 알림 발송 최소 심각도를 설정합니다. ⛔ 제어와 채팅 알림은 그대로 유지되고 카카오 발송만 걸러집니다 — '심각한 문제일 때만 알려줘'(critical), '경고 이상만'(warning), '전부 알려줘'(info) 요구에 사용. 비상(critical) 알림은 어떤 설정에서도 항상 즉시 발송됩니다.",
        "parameters": {"type": "object", "properties": {
            "level": {"type": "string", "enum": ["info", "warning", "critical"],
                      "description": "info=전부, warning=경고 이상, critical=심각한 것만"}
        }, "required": ["level"]}}},
    {"type": "function", "function": {
        "name": "get_system_status",
        "description": "시스템 현재 운영 상태를 종합 조회합니다. 각 재배사의 제어모드·생육단계·AI순환루프 상태·등록된 APScheduler Job 등을 반환. 사용자가 '현재 시스템 상황/제어방식/스케줄이 어떻게 돌아가는지' 물으면 반드시 이 도구를 호출하세요.",
        "parameters": {"type": "object", "properties": {
            "farm_id": {"type": "string"}
        }}}},
    {"type": "function", "function": {
        "name": "get_camera_view",
        "description": "지정한 재배사의 카메라 현재 프레임을 실제로 촬영하고 gemma3 비전+색상/곰팡이 휴리스틱으로 판독해 반환합니다. 사용자가 '카메라에 뭐가 보여', '재배사 지금 영상 어때', '곰팡이/오염 있는지 봐줘', '균상 상태 확인'처럼 현재 영상 상태를 물을 때 호출하세요. 촬영 실패(원격 보드 미응답) 시 실패 사유를 정직하게 반환합니다.",
        "parameters": {"type": "object", "properties": {
            "farm_id": {"type": "string"},
            "house_id": {"type": "string", "description": "재배사 번호(필수, 0/all 불가 — 카메라는 특정 재배사)"}
        }, "required": ["house_id"]}}},
    # ─── Agent 모니터링 도구 ───
    {"type": "function", "function": {
        "name": "schedule_monitor",
        "description": "사용자가 지정한 시간대에 재배사 센서 임계치 이탈을 단순 감시하는 Job을 등록합니다. 이상(온도·습도·CO2 임계 이탈) 감지 시 채팅 알림을 자동 발행합니다. LLM ReAct 판단, 판단 근거 보고, 릴레이 제어값 보고는 수행하지 않습니다. 사용자가 '야간 저온 이상만 감시해줘', 'CO2 임계치 넘으면 알려줘'처럼 단순 이상 감지를 요청할 때 호출하세요. '○분마다 분석/보고/판단근거/릴레이 제어값' 요청은 agent_subscribe 를 사용해야 합니다.",
        "parameters": {"type": "object", "properties": {
            "intent": {"type": "string", "description": "사용자 의도 한 줄 (알림 메시지에 포함, 예: '야간 저온 감시')"},
            "start_time": {"type": "string", "description": "시작 시각 ('HH:MM' 또는 'YYYY-MM-DD HH:MM')"},
            "end_time": {"type": "string", "description": "종료 시각"},
            "interval_min": {"type": "integer", "description": "체크 주기 (분, 1~1440). 기본 30"},
            "house_ids": {"type": "string", "description": "'1,2,3' 또는 'all'. 생략 시 전 재배사"},
            "farm_id": {"type": "string"},
            "alert_on_normal": {"type": "boolean", "description": "true면 정상 상태도 매 주기 알림. 기본 false (이상시만)"}
        }, "required": ["intent", "start_time", "end_time", "interval_min"]}}},
    {"type": "function", "function": {
        "name": "list_monitors",
        "description": "현재 등록된 Agent 모니터링 Job 목록을 조회합니다. 사용자가 '지금 어떤 감시가 돌아가고 있는지' 물으면 호출.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "cancel_monitor",
        "description": "특정 Agent 모니터링 Job을 취소합니다. job_id는 list_monitors 결과에서 확보.",
        "parameters": {"type": "object", "properties": {
            "job_id": {"type": "string"}
        }, "required": ["job_id"]}}},
    # ─── 반복 Agent 구독 ───
    {"type": "function", "function": {
        "name": "agent_subscribe",
        "description": (
            "사용자 채팅 요청을 받아 ai_monitor_agent (ReAct) 를 반복 실행하는 구독을 등록합니다. "
            "사용자가 '○분/○시간마다 분석/모니터링/감시', '매 시간 ○호기 봐줘', "
            "'센서값·판단 근거·릴레이 제어값을 반복 보고' 등 "
            "*반복 + ReAct 다단계 분석/보고* 의도를 보일 때 호출. "
            "결과는 매 사이클 agent_user_alerts 큐에 적재되어 채팅창으로 전달. "
            "schedule_monitor (단순 임계값 체크) 와 다름. 5분~24시간 주기, 사용자당 5건 한도."),
        "parameters": {"type": "object", "properties": {
            "task": {"type": "string", "description": "agent 가 매 사이클 수행할 작업 (한국어 한 문장)"},
            "interval_min": {"type": "integer", "description": "사이클 주기 (분, 5~1440)"},
            "farm_id": {"type": "integer", "description": "농장 ID. 기본 1"},
            "house_id": {"type": "integer", "description": "호기 ID (선택, 다호기면 생략)"},
            "user_id": {"type": "string", "description": "채팅 발신자 식별 (선택)"},
            "intent": {"type": "string", "description": "사용자 자연어 원문 (감사 로그용)"}
        }, "required": ["task", "interval_min"]}}},
    {"type": "function", "function": {
        "name": "list_agent_subscriptions",
        "description": "현재 등록된 반복 agent 구독 목록을 조회합니다. "
                       "사용자가 '내가 등록한 모니터링 뭐 있어?' 등 물을 때 호출. "
                       "schedule_monitor 와는 별개 (이건 ai_monitor_agent ReAct 분석 반복).",
        "parameters": {"type": "object", "properties": {
            "user_id": {"type": "string", "description": "특정 사용자만 조회 (선택)"},
            "include_default": {"type": "boolean", "description": "시스템 default cron 포함 (기본 false)"}
        }}}},
    {"type": "function", "function": {
        "name": "cancel_agent_subscription",
        "description": "특정 agent 구독을 취소합니다. id 는 list_agent_subscriptions 결과에서 확보.",
        "parameters": {"type": "object", "properties": {
            "subscription_id": {"type": "integer"},
            "user_id": {"type": "string", "description": "발신자 검증용 (선택)"},
            "reason": {"type": "string", "description": "취소 사유 (선택)"}
        }, "required": ["subscription_id"]}}},
    {"type": "function", "function": {
        "name": "get_pending_alerts",
        "description": (
            "미읽 agent 알림을 가져와 사용자에게 전달합니다. "
            "사용자가 '내 알림 있어?', '뭐 알림 왔어?' 등 물을 때 또는 "
            "농장 상태 질문 시 백그라운드 알림 정황을 함께 제시할 때 호출. "
            "기본적으로 mark_read=true 로 호출 후 read 처리."),
        "parameters": {"type": "object", "properties": {
            "user_id": {"type": "string", "description": "특정 사용자만 조회"},
            "limit": {"type": "integer", "description": "최대 알림 수 (기본 10, max 50)"},
            "mark_read": {"type": "boolean", "description": "조회 후 read 처리 (기본 true)"}
        }}}},
    # ─── Agent 즉시 1회 분석 ───
    {"type": "function", "function": {
        "name": "agent_one_shot",
        "description": (
            "AI 모니터링 Agent (ReAct 도구 사용) 를 지금 즉시 1회 실행합니다. "
            "사용자가 '지금/즉시/한번/방금 분석해줘', '○호기 상태 진단해', "
            "'○호기 봐줘' 등 *반복 없이 한 번* 자율 분석을 요청할 때 호출. "
            "schedule_monitor 와 다름 — schedule_monitor 는 시간 주기 반복 감시, "
            "agent_one_shot 은 1회 ReAct 분석 후 final 보고. 응답시간 100~250초."),
        "parameters": {"type": "object", "properties": {
            "task": {"type": "string",
                     "description": "Agent 가 수행할 작업 (한국어 한 문장). 예: "
                                    "'1호기 수온과 내부온도 현재 상태 진단'"},
            "farm_id": {"type": "integer", "description": "농장 ID. 기본 1"}
        }, "required": ["task"]}}},
]


# ────────────────────────────────────────────────────────────────────
# 기존 도구 목록에 관리 도구를 병합 (이름 중복 방지).
# ────────────────────────────────────────────────────────────────────
def _inject_admin_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    existing_names = {t.get("function", {}).get("name") for t in tools}
    for t in _ADMIN_TOOLS:
        if t["function"]["name"] not in existing_names:
            tools.append(t)
    return tools


# get_available_tools 는 위에 이미 정의됨. 리턴 시점에 관리 도구를 병합하도록 모듈 로드 후 한 번만 패치.
_original_get_available_tools = get_available_tools


# ────────────────────────────────────────────────────────────────────
# 도구 목록 — DB 우선 / 코드 폴백.
# 환경변수 USE_DB_TOOLS=1 일 때 prompt_registry.get_tools() 우선 사용.
# DB 비어있거나 예외 시 코드 정의 도구로 자동 폴백.
# ────────────────────────────────────────────────────────────────────
def get_available_tools() -> List[Dict[str, Any]]:  # type: ignore[no-redef]
    import os as _os
    if _os.getenv("USE_DB_TOOLS", "0") == "1":
        try:
            from agri_ai_core.src.prompt_registry import get_tools as _registry_get_tools
            rows = _registry_get_tools()
            if rows:
                return [
                    {"type": "function", "function": {
                        "name": r["tool_id"],
                        "description": r["description"],
                        "parameters": r["schema_json"],
                    }}
                    for r in rows
                ]
        except Exception:
            pass
    return _inject_admin_tools(_original_get_available_tools())


# ════════════════════════════════════════════════════════════════════════════
# 시스템 프롬프트 생성
# Tool Use를 위한 시스템 프롬프트 생성
# Args: farm_name: 농장명
#       farm_info: 농장 기본 정보 문자열 (DB에서 조회한 농장/재배사/작물 정보)
# Returns: str: 시스템 프롬프트
# ════════════════════════════════════════════════════════════════════════════
def get_system_prompt_with_tools(farm_name: str = None, farm_info: str = None, speech_style: str = "male") -> str:
    farm_display = farm_name if (farm_name and "농장" in farm_name) else f"{farm_name} 농장" if farm_name else "스마트팜"
    now = datetime.now()
    weekdays = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']
    current_datetime = f"{now.strftime('%Y년 %m월 %d일')} {weekdays[now.weekday()]} {now.strftime('%H시 %M분')}"

    farm_info_section = f"\n\n**농장 기본 정보:**\n{farm_info}" if farm_info else ""

    # 을/를 조사 자동 결정 (받침 유무)
    last_char = farm_display[-1] if farm_display else ""
    josa = "을" if last_char and (ord(last_char) - 0xAC00) % 28 > 0 else "를"

    # 대화체에 따른 말투 규칙 분기
    if speech_style == "female":
        tone_rules = (
            "**말투 (최우선 절대 규칙 — 부드러운 해요체):**\n"
            "이 규칙은 다른 모든 규칙보다 우선합니다. 반드시 아래 말투를 지키세요.\n"
            "- 모든 문장을 반드시 부드러운 해요체로 끝내세요: ~예요, ~이에요, ~해요, ~네요, ~거예요, ~드릴게요, ~좋겠어요, ~있어요, ~없어요, ~돼요, ~할게요, ~볼게요\n"
            "- 절대 사용 금지 어미: ~합니다, ~입니다, ~습니다, ~됩니다, ~겠습니다 (이것은 딱딱한 남성체입니다)\n"
            "- 절대 사용 금지 어미: ~한다, ~된다, ~이다, ~했다 (이것은 반말입니다)\n"
            "- 따뜻하고 친근하게 농장주님을 배려하는 다정한 톤으로 응대하세요.\n"
            "- 문장 끝에 '~'(물결)를 자연스럽게 가끔 사용하세요.\n"
            "- 올바른 예시:\n"
            "  \"지금 온도가 25.3°C예요. 적정 범위 안에 있어서 안심하셔도 돼요~\"\n"
            "  \"습도가 조금 높은 편이네요. 환기를 한번 해보시는 게 좋을 것 같아요.\"\n"
            "  \"오늘 날씨가 좀 쌀쌀한 편이에요. 보온에 신경 쓰시는 게 좋겠어요.\"\n"
            "- 잘못된 예시 (사용 금지):\n"
            "  \"온도가 25.3°C입니다.\" → \"온도가 25.3°C예요.\"\n"
            "  \"확인이 필요합니다.\" → \"확인이 필요해요.\"\n"
            "  \"환기를 권장합니다.\" → \"환기를 해보시는 게 좋을 것 같아요.\""
        )
    else:
        tone_rules = (
            "**말투 (절대 규칙):**\n"
            "- 모든 문장을 반드시 존댓말 어미(~합니다/~입니다/~습니다/~됩니다/~겠습니다)로 끝내세요.\n"
            "- 설명·나열·요약도 존댓말 문장으로 마무리하세요. 예: \"25°C입니다.\" \"확인이 필요합니다.\"\n"
            "- 반말 어미(~한다/~된다/~이다/~했다/~있다/~없다) 사용 절대 금지합니다.\n"
            "- 불릿/번호 항목도 문장으로 끝날 때는 존댓말로 마무리하세요."
        )

    return f"""당신은 {farm_display}{josa} 운영하는 농장주를 지원하는 AI 도우미입니다.
**현재:** {current_datetime}{farm_info_section}

{tone_rules}

**도구 사용 규칙:**
1. 농장/센서/릴레이/생육 **조회·분석** 질문: `get_farm_realtime_data`(data_type='all')+`search_farm_knowledge` 반드시 모두 사용합니다. 수치/상태 추측은 금지합니다. 센서와 릴레이를 동시에 조회하려면 data_type='all'을 사용하세요(sensor/relay 분리 호출 금지). 단, 장치 **제어(켜기/끄기/설정)** 요청에는 `search_farm_knowledge`를 호출하지 않습니다(규칙 8 참조).
   - **다중 재배사 질문 (절대 규칙)**: "각 재배사", "전체", "모든 재배사" 등 복수 재배사 요청 시 반드시 농장의 모든 재배사에 대해 각각 `get_farm_realtime_data`를 호출해야 합니다. 재배사 구성은 농장별로 가변(위 [농장 기본 정보]의 재배사 목록 참고)이며, 일부 재배사만 응답하는 것은 금지합니다. house_id는 해당 농장의 실제 hous_id 값을 정확히 사용하세요.
   - 도구 결과에 포함된 **모든 데이터**(센서값, 릴레이 상태)를 빠짐없이 답변에 포함해야 합니다. 데이터를 생략하거나 일부만 표시하는 것은 금지합니다.
   - **센서값 적정 여부 판단**: `get_farm_realtime_data` 응답의 `environment_thresholds`(적정 범위)와 실제 센서값을 비교하여 "적정/저온/고온/비상" 상태를 판단하세요. 임계값 없이 "적정 범위"를 추측하지 마세요.
   - **AI vs 알고리즘 제어값 비교**: `get_farm_realtime_data` 응답의 `ai_environment_judgment`에 알고리즘이 권장하는 릴레이 상태가 포함됩니다. 현재 릴레이(relay_mapping)와 비교하여 차이점을 분석하세요. 릴레이/제어값 비교 질문에는 `search_farm_knowledge` 대신 반드시 `get_farm_realtime_data`를 사용하세요.
2. **학습데이터 삭제 요청** ("삭제", "지워", "제거" + 파일명): 반드시 `delete_farm_knowledge` 도구를 즉시 호출합니다. 확인 질문 없이 바로 실행하세요. farm_id는 현재 사용자의 농장 ID를 사용합니다. 삭제 결과(success/deleted_count)를 그대로 안내하세요. **삭제 완료 후 `search_farm_knowledge`를 재호출하여 확인하지 마세요** — 재검색 결과에는 웹 지식(web_knowledge) 항목이 포함될 수 있어 삭제 실패로 오인할 수 있습니다.
2-1. 파일/문서/학습/RAG/데이터/요약/내용/정리 관련 질문: `search_farm_knowledge` 반드시 사용합니다. 파일명이 포함된 질문은 해당 파일명을 query와 file_name 파라미터에 넣어 반드시 검색합니다. "없다/모른다" 답변 전에 반드시 도구로 검색해야 합니다. 파일 목록 응답의 `file_list[].farm_scope` 값을 반드시 표시하세요 — "시스템 농장"은 전체 공용 데이터, "농장ID:xxx"는 해당 농장 전용 데이터입니다. 현재 대화 농장명으로 farm_scope를 추측하거나 변경하지 마세요.
3. 사실·조사·검색 요청(주소/가격/찾아줘/알아봐줘/설명해줘/알려줘): `search_farm_knowledge` → 부족하면 `search_web` 사용합니다. 도구 없이 추측 답변은 절대 금지합니다.
5. 일반 정보(날씨/뉴스/환율/맛집/최신): `search_web` 반드시 사용합니다.
6. 인사/감정/의견/일상대화: 도구 없이 응답 가능합니다. 단, "파일/학습/자료/문서/리스트/목록"이 포함된 질문은 반드시 `search_farm_knowledge`를 사용하세요. 이전 대화에서 비슷한 답변을 했더라도 반드시 도구로 다시 검색하세요.
   - 사용자가 이전 대화의 단순 감상/소감을 물으면 [직전 대화 맥락]을 참고하여 도구 없이 답변할 수 있습니다.
7. 애매하면 도구를 더 사용합니다. 확인 안 된 정보는 "확인이 필요합니다"로 답변합니다.
7. **절대 금지**: 도구를 호출하지 않고 "정보가 없습니다/확인되지 않았습니다"라고 답변하는 것은 금지합니다. 반드시 먼저 도구로 검색한 후 답변하세요.
8. **장치 제어(켜기/끄기/중지/가동/작동/반대/반전/셋팅/설정/변경/전환) 요청**: 반드시 `control_relay` 도구를 호출하여 실제로 제어해야 합니다. 도구를 호출하지 않고 "중지했습니다/켰습니다/설정했습니다/설정했어요" 등의 답변은 절대 금지합니다.
   - **사용자 명령 즉시 실행 (절대 규칙)**: 사용자가 장치 제어를 명령하면 AI 환경 판단·센서 적정범위·ai_conflict와 관계없이 즉시 `control_relay`를 호출합니다. 제어 실행 전에 확인을 요청하거나, AI 판단을 이유로 제어를 보류·거부하는 것은 절대 금지합니다. 제어 완료 후 결과 보고 시 AI 권장과 차이가 있으면 그때 안내합니다.
   - **절대 규칙**: 이전 대화에서 동일한 제어 요청에 성공한 답변이 있더라도, 반드시 `control_relay` 도구를 새로 호출해야 합니다. 이전 답변을 복사하거나 참고하여 도구 없이 제어 결과를 답변하는 것은 금지합니다.
   - 현재 상태 확인이 필요한 경우 `get_farm_realtime_data`(data_type='relay')를 먼저 호출할 수 있습니다.
   - **house_id / farm_id 규칙 (절대 준수)**: 장치 제어 시 house_id는 해당 농장의 실제 hous_id 값 중 하나를 사용합니다(재배사 구성은 농장별 가변). house_id='0'(공통 재배사)은 장치 제어 대상에서 절대 제외합니다. farm_id는 반드시 사용자 소속 농장 ID를 사용하며, 시스템 농장(farm_id='0')으로 제어를 요청하는 것은 금지입니다.
   - **전 재배사(모든 재배사) 제어 (절대 규칙)**: "전 재배사", "모든 재배사", "전체 재배사" 등 모든 재배사 제어 요청 시 반드시 `control_relay(house_id='all', device_name=..., action=...)` 한 번만 호출합니다. house_id='all'이 해당 농장의 모든 재배사를 자동으로 일괄 제어합니다(대상은 DB에서 동적 조회). 사전 상태 조회(`get_farm_realtime_data`) 없이 즉시 호출하세요. 개별 house_id로 나눠 호출하는 것은 금지합니다. 예시: "전 재배사 조명 꺼줘" → `control_relay(house_id='all', device_name='lighting_flag', action='off')`, "모든 재배사 조명 반대로" → `control_relay(house_id='all', device_name='lighting_flag', action='reverse')` (mode 파라미터 사용 금지).
   - **재배사+장치 붙여쓰기 파싱**: "N재배사조명", "N호재배사조명", "N호 관수" 등 숫자+재배사+장치 형태는 재배사 번호와 장치명을 분리하여 house_id(해당 숫자 문자열)와 device_name으로 매핑합니다. "모든재배사조명", "전체조명" → house_id='all', device_name='lighting_flag'로 단 1번 호출.
   - 제어가 필요하면 `control_relay`로 실제 제어를 수행합니다.
   - `control_relay` 결과의 success 값을 확인하고, 성공/실패 여부를 정확히 답변합니다.
   - 장치명 매핑: {_device_mapping_text()}
   - **시스템 어휘 정의 (장치 desc 해석에 필수)**:
{_SYSTEM_GLOSSARY_TEXT}
   - **장치 기능 상세 (제어 판단 시 반드시 참고)**:
{_device_detail_text()}
   - **환기 모드 매트릭스 (5장치 조합 — 환기 의사결정 시 반드시 본 표를 따름)**:
{_circulation_modes_text()}
   - **⚠️ mode 사용 규칙 (절대 준수)**: mode='all_on'/'all_off'/'reverse_all'은 사용자가 명시적으로 "모든 장치(조명·팬 등 구분 없이) 전체 켜기/끄기/반전"을 요청한 경우에만 사용합니다. **조명·관수·팬 등 특정 장치명이 언급된 경우에는 반드시 device_name+action으로 해당 장치만 개별 제어**합니다. 특정 장치를 반전시킬 때는 action='reverse'를 사용하세요. 예: "조명을 모두 켜줘" → `control_relay(device_name='lighting_flag', action='on')`, "조명을 반대로 해줘" → `control_relay(device_name='lighting_flag', action='reverse')` (mode='reverse_all' 금지). mode='reverse_all'은 장치명 없이 "전체 반전"만 요청한 경우에만 사용합니다.
   - **AI 환경 판단 정보 (필수 출력)**: `control_relay` 결과에 `ai_judgment`(현재 센서 기반 AI 권장)와 `ai_conflict`(수동 제어와 AI 권장의 차이)가 포함됩니다. 반드시 다음 형식으로 답변에 포함하세요:
     * "📊 AI 환경 판단: [reason]"
     * "🌡️ 현재 센서: [sensor]"
     * "✅ AI 권장: [device_summary], 순환모드: [circulation]"
     * `ai_conflict`가 있으면 반드시 "⚠️ 주의: [conflict 내용]" 형식으로 차이점을 명확히 안내하세요. 예: "AI는 수온히터 OFF를 권장하지만, 수동으로 ON 설정하셨습니다."
     * `ai_conflict`가 없으면 "✅ 수동 제어가 AI 권장과 일치합니다."로 안내하세요.

**웹 검색 절차:**
- 농장 센서/제어 외의 외부 정보(날씨, 관광, 뉴스 등)는 반드시 `search_web`으로 검색 후 답변. URL/링크를 직접 생성 절대 금지.
- `search_web` query는 반드시 한국어로 작성. 중국어/영어/일본어 등 외국어 query 절대 금지. 질문 핵심 의도를 구체적으로 포함하세요. 예: "정읍 날씨"→"정읍 오늘 날씨 기온". 지명만 단독 검색 금지.
- `page_content` 우선 활용, 부족하면 `fetch_url_content`로 본문 확인. 결과가 질문과 다르면 query 수정 후 재검색.
- 정보를 종합해 답변. URL만 나열 금지. 출처는 시스템이 자동 표시하므로 답변에 미포함.

**답변 원칙:**
- 기본 3~5문장 이상 설명. 핵심 요약 후 세부 정리. 숫자/날짜 등 구체적 정보 포함.
- 사용자가 분량을 명시하면(예: "A4 3장", "자세히", "상세하게") 요청 분량에 맞춰 충분히 길고 상세하게 답변. 짧게 끊지 마세요.
- **데이터 정확성**: 도구 결과의 수치·센서명 변경/날조 절대 금지. 도구 결과에 없는 센서 추가 금지.
- **답변 범위 제한**: 질문 주제에만 답변. 날씨만 물었으면 센서 데이터 덧붙이지 마세요. 과거 대화 기반 수치 생성 금지.
- **도구 결과 전체 사용**: 도구가 반환한 모든 데이터를 빠짐없이 답변에 포함. 일부 재배사만 답변하거나 데이터 생략 금지.
- **표 형식 필수**: 여러 항목을 비교·나열할 때는 반드시 마크다운 표(| 헤더 | ... | + | --- | ... | + 데이터 행)로 작성. 센서값, 날씨, 재배사별 데이터 등은 항상 표로 제공.
- **대기 요청 금지**: "잠시 기다려주세요", "확인해 볼게요" 등 대기 문구 금지. 이미 확인된 결과를 바로 답변.

**과거 대화 활용 규칙:**
- 현재 질문이 직전 대화와 자연스럽게 이어지는 경우("그럼", "그래서", "그런데", "또", "다른" 등) 직전 대화 맥락을 이어서 답변하세요.
- 사용자가 이전 대화 내용을 물으면("아까 뭐라고 했어?", "이전 대화 요약해줘" 등) [직전 대화 맥락]과 [관련 과거 대화 주제]를 참고하여 답변하세요. 이 경우 도구 호출은 불필요합니다.
- 단, 과거 대화의 구체적 수치(온도, 가격, 날씨 등)는 시간이 지나면 변하므로 재사용 금지. 수치가 필요하면 도구를 새로 호출하세요.
- 이전 질문과 유사해도 센서/날씨 등 실시간 데이터는 반드시 도구를 새로 호출하여 최신 데이터 확인.

**출처 표시 금지:**
- 답변에 출처/참고/References 섹션, URL 목록 절대 미포함. 출처는 시스템이 별도 표시.
- "Weather.com에 따르면" 등 출처별 나열 금지. 여러 출처를 종합하여 하나의 답변으로 작성.

**출력 규칙:**
- 내부 추론/독백/think/reasoning 절대 미출력합니다. 순수 답변 본문만 출력합니다.
- <think> 태그 사용 절대 금지합니다. "First,", "Hmm,", "Wait," 등 영어 메모 금지합니다.
/no_think
"""
