"""Cross-workflow trigger utilities."""

import logging
import threading
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class CrossWorkflowTrigger:
    """Trigger workflow executions in response to events.

    When an execution_service is provided, workflows are submitted
    through it for bounded concurrency, run tracking, and cancellation.
    Otherwise falls back to unbounded daemon threads (standalone use).
    """

    def __init__(self, execution_service: Any | None = None) -> None:
        self._execution_service = execution_service

    def trigger(
        self,
        workflow_path: str,
        inputs: dict[str, Any] | None = None,
    ) -> str:
        """Spawn a workflow execution.

        Args:
            workflow_path: Path to the workflow YAML config.
            inputs: Optional input dict for the workflow.

        Returns:
            Trigger ID (UUID string).
        """
        trigger_id = str(uuid.uuid4())

        if self._execution_service is not None:
            # Delegate to execution service (bounded, tracked)
            execution_id = self._execution_service.submit_workflow(
                workflow_path,
                input_data=inputs or {},
                run_id=trigger_id,
            )
            logger.info(
                "Cross-workflow trigger submitted: workflow=%s trigger_id=%s exec_id=%s",
                workflow_path,
                trigger_id,
                execution_id,
            )
            return trigger_id

        # Fallback: daemon thread (backward compat, standalone use)
        thread = threading.Thread(
            target=self._run_workflow,
            args=(workflow_path, inputs or {}, trigger_id),
            name=f"cross-workflow-{trigger_id}",
            daemon=True,
        )
        thread.start()
        logger.info(
            "Cross-workflow trigger started: workflow=%s trigger_id=%s",
            workflow_path,
            trigger_id,
        )
        return trigger_id

    def _run_workflow(
        self,
        workflow_path: str,
        inputs: dict[str, Any],
        trigger_id: str,
    ) -> None:
        """Execute the workflow via WorkflowRunner (runs in daemon thread).

        Args:
            workflow_path: Path to the workflow YAML config.
            inputs: Input dict for the workflow.
            trigger_id: ID of the trigger event.
        """
        logger.info(
            "Executing triggered workflow: workflow=%s trigger_id=%s inputs=%s",
            workflow_path,
            trigger_id,
            list(inputs.keys()),
        )
        try:
            from temper_ai.interfaces.server.workflow_runner import (
                WorkflowRunner,
                WorkflowRunnerConfig,
            )

            runner = WorkflowRunner(
                config=WorkflowRunnerConfig(trigger_type="event"),
            )
            result = runner.run(
                workflow_path,
                input_data=inputs,
                run_id=trigger_id,
            )
            logger.info(
                "Triggered workflow completed: workflow=%s trigger_id=%s status=%s",
                workflow_path,
                trigger_id,
                result.status,
            )
        except FileNotFoundError as exc:
            logger.error(
                "Triggered workflow not found: workflow=%s trigger_id=%s error=%s",
                workflow_path,
                trigger_id,
                exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Triggered workflow failed: workflow=%s trigger_id=%s error=%s",
                workflow_path,
                trigger_id,
                exc,
            )
