"""Tests for compile-time agent I/O validation.

Covers:
- AgentIODeclaration schema (types, required, defaults)
- AgentFactory.get_interface() static extraction
- BaseAgent.get_interface() instance method
- Agent with no declarations returns empty inputs/outputs
- Compile-time validation: missing required input, type mismatch, stage output coverage
- Backward compat: agents without declarations pass validation unchanged
- _validation_helpers: type compatibility, validate_agent_io_for_stage
"""

from unittest.mock import MagicMock

import pytest

from temper_ai.storage.schemas.agent_config import AgentIODeclaration

# ── AgentIODeclaration Schema ─────────────────────────────────────


class TestAgentIODeclaration:
    """Tests for AgentIODeclaration Pydantic model."""

    def test_defaults(self):
        d = AgentIODeclaration()
        assert d.type == "any"
        assert d.required is True
        assert d.default is None
        assert d.description is None

    def test_all_types_valid(self):
        for t in ("string", "list", "dict", "number", "boolean", "any"):
            d = AgentIODeclaration(type=t)
            assert d.type == t

    def test_invalid_type_raises(self):
        with pytest.raises(Exception):
            AgentIODeclaration(type="invalid_type")

    def test_optional_with_default(self):
        d = AgentIODeclaration(
            type="string", required=False, default="fallback", description="test"
        )
        assert d.required is False
        assert d.default == "fallback"
        assert d.description == "test"

    def test_model_dump(self):
        d = AgentIODeclaration(type="list", required=True, description="Claims")
        dumped = d.model_dump(exclude_none=True)
        assert dumped == {"type": "list", "required": True, "description": "Claims"}
        assert "default" not in dumped

    def test_on_agent_config_inner(self):
        """inputs/outputs fields on AgentConfigInner are optional."""
        from temper_ai.storage.schemas.agent_config import AgentConfigInner

        # Without inputs/outputs
        a = AgentConfigInner(
            name="test",
            description="test",
            type="script",
            script="echo hi",
            error_handling={
                "retry_strategy": "ExponentialBackoff",
                "fallback": "GracefulDegradation",
            },
        )
        assert a.inputs is None
        assert a.outputs is None

    def test_on_agent_config_inner_with_declarations(self):
        from temper_ai.storage.schemas.agent_config import AgentConfigInner

        a = AgentConfigInner(
            name="test",
            description="test",
            type="script",
            script="echo hi",
            error_handling={
                "retry_strategy": "ExponentialBackoff",
                "fallback": "GracefulDegradation",
            },
            inputs={"q": {"type": "string", "required": True}},
            outputs={"answer": {"type": "string"}},
        )
        assert "q" in a.inputs
        assert a.inputs["q"].type == "string"
        assert "answer" in a.outputs


# ── AgentFactory.get_interface() ──────────────────────────────────


class TestAgentFactoryGetInterface:
    """Tests for AgentFactory.get_interface() static extraction."""

    def _make_loader(self, agent_dict):
        loader = MagicMock()
        loader.load_agent.return_value = agent_dict
        return loader

    def test_extracts_interface_with_declarations(self):
        from temper_ai.agent.utils.agent_factory import AgentFactory

        loader = self._make_loader(
            {
                "agent": {
                    "name": "fact_checker",
                    "description": "Verifies claims",
                    "inputs": {
                        "claims": {"type": "list", "required": True},
                        "sources": {"type": "list", "required": False},
                    },
                    "outputs": {
                        "verified": {"type": "list", "description": "Results"},
                    },
                },
            }
        )
        interface = AgentFactory.get_interface("fact_checker", loader)
        assert interface["name"] == "fact_checker"
        assert interface["description"] == "Verifies claims"
        assert "claims" in interface["inputs"]
        assert interface["inputs"]["claims"].required is True
        assert "sources" in interface["inputs"]
        assert interface["inputs"]["sources"].required is False
        assert "verified" in interface["outputs"]

    def test_extracts_interface_without_declarations(self):
        from temper_ai.agent.utils.agent_factory import AgentFactory

        loader = self._make_loader(
            {
                "agent": {
                    "name": "old_agent",
                    "description": "No declarations",
                },
            }
        )
        interface = AgentFactory.get_interface("old_agent", loader)
        assert interface["name"] == "old_agent"
        assert interface["inputs"] == {}
        assert interface["outputs"] == {}

    def test_no_instantiation_needed(self):
        """get_interface does not call AgentFactory.create()."""
        from temper_ai.agent.utils.agent_factory import AgentFactory

        loader = self._make_loader(
            {
                "agent": {
                    "name": "test",
                    "description": "test",
                    "inputs": {"x": {"type": "string"}},
                },
            }
        )
        # This should NOT need LLM, tools, etc.
        interface = AgentFactory.get_interface("test", loader)
        assert "x" in interface["inputs"]


