# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 채팅 UI 스타일
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
CHAT_STYLES = """
    <style>
        /* 기본 스타일 */
        body {
            background-color: #F8F9FA;
            font-family: 'Noto Sans KR', sans-serif;
        }

        /* 최상단 고정 영역 */
        .fixed-top-section {
            position: sticky;
            top: 0;
            z-index: 100;
            background-color: #ffffff;
            padding: 15px;
            border-bottom: 2px solid #e9ecef;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }

        /* 채팅 입력창 스타일 */
        .stChatInput {
            position: sticky;
            top: 0;
            z-index: 99;
            background-color: #ffffff;
            padding: 10px 0;
        }

        .stChatInput input {
            border: 2px solid #28a745 !important;
            border-radius: 12px !important;
            padding: 12px 20px !important;
            font-size: 15px !important;
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
        }

        /* 파일 첨부 영역 */
        .file-upload-section {
            background-color: #f8f9fa;
            border-radius: 10px;
            padding: 12px;
            margin: 10px 0;
            border: 1px solid #dee2e6;
        }

        /* 파일 업로드 버튼 */
        .stFileUploader {
            border: 2px dashed #ced4da;
            border-radius: 8px;
            padding: 8px;
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
            border-left: 4px solid #28a745;
            border-radius: 6px;
            padding: 8px 12px;
            margin: 5px 0;
            font-size: 14px;
        }

        .file-name {
            font-weight: 600;
            color: #155724;
        }

        /* 구분선 스타일 */
        hr {
            border: none;
            height: 2px;
            background: linear-gradient(to right, #28a745, #20c997, #28a745);
            margin: 20px 0;
        }

        /* 채팅 메시지 */
        .stChatMessage {
            margin-bottom: 12px;
            padding: 10px;
            border-radius: 10px;
            animation: fadeIn 0.3s ease-in;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* 사용자 메시지 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
        }

        /* 어시스턴트 메시지 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
            background-color: #d1ecf1;
            border-left: 4px solid #17a2b8;
        }

        /* 타이틀 스타일 개선 */
        h1 {
            margin-bottom: 20px !important;
            padding-bottom: 10px !important;
            border-bottom: 3px solid #28a745 !important;
        }

        h4 {
            color: #495057 !important;
            font-weight: 600 !important;
            margin-top: 10px !important;
            margin-bottom: 10px !important;
        }

        /* 캡션 스타일 */
        .stCaption {
            color: #6c757d !important;
            font-size: 13px !important;
        }
    </style>
"""


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 페이지 타이틀 스타일
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
PAGE_TITLE_HTML = """
    <div style='text-align: center; padding: 10px 0;'>
        <h1 style='color: #28a745; margin: 0; font-size: 32px; font-weight: 700;'>
            🍄 자연들에 상황버섯 AI
        </h1>
        <p style='color: #6c757d; font-size: 14px; margin: 5px 0 0 0;'>
            스마트팜 관리 및 재배 상담 서비스
        </p>
    </div>
"""


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 파일 첨부 표시 HTML 템플릿
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
FILE_ATTACHMENT_TEMPLATE = """
    <div class='file-attachment'>
        <span style='margin-right: 5px;'>📎</span>
        <span class='file-name'>{filename}</span>
    </div>
"""
