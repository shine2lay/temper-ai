"""Standalone WorkflowRunner for programmatic workflow execution.

Provides a high-level API that any Python program can embed to run
MAF workflows without requiring the full server or CLI.

Usage::

    runner = WorkflowRunner()
    result = runner.run("workflows/research.yaml", {"topic": "AI"})

    # With event callback:
    result = runner.run("workflows/research.yaml", inputs, on_event=print)
"""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class WorkflowRunnerConfig(BaseModel):
    """Configuration for WorkflowRunner."""

    config_root: str = "configs"
    workspace: Optional[str] = None
    show_details: bool = False
    trigger_type: str = "api"
    environment: str = "server"


class WorkflowRunResult(BaseModel):
    """Result of a workflow execution."""

    workflow_id: str
    workflow_name: str
    status: str  # "completed" | "failed"
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: datetime
    duration_seconds: float


class WorkflowRunner:
    """High-level API for running MAF workflows programmatically.

    Handles infrastructure setup, compilation, execution, and cleanup
    in a single synchronous ``run()`` call.
    """

    def __init__(
        self,
        config: Optional[WorkflowRunnerConfig] = None,
        event_bus: Optional[Any] = None,
    ) -> None:
        self.config = config or WorkflowRunnerConfig()
        self.event_bus = event_bus

    def run(
        self,
        workflow_path: str,
        input_data: Optional[Dict[str, Any]] = None,
        on_event: Optional[Callable] = None,
        run_id: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> WorkflowRunResult:
        """Execute a workflow synchronously and return the result.

        Args:
            workflow_path: Path to workflow YAML (absolute or relative to config_root).
            input_data: Input data dict for the workflow.
            on_event: Optional callback invoked for each ObservabilityEvent.
            run_id: Optional externally-provided run ID.
            workspace: Optional workspace root to restrict file operations.

        Returns:
            WorkflowRunResult with execution outcome.

        Raises:
            FileNotFoundError: If workflow file does not exist.
        """
        started_at = datetime.now(timezone.utc)
        sub_id: Optional[str] = None

        # Subscribe on_event callback to event bus
        if on_event is not None and self.event_bus is not None:
            sub_id = self.event_bus.subscribe(on_event)

        engine = None
        try:
            # Resolve workflow file
            workflow_file = self._resolve_workflow_path(workflow_path)

            with open(workflow_file) as f:
                workflow_config = yaml.safe_load(f)

            wf = workflow_config.get("workflow", {})
            workflow_name = wf.get("name", workflow_file.stem)

            # Setup infrastructure
            config_loader, tool_registry, tracker = self._setup_infrastructure()

            # Compile
            compiled, engine = self._compile(workflow_config, tool_registry, config_loader)

            # Execute with tracking
            effective_workspace = workspace or self.config.workspace
            result_data = self._execute(
                compiled=compiled,
                workflow_config=workflow_config,
                workflow_name=workflow_name,
                input_data=input_data or {},
                tracker=tracker,
                config_loader=config_loader,
                tool_registry=tool_registry,
                workspace=effective_workspace,
                run_id=run_id,
            )

            completed_at = datetime.now(timezone.utc)
            return WorkflowRunResult(
                workflow_id=result_data.get("workflow_id", ""),
                workflow_name=workflow_name,
                status="completed",
                result=self._sanitize_result(result_data),
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

        except FileNotFoundError:
            raise
        except Exception as exc:
            completed_at = datetime.now(timezone.utc)
            logger.exception("WorkflowRunner execution failed")
            return WorkflowRunResult(
                workflow_id="",
                workflow_name=workflow_path,
                status="failed",
                error_message=str(exc),
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=(completed_at - started_at).total_seconds(),
            )
        finally:
            # Cleanup event subscription
            if sub_id is not None and self.event_bus is not None:
                self.event_bus.unsubscribe(sub_id)
            # Cleanup engine
            if engine is not None:
                self._cleanup_engine(engine)

    def _resolve_workflow_path(self, workflow_path: str) -> Path:
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

    def _setup_infrastructure(self) -> tuple:
        """Initialize config loader, tool registry, and tracker.

        Returns:
            Tuple of (config_loader, tool_registry, tracker).
        """
        from src.observability.tracker import ExecutionTracker
        from src.tools.registry import ToolRegistry
        from src.workflow.config_loader import ConfigLoader

        config_loader = ConfigLoader(config_root=self.config.config_root)
        tool_registry = ToolRegistry(auto_discover=True)
        if self.event_bus is not None:
            tracker = ExecutionTracker(event_bus=self.event_bus)
        else:
            tracker = ExecutionTracker()
        return config_loader, tool_registry, tracker

    def _compile(
        self,
        workflow_config: Dict[str, Any],
        tool_registry: Any,
        config_loader: Any,
    ) -> tuple:
        """Compile workflow config into executable graph.

        Returns:
            Tuple of (compiled_workflow, engine).
        """
        from src.workflow.engine_registry import EngineRegistry

        registry = EngineRegistry()
        engine = registry.get_engine_from_config(
            workflow_config,
            tool_registry=tool_registry,
            config_loader=config_loader,
        )
        compiled = engine.compile(workflow_config)
        return compiled, engine

    def _execute(
        self,
        compiled: Any,
        workflow_config: Dict[str, Any],
        workflow_name: str,
        input_data: Dict[str, Any],
        tracker: Any,
        config_loader: Any,
        tool_registry: Any,
        workspace: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute compiled workflow with tracking."""
        from src.observability.tracker import WorkflowTrackingParams

        with tracker.track_workflow(WorkflowTrackingParams(
            workflow_name=workflow_name,
            workflow_config=workflow_config,
            trigger_type=self.config.trigger_type,
            environment=self.config.environment,
        )) as workflow_id:
            state: Dict[str, Any] = {
                "workflow_inputs": input_data,
                "tracker": tracker,
                "config_loader": config_loader,
                "tool_registry": tool_registry,
                "workflow_id": workflow_id,
                "show_details": self.config.show_details,
                "detail_console": None,
                "stream_callback": None,
            }
            if workspace is not None:
                state["workspace_root"] = workspace
            if run_id is not None:
                state["run_id"] = run_id

            result: Dict[str, Any] = compiled.invoke(state)
            result["workflow_id"] = workflow_id
            return result

    def _sanitize_result(self, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Strip non-serializable keys from result."""
        from src.interfaces.dashboard.execution_service import _sanitize_workflow_result

        return _sanitize_workflow_result(result)

    def _cleanup_engine(self, engine: Any) -> None:
        """Clean up engine resources."""
        if hasattr(engine, "tool_executor") and engine.tool_executor:
            try:
                engine.tool_executor.shutdown()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error during tool executor shutdown: %s", exc)
