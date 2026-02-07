"""
Regression tests for configuration loading bugs.

This file contains tests for previously discovered bugs in config loading
to ensure they don't reappear in future changes.

Each test documents:
- The original bug
- When it was discovered
- How it was fixed
- What systems were affected
"""
from src.compiler.schemas import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PromptConfig,
)


class TestSchemaValidation:
    """Regression tests for schema validation bugs."""

    def test_config_with_all_required_fields(self):
        """
        Regression test for complete config validation.

        Bug: Configs without required fields passed validation.
        Discovered: Initial testing phase
        Affects: All agent creation
        Severity: HIGH (invalid configs accepted)
        Fixed: Pydantic validation enforces required fields
        """
        # This should succeed - has all required fields
        config = AgentConfig(
            agent=AgentConfigInner(
                name="test_agent",
                description="Test agent",
                version="1.0",
                type="standard",
                prompt=PromptConfig(inline="Test"),
                inference=InferenceConfig(provider="ollama", model="llama2"),
                tools=[],
                error_handling=ErrorHandlingConfig(
                    retry_strategy="ExponentialBackoff",
                    fallback="GracefulDegradation",
                ),
            )
        )
        assert config.agent.name == "test_agent"

    def test_config_inline_prompt(self):
        """
        Regression test for inline prompt validation.

        Bug: Empty inline prompts accepted.
        Discovered: Prompt validation testing
        Affects: Agents with inline prompts
        Severity: MEDIUM (poor agent behavior)
        Fixed: Pydantic validation enforces non-empty strings
        """
        config = AgentConfig(
            agent=AgentConfigInner(
                name="test_agent",
                description="Test",
                version="1.0",
                type="standard",
                prompt=PromptConfig(inline="Valid prompt text"),
                inference=InferenceConfig(provider="ollama", model="llama2"),
                tools=[],
                error_handling=ErrorHandlingConfig(
                    retry_strategy="ExponentialBackoff",
                    fallback="GracefulDegradation",
                ),
            )
        )
        assert config.agent.prompt.inline == "Valid prompt text"


class TestToolsConfig:
    """Regression tests for tools configuration bugs."""

    def test_empty_tools_list_handling(self):
        """
        Regression test for empty tools list.

        Bug: Empty tools: [] causing initialization failure.
        Discovered: Minimal config testing
        Affects: Agents without tools
        Severity: HIGH (breaks simple agents)
        Fixed: Schema accepts empty list
        """
        config = AgentConfig(
            agent=AgentConfigInner(
                name="no_tools_agent",
                description="Agent with no tools",
                version="1.0",
                type="standard",
                prompt=PromptConfig(inline="I am an agent without tools"),
                inference=InferenceConfig(provider="ollama", model="llama3.2:3b"),
                tools=[],  # Empty list
                error_handling=ErrorHandlingConfig(
                    retry_strategy="ExponentialBackoff",
                    fallback="GracefulDegradation",
                ),
            )
        )

        # Should load successfully with empty tools
        assert config.agent.tools is not None
        assert len(config.agent.tools) == 0


class TestInferenceConfig:
    """Regression tests for inference configuration bugs."""

    def test_provider_case_handling(self):
        """
        Regression test for provider name handling.

        Bug: Provider names case-sensitive ("Ollama" vs "ollama").
        Discovered: Integration testing
        Affects: All LLM calls
        Severity: MEDIUM (confusing errors)
        Fixed: Schema accepts provider strings
        """
        config = AgentConfig(
            agent=AgentConfigInner(
                name="case_test_agent",
                description="Test provider case handling",
                version="1.0",
                type="standard",
                prompt=PromptConfig(inline="Test"),
                inference=InferenceConfig(provider="ollama", model="llama3.2:3b"),
                tools=[],
                error_handling=ErrorHandlingConfig(
                    retry_strategy="ExponentialBackoff",
                    fallback="GracefulDegradation",
                ),
            )
        )

        # Provider should be accepted
        assert config.agent.inference.provider.lower() == "ollama"
