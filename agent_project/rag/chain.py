"""
RAG 체인 모듈
- 벡터스토어 검색 + LLM 응답 생성
"""
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.vectorstore import get_vectorstore
from prompts.templates import RAG_RESPONSE_PROMPT
from config import RAG_TOP_K


def format_docs(docs) -> str:
    """검색된 문서를 텍스트로 포맷"""
    if not docs:
        return "관련 참고 자료를 찾지 못했습니다."
    formatted = []
    for i, doc in enumerate(docs, 1):
        title = doc.metadata.get("title", "참고자료")
        source = doc.metadata.get("source", "")
        formatted.append(
            f"### 참고자료 {i}: {title}\n"
            f"출처: {source}\n"
            f"{doc.page_content}"
        )
    return "\n\n---\n\n".join(formatted)


def retrieve_documents(query: str, k: int = None) -> list:
    """벡터스토어에서 관련 문서 검색"""
    if k is None:
        k = RAG_TOP_K
    vectorstore = get_vectorstore()
    return vectorstore.similarity_search(query, k=k)


def create_rag_chain(llm):
    """RAG 체인 생성 - 검색 + LLM 응답"""
    vectorstore = get_vectorstore()
    retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": RAG_TOP_K}
    )

    chain = (
        {
            "context": retriever | format_docs,
            "query": RunnablePassthrough(),
        }
        | RAG_RESPONSE_PROMPT
        | llm
        | StrOutputParser()
    )
    return chain
