# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# MCP (Model Context Protocol) 클라이언트 모듈
# MCP 서버와 통신하여 웹 검색 등의 외부 도구를 사용합니다.
# --->
# call_mcp_tool: MCP 서버의 도구 호출
# search_web: 웹 검색 수행
# get_current_weather: 현재 날씨 조회
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import json
import subprocess
import os
from typing import Dict, Any, Optional, List
from datetime import datetime

from agri_ai_core.src.logs import setup_logger

logger = setup_logger(__name__)

# MCP 서버 경로
MCP_WEB_SEARCH_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    ".mcp", "web-search", "build", "index.js"
)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# MCP 서버 호출
# --->
# MCP 서버의 도구를 호출합니다
# Args:
#     tool_name: 도구 이름 (예: "search")
#     arguments: 도구 인자
#     timeout: 타임아웃 (초)
# Returns:
#     dict: 도구 실행 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def call_mcp_tool(tool_name: str, arguments: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    """MCP 서버의 도구를 호출합니다."""
    try:
        if not os.path.exists(MCP_WEB_SEARCH_PATH):
            logger.error(f"MCP 서버를 찾을 수 없습니다: {MCP_WEB_SEARCH_PATH}")
            return {"error": "MCP server not found"}

        # Node.js MCP 서버 실행
        process = subprocess.Popen(
            ["node", MCP_WEB_SEARCH_PATH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        # 1. Initialize 메시지 전송
        init_request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "agri-ai-core",
                    "version": "1.0.0"
                }
            }
        }

        process.stdin.write(json.dumps(init_request) + "\n")
        process.stdin.flush()

        # 2. Tools/call 메시지 전송
        call_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }

        process.stdin.write(json.dumps(call_request) + "\n")
        process.stdin.flush()
        process.stdin.close()

        # 응답 수신 (타임아웃 적용)
        stdout, stderr = process.communicate(timeout=timeout)

        if stderr:
            logger.debug(f"MCP 서버 stderr: {stderr}")

        # 응답 파싱
        if stdout:
            lines = stdout.strip().split("\n")
            for line in lines:
                if line.strip():
                    try:
                        response = json.loads(line)
                        # tools/call 응답 찾기 (id: 1)
                        if response.get("id") == 1:
                            if "result" in response:
                                return response["result"]
                            elif "error" in response:
                                logger.error(f"MCP 서버 오류: {response['error']}")
                                return {"error": response["error"]}
                    except json.JSONDecodeError as e:
                        logger.debug(f"JSON 파싱 실패: {line[:100]}...")
                        continue

        logger.error("MCP 서버 응답 파싱 실패")
        return {"error": "Failed to parse MCP response"}

    except subprocess.TimeoutExpired:
        logger.error(f"MCP 서버 타임아웃 ({timeout}초)")
        try:
            process.kill()
        except:
            pass
        return {"error": f"MCP server timeout after {timeout}s"}
    except Exception as e:
        logger.error(f"MCP 도구 호출 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"error": str(e)}


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 웹 검색
# --->
# 웹 검색을 수행합니다
# Args:
#     query: 검색 쿼리
#     max_results: 최대 결과 수
# Returns:
#     dict: 검색 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def search_web(query: str, max_results: int = 5) -> Dict[str, Any]:
    """웹 검색을 수행합니다."""
    try:
        logger.info(f"웹 검색 시작: {query}")

        result = call_mcp_tool(
            tool_name="search",
            arguments={
                "query": query,
                "maxResults": max_results
            }
        )

        if "error" in result:
            logger.error(f"웹 검색 실패: {result['error']}")
            return {
                "success": False,
                "error": result["error"],
                "results": []
            }

        # 결과 포맷팅
        search_results = []
        if "content" in result and isinstance(result["content"], list):
            for item in result["content"]:
                if item.get("type") == "text":
                    # 텍스트 결과 파싱
                    text = item.get("text", "")
                    search_results.append({
                        "title": query,
                        "snippet": text[:500],
                        "url": "#",
                        "source": "web_search"
                    })

        logger.info(f"웹 검색 완료: {len(search_results)}개 결과")
        return {
            "success": True,
            "results": search_results,
            "query": query,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"웹 검색 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "error": str(e),
            "results": []
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 현재 날씨 조회
# --->
# 특정 지역의 현재 날씨를 조회합니다
# Args:
#     location: 지역명 (예: "서울", "Seoul")
# Returns:
#     dict: 날씨 정보
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_current_weather(location: str) -> Dict[str, Any]:
    """특정 지역의 현재 날씨를 조회합니다."""
    try:
        logger.info(f"날씨 조회: {location}")

        # 날씨 검색 쿼리 구성
        query = f"{location} 현재 날씨 기온 습도"

        result = search_web(query, max_results=3)

        if result.get("success"):
            return {
                "success": True,
                "location": location,
                "weather_info": result.get("results", []),
                "timestamp": datetime.now().isoformat(),
                "source": "web_search"
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "location": location
            }

    except Exception as e:
        logger.error(f"날씨 조회 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "error": str(e),
            "location": location
        }
