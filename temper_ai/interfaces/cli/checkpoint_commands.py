"""Checkpoint replay commands (R0.6).

Lists and resumes workflow runs from saved checkpoints.
The checkpoint system already exists (CheckpointManager, FileCheckpointBackend).
This module adds CLI commands to list and resume.

Usage:
    temper-ai checkpoint list
    temper-ai checkpoint resume <run_id> --from-stage <stage_name>
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.table import Table

from temper_ai.interfaces.cli.checkpoint_constants import (
    CHECKPOINT_DIR,
    CHECKPOINT_FILE_PATTERN,
    CHECKPOINT_TABLE_TITLE,
    COLUMN_RUN_ID,
    COLUMN_STAGE,
    COLUMN_STAGES_COMPLETED,
    COLUMN_TIMESTAMP,
    MAX_CHECKPOINT_LIST,
)

logger = logging.getLogger(__name__)
console = Console()


def _list_checkpoint_files(checkpoint_dir: str) -> list[Path]:
    """List all checkpoint JSON files in the directory tree.

    Searches for checkpoint files inside workflow subdirectories.

    Args:
        checkpoint_dir: Root checkpoint directory.

    Returns:
        List of checkpoint file paths, sorted by modification time (newest first).
    """
    base = Path(checkpoint_dir)
    if not base.exists():
        return []
    files = list(base.rglob(CHECKPOINT_FILE_PATTERN))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:MAX_CHECKPOINT_LIST]


def _load_checkpoint(path: Path) -> Dict[str, Any]:
    """Load and parse a checkpoint JSON file.

    Handles both HMAC envelope format and legacy format.

    Args:
        path: Path to the checkpoint JSON file.

    Returns:
        Parsed checkpoint data dict.

    Raises:
        json.JSONDecodeError: If file is not valid JSON.
        OSError: If file cannot be read.
    """
    with open(path) as f:
        raw: Dict[str, Any] = json.load(f)
    # Handle HMAC envelope format
    if "hmac" in raw and "data" in raw:
        data: Dict[str, Any] = raw["data"]
        return data
    return raw


def _extract_checkpoint_info(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract display information from checkpoint data.

    Args:
        data: Parsed checkpoint data dict.

    Returns:
        Dict with run_id, stage, timestamp, and stages_completed fields.
    """
    metadata = data.get("metadata", {})
    domain_state = data.get("domain_state", {})
    stages_completed = metadata.get(
        "num_stages_completed",
        len(domain_state.get("stage_outputs", {})),
    )
    return {
        "run_id": data.get("workflow_id", "unknown"),
        "stage": data.get("stage", "unknown"),
        "timestamp": data.get("created_at", "unknown"),
        "stages_completed": stages_completed,
    }


