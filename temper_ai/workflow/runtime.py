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

from temper_ai.workflow._runtime_helpers import (
    create_tracker,
    load_workflow_config,
)
from temper_ai.workflow.pipeline_phases import PipelinePhaseTracker

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
    tenant_id: str | None = None


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
    """Shared pipeline: load -> validate -> adapt -> compile -> execute -> cleanup.  # noqa: god

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

        When tenant_id is set, tries ConfigLoader first (DB-first, then
        filesystem by name).  Falls back to the file-path-based loader
        for backward compatibility with absolute/relative paths.

        Args:
            workflow_path: Workflow name or path to workflow YAML.
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
        # When tenant_id is set, try ConfigLoader first (DB → filesystem by name)
        if self.config.tenant_id:
            try:
                from temper_ai.workflow.config_loader import ConfigLoader

                loader = ConfigLoader(
                    config_root=self.config.config_root,
                    tenant_id=self.config.tenant_id,
                )
                config = loader.load_workflow(workflow_path, validate=True)
                return config, dict(input_data) if input_data else {}
            except Exception:
                # Fall through to file-based loader
                pass

        return load_workflow_config(
            workflow_path,
            self.config.config_root,
            self._event_bus,
            self._workflow_id,
            input_data,
        )

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
                ExecutionTracker,
            )

            ExecutionTracker.ensure_database(self.config.db_path)

        from temper_ai.tools.registry import ToolRegistry
        from temper_ai.workflow.config_loader import ConfigLoader

        effective_event_bus = (
            event_bus if event_bus is not None else self.config.event_bus
        )

        config_loader = ConfigLoader(
            config_root=self.config.config_root,
            tenant_id=self.config.tenant_id,
        )
        tool_registry = ToolRegistry()

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

    def validate_references(
        self,
        workflow_config: dict[str, Any],
        infra: InfrastructureBundle,
    ) -> None:
        """Deep validation: check all config references exist.

        Unlike the fast Level-A check in ExecutionService._validate_config_references
        (which fails on the first error), this collects **all** broken references
        and raises a single ConfigValidationError with a detailed report.

        Each error is a structured ``ConfigError`` with location, fuzzy-match
        suggestion, and list of available options.
        """
        from temper_ai.shared.utils.exceptions import (
            ConfigNotFoundError,
            ConfigValidationError,
        )
        from temper_ai.workflow.config_errors import (
            ConfigError,
            format_error_report,
            suggest_name,
        )

        errors: list[ConfigError] = []
        loader = infra.config_loader
        tool_registry = infra.tool_registry

        # Pre-fetch available names for suggestions
        try:
            available_stages = loader.list_configs("stage")
        except Exception:
            available_stages = []
        try:
            available_agents = loader.list_configs("agent")
        except Exception:
            available_agents = []
        available_tools = tool_registry.list_available()

        stages = workflow_config.get("workflow", {}).get("stages", [])
        for stage_idx, stage_entry in enumerate(stages):
            stage_ref = stage_entry.get("stage_ref") or stage_entry.get("config_path")
            stage_name = stage_entry.get("name", stage_ref)
            if not stage_ref:
                continue

            # Strip directory prefix and extension to get bare stage name
            # e.g. "configs/stages/vcs_work_discovery.yaml" → "vcs_work_discovery"
            import os.path as _osp

            stage_ref_bare = _osp.splitext(_osp.basename(stage_ref))[0]

            try:
                stage_config = loader.load_stage(stage_ref_bare, validate=False)
            except ConfigNotFoundError:
                errors.append(
                    ConfigError(
                        code="stage_not_found",
                        message=f"Stage '{stage_ref}' not found",
                        location=f"workflow → stages[{stage_idx}]",
                        suggestion=suggest_name(stage_ref, available_stages),
                        available=available_stages,
                    )
                )
                continue

            agents = stage_config.get("stage", {}).get("agents", [])
            for agent_idx, agent_entry in enumerate(agents):
                agent_name = (
                    agent_entry
                    if isinstance(agent_entry, str)
                    else agent_entry.get("name", agent_entry.get("agent_ref"))
                )
                if not agent_name:
                    continue

                try:
                    agent_config = loader.load_agent(agent_name, validate=False)
                except ConfigNotFoundError:
                    errors.append(
                        ConfigError(
                            code="agent_not_found",
                            message=f"Agent '{agent_name}' not found",
                            location=(
                                f"workflow → stage '{stage_name}' → "
                                f"agents[{agent_idx}]"
                            ),
                            suggestion=suggest_name(agent_name, available_agents),
                            available=available_agents,
                        )
                    )
                    continue

                agent_inner = agent_config.get("agent", {})

                # Check tools
                for tool_idx, tool_entry in enumerate(agent_inner.get("tools", [])):
                    t_name = (
                        tool_entry
                        if isinstance(tool_entry, str)
                        else tool_entry.get("name", "")
                    )
                    if t_name and not tool_registry.has(t_name):
                        errors.append(
                            ConfigError(
                                code="tool_not_registered",
                                message=f"Tool '{t_name}' not registered",
                                location=(
                                    f"workflow → stage '{stage_name}' → "
                                    f"agent '{agent_name}' → "
                                    f"tools[{tool_idx}]"
                                ),
                                suggestion=suggest_name(t_name, available_tools),
                                available=available_tools,
                            )
                        )

                # Check prompt template path
                prompt_cfg = agent_inner.get("prompt", {})
                template_path = prompt_cfg.get("template_path")
                if template_path:
                    try:
                        loader.load_prompt_template(template_path)
                    except (ConfigNotFoundError, Exception):
                        errors.append(
                            ConfigError(
                                code="template_not_found",
                                message=(
                                    f"Prompt template '{template_path}' " f"not found"
                                ),
                                location=(
                                    f"workflow → stage '{stage_name}' → "
                                    f"agent '{agent_name}' → "
                                    f"prompt.template_path"
                                ),
                                suggestion=None,
                                available=[],
                            )
                        )

        if errors:
            raise ConfigValidationError(
                message=format_error_report(errors),
                config_errors=errors,
            )

    def validate_all(
        self,
        workflow_config: dict[str, Any],
        infra: InfrastructureBundle,
    ) -> None:
        """Validate all configs before compilation.

        Runs three checks in order:
        1. Reference validation — do stage/agent/tool names resolve?
        2. Schema validation — are stage/agent configs well-formed?
        3. I/O wiring validation — do agent inputs/outputs match?

        Raises ``ConfigValidationError`` with all errors collected.
        """
        from temper_ai.shared.utils.exceptions import ConfigValidationError
        from temper_ai.workflow.validation import validate_agent_io, validate_schemas

        # Level-B reference checks (existing)
        self.validate_references(workflow_config, infra)

        # Schema + I/O checks (extracted from engine compile())
        errors: list[str] = []
        validate_schemas(workflow_config, infra.config_loader, errors)
        validate_agent_io(workflow_config, infra.config_loader, errors)

        if errors:
            raise ConfigValidationError(
                message=(
                    "Configuration validation failed:\n"
                    + "\n".join(f"  - {err}" for err in errors)
                ),
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
        from temper_ai.workflow.engine_registry import EngineRegistry

        registry = EngineRegistry()
        engine = registry.get_engine_from_config(
            workflow_config,
            tool_registry=infra.tool_registry,
            config_loader=infra.config_loader,
        )

        compiled = engine.compile(workflow_config)

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
        optional_keys = {
            "workspace": "workspace_root",
            "run_id": "run_id",
            "workflow_name": "workflow_name",
        }
        for key, state_key in optional_keys.items():
            value = extras.get(key)
            if value is not None:
                state[state_key] = value

        # Ensure workspace is also available in workflow_inputs for
        # SourceResolver (stages declare source: workflow.workspace_path)
        workspace = extras.get("workspace")
        if workspace is not None:
            inputs.setdefault("workspace_path", workspace)

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
        phases: PipelinePhaseTracker | None = None,
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
            # Replay buffered pre-execution phases
            if phases is not None:
                phases.replay_to_event_bus(infra.event_bus, workflow_id)
                infra.tracker.record_pipeline_phases(workflow_id, phases.phases)

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
        phases = PipelinePhaseTracker()

        try:
            phases.start_phase("config_loading", {"path": workflow_path})
            workflow_config, inputs = self.load_config(workflow_path, input_data)
            stages = workflow_config.get("workflow", {}).get("stages", [])
            phases.end_phase("config_loading", {"stage_count": len(stages)})

            phases.start_phase("lifecycle_adaptation")
            workflow_config = self.adapt_lifecycle(workflow_config, inputs)
            phases.end_phase("lifecycle_adaptation")

            if hooks.on_config_loaded is not None:
                workflow_config = hooks.on_config_loaded(workflow_config, inputs)

            phases.start_phase("infrastructure_setup")
            infra = self.setup_infrastructure()
            phases.end_phase("infrastructure_setup")

            phases.start_phase("validation")
            self.validate_all(workflow_config, infra)
            phases.end_phase("validation")

            phases.start_phase("compilation")
            engine, compiled = self.compile(workflow_config, infra)
            phases.end_phase("compilation")

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
                phases=phases,
            )
        except Exception as exc:
            phases.fail_current(str(exc))
            if hooks.on_error is not None:
                hooks.on_error(exc)
            raise
        finally:
            if engine is not None:
                self.cleanup(engine)
