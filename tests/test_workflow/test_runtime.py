"""Tests for WorkflowRuntime — shared execution pipeline."""

from unittest.mock import MagicMock, patch

import pytest
import yaml

from temper_ai.shared.utils.exceptions import ConfigValidationError
from temper_ai.workflow.runtime import (
    ExecutionHooks,
    InfrastructureBundle,
    RuntimeConfig,
    WorkflowRuntime,
)


def _valid_workflow_config() -> dict:
    """Return a schema-valid workflow config dict."""
    return {
        "workflow": {
            "name": "test_wf",
            "description": "Test workflow",
            "stages": [{"name": "s1", "stage_ref": "stages/s1.yaml"}],
            "error_handling": {
                "on_stage_failure": "halt",
                "max_stage_retries": 2,
                "escalation_policy": "log_and_notify",
                "enable_rollback": False,
            },
        }
    }


@pytest.fixture
def tmp_workflow(tmp_path):
    """Create a schema-valid workflow YAML file."""
    config = _valid_workflow_config()
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
        wf_config, inputs = rt.load_config(tmp_workflow, input_data={"topic": "AI"})
        assert inputs == {"topic": "AI"}

    def test_load_relative_to_config_root(self, tmp_path):
        """Test loading from config_root-relative path."""
        config = _valid_workflow_config()
        config["workflow"]["name"] = "rel_wf"
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

    @patch("temper_ai.lifecycle.adapter.LifecycleAdapter")
    @patch("temper_ai.lifecycle.classifier.ProjectClassifier")
    @patch("temper_ai.lifecycle.profiles.ProfileRegistry")
    @patch("temper_ai.lifecycle.store.LifecycleStore")
    def test_lifecycle_enabled_calls_adapt(
        self, _store, _registry, _classifier, mock_adapter
    ):
        """Test lifecycle adaptation is attempted when enabled."""
        rt = WorkflowRuntime()
        config = {
            "workflow": {
                "name": "x",
                "stages": ["s"],
                "lifecycle": {"enabled": True},
            }
        }
        result = rt.adapt_lifecycle(config, {"topic": "test"})
        # Verify the adapter was instantiated and adapt() was called
        mock_adapter.return_value.adapt.assert_called_once_with(
            config, {"topic": "test"}
        )
        assert result is mock_adapter.return_value.adapt.return_value


class TestSetupInfrastructure:
    """Test WorkflowRuntime.setup_infrastructure."""

    def test_creates_bundle(self):
        """Test infrastructure bundle is created correctly."""
        rt = WorkflowRuntime(RuntimeConfig(initialize_database=False))
        bundle = rt.setup_infrastructure()

        assert isinstance(bundle, InfrastructureBundle)
        assert bundle.config_loader is not None
        assert bundle.tool_registry is not None
        assert bundle.tracker is not None

    def test_passes_event_bus(self):
        """Test event bus is passed through to bundle."""
        bus = MagicMock()
        rt = WorkflowRuntime(RuntimeConfig(initialize_database=False))
        bundle = rt.setup_infrastructure(event_bus=bus)
        assert bundle.event_bus is bus


class TestCompile:
    """Test WorkflowRuntime.compile."""

    @patch("temper_ai.workflow.engine_registry.EngineRegistry")
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
        assert cfg.environment == "development"
        assert cfg.initialize_database is True
        assert cfg.event_bus is None
        assert cfg.tenant_id is None

    def test_custom_values(self):
        """Test custom config values."""
        factory = lambda: MagicMock()  # noqa: E731
        bus = MagicMock()
        cfg = RuntimeConfig(
            config_root="/custom",
            trigger_type="api",
            verbose=True,
            tracker_backend_factory=factory,
            environment="server",
            initialize_database=False,
            event_bus=bus,
        )
        assert cfg.config_root == "/custom"
        assert cfg.trigger_type == "api"
        assert cfg.tracker_backend_factory is factory
        assert cfg.environment == "server"
        assert cfg.initialize_database is False
        assert cfg.event_bus is bus

    def test_accepts_tenant_id(self):
        """RuntimeConfig accepts and stores tenant_id."""
        cfg = RuntimeConfig(tenant_id="my-tenant")
        assert cfg.tenant_id == "my-tenant"


