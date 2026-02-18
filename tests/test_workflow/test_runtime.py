"""Tests for WorkflowRuntime — shared execution pipeline."""
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.workflow.runtime import (
    InfrastructureBundle,
    RuntimeConfig,
    WorkflowRuntime,
)


@pytest.fixture
def tmp_workflow(tmp_path):
    """Create a minimal workflow YAML file."""
    config = {
        "workflow": {
            "name": "test_wf",
            "stages": ["s1"],
        }
    }
    path = tmp_path / "test.yaml"
    path.write_text(yaml.dump(config))
    return str(path)


@pytest.fixture
def runtime(tmp_path):
    """Create a WorkflowRuntime with config_root set to tmp_path."""
    cfg = RuntimeConfig(config_root=str(tmp_path))
    return WorkflowRuntime(config=cfg)


class TestLoadConfig:
    """Test WorkflowRuntime.load_config."""

    def test_load_absolute_path(self, tmp_workflow):
        """Test loading from absolute path."""
        rt = WorkflowRuntime()
        wf_config, inputs = rt.load_config(tmp_workflow)
        assert wf_config["workflow"]["name"] == "test_wf"
        assert inputs == {}

    def test_load_with_input_data(self, tmp_workflow):
        """Test loading with pre-loaded inputs."""
        rt = WorkflowRuntime()
        wf_config, inputs = rt.load_config(
            tmp_workflow, input_data={"topic": "AI"}
        )
        assert inputs == {"topic": "AI"}

    def test_load_relative_to_config_root(self, tmp_path):
        """Test loading from config_root-relative path."""
        config = {"workflow": {"name": "rel_wf", "stages": ["s1"]}}
        (tmp_path / "workflows").mkdir()
        wf_file = tmp_path / "workflows" / "demo.yaml"
        wf_file.write_text(yaml.dump(config))

        rt = WorkflowRuntime(RuntimeConfig(config_root=str(tmp_path)))
        wf_config, _ = rt.load_config("workflows/demo.yaml")
        assert wf_config["workflow"]["name"] == "rel_wf"

    def test_load_missing_file_raises(self):
        """Test FileNotFoundError on missing file."""
        rt = WorkflowRuntime()
        with pytest.raises(FileNotFoundError):
            rt.load_config("/nonexistent/workflow.yaml")

    def test_load_invalid_yaml_raises(self, tmp_path):
        """Test ValueError on non-mapping YAML."""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("- just a list")
        rt = WorkflowRuntime(RuntimeConfig(config_root=str(tmp_path)))
        with pytest.raises(ValueError, match="YAML mapping"):
            rt.load_config(str(bad_file))


class TestAdaptLifecycle:
    """Test WorkflowRuntime.adapt_lifecycle."""

    def test_no_lifecycle_returns_unchanged(self):
        """Test config without lifecycle returns as-is."""
        rt = WorkflowRuntime()
        config = {"workflow": {"name": "x", "stages": ["s"]}}
        result = rt.adapt_lifecycle(config, {})
        assert result is config

    def test_lifecycle_disabled_returns_unchanged(self):
        """Test disabled lifecycle returns as-is."""
        rt = WorkflowRuntime()
        config = {
            "workflow": {
                "name": "x",
                "stages": ["s"],
                "lifecycle": {"enabled": False},
            }
        }
        result = rt.adapt_lifecycle(config, {})
        assert result is config

    @patch("src.workflow.runtime.LifecycleAdapter", create=True)
    def test_lifecycle_enabled_calls_adapt(self, _mock_adapter):
        """Test lifecycle adaptation is attempted when enabled."""
        rt = WorkflowRuntime()
        config = {
            "workflow": {
                "name": "x",
                "stages": ["s"],
                "lifecycle": {"enabled": True},
            }
        }
        # Will fail (mocked modules), but should not raise
        result = rt.adapt_lifecycle(config, {"topic": "test"})
        assert isinstance(result, dict)


class TestSetupInfrastructure:
    """Test WorkflowRuntime.setup_infrastructure."""

    def test_creates_bundle(self):
        """Test infrastructure bundle is created correctly."""
        rt = WorkflowRuntime()
        bundle = rt.setup_infrastructure()

        assert isinstance(bundle, InfrastructureBundle)
        assert bundle.config_loader is not None
        assert bundle.tool_registry is not None
        assert bundle.tracker is not None

    def test_passes_event_bus(self):
        """Test event bus is passed through to bundle."""
        bus = MagicMock()
        rt = WorkflowRuntime()
        bundle = rt.setup_infrastructure(event_bus=bus)
        assert bundle.event_bus is bus


