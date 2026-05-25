# ══════════════════════════════════════════════════════════════════════════════
# test_llm_backend_vllm — vLLM backend 단위 테스트 [2026-05-25]
#
# 대상: agri_ai_core.src.ai.llm_backend_vllm
#   · is_enabled()         : LLM_BACKEND env switch
#   · _convert_options()   : ollama options → openai 필드
#   · _convert_format()    : ollama format → response_format
#   · _convert_response()  : openai response → ollama-호환 dict
#   · vllm_chat()          : HTTP 호출 mock + 시그니처
#
# 정책:
#   · 실 vLLM 서버 호출 없음 (HTTP mock)
#   · env 격리 (monkeypatch)
#
# 파일 시작 함수 목록:
#   TestSwitch          : LLM_BACKEND env 분기
#   TestConvertOptions  : options 매핑
#   TestConvertFormat   : json / schema 매핑
#   TestConvertResponse : openai response → ollama 형식
#   TestChatHTTP        : 모킹된 HTTP 호출
# ══════════════════════════════════════════════════════════════════════════════
import json
from unittest.mock import patch, MagicMock

import pytest


# ────────────────────────────────────────────────────────────────────
# 1) LLM_BACKEND switch
# ────────────────────────────────────────────────────────────────────
class TestSwitch:
    def test_default_disabled(self, monkeypatch):
        monkeypatch.delenv("LLM_BACKEND", raising=False)
        from agri_ai_core.src.ai import llm_backend_vllm
        assert llm_backend_vllm.is_enabled() is False

    def test_explicit_ollama(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "ollama")
        from agri_ai_core.src.ai import llm_backend_vllm
        assert llm_backend_vllm.is_enabled() is False

    def test_vllm_enabled(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "vllm")
        from agri_ai_core.src.ai import llm_backend_vllm
        assert llm_backend_vllm.is_enabled() is True

    def test_vllm_uppercase(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "VLLM")
        from agri_ai_core.src.ai import llm_backend_vllm
        assert llm_backend_vllm.is_enabled() is True

    def test_base_url_default(self, monkeypatch):
        monkeypatch.delenv("VLLM_URL", raising=False)
        from agri_ai_core.src.ai import llm_backend_vllm
        assert llm_backend_vllm._vllm_base_url() == "http://127.0.0.1:8001"

    def test_base_url_override(self, monkeypatch):
        monkeypatch.setenv("VLLM_URL", "http://192.168.0.10:8080/")
        from agri_ai_core.src.ai import llm_backend_vllm
        assert llm_backend_vllm._vllm_base_url() == "http://192.168.0.10:8080"


# ────────────────────────────────────────────────────────────────────
# 2) Options 변환
# ────────────────────────────────────────────────────────────────────
class TestConvertOptions:
    def test_num_predict_to_max_tokens(self):
        from agri_ai_core.src.ai.llm_backend_vllm import _convert_options
        r = _convert_options({"num_predict": 500})
        assert r["max_tokens"] == 500

    def test_temperature(self):
        from agri_ai_core.src.ai.llm_backend_vllm import _convert_options
        r = _convert_options({"temperature": 0.7})
        assert r["temperature"] == 0.7

    def test_top_k_goes_to_extra_body(self):
        from agri_ai_core.src.ai.llm_backend_vllm import _convert_options
        r = _convert_options({"top_k": 40})
        assert r["extra_body"]["top_k"] == 40

    def test_think_in_extra_body(self):
        from agri_ai_core.src.ai.llm_backend_vllm import _convert_options
        r = _convert_options({"think": False})
        assert r["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False

    def test_empty_options(self):
        from agri_ai_core.src.ai.llm_backend_vllm import _convert_options
        assert _convert_options(None) == {}
        assert _convert_options({}) == {}

    def test_format_json_inline(self):
        from agri_ai_core.src.ai.llm_backend_vllm import _convert_options
        r = _convert_options({"format": "json"})
        assert r["response_format"] == {"type": "json_object"}


# ────────────────────────────────────────────────────────────────────
# 3) Format 변환
# ────────────────────────────────────────────────────────────────────
class TestConvertFormat:
    def test_json_string(self):
        from agri_ai_core.src.ai.llm_backend_vllm import _convert_format
        assert _convert_format("json") == {"type": "json_object"}

    def test_schema_dict(self):
        from agri_ai_core.src.ai.llm_backend_vllm import _convert_format
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        r = _convert_format(schema)
        assert r["type"] == "json_schema"
        assert r["json_schema"]["schema"] == schema
        assert r["json_schema"]["strict"] is True


# ────────────────────────────────────────────────────────────────────
# 4) Response 변환 (OpenAI → Ollama)
# ────────────────────────────────────────────────────────────────────
class TestConvertResponse:
    def test_basic_content(self):
        from agri_ai_core.src.ai.llm_backend_vllm import _convert_response
        oai = {
            "model": "gemma3:27b",
            "choices": [{"message": {"role": "assistant", "content": "hello"}}],
            "usage": {"total_tokens": 12},
        }
        r = _convert_response(oai)
        assert r["message"]["content"] == "hello"
        assert r["message"]["role"] == "assistant"
        assert r["done"] is True

    def test_tool_calls_string_arguments_parsed(self):
        from agri_ai_core.src.ai.llm_backend_vllm import _convert_response
        oai = {
            "choices": [{"message": {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "get_x",
                                  "arguments": '{"farm_id": 1}'}}
                ]
            }}]
        }
        r = _convert_response(oai)
        tc = r["message"]["tool_calls"][0]
        # arguments string → dict 변환
        assert tc["function"]["arguments"] == {"farm_id": 1}
        assert tc["function"]["name"] == "get_x"

    def test_tool_calls_dict_arguments_passthrough(self):
        from agri_ai_core.src.ai.llm_backend_vllm import _convert_response
        oai = {
            "choices": [{"message": {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "g", "arguments": {"a": 1}}}
                ]
            }}]
        }
        r = _convert_response(oai)
        assert r["message"]["tool_calls"][0]["function"]["arguments"] == {"a": 1}

    def test_empty_choices(self):
        from agri_ai_core.src.ai.llm_backend_vllm import _convert_response
        r = _convert_response({"choices": []})
        assert r["message"]["content"] == ""


