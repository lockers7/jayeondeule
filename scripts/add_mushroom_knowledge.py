#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
상황버섯 재배 기본 지식을 ChromaDB document_collection에 추가
"""

import sys
sys.path.insert(0, '/workspace/jayeondeule')

from agri_ai_core.database.chromadb.operations import upsert_documents
from agri_ai_core.database.chromadb.collections import document_collection
from agri_ai_core.data_pipeline.vectorization.embedder import embed_text

# 상황버섯 재배 기본 지식
knowledge_docs = [
    {
        "id": "mushroom_basic_001",
        "content": """
상황버섯(학명: Phellinus linteus)은 약용버섯으로 항암효과가 뛰어나 주목받는 버섯입니다.
주로 참나무 원목을 이용하여 재배하며, 생육기간은 약 2개월입니다.
상황버섯은 온도와 습도 관리가 매우 중요하며, 적정 환경에서만 좋은 품질의 버섯이 생산됩니다.
        """.strip(),
        "metadata": {
            "category": "버섯소개",
            "topic": "상황버섯기본정보"
        }
    },
    {
        "id": "mushroom_temp_001",
        "content": """
상황버섯 재배 최적 온도:
- 균사생장기: 23-28도 (최적 25도)
- 자실체생장기: 20-25도 (최적 22-23도)
- 온도가 너무 높으면 잡균 오염 위험이 증가합니다.
- 온도가 너무 낮으면 생육이 느려지고 기형버섯이 발생할 수 있습니다.
        """.strip(),
        "metadata": {
            "category": "환경조건",
            "topic": "온도관리"
        }
    },
    {
        "id": "mushroom_humidity_001",
        "content": """
상황버섯 재배 최적 습도:
- 균사생장기: 60-70%
- 자실체생장기: 85-95% (최적 90%)
- 습도가 부족하면 버섯 표면이 갈라지고 품질이 저하됩니다.
- 습도가 과다하면 세균성 병해가 발생할 수 있습니다.
- 재배사 내부에 물안개(포그)를 분사하여 습도를 유지합니다.
        """.strip(),
        "metadata": {
            "category": "환경조건",
            "topic": "습도관리"
        }
    },
    {
        "id": "mushroom_co2_001",
        "content": """
상황버섯 재배 CO2 관리:
- 최적 CO2 농도: 500-1000ppm
- CO2가 너무 높으면 버섯 생육이 억제되고 기형버섯이 발생합니다.
- 재배사 환기를 통해 CO2 농도를 조절합니다.
- 외부순환(외부 공기 흡입 + 내부 공기 배출)으로 CO2 농도를 낮춥니다.
        """.strip(),
        "metadata": {
            "category": "환경조건",
            "topic": "CO2관리"
        }
    },
    {
        "id": "mushroom_ventilation_001",
        "content": """
상황버섯 재배사 환기 방법:
1. 내부순환: 순환밸브 ON, 흡입/배출밸브 OFF
   - 재배사 내부 공기만 순환
   - 온도/습도 균일화에 효과적

2. 외부순환: 순환밸브 OFF, 흡입밸브 ON, 배출밸브 ON
   - 외부 공기 흡입 + 내부 공기 배출
   - CO2 농도 조절, 온도 조절에 효과적

3. 흡입순환: 흡입밸브만 ON
   - 외부 온도가 내부보다 낮을 때 사용

4. 배출순환: 배출밸브만 ON
   - 내부 열기 배출
        """.strip(),
        "metadata": {
            "category": "환경제어",
            "topic": "환기시스템"
        }
    },
    {
        "id": "mushroom_heating_001",
        "content": """
상황버섯 재배사 가온 방법:
1. 수온히터 + 포그:
   - 지하수(15-17도)를 수온히터로 가열
   - 습도모터로 물안개 발생
   - 상단 덕트를 통해 재배사 내부로 분사
   - 온도 상승 + 습도 유지 효과

2. 내부히터:
   - 직접 공기를 가열
   - 히터밸브를 통해 따뜻한 공기 흡입
   - 비용이 높아 외부 온도가 낮을 때만 사용

3. 외부 온도 활용:
   - 외부 온도가 내부보다 높을 때
   - 외부순환으로 외부 공기 흡입
        """.strip(),
        "metadata": {
            "category": "환경제어",
            "topic": "온도상승"
        }
    },
    {
        "id": "mushroom_cooling_001",
        "content": """
