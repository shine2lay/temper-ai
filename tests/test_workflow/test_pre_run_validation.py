"""Tests for pre-run config reference validation.

Level A: Fast check in ExecutionService._validate_config_references()
Level B: Deep check in WorkflowRuntime.validate_references()
ConfigError: Structured error dataclass and fuzzy matching
"""

from unittest.mock import MagicMock

import pytest

from temper_ai.shared.utils.exceptions import (
    ConfigNotFoundError,
    ConfigValidationError,
)
from temper_ai.workflow.config_errors import (
    ConfigError,
    format_error_report,
    suggest_name,
)
from temper_ai.workflow.execution_service import WorkflowExecutionService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_loader():
    loader = MagicMock()
    loader.load_stage.return_value = {"stage": {"agents": ["researcher", "writer"]}}
    loader.load_agent.return_value = {"agent": {"tools": ["Calculator"], "prompt": {}}}
    loader.list_configs.return_value = []
    return loader


@pytest.fixture
def good_workflow_config():
    return {
        "workflow": {
            "name": "test",
            "stages": [
                {"name": "research", "stage_ref": "research_stage"},
                {"name": "writing", "stage_ref": "writing_stage"},
            ],
        }
    }


# ---------------------------------------------------------------------------
# ConfigError dataclass
# ---------------------------------------------------------------------------


class TestConfigError:
    def test_format_without_index(self):
        err = ConfigError(
            code="agent_not_found",
            message="Agent 'reseracher' not found",
            location="workflow → stage 'research' → agents[0]",
            suggestion="Did you mean 'researcher'?",
            available=["researcher", "analyst"],
        )
        formatted = err.format()
        assert "Agent 'reseracher' not found" in formatted
        assert "Location:" in formatted
        assert "Suggestion:" in formatted
        assert "Available:" in formatted

    def test_format_with_index(self):
        err = ConfigError(
            code="stage_not_found",
            message="Stage 'bad' not found",
            location="workflow → stages[0]",
        )
        formatted = err.format(index=1)
        assert formatted.startswith("  1. ")
        assert "Stage 'bad' not found" in formatted

    def test_format_no_suggestion_or_available(self):
        err = ConfigError(
            code="stage_not_found",
            message="Stage 'x' not found",
            location="workflow → stages[0]",
        )
        formatted = err.format()
        assert "Suggestion:" not in formatted
        assert "Available:" not in formatted

    def test_format_empty_available(self):
        err = ConfigError(
            code="stage_not_found",
            message="Stage 'x' not found",
            location="workflow → stages[0]",
            available=[],
        )
        formatted = err.format()
        assert "Available:" not in formatted


# ---------------------------------------------------------------------------
# suggest_name fuzzy matching
# ---------------------------------------------------------------------------


class TestSuggestName:
    def test_close_match_transposed_letters(self):
        result = suggest_name("reseracher", ["researcher", "analyst"])
        assert result is not None
        assert "researcher" in result
        assert "Did you mean" in result

    def test_close_match_misspelling(self):
        result = suggest_name("Calculater", ["Calculator", "Bash", "Git"])
        assert result is not None
        assert "Calculator" in result

    def test_no_match_returns_none(self):
        result = suggest_name("totally_wrong_xyz", ["researcher", "analyst"])
        assert result is None

    def test_empty_available_returns_none(self):
        result = suggest_name("anything", [])
        assert result is None

    def test_exact_match_returns_suggestion(self):
        result = suggest_name("researcher", ["researcher", "analyst"])
        assert result is not None
        assert "researcher" in result


# ---------------------------------------------------------------------------
# format_error_report
# ---------------------------------------------------------------------------


