# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM Tool 실행기
# LLM이 요청한 도구를 실제로 실행하는 모듈
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import json
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Any

from agri_ai_core.logs import setup_logger

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
    t_start = time.time()
    logger.info(f"[VectorDB검색] 시작 query=\"{(query or '')[:80]}\" n_results={n_results}")
    try:
        from agri_ai_core.src.ai.rag.embedder import embed_text
        from agri_ai_core.src.chroma.collections import document_collection
        from agri_ai_core.src.chroma.operations import query_documents

        collection_name = document_collection()
        if not collection_name:
            logger.warning("[VectorDB검색] 컬렉션 연결 실패")
            return {
                "success": False,
                "error": "지식 데이터베이스에 연결할 수 없습니다.",
                "results": []
            }
        logger.info(f"[VectorDB검색] 컬렉션={collection_name}")

        t_embed = time.time()
        query_embedding = embed_text(query)
        embed_elapsed = time.time() - t_embed
        if not query_embedding:
            logger.warning(f"[VectorDB검색] 임베딩 생성 실패 ({embed_elapsed:.1f}s)")
            return {
                "success": False,
                "error": "검색 임베딩 생성에 실패했습니다.",
                "results": [],
            }
        logger.info(f"[VectorDB검색] 임베딩 생성 완료 ({embed_elapsed:.1f}s) dim={len(query_embedding)}")

        t_query = time.time()
        results = query_documents(
            collection_name=collection_name,
            query_embeddings=[query_embedding],
            n_results=max(1, int(n_results or 3)),
        )
        query_elapsed = time.time() - t_query

        if "error" in results:
            logger.warning(f"[VectorDB검색] 쿼리 실패 ({query_elapsed:.1f}s): {results['error']}")
            return {"success": False, "error": results["error"], "results": []}

        documents = results.get('documents', []) or []
        metadatas = results.get('metadatas', []) or []
        distances = results.get('distances', []) or []

        formatted_results = []
        for idx, (doc, meta) in enumerate(zip(documents, metadatas)):
            dist = distances[idx] if idx < len(distances) else None
            formatted_results.append({
                "content": doc[:500],
                "metadata": meta,
                "distance": dist,
            })

        total_elapsed = time.time() - t_start
        logger.info(
            f"[VectorDB검색] 완료 {len(formatted_results)}건 "
            f"(쿼리={query_elapsed:.1f}s, 총={total_elapsed:.1f}s)"
        )
        for idx, fr in enumerate(formatted_results, start=1):
            dist_str = f"{fr['distance']:.4f}" if fr['distance'] is not None else "-"
            logger.info(f"[VectorDB검색] 결과[{idx}] distance={dist_str} content_len={len(fr.get('content',''))}자")

        return {
            "success": True,
            "query": query,
            "count": len(formatted_results),
            "results": formatted_results
        }

    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"[VectorDB검색] 오류 ({elapsed:.1f}s): {e}")
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
    t_start = time.time()
    logger.info(f"[PostgreSQL조회] 시작 farm_id={farm_id} house_id={house_id} data_type={data_type}")
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
            t_farm = time.time()
            with db_session() as database:
                farm = database.fetch_one(GET_ONE_FARM)
                if farm and farm.get("farm_id") is not None:
                    target_farm_id = str(farm.get("farm_id"))
            logger.info(f"[PostgreSQL조회] farm_id 자동조회={target_farm_id} ({time.time() - t_farm:.1f}s)")

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
            t_sensor = time.time()
            sensor = read_current_sensor_info(target_farm_id, house_id)
            sensor_elapsed = time.time() - t_sensor
            result["sensor"] = sensor or {}
            sensor_keys = list((sensor or {}).keys())[:8]
            logger.info(f"[PostgreSQL조회] 센서데이터 ({sensor_elapsed:.1f}s) keys={sensor_keys}")

        if data_type in ["relay", "all"]:
            t_relay = time.time()
            relay = read_latest_relay_info(target_farm_id, house_id)
            relay_elapsed = time.time() - t_relay
            result["relay"] = relay or {}
            relay_keys = list((relay or {}).keys())[:8]
            logger.info(f"[PostgreSQL조회] 릴레이데이터 ({relay_elapsed:.1f}s) keys={relay_keys}")

        if (
            (data_type in ["sensor", "all"] and not result.get("sensor"))
            and (data_type in ["relay", "all"] and not result.get("relay"))
        ):
            result["note"] = "조회된 실시간 데이터가 없습니다."
            logger.warning("[PostgreSQL조회] 조회된 실시간 데이터 없음")

        total_elapsed = time.time() - t_start
        logger.info(f"[PostgreSQL조회] 완료 ({total_elapsed:.1f}s) farm={target_farm_id} house={house_id}")
        return result

    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"[PostgreSQL조회] 오류 ({elapsed:.1f}s): {e}")
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
    t_start = time.time()
    logger.info(f"[웹검색] 시작 query=\"{(query or '')[:100]}\"")
    try:
        from agri_ai_core.src.ai.mcp_client import search_web as mcp_search

        result = mcp_search(query, max_results=3)
        elapsed = time.time() - t_start
        result_count = 0
        if isinstance(result, dict) and isinstance(result.get("results"), list):
            result_count = len(result.get("results", []))
        success = result.get('success', False)
        logger.info(f"[웹검색] 완료 ({elapsed:.1f}s) success={success} results={result_count}건")

        if result_count > 0:
            for idx, item in enumerate(result.get("results", [])[:3], start=1):
                if isinstance(item, dict):
                    logger.info(f"[웹검색] 결과[{idx}] title={item.get('title','')[:50]} url={item.get('url','')[:80]}")

        return result

    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"[웹검색] 오류 ({elapsed:.1f}s): {e}")
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
    t_start = time.time()
    logger.info(f"[도구실행] 시작 tool={tool_name} args={tool_args}")

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

        elapsed = time.time() - t_start
        success = result.get("success", True) if isinstance(result, dict) else True
        json_result = json.dumps(result, ensure_ascii=False, indent=2, default=_json_default)
        logger.info(f"[도구실행] 완료 tool={tool_name} ({elapsed:.1f}s) success={success} 결과길이={len(json_result)}자")
        return json_result

    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"[도구실행] 오류 tool={tool_name} ({elapsed:.1f}s): {e}")
        import traceback
        logger.error(traceback.format_exc())

        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False, default=_json_default)