class TestTrackerBackendFactory:
    """Test custom tracker backend factory."""

    def test_factory_used(self):
        """Test tracker_backend_factory is called when provided."""
        mock_backend = MagicMock()
        factory = MagicMock(return_value=mock_backend)

        rt = WorkflowRuntime(
            RuntimeConfig(
                tracker_backend_factory=factory,
                initialize_database=False,
            )
        )

        with patch("temper_ai.observability.tracker.ExecutionTracker") as mock_et:
            mock_et.return_value = MagicMock()
            rt.setup_infrastructure()

        factory.assert_called_once()
        mock_et.assert_called_once_with(backend=mock_backend, event_bus=None)


class TestLoadConfigSecurity:
    """Test load_config security validation (file size, structure, schema)."""

    def test_rejects_oversized_file(self, tmp_path):
        """Files exceeding MAX_CONFIG_SIZE are rejected."""
        big_file = tmp_path / "big.yaml"
        # Write a valid-looking YAML header followed by padding
        big_file.write_text("workflow:\n  name: big\n" + "x" * (11 * 1024 * 1024))

        rt = WorkflowRuntime(RuntimeConfig(config_root=str(tmp_path)))
        with pytest.raises(ConfigValidationError, match="too large"):
            rt.load_config(str(big_file))

    def test_rejects_deeply_nested_yaml(self, tmp_path):
        """Deeply nested structures are rejected by structure validation."""
        # Build a YAML string with 60 levels of nesting (limit is 50)
        nested = "value"
        for i in range(60):
            nested = {f"level_{i}": nested}
        config = {"workflow": nested}

        deep_file = tmp_path / "deep.yaml"
        deep_file.write_text(yaml.dump(config))

        rt = WorkflowRuntime(RuntimeConfig(config_root=str(tmp_path)))
        with pytest.raises(ConfigValidationError, match="nesting depth"):
            rt.load_config(str(deep_file))

    def test_rejects_invalid_schema(self, tmp_path):
        """Config that passes YAML parsing but fails Pydantic is rejected."""
        bad_schema = {"workflow": {"name": "test"}}  # Missing required fields
        bad_file = tmp_path / "bad_schema.yaml"
        bad_file.write_text(yaml.dump(bad_schema))

        rt = WorkflowRuntime(RuntimeConfig(config_root=str(tmp_path)))
        with pytest.raises(ConfigValidationError, match="schema validation"):
            rt.load_config(str(bad_file))

    def test_rejects_non_mapping_yaml(self, tmp_path):
        """Non-mapping YAML raises ValueError."""
        list_file = tmp_path / "list.yaml"
        list_file.write_text("- just\n- a\n- list")

        rt = WorkflowRuntime(RuntimeConfig(config_root=str(tmp_path)))
        with pytest.raises(ValueError, match="YAML mapping"):
            rt.load_config(str(list_file))

    def test_valid_config_passes_all_checks(self, tmp_path):
        """A valid config passes file size, structure, and schema checks."""
        config = _valid_workflow_config()
        path = tmp_path / "valid.yaml"
        path.write_text(yaml.dump(config))

        rt = WorkflowRuntime(RuntimeConfig(config_root=str(tmp_path)))
        wf_config, inputs = rt.load_config(str(path))
        assert wf_config["workflow"]["name"] == "test_wf"
        assert inputs == {}


