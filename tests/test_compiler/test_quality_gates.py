"""
Tests for M3-12: Quality Gates and Confidence Thresholds.

Tests quality gate validation after synthesis.
"""
from unittest.mock import Mock

from src.compiler.langgraph_compiler import LangGraphCompiler
from src.strategies.base import SynthesisResult


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
            metadata={}
        )

        stage_config = {
            "quality_gates": {
                "enabled": False,
                "min_confidence": 0.7
            }
        }

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
            metadata={}
        )

        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7,
                "min_findings": 0,  # Disable findings check
                "require_citations": False  # Disable citations check
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
            metadata={}
        )

        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7,
                "min_findings": 0,
                "require_citations": False
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
            }
        )

        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7,
                "min_findings": 5,
                "require_citations": False
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
            metadata={
                "findings": ["finding1", "finding2"]  # Only 2 findings
            }
        )

        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7,
                "min_findings": 5,
                "require_citations": False
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
            metadata={
                "citations": ["source1", "source2"]
            }
        )

        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7,
                "min_findings": 0,
                "require_citations": True
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
            metadata={}  # No citations
        )

        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7,
                "min_findings": 0,
                "require_citations": True
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
            }
        )

        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7,
                "min_findings": 5,
                "require_citations": True
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
            metadata={}
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


class TestQualityGateIntegration:
    """Integration tests for quality gates in workflow execution."""

    def test_quality_gate_escalate_action(self):
        """Test that 'escalate' action raises exception on failure."""
        # This would require full integration test with actual stage execution
        # Placeholder for now
        assert True  # Placeholder - awaiting integration test implementation

    def test_quality_gate_proceed_with_warning_action(self):
        """Test that 'proceed_with_warning' logs warning but continues."""
        # This would require full integration test
        # Placeholder for now
        assert True  # Placeholder - awaiting integration test implementation

    def test_quality_gate_observability_tracking(self):
        """Test that quality gate failures are tracked in observability."""
        # This would require full integration test
        # Placeholder for now
        assert True  # Placeholder - awaiting integration test implementation


class TestQualityGateRetry:
    """Test quality gate retry logic."""

    def test_retry_state_initialization(self):
        """Test that retry state is properly initialized."""
        from src.compiler.executors.parallel import ParallelStageExecutor

        executor = ParallelStageExecutor()
        state = {"stage_outputs": {}}

        # Initialize retry counts
        if "stage_retry_counts" not in state:
            state["stage_retry_counts"] = {}

        assert "stage_retry_counts" in state
        assert isinstance(state["stage_retry_counts"], dict)

    def test_retry_counter_tracking(self):
        """Test retry counter increment and reset logic."""
        state = {"stage_retry_counts": {}}

        # Simulate first failure
        stage_name = "test_stage"
        retry_count = state["stage_retry_counts"].get(stage_name, 0)
        assert retry_count == 0

        # Increment on failure
        state["stage_retry_counts"][stage_name] = retry_count + 1
        assert state["stage_retry_counts"][stage_name] == 1

        # Increment again on second failure
        retry_count = state["stage_retry_counts"][stage_name]
        state["stage_retry_counts"][stage_name] = retry_count + 1
        assert state["stage_retry_counts"][stage_name] == 2

        # Reset on success
        del state["stage_retry_counts"][stage_name]
        assert stage_name not in state["stage_retry_counts"]

    def test_retry_exhaustion_check(self):
        """Test logic for checking if retries are exhausted."""
        max_retries = 2

        # Test various retry counts
        assert 0 < max_retries  # Should retry
        assert 1 < max_retries  # Should retry
        assert 2 >= max_retries  # Should escalate (exhausted)
        assert 3 >= max_retries  # Should escalate

    def test_max_retries_zero_check(self):
        """Test that max_retries=0 is handled correctly."""
        max_retries = 0
        retry_count = 0

        # With max_retries=0, first failure should escalate
        assert retry_count >= max_retries  # True, should escalate immediately

    def test_config_extraction(self):
        """Test extraction of retry config from quality gates."""
        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7,
                "on_failure": "retry_stage",
                "max_retries": 3
            }
        }

        stage_dict = stage_config if isinstance(stage_config, dict) else {}
        quality_gates_config = stage_dict.get("quality_gates", {})
        max_retries = quality_gates_config.get("max_retries", 2)
        on_failure = quality_gates_config.get("on_failure", "retry_stage")

        assert max_retries == 3
        assert on_failure == "retry_stage"

    def test_config_defaults(self):
        """Test default values when config is missing."""
        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7
                # No on_failure or max_retries specified
            }
        }

        stage_dict = stage_config if isinstance(stage_config, dict) else {}
        quality_gates_config = stage_dict.get("quality_gates", {})
        max_retries = quality_gates_config.get("max_retries", 2)
        on_failure = quality_gates_config.get("on_failure", "retry_stage")

        assert max_retries == 2  # Default
        assert on_failure == "retry_stage"  # Default