class TestFormatErrorReport:
    def test_single_error(self):
        errors = [
            ConfigError(
                code="stage_not_found",
                message="Stage 'bad' not found",
                location="workflow → stages[0]",
            )
        ]
        report = format_error_report(errors)
        assert "1 error" in report
        assert "Stage 'bad'" in report
        assert "1." in report

    def test_multiple_errors(self):
        errors = [
            ConfigError(
                code="stage_not_found",
                message="Stage 'bad' not found",
                location="workflow → stages[0]",
            ),
            ConfigError(
                code="agent_not_found",
                message="Agent 'missing' not found",
                location="workflow → stage 'x' → agents[0]",
                suggestion="Did you mean 'writer'?",
                available=["writer", "analyst"],
            ),
        ]
        report = format_error_report(errors)
        assert "2 error" in report
        assert "1." in report
        assert "2." in report
        assert "Stage 'bad'" in report
        assert "Agent 'missing'" in report


# ---------------------------------------------------------------------------
# Level A — ExecutionService._validate_config_references
# ---------------------------------------------------------------------------


class TestLevelAValidation:
    def test_passes_when_all_refs_exist(self, good_workflow_config, mock_loader):
        WorkflowExecutionService._validate_config_references(
            good_workflow_config, mock_loader
        )
        # No exception means pass

    def test_fails_on_missing_stage(self, mock_loader):
        mock_loader.load_stage.side_effect = ConfigNotFoundError(
            "not found", config_path="missing_stage"
        )
        config = {
            "workflow": {"stages": [{"name": "bad", "stage_ref": "missing_stage"}]}
        }
        with pytest.raises(ValueError, match="Stage 'missing_stage' not found"):
            WorkflowExecutionService._validate_config_references(config, mock_loader)

    def test_fails_on_missing_agent(self, mock_loader):
        mock_loader.load_stage.return_value = {
            "stage": {"agents": ["nonexistent_agent"]}
        }
        mock_loader.load_agent.side_effect = ConfigNotFoundError(
            "not found", config_path="nonexistent_agent"
        )
        config = {"workflow": {"stages": [{"name": "s1", "stage_ref": "my_stage"}]}}
        with pytest.raises(ValueError, match="agent 'nonexistent_agent'"):
            WorkflowExecutionService._validate_config_references(config, mock_loader)

    def test_skips_stages_without_stage_ref(self, mock_loader):
        config = {"workflow": {"stages": [{"name": "inline_stage"}]}}  # No stage_ref
        WorkflowExecutionService._validate_config_references(config, mock_loader)
        mock_loader.load_stage.assert_not_called()

    def test_handles_dict_agent_entries(self, mock_loader):
        mock_loader.load_stage.return_value = {
            "stage": {"agents": [{"name": "my_agent"}]}
        }
        WorkflowExecutionService._validate_config_references(
            {"workflow": {"stages": [{"stage_ref": "s1"}]}},
            mock_loader,
        )
        mock_loader.load_agent.assert_called_with("my_agent", validate=False)

    def test_handles_agent_ref_key(self, mock_loader):
        mock_loader.load_stage.return_value = {
            "stage": {"agents": [{"agent_ref": "ref_agent"}]}
        }
        WorkflowExecutionService._validate_config_references(
            {"workflow": {"stages": [{"stage_ref": "s1"}]}},
            mock_loader,
        )
        mock_loader.load_agent.assert_called_with("ref_agent", validate=False)

    def test_empty_stages_list_passes(self, mock_loader):
        config = {"workflow": {"stages": []}}
        WorkflowExecutionService._validate_config_references(config, mock_loader)

    def test_no_stages_key_passes(self, mock_loader):
        config = {"workflow": {}}
        WorkflowExecutionService._validate_config_references(config, mock_loader)

    def test_missing_stage_with_suggestion(self, mock_loader):
        mock_loader.load_stage.side_effect = ConfigNotFoundError(
            "not found", config_path="reseach_stage"
        )
        mock_loader.list_configs.return_value = ["research_stage", "writing_stage"]
        config = {
            "workflow": {"stages": [{"name": "s1", "stage_ref": "reseach_stage"}]}
        }
        with pytest.raises(ValueError, match="Did you mean"):
            WorkflowExecutionService._validate_config_references(config, mock_loader)

    def test_missing_agent_with_suggestion(self, mock_loader):
        mock_loader.load_stage.return_value = {"stage": {"agents": ["reseracher"]}}
        mock_loader.load_agent.side_effect = ConfigNotFoundError(
            "not found", config_path="reseracher"
        )
        mock_loader.list_configs.return_value = ["researcher", "writer"]
        config = {"workflow": {"stages": [{"name": "s1", "stage_ref": "my_stage"}]}}
        with pytest.raises(ValueError, match="Did you mean"):
            WorkflowExecutionService._validate_config_references(config, mock_loader)