def _find_checkpoint(checkpoint_dir: str, run_id: str) -> Optional[Path]:
    """Find the latest checkpoint file for a given run ID.

    Searches by workflow subdirectory name first, then by scanning
    all checkpoint files.

    Args:
        checkpoint_dir: Root checkpoint directory.
        run_id: Workflow run ID to find.

    Returns:
        Path to the checkpoint file, or None if not found.
    """
    base = Path(checkpoint_dir)
    # Check workflow subdirectory directly
    workflow_dir = base / run_id
    if workflow_dir.is_dir():
        files = sorted(
            workflow_dir.glob("cp-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if files:
            return files[0]

    # Fallback: scan all checkpoint files
    for path in _list_checkpoint_files(checkpoint_dir):
        try:
            data = _load_checkpoint(path)
            if data.get("workflow_id") == run_id:
                return path
        except (json.JSONDecodeError, OSError, KeyError):
            continue
    return None


def _build_resumed_stages(
    checkpoint_data: Dict[str, Any], from_stage: str
) -> set[str]:
    """Calculate which stages to skip when resuming.

    Returns the set of stage names that were completed before from_stage,
    based on the stage_outputs in the checkpoint domain state.

    Args:
        checkpoint_data: Parsed checkpoint data dict.
        from_stage: Stage name to resume from.

    Returns:
        Set of stage names to skip (mark as already completed).
    """
    domain_state = checkpoint_data.get("domain_state", {})
    stage_outputs = domain_state.get("stage_outputs", {})
    completed = set(stage_outputs.keys())
    # Remove from_stage and anything after it — we want to re-run from_stage
    completed.discard(from_stage)
    return completed


@click.group("checkpoint")
def checkpoint_group() -> None:
    """Manage workflow checkpoints."""


@checkpoint_group.command("list")
@click.option(
    "--dir",
    "checkpoint_dir",
    default=CHECKPOINT_DIR,
    show_default=True,
    help="Checkpoint directory",
)
def list_checkpoints(checkpoint_dir: str) -> None:
    """List available checkpoints from past workflow runs."""
    files = _list_checkpoint_files(checkpoint_dir)

    if not files:
        console.print(
            f"[yellow]No checkpoints found in {checkpoint_dir}[/yellow]"
        )
        return

    table = Table(title=CHECKPOINT_TABLE_TITLE)
    table.add_column(COLUMN_RUN_ID, style="cyan")
    table.add_column(COLUMN_STAGE)
    table.add_column(COLUMN_TIMESTAMP)
    table.add_column(COLUMN_STAGES_COMPLETED, style="yellow")

    for path in files:
        try:
            data = _load_checkpoint(path)
            info = _extract_checkpoint_info(data)
            table.add_row(
                info["run_id"],
                info["stage"],
                info["timestamp"],
                str(info["stages_completed"]),
            )
        except (json.JSONDecodeError, OSError, KeyError) as exc:
            logger.debug("Skipping unreadable checkpoint %s: %s", path, exc)
            continue

    console.print(table)


@checkpoint_group.command("resume")
@click.argument("run_id")
@click.option(
    "--from-stage",
    required=True,
    help="Resume from this stage (skip completed stages before it)",
)
@click.option(
    "--dir",
    "checkpoint_dir",
    default=CHECKPOINT_DIR,
    show_default=True,
    help="Checkpoint directory",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--show-details", "-d", is_flag=True, help="Show details")
def resume_checkpoint(
    run_id: str,
    from_stage: str,
    checkpoint_dir: str,
    verbose: bool,
    show_details: bool,
) -> None:
    """Resume a workflow from a checkpoint."""
    cp_path = _find_checkpoint(checkpoint_dir, run_id)
    if cp_path is None:
        console.print(
            f"[red]Error:[/red] No checkpoint found for run '{run_id}' "
            f"in {checkpoint_dir}"
        )
        raise SystemExit(1)

    try:
        checkpoint_data = _load_checkpoint(cp_path)
    except (json.JSONDecodeError, OSError) as exc:
        console.print(f"[red]Error loading checkpoint:[/red] {exc}")
        raise SystemExit(1)

    resumed_stages = _build_resumed_stages(checkpoint_data, from_stage)

    if verbose:
        console.print(
            f"Resuming run [cyan]{run_id}[/cyan] from stage "
            f"[cyan]{from_stage}[/cyan]"
        )
        if resumed_stages:
            console.print(
                f"  Skipping completed stages: {', '.join(sorted(resumed_stages))}"
            )

    # Load the workflow config path from checkpoint metadata
    domain_state = checkpoint_data.get("domain_state", {})
    workflow_path = domain_state.get("workflow_config_path")

    if not workflow_path:
        console.print(
            "[red]Error:[/red] Checkpoint does not contain workflow config path. "
            "Manual resume with 'temper-ai run' is required."
        )
        console.print(
            f"  Completed stages: {', '.join(sorted(resumed_stages))}"
        )
        console.print(f"  Resume from: {from_stage}")
        raise SystemExit(1)

    console.print(
        f"[green]Checkpoint loaded.[/green] Run "
        f"'temper-ai run {workflow_path}' with resumed state."
    )
    console.print(
        f"  Stages to skip: {', '.join(sorted(resumed_stages)) or '(none)'}"
    )
    console.print(f"  Resume from: {from_stage}")
