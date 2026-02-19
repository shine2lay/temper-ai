"""Server delegation for ``temper-ai run``.

When a Temper AI server is running, ``temper-ai run`` delegates workflow execution
to the server so that events flow through the server's event bus,
enabling real-time dashboard streaming.
"""
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from rich.console import Console

from temper_ai.interfaces.cli.server_client import MAFServerClient

logger = logging.getLogger(__name__)

# Terminal statuses that end polling
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

# Polling interval in seconds
POLL_INTERVAL = 2  # scanner: skip-magic

# Maximum time to wait for server-side workflow completion (1 hour)
MAX_POLL_SECONDS = 3600

console = Console()


def detect_server(
    server_url: str, api_key: Optional[str] = None
) -> Optional[MAFServerClient]:
    """Check if a Temper AI server is running and return a client if so.

    Args:
        server_url: Server base URL to probe.
        api_key: Optional API key for authentication.

    Returns:
        MAFServerClient if server is up, None otherwise.
    """
    client = MAFServerClient(base_url=server_url, api_key=api_key)
    if client.is_server_running():
        return client
    return None


def delegate_to_server(
    client: MAFServerClient,
    workflow: str,
    inputs: Dict[str, Any],
    workspace: Optional[str],
    run_id: Optional[str],
    output_file: Optional[str],
    show_details: bool,
) -> None:
    """Delegate workflow execution to a running Temper AI server.

    Resolves paths to absolute so the server can locate files on the
    shared filesystem, triggers the run, polls for completion, and
    optionally saves results.

    Args:
        client: Connected MAFServerClient.
        workflow: Workflow config file path.
        inputs: Workflow input data.
        workspace: Optional workspace root path.
        run_id: Optional externally-provided run ID.
        output_file: Optional path to write JSON results.
        show_details: Show stage transitions during polling.

    Raises:
        SystemExit: On execution failure (exit code 1).
    """
    abs_workflow = str(Path(workflow).resolve())
    abs_workspace = str(Path(workspace).resolve()) if workspace else None

    result = client.trigger_run(
        workflow=abs_workflow,
        inputs=inputs,
        workspace=abs_workspace,
        run_id=run_id,
    )
    execution_id = result.get("execution_id")
    if not execution_id:
        console.print("[red]Error:[/red] Server did not return an execution_id")
        raise SystemExit(1)
    console.print(f"[green]Delegated to server:[/green] {execution_id}")

    final_status = _poll_with_progress(client, execution_id, show_details)

    if output_file:
        _save_output(final_status, output_file)

    status = final_status.get("status", "unknown")
    if status == "failed":
        err = final_status.get("error_message", "")
        if err:
            console.print(f"[red]Error:[/red] {err}")
        raise SystemExit(1)


def _poll_with_progress(
    client: MAFServerClient,
    execution_id: str,
    show_details: bool,
) -> Dict[str, Any]:
    """Poll server for execution status until a terminal state is reached.

    Args:
        client: MAFServerClient instance.
        execution_id: Server-assigned execution ID.
        show_details: If True, print stage transitions as they happen.

    Returns:
        Final status dict from the server.

    Raises:
        SystemExit: If polling times out after MAX_POLL_SECONDS.
    """
    previous_stages: set[str] = set()
    deadline = time.monotonic() + MAX_POLL_SECONDS

    with console.status("[cyan]Running on server...[/cyan]") as spinner:
        while time.monotonic() < deadline:
            try:
                status_data = client.get_status(execution_id)
            except httpx.HTTPError as exc:
                logger.debug("Poll error (transient): %s", exc)
                time.sleep(POLL_INTERVAL)  # Intentional polling: wait before retry after transient error
                continue

            current_status = status_data.get("status", "")
            spinner.update(f"[cyan]Status: {current_status}[/cyan]")

            if show_details:
                _log_stage_transitions(status_data, previous_stages)

            if current_status in TERMINAL_STATUSES:
                style = "green" if current_status == "completed" else "red"
                console.print(f"[{style}]{current_status}[/{style}]")
                return status_data

            time.sleep(POLL_INTERVAL)  # Intentional polling: wait for server-side workflow completion

    console.print("[red]Timed out waiting for server[/red]")
    raise SystemExit(1)


def _log_stage_transitions(
    status_data: Dict[str, Any], previous_stages: set[str]
) -> None:
    """Print newly completed stages since last poll.

    Args:
        status_data: Current status response from server.
        previous_stages: Set of stage names already reported (mutated in place).
    """
    stages = status_data.get("stages", [])
    for stage in stages:
        stage_name = stage.get("name", "")
        stage_status = stage.get("status", "")
        key = f"{stage_name}:{stage_status}"
        if key not in previous_stages:
            previous_stages.add(key)
            style = "green" if stage_status == "completed" else "cyan"
            console.print(f"  [{style}]{stage_name}[/{style}] -> {stage_status}")


def _save_output(status_data: Dict[str, Any], output_file: str) -> None:
    """Write final execution status to a JSON file.

    Args:
        status_data: Final status dict from the server.
        output_file: Path to write JSON output.
    """
    try:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(status_data, f, indent=2, default=str)
        console.print(f"Results saved to [cyan]{output_file}[/cyan]")
    except (IOError, OSError, PermissionError) as e:
        console.print(f"[red]Error saving results:[/red] {e}")
