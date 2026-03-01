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
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from temper_ai.shared.utils.exceptions import ConfigValidationError

logger = logging.getLogger(__name__)


class WorkflowRunnerConfig(BaseModel):
    """Configuration for WorkflowRunner."""

    config_root: str = "configs"
    workspace: str | None = None
    show_details: bool = False
    trigger_type: str = "api"
    environment: str = "server"
    tenant_id: str | None = None


class WorkflowRunResult(BaseModel):
    """Result of a workflow execution."""

    workflow_id: str
    workflow_name: str
    status: str  # "completed" | "failed"
    result: dict[str, Any] | None = None
    error_message: str | None = None
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
        config: WorkflowRunnerConfig | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self.config = config or WorkflowRunnerConfig()
        self.event_bus = event_bus

    def run(
        self,
        workflow_path: str,
        input_data: dict[str, Any] | None = None,
        on_event: Callable | None = None,
        run_id: str | None = None,
        workspace: str | None = None,
        restored_stage_outputs: dict[str, Any] | None = None,
    ) -> WorkflowRunResult:
        """Execute a workflow synchronously and return the result.

        Args:
            workflow_path: Path to workflow YAML (absolute or relative to config_root).
            input_data: Input data dict for the workflow.
            on_event: Optional callback invoked for each ObservabilityEvent.
            run_id: Optional externally-provided run ID.
            workspace: Optional workspace root to restrict file operations.
            restored_stage_outputs: Optional stage outputs from a previous
                checkpoint, used for resume support. Stages with existing
                outputs will be skipped.

        Returns:
            WorkflowRunResult with execution outcome.

        Raises:
            FileNotFoundError: If workflow file does not exist.
        """
        started_at = datetime.now(UTC)
        sub_id: str | None = None

        if on_event is not None and self.event_bus is not None:
            sub_id = self.event_bus.subscribe(on_event)

        try:
            result_data, workflow_name, _engine, _rt = self._run_core(
                workflow_path,
                input_data or {},
                workspace,
                run_id,
                restored_stage_outputs=restored_stage_outputs,
            )
            completed_at = datetime.now(UTC)
            return self._build_result(
                "completed",
                result_data.get("workflow_id", ""),
                workflow_name,
                started_at,
                completed_at,
                result=self._sanitize_result(result_data),
            )
        except FileNotFoundError:
            raise
        except ConfigValidationError:
            raise
        except Exception as exc:
            completed_at = datetime.now(UTC)
            logger.exception("WorkflowRunner execution failed")
            return self._build_result(
                "failed",
                "",
                workflow_path,
                started_at,
                completed_at,
                error_message=str(exc),
            )
        finally:
            if sub_id is not None and self.event_bus is not None:
                self.event_bus.unsubscribe(sub_id)

    def _run_core(
        self,
        workflow_path: str,
        input_data: dict[str, Any],
        workspace: str | None,
        run_id: str | None,
        restored_stage_outputs: dict[str, Any] | None = None,
    ) -> tuple:
        """Execute a workflow via the unified run_pipeline().

        Returns:
            Tuple of (result_data, workflow_name, engine=None, rt).
        """
        from temper_ai.workflow.runtime import (
            RuntimeConfig,
            WorkflowRuntime,
        )

        rt = WorkflowRuntime(
            config=RuntimeConfig(
                config_root=self.config.config_root,
                trigger_type=self.config.trigger_type,
                environment=self.config.environment,
                initialize_database=False,
                event_bus=self.event_bus,
                tenant_id=self.config.tenant_id,
            ),
        )

        hooks = None
        if restored_stage_outputs:
            hooks = self._build_resume_hooks(restored_stage_outputs)

        effective_workspace = workspace or self.config.workspace
        result_data = rt.run_pipeline(
            workflow_path=workflow_path,
            input_data=input_data,
            hooks=hooks,
            workspace=effective_workspace,
            run_id=run_id,
            show_details=self.config.show_details,
        )

        workflow_name = result_data.get("workflow_name", Path(workflow_path).stem)
        # Engine cleanup is handled by run_pipeline internally
        return result_data, workflow_name, None, rt

    @staticmethod
    def _build_resume_hooks(
        restored_stage_outputs: dict[str, Any],
    ) -> "ExecutionHooks":
        """Build ExecutionHooks that inject restored stage outputs for resume."""
        from temper_ai.stage.executors.state_keys import StateKeys
        from temper_ai.workflow.engines.dynamic_engine import DynamicCompiledWorkflow
        from temper_ai.workflow.runtime import ExecutionHooks

        def on_state_built(state: dict[str, Any], _infra: Any) -> None:
            """Inject restored stage outputs into state."""
            existing = state.get(StateKeys.STAGE_OUTPUTS, {})
            existing.update(restored_stage_outputs)
            state[StateKeys.STAGE_OUTPUTS] = existing

        def on_before_execute(compiled: Any, _state: dict[str, Any]) -> None:
            """Set up checkpoint save callback on workflow executor."""
            if isinstance(compiled, DynamicCompiledWorkflow):
                _setup_checkpoint_callback(compiled.workflow_executor)

        return ExecutionHooks(
            on_state_built=on_state_built,
            on_before_execute=on_before_execute,
        )

    def _build_result(
        self,
        status: str,
        workflow_id: str,
        workflow_name: str,
        started_at: datetime,
        completed_at: datetime,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> WorkflowRunResult:
        """Construct a WorkflowRunResult."""
        return WorkflowRunResult(
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            status=status,
            result=result,
            error_message=error_message,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=(completed_at - started_at).total_seconds(),
        )

    def _sanitize_result(self, result: dict[str, Any]) -> dict[str, Any] | None:
        """Strip non-serializable keys from result."""
        from temper_ai.workflow.execution_service import (
            _sanitize_workflow_result,
        )

        return _sanitize_workflow_result(result)


def _setup_checkpoint_callback(workflow_executor: Any) -> None:
    """Wire a checkpoint save callback onto the workflow executor."""
    from temper_ai.stage.executors.state_keys import StateKeys

    def _save_checkpoint(state: dict[str, Any]) -> None:
        """Save checkpoint after each depth group completes."""
        workflow_id = state.get(StateKeys.WORKFLOW_ID)
        if not workflow_id:
            return
        try:
            from temper_ai.workflow.checkpoint_manager import CheckpointManager
            from temper_ai.workflow.domain_state import WorkflowDomainState

            domain = WorkflowDomainState(
                workflow_id=workflow_id,
                stage_outputs=state.get(StateKeys.STAGE_OUTPUTS, {}),
                current_stage=state.get(StateKeys.CURRENT_STAGE, ""),
            )
            mgr = CheckpointManager()
            mgr.save_checkpoint(domain)
        except Exception:
            logger.warning("Checkpoint save failed", exc_info=True)

    workflow_executor._on_depth_complete = _save_checkpoint
