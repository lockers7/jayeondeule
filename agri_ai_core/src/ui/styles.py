# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 채팅 UI 스타일
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
CHAT_STYLES = """
    <style>
        /* 기본 스타일 */
        body {
            background-color: #F8F9FA;
            font-family: 'Noto Sans KR', sans-serif;
            font-size: 13px;
            line-height: 1.3;
        }

        * {
            margin: 0 !important;
            padding: 0 !important;
            line-height: 1.3 !important;
        }

        /* 사이드바 전용 스타일 */
        [data-testid="stSidebar"] * {
            line-height: 1.0 !important;
        }

        /* 최상단 고정 영역 */
        .fixed-top-section {
            position: sticky;
            top: 0;
            z-index: 100;
            background-color: #ffffff;
            padding: 2px !important;
            border-bottom: 1px solid #e9ecef;
            box-shadow: none;
        }

        /* 채팅 입력창 스타일 */
        .stChatInput {
            position: sticky;
            top: 0;
            z-index: 99;
            background-color: #ffffff;
            padding: 2px 0 !important;
            margin: 0 !important;
        }

        .stChatInput input {
            border: 2px solid #28a745 !important;
            border-radius: 0 !important;
            padding: 6px 12px !important;
            font-size: 13px !important;
            font-weight: 500 !important;
            color: #212529 !important;
            box-shadow: none !important;
            line-height: 1.3 !important;
            width: 100% !important;
        }

        .stChatInput input:focus {
            border-color: #218838 !important;
            box-shadow: 0 4px 12px rgba(40, 167, 69, 0.2) !important;
        }

        .stChatInput input::placeholder {
            color: #6c757d !important;
            font-weight: 400 !important;
            font-size: 12px !important;
            line-height: 1.3 !important;
        }

        /* 파일 첨부 영역 */
        .file-upload-section {
            background-color: #ffffff;
            border-radius: 0;
            padding: 0 !important;
            margin: 0 !important;
            border: 2px solid #28a745;
            border-top: none;
        }

        /* 파일 업로드 버튼 */
        .stFileUploader {
            border: none;
            border-radius: 0;
            padding: 0 !important;
            margin: 0 !important;
            background-color: transparent;
            transition: all 0.2s;
        }

        .stFileUploader > div {
            padding: 0 !important;
            margin: 0 !important;
        }

        .stFileUploader label {
            padding: 0 !important;
            margin: 0 !important;
            display: none !important;
        }

        .stFileUploader section {
            padding: 6px 12px !important;
            border: none !important;
        }

        .stFileUploader:hover {
            border-color: #28a745;
            background-color: #f1f8f4;
        }

        /* 업로드된 파일 리스트 아이템 스타일 */
        .stFileUploader [data-testid="stFileUploaderFile"] {
            padding: 2px 4px !important;
            margin: 1px 0 !important;
            font-size: 11px !important;
            line-height: 1.2 !important;
        }

        /* 파일 리스트 아이템 hover 배경 제거 */
        .stFileUploader [data-testid="stFileUploaderFile"]:hover {
            background-color: transparent !important;
        }

        /* 파일 이름 텍스트 스타일 */
        .stFileUploader [data-testid="stFileUploaderFile"] span {
            font-size: 11px !important;
            line-height: 1.2 !important;
        }

        /* 파일 삭제 버튼 스타일 */
        .stFileUploader [data-testid="stFileUploaderFile"] button {
            padding: 1px 3px !important;
            font-size: 10px !important;
        }

        /* 첨부 파일 표시 */
        .file-attachment {
            background-color: #e7f5ea;
            border-left: 2px solid #28a745;
            border-radius: 0;
            padding: 4px 8px !important;
            margin: 0 !important;
            font-size: 13px;
            line-height: 1.3 !important;
        }

        .file-name {
            font-weight: 600;
            color: #155724;
            font-size: 13px;
            line-height: 1.3 !important;
        }

        /* 구분선 스타일 */
        hr {
            border: none;
            height: 1px;
            background: linear-gradient(to right, #28a745, #20c997, #28a745);
            margin: 5px 0 !important;
        }

        /* 채팅 메시지 */
        .stChatMessage {
            margin: 3px 0 !important;
            padding: 6px !important;
            border-radius: 0;
            animation: fadeIn 0.3s ease-in;
            font-size: 13px;
            line-height: 1.3 !important;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* 사용자 메시지 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
            background-color: #fff3cd;
            border-left: 2px solid #ffc107;
        }

        /* 어시스턴트 메시지 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
            background-color: #d1ecf1;
            border-left: 2px solid #17a2b8;
        }

        /* 타이틀 스타일 개선 */
        h1 {
            margin: 0 !important;
            padding: 4px 0 !important;
            border-bottom: 1px solid #28a745 !important;
            font-size: 20px !important;
            line-height: 1.3 !important;
        }

        h4 {
            color: #495057 !important;
            font-weight: 600 !important;
            margin: 2px 0 !important;
            font-size: 13px !important;
            line-height: 1.3 !important;
        }

        /* 캡션 스타일 */
        .stCaption {
            color: #6c757d !important;
            font-size: 11px !important;
            line-height: 1.3 !important;
        }

        /* 상단 우측 메뉴 */
        .top-right-menu {
            position: absolute;
            top: 8px;
            right: 10px;
            z-index: 1000;
        }

        .top-right-menu a {
            color: #495057;
            text-decoration: none;
            font-size: 18px;
            margin-left: 10px;
            transition: color 0.2s;
        }

        .top-right-menu a:hover {
            color: #28a745;
        }

        /* 전체 컨테이너 간격 최소화 */
        .block-container {
            padding-top: 0.2rem !important;
            padding-bottom: 0rem !important;
        }

        /* 마크다운 간격 최소화 */
        .stMarkdown {
            margin: 0 !important;
            padding: 0 !important;
            line-height: 0.9 !important;
        }

        /* 컬럼 간격 최소화 */
        [data-testid="column"] {
            padding: 0.1rem !important;
        }

        /* 모든 텍스트 요소 간격 */
        p, span, div {
            line-height: 1.3 !important;
        }

        /* 컬럼 내부 요소 */
        [data-testid="column"] > div {
            margin: 0 !important;
            padding: 0 !important;
        }

        /* 파일 업로드 컨테이너 내 컬럼 */
        .file-upload-container [data-testid="column"] {
            padding: 4px 8px !important;
        }

        /* 파일 첨부 컨테이너 */
        .file-upload-container {
            border: 2px solid #28a745;
            border-top: none;
            background-color: #ffffff;
            padding: 0 !important;
            margin: 0 !important;
        }

        .file-upload-container > div {
            padding: 0 !important;
            margin: 0 !important;
        }

        /* 파일 목록 스타일 */
        .file-list-item {
            padding: 4px 8px !important;
            margin: 0 !important;
            border-bottom: 1px solid #e9ecef;
        }

        .file-list-item:last-child {
            border-bottom: none;
        }
    </style>
"""


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 페이지 타이틀 스타일
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
PAGE_TITLE_HTML = """
    <div style='text-align: center; padding: 0; margin: 0; position: relative;'>
        <h1 style='color: #28a745; margin: 0; padding: 4px 0; font-size: 20px; font-weight: 700; line-height: 1.3;'>
            🍄 자연들에 상황버섯 AI
        </h1>
        <p style='color: #6c757d; font-size: 11px; margin: 0; padding: 2px 0; line-height: 1.3;'>
            스마트팜 관리 및 재배 상담 서비스
        </p>
        <div class='top-right-menu'>
            <a href='https://github.com/jayeondeule' target='_blank' title='GitHub'>⚙️</a>
            <a href='#' onclick='window.location.reload(); return false;' title='새로고침'>🔄</a>
            <a href='#' onclick='if(confirm("대화 기록을 삭제하시겠습니까?")) sessionStorage.clear(); return false;' title='초기화'>🗑️</a>
        </div>
    </div>
"""


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 파일 첨부 표시 HTML 템플릿
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
FILE_ATTACHMENT_TEMPLATE = """
    <div class='file-attachment' style='line-height: 1.3; padding: 4px 8px; margin: 0;'>
        <span style='margin-right: 4px; line-height: 1.3;'>📎</span>
        <span class='file-name' style='line-height: 1.3;'>{filename}</span>
    </div>
"""