# ── BaseAgent.get_interface() ─────────────────────────────────────


class TestBaseAgentGetInterface:
    """Tests for BaseAgent.get_interface() instance method."""

    def _make_agent_config(self, inputs=None, outputs=None):
        from temper_ai.storage.schemas.agent_config import AgentConfig

        config_dict = {
            "agent": {
                "name": "test_agent",
                "description": "Test agent",
                "type": "script",
                "script": "echo test",
                "error_handling": {
                    "retry_strategy": "ExponentialBackoff",
                    "fallback": "GracefulDegradation",
                },
            },
        }
        if inputs:
            config_dict["agent"]["inputs"] = inputs
        if outputs:
            config_dict["agent"]["outputs"] = outputs
        return AgentConfig(**config_dict)

    def test_with_declarations(self):
        from temper_ai.agent.script_agent import ScriptAgent

        config = self._make_agent_config(
            inputs={
                "text": {
                    "type": "string",
                    "required": True,
                    "description": "Input text",
                }
            },
            outputs={"result": {"type": "dict", "description": "Output"}},
        )
        agent = ScriptAgent(config)
        interface = agent.get_interface()
        assert interface["name"] == "test_agent"
        assert interface["description"] == "Test agent"
        assert "text" in interface["inputs"]
        assert interface["inputs"]["text"]["type"] == "string"
        assert "result" in interface["outputs"]

    def test_without_declarations(self):
        from temper_ai.agent.script_agent import ScriptAgent

        config = self._make_agent_config()
        agent = ScriptAgent(config)
        interface = agent.get_interface()
        assert interface["inputs"] == {}
        assert interface["outputs"] == {}

    def test_excludes_none_values(self):
        from temper_ai.agent.script_agent import ScriptAgent

        config = self._make_agent_config(
            inputs={"x": {"type": "string"}},
        )
        agent = ScriptAgent(config)
        interface = agent.get_interface()
        # default=None and description=None should be excluded
        assert "default" not in interface["inputs"]["x"]
        assert "description" not in interface["inputs"]["x"]


# ── Type Compatibility ────────────────────────────────────────────


class TestTypeCompatibility:
    """Tests for _validation_helpers type checking."""

    def test_same_type_compatible(self):
        from temper_ai.workflow.engines._validation_helpers import (
            check_type_compatibility,
        )

        for t in ("string", "list", "dict", "number", "boolean", "any"):
            assert check_type_compatibility(t, t) is True

    def test_any_accepts_all(self):
        from temper_ai.workflow.engines._validation_helpers import (
            check_type_compatibility,
        )

        for t in ("string", "list", "dict", "number", "boolean"):
            assert check_type_compatibility(t, "any") is True

    def test_any_source_accepted_by_all(self):
        from temper_ai.workflow.engines._validation_helpers import (
            check_type_compatibility,
        )

        for t in ("string", "list", "dict", "number", "boolean"):
            assert check_type_compatibility("any", t) is True

    def test_incompatible_types(self):
        from temper_ai.workflow.engines._validation_helpers import (
            check_type_compatibility,
        )

        assert check_type_compatibility("string", "number") is False
        assert check_type_compatibility("list", "dict") is False
        assert check_type_compatibility("boolean", "string") is False
        assert check_type_compatibility("number", "list") is False


# ── validate_agent_io_types ───────────────────────────────────────