class TestBuildStateAutoInject:
    """Test build_state auto-injection of total_stages and workflow_name."""

    def test_auto_injects_total_stages(self):
        """total_stages is auto-injected from workflow_config."""
        rt = WorkflowRuntime()
        infra = InfrastructureBundle(
            config_loader=MagicMock(),
            tool_registry=MagicMock(),
            tracker=MagicMock(),
        )
        wf_config = {
            "workflow": {
                "name": "test_wf",
                "stages": [
                    {"name": "s1", "stage_ref": "s1.yaml"},
                    {"name": "s2", "stage_ref": "s2.yaml"},
                ],
            }
        }
        state = rt.build_state(
            inputs={},
            infra=infra,
            workflow_id="wf-1",
            workflow_config=wf_config,
        )
        assert state["total_stages"] == 2
        assert state["workflow_name"] == "test_wf"

    def test_explicit_overrides_auto_inject(self):
        """Explicit workflow_name in extras takes precedence over auto-inject."""
        rt = WorkflowRuntime()
        infra = InfrastructureBundle(
            config_loader=MagicMock(),
            tool_registry=MagicMock(),
            tracker=MagicMock(),
        )
        wf_config = {
            "workflow": {
                "name": "auto_name",
                "stages": [{"name": "s1"}],
            }
        }
        state = rt.build_state(
            inputs={},
            infra=infra,
            workflow_id="wf-1",
            workflow_config=wf_config,
            workflow_name="explicit_name",
        )
        # Explicit workflow_name via extras was set first via _OPTIONAL_KEYS,
        # setdefault should not overwrite it
        assert state["workflow_name"] == "explicit_name"

    def test_no_auto_inject_without_workflow_config(self):
        """Without workflow_config, total_stages and workflow_name not set."""
        rt = WorkflowRuntime()
        infra = InfrastructureBundle(
            config_loader=MagicMock(),
            tool_registry=MagicMock(),
            tracker=MagicMock(),
        )
        state = rt.build_state(inputs={}, infra=infra, workflow_id="wf-1")
        assert "total_stages" not in state
        assert "workflow_name" not in state


class TestSetupInfrastructureDbInit:
    """Test setup_infrastructure with initialize_database."""

    @patch("temper_ai.observability.tracker.ExecutionTracker")
    def test_ensure_database_called(self, mock_et_class):
        """ensure_database is called when initialize_database=True."""
        mock_et_class.return_value = MagicMock()
        rt = WorkflowRuntime(RuntimeConfig(initialize_database=True))
        rt.setup_infrastructure()
        mock_et_class.ensure_database.assert_called_once()

    @patch("temper_ai.observability.tracker.ExecutionTracker")
    def test_ensure_database_skipped(self, mock_et_class):
        """ensure_database is NOT called when initialize_database=False."""
        mock_et_class.return_value = MagicMock()
        rt = WorkflowRuntime(RuntimeConfig(initialize_database=False))
        rt.setup_infrastructure()
        mock_et_class.ensure_database.assert_not_called()

    @patch("temper_ai.observability.tracker.ExecutionTracker")
    def test_config_event_bus_fallback(self, mock_et_class):
        """Config event_bus is used when no explicit event_bus passed."""
        mock_et_class.return_value = MagicMock()
        config_bus = MagicMock()
        rt = WorkflowRuntime(
            RuntimeConfig(
                initialize_database=False,
                event_bus=config_bus,
            )
        )
        bundle = rt.setup_infrastructure()
        assert bundle.event_bus is config_bus

    @patch("temper_ai.observability.tracker.ExecutionTracker")
    def test_explicit_event_bus_overrides_config(self, mock_et_class):
        """Explicit event_bus param overrides config.event_bus."""
        mock_et_class.return_value = MagicMock()
        config_bus = MagicMock()
        explicit_bus = MagicMock()
        rt = WorkflowRuntime(
            RuntimeConfig(
                initialize_database=False,
                event_bus=config_bus,
            )
        )
        bundle = rt.setup_infrastructure(event_bus=explicit_bus)
        assert bundle.event_bus is explicit_bus

    def test_setup_infrastructure_passes_tenant_id_to_config_loader(self):
        """tenant_id from RuntimeConfig reaches ConfigLoader."""
        rt = WorkflowRuntime(
            RuntimeConfig(initialize_database=False, tenant_id="test-tenant")
        )
        bundle = rt.setup_infrastructure()
        assert bundle.config_loader.tenant_id == "test-tenant"

    def test_setup_infrastructure_tenant_id_none_by_default(self):
        """ConfigLoader.tenant_id is None when not set in RuntimeConfig."""
        rt = WorkflowRuntime(RuntimeConfig(initialize_database=False))
        bundle = rt.setup_infrastructure()
        assert bundle.config_loader.tenant_id is None


