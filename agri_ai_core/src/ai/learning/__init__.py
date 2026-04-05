# ══════════════════════════════════
# Machine Learning & Training Module
# ══════════════════════════════════
from agri_ai_core.src.ai.learning.model_trainer import verify_chroma_connection, update_ollama_model
from agri_ai_core.src.ai.learning.data_analyzer import analyze_farm_optimal_conditions

__all__ = [
    "verify_chroma_connection",
    "update_ollama_model",
    "analyze_farm_optimal_conditions",
]
