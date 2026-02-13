# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 채팅 UI 스타일
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
CHAT_STYLES = """
    <style>
        /* 기본 스타일 */
        body {
            background-color: #F4F4F9; /* 연한 회색 배경 */
            font-family: 'Noto Sans', sans-serif;
        }
        .chat-container {
            max-width: 700px;
            margin: auto;
        }

        /* 사용자 메시지 (말풍선 스타일 적용) */
        .user-message {
            background-color: #FFDDC1;
            padding: 12px;
            border-radius: 20px;
            margin-bottom: 10px;
            width: fit-content;
            max-width: 80%;
            box-shadow: 2px 2px 5px rgba(0, 0, 0, 0.1);
            position: relative;
        }
        .user-message::after {
            content: "";
            position: absolute;
            bottom: 0;
            right: -10px;
            width: 0;
            height: 0;
            border-left: 10px solid #FFDDC1;
            border-top: 10px solid transparent;
        }

        /* 챗봇 메시지 */
        .bot-message {
            background-color: #D4ECDD;
            padding: 12px;
            border-radius: 20px;
            margin-bottom: 10px;
            width: fit-content;
            max-width: 80%;
            box-shadow: 2px 2px 5px rgba(0, 0, 0, 0.1);
            position: relative;
        }
        .bot-message::after {
            content: "";
            position: absolute;
            bottom: 0;
            left: -10px;
            width: 0;
            height: 0;
            border-right: 10px solid #D4ECDD;
            border-top: 10px solid transparent;
        }

        .chat-input {
            width: 100%;
            padding: 12px;
            border-radius: 25px;
            border: 1px solid #ccc;
            font-size: 16px;
            outline: none;
            transition: all 0.3s ease-in-out;
            color: #000000; /* 텍스트 색상을 검정색으로 설정 */
            font-weight: 500; /* 글꼴 두께를 좀 더 진하게 설정 */
        }

        .chat-input:focus {
            border: 1px solid #2F4F4F;
            box-shadow: 0px 0px 8px rgba(47, 79, 79, 0.5);
        }

        .chat-input::placeholder {
            color: #666;
            font-style: italic;
        }

        .stChatInput div[data-testid="stChatInput"] input::placeholder {
            color: #333333 !important; /* placeholder 색상도 진하게 설정 */
            font-weight: 500;
        }

        /* 파일 업로드 영역 스타일 */
        .file-uploader {
            border: 2px dashed #aaa;
            border-radius: 10px;
            padding: 10px;
            text-align: center;
            margin-bottom: 15px;
            background-color: #f8f9fa;
        }

        /* 첨부 파일 표시 영역 */
        .file-attachment {
            background-color: #f0f8ff;
            border-radius: 5px;
            padding: 8px;
            margin-top: 5px;
            border-left: 3px solid #4682B4;
        }

        /* 첨부 파일 이름 스타일 */
        .file-name {
            font-weight: 500;
            color: #2F4F4F;
        }
    </style>
"""


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 페이지 타이틀 스타일
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
PAGE_TITLE_HTML = """
    <h1 style='text-align: center; color: #2F4F4F;'>🌿 자연들에 상황버섯 AI 🌿</h1>
"""


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 파일 첨부 표시 HTML 템플릿
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
FILE_ATTACHMENT_TEMPLATE = """
    <div class='file-attachment'>
        📎 <span class='file-name'>{filename}</span>
    </div>
"""