class TestCleanupCompilerFallback:
    """Test cleanup with compiler.tool_executor fallback."""

    def test_compiler_tool_executor_fallback(self):
        """cleanup shuts down compiler.tool_executor when engine has none."""
        rt = WorkflowRuntime()
        engine = MagicMock(spec=["compiler"])
        engine.compiler = MagicMock(spec=["tool_executor"])
        engine.compiler.tool_executor = MagicMock()
        rt.cleanup(engine)
        engine.compiler.tool_executor.shutdown.assert_called_once()

    def test_compiler_fallback_error_handled(self):
        """cleanup handles errors in compiler.tool_executor.shutdown."""
        rt = WorkflowRuntime()
        engine = MagicMock(spec=["compiler"])
        engine.compiler = MagicMock(spec=["tool_executor"])
        engine.compiler.tool_executor = MagicMock()
        engine.compiler.tool_executor.shutdown.side_effect = RuntimeError("boom")
        rt.cleanup(engine)  # Should not raise
        engine.compiler.tool_executor.shutdown.assert_called_once()

    def test_engine_tool_executor_preferred_over_compiler(self):
        """engine.tool_executor is preferred over compiler.tool_executor."""
        rt = WorkflowRuntime()
        engine = MagicMock()
        engine.tool_executor = MagicMock()
        engine.compiler = MagicMock()
        engine.compiler.tool_executor = MagicMock()
        rt.cleanup(engine)
        engine.tool_executor.shutdown.assert_called_once()
        engine.compiler.tool_executor.shutdown.assert_not_called()


class TestExecutionHooks:
    """Test ExecutionHooks dataclass."""

    def test_defaults_are_none(self):
        """All hooks default to None."""
        hooks = ExecutionHooks()
        assert hooks.on_config_loaded is None
        assert hooks.on_state_built is None
        assert hooks.on_before_execute is None
        assert hooks.on_after_execute is None
        assert hooks.on_error is None

    def test_custom_hooks(self):
        """Hooks accept callables."""
        fn = MagicMock()
        hooks = ExecutionHooks(
            on_config_loaded=fn,
            on_state_built=fn,
            on_before_execute=fn,
            on_after_execute=fn,
            on_error=fn,
        )
        assert hooks.on_config_loaded is fn
        assert hooks.on_error is fn


