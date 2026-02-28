"""Tests for temper_ai/tools/_executor_config.py.

Covers:
- ToolExecutorConfig dataclass defaults
- workspace_path property (Path when set, None when not)
- Custom values override defaults
"""

from pathlib import Path

from temper_ai.shared.constants.durations import (
    DEFAULT_TIMEOUT_SECONDS,
    RATE_LIMIT_WINDOW_SECOND,
)
from temper_ai.shared.constants.limits import MIN_WORKERS
from temper_ai.tools._executor_config import ToolExecutorConfig


class TestToolExecutorConfig:
    """Tests for ToolExecutorConfig dataclass."""

    def test_default_timeout(self):
        config = ToolExecutorConfig()
        assert config.default_timeout == DEFAULT_TIMEOUT_SECONDS

    def test_default_max_workers(self):
        config = ToolExecutorConfig()
        assert config.max_workers == MIN_WORKERS

    def test_default_max_concurrent_is_none(self):
        config = ToolExecutorConfig()
        assert config.max_concurrent is None

    def test_default_rate_limit_is_none(self):
        config = ToolExecutorConfig()
        assert config.rate_limit is None

    def test_default_rate_window(self):
        config = ToolExecutorConfig()
        assert config.rate_window == RATE_LIMIT_WINDOW_SECOND

    def test_default_rollback_manager_is_none(self):
        config = ToolExecutorConfig()
        assert config.rollback_manager is None

    def test_default_policy_engine_is_none(self):
        config = ToolExecutorConfig()
        assert config.policy_engine is None

    def test_default_approval_workflow_is_none(self):
        config = ToolExecutorConfig()
        assert config.approval_workflow is None

    def test_default_enable_auto_rollback_is_true(self):
        config = ToolExecutorConfig()
        assert config.enable_auto_rollback is True

    def test_default_workspace_root_is_none(self):
        config = ToolExecutorConfig()
        assert config.workspace_root is None

    def test_default_enable_tool_cache_is_false(self):
        config = ToolExecutorConfig()
        assert config.enable_tool_cache is False

    def test_workspace_path_returns_path_when_set(self):
        config = ToolExecutorConfig(workspace_root="/tmp/workspace")
        result = config.workspace_path
        assert isinstance(result, Path)
        assert str(result) == "/tmp/workspace"

    def test_workspace_path_returns_none_when_not_set(self):
        config = ToolExecutorConfig()
        assert config.workspace_path is None

    def test_custom_values_override_defaults(self):
        config = ToolExecutorConfig(
            default_timeout=300,
            max_workers=8,
            max_concurrent=10,
            rate_limit=100,
            enable_auto_rollback=False,
            enable_tool_cache=True,
            tool_cache_max_size=512,
            tool_cache_ttl=600,
        )
        assert config.default_timeout == 300
        assert config.max_workers == 8
        assert config.max_concurrent == 10
        assert config.rate_limit == 100
        assert config.enable_auto_rollback is False
        assert config.enable_tool_cache is True
        assert config.tool_cache_max_size == 512
        assert config.tool_cache_ttl == 600
