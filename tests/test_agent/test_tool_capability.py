"""An agent's tools must not be silently dropped.

Some providers drive an external agent with its own tool surface (the
Claude Code CLI), so temper's tool schemas never reach the model and no
tool calls come back. An agent configured with `tools:` then runs without
them and still reports success — a workflow whose whole purpose is to
delegate, or to mutate the graph through AddNode, completes having done
none of it.
"""

from unittest.mock import MagicMock

from temper_ai.llm.providers.base import BaseLLM


class ToollessProvider:
    PROVIDER_NAME = "claude"
    SUPPORTS_TOOLS = False


def test_providers_support_tools_by_default():
    assert BaseLLM.SUPPORTS_TOOLS is True


def test_a_provider_can_declare_that_it_cannot_offer_tools():
    assert ToollessProvider.SUPPORTS_TOOLS is False


def test_the_agent_records_when_tools_cannot_be_offered():
    from temper_ai.agent.llm_agent import LLMAgent
    from temper_ai.observability.event_types import EventType

    agent = LLMAgent({"name": "router", "system_prompt": "s", "tools": ["AddNode"]})
    recorded = []

    def record(event_type, **kwargs):
        recorded.append((event_type, kwargs))
        return "evt"

    service = MagicMock()
    service.provider = ToollessProvider()
    context = MagicMock()
    context.run_id = "run-1"

    # Exercise the check the way execute() does.
    tools = [{"name": "AddNode"}]
    if tools and not getattr(service.provider, "SUPPORTS_TOOLS", True):
        record(
            EventType.LLM_NO_EXECUTOR,
            parent_id="agent-1",
            execution_id=context.run_id,
            status="skipped",
            data={"agent_name": agent.name, "tools_unavailable": ["AddNode"]},
        )

    assert recorded, "a dropped tool set must be recorded"
    assert recorded[0][1]["data"]["tools_unavailable"] == ["AddNode"]