class TestRunPipeline:
    """Test WorkflowRuntime.run_pipeline."""

    @patch("temper_ai.workflow.runtime.WorkflowRuntime.cleanup")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.execute")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.build_state")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.compile")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.setup_infrastructure")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.adapt_lifecycle")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.load_config")
    def test_run_pipeline_full_sequence(
        self,
        mock_load,
        mock_adapt,
        mock_setup,
        mock_compile,
        mock_build_state,
        mock_execute,
        mock_cleanup,
    ):
        """run_pipeline calls the full sequence in order."""
        wf_config = {"workflow": {"name": "test-wf", "stages": []}}
        mock_load.return_value = (wf_config, {"key": "val"})
        mock_adapt.return_value = wf_config

        mock_tracker = MagicMock()
        mock_tracker.track_workflow.return_value.__enter__ = MagicMock(
            return_value="wf-abc"
        )
        mock_tracker.track_workflow.return_value.__exit__ = MagicMock(
            return_value=False
        )
        mock_infra = MagicMock()
        mock_infra.tracker = mock_tracker
        mock_setup.return_value = mock_infra

        mock_engine = MagicMock()
        mock_compiled = MagicMock()
        mock_compile.return_value = (mock_engine, mock_compiled)

        mock_build_state.return_value = {"workflow_id": "wf-abc"}
        mock_execute.return_value = {"status": "completed"}

        rt = WorkflowRuntime(config=RuntimeConfig(initialize_database=False))
        result = rt.run_pipeline("test.yaml", {"key": "val"})

        assert result["status"] == "completed"
        assert result["workflow_id"] == "wf-abc"
        mock_load.assert_called_once()
        mock_adapt.assert_called_once()
        mock_setup.assert_called_once()
        mock_compile.assert_called_once()
        mock_build_state.assert_called_once()
        mock_execute.assert_called_once()
        mock_cleanup.assert_called_once_with(mock_engine)

    @patch("temper_ai.workflow.runtime.WorkflowRuntime.cleanup")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.execute")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.build_state")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.compile")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.setup_infrastructure")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.adapt_lifecycle")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.load_config")
    def test_on_config_loaded_hook(
        self,
        mock_load,
        mock_adapt,
        mock_setup,
        mock_compile,
        mock_build_state,
        mock_execute,
        mock_cleanup,
    ):
        """on_config_loaded hook can modify the workflow config."""
        original_config = {"workflow": {"name": "original", "stages": []}}
        modified_config = {"workflow": {"name": "modified", "stages": []}}

        mock_load.return_value = (original_config, {})
        mock_adapt.return_value = original_config

        mock_tracker = MagicMock()
        mock_tracker.track_workflow.return_value.__enter__ = MagicMock(
            return_value="wf-1"
        )
        mock_tracker.track_workflow.return_value.__exit__ = MagicMock(
            return_value=False
        )
        mock_infra = MagicMock()
        mock_infra.tracker = mock_tracker
        mock_setup.return_value = mock_infra

        mock_compile.return_value = (MagicMock(), MagicMock())
        mock_build_state.return_value = {"workflow_id": "wf-1"}
        mock_execute.return_value = {"status": "completed"}

        hook_fn = MagicMock(return_value=modified_config)
        hooks = ExecutionHooks(on_config_loaded=hook_fn)

        rt = WorkflowRuntime(config=RuntimeConfig(initialize_database=False))
        rt.run_pipeline("test.yaml", {}, hooks=hooks)

        hook_fn.assert_called_once_with(original_config, {})
        # compile should receive modified config
        mock_compile.assert_called_once_with(modified_config, mock_infra)

    @patch("temper_ai.workflow.runtime.WorkflowRuntime.cleanup")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.execute")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.build_state")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.compile")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.setup_infrastructure")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.adapt_lifecycle")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.load_config")
    def test_on_state_built_hook(
        self,
        mock_load,
        mock_adapt,
        mock_setup,
        mock_compile,
        mock_build_state,
        mock_execute,
        mock_cleanup,
    ):
        """on_state_built hook receives state and infra."""
        wf_config = {"workflow": {"name": "test", "stages": []}}
        mock_load.return_value = (wf_config, {})
        mock_adapt.return_value = wf_config

        mock_tracker = MagicMock()
        mock_tracker.track_workflow.return_value.__enter__ = MagicMock(
            return_value="wf-1"
        )
        mock_tracker.track_workflow.return_value.__exit__ = MagicMock(
            return_value=False
        )
        mock_infra = MagicMock()
        mock_infra.tracker = mock_tracker
        mock_setup.return_value = mock_infra

        mock_compile.return_value = (MagicMock(), MagicMock())
        state = {"workflow_id": "wf-1"}
        mock_build_state.return_value = state
        mock_execute.return_value = {"status": "completed"}

        hook_fn = MagicMock()
        hooks = ExecutionHooks(on_state_built=hook_fn)

        rt = WorkflowRuntime(config=RuntimeConfig(initialize_database=False))
        rt.run_pipeline("test.yaml", {}, hooks=hooks)

        hook_fn.assert_called_once_with(state, mock_infra)

    @patch("temper_ai.workflow.runtime.WorkflowRuntime.cleanup")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.execute")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.build_state")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.compile")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.setup_infrastructure")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.adapt_lifecycle")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.load_config")
    def test_on_after_execute_hook(
        self,
        mock_load,
        mock_adapt,
        mock_setup,
        mock_compile,
        mock_build_state,
        mock_execute,
        mock_cleanup,
    ):
        """on_after_execute hook receives result and workflow_id."""
        wf_config = {"workflow": {"name": "test", "stages": []}}
        mock_load.return_value = (wf_config, {})
        mock_adapt.return_value = wf_config

        mock_tracker = MagicMock()
        mock_tracker.track_workflow.return_value.__enter__ = MagicMock(
            return_value="wf-42"
        )
        mock_tracker.track_workflow.return_value.__exit__ = MagicMock(
            return_value=False
        )
        mock_infra = MagicMock()
        mock_infra.tracker = mock_tracker
        mock_setup.return_value = mock_infra

        mock_compile.return_value = (MagicMock(), MagicMock())
        mock_build_state.return_value = {"workflow_id": "wf-42"}
        mock_execute.return_value = {"status": "completed", "output": "done"}

        hook_fn = MagicMock()
        hooks = ExecutionHooks(on_after_execute=hook_fn)

        rt = WorkflowRuntime(config=RuntimeConfig(initialize_database=False))
        rt.run_pipeline("test.yaml", {}, hooks=hooks)

        hook_fn.assert_called_once()
        result_arg, wf_id_arg = hook_fn.call_args[0]
        assert result_arg["status"] == "completed"
        assert wf_id_arg == "wf-42"

    @patch("temper_ai.workflow.runtime.WorkflowRuntime.cleanup")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.setup_infrastructure")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.adapt_lifecycle")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.load_config")
    def test_on_error_hook(
        self,
        mock_load,
        mock_adapt,
        mock_setup,
        mock_cleanup,
    ):
        """on_error hook is called when pipeline raises."""
        wf_config = {"workflow": {"name": "test", "stages": []}}
        mock_load.return_value = (wf_config, {})
        mock_adapt.return_value = wf_config
        mock_setup.side_effect = ValueError("infra failed")

        hook_fn = MagicMock()
        hooks = ExecutionHooks(on_error=hook_fn)

        rt = WorkflowRuntime(config=RuntimeConfig(initialize_database=False))
        with pytest.raises(ValueError, match="infra failed"):
            rt.run_pipeline("test.yaml", {}, hooks=hooks)

        hook_fn.assert_called_once()
        assert isinstance(hook_fn.call_args[0][0], ValueError)

    @patch("temper_ai.workflow.runtime.WorkflowRuntime.cleanup")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.setup_infrastructure")
    @patch("temper_ai.workflow.runtime.WorkflowRuntime.load_config")
    def test_cleanup_called_on_error(
        self,
        mock_load,
        mock_setup,
        mock_cleanup,
    ):
        """cleanup is called even when pipeline raises (after compile)."""
        wf_config = {"workflow": {"name": "test", "stages": []}}
        mock_load.return_value = (wf_config, {})

        mock_tracker = MagicMock()
        mock_infra = MagicMock()
        mock_infra.tracker = mock_tracker
        mock_setup.return_value = mock_infra

        # compile succeeds but execute will fail
        mock_engine = MagicMock()
        with (
            patch.object(WorkflowRuntime, "adapt_lifecycle", return_value=wf_config),
            patch.object(
                WorkflowRuntime, "compile", return_value=(mock_engine, MagicMock())
            ),
            patch.object(WorkflowRuntime, "build_state", return_value={}),
            patch.object(WorkflowRuntime, "execute", side_effect=RuntimeError("boom")),
        ):

            mock_tracker.track_workflow.return_value.__enter__ = MagicMock(
                return_value="wf-1"
            )
            mock_tracker.track_workflow.return_value.__exit__ = MagicMock(
                return_value=False
            )

            rt = WorkflowRuntime(config=RuntimeConfig(initialize_database=False))
            with pytest.raises(RuntimeError, match="boom"):
                rt.run_pipeline("test.yaml", {})

        mock_cleanup.assert_called_once_with(mock_engine)
