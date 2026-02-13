# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Reflex 상태 관리 모듈
# 전체 애플리케이션의 상태를 클래스 기반으로 관리합니다.
# --->
# ChatState: 채팅 앱 전역 상태 관리 클래스
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import asyncio
import reflex as rx
from datetime import datetime
from typing import List, Dict, Optional, Any
from pydantic import BaseModel

try:
    from agri_ai_core.src.logs import setup_logger
    from agri_ai_core.src.postgresql.connection import db_session
    from agri_ai_core.src.postgresql.queries import (
        GET_ONE_FARM,
        GET_ONE_HOUSE,
        GET_FARM_NAME,
        GET_FARM_HOUSE_LIST,
    )
    from agri_ai_core.src.ai.query_handler_simple import query_llm_simple
    from agri_ai_core.src.ai.llm_client import clean_llm_response
except ModuleNotFoundError:
    from src.logs import setup_logger
    from src.postgresql.connection import db_session
    from src.postgresql.queries import (
        GET_ONE_FARM,
        GET_ONE_HOUSE,
        GET_FARM_NAME,
        GET_FARM_HOUSE_LIST,
    )
    from src.ai.query_handler_simple import query_llm_simple
    from src.ai.llm_client import clean_llm_response

logger = setup_logger(__name__)

# 프로젝트 루트 경로
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "upload")
DOWNLOAD_DIR = os.path.join(PROJECT_ROOT, "download")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)




# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 메시지 및 파일 데이터 모델
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class FileInfo(BaseModel):
    """파일 정보 모델"""
    name: str
    path: str
    type: str = ""
    size: int = 0
    upload_time: str = ""


