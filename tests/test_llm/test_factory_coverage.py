"""Coverage tests for temper_ai/llm/providers/factory.py.

Covers: _resolve_provider_enum, create_llm_from_config, create_llm_client.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.llm.providers.base import LLMProvider
from temper_ai.llm.providers.factory import (
    _resolve_provider_enum,
    create_llm_client,
    create_llm_from_config,
)
from temper_ai.shared.utils.exceptions import LLMError


class TestResolveProviderEnum:
    def test_valid_providers(self) -> None:
        assert _resolve_provider_enum("ollama") == LLMProvider.OLLAMA
        assert _resolve_provider_enum("openai") == LLMProvider.OPENAI
        assert _resolve_provider_enum("anthropic") == LLMProvider.ANTHROPIC
        assert _resolve_provider_enum("vllm") == LLMProvider.VLLM

    def test_case_insensitive(self) -> None:
        assert _resolve_provider_enum("OLLAMA") == LLMProvider.OLLAMA
        assert _resolve_provider_enum("OpenAI") == LLMProvider.OPENAI

    def test_unknown_provider(self) -> None:
        with pytest.raises(LLMError, match="Unknown LLM provider"):
            _resolve_provider_enum("unknown_provider")


class TestCreateLlmClient:
    def test_ollama(self) -> None:
        llm = create_llm_client("ollama", "llama3", "http://localhost:11434")
        from temper_ai.llm.providers.ollama import OllamaLLM

        assert isinstance(llm, OllamaLLM)
        assert llm.model == "llama3"
        llm.close()

    def test_openai(self) -> None:
        llm = create_llm_client(
            "openai", "gpt-4", "https://api.openai.com", api_key="sk-test"
        )
        from temper_ai.llm.providers.openai_provider import OpenAILLM

        assert isinstance(llm, OpenAILLM)
        llm.close()

    def test_anthropic(self) -> None:
        llm = create_llm_client(
            "anthropic",
            "claude-3-opus",
            "https://api.anthropic.com",
            api_key="sk-ant-test",
        )
        from temper_ai.llm.providers.anthropic_provider import AnthropicLLM

        assert isinstance(llm, AnthropicLLM)
        llm.close()

    def test_vllm(self) -> None:
        llm = create_llm_client("vllm", "llama3", "http://localhost:8000")
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        assert isinstance(llm, VllmLLM)
        llm.close()

    def test_unknown_provider(self) -> None:
        with pytest.raises(LLMError, match="Unknown"):
            create_llm_client("foobar", "model", "http://localhost")


class TestCreateLlmFromConfigUnsupported:
    """Test the unreachable 'unsupported provider' branch in create_llm_from_config."""

    def test_unsupported_provider_branch(self) -> None:
        """If a valid LLMProvider isn't in _PROVIDER_CLASSES, raise LLMError."""
        from temper_ai.llm.providers import factory as factory_mod

        cfg = MagicMock()
        cfg.provider = "ollama"
        cfg.model = "llama3"
        cfg.base_url = "http://localhost:11434"

        original_classes = factory_mod._PROVIDER_CLASSES.copy()
        try:
            # Remove OllamaLLM so the enum resolves but class lookup fails
            factory_mod._PROVIDER_CLASSES = {
                k: v
                for k, v in factory_mod._PROVIDER_CLASSES.items()
                if k != LLMProvider.OLLAMA
            }
            with pytest.raises(LLMError, match="Unsupported"):
                create_llm_from_config(cfg)
        finally:
            factory_mod._PROVIDER_CLASSES = original_classes


class TestCreateLlmClientUnsupported:
    """Test the unreachable 'unknown provider' branch in create_llm_client."""

    def test_unknown_provider_after_resolve(self) -> None:
        from temper_ai.llm.providers import factory as factory_mod

        original_classes = factory_mod._PROVIDER_CLASSES.copy()
        try:
            factory_mod._PROVIDER_CLASSES = {
                k: v
                for k, v in factory_mod._PROVIDER_CLASSES.items()
                if k != LLMProvider.VLLM
            }
            with pytest.raises(LLMError, match="Unknown"):
                create_llm_client("vllm", "model", "http://localhost:8000")
        finally:
            factory_mod._PROVIDER_CLASSES = original_classes