class TestCompile:
    """Test WorkflowRuntime.compile."""

    @patch("src.workflow.engine_registry.EngineRegistry")
    def test_compile_returns_engine_and_compiled(self, mock_registry_cls):
        """Test compile returns (engine, compiled) tuple."""
        mock_engine = MagicMock()
        mock_compiled = MagicMock()
        mock_engine.compile.return_value = mock_compiled

        mock_registry = MagicMock()
        mock_registry.get_engine_from_config.return_value = mock_engine
        mock_registry_cls.return_value = mock_registry

        rt = WorkflowRuntime()
        infra = InfrastructureBundle(
            config_loader=MagicMock(),
            tool_registry=MagicMock(),
            tracker=MagicMock(),
        )
        config = {"workflow": {"stages": ["s1"]}}

        engine, compiled = rt.compile(config, infra)
        assert engine is mock_engine
        assert compiled is mock_compiled


class TestBuildState:
    """Test WorkflowRuntime.build_state."""

    def test_basic_state(self):
        """Test state has expected keys."""
        rt = WorkflowRuntime()
        infra = InfrastructureBundle(
            config_loader=MagicMock(),
            tool_registry=MagicMock(),
            tracker=MagicMock(),
        )
        state = rt.build_state(
            inputs={"topic": "AI"},
            infra=infra,
            workflow_id="wf-123",
        )
        assert state["workflow_inputs"] == {"topic": "AI"}
        assert state["workflow_id"] == "wf-123"
        assert state["tracker"] is infra.tracker

    def test_optional_keys(self):
        """Test optional keys are included when provided."""
        rt = WorkflowRuntime()
        infra = InfrastructureBundle(
            config_loader=MagicMock(),
            tool_registry=MagicMock(),
            tracker=MagicMock(),
        )
        state = rt.build_state(
            inputs={},
            infra=infra,
            workflow_id="wf-123",
            workspace="/tmp/ws",
            run_id="run-1",
            workflow_name="demo",
        )
        assert state["workspace_root"] == "/tmp/ws"
        assert state["run_id"] == "run-1"
        assert state["workflow_name"] == "demo"

    def test_no_workspace_key_when_none(self):
        """Test workspace_root not in state when not provided."""
        rt = WorkflowRuntime()
        infra = InfrastructureBundle(
            config_loader=MagicMock(),
            tool_registry=MagicMock(),
            tracker=MagicMock(),
        )
        state = rt.build_state(inputs={}, infra=infra, workflow_id="wf-1")
        assert "workspace_root" not in state


class TestExecute:
    """Test WorkflowRuntime.execute."""

    def test_execute_calls_invoke(self):
        """Test execute delegates to compiled.invoke."""
        rt = WorkflowRuntime()
        compiled = MagicMock()
        compiled.invoke.return_value = {"result": "ok"}

        result = rt.execute(compiled, {"inputs": {}})
        assert result == {"result": "ok"}
        compiled.invoke.assert_called_once_with({"inputs": {}})


class TestCleanup:
    """Test WorkflowRuntime.cleanup."""

    def test_cleanup_calls_shutdown(self):
        """Test cleanup shuts down tool executor."""
        rt = WorkflowRuntime()
        engine = MagicMock()
        engine.tool_executor = MagicMock()

        rt.cleanup(engine)
        engine.tool_executor.shutdown.assert_called_once()

    def test_cleanup_no_executor(self):
        """Test cleanup handles engine without tool_executor."""
        rt = WorkflowRuntime()
        engine = MagicMock(spec=[])  # No tool_executor attribute
        rt.cleanup(engine)  # Should not raise

        assert not hasattr(engine, "tool_executor")

    def test_cleanup_shutdown_error(self):
        """Test cleanup catches shutdown errors."""
        rt = WorkflowRuntime()
        engine = MagicMock()
        engine.tool_executor.shutdown.side_effect = RuntimeError("boom")
        rt.cleanup(engine)  # Should not raise

        engine.tool_executor.shutdown.assert_called_once()


class TestRuntimeConfig:
    """Test RuntimeConfig defaults."""

    def test_defaults(self):
        """Test default config values."""
        cfg = RuntimeConfig()
        assert cfg.config_root == "configs"
        assert cfg.trigger_type == "cli"
        assert cfg.verbose is False
        assert cfg.tracker_backend_factory is None

    def test_custom_values(self):
        """Test custom config values."""
        factory = lambda: MagicMock()  # noqa: E731
        cfg = RuntimeConfig(
            config_root="/custom",
            trigger_type="api",
            verbose=True,
            tracker_backend_factory=factory,
        )
        assert cfg.config_root == "/custom"
        assert cfg.trigger_type == "api"
        assert cfg.tracker_backend_factory is factory


class TestTrackerBackendFactory:
    """Test custom tracker backend factory."""

    def test_factory_used(self):
        """Test tracker_backend_factory is called when provided."""
        mock_backend = MagicMock()
        factory = MagicMock(return_value=mock_backend)

        rt = WorkflowRuntime(RuntimeConfig(tracker_backend_factory=factory))

        with patch("src.observability.tracker.ExecutionTracker") as mock_et:
            mock_et.return_value = MagicMock()
            bundle = rt.setup_infrastructure()

        factory.assert_called_once()
        mock_et.assert_called_once_with(backend=mock_backend, event_bus=None)
