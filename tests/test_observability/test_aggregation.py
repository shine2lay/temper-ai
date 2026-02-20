"""Tests for metric aggregation.

Tests cover MetricAggregator.collect_agent_metrics(), set_agent_output(),
backend delegation, error resilience, and edge cases like empty metrics
and missing backend methods.
"""

from unittest.mock import Mock, patch

import pytest

from temper_ai.observability.metric_aggregator import MetricAggregator


class TestMetricAggregatorInitialization:
    """Tests for MetricAggregator initialization."""

    def test_init_with_backend(self):
        """Test initialization with backend."""
        mock_backend = Mock(spec=['set_agent_output', 'set_stage_output'])
        aggregator = MetricAggregator(backend=mock_backend)

        assert aggregator.backend is mock_backend
        assert aggregator.metric_registry is None

    def test_init_with_backend_and_registry(self):
        """Test initialization with backend and metric registry."""
        mock_backend = Mock(spec=['set_agent_output', 'set_stage_output'])
        mock_registry = Mock(spec=['collect_all'])

        aggregator = MetricAggregator(
            backend=mock_backend,
            metric_registry=mock_registry
        )

        assert aggregator.backend is mock_backend
        assert aggregator.metric_registry is mock_registry


class TestCollectAgentMetrics:
    """Tests for collect_agent_metrics method."""

    def test_collect_with_no_registry(self):
        """Test collect_agent_metrics returns early when no registry."""
        mock_backend = Mock(spec=['set_agent_output'])
        aggregator = MetricAggregator(backend=mock_backend)

        # Should return without error
        aggregator.collect_agent_metrics("agent-123")

        # Backend should not be called
        assert not mock_backend.method_calls

    def test_collect_with_registry_and_execution_found(self):
        """Test metric collection when execution is found."""
        mock_backend = Mock(spec=['set_agent_output', 'get_agent_execution'])
        mock_execution = Mock(spec=['id', 'agent_name'])
        mock_execution.id = "agent-123"
        mock_execution.agent_name = "test_agent"

        mock_backend.get_agent_execution.return_value = mock_execution

        mock_registry = Mock(spec=['collect_all'])
        mock_registry.collect_all.return_value = {
            "accuracy": 0.95,
            "latency": 1.23,
            "throughput": 100.0
        }

        aggregator = MetricAggregator(
            backend=mock_backend,
            metric_registry=mock_registry
        )

        result = aggregator.collect_agent_metrics("agent-123")

        mock_backend.get_agent_execution.assert_called_once_with("agent-123")
        mock_registry.collect_all.assert_called_once_with(mock_execution)
        # collect_agent_metrics returns None (side-effect only method)
        assert result is None

    def test_collect_with_registry_execution_not_found(self):
        """Test metric collection when execution is not found."""
        mock_backend = Mock(spec=['set_agent_output', 'get_agent_execution'])
        mock_backend.get_agent_execution.return_value = None

        mock_registry = Mock(spec=['collect_all'])

        aggregator = MetricAggregator(
            backend=mock_backend,
            metric_registry=mock_registry
        )

        with patch('temper_ai.observability.metric_aggregator.logger') as mock_logger:
            aggregator.collect_agent_metrics("agent-123")

            mock_logger.debug.assert_called_once()
            assert "not found" in mock_logger.debug.call_args[0][0]

        # collect_all should not be called
        mock_registry.collect_all.assert_not_called()

    def test_collect_with_registry_no_get_method(self):
        """Test metric collection when backend has no get_agent_execution method."""
        mock_backend = Mock(spec=['set_agent_output'])
        # No get_agent_execution method

        mock_registry = Mock(spec=['collect_all'])

        aggregator = MetricAggregator(
            backend=mock_backend,
            metric_registry=mock_registry
        )

        # Should handle gracefully (execution will be None)
        result = aggregator.collect_agent_metrics("agent-123")

        mock_registry.collect_all.assert_not_called()
        assert result is None

    def test_collect_with_empty_metrics(self):
        """Test metric collection returns empty dict."""
        mock_backend = Mock(spec=['set_agent_output', 'get_agent_execution'])
        mock_execution = Mock(spec=['id'])
        mock_backend.get_agent_execution.return_value = mock_execution

        mock_registry = Mock(spec=['collect_all'])
        mock_registry.collect_all.return_value = {}

        aggregator = MetricAggregator(
            backend=mock_backend,
            metric_registry=mock_registry
        )

        # Should not log info for empty metrics
        with patch('temper_ai.observability.metric_aggregator.logger') as mock_logger:
            aggregator.collect_agent_metrics("agent-123")

            # Should not call info logger for empty metrics
            info_calls = [call for call in mock_logger.info.call_args_list
                         if "Collected" in str(call)]
            assert len(info_calls) == 0

    def test_collect_with_none_metrics(self):
        """Test metric collection returns None."""
        mock_backend = Mock(spec=['set_agent_output', 'get_agent_execution'])
        mock_execution = Mock(spec=['id'])
        mock_backend.get_agent_execution.return_value = mock_execution

        mock_registry = Mock(spec=['collect_all'])
        mock_registry.collect_all.return_value = None

        aggregator = MetricAggregator(
            backend=mock_backend,
            metric_registry=mock_registry
        )

        # Should handle None gracefully
        result = aggregator.collect_agent_metrics("agent-123")
        assert result is None
        mock_registry.collect_all.assert_called_once()

    def test_collect_exception_handling(self):
        """Test exception handling in metric collection."""
        mock_backend = Mock(spec=['set_agent_output', 'get_agent_execution'])
        mock_backend.get_agent_execution.side_effect = Exception("Database error")

        mock_registry = Mock(spec=['collect_all'])

        aggregator = MetricAggregator(
            backend=mock_backend,
            metric_registry=mock_registry
        )

        with patch('temper_ai.observability.metric_aggregator.logger') as mock_logger:
            # Should not crash
            aggregator.collect_agent_metrics("agent-123")

            mock_logger.warning.assert_called_once()
            assert "Failed to collect metrics" in mock_logger.warning.call_args[0][0]


