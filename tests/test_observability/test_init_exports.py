"""Tests for src/observability/__init__.py exports and lazy loading."""
import pytest


class TestObservabilityInitExports:
    """Tests for observability package __init__ exports."""

    def test_eager_imports_available(self):
        """Test that eager imports are immediately available."""
        import src.observability as obs

        # Backend ABC
        assert hasattr(obs, 'ObservabilityBackend')
        assert obs.ObservabilityBackend is not None

        # Context
        assert hasattr(obs, 'ExecutionContext')
        assert obs.ExecutionContext is not None

        # Models
        assert hasattr(obs, 'WorkflowExecution')
        assert hasattr(obs, 'StageExecution')
        assert hasattr(obs, 'AgentExecution')
        assert hasattr(obs, 'LLMCall')
        assert hasattr(obs, 'ToolExecution')
        assert hasattr(obs, 'CollaborationEvent')
        assert hasattr(obs, 'AgentMeritScore')
        assert hasattr(obs, 'DecisionOutcome')
        assert hasattr(obs, 'SystemMetric')
        assert hasattr(obs, 'SchemaVersion')

        # Tracker
        assert hasattr(obs, 'ExecutionTracker')

        # Hooks
        assert hasattr(obs, 'ExecutionHook')
        assert hasattr(obs, 'get_tracker')
        assert hasattr(obs, 'set_tracker')
        assert hasattr(obs, 'reset_tracker')
        assert hasattr(obs, 'track_workflow')
        assert hasattr(obs, 'track_stage')
        assert hasattr(obs, 'track_agent')

    def test_lazy_backend_imports(self):
        """Test that backend implementations are lazily loaded."""
        import src.observability as obs

        # Access lazy imports
        assert hasattr(obs, 'SQLObservabilityBackend')
        sql_backend = obs.SQLObservabilityBackend
        assert sql_backend is not None

        assert hasattr(obs, 'PrometheusObservabilityBackend')
        prom_backend = obs.PrometheusObservabilityBackend
        assert prom_backend is not None

        assert hasattr(obs, 'S3ObservabilityBackend')
        s3_backend = obs.S3ObservabilityBackend
        assert s3_backend is not None

    def test_lazy_buffer_imports(self):
        """Test that buffer is lazily loaded."""
        import src.observability as obs

        assert hasattr(obs, 'ObservabilityBuffer')
        buffer_cls = obs.ObservabilityBuffer
        assert buffer_cls is not None

    def test_lazy_console_imports(self):
        """Test that console utilities are lazily loaded."""
        import src.observability as obs

        assert hasattr(obs, 'WorkflowVisualizer')
        assert hasattr(obs, 'StreamingVisualizer')
        assert hasattr(obs, 'print_workflow_tree')

        visualizer = obs.WorkflowVisualizer
        assert visualizer is not None

    def test_lazy_database_imports(self):
        """Test that database utilities are lazily loaded."""
        import src.observability as obs

        assert hasattr(obs, 'DatabaseManager')
        assert hasattr(obs, 'init_database')
        assert hasattr(obs, 'get_database')
        assert hasattr(obs, 'get_session')

        db_manager = obs.DatabaseManager
        assert db_manager is not None

    def test_lazy_formatters_imports(self):
        """Test that formatters are lazily loaded."""
        import src.observability as obs

        assert hasattr(obs, 'format_duration')
        assert hasattr(obs, 'format_timestamp')
        assert hasattr(obs, 'format_tokens')
        assert hasattr(obs, 'format_cost')
        assert hasattr(obs, 'status_to_color')
        assert hasattr(obs, 'status_to_icon')

        formatter = obs.format_duration
        assert callable(formatter)

    def test_lazy_migrations_imports(self):
        """Test that migration utilities are lazily loaded."""
        import src.observability as obs

        assert hasattr(obs, 'create_schema')
        assert hasattr(obs, 'drop_schema')
        assert hasattr(obs, 'reset_schema')

        create_fn = obs.create_schema
        assert callable(create_fn)

    def test_all_exports_defined(self):
        """Test that __all__ contains all expected exports."""
        import src.observability as obs

        assert hasattr(obs, '__all__')
        all_exports = obs.__all__

        # Check key exports are in __all__
        expected = [
            'ObservabilityBackend',
            'SQLObservabilityBackend',
            'PrometheusObservabilityBackend',
            'S3ObservabilityBackend',
            'ObservabilityBuffer',
            'WorkflowExecution',
            'ExecutionTracker',
            'ExecutionContext',
            'get_tracker',
            'DatabaseManager',
            'create_schema',
            'WorkflowVisualizer',
            'format_duration',
        ]

        for name in expected:
            assert name in all_exports, f"{name} not in __all__"

    def test_lazy_import_caching(self):
        """Test that lazy imports are cached after first access."""
        import src.observability as obs

        # First access triggers lazy load
        first_ref = obs.SQLObservabilityBackend

        # Second access should return cached value
        second_ref = obs.SQLObservabilityBackend

        # Should be the same object
        assert first_ref is second_ref

    def test_invalid_lazy_import_raises_attribute_error(self):
        """Test that accessing non-existent attributes raises AttributeError."""
        import src.observability as obs

        with pytest.raises(AttributeError) as exc_info:
            _ = obs.NonExistentAttribute

        assert "has no attribute 'NonExistentAttribute'" in str(exc_info.value)

    def test_getattr_not_called_for_eager_imports(self):
        """Test that __getattr__ is not needed for eager imports."""
        import src.observability as obs

        # These should be in globals(), not require __getattr__
        assert 'ObservabilityBackend' in dir(obs)
        assert 'ExecutionTracker' in dir(obs)
        assert 'ExecutionContext' in dir(obs)