class Message(BaseModel):
    """메시지 모델"""
    role: str
    content: str
    files: List[FileInfo] = []
    timestamp: str = ""

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 채팅 상태 관리 클래스
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class ChatState(rx.State):
    """채팅 앱 전역 상태 관리"""

    # 메시지 관리
    messages: List[Message] = []
    current_input: str = ""
    is_loading: bool = False
    input_locked: bool = False
    request_counter: int = 0
    active_request_id: int = 0
    canceled_request_id: int = 0

    # 파일 관리
    uploaded_files: List[FileInfo] = []

    # 농장 정보
    farm_id: str = "1"
    house_id: str = "1"
    farm_name: str = ""
    house_name: str = ""

    # 위치 정보
    weather_city: str = "정읍"

    # 농장/재배사 선택 옵션
    farm_options: List[Dict[str, str]] = []
    house_options: List[Dict[str, str]] = []
    selected_farm_index: int = 0
    selected_house_index: int = 0

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # Computed properties (UI에서 사용)
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    @rx.var
    def farm_option_labels(self) -> List[str]:
        """농장 선택 옵션 라벨 목록"""
        return [f"{farm['farm_name']} ({farm['farm_id']})" for farm in self.farm_options]

    @rx.var
    def house_option_labels(self) -> List[str]:
        """재배사 선택 옵션 라벨 목록"""
        return [f"{house['hous_name']} ({house['hous_id']})" for house in self.house_options]

    @rx.var
    def selected_farm_label(self) -> str:
        """현재 선택된 농장 라벨"""
        if self.farm_options and 0 <= self.selected_farm_index < len(self.farm_options):
            farm = self.farm_options[self.selected_farm_index]
            return f"{farm['farm_name']} ({farm['farm_id']})"
        if self.farm_name and self.farm_id:
            return f"{self.farm_name} ({self.farm_id})"
        return ""

    @rx.var
    def selected_house_label(self) -> str:
        """현재 선택된 재배사 라벨"""
        if self.house_options and 0 <= self.selected_house_index < len(self.house_options):
            house = self.house_options[self.selected_house_index]
            return f"{house['hous_name']} ({house['hous_id']})"
        if self.house_name and self.house_id:
            return f"{self.house_name} ({self.house_id})"
        return ""

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # 초기화
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    def on_load(self):
        """페이지 로드 시 초기화"""
        self.load_default_farm_info()
        self.load_farm_options()

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # 농장 정보 로드
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    def load_default_farm_info(self):
        """DB에서 기본 농장 정보 로드"""
        try:
            with db_session() as database:
                farm = database.fetch_one(GET_ONE_FARM)
                if not farm:
                    logger.warning("등록된 농장이 없습니다. 기본값 사용")
                    self.farm_id = "1"
                    self.house_id = "1"
                    self.farm_name = "기본농장"
                    self.house_name = "기본재배사"
                    return

                farm_id = str(farm.get("farm_id"))
                farm_name = farm.get("farm_name", "기본농장")

                house = database.fetch_one(GET_ONE_HOUSE, (farm_id,))
                if not house:
                    logger.warning(f"농장 {farm_id}에 재배사가 없습니다")
                    house_id = "1"
                    house_name = "기본재배사"
                else:
                    house_id = str(house.get("hous_id"))
                    house_name = house.get("hous_name", "기본재배사")

                self.farm_id = farm_id
                self.house_id = house_id
                self.farm_name = farm_name
                self.house_name = house_name
                logger.info(f"기본 농장 정보 로드: farm={farm_name}, house={house_name}")

        except Exception as e:
            logger.error(f"기본 농장 정보 조회 중 오류: {e}")
            self.farm_id = "1"
            self.house_id = "1"
            self.farm_name = "기본농장"
            self.house_name = "기본재배사"

    def load_farm_options(self):
        """농장 선택 옵션 로드"""
        try:
            with db_session() as database:
                farms = database.fetch_all(
                    query=GET_FARM_NAME,
                    vals=(None, None),
                    as_dict=True
                )

                if farms:
                    self.farm_options = [
                        {"farm_id": str(f["farm_id"]), "farm_name": f["farm_name"]}
                        for f in farms
                    ]
                    self.selected_farm_index = next(
                        (
                            i
                            for i, farm in enumerate(self.farm_options)
                            if farm["farm_id"] == self.farm_id
                        ),
                        0,
                    )
                    self.load_house_options()
        except Exception as e:
            logger.error(f"농장 옵션 로드 중 오류: {e}")

    def load_house_options(self):
        """재배사 선택 옵션 로드"""
        try:
            with db_session() as database:
                houses = database.fetch_all(
                    query=GET_FARM_HOUSE_LIST,
                    vals=(self.farm_id, None, None),
                    as_dict=True
                )

                if houses:
                    self.house_options = [
                        {"hous_id": str(h["hous_id"]), "hous_name": h["hous_name"]}
                        for h in houses
                    ]
                    self.selected_house_index = next(
                        (
                            i
                            for i, house in enumerate(self.house_options)
                            if house["hous_id"] == self.house_id
                        ),
                        0,
                    )
        except Exception as e:
            logger.error(f"재배사 옵션 로드 중 오류: {e}")

    def select_farm(self, value: str):
        """농장 선택 (value는 라벨 문자열)"""
        try:
            # 선택된 라벨에서 인덱스 찾기
            labels = [f"{farm['farm_name']} ({farm['farm_id']})" for farm in self.farm_options]
            if value in labels:
                index = labels.index(value)
                self.selected_farm_index = index
                selected = self.farm_options[index]
                self.farm_id = selected["farm_id"]
                self.farm_name = selected["farm_name"]
                self.load_house_options()
                if self.house_options:
                    self.selected_house_index = 0
                    self.house_id = self.house_options[0]["hous_id"]
                    self.house_name = self.house_options[0]["hous_name"]
        except Exception as e:
            logger.error(f"농장 선택 중 오류: {e}")

    def select_house(self, value: str):
        """재배사 선택 (value는 라벨 문자열)"""
        try:
            # 선택된 라벨에서 인덱스 찾기
            labels = [f"{house['hous_name']} ({house['hous_id']})" for house in self.house_options]
            if value in labels:
                index = labels.index(value)
                self.selected_house_index = index
                selected = self.house_options[index]
                self.house_id = selected["hous_id"]
                self.house_name = selected["hous_name"]
        except Exception as e:
            logger.error(f"재배사 선택 중 오류: {e}")

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # 메시지 관리
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    def set_current_input(self, value: str):
        """입력창 텍스트 설정."""
        self.current_input = value

    def add_user_message(self, content: str, files: List[FileInfo] = None):
        """사용자 메시지 추가"""
        self.messages = [
            *self.messages,
            Message(
                role="user",
                content=content,
                files=files or [],
                timestamp=datetime.now().isoformat()
            )
        ]

    def add_assistant_message(self, content: str):
        """어시스턴트 메시지 추가"""
        self.messages = [
            *self.messages,
            Message(
                role="assistant",
                content=content,
                timestamp=datetime.now().isoformat()
            )
        ]

    def clear_messages(self):
        """메시지 기록 초기화"""
        self.messages = []

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # 파일 업로드 처리
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    async def handle_file_upload(self, files: List[rx.UploadFile]):
        """파일 업로드 처리"""
        try:
            for file in files:
                file_data = await file.read()
                file_path = os.path.join(UPLOAD_DIR, file.filename)

                with open(file_path, "wb") as f:
                    f.write(file_data)

                # 중복 방지
                if not any(f.name == file.filename for f in self.uploaded_files):
                    self.uploaded_files = [
                        *self.uploaded_files,
                        FileInfo(
                            name=file.filename,
                            path=file_path,
                            type=file.content_type or "unknown",
                            size=len(file_data),
                            upload_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        )
                    ]
        except Exception as e:
            logger.error(f"파일 업로드 중 오류: {e}")

    def remove_file(self, index: int):
        """파일 삭제"""
        try:
            if 0 <= index < len(self.uploaded_files):
                file_info = self.uploaded_files[index]
                file_path = file_info.path

                if os.path.exists(file_path):
                    os.remove(file_path)

                # 리스트에서 제거
                new_files = [f for i, f in enumerate(self.uploaded_files) if i != index]
                self.uploaded_files = new_files
        except Exception as e:
            logger.error(f"파일 삭제 중 오류: {e}")

    def cleanup_uploaded_files(self):
        """업로드된 파일 모두 정리"""
        for file_info in self.uploaded_files:
            try:
                if os.path.exists(file_info.path):
                    os.remove(file_info.path)
            except Exception:
                pass
        self.uploaded_files = []

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # 메시지 전송 처리
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    @rx.event(background=True)
    async def send_message(self):
        """메시지 전송 및 LLM 응답 처리"""
        request_id: Optional[int] = None
        user_query = ""
        current_files: List[FileInfo] = []
        farm_id = ""
        house_id = ""
        farm_name = ""
        house_name = ""

        async with self:
            if self.is_loading:
                return
            if not self.current_input.strip():
                return

            # 요청 식별자 발급 (취소/중복 응답 방지)
            self.request_counter += 1
            request_id = self.request_counter
            self.active_request_id = request_id

            # 즉시 로딩 상태로 전환하여 Enter/버튼 중복 전송을 차단
            self.is_loading = True
            self.input_locked = True

            # 사용자 메시지 추가
            user_query = self.current_input.strip()
            current_files = self.uploaded_files.copy()
            self.add_user_message(user_query, current_files)

            # 요청 시점의 문맥 스냅샷
            farm_id = self.farm_id
            house_id = self.house_id
            farm_name = self.farm_name
            house_name = self.house_name

            # 입력 초기화
            self.current_input = ""

        try:
            # 파일 경로 준비
            file_paths = None
            if current_files:
                file_paths = [
                    {"filename": f.name, "path": f.path}
                    for f in current_files
                ]

            async def _run_llm_query() -> str:
                """LLM 질의 실행"""
                response_text = ""
                async for chunk in query_llm_simple(
                    user_query,
                    file_paths,
                    farm_id,
                    house_id,
                    farm_name,
                    house_name
                ):
                    response_text = chunk
                    break  # 단일 응답
                return clean_llm_response(response_text)

            # 입력 잠금 2초 유지 후 해제 (요청이 여전히 유효할 때만)
            await asyncio.sleep(2)
            async with self:
                if self.active_request_id == request_id and self.is_loading:
                    self.input_locked = False

            response = await _run_llm_query()

            # 응답 정리 및 추가
            async with self:
                # 취소/교체된 요청 응답은 화면에 반영하지 않음
                if (
                    self.active_request_id != request_id
                    or self.canceled_request_id >= request_id
                ):
                    return
                self.add_assistant_message(response)

        except Exception as e:
            logger.error(f"메시지 전송 중 오류: {e}")
            async with self:
                if (
                    request_id is not None
                    and self.active_request_id == request_id
                    and self.canceled_request_id < request_id
                ):
                    self.add_assistant_message(f"응답 생성 중 오류가 발생했습니다: {str(e)}")
        finally:
            if request_id is None:
                return
            async with self:
                if self.active_request_id == request_id:
                    self.is_loading = False
                    self.input_locked = False
                    self.active_request_id = 0

    def cancel_message(self):
        """진행 중인 LLM 응답 표시를 취소하고 UI를 즉시 복구."""
        if not self.is_loading:
            return
        if self.active_request_id > 0:
            self.canceled_request_id = max(
                self.canceled_request_id,
                self.active_request_id,
            )
        self.is_loading = False
        self.input_locked = False
        self.active_request_id = 0

    def handle_send_button_click(self):
        """전송/취소 버튼 동작 분기."""
        if self.is_loading:
            return ChatState.cancel_message
        return ChatState.send_message

    def handle_key_down(self, key: str):
        """입력창 keydown 이벤트 처리 (Enter 전송)."""
        if key == "Enter" and not self.is_loading:
            return ChatState.send_message

    def handle_form_submit(self, form_data: Dict[str, Any]):
        """폼 submit 처리 (Enter 전송용)."""
        if not self.is_loading:
            return ChatState.send_message

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # 위치 설정
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    def set_weather_city(self, city: str):
        """날씨 도시 설정"""
        self.weather_city = city
