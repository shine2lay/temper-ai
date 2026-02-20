"""Integration tests for structured output enforcement in StandardAgent (R0.1)."""
import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from temper_ai.agent.base_agent import AgentResponse
from temper_ai.llm.service import LLMRunResult
from temper_ai.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    OutputSchemaConfig,
    PromptConfig,
)


SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
    },
    "required": ["answer"],
}


@pytest.fixture
def agent_config_with_output_schema():
    """Agent config with output schema validation enabled."""
    return AgentConfig(
        agent=AgentConfigInner(
            name="schema_agent",
            description="Agent with output schema",
            version="1.0",
            type="standard",
            prompt=PromptConfig(inline="Answer the question: {{input}}"),
            inference=InferenceConfig(
                provider="ollama",
                model="llama2",
                base_url="http://localhost:11434",
            ),
            tools=[],
            output_schema=OutputSchemaConfig(
                json_schema=SIMPLE_SCHEMA,
                max_retries=2,
            ),
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation",
            ),
        )
    )


@pytest.fixture
def agent_config_no_schema():
    """Agent config without output schema."""
    return AgentConfig(
        agent=AgentConfigInner(
            name="plain_agent",
            description="Agent without schema",
            version="1.0",
            type="standard",
            prompt=PromptConfig(inline="Answer: {{input}}"),
            inference=InferenceConfig(
                provider="ollama",
                model="llama2",
                base_url="http://localhost:11434",
            ),
            tools=[],
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation",
            ),
        )
    )


class TestStructuredOutputValidation:
    """Tests for validate_and_retry_output helper."""

    def test_valid_output_no_retry(self, agent_config_with_output_schema):
        """Should not retry when output is valid JSON matching schema."""
        from temper_ai.agent._r0_pipeline_helpers import validate_and_retry_output

        llm_service = MagicMock()
        valid_output = json.dumps({"answer": "42"})
        result = LLMRunResult(output=valid_output)

        final = validate_and_retry_output(
            llm_service, agent_config_with_output_schema, result, "test", {"prompt": "test"},
        )
        assert final.output == valid_output

    def test_invalid_output_retries(self, agent_config_with_output_schema):
        """Should retry when output is invalid JSON."""
        from temper_ai.agent._r0_pipeline_helpers import validate_and_retry_output

        good_output = json.dumps({"answer": "42"})
        good_result = LLMRunResult(output=good_output)
        llm_service = MagicMock()
        llm_service.run.return_value = good_result

        bad_result = LLMRunResult(output="not json")
        final = validate_and_retry_output(
            llm_service, agent_config_with_output_schema, bad_result, "test", {"prompt": "test"},
        )
        assert llm_service.run.called
        assert final.output == good_output

    def test_no_schema_skips_validation(self, agent_config_no_schema):
        """Should skip validation when no output schema is configured."""
        from temper_ai.agent._r0_pipeline_helpers import validate_and_retry_output

        llm_service = MagicMock()
        result = LLMRunResult(output="plain text")
        final = validate_and_retry_output(
            llm_service, agent_config_no_schema, result, "test", {"prompt": "test"},
        )
        assert final.output == "plain text"

    def test_max_retries_exhausted(self, agent_config_with_output_schema):
        """Should return last result after max retries are exhausted."""
        from temper_ai.agent._r0_pipeline_helpers import validate_and_retry_output

        bad_result = LLMRunResult(output="still bad")
        llm_service = MagicMock()
        llm_service.run.return_value = bad_result

        final = validate_and_retry_output(
            llm_service, agent_config_with_output_schema,
            LLMRunResult(output="bad"), "test", {"prompt": "test"},
        )
        # After 2 retries, still returns the bad result
        assert final.output == "still bad"


class TestOutputSchemaConfig:
    """Tests for OutputSchemaConfig schema model."""

    def test_defaults(self):
        """Should have sensible defaults."""
        cfg = OutputSchemaConfig()
        assert cfg.json_schema is None
        assert cfg.enforce_mode == "validate_only"
        assert cfg.max_retries == 2
        assert cfg.strict is False

    def test_custom_values(self):
        """Should accept custom values."""
        cfg = OutputSchemaConfig(
            json_schema=SIMPLE_SCHEMA,
            enforce_mode="response_format",
            max_retries=5,
            strict=True,
        )
        assert cfg.json_schema == SIMPLE_SCHEMA
        assert cfg.enforce_mode == "response_format"
        assert cfg.max_retries == 5
        assert cfg.strict is True
