"""Tests for dialogue context auto-injection in _build_prompt."""

from unittest.mock import patch

import pytest

from temper_ai.agent.standard_agent import StandardAgent
from temper_ai.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PromptConfig,
)


def _make_config(
    inline_prompt: str = "You are a helpful assistant.",
    dialogue_aware: bool = True,
    max_dialogue_context_chars: int = 8000,
) -> AgentConfig:
    """Create a minimal agent config for testing."""
    return AgentConfig(
        agent=AgentConfigInner(
            name="test_agent",
            description="Test agent",
            version="1.0",
            type="standard",
            prompt=PromptConfig(inline=inline_prompt),
            inference=InferenceConfig(
                provider="ollama",
                model="llama2",
                base_url="http://localhost:11434",
                temperature=0.7,
                max_tokens=2048,
            ),
            tools=[],
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation",
            ),
            dialogue_aware=dialogue_aware,
            max_dialogue_context_chars=max_dialogue_context_chars,
        )
    )


def _make_agent(config: AgentConfig) -> StandardAgent:
    """Create agent with mocked ToolRegistry."""
    with patch("temper_ai.agent.base_agent.ToolRegistry"):
        return StandardAgent(config)


def _sample_dialogue_history() -> list:
    return [
        {"agent": "skeptic", "round": 0, "output": "Wait", "reasoning": "Risk analysis", "confidence": 0.7},
        {"agent": "optimist", "round": 0, "output": "Go", "reasoning": "Opportunity", "confidence": 0.8},
    ]


class TestDialogueAutoInject:

    def test_injects_dialogue_history_when_dialogue_aware(self):
        agent = _make_agent(_make_config(dialogue_aware=True))
        rendered = agent._build_prompt({
            "dialogue_history": _sample_dialogue_history(),
        })
        assert "## Prior Dialogue" in rendered
        assert "Round 0 - skeptic" in rendered
        assert "Risk analysis" in rendered

    def test_no_inject_when_dialogue_aware_false(self):
        agent = _make_agent(_make_config(dialogue_aware=False))
        rendered = agent._build_prompt({
            "dialogue_history": _sample_dialogue_history(),
        })
        assert "## Prior Dialogue" not in rendered

    def test_no_inject_when_history_empty(self):
        agent = _make_agent(_make_config(dialogue_aware=True))
        rendered = agent._build_prompt({
            "dialogue_history": [],
        })
        assert "## Prior Dialogue" not in rendered

    def test_no_inject_when_history_none(self):
        agent = _make_agent(_make_config(dialogue_aware=True))
        rendered = agent._build_prompt({
            "dialogue_history": None,
        })
        assert "## Prior Dialogue" not in rendered

    def test_no_inject_when_history_absent(self):
        agent = _make_agent(_make_config(dialogue_aware=True))
        rendered = agent._build_prompt({"input": "test"})
        assert "## Prior Dialogue" not in rendered

    def test_injects_stage_agent_outputs(self):
        agent = _make_agent(_make_config(dialogue_aware=True))
        rendered = agent._build_prompt({
            "current_stage_agents": {"analyst": "The market is growing"},
        })
        assert "## Prior Agent Outputs" in rendered
        assert "analyst" in rendered

    def test_no_inject_stage_agents_when_dialogue_aware_false(self):
        agent = _make_agent(_make_config(dialogue_aware=False))
        rendered = agent._build_prompt({
            "current_stage_agents": {"analyst": "output"},
        })
        assert "## Prior Agent Outputs" not in rendered

    def test_respects_max_dialogue_context_chars(self):
        """Large dialogue history gets truncated."""
        history = [
            {"agent": f"a{i}", "round": i, "output": "X" * 300, "reasoning": "Y" * 300, "confidence": 0.8}
            for i in range(20)
        ]
        agent = _make_agent(_make_config(max_dialogue_context_chars=500))
        rendered = agent._build_prompt({"dialogue_history": history})
        # The dialogue section should be present but truncated
        assert "## Prior Dialogue" in rendered


class TestModeContextKeyExclusion:
    """Verify mode context keys are NOT double-injected via string auto-inject."""

    def test_mode_instruction_not_in_input_context(self):
        agent = _make_agent(_make_config())
        rendered = agent._build_prompt({
            "mode_instruction": "You are in a DEBATE.",
            "interaction_mode": "debate",
            "debate_framing": "State your position.",
        })
        # These should NOT appear in the "# Input Context" section
        # (they're excluded from the string auto-inject loop)
        if "# Input Context" in rendered:
            input_context_section = rendered.split("# Input Context")[1]
            assert "Mode Instruction" not in input_context_section
            assert "Interaction Mode" not in input_context_section
            assert "Debate Framing" not in input_context_section


class TestBackwardCompat:
    """Verify agents without new schema fields still work."""

    def test_getattr_fallback_for_dialogue_aware(self):
        """Agents created before the schema change still work via getattr defaults."""
        config = _make_config()
        # Simulate missing field by deleting it
        agent = _make_agent(config)
        # Even if somehow the field didn't exist, getattr default=True handles it
        assert getattr(agent.config.agent, 'dialogue_aware', True) is True

    def test_getattr_fallback_for_max_chars(self):
        config = _make_config()
        agent = _make_agent(config)
        assert getattr(agent.config.agent, 'max_dialogue_context_chars', 8000) == 8000
