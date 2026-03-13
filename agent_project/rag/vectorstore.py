"""
RAG 벡터스토어 모듈
- ChromaDB PersistentClient (로컬, 기존 시스템과 분리)
- Ollama bge-m3 임베딩
- 문서 로딩 및 청킹
"""
import os
from pathlib import Path
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
import chromadb
from chromadb.config import Settings as ChromaSettings

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    OLLAMA_BASE_URL, EMBEDDING_MODEL, CHROMA_PERSIST_DIR,
    CHUNK_SIZE, CHUNK_OVERLAP
)


def get_embeddings() -> OllamaEmbeddings:
    """Ollama 기반 임베딩 모델 반환"""
    return OllamaEmbeddings(
        model=EMBEDDING_MODEL,
        base_url=OLLAMA_BASE_URL,
    )


def get_chroma_client():
    """ChromaDB PersistentClient 생성 (레거시 설정 충돌 방지)"""
    settings = ChromaSettings(chroma_db_impl=None)
    return chromadb.PersistentClient(
        path=CHROMA_PERSIST_DIR,
        settings=settings,
    )


def get_vectorstore() -> Chroma:
    """ChromaDB 벡터스토어 인스턴스 반환 (PersistentClient)"""
    client = get_chroma_client()
    return Chroma(
        client=client,
        collection_name="smartfarm_knowledge",
        embedding_function=get_embeddings(),
    )


def load_documents(data_dir: str = None) -> list[Document]:
    """data/ 디렉토리의 텍스트 파일들을 Document로 로드"""
    if data_dir is None:
        data_dir = str(Path(__file__).parent.parent / "data")

    documents = []
    for file_path in Path(data_dir).glob("*.txt"):
        content = file_path.read_text(encoding="utf-8")
        # [제목] 패턴으로 섹션 분리
        sections = content.split("\n[")
        for i, section in enumerate(sections):
            if not section.strip():
                continue
            if i > 0:
                section = "[" + section
            # 제목 추출
            title = ""
            if section.startswith("[") and "]" in section:
                title = section[1:section.index("]")]
            documents.append(Document(
                page_content=section.strip(),
                metadata={
                    "source": file_path.name,
                    "title": title,
                    "section_index": i,
                }
            ))
    return documents


def chunk_documents(documents: list[Document]) -> list[Document]:
    """문서를 청크로 분할"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_documents(documents)


def initialize_vectorstore(force: bool = False) -> Chroma:
    """벡터스토어 초기화 - 문서 로드 및 인덱싱"""
    vectorstore = get_vectorstore()

    # 이미 데이터가 있으면 스킵 (force=True면 재구축)
    existing = vectorstore._collection.count()
    if existing > 0 and not force:
        print(f"벡터스토어에 이미 {existing}개 문서가 있습니다. 스킵합니다.")
        return vectorstore

    print("문서 로딩 및 벡터스토어 구축 중...")
    documents = load_documents()
    chunks = chunk_documents(documents)
    print(f"  - 원본 문서: {len(documents)}개 섹션")
    print(f"  - 청크 수: {len(chunks)}개")

    # 기존 데이터 삭제 후 재구축
    if existing > 0:
        vectorstore._collection.delete(where={"source": {"$exists": True}})

    vectorstore.add_documents(chunks)
    print(f"  - 벡터스토어 구축 완료: {vectorstore._collection.count()}개 청크 저장")
    return vectorstore


if __name__ == "__main__":
    vs = initialize_vectorstore(force=True)
    # 테스트 검색
    results = vs.similarity_search("토마토 적정 온도", k=3)
    for r in results:
        print(f"\n[{r.metadata.get('title', 'N/A')}]")
        print(r.page_content[:200])
