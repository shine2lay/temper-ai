"""Tests for output extraction and two-compartment store format."""
import pytest

from src.workflow.context_schemas import StageOutputDeclaration
from src.workflow.output_extractor import (
    LLMOutputExtractor,
    NoopExtractor,
    get_extractor,
)


class TestNoopExtractor:
    """Tests for NoopExtractor."""

    def test_returns_empty_dict(self):
        extractor = NoopExtractor()
        result = extractor.extract("some output", {}, "test_stage")
        assert result == {}

    def test_returns_empty_with_declarations(self):
        extractor = NoopExtractor()
        decls = {
            "decision": StageOutputDeclaration(type="string"),
        }
        result = extractor.extract("output", decls, "test_stage")
        assert result == {}


class TestLLMOutputExtractor:
    """Tests for LLMOutputExtractor (with mocked LLM)."""

    def test_build_extraction_prompt(self):
        extractor = LLMOutputExtractor()
        decls = {
            "decision": StageOutputDeclaration(
                type="string", description="Approved or rejected"
            ),
            "priority": StageOutputDeclaration(
                type="string", description="High, medium, or low"
            ),
        }
        prompt = extractor._build_extraction_prompt("Raw output text", decls)
        assert "decision" in prompt
        assert "priority" in prompt
        assert "Raw output text" in prompt
        assert "JSON" in prompt

    def test_parse_extraction_response_valid_json(self):
        response = '{"decision": "APPROVE", "priority": "high"}'
        result = LLMOutputExtractor._parse_extraction_response(response)
        assert result["decision"] == "APPROVE"
        assert result["priority"] == "high"

    def test_parse_extraction_response_with_code_block(self):
        response = '```json\n{"decision": "REJECT"}\n```'
        result = LLMOutputExtractor._parse_extraction_response(response)
        assert result["decision"] == "REJECT"

    def test_parse_extraction_response_invalid_json(self):
        with pytest.raises(Exception):
            LLMOutputExtractor._parse_extraction_response("not json")

    def test_extract_empty_output(self):
        extractor = LLMOutputExtractor()
        result = extractor.extract("", {"d": StageOutputDeclaration()}, "s1")
        assert result == {}

    def test_extract_no_declarations(self):
        extractor = LLMOutputExtractor()
        result = extractor.extract("some output", {}, "s1")
        assert result == {}


class TestGetExtractor:
    """Tests for get_extractor() factory."""

    def test_no_config_returns_noop(self):
        extractor = get_extractor(None)
        assert isinstance(extractor, NoopExtractor)

    def test_no_extraction_section_returns_noop(self):
        extractor = get_extractor({"workflow": {}})
        assert isinstance(extractor, NoopExtractor)

    def test_extraction_disabled_returns_noop(self):
        config = {
            "workflow": {
                "context_management": {
                    "extraction": {"enabled": False},
                },
            },
        }
        extractor = get_extractor(config)
        assert isinstance(extractor, NoopExtractor)

    def test_extraction_enabled_returns_llm(self):
        config = {
            "workflow": {
                "context_management": {
                    "extraction": {
                        "enabled": True,
                        "provider": "ollama",
                        "model": "qwen3:8b",
                        "timeout_seconds": 30,
                    },
                },
            },
        }
        extractor = get_extractor(config)
        assert isinstance(extractor, LLMOutputExtractor)


class TestTwoCompartmentFormat:
    """Tests for two-compartment store format in stage outputs."""

    def test_sequential_store_format(self):
        """Verify _store_stage_output produces two-compartment format."""
        from unittest.mock import MagicMock

        from src.stage.executors.sequential import (
            SequentialStageExecutor,
            StageOutputData,
        )

        state = {"stage_outputs": {}, "current_stage": ""}
        data = StageOutputData(
            final_output="test output",
            synthesis_result=None,
            agent_outputs={"agent1": {"output": "data"}},
            agent_statuses={"agent1": "success"},
            agent_metrics={"agent1": {"tokens": 100}},
            agents=["agent1"],
        )
        structured = {"decision": "APPROVE", "priority": "high"}

        SequentialStageExecutor._store_stage_output(
            state, "test_stage", data, structured=structured,
        )

        stage_out = state["stage_outputs"]["test_stage"]

        # Two-compartment format
        assert stage_out["structured"] == structured
        assert "raw" in stage_out
        assert stage_out["raw"]["output"] == "test output"

        # Top-level compat aliases
        assert stage_out["output"] == "test output"
        assert stage_out["stage_status"] == "completed"
        assert stage_out["agent_outputs"] == {"agent1": {"output": "data"}}

    def test_sequential_store_no_structured(self):
        """Without structured, compartment should be empty dict."""
        from src.stage.executors.sequential import (
            SequentialStageExecutor,
            StageOutputData,
        )

        state = {"stage_outputs": {}, "current_stage": ""}
        data = StageOutputData(
            final_output="output",
            synthesis_result=None,
            agent_outputs={},
            agent_statuses={},
            agent_metrics={},
            agents=[],
        )

        SequentialStageExecutor._store_stage_output(state, "s1", data)

        assert state["stage_outputs"]["s1"]["structured"] == {}
        assert state["stage_outputs"]["s1"]["raw"]["output"] == "output"

    def test_parallel_update_state_format(self):
        """Verify update_state_with_results produces two-compartment format."""
        from unittest.mock import MagicMock

        from src.stage.executors._parallel_helpers import (
            update_state_with_results,
        )

        synth = MagicMock()
        synth.decision = "APPROVE"
        synth.method = "consensus"
        synth.confidence = 0.9
        synth.votes = {"APPROVE": 3}
        synth.conflicts = []

        state = {"stage_outputs": {}}
        parallel_result = {
            "agent_statuses": {"a1": "success"},
            "agent_metrics": {"a1": {"tokens": 100}},
        }
        agg = {"total_tokens": 100}
        structured = {"verdict": "pass"}

        update_state_with_results(
            state, "test_stage", synth,
            {"a1": {"output": "data"}},
            parallel_result, agg,
            structured=structured,
        )

        stage_out = state["stage_outputs"]["test_stage"]
        assert stage_out["structured"] == structured
        assert "raw" in stage_out
        assert stage_out["raw"]["decision"] == "APPROVE"
        # Top-level compat
        assert stage_out["decision"] == "APPROVE"
        assert stage_out["stage_status"] == "completed"
