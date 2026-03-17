# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 파일 처리 모듈
# 업로드된 파일을 읽고 LLM이 처리할 수 있는 형식으로 변환합니다.
# --->
# _format_dataframe: CSV 파일 읽기
# read_csv_file: CSV 파일 읽기
# read_excel_file: Excel 파일 읽기
# read_text_file: 텍스트 파일 읽기
# read_pdf_file: PDF 파일 읽기
# process_uploaded_files: 업로드된 파일 목록 처리
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import pandas as pd
from typing import List, Dict

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
# DataFrame을 행 제한 + 요약 텍스트로 변환 (CSV/Excel 공용)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _format_dataframe(df, max_rows, prefix=""):
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
_TEXT_ENCODINGS = ("utf-8", "cp949", "euc-kr", "utf-8-sig", "latin-1")


def read_text_file(file_path: str, max_chars: int = 10000) -> str:
    for encoding in _TEXT_ENCODINGS:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read(max_chars)

            if len(content) >= max_chars:
                return f"{content}\n\n... (파일이 너무 길어 일부만 표시됩니다)"

            return content
        except (UnicodeDecodeError, UnicodeError):
            continue

    logger.error(f"텍스트 파일 읽기 오류 ({file_path}): 지원되는 인코딩 없음")
    return "텍스트 파일을 읽을 수 없습니다: 인코딩을 감지할 수 없습니다."


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
    # 1차 시도: PyMuPDF (fitz) — 일반 텍스트 PDF 추출
    # 2차 시도: PyMuPDF OCR — 이미지 스캔 PDF (tesseract 필요)
    # 3차 시도: PyPDF2 폴백
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(file_path)
        total_pages = doc.page_count
        extracted = []

        for i in range(total_pages):
            text = doc[i].get_text("text")
            if text and text.strip():
                extracted.append(f"[페이지 {i+1}]\n{text.strip()}")

        if extracted:
            doc.close()
            header = f"총 {total_pages}페이지입니다.\n\n"
            logger.debug(f"[PDF] PyMuPDF 추출 성공: {file_path} ({len(extracted)}/{total_pages}페이지)")
            return header + "\n\n".join(extracted)

        # 텍스트 추출 실패 → OCR 시도 (doc 아직 열려 있음)
        logger.info(f"[PDF] 텍스트 없음 → OCR 시도 (이미지 PDF): {file_path}")
        try:
            ocr_extracted = []
            for i in range(total_pages):
                page = doc[i]
                tp = page.get_textpage_ocr(flags=0, full=True)
                text = page.get_text(textpage=tp).strip()
                if text:
                    ocr_extracted.append(f"[페이지 {i+1}]\n{text}")
            doc.close()
            if ocr_extracted:
                header = f"총 {total_pages}페이지입니다. (OCR 추출)\n\n"
                logger.info(f"[PDF] OCR 추출 성공: {file_path} ({len(ocr_extracted)}/{total_pages}페이지)")
                return header + "\n\n".join(ocr_extracted)
            logger.warning(f"[PDF] OCR 텍스트 없음: {file_path}")
            doc.close()
        except Exception as ocr_err:
            logger.warning(f"[PDF] OCR 실패: {ocr_err}")
            try:
                doc.close()
            except Exception:
                pass

        logger.warning(f"[PDF] PyMuPDF 텍스트/OCR 없음, PyPDF2로 폴백: {file_path}")
    except Exception as e:
        logger.warning(f"[PDF] PyMuPDF 실패, PyPDF2로 폴백: {file_path} ({e})")

    # 2차 시도: PyPDF2 폴백
    try:
        from PyPDF2 import PdfReader

        reader = PdfReader(file_path)
        total_pages = len(reader.pages)
        extracted = []

        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if not text or not text.strip():
                continue
            extracted.append(f"[페이지 {i+1}]\n{text.strip()}")

        if extracted:
            header = f"총 {total_pages}페이지입니다.\n\n"
            logger.debug(f"[PDF] PyPDF2 폴백 추출 성공: {file_path}")
            return header + "\n\n".join(extracted)

        logger.warning(f"[PDF] 두 라이브러리 모두 텍스트 추출 실패 (이미지 PDF + tesseract 미설치): {file_path}")
        return ""

    except Exception as e:
        logger.error(f"PDF 파일 읽기 오류 ({file_path}): {e}")
        return ""


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
