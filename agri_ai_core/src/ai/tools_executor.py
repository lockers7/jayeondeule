# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM Tool 실행기
# LLM이 요청한 도구를 실제로 실행하는 모듈
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import json
from datetime import datetime
from typing import Dict, Any

from agri_ai_core.src.logs import setup_logger

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 현재 날짜/시간 가져오기
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_current_datetime() -> Dict[str, Any]:
    """
    현재 날짜와 시간 정보 반환

    Returns:
        dict: 현재 날짜/시간 정보
    """
    now = datetime.now()
    weekdays = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']

    return {
        "date": now.strftime("%Y년 %m월 %d일"),
        "weekday": weekdays[now.weekday()],
        "time": now.strftime("%H시 %M분"),
        "hour": now.hour,
        "minute": now.minute,
        "timestamp": now.isoformat()
    }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 농장 지식 검색
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def search_farm_knowledge(query: str, n_results: int = 3) -> Dict[str, Any]:
    """
    ChromaDB에서 농장 지식 검색

    Args:
        query: 검색 질의
        n_results: 결과 개수

    Returns:
        dict: 검색 결과
    """
    try:
        from agri_ai_core.src.chroma.collections import document_collection

        collection = document_collection()
        if collection is None:
            return {
                "success": False,
                "error": "지식 데이터베이스에 연결할 수 없습니다.",
                "results": []
            }

        results = collection.query(
            query_texts=[query],
            n_results=n_results
        )

        documents = results.get('documents', [[]])[0]
        metadatas = results.get('metadatas', [[]])[0]

        formatted_results = []
        for doc, meta in zip(documents, metadatas):
            formatted_results.append({
                "content": doc[:500],  # 처음 500자만
                "metadata": meta
            })

        logger.info(f"[Tool] search_farm_knowledge: {len(formatted_results)}개 결과")

        return {
            "success": True,
            "query": query,
            "count": len(formatted_results),
            "results": formatted_results
        }

    except Exception as e:
        logger.error(f"농장 지식 검색 중 오류: {e}")
        return {
            "success": False,
            "error": str(e),
            "results": []
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 농장 실시간 데이터 가져오기
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_farm_realtime_data(house_id: str, farm_id: str = None, data_type: str = "all") -> Dict[str, Any]:
    """
    PostgreSQL에서 농장 실시간 데이터 조회

    Args:
        house_id: 재배사 ID
        farm_id: 농장 ID (선택)
        data_type: 데이터 유형 (sensor/relay/all)

    Returns:
        dict: 실시간 데이터
    """
    try:
        # TODO: PostgreSQL 클라이언트 구현 필요
        # 현재는 더미 데이터 반환
        logger.warning(f"[Tool] get_farm_realtime_data: PostgreSQL 클라이언트 미구현 - 더미 데이터 반환")

        result = {
            "success": True,
            "house_id": house_id,
            "timestamp": datetime.now().isoformat(),
            "note": "실제 데이터베이스 연결 구현 필요"
        }

        # 더미 센서 데이터
        if data_type in ["sensor", "all"]:
            result["sensor"] = {
                "temperature": 25.3,
                "humidity": 65.2,
                "co2": 450,
                "timestamp": datetime.now().isoformat()
            }

        # 더미 릴레이 상태
        if data_type in ["relay", "all"]:
            result["relay"] = {
                "heater": "OFF",
                "cooler": "OFF",
                "humidifier": "ON",
                "timestamp": datetime.now().isoformat()
            }

        return result

    except Exception as e:
        logger.error(f"농장 실시간 데이터 조회 중 오류: {e}")
        return {
            "success": False,
            "error": str(e),
            "house_id": house_id
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 웹 검색
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def search_web(query: str, search_type: str = "일반") -> Dict[str, Any]:
    """
    MCP를 통한 웹 검색

    Args:
        query: 검색 키워드
        search_type: 검색 유형

    Returns:
        dict: 검색 결과
    """
    try:
        from agri_ai_core.src.ai.mcp_client import search_web as mcp_search

        result = mcp_search(query, max_results=3)
        logger.info(f"[Tool] search_web: '{query}' 검색 완료")

        return result

    except Exception as e:
        logger.error(f"웹 검색 중 오류: {e}")
        return {
            "success": False,
            "error": str(e),
            "results": []
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 도구 실행기 (메인)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def execute_tool(tool_name: str, tool_args: Dict[str, Any]) -> str:
    """
    LLM이 요청한 도구를 실행하고 결과를 JSON 문자열로 반환

    Args:
        tool_name: 도구 이름
        tool_args: 도구 인자

    Returns:
        str: 실행 결과 (JSON 문자열)
    """
    logger.info(f"[Tool] 실행: {tool_name}({tool_args})")

    try:
        if tool_name == "get_current_datetime":
            result = get_current_datetime()

        elif tool_name == "search_farm_knowledge":
            result = search_farm_knowledge(
                query=tool_args.get("query"),
                n_results=tool_args.get("n_results", 3)
            )

        elif tool_name == "get_farm_realtime_data":
            result = get_farm_realtime_data(
                house_id=tool_args.get("house_id"),
                farm_id=tool_args.get("farm_id"),
                data_type=tool_args.get("data_type", "all")
            )

        elif tool_name == "search_web":
            result = search_web(
                query=tool_args.get("query"),
                search_type=tool_args.get("search_type", "일반")
            )

        else:
            result = {
                "success": False,
                "error": f"알 수 없는 도구: {tool_name}"
            }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error(f"도구 실행 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)
