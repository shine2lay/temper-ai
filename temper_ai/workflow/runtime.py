"""Shared workflow runtime pipeline.

Extracts the common load -> validate -> adapt -> compile -> execute -> cleanup
pipeline that both the CLI ``run()`` and ``WorkflowRunner.run()`` duplicate.

Each consumer keeps its unique responsibilities:
- CLI: Click args, Rich output, dashboard, --autonomous, Gantt charts
- WorkflowRunner: WorkflowRunResult packaging, on_event callback

This module provides the shared skeleton so both paths always validate,
lifecycle-adapt, and compile identically.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

# Lazy-imported in _emit_lifecycle_event to avoid import fan-out
_ObservabilityEvent: Optional[type] = None


@dataclass
class RuntimeConfig:
    """Configuration for WorkflowRuntime."""

    config_root: str = "configs"
    trigger_type: str = "cli"
    verbose: bool = False
    db_path: str = ".meta-autonomous/observability.db"
    tracker_backend_factory: Optional[Callable] = None


@dataclass
class InfrastructureBundle:
    """Bundle of infrastructure components created during setup."""

    config_loader: Any = None
    tool_registry: Any = None
    tracker: Any = None
    event_bus: Optional[Any] = None


class WorkflowRuntime:
    """Shared pipeline: load -> validate -> adapt -> compile -> execute -> cleanup.

    This is the canonical execution pipeline for MAF workflows.
    Both CLI and WorkflowRunner delegate to this class.
    """

    def __init__(
        self,
        config: Optional[RuntimeConfig] = None,
        event_bus: Optional[Any] = None,
        workflow_id: Optional[str] = None,
    ) -> None:
        self.config = config or RuntimeConfig()
        self._event_bus = event_bus
        self._workflow_id = workflow_id

    def load_config(
        self,
        workflow_path: str,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Load and validate workflow configuration.

        Args:
            workflow_path: Path to workflow YAML (absolute or relative
                to config_root).
            input_data: Optional pre-loaded input dict. If None, no
                inputs are used.

        Returns:
            Tuple of (workflow_config, inputs).

        Raises:
            FileNotFoundError: If workflow file does not exist.
            ValueError: If workflow config is invalid YAML.
        """
        workflow_file = self._resolve_path(workflow_path)

        with open(workflow_file) as f:
            workflow_config: Dict[str, Any] = yaml.safe_load(f)

        if not isinstance(workflow_config, dict):
            raise ValueError(
                f"Workflow config must be a YAML mapping, "
                f"got {type(workflow_config).__name__}"
            )

        inputs = dict(input_data) if input_data else {}

        from temper_ai.observability.constants import EVENT_CONFIG_LOADED
        self._emit_lifecycle_event(EVENT_CONFIG_LOADED, {
            "workflow_path": str(workflow_file),
            "stage_count": len(
                workflow_config.get("workflow", {}).get("stages", []),
            ),
        })

        return workflow_config, inputs

    def adapt_lifecycle(
        self,
        workflow_config: Dict[str, Any],
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
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
            adapted: Dict[str, Any] = adapter.adapt(workflow_config, inputs)
            logger.info("Lifecycle adaptation applied")

            from temper_ai.observability.constants import EVENT_LIFECYCLE_ADAPTED
            self._emit_lifecycle_event(EVENT_LIFECYCLE_ADAPTED, {
                "status": "adapted",
            })

            return adapted
        except ImportError:
            logger.debug("Lifecycle modules not available, skipping adaptation")
            return workflow_config
        except Exception as exc:  # noqa: BLE001 -- lifecycle is optional
            logger.warning("Lifecycle adaptation failed: %s", exc)
            return workflow_config

    def setup_infrastructure(
        self,
        event_bus: Optional[Any] = None,
    ) -> InfrastructureBundle:
        """Create infrastructure components (loader, registry, tracker).

        Args:
            event_bus: Optional pre-existing event bus for tracker.

        Returns:
            InfrastructureBundle with config_loader, tool_registry, tracker.
        """
        from temper_ai.tools.registry import ToolRegistry
        from temper_ai.workflow.config_loader import ConfigLoader

        config_loader = ConfigLoader(config_root=self.config.config_root)
        tool_registry = ToolRegistry(auto_discover=True)

        tracker = self._create_tracker(event_bus)

        return InfrastructureBundle(
            config_loader=config_loader,
            tool_registry=tool_registry,
            tracker=tracker,
            event_bus=event_bus,
        )

    def compile(
        self,
        workflow_config: Dict[str, Any],
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
        self._emit_lifecycle_event(EVENT_WORKFLOW_COMPILING, {
            "engine": engine_name,
        })

        compiled = engine.compile(workflow_config)

        self._emit_lifecycle_event(EVENT_WORKFLOW_COMPILED, {
            "engine": engine_name,
        })

        return engine, compiled

    def build_state(
        self,
        inputs: Dict[str, Any],
        infra: InfrastructureBundle,
        workflow_id: str,
        **extras: Any,
    ) -> Dict[str, Any]:
        """Build the initial workflow state dict.

        Args:
            inputs: Input data for the workflow.
            infra: Infrastructure bundle.
            workflow_id: Unique workflow execution ID.
            **extras: Optional keys forwarded to state. Common keys:
                show_details, detail_console, stream_callback,
                workspace, run_id, workflow_name.

        Returns:
            State dict ready for ``compiled.invoke(state)``.
        """
        state: Dict[str, Any] = {
            "workflow_inputs": inputs,
            "tracker": infra.tracker,
            "config_loader": infra.config_loader,
            "tool_registry": infra.tool_registry,
            "workflow_id": workflow_id,
            "show_details": extras.get("show_details", False),
            "detail_console": extras.get("detail_console"),
            "stream_callback": extras.get("stream_callback"),
        }
        _OPTIONAL_KEYS = {"workspace": "workspace_root", "run_id": "run_id",
                          "workflow_name": "workflow_name"}
        for key, state_key in _OPTIONAL_KEYS.items():
            value = extras.get(key)
            if value is not None:
                state[state_key] = value
        return state

    def execute(
        self,
        compiled: Any,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a compiled workflow with the given state.

        Args:
            compiled: Compiled workflow from ``compile()``.
            state: Workflow state from ``build_state()``.

        Returns:
            Final workflow state dict.
        """
        result: Dict[str, Any] = compiled.invoke(state)
        return result

    def cleanup(self, engine: Any) -> None:
        """Clean up engine resources (tool executor shutdown).

        Args:
            engine: Engine instance to clean up.
        """
        if hasattr(engine, "tool_executor") and engine.tool_executor:
            try:
                engine.tool_executor.shutdown()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error during tool executor shutdown: %s", exc)

    # ── helpers ───────────────────────────────────────────────────────

    def _resolve_path(self, workflow_path: str) -> Path:
        """Resolve workflow path, checking config_root if not absolute."""
        path = Path(workflow_path)
        if path.is_absolute() and path.exists():
            return path

        config_path = Path(self.config.config_root) / workflow_path
        if config_path.exists():
            return config_path

        if path.exists():
            return path

        raise FileNotFoundError(f"Workflow file not found: {workflow_path}")

    def _emit_lifecycle_event(
        self,
        event_type: str,
        data: Dict[str, Any],
    ) -> None:
        """Emit a lifecycle event via the event bus.

        These events cover pre-execution pipeline phases (config loading,
        lifecycle adaptation, compilation) that occur before the tracker
        opens its workflow scope.

        Args:
            event_type: Event type constant from observability.constants.
            data: Event payload dict.
        """
        if self._event_bus is None:
            return

        global _ObservabilityEvent  # noqa: PLW0603
        if _ObservabilityEvent is None:
            from temper_ai.observability.event_bus import (
                ObservabilityEvent as _OE,
            )
            _ObservabilityEvent = _OE

        event = _ObservabilityEvent(
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            data=data,
            workflow_id=self._workflow_id,
        )
        self._event_bus.emit(event)

    def _create_tracker(self, event_bus: Optional[Any] = None) -> Any:
        """Create ExecutionTracker with optional event bus."""
        from temper_ai.observability.tracker import ExecutionTracker

        if self.config.tracker_backend_factory is not None:
            backend = self.config.tracker_backend_factory()
            return ExecutionTracker(backend=backend, event_bus=event_bus)

        if event_bus is not None:
            return ExecutionTracker(event_bus=event_bus)

        return ExecutionTracker()