class TestSetAgentOutput:
    """Tests for set_agent_output method."""

    def test_set_agent_output_minimal(self):
        """Test set_agent_output with minimal parameters."""
        mock_backend = Mock(spec=['set_agent_output'])
        aggregator = MetricAggregator(backend=mock_backend)

        output_data = {"result": "success", "value": 42}

        aggregator.set_agent_output(
            agent_id="agent-123",
            output_data=output_data
        )

        mock_backend.set_agent_output.assert_called_once_with(
            agent_id="agent-123",
            output_data=output_data,
            reasoning=None,
            confidence_score=None,
            total_tokens=None,
            prompt_tokens=None,
            completion_tokens=None,
            estimated_cost_usd=None,
            num_llm_calls=None,
            num_tool_calls=None
        )
        assert mock_backend.set_agent_output.call_count == 1

    def test_set_agent_output_full_parameters(self):
        """Test set_agent_output with all parameters."""
        mock_backend = Mock(spec=['set_agent_output'])
        aggregator = MetricAggregator(backend=mock_backend)

        output_data = {"result": "success"}

        aggregator.set_agent_output(
            agent_id="agent-456",
            output_data=output_data,
            reasoning="Based on analysis of X",
            confidence_score=0.95,
            total_tokens=1500,
            prompt_tokens=1000,
            completion_tokens=500,
            estimated_cost_usd=0.03,
            num_llm_calls=3,
            num_tool_calls=5
        )

        mock_backend.set_agent_output.assert_called_once_with(
            agent_id="agent-456",
            output_data=output_data,
            reasoning="Based on analysis of X",
            confidence_score=0.95,
            total_tokens=1500,
            prompt_tokens=1000,
            completion_tokens=500,
            estimated_cost_usd=0.03,
            num_llm_calls=3,
            num_tool_calls=5
        )
        assert mock_backend.set_agent_output.call_count == 1

    def test_set_agent_output_delegates_to_backend(self):
        """Test set_agent_output properly delegates to backend."""
        mock_backend = Mock(spec=['set_agent_output'])
        aggregator = MetricAggregator(backend=mock_backend)

        aggregator.set_agent_output(
            agent_id="agent-789",
            output_data={"status": "complete"}
        )

        assert mock_backend.set_agent_output.call_count == 1

    def test_set_agent_output_with_zero_tokens(self):
        """Test set_agent_output with zero token counts."""
        mock_backend = Mock(spec=['set_agent_output'])
        aggregator = MetricAggregator(backend=mock_backend)

        aggregator.set_agent_output(
            agent_id="agent-000",
            output_data={"cached": True},
            total_tokens=0,
            prompt_tokens=0,
            completion_tokens=0,
            estimated_cost_usd=0.0
        )

        call_kwargs = mock_backend.set_agent_output.call_args[1]
        assert call_kwargs["total_tokens"] == 0
        assert call_kwargs["estimated_cost_usd"] == 0.0


