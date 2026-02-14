"""
Workflow execution service for dashboard.

Provides async workflow execution without blocking the FastAPI event loop.
Integrates with existing observability backend for progress tracking.
"""
import asyncio
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

# Keys from WorkflowStateDict that hold non-serializable infrastructure objects
_NON_SERIALIZABLE_KEYS = frozenset({
    "tracker",
    "tool_registry",
    "config_loader",
    "visualizer",
    "detail_console",
    "stream_callback",
})


def _sanitize_workflow_result(result: Any) -> Optional[Dict[str, Any]]:
    """Strip non-serializable infrastructure objects from workflow result.

    The LangGraph state dict contains objects like ExecutionTracker,
    ConfigLoader, ToolRegistry, and Rich Console that cannot be
    JSON-serialized.  This extracts only the serializable portions.
    """
    if not isinstance(result, dict):
        return None

    sanitized: Dict[str, Any] = {}
    for key, value in result.items():
        if key in _NON_SERIALIZABLE_KEYS:
            continue
        # Best-effort: skip values that aren't JSON-safe
        try:
            json.dumps(value)
            sanitized[key] = value
        except (TypeError, ValueError, OverflowError):
            logger.debug("Skipping non-serializable key '%s' in workflow result", key)
    return sanitized


# Execution status constants
class ExecutionStatus(str, Enum):
    """Workflow execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowExecutionMetadata:
    """Metadata for a workflow execution tracked in memory."""

    def __init__(
        self,
        execution_id: str,
        workflow_path: str,
        workflow_name: str,
        status: ExecutionStatus,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
    ):
        self.execution_id = execution_id
        self.workflow_path = workflow_path
        self.workflow_name = workflow_name
        self.status = status
        self.started_at = started_at
        self.completed_at = completed_at
        self.error_message = error_message
        self.workflow_id: Optional[str] = None
        self.result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "workflow_path": self.workflow_path,
            "workflow_name": self.workflow_name,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            "result": self.result,
        }


class WorkflowExecutionService:
    """Service for executing workflows in background without blocking FastAPI."""

    def __init__(
        self,
        backend: Any,
        event_bus: Any,
        config_root: str = "configs",
        max_workers: int = 4,
    ):
        """Initialize the execution service.

        Args:
            backend: ObservabilityBackend instance for tracking
            event_bus: ObservabilityEventBus for real-time updates
            config_root: Config directory root path
            max_workers: Max concurrent workflow executions
        """
        self.backend = backend
        self.event_bus = event_bus
        self.config_root = config_root

        # Thread pool for blocking workflow execution
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

        # In-memory execution tracking (execution_id -> metadata)
        self._executions: Dict[str, WorkflowExecutionMetadata] = {}
        self._lock = asyncio.Lock()

        logger.info(
            "WorkflowExecutionService initialized with max_workers=%d, config_root=%s",
            max_workers,
            config_root,
        )

    async def execute_workflow_async(
        self,
        workflow_path: str,
        input_data: Optional[Dict[str, Any]] = None,
        workspace: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> str:
        """Execute workflow in background and return execution ID immediately.

        Args:
            workflow_path: Path to workflow YAML file (relative to config_root)
            input_data: Input data dictionary for workflow

        Returns:
            execution_id: Unique ID for tracking this execution

        Raises:
            ValueError: If workflow_path is invalid
            FileNotFoundError: If workflow file doesn't exist
        """
        # Generate unique execution ID (use provided run_id as prefix if given)
        if run_id:
            execution_id = f"exec-{run_id}"
        else:
            execution_id = f"exec-{uuid.uuid4().hex[:12]}"

        # Resolve workflow path
        workflow_file = Path(self.config_root) / workflow_path
        if not workflow_file.exists():
            raise FileNotFoundError(f"Workflow file not found: {workflow_file}")

        # Load workflow config to get name
        with open(workflow_file) as f:
            workflow_config = yaml.safe_load(f)
        workflow_name = workflow_config.get("workflow", {}).get("name", workflow_file.stem)

        # Create execution metadata
        metadata = WorkflowExecutionMetadata(
            execution_id=execution_id,
            workflow_path=str(workflow_path),
            workflow_name=workflow_name,
            status=ExecutionStatus.PENDING,
        )

        async with self._lock:
            if execution_id in self._executions:
                raise ValueError(f"Execution ID already exists: {execution_id}")
            self._executions[execution_id] = metadata

        logger.info(
            "Starting workflow execution: id=%s, workflow=%s, name=%s",
            execution_id,
            workflow_path,
            workflow_name,
        )

        # Schedule background execution
        asyncio.create_task(
            self._run_workflow_background(execution_id, str(workflow_file), input_data or {}, workspace)
        )

        return execution_id

    async def _run_workflow_background(
        self,
        execution_id: str,
        workflow_path: str,
        input_data: Dict[str, Any],
        workspace: Optional[str] = None,
    ) -> None:
        """Run workflow in background thread (internal method).

        Updates execution metadata and handles errors gracefully.
        """
        metadata = self._executions[execution_id]

        try:
            # Update status to running
            metadata.status = ExecutionStatus.RUNNING
            metadata.started_at = datetime.now(timezone.utc)

            logger.info("Executing workflow in thread pool: %s", execution_id)

            # Execute in thread pool to avoid blocking event loop
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self._executor,
                self._execute_workflow_sync,
                workflow_path,
                input_data,
                execution_id,
                workspace,
            )

            # Update metadata with success
            metadata.status = ExecutionStatus.COMPLETED
            metadata.completed_at = datetime.now(timezone.utc)
            metadata.result = _sanitize_workflow_result(result)

            logger.info("Workflow execution completed: %s", execution_id)

        except Exception as e:  # noqa: BLE001
            # Update metadata with failure
            metadata.status = ExecutionStatus.FAILED
            metadata.completed_at = datetime.now(timezone.utc)
            metadata.error_message = str(e)

            logger.exception("Workflow execution failed: %s", execution_id)

    def _execute_workflow_sync(
        self,
        workflow_path: str,
        input_data: Dict[str, Any],
        execution_id: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute workflow synchronously (runs in thread pool).

        This is the blocking execution logic adapted from src/cli/main.py.

        Args:
            workflow_path: Absolute path to workflow YAML
            input_data: Workflow inputs
            execution_id: Execution ID for tracking

        Returns:
            Workflow result dictionary

        Raises:
            RuntimeError: On workflow execution failure
        """
        from src.compiler.config_loader import ConfigLoader
        from src.compiler.engine_registry import EngineRegistry
        from src.observability.tracker import ExecutionTracker
        from src.tools.registry import ToolRegistry

        # Load workflow config
        with open(workflow_path) as f:
            workflow_config = yaml.safe_load(f)

        # Initialize infrastructure
        config_loader = ConfigLoader(config_root=self.config_root)
        tool_registry = ToolRegistry(auto_discover=True)
        tracker = ExecutionTracker(event_bus=self.event_bus) if self.event_bus else ExecutionTracker()

        # Compile workflow
        registry = EngineRegistry()
        engine = registry.get_engine_from_config(
            workflow_config,
            tool_registry=tool_registry,
            config_loader=config_loader,
        )
        compiled = engine.compile(workflow_config)

        # Execute with tracking
        wf = workflow_config.get("workflow", {})
        workflow_name = wf.get("name", Path(workflow_path).stem)

        with tracker.track_workflow(
            workflow_name=workflow_name,
            workflow_config=workflow_config,
            trigger_type="dashboard",
            environment="dashboard",
        ) as workflow_id:
            # Store workflow_id so the API can return it to the frontend
            self._executions[execution_id].workflow_id = workflow_id

            state: Dict[str, Any] = {
                "workflow_inputs": input_data,
                "tracker": tracker,
                "config_loader": config_loader,
                "tool_registry": tool_registry,
                "workflow_id": workflow_id,
                "show_details": False,
                "detail_console": None,
                "stream_callback": None,
            }
            if workspace is not None:
                state["workspace_root"] = workspace
            result = compiled.invoke(state)

        # Cleanup
        if hasattr(engine, "tool_executor") and engine.tool_executor:
            try:
                engine.tool_executor.shutdown()
            except Exception as e:  # noqa: BLE001
                logger.debug("Error during tool executor shutdown: %s", e)

        return result

    async def get_execution_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Get execution status and metadata.

        Args:
            execution_id: Execution ID returned from execute_workflow_async

        Returns:
            Execution metadata dict, or None if not found
        """
        async with self._lock:
            metadata = self._executions.get(execution_id)
            if metadata:
                return metadata.to_dict()
            return None

    async def list_executions(
        self,
        status: Optional[ExecutionStatus] = None,
        limit: int = 100,
    ) -> list[Dict[str, Any]]:
        """List all tracked executions.

        Args:
            status: Filter by status (optional)
            limit: Max number of executions to return

        Returns:
            List of execution metadata dicts
        """
        async with self._lock:
            executions = list(self._executions.values())

        # Filter by status if specified
        if status:
            executions = [e for e in executions if e.status == status]

        # Sort by started_at (most recent first)
        executions.sort(
            key=lambda e: e.started_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        # Limit results
        executions = executions[:limit]

        return [e.to_dict() for e in executions]

    async def cancel_execution(self, execution_id: str) -> bool:
        """Cancel a running workflow execution.

        Args:
            execution_id: Execution ID to cancel

        Returns:
            True if cancelled, False if not found or already completed

        Note:
            Cancellation is best-effort and may not stop immediately.
        """
        async with self._lock:
            metadata = self._executions.get(execution_id)
            if not metadata:
                return False

            if metadata.status not in (ExecutionStatus.PENDING, ExecutionStatus.RUNNING):
                return False

            metadata.status = ExecutionStatus.CANCELLED
            metadata.completed_at = datetime.now(timezone.utc)
            metadata.error_message = "Execution cancelled by user"

        logger.info("Workflow execution cancelled: %s", execution_id)
        return True

    def shutdown(self) -> None:
        """Shutdown the service and wait for pending executions."""
        logger.info("Shutting down WorkflowExecutionService")
        self._executor.shutdown(wait=True)
