"""Tests for temper_ai/shared/core/__init__.py.

Targets uncovered lines 20-28 — the __getattr__ lazy import mechanism.
"""

import pytest


class TestCoreInitLazyImports:
    """Test lazy imports via __getattr__ in temper_ai.shared.core."""

    def test_circuit_breaker_accessible_via_package(self):
        """CircuitBreaker can be imported from the core package (lines 20-23)."""
        import temper_ai.shared.core as core

        cb = core.CircuitBreaker
        # Should be the actual class
        from temper_ai.shared.core.circuit_breaker import CircuitBreaker

        assert cb is CircuitBreaker

    def test_execution_context_accessible_via_package(self):
        """ExecutionContext can be imported from the core package (lines 24-27)."""
        import temper_ai.shared.core as core

        ec = core.ExecutionContext
        from temper_ai.shared.core.context import ExecutionContext

        assert ec is ExecutionContext

    def test_unknown_attribute_raises_attribute_error(self):
        """Accessing unknown attribute raises AttributeError (line 28)."""
        import temper_ai.shared.core as core

        with pytest.raises(AttributeError, match="no attribute"):
            _ = core.NonExistentClass

    def test_circuit_breaker_is_instantiable(self):
        """CircuitBreaker from package can be instantiated."""
        import temper_ai.shared.core as core

        cb = core.CircuitBreaker(name="test-from-pkg")
        assert cb.name == "test-from-pkg"

    def test_execution_context_is_instantiable(self):
        """ExecutionContext from package can be instantiated."""
        import temper_ai.shared.core as core

        ctx = core.ExecutionContext(workflow_id="wf-test")
        assert ctx.workflow_id == "wf-test"
