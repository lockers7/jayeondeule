# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# QA 데이터 생성기 모듈
# 파인튜닝을 위한 질문-답변 쌍을 자동으로 생성하며,
# 기존 데이터와 LLM을 활용하여 학습 데이터셋을 확장합니다.
# --->
# generate_crop_qa_pairs: 작물 관련 문서에서 Q&A 쌍 생성
# store_crop_qa_pairs: 생성된 QA 쌍을 learned_collection에 저장
# extract_structured_information: 원문에서 구조화된 핵심 정보 추출
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import re
import ollama
from datetime import datetime

from agri_ai_core.src.logs import setup_logger
from agri_ai_core.config import settings, NUM_PREDICT
from agri_ai_core.src.chroma.collections import learned_collection
from agri_ai_core.src.chroma.operations import upsert_collection_data

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 작물 관련 QA 쌍 생성
# --->
# 작물 관련 문서에서 Q&A 쌍 생성
# Args:
# crop_name: 작물명
# document_content: 문서 내용
# document_title: 문서 제목
# Returns:
# list: QA 쌍 목록
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def generate_crop_qa_pairs(crop_name, document_content, document_title=None):
    qa_categories = {
        "general": {
            "patterns": [r"일반현황", r"성상", r"특성"],
            "questions": [
                f"{crop_name}이란 무엇인가요?",
                f"{crop_name}의 특성은 무엇인가요?",
                f"{crop_name}은 어떤 식물인가요?"
            ]
        },
        "benefits": {
            "patterns": [r"효능", r"효과", r"성분", r"약리작용"],
            "questions": [
                f"{crop_name}의 효능은 무엇인가요?",
                f"{crop_name}의 주요 성분은 무엇인가요?",
                f"{crop_name}은 어떤 건강상 이점이 있나요?"
            ]
        },
        "cultivation": {
            "patterns": [r"재배방법", r"재배 방법", r"재배환경", r"재배 환경"],
            "questions": [
                f"{crop_name} 재배 방법을 알려주세요",
                f"{crop_name}은 어떤 환경에서 재배하나요?",
                f"{crop_name}의 재배 시기는 언제인가요?"
            ]
        },
        "disease": {
            "patterns": [r"병해충", r"병충해", r"방제"],
            "questions": [
                f"{crop_name}에 발생하는 주요 병해충은 무엇인가요?",
                f"{crop_name}의 병해충 방제 방법은 무엇인가요?",
                f"{crop_name} 재배시 주의할 질병은 무엇인가요?"
            ]
        },
        "harvest": {
            "patterns": [r"수확", r"저장", r"보관"],
            "questions": [
                f"{crop_name}의 수확 시기와 방법은 어떻게 되나요?",
                f"{crop_name}은 어떻게 저장하고 보관하나요?",
                f"{crop_name}의 품질 기준은 무엇인가요?"
            ]
        }
    }

    model_name = getattr(settings.model, "name", None) or "llama3.2"
    qa_pairs = []

    for category, info in qa_categories.items():
        section_text = ""
        for pattern in info["patterns"]:
            matches = re.finditer(pattern, document_content, re.IGNORECASE)
            for match in matches:
                start = max(0, match.start() - 100)
                end = min(len(document_content), match.end() + 1000)
                section_text += document_content[start:end] + "\n\n"

        if section_text:
            for question in info["questions"]:
                prompt = f"""다음은 {crop_name}에 관한 정보입니다:
                        {section_text}
                        위 정보를 바탕으로 다음 질문에 답변해주세요:
                        질문: {question}
                        답변:"""

                try:
                    response = ollama.generate(
                        model=model_name,
                        prompt=prompt,
                        options={
                            "temperature": 0.1,
                            "top_p": 0.8,
                            "top_k": 20,
                            "num_predict": NUM_PREDICT,
                            "stop": ["\n```", "\n\n", "\n###", "}\n"]
                        }
                    )

                    answer = response.get("response", "").strip()

                    if answer:
                        qa_pairs.append({
                            "question": question,
                            "answer": answer,
                            "category": category,
                            "crop_name": crop_name,
                            "document_title": document_title or f"{crop_name} 정보 문서"
                        })

                        logger.info(f"{crop_name} 관련 QA 쌍 생성 완료 - {category}")
                except Exception as e:
                    logger.warning(f"QA 생성 중 오류: {e}")
                    continue

    return qa_pairs


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# QA 쌍 저장
# --->
# 생성된 QA 쌍을 learned_collection에 저장
# Args:
# qa_pairs: QA 쌍 목록
# farm_id: 농장 ID (선택)
# Returns:
# int: 저장된 QA 쌍 수
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def store_crop_qa_pairs(qa_pairs, farm_id=None):
    if not qa_pairs:
        logger.info("저장할 QA 쌍이 없습니다.")
        return 0

    try:
        ids = []
        metadatas = []
        documents = []

        for i, qa_pair in enumerate(qa_pairs):
            # QA 쌍 ID 생성
            qa_id = f"qa_{qa_pair['crop_name']}_{qa_pair['category']}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{i}"

            # 메타데이터 구성
            current_datetime = datetime.now()
            metadata = {
                "data_type": "qa_pair",
                "crop_name": qa_pair["crop_name"],
                "category": qa_pair["category"],
                "question": qa_pair["question"],
                "document_title": qa_pair.get("document_title", ""),
                "learning_date": current_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                "is_generated": True,
                "is_learned_flag": True,
                "record_datetime": current_datetime.strftime("%Y-%m-%d %H:%M:%S")
            }

            if farm_id:
                metadata["farm_id"] = farm_id

            # QA 문서 구성
            document = f"Q: {qa_pair['question']}\nA: {qa_pair['answer']}"

            ids.append(qa_id)
            metadatas.append(metadata)
            documents.append(document)

        status = upsert_collection_data(
            "store_crop_qa_pairs",
            learned_collection(),
            ids,
            metadatas,
            documents
        )
        if status != "added" and status != "updated":
            logger.warning(f"store_crop_qa_pairs 문서 저장 실패 - status={status}")

        logger.info(f"총 {len(qa_pairs)}개의 Q & A 쌍이 저장되었습니다.")
        return len(qa_pairs)

    except Exception as e:
        logger.error(f"Q & A 쌍 저장 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 0


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 구조화된 정보 추출
# --->
# 원문에서 구조화된 핵심 정보 추출
# Args:
# document_content: 원문 내용
# document_type: 문서 유형
# Returns:
# dict: 구조화된 정보
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def extract_structured_information(document_content, document_type='crop_info'):
    structured_info = {
        "document_type": document_type,
        "extracted_data": {},
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    try:
        if document_type == 'crop_info':
            crop_patterns = {
                "상황버섯": r'상황\s*버섯',
                "작약": r'작약',
                "쇠무릎": r'쇠\s*무릎'
            }

            crop_name = None
            first_chunk = document_content[:1000]

            for crop, pattern in crop_patterns.items():
                if re.search(pattern, first_chunk, re.IGNORECASE):
                    crop_name = crop
                    break

            if crop_name:
                structured_info["extracted_data"]["crop_name"] = crop_name

        elif document_type == 'disease_info':
            _extract_disease_info(document_content, structured_info)

        return structured_info

    except Exception as e:
        logger.error(f"구조화 정보 추출 중 오류: {e}")
        structured_info["error"] = str(e)
        return structured_info


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 병해충 정보 추출
# --->
# 병해충 정보 추출
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _extract_disease_info(document_content, structured_info):
    disease_matches = re.finditer(
        r'(\d+\)\s*([^\n]+)병[^\n]*)\s*\n\s*가\)\s*병원균[^\n]*\n(.*?)(?=\s*\d+\)\s*|\Z)',
        document_content, re.DOTALL
    )
    diseases = []
    for match in disease_matches:
        disease_name = match.group(2).strip() + "병"
        description = match.group(3).strip()

        pathogen_match = re.search(r'병원균은\s*([^\.]+)\.', description)
        pathogen = pathogen_match.group(1).strip() if pathogen_match else ""

        symptom_match = re.search(r'병징\s*\n(.*?)(?=\s*나\))', description, re.DOTALL)
        symptom = symptom_match.group(1).strip() if symptom_match else ""

        prevention_match = re.search(r'예방\s*및\s*방제\s*\n(.*?)(?=\s*\d+\)|\Z)', description, re.DOTALL)
        prevention = prevention_match.group(1).strip() if prevention_match else ""

        diseases.append({
            "name": disease_name,
            "pathogen": pathogen,
            "symptom": symptom,
            "prevention": prevention
        })

    if diseases:
        structured_info["extracted_data"]["diseases"] = diseases