class TestValidateAgentIOTypes:
    """Tests for validate_agent_io_types()."""

    def test_type_mismatch_reported(self):
        from temper_ai.workflow.engines._validation_helpers import (
            validate_agent_io_types,
        )

        producer_outputs = {
            "score": AgentIODeclaration(type="string"),
        }
        consumer_inputs = {
            "score": AgentIODeclaration(type="number", required=True),
        }
        errors = []
        validate_agent_io_types(
            "producer",
            producer_outputs,
            "consumer",
            consumer_inputs,
            errors,
            "my_stage",
        )
        assert len(errors) == 1
        assert "type mismatch" in errors[0]
        assert "producer" in errors[0]
        assert "consumer" in errors[0]

    def test_compatible_types_no_error(self):
        from temper_ai.workflow.engines._validation_helpers import (
            validate_agent_io_types,
        )

        producer_outputs = {
            "data": AgentIODeclaration(type="list"),
        }
        consumer_inputs = {
            "data": AgentIODeclaration(type="list", required=True),
        }
        errors = []
        validate_agent_io_types(
            "producer",
            producer_outputs,
            "consumer",
            consumer_inputs,
            errors,
            "my_stage",
        )
        assert errors == []

    def test_non_overlapping_fields_ignored(self):
        from temper_ai.workflow.engines._validation_helpers import (
            validate_agent_io_types,
        )

        producer_outputs = {"x": AgentIODeclaration(type="string")}
        consumer_inputs = {"y": AgentIODeclaration(type="number", required=True)}
        errors = []
        validate_agent_io_types(
            "p", producer_outputs, "c", consumer_inputs, errors, "s"
        )
        assert errors == []


# ── validate_agent_io_for_stage ───────────────────────────────────