class TestSetStageOutput:
    """Tests for set_stage_output method."""

    def test_set_stage_output(self):
        """Test set_stage_output delegates to backend."""
        mock_backend = Mock(spec=['set_stage_output'])
        aggregator = MetricAggregator(backend=mock_backend)

        output_data = {
            "stage_result": "completed",
            "agents_executed": 3,
            "summary": "All agents succeeded"
        }

        aggregator.set_stage_output(
            stage_id="stage-123",
            output_data=output_data
        )

        mock_backend.set_stage_output.assert_called_once_with(
            stage_id="stage-123",
            output_data=output_data
        )
        assert mock_backend.set_stage_output.call_count == 1

    def test_set_stage_output_empty_data(self):
        """Test set_stage_output with empty dict."""
        mock_backend = Mock(spec=['set_stage_output'])
        aggregator = MetricAggregator(backend=mock_backend)

        aggregator.set_stage_output(
            stage_id="stage-456",
            output_data={}
        )

        mock_backend.set_stage_output.assert_called_once()
        assert mock_backend.set_stage_output.call_args[1]["output_data"] == {}


class TestBackendDelegation:
    """Tests for backend delegation patterns."""

    def test_all_methods_delegate_to_backend(self):
        """Test all public methods delegate to backend."""
        mock_backend = Mock(spec=['set_agent_output', 'set_stage_output'])
        aggregator = MetricAggregator(backend=mock_backend)

        # Call all methods
        aggregator.set_agent_output("agent-1", {"data": "test"})
        aggregator.set_stage_output("stage-1", {"data": "test"})

        assert mock_backend.set_agent_output.call_count == 1
        assert mock_backend.set_stage_output.call_count == 1

    def test_backend_method_signatures_preserved(self):
        """Test backend method signatures are preserved."""
        mock_backend = Mock(spec=['set_agent_output'])
        aggregator = MetricAggregator(backend=mock_backend)

        aggregator.set_agent_output(
            agent_id="agent-test",
            output_data={"test": "data"},
            reasoning="test reasoning",
            confidence_score=0.8,
            total_tokens=100
        )

        # Verify all parameters were passed
        call_kwargs = mock_backend.set_agent_output.call_args[1]
        assert call_kwargs["agent_id"] == "agent-test"
        assert call_kwargs["reasoning"] == "test reasoning"
        assert call_kwargs["confidence_score"] == 0.8
        assert call_kwargs["total_tokens"] == 100


class TestErrorResilience:
    """Tests for error handling and resilience."""

    def test_backend_error_in_set_agent_output(self):
        """Test error handling when backend raises exception."""
        mock_backend = Mock(spec=['set_agent_output'])
        mock_backend.set_agent_output.side_effect = Exception("Backend error")

        aggregator = MetricAggregator(backend=mock_backend)

        # Should propagate exception (no error handling in aggregator)
        with pytest.raises(Exception, match="Backend error"):
            aggregator.set_agent_output("agent-1", {"data": "test"})

    def test_backend_error_in_set_stage_output(self):
        """Test error handling when backend raises exception."""
        mock_backend = Mock(spec=['set_stage_output'])
        mock_backend.set_stage_output.side_effect = Exception("Backend error")

        aggregator = MetricAggregator(backend=mock_backend)

        # Should propagate exception (no error handling in aggregator)
        with pytest.raises(Exception, match="Backend error"):
            aggregator.set_stage_output("stage-1", {"data": "test"})

    def test_collect_metrics_continues_on_exception(self):
        """Test collect_agent_metrics handles exceptions without crashing."""
        mock_backend = Mock(spec=['get_agent_execution'])
        mock_backend.get_agent_execution.side_effect = Exception("Connection lost")

        mock_registry = Mock(spec=['collect_all'])

        aggregator = MetricAggregator(
            backend=mock_backend,
            metric_registry=mock_registry
        )

        # Should not crash, just log warning
        with patch('temper_ai.observability.metric_aggregator.logger') as mock_logger:
            result = aggregator.collect_agent_metrics("agent-123")

        # Registry should not be called after exception
        mock_registry.collect_all.assert_not_called()
        assert result is None
        assert mock_logger.warning.called


