# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM Tool 실행기
# LLM이 요청한 도구를 실제로 실행하는 모듈
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Any

from agri_ai_core.src.logs import setup_logger

logger = setup_logger(__name__)


def _json_default(value: Any) -> Any:
    """json.dumps 기본 직렬화로 처리할 수 없는 타입 변환."""
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return str(value)
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


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
        from agri_ai_core.src.ai.rag.embedder import embed_text
        from agri_ai_core.src.chroma.collections import document_collection
        from agri_ai_core.src.chroma.operations import query_documents

        collection_name = document_collection()
        if not collection_name:
            return {
                "success": False,
                "error": "지식 데이터베이스에 연결할 수 없습니다.",
                "results": []
            }

        query_embedding = embed_text(query)
        if not query_embedding:
            return {
                "success": False,
                "error": "검색 임베딩 생성에 실패했습니다.",
                "results": [],
            }

        results = query_documents(
            collection_name=collection_name,
            query_embeddings=[query_embedding],
            n_results=max(1, int(n_results or 3)),
        )

        if "error" in results:
            return {"success": False, "error": results["error"], "results": []}

        documents = results.get('documents', []) or []
        metadatas = results.get('metadatas', []) or []
        distances = results.get('distances', []) or []

        formatted_results = []
        for idx, (doc, meta) in enumerate(zip(documents, metadatas)):
            formatted_results.append({
                "content": doc[:500],  # 처음 500자만
                "metadata": meta,
                "distance": distances[idx] if idx < len(distances) else None,
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
        from agri_ai_core.src.postgresql.connection import db_session
        from agri_ai_core.src.postgresql.queries import GET_ONE_FARM
        from agri_ai_core.src.postgresql.reader import (
            read_current_sensor_info,
            read_latest_relay_info,
        )

        if not house_id:
            return {
                "success": False,
                "error": "house_id는 필수입니다.",
                "house_id": house_id
            }

        target_farm_id = farm_id
        if not target_farm_id:
            with db_session() as database:
                farm = database.fetch_one(GET_ONE_FARM)
                if farm and farm.get("farm_id") is not None:
                    target_farm_id = str(farm.get("farm_id"))

        if not target_farm_id:
            return {
                "success": False,
                "error": "farm_id를 확인할 수 없습니다.",
                "house_id": house_id
            }

        result = {
            "success": True,
            "farm_id": str(target_farm_id),
            "house_id": house_id,
            "timestamp": datetime.now().isoformat(),
        }

        if data_type in ["sensor", "all"]:
            sensor = read_current_sensor_info(target_farm_id, house_id)
            result["sensor"] = sensor or {}

        if data_type in ["relay", "all"]:
            relay = read_latest_relay_info(target_farm_id, house_id)
            result["relay"] = relay or {}

        if (
            (data_type in ["sensor", "all"] and not result.get("sensor"))
            and (data_type in ["relay", "all"] and not result.get("relay"))
        ):
            result["note"] = "조회된 실시간 데이터가 없습니다."

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
def search_web(query: str) -> Dict[str, Any]:
    """
    MCP를 통한 웹 검색

    Args:
        query: 검색 키워드

    Returns:
        dict: 검색 결과
    """
    try:
        from agri_ai_core.src.ai.mcp_client import search_web as mcp_search

        result = mcp_search(query, max_results=3)
        result_count = 0
        if isinstance(result, dict) and isinstance(result.get("results"), list):
            result_count = len(result.get("results", []))
        logger.info(f"[Tool] search_web(MCP): query='{query}' success={result.get('success')} results={result_count}")

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
                query=tool_args.get("query")
            )

        else:
            result = {
                "success": False,
                "error": f"알 수 없는 도구: {tool_name}"
            }

        return json.dumps(result, ensure_ascii=False, indent=2, default=_json_default)

    except Exception as e:
        logger.error(f"도구 실행 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False, default=_json_default)
