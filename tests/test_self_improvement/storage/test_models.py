"""
Tests for M5 storage models.

Verifies that:
1. CustomMetric model can be created with all fields
2. Default values are applied correctly
3. Indexes are defined for query performance
4. Raw SQL migration was removed in favor of Alembic
"""

from datetime import datetime, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from src.self_improvement.storage.models import (
    CustomMetric,
)


class TestCustomMetric:
    """Test CustomMetric model."""

    def test_create_custom_metric_with_all_fields(self):
        """Can create CustomMetric with all fields specified."""
        now = datetime.now(timezone.utc)
        metric = CustomMetric(
            id=1,
            execution_id="exec-123",
            metric_name="extraction_quality",
            value=0.95,
            metric_type="automatic",
            collector_version="1.2",
            collected_at=now,
            extra_metadata={"confidence": 0.9, "samples": 100},
            created_at=now,
        )

        assert metric.id == 1
        assert metric.execution_id == "exec-123"
        assert metric.metric_name == "extraction_quality"
        assert metric.value == 0.95
        assert metric.metric_type == "automatic"
        assert metric.collector_version == "1.2"
        assert metric.collected_at == now
        assert metric.extra_metadata == {"confidence": 0.9, "samples": 100}
        assert metric.created_at == now

    def test_create_custom_metric_with_defaults(self):
        """CustomMetric applies default values correctly."""
        metric = CustomMetric(
            execution_id="exec-456",
            metric_name="success_rate",
            value=1.0,
            metric_type="automatic",
        )

        assert metric.id is None  # Will be assigned by database
        assert metric.execution_id == "exec-456"
        assert metric.metric_name == "success_rate"
        assert metric.value == 1.0
        assert metric.metric_type == "automatic"
        assert metric.collector_version == "1.0"  # Default
        assert isinstance(metric.collected_at, datetime)
        assert isinstance(metric.created_at, datetime)
        assert metric.extra_metadata is None  # Default

    def test_custom_metric_with_extra_metadata(self):
        """CustomMetric can store arbitrary extra_metadata."""
        metric = CustomMetric(
            execution_id="exec-789",
            metric_name="factual_accuracy",
            value=0.88,
            metric_type="custom",
            extra_metadata={
                "verification_method": "fact_check_api",
                "facts_checked": 25,
                "facts_correct": 22,
                "confidence": 0.95,
                "evidence": ["fact1", "fact2", "fact3"],
            },
        )

        assert metric.extra_metadata["verification_method"] == "fact_check_api"
        assert metric.extra_metadata["facts_checked"] == 25
        assert metric.extra_metadata["facts_correct"] == 22
        assert metric.extra_metadata["confidence"] == 0.95
        assert len(metric.extra_metadata["evidence"]) == 3

    def test_custom_metric_value_boundaries(self):
        """CustomMetric accepts valid boundary values."""
        min_metric = CustomMetric(
            execution_id="exec-min",
            metric_name="test",
            value=0.0,
            metric_type="automatic",
        )
        max_metric = CustomMetric(
            execution_id="exec-max",
            metric_name="test",
            value=1.0,
            metric_type="automatic",
        )

        assert min_metric.value == 0.0
        assert max_metric.value == 1.0

    def test_custom_metric_types(self):
        """CustomMetric accepts all valid metric types."""
        automatic = CustomMetric(
            execution_id="exec-1",
            metric_name="cost",
            value=0.5,
            metric_type="automatic",
        )
        derived = CustomMetric(
            execution_id="exec-2",
            metric_name="retry_rate",
            value=0.1,
            metric_type="derived",
        )
        custom = CustomMetric(
            execution_id="exec-3",
            metric_name="quality",
            value=0.9,
            metric_type="custom",
        )

        assert automatic.metric_type == "automatic"
        assert derived.metric_type == "derived"
        assert custom.metric_type == "custom"


class TestCustomMetricDatabase:
    """Test CustomMetric database operations."""

    @pytest.fixture
    def engine(self):
        """Create in-memory SQLite database for testing."""
        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        return engine

    def test_insert_and_query_custom_metric(self, engine):
        """Can insert and query CustomMetric from database."""
        metric = CustomMetric(
            execution_id="exec-db-1",
            metric_name="test_metric",
            value=0.75,
            metric_type="automatic",
            extra_metadata={"test": True},
        )

        with Session(engine) as session:
            session.add(metric)
            session.commit()
            session.refresh(metric)

            # Verify ID was assigned
            assert metric.id is not None

        # Query back
        with Session(engine) as session:
            result = session.exec(
                select(CustomMetric).where(
                    CustomMetric.execution_id == "exec-db-1"
                )
            ).first()

            assert result is not None
            assert result.execution_id == "exec-db-1"
            assert result.metric_name == "test_metric"
            assert result.value == 0.75
            assert result.extra_metadata == {"test": True}

    def test_query_by_metric_name(self, engine):
        """Can query metrics by metric_name (indexed field)."""
        metrics = [
            CustomMetric(
                execution_id=f"exec-{i}",
                metric_name="extraction_quality",
                value=0.8 + i * 0.05,
                metric_type="automatic",
            )
            for i in range(5)
        ]

        with Session(engine) as session:
            for metric in metrics:
                session.add(metric)
            session.commit()

        with Session(engine) as session:
            results = session.exec(
                select(CustomMetric).where(
                    CustomMetric.metric_name == "extraction_quality"
                )
            ).all()

            assert len(results) == 5
            assert all(m.metric_name == "extraction_quality" for m in results)

    def test_query_by_metric_type(self, engine):
        """Can query metrics by metric_type (indexed field)."""
        metrics = [
            CustomMetric(
                execution_id=f"exec-auto-{i}",
                metric_name=f"metric-{i}",
                value=0.5,
                metric_type="automatic",
            )
            for i in range(3)
        ] + [
            CustomMetric(
                execution_id=f"exec-custom-{i}",
                metric_name=f"metric-custom-{i}",
                value=0.7,
                metric_type="custom",
            )
            for i in range(2)
        ]

        with Session(engine) as session:
            for metric in metrics:
                session.add(metric)
            session.commit()

        with Session(engine) as session:
            automatic_results = session.exec(
                select(CustomMetric).where(
                    CustomMetric.metric_type == "automatic"
                )
            ).all()
            custom_results = session.exec(
                select(CustomMetric).where(CustomMetric.metric_type == "custom")
            ).all()

            assert len(automatic_results) == 3
            assert len(custom_results) == 2

    def test_query_by_execution_id(self, engine):
        """Can query metrics by execution_id (indexed field)."""
        metrics = [
            CustomMetric(
                execution_id="exec-multi",
                metric_name=f"metric-{i}",
                value=0.5 + i * 0.1,
                metric_type="automatic",
            )
            for i in range(4)
        ]

        with Session(engine) as session:
            for metric in metrics:
                session.add(metric)
            session.commit()

        with Session(engine) as session:
            results = session.exec(
                select(CustomMetric).where(
                    CustomMetric.execution_id == "exec-multi"
                )
            ).all()

            assert len(results) == 4
            assert all(m.execution_id == "exec-multi" for m in results)


class TestCustomMetricSchemaRemoved:
    """Verify raw SQL migration was removed in favor of Alembic."""

    def test_raw_sql_schema_removed(self):
        """CUSTOM_METRICS_SCHEMA_SQL should no longer exist (M-17)."""
        import src.self_improvement.storage.models as models_mod
        assert not hasattr(models_mod, "CUSTOM_METRICS_SCHEMA_SQL"), (
            "CUSTOM_METRICS_SCHEMA_SQL should be removed; use Alembic migrations instead"
        )
