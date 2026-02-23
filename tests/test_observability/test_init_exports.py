"""Tests for src/observability/__init__.py exports and lazy loading."""

import pytest


class TestObservabilityInitExports:
    """Tests for observability package __init__ exports."""

    def test_eager_imports_available(self):
        """Test that eager imports are immediately available and correct types."""
        import temper_ai.observability as obs

        # Backend ABC should be a class
        assert isinstance(obs.ObservabilityBackend, type)

        # Context should be a class
        assert isinstance(obs.ExecutionContext, type)

        # Models should be classes
        for model_name in [
            "WorkflowExecution",
            "StageExecution",
            "AgentExecution",
            "LLMCall",
            "ToolExecution",
            "CollaborationEvent",
            "AgentMeritScore",
            "DecisionOutcome",
            "SystemMetric",
            "SchemaVersion",
        ]:
            assert isinstance(
                getattr(obs, model_name), type
            ), f"{model_name} should be a class"

        # Tracker should be a class
        assert isinstance(obs.ExecutionTracker, type)

        # Hooks should be correct types
        assert isinstance(obs.ExecutionHook, type)
        assert callable(obs.get_tracker)
        assert callable(obs.set_tracker)
        assert callable(obs.reset_tracker)
        assert callable(obs.track_workflow)
        assert callable(obs.track_stage)
        assert callable(obs.track_agent)

    def test_lazy_backend_imports(self):
        """Test that backend implementations are lazily loaded and are classes."""
        import temper_ai.observability as obs

        # All backends should be classes
        assert isinstance(obs.SQLObservabilityBackend, type)
        assert isinstance(obs.PrometheusObservabilityBackend, type)
        assert isinstance(obs.S3ObservabilityBackend, type)

    def test_lazy_buffer_imports(self):
        """Test that buffer is lazily loaded and is a class."""
        import temper_ai.observability as obs

        assert isinstance(obs.ObservabilityBuffer, type)

    def test_lazy_console_imports(self):
        """Test that console utilities are lazily loaded and correct types."""
        import temper_ai.observability as obs

        assert isinstance(obs.WorkflowVisualizer, type)
        assert isinstance(obs.StreamingVisualizer, type)
        assert callable(obs.print_workflow_tree)

    def test_lazy_database_imports(self):
        """Test that database utilities are lazily loaded and correct types."""
        import temper_ai.observability as obs

        assert isinstance(obs.DatabaseManager, type)
        assert callable(obs.init_database)
        assert callable(obs.get_database)
        assert callable(obs.get_session)

    def test_lazy_formatters_imports(self):
        """Test that formatters are lazily loaded."""
        import temper_ai.observability as obs

        assert hasattr(obs, "format_duration")
        assert hasattr(obs, "format_timestamp")
        assert hasattr(obs, "format_tokens")
        assert hasattr(obs, "format_cost")
        assert hasattr(obs, "status_to_color")
        assert hasattr(obs, "status_to_icon")

        formatter = obs.format_duration
        assert callable(formatter)

    def test_lazy_migrations_imports(self):
        """Test that migration utilities are lazily loaded."""
        import temper_ai.observability as obs

        assert hasattr(obs, "create_schema")
        assert hasattr(obs, "drop_schema")
        assert hasattr(obs, "reset_schema")

        create_fn = obs.create_schema
        assert callable(create_fn)

    def test_all_exports_defined(self):
        """Test that __all__ contains all expected exports."""
        import temper_ai.observability as obs

        assert hasattr(obs, "__all__")
        all_exports = obs.__all__

        # Check key exports are in __all__
        expected = [
            "ObservabilityBackend",
            "SQLObservabilityBackend",
            "PrometheusObservabilityBackend",
            "S3ObservabilityBackend",
            "ObservabilityBuffer",
            "WorkflowExecution",
            "ExecutionTracker",
            "ExecutionContext",
            "get_tracker",
            "DatabaseManager",
            "create_schema",
            "WorkflowVisualizer",
            "format_duration",
        ]

        for name in expected:
            assert name in all_exports, f"{name} not in __all__"

    def test_lazy_import_caching(self):
        """Test that lazy imports are cached after first access."""
        import temper_ai.observability as obs

        # First access triggers lazy load
        first_ref = obs.SQLObservabilityBackend

        # Second access should return cached value
        second_ref = obs.SQLObservabilityBackend

        # Should be the same object
        assert first_ref is second_ref

    def test_invalid_lazy_import_raises_attribute_error(self):
        """Test that accessing non-existent attributes raises AttributeError."""
        import temper_ai.observability as obs

        with pytest.raises(AttributeError) as exc_info:
            _ = obs.NonExistentAttribute

        assert "has no attribute 'NonExistentAttribute'" in str(exc_info.value)

    def test_getattr_not_called_for_eager_imports(self):
        """Test that __getattr__ is not needed for eager imports."""
        import temper_ai.observability as obs

        # These should be in globals(), not require __getattr__
        assert "ObservabilityBackend" in dir(obs)
        assert "ExecutionTracker" in dir(obs)
        assert "ExecutionContext" in dir(obs)


class TestBackendsInitExports:
    """Tests for src/observability/backends/__init__.py exports."""

    def test_backends_init_exports(self):
        """Test that backends __init__ exports all backend implementations."""
        from temper_ai.observability import backends

        assert hasattr(backends, "SQLObservabilityBackend")
        assert hasattr(backends, "PrometheusObservabilityBackend")
        assert hasattr(backends, "S3ObservabilityBackend")

    def test_backends_all_defined(self):
        """Test that __all__ is correctly defined."""
        from temper_ai.observability import backends

        assert hasattr(backends, "__all__")
        assert "SQLObservabilityBackend" in backends.__all__
        assert "PrometheusObservabilityBackend" in backends.__all__
        assert "S3ObservabilityBackend" in backends.__all__

    def test_backends_imports_work(self):
        """Test that imports from backends work correctly."""
        from temper_ai.observability.backends import (
            PrometheusObservabilityBackend,
            S3ObservabilityBackend,
            SQLObservabilityBackend,
        )

        assert SQLObservabilityBackend is not None
        assert PrometheusObservabilityBackend is not None
        assert S3ObservabilityBackend is not None


class TestAggregationInitExports:
    """Tests for src/observability/aggregation/__init__.py exports."""

    def test_aggregation_init_exports(self):
        """Test that aggregation __init__ exports the public API."""
        from temper_ai.observability import aggregation

        assert hasattr(aggregation, "AggregationOrchestrator")
        assert hasattr(aggregation, "AggregationPeriod")

    def test_aggregation_all_defined(self):
        """Test that __all__ is correctly defined."""
        from temper_ai.observability import aggregation

        assert hasattr(aggregation, "__all__")
        assert "AggregationOrchestrator" in aggregation.__all__
        assert "AggregationPeriod" in aggregation.__all__

    def test_aggregation_imports_work(self):
        """Test that imports from aggregation work correctly."""
        from temper_ai.observability.aggregation import (
            AggregationOrchestrator,
            AggregationPeriod,
        )

        assert AggregationOrchestrator is not None
        assert AggregationPeriod is not None

    def test_aggregation_period_is_enum(self):
        """Test that AggregationPeriod is the enum type."""
        from enum import Enum

        from temper_ai.observability.aggregation import AggregationPeriod

        assert issubclass(AggregationPeriod, Enum)

    def test_aggregation_orchestrator_is_class(self):
        """Test that AggregationOrchestrator is a class."""
        from temper_ai.observability.aggregation import AggregationOrchestrator

        assert isinstance(AggregationOrchestrator, type)
