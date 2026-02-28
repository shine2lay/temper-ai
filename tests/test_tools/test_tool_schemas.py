"""Tests for temper_ai/tools/_schemas.py"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from temper_ai.tools._schemas import (
    RateLimits,
    SafetyCheck,
    ToolConfig,
    ToolConfigInner,
    ToolErrorHandlingConfig,
    ToolObservabilityConfig,
    ToolRequirements,
)

# ===========================================================================
# TestSafetyCheck
# ===========================================================================


class TestSafetyCheck:
    def test_minimal_valid(self):
        sc = SafetyCheck(name="content_filter")
        assert sc.name == "content_filter"
        assert sc.config == {}

    def test_with_config(self):
        sc = SafetyCheck(name="rate_check", config={"threshold": 100})
        assert sc.config == {"threshold": 100}


# ===========================================================================
# TestRateLimits
# ===========================================================================


class TestRateLimits:
    def test_defaults_are_positive(self):
        rl = RateLimits()
        assert rl.max_calls_per_minute > 0
        assert rl.max_calls_per_hour > 0
        assert rl.max_concurrent_requests > 0
        assert rl.cooldown_on_failure_seconds >= 0

    def test_zero_max_calls_per_minute_raises(self):
        with pytest.raises(ValidationError):
            RateLimits(max_calls_per_minute=0)

    def test_negative_max_calls_per_minute_raises(self):
        with pytest.raises(ValidationError):
            RateLimits(max_calls_per_minute=-1)

    def test_zero_max_calls_per_hour_raises(self):
        with pytest.raises(ValidationError):
            RateLimits(max_calls_per_hour=0)

    def test_zero_cooldown_on_failure_is_valid(self):
        rl = RateLimits(cooldown_on_failure_seconds=0)
        assert rl.cooldown_on_failure_seconds == 0


# ===========================================================================
# TestToolErrorHandlingConfig
# ===========================================================================


class TestToolErrorHandlingConfig:
    def test_defaults(self):
        cfg = ToolErrorHandlingConfig()
        assert cfg.max_retries >= 0
        assert cfg.retry_on_status_codes == []
        assert cfg.backoff_strategy == "ExponentialBackoff"
        assert cfg.timeout_is_retry is False

    def test_negative_max_retries_raises(self):
        with pytest.raises(ValidationError):
            ToolErrorHandlingConfig(max_retries=-1)

    def test_zero_max_retries_is_valid(self):
        cfg = ToolErrorHandlingConfig(max_retries=0)
        assert cfg.max_retries == 0


# ===========================================================================
# TestToolObservabilityConfig
# ===========================================================================


class TestToolObservabilityConfig:
    def test_defaults(self):
        cfg = ToolObservabilityConfig()
        assert cfg.log_inputs is True
        assert cfg.log_outputs is True
        assert cfg.log_full_response is False
        assert cfg.track_latency is True
        assert cfg.track_success_rate is True
        assert cfg.metrics == []

    def test_all_booleans_toggleable(self):
        cfg = ToolObservabilityConfig(
            log_inputs=False,
            log_outputs=False,
            log_full_response=True,
            track_latency=False,
            track_success_rate=False,
        )
        assert cfg.log_inputs is False
        assert cfg.log_outputs is False
        assert cfg.log_full_response is True
        assert cfg.track_latency is False
        assert cfg.track_success_rate is False


# ===========================================================================
# TestToolRequirements
# ===========================================================================


class TestToolRequirements:
    def test_defaults_all_false(self):
        req = ToolRequirements()
        assert req.requires_network is False
        assert req.requires_credentials is False
        assert req.requires_sandbox is False

    def test_all_true(self):
        req = ToolRequirements(
            requires_network=True,
            requires_credentials=True,
            requires_sandbox=True,
        )
        assert req.requires_network is True
        assert req.requires_credentials is True
        assert req.requires_sandbox is True


# ===========================================================================
# TestToolConfigInner
# ===========================================================================


class TestToolConfigInner:
    def test_minimal_valid(self):
        cfg = ToolConfigInner(
            name="my_tool",
            description="Does stuff",
            implementation="my.module.MyTool",
        )
        assert cfg.name == "my_tool"
        assert cfg.description == "Does stuff"
        assert cfg.implementation == "my.module.MyTool"

    def test_defaults_for_optional_fields(self):
        cfg = ToolConfigInner(
            name="my_tool",
            description="Does stuff",
            implementation="my.module.MyTool",
        )
        assert cfg.version == "1.0"
        assert cfg.category is None
        assert cfg.default_config == {}
        assert cfg.safety_checks == []

    def test_with_overridden_optional_fields(self):
        cfg = ToolConfigInner(
            name="my_tool",
            description="Full config",
            implementation="my.module.MyTool",
            version="2.0",
            category="utility",
            default_config={"timeout": 30},
        )
        assert cfg.version == "2.0"
        assert cfg.category == "utility"
        assert cfg.default_config == {"timeout": 30}


# ===========================================================================
# TestToolConfig
# ===========================================================================


class TestToolConfig:
    def test_wraps_tool_config_inner(self):
        inner = ToolConfigInner(
            name="my_tool",
            description="Does stuff",
            implementation="my.module.MyTool",
        )
        cfg = ToolConfig(tool=inner)
        assert cfg.tool is inner
        assert cfg.tool.name == "my_tool"
