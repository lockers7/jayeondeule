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
        }

        /* 최상단 고정 영역 */
        .fixed-top-section {
            position: sticky;
            top: 0;
            z-index: 100;
            background-color: #ffffff;
            padding: 8px;
            border-bottom: 2px solid #e9ecef;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }

        /* 채팅 입력창 스타일 */
        .stChatInput {
            position: sticky;
            top: 0;
            z-index: 99;
            background-color: #ffffff;
            padding: 5px 0;
            margin-bottom: 5px !important;
        }

        .stChatInput input {
            border: 2px solid #28a745 !important;
            border-radius: 10px !important;
            padding: 8px 15px !important;
            font-size: 13px !important;
            font-weight: 500 !important;
            color: #212529 !important;
            box-shadow: 0 2px 8px rgba(40, 167, 69, 0.1) !important;
        }

        .stChatInput input:focus {
            border-color: #218838 !important;
            box-shadow: 0 4px 12px rgba(40, 167, 69, 0.2) !important;
        }

        .stChatInput input::placeholder {
            color: #6c757d !important;
            font-weight: 400 !important;
            font-size: 12px !important;
        }

        /* 파일 첨부 영역 */
        .file-upload-section {
            background-color: #f8f9fa;
            border-radius: 8px;
            padding: 6px;
            margin: 3px 0;
            border: 1px solid #dee2e6;
        }

        /* 파일 업로드 버튼 */
        .stFileUploader {
            border: 2px dashed #ced4da;
            border-radius: 6px;
            padding: 4px;
            background-color: #ffffff;
            transition: all 0.2s;
        }

        .stFileUploader:hover {
            border-color: #28a745;
            background-color: #f1f8f4;
        }

        /* 첨부 파일 표시 */
        .file-attachment {
            background-color: #e7f5ea;
            border-left: 3px solid #28a745;
            border-radius: 4px;
            padding: 5px 8px;
            margin: 3px 0;
            font-size: 12px;
        }

        .file-name {
            font-weight: 600;
            color: #155724;
            font-size: 12px;
        }

        /* 구분선 스타일 */
        hr {
            border: none;
            height: 1px;
            background: linear-gradient(to right, #28a745, #20c997, #28a745);
            margin: 8px 0;
        }

        /* 채팅 메시지 */
        .stChatMessage {
            margin-bottom: 6px;
            padding: 6px;
            border-radius: 8px;
            animation: fadeIn 0.3s ease-in;
            font-size: 13px;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* 사용자 메시지 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
            background-color: #fff3cd;
            border-left: 3px solid #ffc107;
        }

        /* 어시스턴트 메시지 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
            background-color: #d1ecf1;
            border-left: 3px solid #17a2b8;
        }

        /* 타이틀 스타일 개선 */
        h1 {
            margin-bottom: 5px !important;
            margin-top: 5px !important;
            padding-bottom: 5px !important;
            border-bottom: 2px solid #28a745 !important;
            font-size: 22px !important;
        }

        h4 {
            color: #495057 !important;
            font-weight: 600 !important;
            margin-top: 4px !important;
            margin-bottom: 4px !important;
            font-size: 14px !important;
        }

        /* 캡션 스타일 */
        .stCaption {
            color: #6c757d !important;
            font-size: 11px !important;
        }

        /* 전체 컨테이너 간격 최소화 */
        .block-container {
            padding-top: 1rem !important;
            padding-bottom: 0rem !important;
        }

        /* 마크다운 간격 최소화 */
        .stMarkdown {
            margin-bottom: 0.3rem !important;
        }

        /* 컬럼 간격 최소화 */
        [data-testid="column"] {
            padding: 0.3rem !important;
        }
    </style>
"""


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 페이지 타이틀 스타일
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
PAGE_TITLE_HTML = """
    <div style='text-align: center; padding: 3px 0; margin: 0;'>
        <h1 style='color: #28a745; margin: 0; font-size: 22px; font-weight: 700; line-height: 1.2;'>
            🍄 자연들에 상황버섯 AI
        </h1>
        <p style='color: #6c757d; font-size: 11px; margin: 2px 0 0 0; line-height: 1.2;'>
            스마트팜 관리 및 재배 상담 서비스
        </p>
    </div>
"""


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 파일 첨부 표시 HTML 템플릿
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
FILE_ATTACHMENT_TEMPLATE = """
    <div class='file-attachment'>
        <span style='margin-right: 3px;'>📎</span>
        <span class='file-name'>{filename}</span>
    </div>
"""