상황버섯 재배사 냉각 방법:
1. 지하수 포그:
   - 지하수(15-17도)로 물안개 발생
   - 증발열로 온도 하강 + 습도 유지

2. 외부순환:
   - 외부 온도가 내부보다 낮을 때
   - 외부 공기 흡입으로 온도 하강

3. 배수밸브:
   - 장치박스 내 물을 교체
   - 지속적으로 지하수 온도 유지
        """.strip(),
        "metadata": {
            "category": "환경제어",
            "topic": "온도하강"
        }
    },
    {
        "id": "mushroom_harvest_001",
        "content": """
상황버섯 수확 기준:
- 재배 시작 후 약 2개월
- 버섯 갓이 충분히 펼쳐졌을 때
- 포자가 나오기 전에 수확
- 등급 기준:
  등급1: 크기 균일, 색상 양호, 모양 완전
  등급2: 크기 약간 작음, 색상 양호
  등급3: 크기 작거나 색상 불량
  등급4-5: 기형, 병해
        """.strip(),
        "metadata": {
            "category": "재배관리",
            "topic": "수확"
        }
    },
    {
        "id": "mushroom_disease_001",
        "content": """
상황버섯 병해 예방:
1. 잡균 오염:
   - 원인: 온도 과다, 습도 과다, 불결한 환경
   - 예방: 적정 온도/습도 유지, 재배사 청결

2. 세균성 병해:
   - 원인: 습도 과다, 환기 부족
   - 예방: 습도 조절, 충분한 환기

3. 해충:
   - 원인: 재배사 틈새로 유입
   - 예방: 재배사 밀폐, 방충망 설치

4. 기형버섯:
   - 원인: CO2 과다, 온도 부적합
   - 예방: 환기, 온도 조절
        """.strip(),
        "metadata": {
            "category": "재배관리",
            "topic": "병해관리"
        }
    },
    {
        "id": "smartfarm_basic_001",
        "content": """
스마트팜(Smart Farm)이란?
정보통신기술(ICT)을 활용하여 농작물 재배 환경을 자동으로 제어하는 농업 시스템입니다.

주요 구성요소:
1. 센서: 온도, 습도, CO2, 광량, 수위 등 측정
2. 제어장치: 히터, 환풍기, 밸브 등 자동 제어
3. 모니터링: 실시간 환경 데이터 확인
4. 자동제어: 최적 환경 유지를 위한 자동 조절

장점:
- 노동력 절감
- 최적 환경 유지로 품질 향상
- 수확량 증대
- 원격 관리 가능
        """.strip(),
        "metadata": {
            "category": "스마트팜",
            "topic": "스마트팜소개"
        }
    }
]

def main():
    print("="*80)
    print("상황버섯 재배 지식을 ChromaDB에 추가")
    print("="*80)

    collection_name = document_collection()
    if not collection_name:
        print("❌ 오류: document_collection이 설정되지 않음")
        return

    print(f"\n컬렉션: {collection_name}")
    print(f"추가할 문서: {len(knowledge_docs)}건")
    print()

    # 각 문서의 임베딩 생성 및 ChromaDB에 저장
    ids = []
    documents = []
    embeddings = []
    metadatas = []

    for i, doc in enumerate(knowledge_docs, 1):
        print(f"[{i}/{len(knowledge_docs)}] {doc['metadata']['topic']} 처리 중...", end=" ")

        # 임베딩 생성
        embedding = embed_text(doc['content'])
        if not embedding:
            print("❌ 임베딩 실패")
            continue

        ids.append(doc['id'])
        documents.append(doc['content'])
        embeddings.append(embedding)
        metadatas.append(doc['metadata'])

        print("✓")

    # ChromaDB에 저장
    print(f"\nChromaDB에 {len(ids)}건 저장 중...")
    result = upsert_documents(
        collection_name=collection_name,
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas
    )

    if "error" in result:
        print(f"❌ 저장 실패: {result['error']}")
    else:
        print(f"✓ 저장 완료: {len(ids)}건")
        print()
        print("추가된 지식:")
        for doc in knowledge_docs:
            print(f"  - {doc['metadata']['category']}: {doc['metadata']['topic']}")

if __name__ == "__main__":
    main()
