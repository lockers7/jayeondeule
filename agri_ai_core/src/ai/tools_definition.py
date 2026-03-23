# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM Tool Use 도구 정의
# Ollama Function Calling을 위한 도구 정의
# --->
# get_available_tools: 사용 가능한 도구 목록 (get_farm_realtime_data에 환경임계값+AI판단 포함 설명 추가)
# get_system_prompt_with_tools: 시스템 프롬프트 생성 (센서값 적정 판단 + AI vs 알고리즘 비교 가이드 + house_id 정확 지정 가이드 + 장치제어 도구필수 호출 강화 포함)
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
from datetime import datetime
from typing import List, Dict, Any


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 사용 가능한 도구 목록
# LLM이 사용할 수 있는 도구 목록 반환
# Returns: List[Dict]: Ollama Tool Use 형식의 도구 정의
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_available_tools() -> List[Dict[str, Any]]:
    return [
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
        },
        {
            "type": "function",
            "function": {
                "name": "search_gas_price",
                "description": "주유소·유가 정보 전용 API(Opinet)입니다. 주유소 찾기, 기름값, 유가, 휘발유·경유·LPG 가격, 주변 주유소, 최저가 주유소, 시도/시군구별 평균 유가 등 주유소 관련 질문에 이 도구를 사용하세요. search_web보다 정확한 실시간 유가 데이터를 제공합니다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query_type": {
                            "type": "string",
                            "enum": ["avg_national", "avg_sido", "avg_sigun", "low_price"],
                            "description": "조회 유형: avg_national=전국 평균, avg_sido=시도별 평균, avg_sigun=시군구별 평균, low_price=최저가 주유소 Top10"
                        },
                        "sido": {
                            "type": "string",
                            "description": "시도명 (예: '전북', '서울', '경기'). avg_sido/avg_sigun/low_price에서 사용"
                        },
                        "sigun": {
                            "type": "string",
                            "description": "시군구 코드 (예: '0605'=정읍시). avg_sigun에서 사용"
                        },
                        "fuel_name": {
                            "type": "string",
                            "description": "유종명 (예: '휘발유', '경유', 'LPG', '등유'). 미지정 시 휘발유"
                        }
                    },
                    "required": ["query_type"]
                }
            }
        }
    ]


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 시스템 프롬프트 생성
# Tool Use를 위한 시스템 프롬프트 생성
# Args: farm_name: 농장명
#       farm_info: 농장 기본 정보 문자열 (DB에서 조회한 농장/재배사/작물 정보)
# Returns: str: 시스템 프롬프트
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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
   - **다중 재배사 질문 (절대 규칙)**: "각 재배사", "전체", "모든 재배사" 등 복수 재배사 요청 시 반드시 **모든 재배사**(1호, 2호, 3호)에 대해 각각 `get_farm_realtime_data`를 호출해야 합니다. 일부 재배사만 응답하는 것은 금지합니다. house_id는 재배사별로 정확히 지정하세요 (1호='1', 2호='2', 3호='3').
   - 도구 결과에 포함된 **모든 데이터**(센서값, 릴레이 상태)를 빠짐없이 답변에 포함해야 합니다. 데이터를 생략하거나 일부만 표시하는 것은 금지합니다.
   - **센서값 적정 여부 판단**: `get_farm_realtime_data` 응답의 `environment_thresholds`(적정 범위)와 실제 센서값을 비교하여 "적정/저온/고온/비상" 상태를 판단하세요. 임계값 없이 "적정 범위"를 추측하지 마세요.
   - **AI vs 알고리즘 제어값 비교**: `get_farm_realtime_data` 응답의 `ai_environment_judgment`에 알고리즘이 권장하는 릴레이 상태가 포함됩니다. 현재 릴레이(relay_mapping)와 비교하여 차이점을 분석하세요. 릴레이/제어값 비교 질문에는 `search_farm_knowledge` 대신 반드시 `get_farm_realtime_data`를 사용하세요.