class TestValidateAgentIOForStage:
    """Tests for full stage-level agent I/O validation."""

    def test_missing_required_input(self):
        from temper_ai.workflow.engines._validation_helpers import (
            validate_agent_io_for_stage,
        )

        agent_interfaces = {
            "checker": {
                "inputs": {
                    "claims": AgentIODeclaration(type="list", required=True),
                },
                "outputs": {},
            },
        }
        errors = []
        validate_agent_io_for_stage(
            agent_interfaces,
            stage_name="review",
            stage_inputs_raw={},  # No stage inputs
            stage_outputs_raw={},
            errors=errors,
        )
        assert len(errors) == 1
        assert "required input 'claims'" in errors[0]
        assert "checker" in errors[0]

    def test_required_input_satisfied_by_stage(self):
        from temper_ai.workflow.engines._validation_helpers import (
            validate_agent_io_for_stage,
        )

        agent_interfaces = {
            "checker": {
                "inputs": {
                    "claims": AgentIODeclaration(type="list", required=True),
                },
                "outputs": {},
            },
        }
        errors = []
        validate_agent_io_for_stage(
            agent_interfaces,
            stage_name="review",
            stage_inputs_raw={"claims": {"type": "list"}},
            stage_outputs_raw={},
            errors=errors,
        )
        assert errors == []

    def test_required_input_satisfied_by_prior_agent(self):
        from temper_ai.workflow.engines._validation_helpers import (
            validate_agent_io_for_stage,
        )

        agent_interfaces = {
            "researcher": {
                "inputs": {},
                "outputs": {
                    "claims": AgentIODeclaration(type="list"),
                },
            },
            "checker": {
                "inputs": {
                    "claims": AgentIODeclaration(type="list", required=True),
                },
                "outputs": {},
            },
        }
        errors = []
        validate_agent_io_for_stage(
            agent_interfaces,
            stage_name="review",
            stage_inputs_raw={},
            stage_outputs_raw={},
            errors=errors,
        )
        assert errors == []

    def test_required_with_default_passes(self):
        from temper_ai.workflow.engines._validation_helpers import (
            validate_agent_io_for_stage,
        )

        agent_interfaces = {
            "agent": {
                "inputs": {
                    "missing": AgentIODeclaration(
                        type="string", required=True, default="fallback"
                    ),
                },
                "outputs": {},
            },
        }
        errors = []
        validate_agent_io_for_stage(agent_interfaces, "s", {}, {}, errors)
        assert errors == []

    def test_optional_input_passes(self):
        from temper_ai.workflow.engines._validation_helpers import (
            validate_agent_io_for_stage,
        )

        agent_interfaces = {
            "agent": {
                "inputs": {
                    "optional_field": AgentIODeclaration(type="string", required=False),
                },
                "outputs": {},
            },
        }
        errors = []
        validate_agent_io_for_stage(agent_interfaces, "s", {}, {}, errors)
        assert errors == []

    def test_type_mismatch_between_agents(self):
        from temper_ai.workflow.engines._validation_helpers import (
            validate_agent_io_for_stage,
        )

        agent_interfaces = {
            "producer": {
                "inputs": {},
                "outputs": {
                    "severity": AgentIODeclaration(type="string"),
                },
            },
            "consumer": {
                "inputs": {
                    "severity": AgentIODeclaration(type="number", required=True),
                },
                "outputs": {},
            },
        }
        errors = []
        validate_agent_io_for_stage(
            agent_interfaces, "review", {"severity": {}}, {}, errors
        )
        assert any("type mismatch" in e for e in errors)

    def test_stage_output_coverage_warning(self, caplog):
        """Stage output with no producing agent logs a warning."""
        import logging

        from temper_ai.workflow.engines._validation_helpers import (
            validate_agent_io_for_stage,
        )

        agent_interfaces = {
            "agent": {
                "inputs": {},
                "outputs": {
                    "analysis": AgentIODeclaration(type="string"),
                },
            },
        }
        with caplog.at_level(logging.WARNING):
            errors = []
            validate_agent_io_for_stage(
                agent_interfaces,
                stage_name="review",
                stage_inputs_raw={},
                stage_outputs_raw={"summary": {"type": "string"}},
                errors=errors,
            )
        # Warning, not error
        assert errors == []
        assert any(
            "summary" in r.message and "no agent produces" in r.message
            for r in caplog.records
        )

    def test_stage_output_covered_by_agent(self, caplog):
        """Stage output covered by an agent — no warning."""
        import logging

        from temper_ai.workflow.engines._validation_helpers import (
            validate_agent_io_for_stage,
        )

        agent_interfaces = {
            "agent": {
                "inputs": {},
                "outputs": {
                    "summary": AgentIODeclaration(type="string"),
                },
            },
        }
        with caplog.at_level(logging.WARNING):
            errors = []
            validate_agent_io_for_stage(
                agent_interfaces,
                "review",
                {},
                {"summary": {"type": "string"}},
                errors,
            )
        assert errors == []
        assert not any("no agent produces" in r.message for r in caplog.records)

    def test_agents_without_declarations_skipped(self):
        """Agents with no inputs/outputs are skipped — no errors."""
        from temper_ai.workflow.engines._validation_helpers import (
            validate_agent_io_for_stage,
        )

        agent_interfaces = {
            "old_agent_a": {"inputs": {}, "outputs": {}},
            "old_agent_b": {"inputs": {}, "outputs": {}},
        }
        errors = []
        validate_agent_io_for_stage(agent_interfaces, "s", {}, {}, errors)
        assert errors == []

    def test_mixed_declared_and_undeclared_agents(self):
        """Mix of agents with and without declarations."""
        from temper_ai.workflow.engines._validation_helpers import (
            validate_agent_io_for_stage,
        )

        agent_interfaces = {
            "old_agent": {"inputs": {}, "outputs": {}},
            "new_agent": {
                "inputs": {
                    "topic": AgentIODeclaration(type="string", required=True),
                },
                "outputs": {},
            },
        }
        errors = []
        validate_agent_io_for_stage(
            agent_interfaces,
            "s",
            {"topic": {"type": "string"}},  # stage provides it
            {},
            errors,
        )
        assert errors == []


# ── DynamicEngine integration ─────────────────────────────────────


class TestDynamicEngineValidation:
    """Test agent I/O validation is available from the unified module."""

    def test_validate_agent_io_in_validation_module(self):
        """Verify validate_agent_io is importable from workflow.validation."""
        from temper_ai.workflow.validation import validate_agent_io

        assert callable(validate_agent_io)