class TestCreateLlmFromConfig:
    def _make_config(self, **overrides: Any) -> MagicMock:
        cfg = MagicMock()
        cfg.provider = overrides.get("provider", "ollama")
        cfg.model = overrides.get("model", "llama3")
        cfg.base_url = overrides.get("base_url", "http://localhost:11434")
        cfg.temperature = overrides.get("temperature", 0.7)
        cfg.max_tokens = overrides.get("max_tokens", 2048)
        cfg.top_p = overrides.get("top_p", 0.9)
        cfg.timeout_seconds = overrides.get("timeout_seconds", 600)
        cfg.max_retries = overrides.get("max_retries", 3)
        cfg.retry_delay_seconds = overrides.get("retry_delay_seconds", 2)
        cfg.api_key_ref = overrides.get("api_key_ref", None)
        cfg.api_key = overrides.get("api_key", None)
        return cfg

    def test_ollama_from_config(self) -> None:
        cfg = self._make_config(provider="ollama")
        llm = create_llm_from_config(cfg)
        assert llm.model == "llama3"
        llm.close()

    def test_openai_with_api_key_ref(self) -> None:
        cfg = self._make_config(
            provider="openai",
            model="gpt-4",
            base_url="https://api.openai.com",
            api_key_ref="OPENAI_API_KEY",
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}):
            llm = create_llm_from_config(cfg)
            assert llm.api_key == "sk-real-key"
            llm.close()

    def test_openai_with_api_key_ref_missing(self) -> None:
        cfg = self._make_config(
            provider="openai",
            model="gpt-4",
            base_url="https://api.openai.com",
            api_key_ref="MISSING_KEY",
        )
        with patch.dict(os.environ, {}, clear=True):
            # Make sure the env var doesn't exist
            os.environ.pop("MISSING_KEY", None)
            with pytest.raises(ValueError, match="not found in environment"):
                create_llm_from_config(cfg)

    def test_openai_with_direct_api_key(self) -> None:
        cfg = self._make_config(
            provider="openai",
            model="gpt-4",
            base_url="https://api.openai.com",
            api_key_ref=None,
            api_key="sk-direct",
        )
        llm = create_llm_from_config(cfg)
        assert llm.api_key == "sk-direct"
        llm.close()

    def test_openai_no_api_key_raises(self) -> None:
        cfg = self._make_config(
            provider="openai",
            model="gpt-4",
            base_url="https://api.openai.com",
            api_key_ref=None,
            api_key=None,
        )
        with pytest.raises(ValueError, match="No API key"):
            create_llm_from_config(cfg)

    def test_anthropic_with_api_key(self) -> None:
        cfg = self._make_config(
            provider="anthropic",
            model="claude-3",
            base_url="https://api.anthropic.com",
            api_key="sk-ant-test",
        )
        llm = create_llm_from_config(cfg)
        assert llm.api_key == "sk-ant-test"
        llm.close()

    def test_default_base_url_used(self) -> None:
        cfg = self._make_config(provider="ollama", base_url=None)
        llm = create_llm_from_config(cfg)
        assert "11434" in llm.base_url
        llm.close()

    def test_unknown_provider_from_config(self) -> None:
        cfg = self._make_config(provider="foobar")
        with pytest.raises(LLMError, match="Unknown"):
            create_llm_from_config(cfg)

    def test_vllm_from_config(self) -> None:
        cfg = self._make_config(
            provider="vllm",
            model="llama3",
            base_url="http://localhost:8000",
        )
        llm = create_llm_from_config(cfg)
        assert llm.model == "llama3"
        llm.close()
