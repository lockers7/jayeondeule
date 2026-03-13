"""
AI 스마트팜 컨설턴트 - Streamlit UI
메인 애플리케이션: 대화형 인터페이스
"""
import streamlit as st
import sys
import time
from pathlib import Path

# 프로젝트 경로 추가
PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

from config import PAGE_TITLE, PAGE_ICON, LLM_MODEL, OLLAMA_BASE_URL
from agents.graph import get_graph
from rag.vectorstore import initialize_vectorstore
from langchain_core.messages import HumanMessage, AIMessage

# ============================================================
# 페이지 설정
# ============================================================
st.set_page_config(
    page_title=PAGE_TITLE,
    page_icon=PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# 커스텀 CSS
# ============================================================
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #2E7D32;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1rem;
        color: #666;
        margin-bottom: 1.5rem;
    }
    .status-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .badge-crop { background-color: #E8F5E9; color: #2E7D32; }
    .badge-pest { background-color: #FFF3E0; color: #E65100; }
    .badge-env { background-color: #E3F2FD; color: #1565C0; }
    .badge-general { background-color: #F3E5F5; color: #6A1B9A; }
    .agent-flow {
        background-color: #F5F5F5;
        border-radius: 8px;
        padding: 10px 15px;
        margin: 5px 0;
        font-size: 0.85rem;
    }
    .stChatMessage {
        max-width: 100%;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# 세션 상태 초기화
# ============================================================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "vectorstore_ready" not in st.session_state:
    st.session_state.vectorstore_ready = False


# ============================================================
# 벡터스토어 초기화 (최초 1회)
# ============================================================
@st.cache_resource
def init_vectorstore():
    """벡터스토어 초기화 (캐싱)"""
    return initialize_vectorstore()


# ============================================================
# 사이드바
# ============================================================
with st.sidebar:
    st.markdown("### 🌱 AI 스마트팜 컨설턴트")
    st.markdown("---")

    # 시스템 정보
    st.markdown("**시스템 정보**")
    st.markdown(f"- LLM: `{LLM_MODEL}`")
    st.markdown(f"- Ollama: `{OLLAMA_BASE_URL}`")

    st.markdown("---")

    # 벡터스토어 상태
    st.markdown("**RAG 벡터스토어**")
    if st.button("📚 지식 DB 초기화", use_container_width=True):
        with st.spinner("문서 임베딩 중..."):
            try:
                vs = initialize_vectorstore(force=True)
                st.session_state.vectorstore_ready = True
                st.success(f"✅ 벡터스토어 구축 완료!")
            except Exception as e:
                st.error(f"❌ 오류: {e}")

    st.markdown("---")

    # 문서 업로드
    st.markdown("**📄 문서 업로드 (RAG)**")
    uploaded_file = st.file_uploader(
        "농업 관련 문서를 업로드하세요",
        type=["txt", "pdf", "csv"],
        help="업로드된 문서는 RAG 지식 베이스에 추가됩니다."
    )
    if uploaded_file:
        try:
            content = uploaded_file.read().decode("utf-8", errors="ignore")
            from langchain_core.documents import Document
            from rag.vectorstore import get_vectorstore, chunk_documents

            docs = [Document(
                page_content=content,
                metadata={"source": uploaded_file.name, "title": uploaded_file.name}
            )]
            chunks = chunk_documents(docs)
            vs = get_vectorstore()
            vs.add_documents(chunks)
            st.success(f"✅ '{uploaded_file.name}' 추가 완료 ({len(chunks)}개 청크)")
        except Exception as e:
            st.error(f"❌ 업로드 오류: {e}")

    st.markdown("---")

    # 대화 초기화
    if st.button("🗑️ 대화 초기화", use_container_width=True):
        st.session_state.messages = []
        st.session_state.chat_history = []
        st.rerun()

    st.markdown("---")

    # 에이전트 플로우 설명
    with st.expander("🔄 에이전트 플로우"):
        st.markdown("""
        ```
        [사용자 질문]
             ↓
        [Router] 질문 유형 분류
             ├→ [RAG] 지식 검색
             │     ├→ [Tool Agent]
             │     └→ [Synthesizer]
             └→ [Tool Agent] 도구 실행
                   └→ [Synthesizer]
             ↓
        [최종 응답]
        ```

        **기술 스택:**
        - LangGraph (Multi-Agent Flow)
        - LangChain (ReAct Tool Agent)
        - ChromaDB (RAG Vector Store)
        - Ollama (Local LLM)
        - Streamlit (UI)
        """)

    # 과제 정보
    with st.expander("ℹ️ 과제 정보"):
        st.markdown("""
        **AI Agent 개인 과제**

        1. **Prompt Engineering**
           - 역할 부여, CoT, Few-shot
        2. **LangChain & LangGraph**
           - Multi-Agent Flow, ReAct
        3. **RAG**
           - ChromaDB, 문서 임베딩
        4. **서비스 개발**
           - Streamlit UI
        """)


# ============================================================
# 메인 영역
# ============================================================
st.markdown('<div class="main-header">🌱 AI 스마트팜 컨설턴트</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">LangGraph Multi-Agent 기반 스마트팜 전문 AI 어시스턴트</div>',
    unsafe_allow_html=True
)

# 벡터스토어 자동 초기화
if not st.session_state.vectorstore_ready:
    with st.spinner("🔄 지식 DB 준비 중..."):
        try:
            init_vectorstore()
            st.session_state.vectorstore_ready = True
        except Exception as e:
            st.warning(f"⚠️ 벡터스토어 초기화 실패: {e}\n사이드바에서 수동 초기화해주세요.")

# 기존 대화 표시
for message in st.session_state.messages:
    role = message["role"]
    with st.chat_message(role):
        st.markdown(message["content"])
        # 에이전트 처리 정보 표시
        if role == "assistant" and "metadata" in message:
            meta = message["metadata"]
            badge_map = {
                "crop_knowledge": ("작물 지식", "badge-crop"),
                "pest_diagnosis": ("병해충 진단", "badge-pest"),
                "environment": ("환경 관리", "badge-env"),
                "general": ("일반 질문", "badge-general"),
            }
            qt = meta.get("query_type", "general")
            label, badge_class = badge_map.get(qt, ("일반", "badge-general"))
            st.markdown(
                f'<span class="status-badge {badge_class}">{label}</span> '
                f'| 처리 시간: {meta.get("elapsed", 0):.1f}초',
                unsafe_allow_html=True
            )

# ============================================================
# 사용자 입력 처리
# ============================================================
if prompt := st.chat_input("스마트팜에 대해 무엇이든 물어보세요..."):
    # 사용자 메시지 표시
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # AI 응답 생성
    with st.chat_message("assistant"):
        status_container = st.empty()
        response_container = st.empty()

        try:
            graph = get_graph()

            # 에이전트 실행 상태 표시
            status_container.markdown(
                '<div class="agent-flow">🔄 질문을 분석하고 있습니다...</div>',
                unsafe_allow_html=True
            )

            start_time = time.time()

            # 그래프 실행
            initial_state = {
                "query": prompt,
                "query_type": "",
                "chat_history": st.session_state.chat_history[-10:],
                "rag_context": "",
                "tool_results": "",
                "messages": [],
                "collected_info": "",
                "final_response": "",
            }

            # 스트리밍 방식으로 노드별 상태 표시
            final_state = None
            node_labels = {
                "router": "🔀 질문 유형을 분류하고 있습니다...",
                "rag": "📚 관련 지식을 검색하고 있습니다...",
                "tool_agent": "🔧 도구를 실행하고 있습니다...",
                "synthesizer": "✍️ 최종 답변을 생성하고 있습니다...",
            }

            for event in graph.stream(initial_state):
                for node_name, node_state in event.items():
                    label = node_labels.get(node_name, f"처리 중: {node_name}")
                    status_container.markdown(
                        f'<div class="agent-flow">{label}</div>',
                        unsafe_allow_html=True
                    )
                    final_state = node_state

            elapsed = time.time() - start_time

            # 최종 응답 표시
            if final_state and "final_response" in final_state:
                response = final_state["final_response"]
            else:
                response = "응답을 생성하지 못했습니다. 다시 시도해주세요."

            status_container.empty()
            response_container.markdown(response)

            # 메타데이터 표시
            query_type = ""
            if final_state:
                query_type = final_state.get("query_type", "general")
            else:
                query_type = "general"

            badge_map = {
                "crop_knowledge": ("작물 지식", "badge-crop"),
                "pest_diagnosis": ("병해충 진단", "badge-pest"),
                "environment": ("환경 관리", "badge-env"),
                "general": ("일반 질문", "badge-general"),
            }
            label, badge_class = badge_map.get(query_type, ("일반", "badge-general"))
            st.markdown(
                f'<span class="status-badge {badge_class}">{label}</span> '
                f'| 처리 시간: {elapsed:.1f}초',
                unsafe_allow_html=True
            )

            # 세션에 저장
            st.session_state.messages.append({
                "role": "assistant",
                "content": response,
                "metadata": {
                    "query_type": query_type,
                    "elapsed": elapsed,
                }
            })

            # 대화 히스토리 업데이트 (멀티턴)
            st.session_state.chat_history.extend([
                HumanMessage(content=prompt),
                AIMessage(content=response),
            ])

        except Exception as e:
            status_container.empty()
            error_msg = f"⚠️ 오류가 발생했습니다: {str(e)}"
            response_container.error(error_msg)
            st.session_state.messages.append({
                "role": "assistant",
                "content": error_msg,
            })