# ---------------------------------------------------------------------------
# Level B — WorkflowRuntime.validate_references
# ---------------------------------------------------------------------------


class TestLevelBValidation:
    def _make_runtime(self):
        from temper_ai.workflow.runtime import RuntimeConfig, WorkflowRuntime

        return WorkflowRuntime(config=RuntimeConfig(initialize_database=False))

    def _make_infra(self, loader, tool_registry):
        from temper_ai.workflow.runtime import InfrastructureBundle

        bundle = InfrastructureBundle()
        bundle.config_loader = loader
        bundle.tool_registry = tool_registry
        return bundle

    def test_passes_when_all_refs_exist(self, good_workflow_config, mock_loader):
        rt = self._make_runtime()
        tool_reg = MagicMock()
        tool_reg.has.return_value = True
        tool_reg.list_available.return_value = ["Calculator"]
        infra = self._make_infra(mock_loader, tool_reg)

        rt.validate_references(good_workflow_config, infra)

    def test_collects_all_errors(self):
        rt = self._make_runtime()

        loader = MagicMock()
        # First stage loads, second doesn't
        loader.load_stage.side_effect = [
            {"stage": {"agents": ["missing_agent"]}},
            ConfigNotFoundError("not found", config_path="bad_stage"),
        ]
        loader.load_agent.side_effect = ConfigNotFoundError(
            "not found", config_path="missing_agent"
        )
        loader.list_configs.return_value = []

        tool_reg = MagicMock()
        tool_reg.has.return_value = True
        tool_reg.list_available.return_value = []

        infra = self._make_infra(loader, tool_reg)

        config = {
            "workflow": {
                "stages": [
                    {"name": "s1", "stage_ref": "good_stage"},
                    {"name": "s2", "stage_ref": "bad_stage"},
                ],
            }
        }

        with pytest.raises(ConfigValidationError, match="2 error") as exc_info:
            rt.validate_references(config, infra)

        msg = str(exc_info.value)
        assert "missing_agent" in msg
        assert "bad_stage" in msg

    def test_collects_structured_config_errors(self):
        rt = self._make_runtime()

        loader = MagicMock()
        loader.load_stage.side_effect = ConfigNotFoundError(
            "not found", config_path="bad_stage"
        )
        loader.list_configs.return_value = ["good_stage", "other_stage"]

        tool_reg = MagicMock()
        tool_reg.list_available.return_value = []

        infra = self._make_infra(loader, tool_reg)

        config = {"workflow": {"stages": [{"name": "s1", "stage_ref": "bad_stage"}]}}

        with pytest.raises(ConfigValidationError) as exc_info:
            rt.validate_references(config, infra)

        err = exc_info.value
        assert len(err.config_errors) == 1
        ce = err.config_errors[0]
        assert ce.code == "stage_not_found"
        assert "bad_stage" in ce.message
        assert "stages[0]" in ce.location
        assert ce.available == ["good_stage", "other_stage"]

    def test_checks_tool_existence(self):
        rt = self._make_runtime()

        loader = MagicMock()
        loader.load_stage.return_value = {"stage": {"agents": ["agent1"]}}
        loader.load_agent.return_value = {
            "agent": {"tools": ["Calculator", "FakeTool"], "prompt": {}}
        }
        loader.list_configs.return_value = []

        tool_reg = MagicMock()
        tool_reg.has.side_effect = lambda name: name == "Calculator"
        tool_reg.list_available.return_value = ["Bash", "Calculator", "WebSearch"]

        infra = self._make_infra(loader, tool_reg)

        config = {"workflow": {"stages": [{"name": "s1", "stage_ref": "my_stage"}]}}

        with pytest.raises(ConfigValidationError) as exc_info:
            rt.validate_references(config, infra)

        err = exc_info.value
        assert len(err.config_errors) == 1
        ce = err.config_errors[0]
        assert ce.code == "tool_not_registered"
        assert "FakeTool" in ce.message
        assert "tools[1]" in ce.location
        assert "Bash" in ce.available

    def test_checks_prompt_template(self):
        rt = self._make_runtime()

        loader = MagicMock()
        loader.load_stage.return_value = {"stage": {"agents": ["agent1"]}}
        loader.load_agent.return_value = {
            "agent": {
                "tools": [],
                "prompt": {"template_path": "missing_template.txt"},
            }
        }
        loader.load_prompt_template.side_effect = ConfigNotFoundError(
            "not found", config_path="missing_template.txt"
        )
        loader.list_configs.return_value = []

        tool_reg = MagicMock()
        tool_reg.list_available.return_value = []
        infra = self._make_infra(loader, tool_reg)

        config = {"workflow": {"stages": [{"name": "s1", "stage_ref": "my_stage"}]}}

        with pytest.raises(ConfigValidationError) as exc_info:
            rt.validate_references(config, infra)

        ce = exc_info.value.config_errors[0]
        assert ce.code == "template_not_found"
        assert "missing_template" in ce.message
        assert "prompt.template_path" in ce.location

    def test_handles_dict_tool_entries(self):
        rt = self._make_runtime()

        loader = MagicMock()
        loader.load_stage.return_value = {"stage": {"agents": ["agent1"]}}
        loader.load_agent.return_value = {
            "agent": {
                "tools": [{"name": "MyTool"}],
                "prompt": {},
            }
        }
        loader.list_configs.return_value = []

        tool_reg = MagicMock()
        tool_reg.has.return_value = False
        tool_reg.list_available.return_value = ["Bash", "Calculator"]

        infra = self._make_infra(loader, tool_reg)

        config = {"workflow": {"stages": [{"name": "s1", "stage_ref": "my_stage"}]}}

        with pytest.raises(ConfigValidationError, match="MyTool"):
            rt.validate_references(config, infra)

    def test_empty_workflow_passes(self):
        rt = self._make_runtime()
        loader = MagicMock()
        loader.list_configs.return_value = []
        tool_reg = MagicMock()
        tool_reg.list_available.return_value = []
        infra = self._make_infra(loader, tool_reg)

        rt.validate_references({"workflow": {"stages": []}}, infra)

    def test_fuzzy_suggestion_for_agent(self):
        rt = self._make_runtime()

        loader = MagicMock()
        loader.load_stage.return_value = {"stage": {"agents": ["reseracher"]}}
        loader.load_agent.side_effect = ConfigNotFoundError(
            "not found", config_path="reseracher"
        )
        loader.list_configs.side_effect = lambda t: (
            ["researcher", "analyst", "writer"] if t == "agent" else []
        )

        tool_reg = MagicMock()
        tool_reg.list_available.return_value = []

        infra = self._make_infra(loader, tool_reg)

        config = {
            "workflow": {"stages": [{"name": "research", "stage_ref": "my_stage"}]}
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            rt.validate_references(config, infra)

        ce = exc_info.value.config_errors[0]
        assert ce.suggestion is not None
        assert "researcher" in ce.suggestion
        assert "Did you mean" in ce.suggestion

    def test_fuzzy_suggestion_for_tool(self):
        rt = self._make_runtime()

        loader = MagicMock()
        loader.load_stage.return_value = {"stage": {"agents": ["agent1"]}}
        loader.load_agent.return_value = {
            "agent": {"tools": ["Calculater"], "prompt": {}}
        }
        loader.list_configs.return_value = []

        tool_reg = MagicMock()
        tool_reg.has.return_value = False
        tool_reg.list_available.return_value = ["Bash", "Calculator", "WebSearch"]

        infra = self._make_infra(loader, tool_reg)

        config = {"workflow": {"stages": [{"name": "s1", "stage_ref": "my_stage"}]}}

        with pytest.raises(ConfigValidationError) as exc_info:
            rt.validate_references(config, infra)

        ce = exc_info.value.config_errors[0]
        assert ce.suggestion is not None
        assert "Calculator" in ce.suggestion
