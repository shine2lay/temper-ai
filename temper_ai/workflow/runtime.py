"""Shared workflow runtime pipeline.

Extracts the common load -> validate -> adapt -> compile -> execute -> cleanup
pipeline that both the CLI ``run()`` and ``WorkflowRunner.run()`` duplicate.

Each consumer keeps its unique responsibilities:
- CLI: Click args, Rich output, dashboard, --autonomous, Gantt charts
- WorkflowRunner: WorkflowRunResult packaging, on_event callback

This module provides the shared skeleton so both paths always validate,
lifecycle-adapt, and compile identically.

The ``run_pipeline()`` method is the single-call entry point that
encapsulates the full sequence.  ``ExecutionHooks`` lets callers inject
behaviour (CLI Rich output, planning pass, autonomous loop) without
forking the pipeline.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from temper_ai.workflow._runtime_helpers import (
    check_required_inputs,
    create_tracker,
    emit_lifecycle_event,
    resolve_path,
    validate_file_size,
    validate_schema,
    validate_structure,
)

logger = logging.getLogger(__name__)


def _create_temper_event_bus(workflow_config: dict[str, Any]) -> Any | None:
    """Create a TemperEventBus if event_bus is enabled in workflow config options.

    Args:
        workflow_config: Parsed workflow configuration dict.

    Returns:
        TemperEventBus instance if enabled, None otherwise.
    """
    wf = workflow_config.get("workflow", {})
    config = wf.get("config", {}) if isinstance(wf, dict) else {}
    event_bus_cfg = (
        config.get("event_bus")
        if isinstance(config, dict)
        else getattr(config, "event_bus", None)
    )
    if event_bus_cfg is None:
        return None

    enabled = (
        event_bus_cfg.get("enabled", False)
        if isinstance(event_bus_cfg, dict)
        else getattr(event_bus_cfg, "enabled", False)
    )
    if not enabled:
        return None

    persist = (
        event_bus_cfg.get("persist_events", True)
        if isinstance(event_bus_cfg, dict)
        else getattr(event_bus_cfg, "persist_events", True)
    )
    try:
        from temper_ai.events.event_bus import TemperEventBus

        return TemperEventBus(persist=persist)
    except ImportError:
        logger.debug("TemperEventBus not available, skipping event bus creation")
        return None


def _emit_workflow_completed(
    event_bus: Any,
    workflow_name: str | None,
    workflow_id: str | None,
) -> None:
    """Emit workflow.completed event via the event bus.

    Args:
        event_bus: TemperEventBus instance.
        workflow_name: Name of the completed workflow.
        workflow_id: Unique workflow execution ID.
    """
    from temper_ai.events.constants import EVENT_WORKFLOW_COMPLETED

    try:
        event_bus.emit(
            event_type=EVENT_WORKFLOW_COMPLETED,
            payload={"workflow_name": workflow_name, "status": "completed"},
            source_workflow_id=workflow_id,
        )
    except Exception as exc:
        logger.warning("Failed to emit workflow.completed event: %s", exc)


@dataclass
class RuntimeConfig:
    """Configuration for WorkflowRuntime."""

    config_root: str = "configs"
    trigger_type: str = "cli"
    verbose: bool = False
    db_path: str = ".meta-autonomous/observability.db"
    tracker_backend_factory: Callable | None = None
    environment: str = "development"
    initialize_database: bool = True
    event_bus: Any | None = None


@dataclass
class InfrastructureBundle:
    """Bundle of infrastructure components created during setup."""

    config_loader: Any = None
    tool_registry: Any = None
    tracker: Any = None
    event_bus: Any | None = None


@dataclass
class ExecutionHooks:
    """Optional hooks that callers inject into ``run_pipeline()``.

    Each hook is an optional callable invoked at a specific pipeline phase.
    Hooks let callers layer CLI Rich output, planning passes, autonomous
    loops, and optimization engines onto the shared pipeline without
    forking the execution flow.
    """

    on_config_loaded: Callable | None = None
    """(workflow_config, input_data) -> workflow_config.  Called after
    load_config + adapt_lifecycle, before compile.  Return a (possibly
    modified) workflow_config."""

    on_state_built: Callable | None = None
    """(state, infra) -> None.  Called after build_state, before execute.
    Mutate *state* in-place to wire CLI-specific overlays."""

    on_before_execute: Callable | None = None
    """(compiled, state) -> None.  Final chance before compiled.invoke()."""

    on_after_execute: Callable | None = None
    """(result, workflow_id) -> None.  Called after successful execution."""

    on_error: Callable | None = None
    """(exception) -> None.  Called when execution raises."""


@dataclass
class RunOptions:
    """Keyword-only options for a single pipeline execution."""

    workspace: str | None = None
    run_id: str | None = None
    show_details: bool = False


class WorkflowRuntime:
    """Shared pipeline: load -> validate -> adapt -> compile -> execute -> cleanup.

    This is the canonical execution pipeline for MAF workflows.
    Both CLI and WorkflowRunner delegate to this class.
    """

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        event_bus: Any | None = None,
        workflow_id: str | None = None,
    ) -> None:
        self.config = config or RuntimeConfig()
        self._event_bus = event_bus
        self._workflow_id = workflow_id

    def load_config(
        self,
        workflow_path: str,
        input_data: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Load and validate workflow configuration.

        Applies the full security pipeline: file size check, YAML parse,
        mapping check, structure validation (depth/nodes/circular refs),
        and Pydantic schema validation.

        Args:
            workflow_path: Path to workflow YAML (absolute or relative
                to config_root).
            input_data: Optional pre-loaded input dict. If None, no
                inputs are used.

        Returns:
            Tuple of (workflow_config, inputs).

        Raises:
            FileNotFoundError: If workflow file does not exist.
            ConfigValidationError: If file too large, structure invalid,
                or schema validation fails.
            ValueError: If workflow config is not a YAML mapping.
        """
        from temper_ai.shared.utils.exceptions import ConfigValidationError

        workflow_file = resolve_path(workflow_path, self.config.config_root)

        validate_file_size(workflow_file)

        try:
            with open(workflow_file, encoding="utf-8") as f:
                workflow_config: dict[str, Any] = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ConfigValidationError(
                f"YAML parsing failed for {workflow_file}: {exc}"
            )

        if workflow_config is None:
            raise ConfigValidationError("Empty workflow file")

        if not isinstance(workflow_config, dict):
            raise ValueError(
                f"Workflow config must be a YAML mapping, "
                f"got {type(workflow_config).__name__}"
            )

        validate_structure(workflow_config, workflow_file)
        validate_schema(workflow_config)

        inputs = dict(input_data) if input_data else {}

        from temper_ai.observability.constants import EVENT_CONFIG_LOADED

        emit_lifecycle_event(
            self._event_bus,
            self._workflow_id,
            EVENT_CONFIG_LOADED,
            {
                "workflow_path": str(workflow_file),
                "stage_count": len(
                    workflow_config.get("workflow", {}).get("stages", []),
                ),
            },
        )

        return workflow_config, inputs

    def load_input_file(self, input_path: str) -> dict[str, Any]:
        """Load an input YAML file with security checks.

        Args:
            input_path: Path to input YAML file.

        Returns:
            Parsed input dict (empty dict for empty files).

        Raises:
            FileNotFoundError: If input file does not exist.
            ConfigValidationError: If file too large or structure invalid.
        """
        from temper_ai.shared.utils.exceptions import ConfigValidationError

        path = Path(input_path)
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        validate_file_size(path)

        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ConfigValidationError(f"YAML parsing failed for {path}: {exc}")

        if data is None:
            return {}

        if not isinstance(data, dict):
            raise ConfigValidationError(
                f"Input file must be a YAML mapping, " f"got {type(data).__name__}"
            )

        validate_structure(data, path)
        return data

    # Keep as a static method for backward compatibility
    check_required_inputs = staticmethod(check_required_inputs)

    def adapt_lifecycle(
        self,
        workflow_config: dict[str, Any],
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply lifecycle adaptation if enabled in workflow config.

        Args:
            workflow_config: Parsed workflow configuration.
            inputs: Input data dict.

        Returns:
            Possibly-adapted workflow config (original if adaptation
            is disabled or fails).
        """
        wf = workflow_config.get("workflow", {})
        lifecycle_cfg = wf.get("lifecycle", {})
        if not lifecycle_cfg.get("enabled", False):
            return workflow_config

        try:
            from temper_ai.lifecycle.adapter import LifecycleAdapter
            from temper_ai.lifecycle.classifier import ProjectClassifier
            from temper_ai.lifecycle.profiles import ProfileRegistry
            from temper_ai.lifecycle.store import LifecycleStore

            store = LifecycleStore()
            registry = ProfileRegistry(
                config_dir=Path(self.config.config_root) / "lifecycle",
                store=store,
            )
            classifier = ProjectClassifier()
            adapter = LifecycleAdapter(
                profile_registry=registry,
                classifier=classifier,
                store=store,
            )
            adapted: dict[str, Any] = adapter.adapt(workflow_config, inputs)
            logger.info("Lifecycle adaptation applied")

            from temper_ai.observability.constants import EVENT_LIFECYCLE_ADAPTED

            emit_lifecycle_event(
                self._event_bus,
                self._workflow_id,
                EVENT_LIFECYCLE_ADAPTED,
                {"status": "adapted"},
            )

            return adapted
        except ImportError:
            logger.debug("Lifecycle modules not available, skipping adaptation")
            return workflow_config
        except Exception as exc:  # noqa: BLE001 -- lifecycle is optional
            logger.warning("Lifecycle adaptation failed: %s", exc)
            return workflow_config

    def setup_infrastructure(
        self,
        event_bus: Any | None = None,
    ) -> InfrastructureBundle:
        """Create infrastructure components (loader, registry, tracker).

        Args:
            event_bus: Optional pre-existing event bus for tracker.
                Falls back to ``self.config.event_bus`` when *None*.

        Returns:
            InfrastructureBundle with config_loader, tool_registry, tracker.
        """
        if self.config.initialize_database:
            from temper_ai.observability.tracker import (
                ExecutionTracker as _ET,
            )

            _ET.ensure_database(self.config.db_path)

        from temper_ai.tools.registry import ToolRegistry
        from temper_ai.workflow.config_loader import ConfigLoader

        effective_event_bus = (
            event_bus if event_bus is not None else self.config.event_bus
        )

        config_loader = ConfigLoader(config_root=self.config.config_root)
        tool_registry = ToolRegistry(auto_discover=True)

        tracker = create_tracker(
            self.config.tracker_backend_factory,
            effective_event_bus,
        )

        return InfrastructureBundle(
            config_loader=config_loader,
            tool_registry=tool_registry,
            tracker=tracker,
            event_bus=effective_event_bus,
        )

    def compile(
        self,
        workflow_config: dict[str, Any],
        infra: InfrastructureBundle,
    ) -> tuple[Any, Any]:
        """Compile workflow config into an executable graph.

        Args:
            workflow_config: Workflow configuration dict.
            infra: Infrastructure bundle from ``setup_infrastructure()``.

        Returns:
            Tuple of (engine, compiled_workflow).

        Raises:
            ValueError: If compilation fails.
        """
        from temper_ai.observability.constants import (
            EVENT_WORKFLOW_COMPILED,
            EVENT_WORKFLOW_COMPILING,
        )
        from temper_ai.workflow.engine_registry import EngineRegistry

        registry = EngineRegistry()
        engine = registry.get_engine_from_config(
            workflow_config,
            tool_registry=infra.tool_registry,
            config_loader=infra.config_loader,
        )

        engine_name = type(engine).__name__
        emit_lifecycle_event(
            self._event_bus,
            self._workflow_id,
            EVENT_WORKFLOW_COMPILING,
            {"engine": engine_name},
        )

        compiled = engine.compile(workflow_config)

        emit_lifecycle_event(
            self._event_bus,
            self._workflow_id,
            EVENT_WORKFLOW_COMPILED,
            {"engine": engine_name},
        )

        return engine, compiled

    def build_state(
        self,
        inputs: dict[str, Any],
        infra: InfrastructureBundle,
        workflow_id: str,
        workflow_config: dict[str, Any] | None = None,
        **extras: Any,
    ) -> dict[str, Any]:
        """Build the initial workflow state dict.

        Args:
            inputs: Input data for the workflow.
            infra: Infrastructure bundle.
            workflow_id: Unique workflow execution ID.
            workflow_config: Parsed workflow config -- used to create TemperEventBus
                when event_bus is enabled in config options.
            **extras: Optional keys forwarded to state. Common keys:
                show_details, detail_console, stream_callback,
                workspace, run_id, workflow_name.

        Returns:
            State dict ready for ``compiled.invoke(state)``.
        """
        state: dict[str, Any] = {
            "workflow_inputs": inputs,
            "tracker": infra.tracker,
            "config_loader": infra.config_loader,
            "tool_registry": infra.tool_registry,
            "workflow_id": workflow_id,
            "show_details": extras.get("show_details", False),
            "detail_console": extras.get("detail_console"),
            "stream_callback": extras.get("stream_callback"),
        }
        _OPTIONAL_KEYS = {
            "workspace": "workspace_root",
            "run_id": "run_id",
            "workflow_name": "workflow_name",
        }
        for key, state_key in _OPTIONAL_KEYS.items():
            value = extras.get(key)
            if value is not None:
                state[state_key] = value

        if workflow_config is not None:
            temper_event_bus = _create_temper_event_bus(workflow_config)
            if temper_event_bus is not None:
                state["event_bus"] = temper_event_bus
                infra.event_bus = temper_event_bus

            # Auto-inject total_stages and workflow_name from config
            stages = workflow_config.get("workflow", {}).get("stages", [])
            state.setdefault("total_stages", len(stages))
            wf_name = workflow_config.get("workflow", {}).get("name", "")
            state.setdefault("workflow_name", wf_name)

        return state

    def execute(
        self,
        compiled: Any,
        state: dict[str, Any],
        mode: Any | None = None,
    ) -> dict[str, Any]:
        """Execute a compiled workflow with the given state.

        Args:
            compiled: Compiled workflow from ``compile()``.
            state: Workflow state from ``build_state()``.
            mode: Optional ExecutionMode. STREAM mode falls back to ASYNC
                execution at the workflow level -- streaming happens at the
                LLM layer via stream_callback in state.

        Returns:
            Final workflow state dict.
        """
        from temper_ai.workflow.execution_engine import ExecutionMode

        if mode is ExecutionMode.STREAM:
            logger.warning(
                "ExecutionMode.STREAM requested but full pipeline streaming is not yet "
                "supported. Falling back to ASYNC mode. LLM-layer streaming remains "
                "active via stream_callback."
            )

        result: dict[str, Any] = compiled.invoke(state)

        event_bus = state.get("event_bus")
        if event_bus is not None:
            _emit_workflow_completed(
                event_bus=event_bus,
                workflow_name=state.get("workflow_name"),
                workflow_id=state.get("workflow_id"),
            )

        return result

    def cleanup(self, engine: Any) -> None:
        """Clean up engine resources (tool executor shutdown).

        Checks ``engine.tool_executor`` first, then falls back to
        ``engine.compiler.tool_executor`` (LangGraph engines store it there).

        Args:
            engine: Engine instance to clean up.
        """
        if hasattr(engine, "tool_executor") and engine.tool_executor:
            try:
                engine.tool_executor.shutdown()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error during tool executor shutdown: %s", exc)
        elif (
            hasattr(engine, "compiler")
            and hasattr(engine.compiler, "tool_executor")
            and engine.compiler.tool_executor
        ):
            try:
                engine.compiler.tool_executor.shutdown()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error during compiler tool executor shutdown: %s", exc)

    # ── run_pipeline helpers ────────────────────────────────────────────

    def _execute_in_tracker_scope(
        self,
        compiled: Any,
        workflow_config: dict[str, Any],
        workflow_path: str,
        inputs: dict[str, Any],
        infra: InfrastructureBundle,
        hooks: ExecutionHooks,
        opts: RunOptions,
    ) -> dict[str, Any]:
        """Build state, invoke hooks, and execute inside a tracker scope.

        Returns:
            Final workflow state dict with ``workflow_id`` injected.
        """
        from temper_ai.observability.tracker import WorkflowTrackingParams

        wf = workflow_config.get("workflow", {})
        workflow_name = wf.get("name", Path(workflow_path).stem)

        with infra.tracker.track_workflow(
            WorkflowTrackingParams(
                workflow_name=workflow_name,
                workflow_config=workflow_config,
                trigger_type=self.config.trigger_type,
                environment=self.config.environment,
            )
        ) as workflow_id:
            state = self.build_state(
                inputs,
                infra,
                workflow_id,
                workflow_config=workflow_config,
                workspace=opts.workspace,
                run_id=opts.run_id,
                show_details=opts.show_details,
                workflow_name=workflow_name,
            )

            if hooks.on_state_built is not None:
                hooks.on_state_built(state, infra)
            if hooks.on_before_execute is not None:
                hooks.on_before_execute(compiled, state)

            result = self.execute(compiled, state)
            result["workflow_id"] = workflow_id

        if hooks.on_after_execute is not None:
            hooks.on_after_execute(result, workflow_id)

        return result

    # ── run_pipeline (single-call entry point) ─────────────────────────

    def run_pipeline(
        self,
        workflow_path: str,
        input_data: dict[str, Any],
        hooks: ExecutionHooks | None = None,
        workspace: str | None = None,
        run_id: str | None = None,
        show_details: bool = False,
        mode: Any | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow through the full pipeline in one call.

        Encapsulates: load_config -> adapt_lifecycle -> [hook] ->
        setup_infrastructure -> compile -> build_state -> [hook] ->
        execute -> [hook] -> cleanup.

        Args:
            workflow_path: Path to workflow YAML (absolute or relative
                to config_root).
            input_data: Input data dict for the workflow.
            hooks: Optional ExecutionHooks to inject caller behaviour.
            workspace: Optional workspace root for file ops.
            run_id: Optional externally-provided run ID.
            show_details: Whether to show detailed progress.
            mode: Optional ExecutionMode. STREAM raises NotImplementedError
                immediately before any pipeline work begins.

        Returns:
            Final workflow state dict.

        Raises:
            FileNotFoundError: If workflow file does not exist.
            ConfigValidationError: If validation fails.
            NotImplementedError: If mode is ExecutionMode.STREAM.
        """
        from temper_ai.workflow.execution_engine import ExecutionMode

        if mode is ExecutionMode.STREAM:
            logger.warning(
                "ExecutionMode.STREAM requested but full pipeline streaming is not yet "
                "supported. Falling back to ASYNC mode. LLM-layer streaming remains "
                "active via stream_callback."
            )

        hooks = hooks or ExecutionHooks()
        engine = None

        try:
            workflow_config, inputs = self.load_config(workflow_path, input_data)
            workflow_config = self.adapt_lifecycle(workflow_config, inputs)
            if hooks.on_config_loaded is not None:
                workflow_config = hooks.on_config_loaded(workflow_config, inputs)

            infra = self.setup_infrastructure()
            engine, compiled = self.compile(workflow_config, infra)

            return self._execute_in_tracker_scope(
                compiled,
                workflow_config,
                workflow_path,
                inputs,
                infra,
                hooks,
                RunOptions(
                    workspace=workspace, run_id=run_id, show_details=show_details
                ),
            )
        except Exception as exc:
            if hooks.on_error is not None:
                hooks.on_error(exc)
            raise
        finally:
            if engine is not None:
                self.cleanup(engine)
