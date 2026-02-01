"""
Tests for OllamaClient wrapper.

Tests the simplified Ollama API wrapper used by M5 self-improvement system
for model selection experiments.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.self_improvement.ollama_client import OllamaClient
from src.agents.llm_providers import LLMResponse, LLMProvider
from src.utils.exceptions import LLMError, LLMTimeoutError


class TestOllamaClientInit:
    """Test OllamaClient initialization."""

    def test_init_with_defaults(self):
        """Should initialize with default parameters."""
        client = OllamaClient(model="llama3.1:8b")

        assert client.model == "llama3.1:8b"
        assert client._llm is not None
        assert client._llm.model == "llama3.1:8b"
        assert client._llm.base_url == "http://localhost:11434"
        assert client._llm.temperature == 0.7
        assert client._llm.max_tokens == 2048

    def test_init_with_custom_parameters(self):
        """Should initialize with custom parameters."""
        client = OllamaClient(
            model="qwen2.5:32b",
            base_url="http://remote-server:11434",
            temperature=0.3,
            max_tokens=512,
            top_p=0.95,
            timeout=30,
        )

        assert client.model == "qwen2.5:32b"
        assert client._llm.base_url == "http://remote-server:11434"
        assert client._llm.temperature == 0.3
        assert client._llm.max_tokens == 512
        assert client._llm.top_p == 0.95
        assert client._llm.timeout == 30

    def test_repr(self):
        """Should have meaningful string representation."""
        client = OllamaClient(model="mistral:7b")
        assert repr(client) == "OllamaClient(model='mistral:7b')"


class TestOllamaClientGenerate:
    """Test OllamaClient.generate() method."""

    @patch("src.self_improvement.ollama_client.OllamaLLM.complete")
    def test_generate_basic(self, mock_complete):
        """Should generate text from prompt."""
        # Setup mock
        mock_response = LLMResponse(
            content="Paris is the capital of France.",
            model="llama3.1:8b",
            provider=LLMProvider.OLLAMA,
            prompt_tokens=10,
            completion_tokens=8,
            total_tokens=18,
            latency_ms=150,
        )
        mock_complete.return_value = mock_response

        # Test
        client = OllamaClient(model="llama3.1:8b")
        result = client.generate("What is the capital of France?")

        # Verify
        assert result == "Paris is the capital of France."
        assert isinstance(result, str)
        mock_complete.assert_called_once()

    @patch("src.self_improvement.ollama_client.OllamaLLM.complete")
    def test_generate_with_temperature_override(self, mock_complete):
        """Should allow temperature override."""
        mock_response = LLMResponse(
            content="Generated response",
            model="llama3.1:8b",
            provider=LLMProvider.OLLAMA,
        )
        mock_complete.return_value = mock_response

        client = OllamaClient(model="llama3.1:8b", temperature=0.7)
        client.generate("Test prompt", temperature=0.3)

        # Verify temperature override was passed
        call_kwargs = mock_complete.call_args[1]
        assert call_kwargs["temperature"] == 0.3

    @patch("src.self_improvement.ollama_client.OllamaLLM.complete")
    def test_generate_with_max_tokens_override(self, mock_complete):
        """Should allow max_tokens override."""
        mock_response = LLMResponse(
            content="Short response",
            model="llama3.1:8b",
            provider=LLMProvider.OLLAMA,
        )
        mock_complete.return_value = mock_response

        client = OllamaClient(model="llama3.1:8b", max_tokens=2048)
        client.generate("Test prompt", max_tokens=256)

        # Verify max_tokens override was passed
        call_kwargs = mock_complete.call_args[1]
        assert call_kwargs["max_tokens"] == 256

    @patch("src.self_improvement.ollama_client.OllamaLLM.complete")
    def test_generate_with_both_overrides(self, mock_complete):
        """Should allow both temperature and max_tokens override."""
        mock_response = LLMResponse(
            content="Response",
            model="llama3.1:8b",
            provider=LLMProvider.OLLAMA,
        )
        mock_complete.return_value = mock_response

        client = OllamaClient(model="llama3.1:8b")
        client.generate("Test", temperature=0.5, max_tokens=128)

        # Verify both overrides were passed
        call_kwargs = mock_complete.call_args[1]
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 128

    @patch("src.self_improvement.ollama_client.OllamaLLM.complete")
    def test_generate_empty_response(self, mock_complete):
        """Should handle empty response from model."""
        mock_response = LLMResponse(
            content="",
            model="llama3.1:8b",
            provider=LLMProvider.OLLAMA,
        )
        mock_complete.return_value = mock_response

        client = OllamaClient(model="llama3.1:8b")
        result = client.generate("Test prompt")

        assert result == ""
        assert isinstance(result, str)

    @patch("src.self_improvement.ollama_client.OllamaLLM.complete")
    def test_generate_long_response(self, mock_complete):
        """Should handle long multi-paragraph response."""
        long_text = "Paragraph 1.\n\nParagraph 2.\n\nParagraph 3." * 100
        mock_response = LLMResponse(
            content=long_text,
            model="qwen2.5:32b",
            provider=LLMProvider.OLLAMA,
        )
        mock_complete.return_value = mock_response

        client = OllamaClient(model="qwen2.5:32b")
        result = client.generate("Long prompt")

        assert result == long_text
        assert len(result) > 1000


class TestOllamaClientErrorHandling:
    """Test OllamaClient error handling."""

    @patch("src.self_improvement.ollama_client.OllamaLLM.complete")
    def test_generate_llm_error(self, mock_complete):
        """Should propagate LLMError from underlying provider."""
        mock_complete.side_effect = LLMError("Model not found")

        client = OllamaClient(model="invalid-model")

        with pytest.raises(LLMError) as exc_info:
            client.generate("Test prompt")

        assert "Model not found" in str(exc_info.value)

    @patch("src.self_improvement.ollama_client.OllamaLLM.complete")
    def test_generate_timeout_error(self, mock_complete):
        """Should propagate LLMTimeoutError from underlying provider."""
        mock_complete.side_effect = LLMTimeoutError("Request timed out")

        client = OllamaClient(model="llama3.1:8b")

        with pytest.raises(LLMTimeoutError) as exc_info:
            client.generate("Test prompt")

        assert "timed out" in str(exc_info.value).lower()


class TestOllamaClientM5Integration:
    """Test OllamaClient usage in M5 experimentation scenarios."""

    @patch("src.self_improvement.ollama_client.OllamaLLM.complete")
    def test_multiple_clients_different_models(self, mock_complete):
        """Should support multiple clients with different models."""
        # Setup mocks for different models
        def mock_complete_side_effect(prompt, **kwargs):
            model = mock_complete._client_model
            return LLMResponse(
                content=f"Response from {model}",
                model=model,
                provider=LLMProvider.OLLAMA,
            )

        mock_complete.side_effect = mock_complete_side_effect

        # Create experiment config with multiple models
        models = {
            "phi3:mini": OllamaClient("phi3:mini"),
            "llama3.1:8b": OllamaClient("llama3.1:8b"),
            "mistral:7b": OllamaClient("mistral:7b"),
            "qwen2.5:32b": OllamaClient("qwen2.5:32b"),
        }

        # Verify each client has correct model
        assert models["phi3:mini"].model == "phi3:mini"
        assert models["llama3.1:8b"].model == "llama3.1:8b"
        assert models["mistral:7b"].model == "mistral:7b"
        assert models["qwen2.5:32b"].model == "qwen2.5:32b"

        # Verify clients are independent
        for name, client in models.items():
            mock_complete._client_model = name
            result = client.generate("Test")
            assert name in result

    @patch("src.self_improvement.ollama_client.OllamaLLM.complete")
    def test_model_selection_experiment_workflow(self, mock_complete):
        """Should support M5 model selection experiment workflow."""
        # Simulate quality scores for different models
        model_quality = {
            "phi3:mini": 0.65,
            "llama3.1:8b": 0.72,
            "mistral:7b": 0.78,
            "qwen2.5:32b": 0.91,
        }

        def mock_generate(prompt, **kwargs):
            model = mock_complete._current_model
            quality = model_quality[model]
            # Simulate varying quality in response
            return LLMResponse(
                content=f"Quality score: {quality}",
                model=model,
                provider=LLMProvider.OLLAMA,
            )

        mock_complete.side_effect = mock_generate

        # Create clients for experiment
        clients = {
            model_name: OllamaClient(model_name)
            for model_name in model_quality.keys()
        }

        # Run simulated experiment
        results = {}
        for model_name, client in clients.items():
            mock_complete._current_model = model_name
            response = client.generate("Extract product info from: iPhone 15")
            results[model_name] = response

        # Verify experiment ran for all models
        assert len(results) == 4
        assert all(isinstance(r, str) for r in results.values())

    @patch("src.self_improvement.ollama_client.OllamaLLM.complete")
    def test_temperature_experimentation(self, mock_complete):
        """Should support temperature parameter experiments."""
        temperatures = [0.1, 0.3, 0.5, 0.7, 0.9]

        mock_response = LLMResponse(
            content="Test response",
            model="llama3.1:8b",
            provider=LLMProvider.OLLAMA,
        )
        mock_complete.return_value = mock_response

        client = OllamaClient(model="llama3.1:8b")

        # Test different temperatures
        for temp in temperatures:
            client.generate("Test", temperature=temp)

        # Verify all temperatures were tested
        assert mock_complete.call_count == len(temperatures)

        # Verify last call used last temperature
        last_call_kwargs = mock_complete.call_args[1]
        assert last_call_kwargs["temperature"] == 0.9


class TestOllamaClientEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_model_name_with_version_tag(self):
        """Should handle model names with version tags."""
        client = OllamaClient(model="llama3.1:8b")
        assert client.model == "llama3.1:8b"

    def test_model_name_without_version_tag(self):
        """Should handle model names without version tags."""
        client = OllamaClient(model="mistral")
        assert client.model == "mistral"

    @patch("src.self_improvement.ollama_client.OllamaLLM.complete")
    def test_unicode_prompt(self, mock_complete):
        """Should handle unicode characters in prompt."""
        mock_response = LLMResponse(
            content="🎉 Success!",
            model="llama3.1:8b",
            provider=LLMProvider.OLLAMA,
        )
        mock_complete.return_value = mock_response

        client = OllamaClient(model="llama3.1:8b")
        result = client.generate("你好 (Hello in Chinese)")

        assert "🎉" in result

    @patch("src.self_improvement.ollama_client.OllamaLLM.complete")
    def test_special_characters_in_response(self, mock_complete):
        """Should handle special characters in response."""
        mock_response = LLMResponse(
            content="Special chars: <>\"'&@#$%^*()[]{}",
            model="llama3.1:8b",
            provider=LLMProvider.OLLAMA,
        )
        mock_complete.return_value = mock_response

        client = OllamaClient(model="llama3.1:8b")
        result = client.generate("Test")

        assert "<>" in result
        assert "\"'" in result
        assert "@#$" in result