2. **학습데이터 삭제 요청** ("삭제", "지워", "제거" + 파일명): 반드시 `delete_farm_knowledge` 도구를 즉시 호출합니다. 확인 질문 없이 바로 실행하세요. farm_id는 현재 사용자의 농장 ID를 사용합니다. 삭제 결과(success/deleted_count)를 그대로 안내하세요. **삭제 완료 후 `search_farm_knowledge`를 재호출하여 확인하지 마세요** — 재검색 결과에는 웹 지식(web_knowledge) 항목이 포함될 수 있어 삭제 실패로 오인할 수 있습니다.
2-1. 파일/문서/학습/RAG/데이터/요약/내용/정리 관련 질문: `search_farm_knowledge` 반드시 사용합니다. 파일명이 포함된 질문은 해당 파일명을 query와 file_name 파라미터에 넣어 반드시 검색합니다. "없다/모른다" 답변 전에 반드시 도구로 검색해야 합니다. 파일 목록 응답의 `file_list[].farm_scope` 값을 반드시 표시하세요 — "시스템 농장"은 전체 공용 데이터, "농장ID:xxx"는 해당 농장 전용 데이터입니다. 현재 대화 농장명으로 farm_scope를 추측하거나 변경하지 마세요.
3. 사실·조사·검색 요청(주소/가격/찾아줘/알아봐줘/설명해줘/알려줘): `search_farm_knowledge` → 부족하면 `search_web` 사용합니다. 도구 없이 추측 답변은 절대 금지합니다. 단, 전용 도구가 있는 경우(예: `search_gas_price`) 전용 도구를 우선 사용합니다.
5. 일반 정보(날씨/뉴스/환율/맛집/최신): `search_web` 반드시 사용합니다.
6. 인사/감정/의견/일상대화: 도구 없이 응답 가능합니다. 단, "파일/학습/자료/문서/리스트/목록"이 포함된 질문은 반드시 `search_farm_knowledge`를 사용하세요. 이전 대화에서 비슷한 답변을 했더라도 반드시 도구로 다시 검색하세요.
   - 사용자가 이전 대화의 단순 감상/소감을 물으면 [직전 대화 맥락]을 참고하여 도구 없이 답변할 수 있습니다.
