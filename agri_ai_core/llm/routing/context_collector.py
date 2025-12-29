# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 컨텍스트 수집기 모듈
# 쿼리 처리에 필요한 관련 정보를 DB 및 벡터 저장소에서 수집하여
# LLM에게 제공할 컨텍스트를 구성합니다.
# --->
# collect_farm_knowledge: ChromaDB에서 농장 지식 검색 (RAG)
# collect_farm_realtime_data: PostgreSQL에서 실시간 농장 데이터 수집
# collect_system_info: 시스템 정보 수집
# collect_web_search: 웹 검색 수행
# collect_context_parallel: 병렬 데이터 수집 오케스트레이터
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import asyncio
from typing import Dict, Any
from datetime import datetime, timedelta

from agri_ai_core.log_utils.log_handlers import setup_logger

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ChromaDB에서 농장 지식 검색 (RAG)
# ChromaDB에서 농장 관련 지식 검색 (RAG)
#
# Args:
#     required_data: 검색 명세
#     {
#         "query": "스마트팜이란?",
#         "n_results": 3
#     }
#
# Returns:
#     dict: 검색된 지식 데이터
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def collect_farm_knowledge(required_data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from agri_ai_core.database.chromadb.operations import query_documents
        from agri_ai_core.database.chromadb.collections import document_collection

        query_text = required_data.get("query", "")
        n_results = required_data.get("n_results", 3)

        collected_data = {
            "data_type": "farm_knowledge",
            "timestamp": datetime.now().isoformat(),
            "query": query_text,
            "results": [],
            "summary": ""
        }

        # ChromaDB에서 유사 문서 검색
        collection_name = document_collection()
        if not collection_name:
            collected_data["summary"] = "문서 컬렉션이 설정되지 않음"
            return collected_data

        # 텍스트를 임베딩 벡터로 변환
        from agri_ai_core.data_pipeline.vectorization.embedder import embed_text

        query_embedding = await asyncio.to_thread(embed_text, query_text)
        if not query_embedding or len(query_embedding) == 0:
            collected_data["summary"] = "임베딩 생성 실패"
            return collected_data

        search_results = await asyncio.to_thread(
            query_documents,
            collection_name,
            query_embeddings=[query_embedding],
            n_results=n_results
        )

        if search_results and 'documents' in search_results:
            # 결과가 빈 리스트인 경우 처리
            documents = search_results.get('documents', [])
            if documents and len(documents) > 0 and isinstance(documents[0], list):
                docs = documents[0]
            else:
                docs = []

            metadatas_raw = search_results.get('metadatas', [])
            metadatas = metadatas_raw[0] if metadatas_raw and len(metadatas_raw) > 0 else []

            distances_raw = search_results.get('distances', [])
            distances = distances_raw[0] if distances_raw and len(distances_raw) > 0 else []

            for i, doc in enumerate(docs):
                result_item = {
                    "content": doc,
                    "metadata": metadatas[i] if i < len(metadatas) else {},
                    "distance": distances[i] if i < len(distances) else 0
                }
                collected_data["results"].append(result_item)

            if docs:
                collected_data["summary"] = f"{len(docs)}개의 관련 문서 검색 완료"
            else:
                collected_data["summary"] = "ChromaDB에 관련 문서가 없음 (문서 업로드 필요)"
        else:
            collected_data["summary"] = "검색 결과 없음"

        logger.info(f"ChromaDB 지식 검색 완료: {collected_data['summary']}")
        return collected_data

    except Exception as e:
        logger.error(f"ChromaDB 지식 검색 중 오류: {e}")
        return {
            "data_type": "farm_knowledge",
            "error": str(e),
            "summary": f"ChromaDB 검색 실패: {str(e)}"
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# PostgreSQL에서 실시간 농장 데이터 수집
# PostgreSQL에서 실시간 센서/릴레이 데이터 수집
# 기존 쿼리(GET_NOW_UNIT_INFO, GET_LATEST_RELAY_INFO) 사용
#
# Args:
#     required_data: 데이터 명세
#     {
#         "farm_id": "1",
#         "house_id": "1"
#     }
#
# Returns:
#     dict: 수집된 실시간 데이터
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def collect_farm_realtime_data(required_data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from agri_ai_core.database.postgres.connection import DatabaseHandler
        from agri_ai_core.database.postgres.queries import GET_NOW_UNIT_INFO, GET_LATEST_RELAY_INFO

        farm_id = required_data.get("farm_id")
        house_id = required_data.get("house_id")

        collected_data = {
            "farm_id": farm_id,
            "house_id": house_id,
            "data_type": "farm_realtime",
            "timestamp": datetime.now().isoformat(),
            "sensors": {},
            "relays": {},
            "summary": ""
        }

        # DB 연결
        db = DatabaseHandler()
        await asyncio.to_thread(db.connect)

        # 센서 데이터 조회 (기존 쿼리 사용)
        cursor = db.connection.cursor()
        await asyncio.to_thread(cursor.execute, GET_NOW_UNIT_INFO, (farm_id, house_id))
        sensor_result = cursor.fetchone()

        if sensor_result:
            # RealDictRow에서 데이터 추출
            collected_data["sensors"] = {
                "기록시간": sensor_result['record_datetime'],
                "내부온도": float(sensor_result['indoor_temperature']) if sensor_result['indoor_temperature'] else None,
                "내부습도": float(sensor_result['indoor_humidity']) if sensor_result['indoor_humidity'] else None,
                "외부온도": float(sensor_result['outdoor_temperature']) if sensor_result['outdoor_temperature'] else None,
                "외부습도": float(sensor_result['outdoor_humidity']) if sensor_result['outdoor_humidity'] else None,
                "CO2": float(sensor_result['co2']) if sensor_result['co2'] else None,
                "수온": float(sensor_result['water_temperature']) if sensor_result['water_temperature'] else None,
                "조도": float(sensor_result['light_level']) if sensor_result['light_level'] else None,
                "수위": float(sensor_result['water_level']) if sensor_result['water_level'] else None
            }

            # 요약 생성
            summary_parts = []
            if collected_data["sensors"]["내부온도"]:
                summary_parts.append(f"내부온도 {collected_data['sensors']['내부온도']:.1f}°C")
            if collected_data["sensors"]["내부습도"]:
                summary_parts.append(f"습도 {collected_data['sensors']['내부습도']:.1f}%")
            if collected_data["sensors"]["CO2"]:
                summary_parts.append(f"CO2 {collected_data['sensors']['CO2']:.0f}ppm")

            collected_data["summary"] = ", ".join(summary_parts) if summary_parts else "센서 데이터 수집 완료"

        # 릴레이 정보 조회 (기존 쿼리 사용)
        await asyncio.to_thread(cursor.execute, GET_LATEST_RELAY_INFO, (farm_id, house_id))
        relay_result = cursor.fetchone()

        if relay_result:
            # 16개 릴레이 상태
            relay_flags = list(relay_result)
            on_count = sum(1 for f in relay_flags if f == 1)

            collected_data["relays"] = {
                "전체개수": 16,
                "ON개수": on_count,
                "상태목록": [
                    {"번호": i, "상태": "ON" if flag == 1 else "OFF"}
                    for i, flag in enumerate(relay_flags, 1)
                ]
            }

            if collected_data["summary"]:
                collected_data["summary"] += f", 릴레이 {on_count}/16 ON"
            else:
                collected_data["summary"] = f"릴레이 {on_count}/16 ON"

        cursor.close()
        db.close()

        logger.info(f"PostgreSQL 실시간 데이터 수집 완료: {collected_data['summary']}")
        return collected_data

    except Exception as e:
        logger.error(f"PostgreSQL 실시간 데이터 수집 중 오류: {e}")
        return {
            "data_type": "farm_realtime",
            "error": str(e),
            "summary": f"실시간 데이터 수집 실패: {str(e)}"
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 시스템 정보 수집
# 시스템 정보 수집 (날짜, 시간, 시스템 상태)
#
# Args:
#     required_data: 필요한 정보 명세
#     {
#         "current_time": True/False,
#         "current_date": True/False,
#         "system_status": True/False
#     }
#
# Returns:
#     dict: 수집된 시스템 정보
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def collect_system_info(required_data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        import platform
        import psutil

        collected_data = {
            "data_type": "system",
            "timestamp": datetime.now().isoformat(),
            "datetime": {},
            "system": {},
            "summary": ""
        }

        summary_parts = []

        # 날짜/시간 정보
        if required_data.get("current_time") or required_data.get("current_date"):
            now = datetime.now()
            collected_data["datetime"] = {
                "현재시간": now.strftime("%H:%M:%S"),
                "현재날짜": now.strftime("%Y년 %m월 %d일"),
                "요일": now.strftime("%A"),
                "한글요일": ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"][now.weekday()],
                "ISO": now.isoformat()
            }
            summary_parts.append(
                f"현재 {collected_data['datetime']['현재날짜']} {collected_data['datetime']['현재시간']}"
            )

        # 시스템 상태
        if required_data.get("system_status"):
            cpu_percent = await asyncio.to_thread(psutil.cpu_percent, interval=0.5)
            memory = await asyncio.to_thread(psutil.virtual_memory)

            collected_data["system"] = {
                "플랫폼": platform.system(),
                "CPU사용률": f"{cpu_percent}%",
                "메모리사용률": f"{memory.percent}%",
                "가동시간": str(timedelta(seconds=int(await asyncio.to_thread(lambda: __import__('time').time() - psutil.boot_time()))))
            }
            summary_parts.append(
                f"시스템 정상 (CPU {cpu_percent}%, 메모리 {memory.percent}%)"
            )

        collected_data["summary"] = ", ".join(summary_parts) if summary_parts else "시스템 정보 수집 완료"

        logger.info(f"시스템 정보 수집 완료: {collected_data['summary']}")
        return collected_data

    except Exception as e:
        logger.error(f"시스템 정보 수집 중 오류: {e}")
        return {
            "data_type": "system",
            "error": str(e),
            "summary": f"시스템 정보 수집 실패: {str(e)}"
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 웹 검색 수행
# 웹 검색 수행
#
# Args:
#     required_data: 검색 명세
#     {
#         "search_keywords": "검색어",
#         "search_type": "날씨" or "뉴스" or None
#     }
#
# Returns:
#     dict: 검색 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def collect_web_search(required_data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        # TODO: 실제 웹 검색 API 연동
        # 현재는 mock 데이터 반환

        keywords = required_data.get("search_keywords", "")
        search_type = required_data.get("search_type")

        collected_data = {
            "data_type": "web",
            "timestamp": datetime.now().isoformat(),
            "keywords": keywords,
            "type": search_type,
            "results": [],
            "summary": ""
        }

        # Mock 검색 결과
        if "날씨" in keywords:
            collected_data["results"] = [
                {
                    "title": f"{keywords} 검색 결과",
                    "snippet": "웹 검색 기능은 추후 구현 예정입니다. 사용자에게 직접 검색을 요청하세요.",
                    "url": "#"
                }
            ]
            collected_data["summary"] = f"{keywords} 검색 결과: 웹 검색 API 연동 필요"
        else:
            collected_data["summary"] = f"{keywords} 검색 완료 (mock)"

        logger.info(f"웹 검색 완료: {collected_data['summary']}")
        return collected_data

    except Exception as e:
        logger.error(f"웹 검색 중 오류: {e}")
        return {
            "data_type": "web",
            "error": str(e),
            "summary": f"웹 검색 실패: {str(e)}"
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 병렬 데이터 수집 오케스트레이터
# 분류 결과에 따라 필요한 데이터를 병렬로 수집
#
# Args:
#     classification: 질문 분류 결과
#
# Returns:
#     dict: 수집된 모든 컨텍스트 데이터
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def collect_context_parallel(classification: Dict[str, Any]) -> Dict[str, Any]:
    try:
        required_data = classification.get("required_data", {})
        tasks = []

        # ChromaDB 농장 지식 검색 태스크
        if required_data.get("farm_knowledge"):
            tasks.append(("farm_knowledge", collect_farm_knowledge(required_data["farm_knowledge"])))

        # PostgreSQL 실시간 데이터 수집 태스크
        if required_data.get("farm_realtime"):
            tasks.append(("farm_realtime", collect_farm_realtime_data(required_data["farm_realtime"])))

        # 시스템 정보 수집 태스크
        if required_data.get("system"):
            tasks.append(("system", collect_system_info(required_data["system"])))

        # 웹 검색 태스크
        if required_data.get("web"):
            tasks.append(("web", collect_web_search(required_data["web"])))

        # 병렬 실행
        if not tasks:
            return {"collected": {}, "summary": "수집할 데이터 없음"}

        results = await asyncio.gather(*[task[1] for task in tasks], return_exceptions=True)

        # 결과 구성
        collected = {}
        summaries = []

        for i, (data_type, _) in enumerate(tasks):
            result = results[i]
            if isinstance(result, Exception):
                logger.error(f"{data_type} 데이터 수집 실패: {result}")
                collected[data_type] = {"error": str(result)}
            else:
                collected[data_type] = result
                if result.get("summary"):
                    summaries.append(result["summary"])

        context = {
            "collected": collected,
            "summary": " | ".join(summaries) if summaries else "데이터 수집 완료",
            "timestamp": datetime.now().isoformat()
        }

        logger.info(f"병렬 데이터 수집 완료: {len(collected)}개 소스")
        return context

    except Exception as e:
        logger.error(f"병렬 데이터 수집 중 오류: {e}")
        return {
            "collected": {},
            "summary": f"데이터 수집 실패: {str(e)}",
            "error": str(e)
        }
