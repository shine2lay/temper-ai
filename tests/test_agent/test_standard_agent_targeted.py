"""Targeted tests for agent/standard_agent.py to improve coverage from 58% to 90%+.

Covers missing: _build_messages_from_history, _inject_dialogue_context,
_inject_persistent_context, _inject_optimization_context, _on_after_run,
_maybe_publish_persistent_output, _maybe_extract_procedural, _maybe_store_shared,
_on_error, get_capabilities.
"""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.agent.base_agent import AgentResponse
from temper_ai.agent.standard_agent import (
    StandardAgent,
    _build_messages_from_history,
    _extract_memory_query,
)
from temper_ai.shared.utils.exceptions import (
    LLMError,
    MaxIterationsError,
    ToolExecutionError,
)

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestBuildMessagesFromHistory:
    def test_none_history_returns_none(self):
        result = _build_messages_from_history({}, "prompt text")
        assert result is None

    def test_empty_history_returns_none(self):
        history = MagicMock()
        history.__len__ = MagicMock(return_value=0)
        result = _build_messages_from_history(
            {"_conversation_history": history}, "prompt"
        )
        assert result is None

    def test_no_history_key_returns_none(self):
        result = _build_messages_from_history({"other_key": "val"}, "prompt")
        assert result is None

    def test_with_history_returns_messages(self):
        history = MagicMock()
        history.__len__ = MagicMock(return_value=2)
        history.to_message_list.return_value = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = _build_messages_from_history(
            {"_conversation_history": history}, "new prompt"
        )
        assert result is not None
        assert len(result) == 3  # 2 history + 1 current
        assert result[-1] == {"role": "user", "content": "new prompt"}


class TestExtractMemoryQuery:
    def test_extracts_string_values(self):
        result = _extract_memory_query({"topic": "AI", "depth": "deep"})
        assert "AI" in result
        assert "deep" in result

    def test_ignores_non_string_values(self):
        result = _extract_memory_query({"num": 42, "topic": "hello", "flag": True})
        assert "hello" in result
        # 42 and True are not str, should be ignored
        assert "42" not in result

    def test_truncates_to_limit(self):
        long_val = "x" * 5000
        result = _extract_memory_query({"key": long_val})
        from temper_ai.memory.constants import MEMORY_QUERY_MAX_CHARS

        assert len(result) <= MEMORY_QUERY_MAX_CHARS


# ---------------------------------------------------------------------------
# StandardAgent tests
# ---------------------------------------------------------------------------


@pytest.fixture
def make_agent(minimal_agent_config):
    """Create a StandardAgent with mocked LLM and tool registry."""
    with patch("temper_ai.agent.base_agent.ToolRegistry") as mock_reg_cls:
        mock_reg = MagicMock()
        mock_reg.get_all_tools.return_value = {}
        mock_reg.list_tools.return_value = []
        mock_reg_cls.return_value = mock_reg
        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            agent = StandardAgent(minimal_agent_config)
            agent.llm = MagicMock()
            agent.llm_service = MagicMock()
            agent.tool_registry = mock_reg
            return agent


class TestGetCapabilities:
    def test_returns_expected_keys(self, make_agent):
        caps = make_agent.get_capabilities()
        assert caps["name"] == "test_agent"
        assert caps["type"] == "standard"
        assert "llm_provider" in caps
        assert "llm_model" in caps
        assert "tools" in caps
        assert caps["supports_streaming"] is True
        assert caps["supports_multimodal"] is False


class TestOnError:
    def test_max_iterations_error_returns_response(self, make_agent):
        error = MaxIterationsError(
            iterations=5,
            last_output="partial output",
            last_reasoning=None,
            tool_calls=[],
            tokens=100,
            cost=0.01,
        )
        result = make_agent._on_error(error, 0.0)
        assert result is not None
        assert isinstance(result, AgentResponse)

    def test_llm_error_returns_error_response(self, make_agent):
        error = LLMError(message="LLM failed")
        result = make_agent._on_error(error, 0.0)
        assert result is not None
        assert isinstance(result, AgentResponse)

    def test_tool_execution_error_returns_error_response(self, make_agent):
        error = ToolExecutionError(message="tool failed", tool_name="bash")
        result = make_agent._on_error(error, 0.0)
        assert result is not None

    def test_runtime_error_returns_error_response(self, make_agent):
        error = RuntimeError("something went wrong")
        result = make_agent._on_error(error, 0.0)
        assert result is not None

    def test_value_error_returns_error_response(self, make_agent):
        error = ValueError("bad value")
        result = make_agent._on_error(error, 0.0)
        assert result is not None

    def test_timeout_error_returns_error_response(self, make_agent):
        error = TimeoutError("timed out")
        result = make_agent._on_error(error, 0.0)
        assert result is not None

    def test_unknown_error_returns_none(self, make_agent):
        error = KeyError("unknown")
        result = make_agent._on_error(error, 0.0)
        assert result is None


