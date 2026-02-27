"""
Tests for M3-12: Quality Gates and Confidence Thresholds.

Tests quality gate validation after synthesis.
"""

from unittest.mock import Mock

from temper_ai.agent.strategies.base import SynthesisResult
from temper_ai.workflow.engines.langgraph_compiler import LangGraphCompiler


class TestQualityGateValidation:
    """Test quality gate validation logic."""

    def setup_method(self):
        """Setup test fixtures."""
        self.compiler = LangGraphCompiler(config_loader=Mock())

    def test_quality_gates_disabled(self):
        """Quality gates disabled should always pass."""
        synthesis_result = SynthesisResult(
            decision="Option A",
            confidence=0.3,  # Low confidence
            method="consensus",
            votes={"A": 1},
            conflicts=[],
            reasoning="test",
            metadata={},
        )

        stage_config = {"quality_gates": {"enabled": False, "min_confidence": 0.7}}

        passed, violations = self.compiler._validate_quality_gates(
            synthesis_result, stage_config, "test_stage"
        )

        assert passed is True
        assert violations == []

    def test_quality_gates_confidence_pass(self):
        """Test passing minimum confidence threshold."""
        synthesis_result = SynthesisResult(
            decision="Option A",
            confidence=0.85,  # Above threshold
            method="consensus",
            votes={"A": 2, "B": 1},
            conflicts=[],
            reasoning="test",
            metadata={},
        )

        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7,
                "min_findings": 0,  # Disable findings check
                "require_citations": False,  # Disable citations check
            }
        }

        passed, violations = self.compiler._validate_quality_gates(
            synthesis_result, stage_config, "test_stage"
        )

        assert passed is True
        assert violations == []

    def test_quality_gates_confidence_fail(self):
        """Test failing minimum confidence threshold."""
        synthesis_result = SynthesisResult(
            decision="Option A",
            confidence=0.5,  # Below threshold
            method="consensus",
            votes={"A": 1},
            conflicts=[],
            reasoning="test",
            metadata={},
        )

        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7,
                "min_findings": 0,
                "require_citations": False,
            }
        }

        passed, violations = self.compiler._validate_quality_gates(
            synthesis_result, stage_config, "test_stage"
        )

        assert passed is False
        assert len(violations) == 1
        assert "Confidence 0.50 below minimum 0.70" in violations[0]

    def test_quality_gates_findings_pass(self):
        """Test passing minimum findings requirement."""
        synthesis_result = SynthesisResult(
            decision="Option A",
            confidence=0.9,
            method="consensus",
            votes={"A": 2},
            conflicts=[],
            reasoning="test",
            metadata={
                "findings": ["finding1", "finding2", "finding3", "finding4", "finding5"]
            },
        )

        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7,
                "min_findings": 5,
                "require_citations": False,
            }
        }

        passed, violations = self.compiler._validate_quality_gates(
            synthesis_result, stage_config, "test_stage"
        )

        assert passed is True
        assert violations == []

    def test_quality_gates_findings_fail(self):
        """Test failing minimum findings requirement."""
        synthesis_result = SynthesisResult(
            decision="Option A",
            confidence=0.9,
            method="consensus",
            votes={"A": 2},
            conflicts=[],
            reasoning="test",
            metadata={"findings": ["finding1", "finding2"]},  # Only 2 findings
        )

        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7,
                "min_findings": 5,
                "require_citations": False,
            }
        }

        passed, violations = self.compiler._validate_quality_gates(
            synthesis_result, stage_config, "test_stage"
        )

        assert passed is False
        assert len(violations) == 1
        assert "Only 2 findings, minimum 5 required" in violations[0]

    def test_quality_gates_citations_pass(self):
        """Test passing citations requirement."""
        synthesis_result = SynthesisResult(
            decision="Option A",
            confidence=0.9,
            method="consensus",
            votes={"A": 2},
            conflicts=[],
            reasoning="test",
            metadata={"citations": ["source1", "source2"]},
        )

        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7,
                "min_findings": 0,
                "require_citations": True,
            }
        }

        passed, violations = self.compiler._validate_quality_gates(
            synthesis_result, stage_config, "test_stage"
        )

        assert passed is True
        assert violations == []

    def test_quality_gates_citations_fail(self):
        """Test failing citations requirement."""
        synthesis_result = SynthesisResult(
            decision="Option A",
            confidence=0.9,
            method="consensus",
            votes={"A": 2},
            conflicts=[],
            reasoning="test",
            metadata={},  # No citations
        )

        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7,
                "min_findings": 0,
                "require_citations": True,
            }
        }

        passed, violations = self.compiler._validate_quality_gates(
            synthesis_result, stage_config, "test_stage"
        )

        assert passed is False
        assert len(violations) == 1
        assert "No citations provided" in violations[0]

    def test_quality_gates_multiple_violations(self):
        """Test multiple quality gate violations."""
        synthesis_result = SynthesisResult(
            decision="Option A",
            confidence=0.5,  # Too low
            method="consensus",
            votes={"A": 1},
            conflicts=[],
            reasoning="test",
            metadata={
                "findings": ["finding1"]  # Too few
                # No citations
            },
        )

        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7,
                "min_findings": 5,
                "require_citations": True,
            }
        }

        passed, violations = self.compiler._validate_quality_gates(
            synthesis_result, stage_config, "test_stage"
        )

        assert passed is False
        assert len(violations) == 3
        assert any("Confidence" in v for v in violations)
        assert any("findings" in v for v in violations)
        assert any("citations" in v for v in violations)

    def test_quality_gates_default_config(self):
        """Test quality gates with default/missing config."""
        synthesis_result = SynthesisResult(
            decision="Option A",
            confidence=0.8,
            method="consensus",
            votes={"A": 2},
            conflicts=[],
            reasoning="test",
            metadata={},
        )

        # Empty config - should use defaults (enabled=False for backward compatibility)
        stage_config = {}

        passed, violations = self.compiler._validate_quality_gates(
            synthesis_result, stage_config, "test_stage"
        )

        # With defaults: enabled=False, quality gates disabled
        # This should pass (quality gates not enforced)
        assert passed is True
        assert violations == []
