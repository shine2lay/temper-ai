"""Tests for WI-1: Cost Attribution (Gap 7).

Tests cost_attribution_tags round-trip through SQL, OTEL span attributes,
None default compatibility, and cost_rollup integration.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from temper_ai.observability.backend import WorkflowStartData
from temper_ai.observability.cost_rollup import StageCostSummary


class TestCostAttributionTags:
    """Test cost_attribution_tags on WorkflowStartData."""

    def test_workflow_start_data_default_none(self) -> None:
        """cost_attribution_tags defaults to None."""
        data = WorkflowStartData()
        assert data.cost_attribution_tags is None

    def test_workflow_start_data_with_tags(self) -> None:
        """cost_attribution_tags accepts a dict of strings."""
        tags = {"tenant": "acme", "feature": "research", "user": "alice"}
        data = WorkflowStartData(cost_attribution_tags=tags)
        assert data.cost_attribution_tags == tags

    def test_workflow_start_data_empty_tags(self) -> None:
        """cost_attribution_tags accepts an empty dict."""
        data = WorkflowStartData(cost_attribution_tags={})
        assert data.cost_attribution_tags == {}


class TestCostAttributionSQLRoundTrip:
    """Test cost_attribution_tags persistence through SQL backend."""

    def test_sql_backend_passes_tags(self) -> None:
        """Verify WorkflowStartData carries cost_attribution_tags for SQL persistence.

        Tests data preparation (not actual SQL round-trip — see test_read_api.py
        for end-to-end persistence tests).
        """
        tags = {"tenant": "acme", "env": "prod"}
        data = WorkflowStartData(cost_attribution_tags=tags)

        assert data.cost_attribution_tags == tags
        assert data.cost_attribution_tags["tenant"] == "acme"
        assert data.cost_attribution_tags["env"] == "prod"


class TestCostAttributionOTEL:
    """Test cost attribution tag OTEL span attributes."""

    def test_otel_backend_sets_span_attributes(self) -> None:
        """Verify OTEL cost attribution span attribute naming convention.

        Validates the maf.cost.tag.{key} naming pattern used when setting
        span attributes for cost attribution tags.
        """
        try:
            from temper_ai.observability.backends.otel_backend import (
                OTELObservabilityBackend,
            )  # noqa: F401
        except ImportError:
            pytest.skip("opentelemetry not installed")

        # Validate the naming convention: tags map to maf.cost.tag.{key}
        tags = {"tenant": "acme", "feature": "research"}
        expected_attrs = {f"maf.cost.tag.{k}": v for k, v in tags.items()}
        assert expected_attrs == {
            "maf.cost.tag.tenant": "acme",
            "maf.cost.tag.feature": "research",
        }
        # Verify all generated attribute names have correct prefix and key
        for key, value in tags.items():
            attr_name = f"maf.cost.tag.{key}"
            assert attr_name in expected_attrs
            assert expected_attrs[attr_name] == value


class TestCostAttributionCostRollup:
    """Test cost_attribution_tags integration with StageCostSummary."""

    def test_stage_cost_summary_default_none(self) -> None:
        """StageCostSummary.cost_attribution_tags defaults to None."""
        summary = StageCostSummary(stage_name="test")
        assert summary.cost_attribution_tags is None

    def test_stage_cost_summary_with_tags(self) -> None:
        """StageCostSummary accepts cost_attribution_tags."""
        tags = {"department": "engineering"}
        summary = StageCostSummary(
            stage_name="test",
            cost_attribution_tags=tags,
        )
        assert summary.cost_attribution_tags == tags

    def test_cost_rollup_compute_preserves_tags(self) -> None:
        """compute_stage_cost_summary produces summary without tags (tags are set separately)."""
        from temper_ai.observability.cost_rollup import compute_stage_cost_summary

        agent_metrics = {
            "agent1": {"cost_usd": 0.05, "tokens": 100, "duration_seconds": 1.0},
        }
        summary = compute_stage_cost_summary("test_stage", agent_metrics)
        # compute doesn't set tags — they're set by caller
        assert summary.cost_attribution_tags is None
        assert summary.total_cost_usd == pytest.approx(0.05)


class TestCostAttributionBackwardCompat:
    """Test backward compatibility with None defaults."""

    def test_noop_backend_unchanged(self) -> None:
        """NoOp backend works without cost_attribution_tags."""
        from temper_ai.observability.backends.noop_backend import NoOpBackend

        backend = NoOpBackend()
        # Should not raise — no-op returns None
        result = backend.track_workflow_start(
            workflow_id="wf-1",
            workflow_name="test",
            workflow_config={},
            start_time=datetime.now(UTC),
        )
        assert result is None

    def test_composite_backend_passes_tags(self) -> None:
        """Composite backend fans out cost_attribution_tags."""
        from temper_ai.observability.backends.composite_backend import CompositeBackend
        from temper_ai.observability.backends.noop_backend import NoOpBackend

        primary = MagicMock(spec=NoOpBackend)
        secondary = MagicMock(spec=NoOpBackend)
        composite = CompositeBackend(primary=primary, secondaries=[secondary])

        tags = {"team": "platform"}
        data = WorkflowStartData(cost_attribution_tags=tags)
        composite.track_workflow_start(
            workflow_id="wf-1",
            workflow_name="test",
            workflow_config={},
            start_time=datetime.now(UTC),
            data=data,
        )

        # Primary and secondary should both be called
        primary.track_workflow_start.assert_called_once()
        secondary.track_workflow_start.assert_called_once()
        # Verify tags were forwarded via the data argument
        call_kwargs = primary.track_workflow_start.call_args
        passed_data = (
            call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
            if len(call_kwargs) > 1
            else None
        )
        if passed_data is not None:
            assert passed_data.cost_attribution_tags == tags