class TestInjectDialogueContext:
    def test_returns_template_when_no_dialogue_config(self, make_agent):
        make_agent.config.agent.__dict__["dialogue_aware"] = False
        result = make_agent._inject_dialogue_context("template", {})
        assert result == "template"

    def test_appends_dialogue_history(self, make_agent):
        make_agent.config.agent.__dict__["dialogue_aware"] = True
        input_data = {
            "dialogue_history": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ]
        }
        with patch(
            "temper_ai.llm.prompts.dialogue_formatter.format_dialogue_history",
            return_value="## Dialogue History\nhello\nhi",
        ):
            with patch(
                "temper_ai.llm.prompts.dialogue_formatter.format_stage_agent_outputs",
                return_value="",
            ):
                result = make_agent._inject_dialogue_context(
                    "base template", input_data
                )
        assert "Dialogue History" in result

    def test_appends_stage_agent_outputs(self, make_agent):
        make_agent.config.agent.__dict__["dialogue_aware"] = True
        input_data = {"current_stage_agents": {"agent1": "output text"}}
        with patch(
            "temper_ai.llm.prompts.dialogue_formatter.format_dialogue_history",
            return_value="",
        ):
            with patch(
                "temper_ai.llm.prompts.dialogue_formatter.format_stage_agent_outputs",
                return_value="## Agent Outputs\nagent1: output text",
            ):
                result = make_agent._inject_dialogue_context(
                    "base template", input_data
                )
        assert "Agent Outputs" in result

    def test_empty_dialogue_history_not_appended(self, make_agent):
        make_agent.config.agent.__dict__["dialogue_aware"] = True
        input_data = {"dialogue_history": []}
        result = make_agent._inject_dialogue_context("base template", input_data)
        # Empty list — no injection
        assert result == "base template"


class TestInjectOptimizationContext:
    def test_no_opt_config_returns_template(self, make_agent):
        make_agent.config.agent.__dict__["prompt_optimization"] = None
        result = make_agent._inject_optimization_context("template")
        assert result == "template"

    def test_opt_disabled_returns_template(self, make_agent):
        opt_cfg = MagicMock()
        opt_cfg.enabled = False
        make_agent.config.agent.__dict__["prompt_optimization"] = opt_cfg
        result = make_agent._inject_optimization_context("template")
        assert result == "template"

    def test_import_error_returns_template(self, make_agent):
        opt_cfg = MagicMock()
        opt_cfg.enabled = True
        opt_cfg.program_store_dir = "/tmp/store"
        opt_cfg.max_demos = 3
        make_agent.config.agent.__dict__["prompt_optimization"] = opt_cfg
        with patch.dict(
            "sys.modules", {"temper_ai.optimization.dspy.program_store": None}
        ):
            result = make_agent._inject_optimization_context("template")
        # Should return template unchanged on ImportError
        assert result == "template"

    def test_runtime_error_returns_template(self, make_agent):
        opt_cfg = MagicMock()
        opt_cfg.enabled = True
        opt_cfg.program_store_dir = "/tmp/store"
        opt_cfg.max_demos = 3
        make_agent.config.agent.__dict__["prompt_optimization"] = opt_cfg

        mock_store = MagicMock()
        mock_adapter = MagicMock()
        mock_adapter.augment_prompt.side_effect = RuntimeError("dspy error")
        mock_adapter_cls = MagicMock(return_value=mock_adapter)
        mock_store_cls = MagicMock(return_value=mock_store)

        with patch.dict(
            "sys.modules",
            {
                "temper_ai.optimization.dspy.program_store": MagicMock(
                    CompiledProgramStore=mock_store_cls
                ),
                "temper_ai.optimization.dspy.prompt_adapter": MagicMock(
                    DSPyPromptAdapter=mock_adapter_cls
                ),
            },
        ):
            result = make_agent._inject_optimization_context("template")
        assert result == "template"


