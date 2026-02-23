"""Tests for src/observability/constants.py."""

from temper_ai.observability import constants


class TestPerformanceConstants:
    """Tests for performance monitoring constants."""

    def test_max_latency_samples_defined(self):
        """Test that MAX_LATENCY_SAMPLES has the expected value."""
        assert isinstance(constants.MAX_LATENCY_SAMPLES, int)
        assert constants.MAX_LATENCY_SAMPLES == 1000

    def test_max_slow_operations_defined(self):
        """Test that MAX_SLOW_OPERATIONS has the expected value."""
        assert isinstance(constants.MAX_SLOW_OPERATIONS, int)
        assert constants.MAX_SLOW_OPERATIONS == 100

    def test_default_cleanup_interval_defined(self):
        """Test that DEFAULT_CLEANUP_INTERVAL has the expected value."""
        assert isinstance(constants.DEFAULT_CLEANUP_INTERVAL, int)
        assert constants.DEFAULT_CLEANUP_INTERVAL == 1000

    def test_default_slow_threshold_ms_defined(self):
        """Test that DEFAULT_SLOW_THRESHOLD_MS has the expected value."""
        assert isinstance(constants.DEFAULT_SLOW_THRESHOLD_MS, float)
        assert constants.DEFAULT_SLOW_THRESHOLD_MS == 1000.0

    def test_ms_per_second_conversion(self):
        """Test that MS_PER_SECOND is correct."""
        assert hasattr(constants, "MS_PER_SECOND")
        assert constants.MS_PER_SECOND == 1000.0


class TestOperationThresholds:
    """Tests for operation threshold constants."""

    def test_default_thresholds_defined(self):
        """Test that DEFAULT_THRESHOLDS_MS is a non-empty dict."""
        assert isinstance(constants.DEFAULT_THRESHOLDS_MS, dict)
        assert len(constants.DEFAULT_THRESHOLDS_MS) >= 5

    def test_all_operation_thresholds_present(self):
        """Test that all expected operation types have thresholds."""
        expected_operations = [
            "llm_call",
            "tool_execution",
            "stage_execution",
            "agent_execution",
            "workflow_execution",
        ]

        for op in expected_operations:
            assert op in constants.DEFAULT_THRESHOLDS_MS

    def test_threshold_values_are_positive_floats(self):
        """Test that all threshold values are positive floats."""
        for op, threshold in constants.DEFAULT_THRESHOLDS_MS.items():
            assert isinstance(threshold, float), f"{op} threshold should be float"
            assert threshold > 0, f"{op} threshold should be positive"

    def test_threshold_ordering_makes_sense(self):
        """Test that thresholds increase with operation complexity."""
        thresholds = constants.DEFAULT_THRESHOLDS_MS

        # LLM calls should be faster than tool executions
        assert thresholds["llm_call"] >= thresholds["tool_execution"]

        # Stages should take longer than individual operations
        assert thresholds["stage_execution"] > thresholds["tool_execution"]

        # Agents should take longer than stages
        assert thresholds["agent_execution"] > thresholds["stage_execution"]

        # Workflows should take longest
        assert thresholds["workflow_execution"] > thresholds["agent_execution"]


class TestBufferConstants:
    """Tests for buffer configuration constants."""

    def test_default_buffer_size_defined(self):
        """Test that DEFAULT_BUFFER_SIZE has the expected value."""
        assert isinstance(constants.DEFAULT_BUFFER_SIZE, int)
        assert constants.DEFAULT_BUFFER_SIZE == 100

    def test_default_buffer_timeout_defined(self):
        """Test that DEFAULT_BUFFER_TIMEOUT_SECONDS has the expected value."""
        assert isinstance(constants.DEFAULT_BUFFER_TIMEOUT_SECONDS, float)
        assert constants.DEFAULT_BUFFER_TIMEOUT_SECONDS == 5.0

    def test_max_retry_attempts_defined(self):
        """Test that MAX_RETRY_ATTEMPTS has the expected value."""
        assert isinstance(constants.MAX_RETRY_ATTEMPTS, int)
        assert constants.MAX_RETRY_ATTEMPTS == 3

    def test_retry_delay_seconds_defined(self):
        """Test that RETRY_DELAY_SECONDS has the expected value."""
        assert isinstance(constants.RETRY_DELAY_SECONDS, float)
        assert constants.RETRY_DELAY_SECONDS == 1.0


