"""Cross-workflow trigger utilities."""

import logging
import threading
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class CrossWorkflowTrigger:
    """Trigger workflow executions in response to events."""

    def trigger(
        self,
        workflow_path: str,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Spawn a workflow execution in a background thread.

        Args:
            workflow_path: Path to the workflow YAML config.
            inputs: Optional input dict for the workflow.

        Returns:
            Thread name used as trigger ID.
        """
        trigger_id = str(uuid.uuid4())
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
        inputs: Dict[str, Any],
        trigger_id: str,
    ) -> None:
        """Execute the workflow (runs in daemon thread).

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