class TestInjectPersistentContext:
    def test_not_persistent_returns_prompt(self, make_agent):
        make_agent.config.agent.__dict__["persistent"] = False
        result = make_agent._inject_persistent_context("my prompt", None)
        assert result == "my prompt"

    def test_persistent_injects_execution_mode(self, make_agent):
        make_agent.config.agent.__dict__["persistent"] = True
        make_agent.config.agent.__dict__["agent_id"] = None
        make_agent.config.agent.__dict__["cross_pollination"] = None

        with patch(
            "temper_ai.agent._m9_context_helpers.detect_execution_mode",
            return_value="single",
        ):
            with patch(
                "temper_ai.agent._m9_context_helpers.inject_execution_mode_context",
                return_value="my prompt [mode=single]",
            ):
                result = make_agent._inject_persistent_context("my prompt", None)
        assert "mode" in result or result == "my prompt [mode=single]"

    def test_persistent_with_agent_id_injects_goals(self, make_agent):
        make_agent.config.agent.__dict__["persistent"] = True
        make_agent.config.agent.__dict__["agent_id"] = "agent-123"
        make_agent.config.agent.__dict__["cross_pollination"] = None

        mock_goal_service = MagicMock()
        with patch(
            "temper_ai.agent._m9_context_helpers.detect_execution_mode",
            return_value="multi",
        ):
            with patch(
                "temper_ai.agent._m9_context_helpers.inject_execution_mode_context",
                return_value="prompt",
            ):
                with patch(
                    "temper_ai.goals.agent_goals.AgentGoalService",
                    return_value=mock_goal_service,
                ):
                    with patch(
                        "temper_ai.agent._m9_context_helpers.inject_project_goal_context",
                        return_value="prompt+goals",
                    ):
                        result = make_agent._inject_persistent_context(
                            "my prompt", None
                        )
        assert result is not None


class TestOnAfterRun:
    def test_memory_disabled_returns_result(self, make_agent):
        make_agent.config.agent.memory.enabled = False
        result_in = AgentResponse(
            output="hello",
            reasoning=None,
            tool_calls=[],
            tokens=0,
            estimated_cost_usd=0.0,
            latency_seconds=0.0,
        )
        result = make_agent._on_after_run(result_in)
        assert result is result_in

    def test_memory_enabled_stores_episodic(self, make_agent):
        make_agent.config.agent.memory.enabled = True
        make_agent.config.agent.memory.max_episodes = 10
        make_agent.config.agent.memory.auto_extract_procedural = False
        make_agent.config.agent.memory.shared_namespace = None

        mock_svc = MagicMock()
        make_agent._memory_service = mock_svc

        mock_scope = MagicMock()
        with patch.object(make_agent, "_build_memory_scope", return_value=mock_scope):
            result_in = AgentResponse(
                output="result text",
                reasoning=None,
                tool_calls=[],
                tokens=10,
                estimated_cost_usd=0.01,
                latency_seconds=0.1,
            )
            result = make_agent._on_after_run(result_in)

        mock_svc.store_episodic.assert_called_once()
        assert result is result_in

    def test_memory_storage_exception_handled(self, make_agent):
        make_agent.config.agent.memory.enabled = True

        mock_svc = MagicMock()
        mock_svc.store_episodic.side_effect = RuntimeError("storage failed")
        make_agent._memory_service = mock_svc

        with patch.object(make_agent, "_build_memory_scope", return_value=MagicMock()):
            result_in = AgentResponse(
                output="text",
                reasoning=None,
                tool_calls=[],
                tokens=0,
                estimated_cost_usd=0.0,
                latency_seconds=0.0,
            )
            # Should not raise
            result = make_agent._on_after_run(result_in)

        assert result is result_in

    def test_empty_output_skips_memory_store(self, make_agent):
        make_agent.config.agent.memory.enabled = True

        mock_svc = MagicMock()
        make_agent._memory_service = mock_svc

        with patch.object(make_agent, "_build_memory_scope", return_value=MagicMock()):
            result_in = AgentResponse(
                output="",
                reasoning=None,
                tool_calls=[],
                tokens=0,
                estimated_cost_usd=0.0,
                latency_seconds=0.0,
            )
            make_agent._on_after_run(result_in)

        mock_svc.store_episodic.assert_not_called()


