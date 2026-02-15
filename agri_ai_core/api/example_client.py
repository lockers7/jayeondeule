"""
AgriAI REST API 외부 접속 예제

Usage:
    python -m agri_ai_core.api.example_client

환경에 맞게 API_URL, API_KEY 를 수정하세요.
"""
import requests
import json
import time

# =========================================================================
# 접속 설정
# =========================================================================
API_URL = "http://localhost:8002"          # API 서버 주소
API_KEY = ""                               # AGRI_API_KEY 설정 시 입력


def query(prompt, farm_id=None, house_id=None, farm_name=None):
    """AI에 질문을 보내고 응답을 받는다."""
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    payload = {"query": prompt}
    if farm_id:
        payload["farm_id"] = farm_id
    if house_id:
        payload["house_id"] = house_id
    if farm_name:
        payload["farm_name"] = farm_name

    response = requests.post(
        f"{API_URL}/api/v1/query",
        headers=headers,
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def health_check():
    """서버 상태 확인"""
    response = requests.get(f"{API_URL}/health", timeout=5)
    response.raise_for_status()
    return response.json()


# =========================================================================
# 실행 예제
# =========================================================================
if __name__ == "__main__":
    # 1) 서버 상태 확인
    print("=== 서버 상태 확인 ===")
    try:
        status = health_check()
        print(f"상태: {status}")
    except Exception as e:
        print(f"서버 연결 실패: {e}")
        print(f"API 서버({API_URL})가 실행 중인지 확인하세요.")
        exit(1)

    print()

    # 2) AI 질의 예제
    examples = [
        {
            "prompt": "현재 재배사 온도와 습도를 알려줘",
            "farm_id": "1",
            "house_id": "3",
        },
        {
            "prompt": "버섯 재배 최적 온도는?",
            "farm_name": "자연들에",
        },
        {
            "prompt": "오늘 날씨 어때?",
        },
    ]

    for i, ex in enumerate(examples, 1):
        print(f"=== 예제 {i}: {ex['prompt']} ===")
        start = time.time()

        result = query(
            prompt=ex["prompt"],
            farm_id=ex.get("farm_id"),
            house_id=ex.get("house_id"),
            farm_name=ex.get("farm_name"),
        )

        print(f"성공: {result['success']}")
        print(f"응답: {result['response'][:200]}...")
        print(f"처리시간: {result['processing_time']}초")
        print()
