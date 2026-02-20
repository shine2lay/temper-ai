"""CLI command for DAG visualization.

Usage:
    temper-ai visualize <config.yaml>
    temper-ai visualize <config.yaml> --format mermaid --output dag.md
"""
import logging
from pathlib import Path
from typing import Any, Optional

import click
import yaml
from rich.console import Console

from temper_ai.workflow.dag_visualizer_constants import (
    FORMAT_ASCII,
    FORMAT_DOT,
    FORMAT_MERMAID,
)

console = Console()
logger = logging.getLogger(__name__)

_FORMAT_CHOICES = [FORMAT_ASCII, FORMAT_MERMAID, FORMAT_DOT]


def _load_workflow_yaml(workflow_path: str) -> dict:
    """Load and parse a workflow YAML file.

    Args:
        workflow_path: Path to workflow YAML.

    Returns:
        Parsed YAML as dict.

    Raises:
        SystemExit: On file-not-found or parse errors.
    """
    path = Path(workflow_path)
    if not path.exists():
        console.print(f"[red]Error:[/red] Config not found: {workflow_path}")
        raise SystemExit(1)
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        console.print(f"[red]YAML parse error:[/red] {exc}")
        raise SystemExit(1)
    if not isinstance(data, dict) or "workflow" not in data:
        console.print("[red]Error:[/red] Missing 'workflow' key in config")
        raise SystemExit(1)
    return data


def _build_dag_from_workflow(data: dict) -> Any:
    """Build a StageDAG from parsed workflow YAML data.

    Args:
        data: Parsed YAML dict with 'workflow.stages'.

    Returns:
        StageDAG instance.

    Raises:
        SystemExit: On dag-build errors.
    """
    from temper_ai.workflow.dag_builder import build_stage_dag

    stages = data.get("workflow", {}).get("stages", [])
    stage_names = [s.get("name") for s in stages if s.get("name")]
    try:
        return build_stage_dag(stage_names, stages)
    except ValueError as exc:
        console.print(f"[red]DAG error:[/red] {exc}")
        raise SystemExit(1)


def _render_dag(dag: Any, fmt: str) -> str:
    """Render the DAG in the specified format.

    Args:
        dag: StageDAG instance.
        fmt: One of 'ascii', 'mermaid', 'dot'.

    Returns:
        Rendered string.
    """
    from temper_ai.workflow.dag_visualizer import (
        export_dot,
        export_mermaid,
        render_console_dag,
    )

    if fmt == FORMAT_MERMAID:
        return export_mermaid(dag)
    if fmt == FORMAT_DOT:
        return export_dot(dag)
    return render_console_dag(dag)


def _write_output(content: str, output: Optional[str]) -> None:
    """Write rendered content to file or stdout.

    Args:
        content: Rendered DAG string.
        output: File path or None for stdout.
    """
    if output:
        Path(output).write_text(content, encoding="utf-8")
        console.print(f"[green]Written to:[/green] {output}")
    else:
        console.print(content)


@click.command("visualize")
@click.argument("workflow", type=click.Path())
@click.option(
    "--format",
    "fmt",
    type=click.Choice(_FORMAT_CHOICES),
    default=FORMAT_ASCII,
    show_default=True,
    help="Output format.",
)
@click.option(
    "--output",
    "-o",
    default=None,
    help="Write output to file instead of stdout.",
)
def visualize(workflow: str, fmt: str, output: Optional[str]) -> None:
    """Render a workflow DAG as ASCII, Mermaid, or DOT."""
    data = _load_workflow_yaml(workflow)
    dag = _build_dag_from_workflow(data)
    content = _render_dag(dag, fmt)
    _write_output(content, output)
