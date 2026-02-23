"""
Workflow execution service — shared infrastructure.

Provides bounded-concurrency workflow execution via ThreadPoolExecutor,
in-memory run tracking, status queries, cancellation, RunStore persistence,
and graceful shutdown.  Used by Dashboard REST, MCP, and CrossWorkflowTrigger.
"""

import json
import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

EXECUTION_ID_LENGTH = 12

# Default max concurrent workflow executions
DEFAULT_MAX_WORKFLOW_WORKERS = 4


def _sanitize_workflow_result(result: Any) -> dict[str, Any] | None:
    """Strip non-serializable infrastructure objects from workflow result.

    The LangGraph state dict contains objects like ExecutionTracker,
    ConfigLoader, ToolRegistry, and Rich Console that cannot be
    JSON-serialized.  This extracts only the serializable portions.
    """
    from temper_ai.stage.executors.state_keys import StateKeys

    if not isinstance(result, dict):
        return None

    sanitized: dict[str, Any] = {}
    for key, value in result.items():
        if key in StateKeys.NON_SERIALIZABLE_KEYS:
            continue
        # Best-effort: skip values that aren't JSON-safe
        try:
            json.dumps(value)
            sanitized[key] = value
        except (TypeError, ValueError, OverflowError):
            logger.debug("Skipping non-serializable key '%s' in workflow result", key)
    return sanitized


# Execution status constants
class WorkflowExecutionStatus(str, Enum):
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
        status: WorkflowExecutionStatus,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error_message: str | None = None,
    ):
        self.execution_id = execution_id
        self.workflow_path = workflow_path
        self.workflow_name = workflow_name
        self.status = status
        self.started_at = started_at
        self.completed_at = completed_at
        self.error_message = error_message
        self.workflow_id: str | None = None
        self.result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "workflow_path": self.workflow_path,
            "workflow_name": self.workflow_name,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "error_message": self.error_message,
            "result": self.result,
        }


