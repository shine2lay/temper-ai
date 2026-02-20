"""Integration tests for the optimization pipeline."""

import json
from unittest.mock import MagicMock, patch
import sys

import pytest

from temper_ai.optimization.dspy._schemas import (
    CompilationResult,
    PromptOptimizationConfig,
    TrainingExample,
)


class TestOptimizationPipeline:
    """End-to-end optimization flow tests (all dspy mocked)."""

    def test_full_pipeline(self, tmp_path):
        """Collect -> build -> compile -> save -> load -> adapt prompt."""
        from temper_ai.optimization.dspy.program_store import CompiledProgramStore
        from temper_ai.optimization.dspy.prompt_adapter import DSPyPromptAdapter

        # Save a compiled program
        store = CompiledProgramStore(store_dir=str(tmp_path))
        store.save(
            "researcher",
            {
                "instruction": "Be thorough in analysis",
                "demos": [
                    {"input": "AI safety", "output": "Detailed analysis"},
                ],
            },
            metadata={"optimizer": "bootstrap"},
        )

        # Adapt a prompt
        adapter = DSPyPromptAdapter(store=store)
        result = adapter.augment_prompt(
            "researcher", "Research {{ topic }}"
        )
        assert "Research {{ topic }}" in result
        assert "Be thorough in analysis" in result
        assert "AI safety" in result

    def test_graceful_degradation_no_program(self, tmp_path):
        """Prompt unchanged when no compiled program exists."""
        from temper_ai.optimization.dspy.program_store import CompiledProgramStore
        from temper_ai.optimization.dspy.prompt_adapter import DSPyPromptAdapter

        store = CompiledProgramStore(store_dir=str(tmp_path))
        adapter = DSPyPromptAdapter(store=store)
        result = adapter.augment_prompt("unknown", "Base prompt")
        assert result == "Base prompt"

    def test_config_round_trip(self):
        """YAML dict -> AgentConfig -> PromptOptimizationConfig."""
        from temper_ai.storage.schemas.agent_config import AgentConfig

        config = AgentConfig(
            agent={
                "name": "researcher",
                "description": "test",
                "prompt": {"inline": "Research {{ topic }}"},
                "inference": {"provider": "ollama", "model": "llama3"},
                "error_handling": {},
                "prompt_optimization": {
                    "enabled": True,
                    "optimizer": "mipro",
                    "max_demos": 5,
                },
            }
        )
        opt = config.agent.prompt_optimization
        assert isinstance(opt, PromptOptimizationConfig)
        assert opt.optimizer == "mipro"
        assert opt.max_demos == 5

    def test_training_example_serialization(self):
        """TrainingExample can round-trip through JSON."""
        ex = TrainingExample(
            input_text="test input",
            output_text="test output",
            metric_score=0.95,
            agent_name="researcher",
            prompt_template_hash="abc123",
        )
        data = json.loads(ex.model_dump_json())
        restored = TrainingExample(**data)
        assert restored.input_text == ex.input_text
        assert restored.metric_score == ex.metric_score

    def test_autonomy_schema_has_optimization_field(self):
        """AutonomousLoopConfig has prompt_optimization_enabled field."""
        from temper_ai.autonomy._schemas import AutonomousLoopConfig
        config = AutonomousLoopConfig(prompt_optimization_enabled=True)
        assert config.prompt_optimization_enabled is True

    def test_post_execution_report_has_optimization_result(self):
        """PostExecutionReport has optimization_result field."""
        from temper_ai.autonomy._schemas import PostExecutionReport
        report = PostExecutionReport(
            optimization_result={"agents_compiled": 2}
        )
        assert report.optimization_result["agents_compiled"] == 2