# ────────────────────────────────────────────────────────────────────
# 5) HTTP chat 호출 (mock)
# ────────────────────────────────────────────────────────────────────
class TestChatHTTP:
    def test_vllm_chat_basic(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "vllm")
        from agri_ai_core.src.ai import llm_backend_vllm as V

        fake_oai = {
            "model": "gemma3:27b",
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"total_tokens": 5},
        }
        with patch.object(V, "_http_post_json", return_value=fake_oai) as mh:
            r = V.vllm_chat(
                model="gemma3:27b",
                messages=[{"role": "user", "content": "hi"}],
                options={"num_predict": 100, "temperature": 0.5},
                tools=[{"type": "function", "function": {"name": "x"}}],
            )
        assert r["message"]["content"] == "ok"
        # payload 검증
        path, payload = mh.call_args.args[0], mh.call_args.args[1]
        assert path == "/v1/chat/completions"
        assert payload["model"] == "gemma3:27b"
        assert payload["max_tokens"] == 100
        assert payload["temperature"] == 0.5
        assert payload["tools"][0]["function"]["name"] == "x"
        assert payload["tool_choice"] == "auto"

    def test_vllm_generate_converts_to_chat(self, monkeypatch):
        from agri_ai_core.src.ai import llm_backend_vllm as V
        fake = {"choices": [{"message": {"role": "assistant",
                                          "content": '{"action":"keep"}'}}]}
        with patch.object(V, "_http_post_json", return_value=fake) as mh:
            r = V.vllm_generate(model="gemma3:27b",
                                prompt="센서 상태", format="json")
        # generate 는 response 필드도 채움
        assert r["response"] == '{"action":"keep"}'
        # 내부적으로 chat 으로 변환됐는지 — messages 로 단일 user
        payload = mh.call_args.args[1]
        assert payload["messages"][0]["role"] == "user"
        assert payload["messages"][0]["content"] == "센서 상태"
        # format=json → response_format
        assert payload["response_format"]["type"] == "json_object"


# ────────────────────────────────────────────────────────────────────
# 6) llm_transport._ollama_chat 의 backend switch (default ollama)
# ────────────────────────────────────────────────────────────────────
class TestTransportSwitch:
    def test_default_ollama_path_not_calling_vllm(self, monkeypatch):
        """LLM_BACKEND 미설정 → vllm_chat 호출 0."""
        monkeypatch.delenv("LLM_BACKEND", raising=False)
        from agri_ai_core.src.ai import llm_transport, llm_backend_vllm

        # ollama 흐름 자체는 transport 가 모두 비활성화되면 last_err 로 떨어짐.
        # 여기서는 vllm 분기에 들어가지 않는지만 검증 — vllm_chat 을 monkey-patch
        with patch.object(llm_backend_vllm, "vllm_chat") as mv:
            try:
                # 실 ollama 호출은 안 되어도 되니 transport 전부 비활성화
                with patch.object(llm_transport, "_use_ollama_package", return_value=False), \
                     patch.object(llm_transport, "_use_mcp_fetch", return_value=False), \
                     patch.object(llm_transport, "_is_direct_ollama_enabled", return_value=False):
                    try:
                        llm_transport._ollama_chat(
                            model="x", messages=[{"role":"user","content":"hi"}])
                    except Exception:
                        pass  # 모든 transport 비활성화 → UnboundLocalError 등 무관
            finally:
                pass
        mv.assert_not_called()

    def test_vllm_enabled_path_calls_vllm(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "vllm")
        from agri_ai_core.src.ai import llm_transport, llm_backend_vllm

        fake_result = {"message": {"role": "assistant", "content": "v"}}
        with patch.object(llm_backend_vllm, "vllm_chat", return_value=fake_result) as mv:
            r = llm_transport._ollama_chat(
                model="m", messages=[{"role":"user","content":"hi"}],
                options={"num_predict": 50})
        mv.assert_called_once()
        assert r["message"]["content"] == "v"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
