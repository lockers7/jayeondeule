# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 파일 처리 모듈
# 업로드된 파일을 읽고 LLM이 처리할 수 있는 형식으로 변환합니다.
# --->
# process_uploaded_files: 업로드된 파일 목록 처리
# read_csv_file: CSV 파일 읽기
# read_excel_file: Excel 파일 읽기
# read_text_file: 텍스트 파일 읽기
# read_pdf_file: PDF 파일 읽기
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import pandas as pd
from typing import List, Dict, Any

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# CSV 파일 읽기
# ---&gt;
# CSV 파일을 읽어서 문자열로 반환
#
# Args:
#     file_path: 파일 경로
#     max_rows: 최대 행 수 (기본 100)
#
# Returns:
#     str: CSV 내용 (텍스트 형식)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _format_dataframe(df, max_rows, prefix=""):
    """DataFrame을 행 제한 + 요약 텍스트로 변환 (CSV/Excel 공용)"""
    total_rows = len(df)
    if total_rows > max_rows:
        df = df.head(max_rows)
        summary = f"{prefix}총 {total_rows}개 행 중 처음 {max_rows}개 행만 표시합니다.\n"
    else:
        summary = f"{prefix}총 {total_rows}개 행입니다.\n"
    columns_info = f"컬럼: {', '.join(df.columns.tolist())}\n"
    return f"{summary}{columns_info}\n{df.to_string(index=False)}"


def read_csv_file(file_path: str, max_rows: int = 100) -> str:
    try:
        return _format_dataframe(pd.read_csv(file_path), max_rows, prefix="\n")
    except Exception as e:
        logger.error(f"CSV 파일 읽기 오류 ({file_path}): {e}")
        return f"CSV 파일을 읽을 수 없습니다: {str(e)}"


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Excel 파일 읽기
# ---&gt;
# Excel 파일을 읽어서 문자열로 반환
#
# Args:
#     file_path: 파일 경로
#     max_rows: 최대 행 수 (기본 100)
#
# Returns:
#     str: Excel 내용 (텍스트 형식)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def read_excel_file(file_path: str, max_rows: int = 100) -> str:
    try:
        excel_file = pd.ExcelFile(file_path)
        result = [
            _format_dataframe(
                pd.read_excel(file_path, sheet_name=name),
                max_rows,
                prefix=f"[시트: {name}] ",
            )
            for name in excel_file.sheet_names
        ]
        return "\n\n".join(result)
    except Exception as e:
        logger.error(f"Excel 파일 읽기 오류 ({file_path}): {e}")
        return f"Excel 파일을 읽을 수 없습니다: {str(e)}"


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 텍스트 파일 읽기
# ---&gt;
# 텍스트 파일을 읽어서 문자열로 반환
#
# Args:
#     file_path: 파일 경로
#     max_chars: 최대 문자 수 (기본 10000)
#
# Returns:
#     str: 텍스트 내용
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def read_text_file(file_path: str, max_chars: int = 10000) -> str:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read(max_chars)

        if len(content) >= max_chars:
            return f"{content}\n\n... (파일이 너무 길어 일부만 표시됩니다)"

        return content

    except UnicodeDecodeError:
        try:
            # UTF-8 실패 시 다른 인코딩 시도
            with open(file_path, 'r', encoding='cp949') as f:
                content = f.read(max_chars)

            if len(content) >= max_chars:
                return f"{content}\n\n... (파일이 너무 길어 일부만 표시됩니다)"

            return content
        except Exception as e:
            logger.error(f"텍스트 파일 읽기 오류 ({file_path}): {e}")
            return f"텍스트 파일을 읽을 수 없습니다: {str(e)}"

    except Exception as e:
        logger.error(f"텍스트 파일 읽기 오류 ({file_path}): {e}")
        return f"텍스트 파일을 읽을 수 없습니다: {str(e)}"


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# PDF 파일 읽기
# --->
# PDF 파일의 텍스트를 추출하여 문자열로 반환
#
# Args:
#     file_path: 파일 경로
# Returns:
#     str: PDF 텍스트 내용
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def read_pdf_file(file_path: str) -> str:
    try:
        from PyPDF2 import PdfReader

        reader = PdfReader(file_path)
        total_pages = len(reader.pages)

        extracted = []

        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if not text:
                continue
            text = text.strip()
            if not text:
                continue
            extracted.append(f"[페이지 {i+1}]\n{text}")

        if not extracted:
            return "PDF 파일에서 텍스트를 추출할 수 없습니다. (이미지 PDF일 수 있습니다)"

        header = f"총 {total_pages}페이지입니다.\n\n"
        return header + "\n\n".join(extracted)

    except Exception as e:
        logger.error(f"PDF 파일 읽기 오류 ({file_path}): {e}")
        return f"PDF 파일을 읽을 수 없습니다: {str(e)}"


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 업로드된 파일 목록 처리
# ---&gt;
# 업로드된 파일 목록을 읽어서 LLM 프롬프트에 포함할 내용 생성
#
# Args:
#     file_paths: 파일 정보 목록 [{"filename": "...", "path": "..."}, ...]
#
# Returns:
#     str: 파일 내용을 포함한 프롬프트 텍스트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def process_uploaded_files(file_paths: List[Dict[str, str]]) -> str:
    if not file_paths:
        return ""

    logger.debug(f"파일 처리 시작: {len(file_paths)}개 파일")

    file_contents = []

    for file_info in file_paths:
        filename = file_info.get("filename", "")
        filepath = file_info.get("path", "")

        if not os.path.exists(filepath):
            logger.warning(f"파일을 찾을 수 없습니다: {filepath}")
            file_contents.append(f"[파일: {filename}]\n파일을 찾을 수 없습니다.\n")
            continue

        # 파일 확장자 확인
        _, ext = os.path.splitext(filename)
        ext = ext.lower()

        logger.debug(f"파일 읽기: {filename} ({ext})")

        # 파일 타입별 처리
        if ext == '.csv':
            content = read_csv_file(filepath)
            file_contents.append(f"[첨부 파일: {filename}]\n{content}\n")

        elif ext in ['.xlsx', '.xls']:
            content = read_excel_file(filepath)
            file_contents.append(f"[첨부 파일: {filename}]\n{content}\n")

        elif ext == '.txt':
            content = read_text_file(filepath)
            file_contents.append(f"[첨부 파일: {filename}]\n{content}\n")

        elif ext == '.pdf':
            content = read_pdf_file(filepath)
            file_contents.append(f"[첨부 파일: {filename}]\n{content}\n")

        elif ext in ['.jpg', '.jpeg', '.png']:
            # 이미지는 나중에 구현 (OCR 필요)
            file_contents.append(f"[첨부 파일: {filename}]\n이미지 파일은 현재 지원하지 않습니다.\n")

        else:
            file_contents.append(f"[첨부 파일: {filename}]\n지원하지 않는 파일 형식입니다.\n")

    if file_contents:
        header = "\n\n=== 첨부된 파일 내용 ===\n\n"
        footer = "\n\n=== 첨부 파일 끝 ===\n\n"
        return header + "\n".join(file_contents) + footer

    return ""