class TestAlertingConstants:
    """Tests for alerting threshold constants."""

    def test_default_alert_cooldown_defined(self):
        """Test that DEFAULT_ALERT_COOLDOWN_SECONDS has the expected value."""
        assert isinstance(constants.DEFAULT_ALERT_COOLDOWN_SECONDS, int)
        assert constants.DEFAULT_ALERT_COOLDOWN_SECONDS == 300

    def test_max_alert_history_defined(self):
        """Test that MAX_ALERT_HISTORY has the expected value."""
        assert isinstance(constants.MAX_ALERT_HISTORY, int)
        assert constants.MAX_ALERT_HISTORY == 1000

    def test_error_rate_alert_threshold_defined(self):
        """Test that DEFAULT_ERROR_RATE_ALERT_THRESHOLD is defined."""
        assert hasattr(constants, "DEFAULT_ERROR_RATE_ALERT_THRESHOLD")
        assert isinstance(constants.DEFAULT_ERROR_RATE_ALERT_THRESHOLD, float)
        assert 0 < constants.DEFAULT_ERROR_RATE_ALERT_THRESHOLD < 1

    def test_latency_alert_multiplier_defined(self):
        """Test that DEFAULT_LATENCY_ALERT_MULTIPLIER is defined."""
        assert hasattr(constants, "DEFAULT_LATENCY_ALERT_MULTIPLIER")
        assert isinstance(constants.DEFAULT_LATENCY_ALERT_MULTIPLIER, float)
        assert constants.DEFAULT_LATENCY_ALERT_MULTIPLIER > 1


class TestDisplayConstants:
    """Tests for display and formatting constants."""

    def test_default_trace_depth_defined(self):
        """Test that DEFAULT_TRACE_DEPTH has the expected value."""
        assert isinstance(constants.DEFAULT_TRACE_DEPTH, int)
        assert constants.DEFAULT_TRACE_DEPTH == 10

    def test_max_trace_display_items_defined(self):
        """Test that MAX_TRACE_DISPLAY_ITEMS has the expected value."""
        assert isinstance(constants.MAX_TRACE_DISPLAY_ITEMS, int)
        assert constants.MAX_TRACE_DISPLAY_ITEMS == 50

    def test_default_indent_size_defined(self):
        """Test that DEFAULT_INDENT_SIZE has the expected value."""
        assert isinstance(constants.DEFAULT_INDENT_SIZE, int)
        assert constants.DEFAULT_INDENT_SIZE == 2

    def test_sanitization_max_length_defined(self):
        """Test that SANITIZATION_MAX_LENGTH has the expected value."""
        assert isinstance(constants.SANITIZATION_MAX_LENGTH, int)
        assert constants.SANITIZATION_MAX_LENGTH == 10000

    def test_sanitization_replacement_defined(self):
        """Test that SANITIZATION_REPLACEMENT has the expected value."""
        assert isinstance(constants.SANITIZATION_REPLACEMENT, str)
        assert constants.SANITIZATION_REPLACEMENT == "***"


class TestDLQConstants:
    """Tests for dead letter queue constants."""

    def test_default_dlq_max_size_defined(self):
        """Test that DEFAULT_DLQ_MAX_SIZE has the expected value."""
        assert isinstance(constants.DEFAULT_DLQ_MAX_SIZE, int)
        assert constants.DEFAULT_DLQ_MAX_SIZE == 10000

    def test_default_dlq_retry_interval_defined(self):
        """Test that DEFAULT_DLQ_RETRY_INTERVAL has the expected value."""
        assert isinstance(constants.DEFAULT_DLQ_RETRY_INTERVAL, int)
        assert constants.DEFAULT_DLQ_RETRY_INTERVAL == 60

    def test_max_dlq_retry_attempts_defined(self):
        """Test that MAX_DLQ_RETRY_ATTEMPTS has the expected value."""
        assert isinstance(constants.MAX_DLQ_RETRY_ATTEMPTS, int)
        assert constants.MAX_DLQ_RETRY_ATTEMPTS == 5


