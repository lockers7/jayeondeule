# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM Tool Use 도구 정의
# Ollama Function Calling을 위한 도구 정의
# --->
# get_available_tools: 사용 가능한 도구 목록
# get_system_prompt_with_tools: 시스템 프롬프트 생성
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
                "name": "search_farm_knowledge",
                "description": "스마트팜 벡터 데이터베이스(ChromaDB)에서 관련 정보를 검색합니다. 학습(RAG)된 문서 지식, 파일 내용, 농장 시계열 데이터를 함께 조회합니다. 파일명으로도 검색 가능합니다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "검색할 질문 또는 키워드. 파일 검색 시 파일명을 포함하세요."
                        },
                        "n_results": {
                            "type": "integer",
                            "description": "가져올 결과 개수 (기본값: 3)",
                            "default": 3
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
                "description": "농장의 실시간 센서 데이터(온도, 습도 등) 또는 릴레이 상태를 가져옵니다. 특정 재배사의 현재 상태를 확인할 때 사용합니다.",
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
                            "description": "데이터 유형 (sensor: 센서 데이터, relay: 릴레이 상태)",
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
                "description": "재배사의 릴레이(장치)를 제어합니다. 단건 제어: device_name+action 사용. 일괄 제어: mode 사용 (reverse_all=전체반전, all_on=전체켜기, all_off=전체끄기). 반드시 먼저 get_farm_realtime_data로 현재 상태를 확인한 후 사용하세요.",
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
                        "device_name": {
                            "type": "string",
                            "description": "단건 제어 시 장치명 (relay_mapping의 device 값 사용)"
                        },
                        "action": {
                            "type": "string",
                            "description": "단건 제어 동작 (on: 켜기, off: 끄기)",
                            "enum": ["on", "off"]
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
                            "description": "검색할 키워드"
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
1. 농장/센서/릴레이/생육 질문: `get_farm_realtime_data`+`search_farm_knowledge` 반드시 모두 사용합니다. 수치/상태 추측은 금지합니다.
   - **다중 재배사 질문 (절대 규칙)**: "각 재배사", "전체", "모든 재배사" 등 복수 재배사 요청 시 반드시 **모든 재배사**(1호, 2호, 3호)에 대해 각각 도구를 호출해야 합니다. 일부 재배사만 응답하는 것은 금지합니다.
   - 도구 결과에 포함된 **모든 데이터**(센서값, 릴레이 상태)를 빠짐없이 답변에 포함해야 합니다. 데이터를 생략하거나 일부만 표시하는 것은 금지합니다.
2. 파일/문서/학습/RAG/데이터/요약/내용/정리 관련 질문: `search_farm_knowledge` 반드시 사용합니다. 파일명이 포함된 질문은 해당 파일명을 query와 file_name 파라미터에 넣어 반드시 검색합니다. "없다/모른다" 답변 전에 반드시 도구로 검색해야 합니다.
3. 사실·조사·검색 요청(주소/가격/찾아줘/알아봐줘/설명해줘/알려줘): `search_farm_knowledge` → 부족하면 `search_web` 사용합니다. 도구 없이 추측 답변은 절대 금지합니다.
4. 일반 정보(날씨/뉴스/환율/맛집/최신): `search_web` 반드시 사용합니다.
5. 인사/감정/의견: 도구 없이 응답 가능합니다.
6. 애매하면 도구를 더 사용합니다. 확인 안 된 정보는 "확인이 필요합니다"로 답변합니다.
7. **절대 금지**: 도구를 호출하지 않고 "정보가 없습니다/확인되지 않았습니다"라고 답변하는 것은 금지합니다. 반드시 먼저 도구로 검색한 후 답변하세요.
8. **장치 제어(켜기/끄기/중지/가동/작동) 요청**: 반드시 `control_relay` 도구를 호출하여 실제로 제어해야 합니다. 도구를 호출하지 않고 "중지했습니다/켰습니다" 등의 답변은 절대 금지합니다.
   - 먼저 `get_farm_realtime_data`(data_type='relay')로 현재 상태를 확인합니다.
   - 제어가 필요하면 `control_relay`로 실제 제어를 수행합니다.
   - `control_relay` 결과의 success 값을 확인하고, 성공/실패 여부를 정확히 답변합니다.
   - 장치명 매핑: 흡입팬/흡기팬=intake_fan_flag, 배출팬/배기팬=exhaust_fan_flag, 수온히터/물가열기/칠러=water_heater_flag, 포그생성/분사펌프/순환모터=fog_occurs_flag, 배수밸브=drainage_motor_flag, 조명=lighting_flag, 관수=irrigation_flag, 실내히터/열풍기=indoor_heater_flag, 히터밸브/열풍댐퍼=indoor_heater_valve_flag, 순환밸브/순환댐퍼=air_circulation_valve_flag, 흡입밸브/흡기댐퍼=air_intake_valve_flag, 배출밸브/배기댐퍼=air_exhaust_valve_flag, 라디에이터=radiator_flag
   - 전체 반전/전체 ON/OFF가 필요하면 `control_relay`에 mode를 사용합니다. 전체 반전은 mode='reverse_all', 전체 켜기는 mode='all_on', 전체 끄기는 mode='all_off'로 호출합니다.
   - **AI 환경 판단 정보 (필수 출력)**: `control_relay` 결과에 `ai_judgment`(현재 센서 기반 AI 권장)와 `ai_conflict`(수동 제어와 AI 권장의 차이)가 포함됩니다. 반드시 다음 형식으로 답변에 포함하세요:
     * "📊 AI 환경 판단: [reason]"
     * "🌡️ 현재 센서: [sensor]"
     * "✅ AI 권장: [device_summary], 순환모드: [circulation]"
     * `ai_conflict`가 있으면 반드시 "⚠️ 주의: [conflict 내용]" 형식으로 차이점을 명확히 안내하세요. 예: "AI는 물가열기 OFF를 권장하지만, 수동으로 ON 설정하셨습니다."
     * `ai_conflict`가 없으면 "✅ 수동 제어가 AI 권장과 일치합니다."로 안내하세요.

**웹 검색 절차:**
- `search_web` 결과의 `page_content` 우선 활용, 부족하면 `fetch_url_content`로 본문을 읽습니다.
- 필요 시 `search_web`에 `n_results`, `auto_fetch_max`를 지정해 검색 깊이를 조절합니다.
- 정보를 종합해 체계적으로 답변합니다. URL만 나열하지 마세요. 출처는 시스템이 자동 표시하므로 답변에 포함하지 마세요.

**답변 원칙:**
- 3~5문장 이상 충분히 설명합니다. 핵심 먼저 요약 후 세부 항목을 정리합니다.
- 숫자/날짜 등 구체적 정보를 포함합니다. 여러 출처를 종합하여 균형 잡힌 답변을 제공합니다.
- 정보 부족 시 솔직히 안내합니다. 사용자 제공 URL은 최우선으로 반영합니다.
- 최신 정보 질문은 웹 검색 근거를 우선 반영합니다.
- **대기 요청 금지 (절대 규칙)**: 도구 호출과 데이터 수집은 답변 전에 이미 완료된 상태입니다. "잠시 기다려주세요", "확인해 볼게요", "잠시만요", "알아보겠습니다" 등 대기를 요청하는 문구를 답변에 포함하지 마세요. 이미 확인된 결과를 바로 답변하세요.

**출처 표시 금지 (절대 규칙):**
- 답변 본문에 출처, 참고 링크, 참고 자료, References 등의 섹션을 절대 포함하지 마세요.
- URL 목록, [출처](URL) 형식의 링크 모음을 답변 끝에 나열하지 마세요.
- 출처 정보는 시스템이 자동으로 별도 영역에 표시합니다. 답변에 중복 포함하면 사용자에게 같은 정보가 두 번 보입니다.
- 답변 본문 중간에 자연스럽게 언급하는 것은 허용합니다. 예: "연합뉴스에 따르면..."은 허용하되, 답변 끝에 별도 출처 섹션을 만들지 마세요.

**출력 규칙:**
- 내부 추론/독백/think/reasoning 절대 미출력합니다. 순수 답변 본문만 출력합니다.
- <think> 태그 사용 절대 금지합니다. "First,", "Hmm,", "Wait," 등 영어 메모 금지합니다.
/no_think
"""