7. 애매하면 도구를 더 사용합니다. 확인 안 된 정보는 "확인이 필요합니다"로 답변합니다.
7. **절대 금지**: 도구를 호출하지 않고 "정보가 없습니다/확인되지 않았습니다"라고 답변하는 것은 금지합니다. 반드시 먼저 도구로 검색한 후 답변하세요.
8. **장치 제어(켜기/끄기/중지/가동/작동/반대/반전/셋팅/설정/변경/전환) 요청**: 반드시 `control_relay` 도구를 호출하여 실제로 제어해야 합니다. 도구를 호출하지 않고 "중지했습니다/켰습니다/설정했습니다/설정했어요" 등의 답변은 절대 금지합니다.
   - **사용자 명령 즉시 실행 (절대 규칙)**: 사용자가 장치 제어를 명령하면 AI 환경 판단·센서 적정범위·ai_conflict와 관계없이 즉시 `control_relay`를 호출합니다. 제어 실행 전에 확인을 요청하거나, AI 판단을 이유로 제어를 보류·거부하는 것은 절대 금지합니다. 제어 완료 후 결과 보고 시 AI 권장과 차이가 있으면 그때 안내합니다.
   - **절대 규칙**: 이전 대화에서 동일한 제어 요청에 성공한 답변이 있더라도, 반드시 `control_relay` 도구를 새로 호출해야 합니다. 이전 답변을 복사하거나 참고하여 도구 없이 제어 결과를 답변하는 것은 금지합니다.
   - 현재 상태 확인이 필요한 경우 `get_farm_realtime_data`(data_type='relay')를 먼저 호출할 수 있습니다.
   - **house_id / farm_id 규칙 (절대 준수)**: 장치 제어 시 house_id는 특정 재배사의 경우 '1', '2', '3' 중 하나를 사용합니다. house_id='0'(공통 재배사)은 장치 제어 대상에서 절대 제외합니다. farm_id는 반드시 사용자 소속 농장 ID를 사용하며, 시스템 농장(farm_id='0')으로 제어를 요청하는 것은 금지입니다.
   - **전 재배사(모든 재배사) 제어 (절대 규칙)**: "전 재배사", "모든 재배사", "전체 재배사" 등 모든 재배사 제어 요청 시 반드시 `control_relay(house_id='all', device_name=..., action=...)` 한 번만 호출합니다. house_id='all'이 모든 재배사를 자동으로 일괄 제어합니다. 사전 상태 조회(`get_farm_realtime_data`) 없이 즉시 호출하세요. 개별 house_id='1','2','3'으로 나눠 호출하는 것은 금지합니다. 예시: "전 재배사 조명 꺼줘" → `control_relay(house_id='all', device_name='lighting_flag', action='off')`, "모든 재배사 조명 반대로" → `control_relay(house_id='all', device_name='lighting_flag', action='reverse')` (mode 파라미터 사용 금지).
   - **재배사+장치 붙여쓰기 파싱**: "1재배사조명", "1호재배사조명", "2재배사 조명", "3호 관수" 등은 재배사 번호와 장치명을 분리하여 house_id와 device_name으로 매핑합니다. 예: "1재배사조명" → house_id='1', device_name='lighting_flag'. "모든재배사조명", "전체조명" → house_id='all', device_name='lighting_flag'로 단 1번 호출.
   - 제어가 필요하면 `control_relay`로 실제 제어를 수행합니다.
   - `control_relay` 결과의 success 값을 확인하고, 성공/실패 여부를 정확히 답변합니다.
   - 장치명 매핑: 흡입팬/흡기팬=intake_fan_flag, 배출팬/배기팬=exhaust_fan_flag, 수온히터/물가열기/칠러=water_heater_flag, 포그생성/분사펌프/순환모터=fog_occurs_flag, 배수밸브=drainage_motor_flag, 조명=lighting_flag, 관수=irrigation_flag, 실내히터/열풍기=indoor_heater_flag, 히터밸브/열풍댐퍼=indoor_heater_valve_flag, 순환밸브/순환댐퍼=air_circulation_valve_flag, 흡입밸브/흡기댐퍼=air_intake_valve_flag, 배출밸브/배기댐퍼=air_exhaust_valve_flag, 라디에이터=radiator_flag
   - **⚠️ mode 사용 규칙 (절대 준수)**: mode='all_on'/'all_off'/'reverse_all'은 사용자가 명시적으로 "모든 장치(조명·팬 등 구분 없이) 전체 켜기/끄기/반전"을 요청한 경우에만 사용합니다. **조명·관수·팬 등 특정 장치명이 언급된 경우에는 반드시 device_name+action으로 해당 장치만 개별 제어**합니다. 특정 장치를 반전시킬 때는 action='reverse'를 사용하세요. 예: "조명을 모두 켜줘" → `control_relay(device_name='lighting_flag', action='on')`, "조명을 반대로 해줘" → `control_relay(device_name='lighting_flag', action='reverse')` (mode='reverse_all' 금지). mode='reverse_all'은 장치명 없이 "전체 반전"만 요청한 경우에만 사용합니다.
   - **AI 환경 판단 정보 (필수 출력)**: `control_relay` 결과에 `ai_judgment`(현재 센서 기반 AI 권장)와 `ai_conflict`(수동 제어와 AI 권장의 차이)가 포함됩니다. 반드시 다음 형식으로 답변에 포함하세요:
     * "📊 AI 환경 판단: [reason]"
     * "🌡️ 현재 센서: [sensor]"
     * "✅ AI 권장: [device_summary], 순환모드: [circulation]"
     * `ai_conflict`가 있으면 반드시 "⚠️ 주의: [conflict 내용]" 형식으로 차이점을 명확히 안내하세요. 예: "AI는 물가열기 OFF를 권장하지만, 수동으로 ON 설정하셨습니다."
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