class TestMeritScoreConstants:
    """Tests for merit score service constants."""

    def test_default_merit_decay_rate_defined(self):
        """Test that DEFAULT_MERIT_DECAY_RATE has the expected value."""
        assert isinstance(constants.DEFAULT_MERIT_DECAY_RATE, float)
        assert constants.DEFAULT_MERIT_DECAY_RATE == 0.95

    def test_default_merit_window_days_defined(self):
        """Test that DEFAULT_MERIT_WINDOW_DAYS has the expected value."""
        assert isinstance(constants.DEFAULT_MERIT_WINDOW_DAYS, int)
        assert constants.DEFAULT_MERIT_WINDOW_DAYS == 30

    def test_min_observations_for_merit_defined(self):
        """Test that MIN_OBSERVATIONS_FOR_MERIT has the expected value."""
        assert isinstance(constants.MIN_OBSERVATIONS_FOR_MERIT, int)
        assert constants.MIN_OBSERVATIONS_FOR_MERIT == 5


class TestDecisionTrackerConstants:
    """Tests for decision tracker constants."""

    def test_max_decision_history_defined(self):
        """Test that MAX_DECISION_HISTORY has the expected value."""
        assert isinstance(constants.MAX_DECISION_HISTORY, int)
        assert constants.MAX_DECISION_HISTORY == 10000

    def test_decision_context_max_length_defined(self):
        """Test that DECISION_CONTEXT_MAX_LENGTH has the expected value."""
        assert isinstance(constants.DECISION_CONTEXT_MAX_LENGTH, int)
        assert constants.DECISION_CONTEXT_MAX_LENGTH == 5000


class TestSQLBackendConstants:
    """Tests for SQL backend constants."""

    def test_default_query_limit_defined(self):
        """Test that DEFAULT_QUERY_LIMIT has the expected value."""
        assert isinstance(constants.DEFAULT_QUERY_LIMIT, int)
        assert constants.DEFAULT_QUERY_LIMIT == 1000

    def test_default_aggregation_interval_defined(self):
        """Test that DEFAULT_AGGREGATION_INTERVAL_SECONDS has the expected value."""
        assert isinstance(constants.DEFAULT_AGGREGATION_INTERVAL_SECONDS, int)
        assert constants.DEFAULT_AGGREGATION_INTERVAL_SECONDS == 60


class TestConstantsIntegrity:
    """Tests for overall constants module integrity."""

    def test_no_mutable_defaults_leaked(self):
        """Test that mutable defaults are not shared."""
        # Get two references to DEFAULT_THRESHOLDS_MS
        thresholds1 = constants.DEFAULT_THRESHOLDS_MS
        thresholds2 = constants.DEFAULT_THRESHOLDS_MS

        # They should be the same object (not a copy)
        assert thresholds1 is thresholds2

        # But modifying a copy shouldn't affect the original
        thresholds_copy = dict(constants.DEFAULT_THRESHOLDS_MS)
        thresholds_copy["test"] = 999.0
        assert "test" not in constants.DEFAULT_THRESHOLDS_MS

    def test_constants_are_module_level(self):
        """Test that constants are defined at module level."""
        # All constants should be accessible directly from the module
        import temper_ai.observability.constants as const_module

        assert hasattr(const_module, "MAX_LATENCY_SAMPLES")
        assert hasattr(const_module, "DEFAULT_BUFFER_SIZE")
        assert hasattr(const_module, "DEFAULT_ALERT_COOLDOWN_SECONDS")

    def test_numeric_constants_are_reasonable(self):
        """Test that numeric constants have reasonable values."""
        # Max sizes should be large but not absurdly so
        assert 10 <= constants.MAX_LATENCY_SAMPLES <= 100000
        assert 10 <= constants.MAX_SLOW_OPERATIONS <= 10000
        assert 10 <= constants.DEFAULT_BUFFER_SIZE <= 10000

        # Timeouts should be in reasonable ranges
        assert 0.1 <= constants.DEFAULT_BUFFER_TIMEOUT_SECONDS <= 3600
        assert 0.1 <= constants.RETRY_DELAY_SECONDS <= 60

        # Retry attempts should be reasonable
        assert 1 <= constants.MAX_RETRY_ATTEMPTS <= 10
        assert 1 <= constants.MAX_DLQ_RETRY_ATTEMPTS <= 20