class TestBackendsInitExports:
    """Tests for src/observability/backends/__init__.py exports."""

    def test_backends_init_exports(self):
        """Test that backends __init__ exports all backend implementations."""
        from src.observability import backends

        assert hasattr(backends, 'SQLObservabilityBackend')
        assert hasattr(backends, 'PrometheusObservabilityBackend')
        assert hasattr(backends, 'S3ObservabilityBackend')

    def test_backends_all_defined(self):
        """Test that __all__ is correctly defined."""
        from src.observability import backends

        assert hasattr(backends, '__all__')
        assert 'SQLObservabilityBackend' in backends.__all__
        assert 'PrometheusObservabilityBackend' in backends.__all__
        assert 'S3ObservabilityBackend' in backends.__all__

    def test_backends_imports_work(self):
        """Test that imports from backends work correctly."""
        from src.observability.backends import (
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
        from src.observability import aggregation

        assert hasattr(aggregation, 'AggregationOrchestrator')
        assert hasattr(aggregation, 'AggregationPeriod')

    def test_aggregation_all_defined(self):
        """Test that __all__ is correctly defined."""
        from src.observability import aggregation

        assert hasattr(aggregation, '__all__')
        assert 'AggregationOrchestrator' in aggregation.__all__
        assert 'AggregationPeriod' in aggregation.__all__

    def test_aggregation_imports_work(self):
        """Test that imports from aggregation work correctly."""
        from src.observability.aggregation import AggregationOrchestrator, AggregationPeriod

        assert AggregationOrchestrator is not None
        assert AggregationPeriod is not None

    def test_aggregation_period_is_enum(self):
        """Test that AggregationPeriod is the enum type."""
        from enum import Enum

        from src.observability.aggregation import AggregationPeriod

        assert issubclass(AggregationPeriod, Enum)

    def test_aggregation_orchestrator_is_class(self):
        """Test that AggregationOrchestrator is a class."""
        from src.observability.aggregation import AggregationOrchestrator

        assert isinstance(AggregationOrchestrator, type)
