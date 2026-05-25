# ════════════════════════════════════════════════════════════════════
# ChromaFlowStudio 1.0.0.3000 ↔ chromadb 1.0 / 운영 ChromaDB 호환 shim.
#
# 목적:
#   1) list_collections() 가 [str] 을 반환하던 시기 가정 → 1.0+ 의 Collection 객체
#      반환을 문자열로 평탄화 (compat).
#   2) get_collection(name=Collection(...)) 같은 잘못된 인자 → 객체에서 .name 추출.
#   3) SentenceTransformerEmbeddingFunction 을 운영 시스템과 동일한
#      Ollama bge-m3 호출로 교체 — 운영 ChromaDB(1024차원) 와 임베딩 100% 일치.
#      운영 embedder.py 와 동일한 호출 옵션 사용:
#        · /api/embed (신 API) 우선 + 404 시 /api/embeddings 폴백
#        · keep_alive="0", options={"num_gpu":0}  ← CPU 모드, GPU 메모리 충돌 회피
# ════════════════════════════════════════════════════════════════════
import json
import urllib.request
import urllib.error

import chromadb.api.client as _cc
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb.utils import embedding_functions as _ef


# ────────────────────────────────────────────────────────────────────
# (1) list_collections → 항상 문자열 리스트 반환.
# ────────────────────────────────────────────────────────────────────
_orig_list = _cc.Client.list_collections
def _patched_list(self, *args, **kwargs):
    return [getattr(c, "name", c) for c in _orig_list(self, *args, **kwargs)]
_cc.Client.list_collections = _patched_list


# ────────────────────────────────────────────────────────────────────
# (2) get_collection(name=Collection(...)) → 객체면 .name 추출.
# ────────────────────────────────────────────────────────────────────
_orig_get = _cc.Client.get_collection
def _patched_get(self, name=None, *args, **kwargs):
    if hasattr(name, "name"):
        name = name.name
    return _orig_get(self, name=name, *args, **kwargs)
_cc.Client.get_collection = _patched_get


# ────────────────────────────────────────────────────────────────────
# (3) Ollama bge-m3 임베딩 함수 — 운영 시스템과 동일한 1024차원 임베딩.
# ────────────────────────────────────────────────────────────────────
_OLLAMA_EMBED_URL = "http://127.0.0.1:11434/api/embed"
_OLLAMA_EMBEDDINGS_URL = "http://127.0.0.1:11434/api/embeddings"
_OPTIONS = {"num_gpu": 0}


def _ollama_embed_one(text: str) -> list:
    # keep_alive=-1: bge-m3 를 메모리에 영구 상주 (CPU 사용 — num_gpu=0 옵션과 함께
    # GPU OOM 회피). 매 호출 시 모델 재로드 부하 제거 → gemma3:27b GPU 메모리 안정.
    body_new = json.dumps({
        "model": "bge-m3",
        "input": text,
        "keep_alive": -1,
        "options": _OPTIONS,
    }).encode("utf-8")
    req = urllib.request.Request(
        _OLLAMA_EMBED_URL, data=body_new,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
            embs = data.get("embeddings")
            if embs:
                return embs[0]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise

    body_old = json.dumps({
        "model": "bge-m3",
        "prompt": text,
        "keep_alive": -1,
        "options": _OPTIONS,
    }).encode("utf-8")
    req = urllib.request.Request(
        _OLLAMA_EMBEDDINGS_URL, data=body_old,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["embedding"]


class OllamaBgeM3(EmbeddingFunction[Documents]):
    def __init__(self):
        pass

    def __call__(self, input: Documents) -> Embeddings:
        if isinstance(input, str):
            input = [input]
        return [_ollama_embed_one(t) for t in input]

    @staticmethod
    def name() -> str:
        return "ollama-bge-m3"


_ef.SentenceTransformerEmbeddingFunction = lambda *a, **kw: OllamaBgeM3()