class WorkflowExecutionService:
    """Service for executing workflows with bounded concurrency and tracking.

    Serves as the single execution gateway for all non-CLI entry points
    (Dashboard REST, MCP, CrossWorkflowTrigger).
    """

    def __init__(
        self,
        backend: Any,
        event_bus: Any,
        config_root: str = "configs",
        max_workers: int = DEFAULT_MAX_WORKFLOW_WORKERS,
        run_store: Any = None,
    ):
        """Initialize the execution service.

        Args:
            backend: ObservabilityBackend instance for tracking
            event_bus: ObservabilityEventBus for real-time updates
            config_root: Config directory root path
            max_workers: Max concurrent workflow executions
            run_store: Optional RunStore for persistent run history
        """
        self.backend = backend
        self.event_bus = event_bus
        self.config_root = config_root
        self.run_store = run_store

        # Thread pool for blocking workflow execution
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

        # In-memory execution tracking (execution_id -> metadata)
        self._executions: dict[str, WorkflowExecutionMetadata] = {}
        self._lock = threading.Lock()

        # Track futures for sync callers that need to wait for results
        self._futures: dict[str, Future] = {}

        logger.info(
            "WorkflowExecutionService initialized with max_workers=%d, config_root=%s",
            max_workers,
            config_root,
        )

    # -- Async methods (Dashboard REST) -------------------------------------

    async def execute_workflow_async(
        self,
        workflow_path: str,
        input_data: dict[str, Any] | None = None,
        workspace: str | None = None,
        run_id: str | None = None,
        tenant_id: str | None = None,
    ) -> str:
        """Execute workflow in background and return execution ID immediately.

        Args:
            workflow_path: Path to workflow YAML file (relative to config_root)
            input_data: Input data dictionary for workflow
            workspace: Optional workspace root directory
            run_id: Optional run ID prefix for the execution
            tenant_id: Optional tenant ID for multi-tenant isolation

        Returns:
            execution_id: Unique ID for tracking this execution

        Raises:
            ValueError: If workflow_path is invalid
            FileNotFoundError: If workflow file doesn't exist
        """
        import asyncio

        execution_id, workflow_file = self._prepare_execution(
            workflow_path,
            input_data,
            workspace,
            run_id,
            tenant_id=tenant_id,
        )

        # Schedule background execution
        asyncio.create_task(
            self._run_workflow_background(
                execution_id, str(workflow_file), input_data or {}, workspace
            )
        )

        return execution_id

    async def _run_workflow_background(
        self,
        execution_id: str,
        workflow_path: str,
        input_data: dict[str, Any],
        workspace: str | None = None,
    ) -> None:
        """Run workflow in background thread (internal method).

        Updates execution metadata and handles errors gracefully.
        """
        import asyncio

        with self._lock:
            metadata = self._executions.get(execution_id)
        if metadata is None:
            logger.error("Execution metadata missing for: %s", execution_id)
            return

        try:
            # Update status to running
            with self._lock:
                metadata.status = WorkflowExecutionStatus.RUNNING
                metadata.started_at = datetime.now(UTC)
            if self.run_store is not None:
                self.run_store.update_status(
                    execution_id,
                    "running",
                    started_at=metadata.started_at,
                )

            logger.info("Executing workflow in thread pool: %s", execution_id)

            # Execute in thread pool to avoid blocking event loop
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self._executor,
                self._execute_workflow_in_runner,
                workflow_path,
                input_data,
                execution_id,
                workspace,
            )

            self._record_success(execution_id, result)

        except Exception as e:  # noqa: BLE001
            self._record_failure(execution_id, str(e))
            logger.exception("Workflow execution failed: %s", execution_id)

    # -- Sync methods (MCP / CrossWorkflowTrigger) --------------------------

    def submit_workflow(
        self,
        workflow_path: str,
        input_data: dict[str, Any] | None = None,
        workspace: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """Submit a workflow for background execution (sync, non-blocking).

        Returns execution_id immediately. Workflow runs in thread pool.
        Used by CrossWorkflowTrigger.
        """
        execution_id, workflow_file = self._prepare_execution(
            workflow_path,
            input_data,
            workspace,
            run_id,
        )

        with self._lock:
            metadata = self._executions[execution_id]
            metadata.status = WorkflowExecutionStatus.RUNNING
            metadata.started_at = datetime.now(UTC)
        if self.run_store is not None:
            self.run_store.update_status(
                execution_id,
                "running",
                started_at=metadata.started_at,
            )

        future = self._executor.submit(
            self._run_workflow_with_tracking,
            execution_id,
            str(workflow_file),
            input_data or {},
            workspace,
        )
        with self._lock:
            self._futures[execution_id] = future

        logger.info("Workflow submitted for execution: %s", execution_id)
        return execution_id

    def execute_workflow_sync(
        self,
        workflow_path: str,
        input_data: dict[str, Any] | None = None,
        workspace: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute workflow synchronously and return result (blocking).

        Used by MCP run_workflow handler.
        """
        execution_id = self.submit_workflow(
            workflow_path,
            input_data=input_data,
            workspace=workspace,
            run_id=run_id,
        )

        with self._lock:
            future = self._futures.pop(execution_id, None)

        if future is not None:
            # Wait for completion
            future.result()

        return self.get_status_sync(execution_id) or {}

    def get_status_sync(self, execution_id: str) -> dict[str, Any] | None:
        """Get execution status (sync version of get_execution_status).

        Used by MCP get_run_status handler.
        """
        with self._lock:
            metadata = self._executions.get(execution_id)
            if metadata:
                return metadata.to_dict()

        if self.run_store is not None:
            stored = self.run_store.get_run(execution_id)
            if stored is not None:
                return cast(dict[str, Any], stored.to_dict())

        return None

    # -- Async query methods (Dashboard REST) --------------------------------

    async def get_execution_status(self, execution_id: str) -> dict[str, Any] | None:
        """Get execution status and metadata.

        Falls back to persistent RunStore if not found in memory.

        Args:
            execution_id: Execution ID returned from execute_workflow_async

        Returns:
            Execution metadata dict, or None if not found
        """
        with self._lock:
            metadata = self._executions.get(execution_id)
            if metadata:
                return metadata.to_dict()

        # Fallback to persistent store
        if self.run_store is not None:
            stored = self.run_store.get_run(execution_id)
            if stored is not None:
                return cast(dict[str, Any], stored.to_dict())

        return None

    async def list_executions(
        self,
        status: WorkflowExecutionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List all tracked executions.

        Merges in-memory active runs with persistent store data.

        Args:
            status: Filter by status (optional)
            limit: Max number of executions to return
            offset: Number of results to skip

        Returns:
            List of execution metadata dicts
        """
        if self.run_store is not None:
            results = await self._list_from_store(status, limit + offset)
        else:
            results = await self._list_from_memory(status)

        return results[offset : offset + limit]

    async def _list_from_store(
        self,
        status: WorkflowExecutionStatus | None,
        fetch_limit: int,
    ) -> list[dict[str, Any]]:
        """Query persistent store and merge in-memory active runs."""
        status_str = status.value if status else None
        stored = self.run_store.list_runs(
            status=status_str, limit=fetch_limit, offset=0
        )
        stored_ids = {r.execution_id for r in stored}
        results = [r.to_dict() for r in stored]

        with self._lock:
            for meta in self._executions.values():
                if meta.execution_id in stored_ids:
                    continue
                if status is None or meta.status == status:
                    results.append(meta.to_dict())
        return results

    async def _list_from_memory(
        self,
        status: WorkflowExecutionStatus | None,
    ) -> list[dict[str, Any]]:
        """List executions from in-memory tracking only."""
        with self._lock:
            executions = list(self._executions.values())
        if status:
            executions = [e for e in executions if e.status == status]
        executions.sort(
            key=lambda e: e.started_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
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
        with self._lock:
            metadata = self._executions.get(execution_id)
            if not metadata:
                return False

            if metadata.status not in (
                WorkflowExecutionStatus.PENDING,
                WorkflowExecutionStatus.RUNNING,
            ):
                return False

            metadata.status = WorkflowExecutionStatus.CANCELLED
            metadata.completed_at = datetime.now(UTC)
            metadata.error_message = "Execution cancelled by user"

        logger.info("Workflow execution cancelled: %s", execution_id)
        return True

    def shutdown(self) -> None:
        """Shutdown the service and wait for pending executions."""
        logger.info("Shutting down WorkflowExecutionService")
        self._executor.shutdown(wait=True)

    # -- Private helpers -----------------------------------------------------

    def _prepare_execution(
        self,
        workflow_path: str,
        input_data: dict[str, Any] | None,
        workspace: str | None,
        run_id: str | None,
        tenant_id: str | None = None,
    ) -> tuple[str, Path]:
        """Validate workflow and register execution metadata.

        Returns:
            Tuple of (execution_id, workflow_file_path).
        """
        if run_id:
            execution_id = f"exec-{run_id}"
        else:
            execution_id = f"exec-{uuid.uuid4().hex[:EXECUTION_ID_LENGTH]}"

        # Load and validate workflow config via unified pipeline
        from temper_ai.workflow.runtime import RuntimeConfig, WorkflowRuntime

        rt = WorkflowRuntime(
            config=RuntimeConfig(config_root=self.config_root),
        )
        workflow_config, _ = rt.load_config(workflow_path)
        workflow_file = Path(self.config_root) / workflow_path
        workflow_name = workflow_config.get("workflow", {}).get(
            "name", workflow_file.stem
        )

        metadata = WorkflowExecutionMetadata(
            execution_id=execution_id,
            workflow_path=str(workflow_path),
            workflow_name=workflow_name,
            status=WorkflowExecutionStatus.PENDING,
        )

        with self._lock:
            if execution_id in self._executions:
                raise ValueError(f"Execution ID already exists: {execution_id}")
            self._executions[execution_id] = metadata

        # Persist to store if available
        if self.run_store is not None:
            from temper_ai.interfaces.server.models import ServerRun

            self.run_store.save_run(
                ServerRun(
                    execution_id=execution_id,
                    workflow_path=str(workflow_path),
                    workflow_name=workflow_name,
                    status=WorkflowExecutionStatus.PENDING.value,
                    input_data=input_data,
                    workspace=workspace,
                    tenant_id=tenant_id,
                )
            )

        logger.info(
            "Starting workflow execution: id=%s, workflow=%s, name=%s",
            execution_id,
            workflow_path,
            workflow_name,
        )

        return execution_id, workflow_file

    def _execute_workflow_in_runner(
        self,
        workflow_path: str,
        input_data: dict[str, Any],
        execution_id: str,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        """Execute workflow synchronously via WorkflowRunner (runs in thread pool).

        Args:
            workflow_path: Absolute path to workflow YAML
            input_data: Workflow inputs
            execution_id: Execution ID for tracking
            workspace: Optional workspace root directory

        Returns:
            Workflow result dictionary

        Raises:
            RuntimeError: On workflow execution failure
        """
        from temper_ai.interfaces.server.workflow_runner import (
            WorkflowRunner,
            WorkflowRunnerConfig,
        )

        runner_config = WorkflowRunnerConfig(
            config_root=self.config_root,
            workspace=workspace,
        )
        runner = WorkflowRunner(config=runner_config, event_bus=self.event_bus)
        run_result = runner.run(workflow_path, input_data=input_data)

        # Store workflow_id so the API can return it to the frontend
        with self._lock:
            self._executions[execution_id].workflow_id = run_result.workflow_id

        if run_result.status == "failed":
            raise RuntimeError(run_result.error_message or "Workflow execution failed")

        return run_result.result or {}

    def _run_workflow_with_tracking(
        self,
        execution_id: str,
        workflow_path: str,
        input_data: dict[str, Any],
        workspace: str | None = None,
    ) -> None:
        """Execute workflow with status tracking (for sync submit_workflow path)."""
        try:
            result = self._execute_workflow_in_runner(
                workflow_path,
                input_data,
                execution_id,
                workspace,
            )
            self._record_success(execution_id, result)
        except Exception as e:  # noqa: BLE001
            self._record_failure(execution_id, str(e))
            logger.exception("Workflow execution failed: %s", execution_id)
        finally:
            with self._lock:
                self._futures.pop(execution_id, None)

    def _record_success(self, execution_id: str, result: dict[str, Any]) -> None:
        """Record successful completion of a workflow execution."""
        with self._lock:
            metadata = self._executions[execution_id]
            metadata.status = WorkflowExecutionStatus.COMPLETED
            metadata.completed_at = datetime.now(UTC)
            metadata.result = _sanitize_workflow_result(result)
        if self.run_store is not None:
            self.run_store.update_status(
                execution_id,
                "completed",
                completed_at=metadata.completed_at,
                workflow_id=metadata.workflow_id,
                result_summary=metadata.result,
            )
        logger.info("Workflow execution completed: %s", execution_id)

    def _record_failure(self, execution_id: str, error_message: str) -> None:
        """Record failure of a workflow execution."""
        with self._lock:
            metadata = self._executions[execution_id]
            metadata.status = WorkflowExecutionStatus.FAILED
            metadata.completed_at = datetime.now(UTC)
            metadata.error_message = error_message
        if self.run_store is not None:
            self.run_store.update_status(
                execution_id,
                "failed",
                completed_at=metadata.completed_at,
                error_message=metadata.error_message,
            )
