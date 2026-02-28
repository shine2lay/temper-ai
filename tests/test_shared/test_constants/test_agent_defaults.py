"""Tests for temper_ai/shared/constants/agent_defaults.py."""

from temper_ai.shared.constants.agent_defaults import (
    DEFAULT_MAX_DIALOGUE_CONTEXT_CHARS,
    MAX_EXECUTION_TIME_SECONDS,
    MAX_PROMPT_LENGTH,
    MAX_TOOL_CALLS_PER_EXECUTION,
    PRE_COMMAND_DEFAULT_TIMEOUT,
    PRE_COMMAND_MAX_TIMEOUT,
)


class TestAgentExecutionDefaults:
    def test_max_tool_calls_positive(self):
        assert MAX_TOOL_CALLS_PER_EXECUTION > 0

    def test_max_execution_time_positive(self):
        assert MAX_EXECUTION_TIME_SECONDS > 0

    def test_max_prompt_length_positive(self):
        assert MAX_PROMPT_LENGTH > 0

    def test_dialogue_context_chars_positive(self):
        assert DEFAULT_MAX_DIALOGUE_CONTEXT_CHARS > 0


class TestPreCommandDefaults:
    def test_default_timeout_positive(self):
        assert PRE_COMMAND_DEFAULT_TIMEOUT > 0

    def test_max_timeout_exceeds_default(self):
        assert PRE_COMMAND_MAX_TIMEOUT >= PRE_COMMAND_DEFAULT_TIMEOUT
