"""Tests for the LLM provider factory — create_provider and register_provider."""

import os
from unittest.mock import patch

import pytest

from temper_ai.llm.providers.factory import (
    _DEFAULT_BASE_URLS,
    _PROVIDER_MAP,
    create_provider,
    register_provider,
)
from temper_ai.llm.providers.ollama import OllamaLLM
from temper_ai.llm.providers.openai import OpenAILLM
from temper_ai.llm.providers.vllm import VllmLLM


class TestCreateProviderOpenAI:
    def test_returns_openai_instance(self):
        p = create_provider("openai", model="gpt-4o", api_key="test")
        assert isinstance(p, OpenAILLM)
        p.close()

    def test_model_is_set(self):
        p = create_provider("openai", model="gpt-4o", api_key="test")
        assert p.model == "gpt-4o"
        p.close()

    def test_default_base_url_openai(self):
        p = create_provider("openai", model="gpt-4o")
        assert p.base_url == "https://api.openai.com"
        p.close()

    def test_custom_base_url_overrides_default(self):
        p = create_provider("openai", model="gpt-4o", base_url="http://custom:8080")
        assert p.base_url == "http://custom:8080"
        p.close()

    def test_explicit_api_key(self):
        p = create_provider("openai", model="gpt-4o", api_key="sk-explicit")
        assert p.api_key == "sk-explicit"
        p.close()

    def test_api_key_from_env(self):
        with patch.dict(os.environ, {"MY_KEY": "from-env-123"}):
            p = create_provider("openai", model="gpt-4o", api_key_env="MY_KEY")
            assert p.api_key == "from-env-123"
            p.close()

    def test_explicit_api_key_takes_precedence_over_env(self):
        with patch.dict(os.environ, {"MY_KEY": "from-env"}):
            p = create_provider(
                "openai", model="gpt-4o", api_key="explicit", api_key_env="MY_KEY"
            )
            assert p.api_key == "explicit"
            p.close()

    def test_missing_env_var_logs_warning(self, caplog):
        import logging
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MISSING_KEY", None)
            with caplog.at_level(logging.WARNING, logger="temper_ai.llm.providers.factory"):
                p = create_provider("openai", model="gpt-4o", api_key_env="MISSING_KEY")
                p.close()
        assert "MISSING_KEY" in caplog.text

    def test_extra_kwargs_forwarded(self):
        p = create_provider("openai", model="gpt-4o", temperature=0.1, max_tokens=512)
        assert p.temperature == 0.1
        assert p.max_tokens == 512
        p.close()


class TestCreateProviderVLLM:
    def test_returns_vllm_instance(self):
        p = create_provider("vllm", model="qwen3-next")
        assert isinstance(p, VllmLLM)
        p.close()

    def test_default_base_url_vllm(self):
        p = create_provider("vllm", model="qwen3-next")
        assert p.base_url == "http://localhost:8000"
        p.close()


class TestCreateProviderOllama:
    def test_returns_ollama_instance_direct(self):
        """OllamaLLM constructed directly (factory passes api_key which clashes)."""
        p = OllamaLLM(model="llama3.2")
        assert isinstance(p, OllamaLLM)
        p.close()

    def test_default_base_url_ollama_direct(self):
        p = OllamaLLM(model="llama3.2")
        assert p.base_url == "http://localhost:11434"
        p.close()

    def test_custom_base_url_direct(self):
        p = OllamaLLM(model="llama3.2", base_url="http://gpu-box:11434")
        assert p.base_url == "http://gpu-box:11434"
        p.close()

    def test_factory_ollama_works_without_explicit_api_key(self):
        """Factory omits api_key when None, so Ollama's hardcoded default takes effect."""
        provider = create_provider("ollama", model="llama3.2")
        assert provider.model == "llama3.2"
        assert provider.api_key == "ollama"  # Ollama's hardcoded default


class TestCreateProviderErrors:
    def test_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("nonexistent", model="x")

    def test_error_message_lists_available_providers(self):
        with pytest.raises(ValueError) as exc_info:
            create_provider("bad_provider", model="x")
        assert "openai" in str(exc_info.value)

    def test_empty_string_provider_raises(self):
        with pytest.raises(ValueError):
            create_provider("", model="x")


class TestRegisterProvider:
    def test_register_custom_provider(self):
        class DummyProvider(OpenAILLM):
            PROVIDER_NAME = "dummy"

        register_provider("dummy", DummyProvider, default_base_url="http://dummy:9000")
        p = create_provider("dummy", model="dummy-model")
        assert isinstance(p, DummyProvider)
        assert p.base_url == "http://dummy:9000"
        p.close()
        # cleanup
        _PROVIDER_MAP.pop("dummy", None)
        _DEFAULT_BASE_URLS.pop("dummy", None)

    def test_register_without_default_url_falls_back(self):
        class MinimalProvider(OpenAILLM):
            PROVIDER_NAME = "minimal"

        register_provider("minimal", MinimalProvider)
        # No default URL registered — falls back to "http://localhost:8000"
        p = create_provider("minimal", model="m")
        assert p.base_url == "http://localhost:8000"
        p.close()
        _PROVIDER_MAP.pop("minimal", None)

    def test_registered_provider_overrides_existing(self):
        """Re-registering a name replaces the previous class."""
        class ProviderV1(OpenAILLM):
            PROVIDER_NAME = "versioned"

        class ProviderV2(OpenAILLM):
            PROVIDER_NAME = "versioned"

        register_provider("versioned", ProviderV1, default_base_url="http://v1")
        register_provider("versioned", ProviderV2, default_base_url="http://v2")
        p = create_provider("versioned", model="m")
        assert isinstance(p, ProviderV2)
        p.close()
        _PROVIDER_MAP.pop("versioned", None)
        _DEFAULT_BASE_URLS.pop("versioned", None)


class TestOptionalProviderRegistration:
    """Verify optional providers (anthropic, gemini, claude) are registered at import time.

    The factory uses a lazy-import pattern: _register_optional_providers() wraps each
    provider class import in try/except ImportError. If the provider module itself can
    be imported (even when the underlying SDK isn't installed — the module imports are
    guarded by _ensure_* helpers at call time), the class gets registered in _PROVIDER_MAP.

    These tests assert the registration state that actually exists in the running env.
    """

    def test_anthropic_in_provider_map(self):
        """AnthropicLLM is always registered; the SDK is only required at instantiation."""
        assert "anthropic" in _PROVIDER_MAP

    def test_gemini_in_provider_map(self):
        """GeminiLLM is always registered; the SDK is only required at instantiation."""
        assert "gemini" in _PROVIDER_MAP

    def test_anthropic_default_base_url_registered(self):
        assert _DEFAULT_BASE_URLS.get("anthropic") == "https://api.anthropic.com"

    def test_gemini_default_base_url_registered(self):
        assert _DEFAULT_BASE_URLS.get("gemini") == "https://generativelanguage.googleapis.com"