class TestMaybePublishPersistentOutput:
    def test_not_persistent_does_nothing(self, make_agent):
        make_agent.config.agent.__dict__["persistent"] = False
        result = AgentResponse(
            output="text",
            reasoning=None,
            tool_calls=[],
            tokens=0,
            estimated_cost_usd=0.0,
            latency_seconds=0.0,
        )
        # Should not raise
        make_agent._maybe_publish_persistent_output(result)

    def test_no_cross_config_does_nothing(self, make_agent):
        make_agent.config.agent.__dict__["persistent"] = True
        make_agent.config.agent.__dict__["cross_pollination"] = None
        result = AgentResponse(
            output="text",
            reasoning=None,
            tool_calls=[],
            tokens=0,
            estimated_cost_usd=0.0,
            latency_seconds=0.0,
        )
        make_agent._maybe_publish_persistent_output(result)

    def test_cross_pollination_publish_output_false_does_nothing(self, make_agent):
        make_agent.config.agent.__dict__["persistent"] = True
        cross_cfg = MagicMock()
        cross_cfg.publish_output = False
        make_agent.config.agent.__dict__["cross_pollination"] = cross_cfg
        result = AgentResponse(
            output="text",
            reasoning=None,
            tool_calls=[],
            tokens=0,
            estimated_cost_usd=0.0,
            latency_seconds=0.0,
        )
        make_agent._maybe_publish_persistent_output(result)

    def test_publishes_when_configured(self, make_agent):
        make_agent.config.agent.__dict__["persistent"] = True
        cross_cfg = MagicMock()
        cross_cfg.publish_output = True
        make_agent.config.agent.__dict__["cross_pollination"] = cross_cfg

        mock_svc = MagicMock()
        make_agent._memory_service = mock_svc

        result = AgentResponse(
            output="important output",
            reasoning=None,
            tool_calls=[],
            tokens=0,
            estimated_cost_usd=0.0,
            latency_seconds=0.0,
        )

        with patch("temper_ai.memory.cross_pollination.publish_knowledge") as mock_pub:
            make_agent._maybe_publish_persistent_output(result)
            mock_pub.assert_called_once()

    def test_empty_output_does_not_publish(self, make_agent):
        make_agent.config.agent.__dict__["persistent"] = True
        cross_cfg = MagicMock()
        cross_cfg.publish_output = True
        make_agent.config.agent.__dict__["cross_pollination"] = cross_cfg

        result = AgentResponse(
            output="",
            reasoning=None,
            tool_calls=[],
            tokens=0,
            estimated_cost_usd=0.0,
            latency_seconds=0.0,
        )

        with patch("temper_ai.memory.cross_pollination.publish_knowledge") as mock_pub:
            make_agent._maybe_publish_persistent_output(result)
            mock_pub.assert_not_called()


class TestMaybeExtractProcedural:
    def test_auto_extract_disabled_does_nothing(self, make_agent):
        mem_cfg = MagicMock()
        mem_cfg.auto_extract_procedural = False
        mock_svc = MagicMock()
        make_agent._maybe_extract_procedural(mock_svc, MagicMock(), "text", mem_cfg)
        mock_svc.store_procedural.assert_not_called()

    def test_extracts_and_stores_patterns(self, make_agent):
        mem_cfg = MagicMock()
        mem_cfg.auto_extract_procedural = True

        mock_svc = MagicMock()
        mock_scope = MagicMock()

        with patch(
            "temper_ai.memory.extractors.extract_procedural_patterns",
            return_value=["pattern1", "pattern2"],
        ):
            make_agent._maybe_extract_procedural(
                mock_svc, mock_scope, "output text", mem_cfg
            )

        assert mock_svc.store_procedural.call_count == 2

    def test_exception_handled_gracefully(self, make_agent):
        mem_cfg = MagicMock()
        mem_cfg.auto_extract_procedural = True

        mock_svc = MagicMock()
        mock_svc.store_procedural.side_effect = RuntimeError("storage error")
        mock_scope = MagicMock()

        with patch(
            "temper_ai.memory.extractors.extract_procedural_patterns",
            return_value=["pattern1"],
        ):
            # Should not raise
            make_agent._maybe_extract_procedural(
                mock_svc, mock_scope, "output text", mem_cfg
            )


class TestMaybeStoreShared:
    def test_no_shared_namespace_does_nothing(self, make_agent):
        mem_cfg = MagicMock()
        mem_cfg.shared_namespace = None
        mock_svc = MagicMock()
        make_agent._maybe_store_shared(mock_svc, MagicMock(), "text", mem_cfg)
        mock_svc.store_episodic.assert_not_called()

    def test_stores_to_shared_namespace(self, make_agent):
        mem_cfg = MagicMock()
        mem_cfg.shared_namespace = "shared_ns"

        mock_svc = MagicMock()
        mock_scope = MagicMock()
        mock_shared_scope = MagicMock()
        mock_svc.build_shared_scope.return_value = mock_shared_scope

        make_agent._maybe_store_shared(mock_svc, mock_scope, "output text", mem_cfg)

        mock_svc.build_shared_scope.assert_called_once()
        mock_svc.store_episodic.assert_called_once()

    def test_exception_handled_gracefully(self, make_agent):
        mem_cfg = MagicMock()
        mem_cfg.shared_namespace = "shared_ns"

        mock_svc = MagicMock()
        mock_svc.build_shared_scope.side_effect = RuntimeError("shared error")

        # Should not raise
        make_agent._maybe_store_shared(mock_svc, MagicMock(), "text", mem_cfg)