class TestMetricRegistryIntegration:
    """Tests for metric registry integration."""

    def test_registry_collect_all_called_with_execution(self):
        """Test registry collect_all is called with execution object."""
        mock_backend = Mock(spec=['get_agent_execution'])
        mock_execution = Mock()
        mock_execution.id = "agent-123"
        mock_backend.get_agent_execution.return_value = mock_execution

        mock_registry = Mock(spec=['collect_all'])
        mock_registry.collect_all.return_value = {"metric1": 1.0}

        aggregator = MetricAggregator(
            backend=mock_backend,
            metric_registry=mock_registry
        )

        aggregator.collect_agent_metrics("agent-123")

        # Verify registry was called with the execution object
        mock_registry.collect_all.assert_called_once()
        call_args = mock_registry.collect_all.call_args[0]
        assert call_args[0] is mock_execution

    def test_registry_multiple_metrics_logged(self):
        """Test multiple metrics are logged correctly."""
        mock_backend = Mock(spec=['get_agent_execution'])
        mock_execution = Mock()
        mock_backend.get_agent_execution.return_value = mock_execution

        mock_registry = Mock(spec=['collect_all'])
        mock_registry.collect_all.return_value = {
            "accuracy": 0.95,
            "precision": 0.92,
            "recall": 0.88,
            "f1_score": 0.90
        }

        aggregator = MetricAggregator(
            backend=mock_backend,
            metric_registry=mock_registry
        )

        with patch('temper_ai.observability.metric_aggregator.logger') as mock_logger:
            aggregator.collect_agent_metrics("agent-123")

            mock_logger.info.assert_called_once()
            log_message = mock_logger.info.call_args[0][0]
            assert "4 metrics" in log_message


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_output_data(self):
        """Test handling of empty output data."""
        mock_backend = Mock(spec=['set_agent_output'])
        aggregator = MetricAggregator(backend=mock_backend)

        aggregator.set_agent_output(
            agent_id="agent-empty",
            output_data={}
        )

        call_kwargs = mock_backend.set_agent_output.call_args[1]
        assert call_kwargs["output_data"] == {}

    def test_very_large_output_data(self):
        """Test handling of large output data."""
        mock_backend = Mock(spec=['set_agent_output'])
        aggregator = MetricAggregator(backend=mock_backend)

        large_data = {"items": [{"id": i, "value": f"value_{i}"} for i in range(1000)]}

        aggregator.set_agent_output(
            agent_id="agent-large",
            output_data=large_data
        )

        call_kwargs = mock_backend.set_agent_output.call_args[1]
        assert len(call_kwargs["output_data"]["items"]) == 1000

    def test_negative_token_counts(self):
        """Test handling of negative token counts (should pass through to backend)."""
        mock_backend = Mock(spec=['set_agent_output'])
        aggregator = MetricAggregator(backend=mock_backend)

        # Aggregator doesn't validate, just passes to backend
        aggregator.set_agent_output(
            agent_id="agent-negative",
            output_data={"test": "data"},
            total_tokens=-100
        )

        call_kwargs = mock_backend.set_agent_output.call_args[1]
        assert call_kwargs["total_tokens"] == -100

    def test_confidence_score_out_of_range(self):
        """Test handling of confidence score outside 0-1 range."""
        mock_backend = Mock(spec=['set_agent_output'])
        aggregator = MetricAggregator(backend=mock_backend)

        # Aggregator doesn't validate, just passes to backend
        aggregator.set_agent_output(
            agent_id="agent-conf",
            output_data={"test": "data"},
            confidence_score=1.5
        )

        call_kwargs = mock_backend.set_agent_output.call_args[1]
        assert call_kwargs["confidence_score"] == 1.5

    def test_none_agent_id(self):
        """Test handling of None agent_id."""
        mock_backend = Mock(spec=['set_agent_output'])
        aggregator = MetricAggregator(backend=mock_backend)

        # Aggregator should pass None through to backend
        aggregator.set_agent_output(
            agent_id=None,
            output_data={"test": "data"}
        )

        call_kwargs = mock_backend.set_agent_output.call_args[1]
        assert call_kwargs["agent_id"] is None
