"""CLI commands for A/B testing and experimentation.

Usage:
    temper-ai experiment list       List experiments
    temper-ai experiment create     Create experiment from YAML
    temper-ai experiment start      Start an experiment
    temper-ai experiment stop       Stop an experiment
    temper-ai experiment results    Show experiment results
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from temper_ai.experimentation.service import ExperimentService

console = Console()

DEFAULT_EXPERIMENT_LIMIT = 20
_COL_WIDTH_ID = 16
_COL_WIDTH_DESC = 40
_ID_DISPLAY_LEN = 16
_OPT_DB = "--db"
_HELP_DB = "Experimentation database URL"
DEFAULT_EXPERIMENT_DB = "sqlite:///./experimentation.db"


def _get_service() -> ExperimentService:
    """Create and initialize ExperimentService."""
    from temper_ai.experimentation.service import ExperimentService

    service = ExperimentService()
    service.initialize()
    return service


@click.group("experiment")
def experiment_group() -> None:
    """A/B testing and experimentation commands."""


@experiment_group.command("list")
@click.option("--status", default=None, help="Filter by status (draft, running, stopped)")
@click.option("--limit", default=DEFAULT_EXPERIMENT_LIMIT, help="Max experiments to show")
def list_experiments(status: str | None, limit: int) -> None:
    """List experiments."""
    from temper_ai.experimentation.models import ExperimentStatus

    service = _get_service()
    status_enum = ExperimentStatus(status) if status else None
    experiments = service.list_experiments(status=status_enum)

    if not experiments:
        console.print("[yellow]No experiments found[/yellow]")
        return

    table = Table(title=f"Experiments ({len(experiments[:limit])})")
    table.add_column("ID", width=_COL_WIDTH_ID)
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Metric")
    table.add_column("Executions")
    table.add_column("Created")
    for exp in experiments[:limit]:
        status_val = exp.status.value if hasattr(exp.status, "value") else str(exp.status)
        created = exp.created_at.strftime("%Y-%m-%d %H:%M") if exp.created_at else "?"
        table.add_row(
            exp.id[:_ID_DISPLAY_LEN],
            exp.name,
            status_val,
            exp.primary_metric,
            str(exp.total_executions),
            created,
        )
    console.print(table)


@experiment_group.command("create")
@click.option("--name", required=True, help="Experiment name")
@click.option("--description", default="", help="Experiment description")
@click.option("--variants-file", required=True, type=click.Path(exists=True), help="YAML file with variant definitions")
@click.option("--metric", default="duration_seconds", help="Primary metric")
def create_experiment(
    name: str, description: str, variants_file: str, metric: str,
) -> None:
    """Create an experiment from a YAML variants file."""
    import yaml

    with open(variants_file) as f:
        data = yaml.safe_load(f)

    variants = data if isinstance(data, list) else data.get("variants", [])
    if not variants:
        console.print("[red]Error:[/red] No variants found in file")
        raise SystemExit(1)

    service = _get_service()
    exp_id = service.create_experiment(
        name=name,
        description=description,
        variants=variants,
        primary_metric=metric,
    )
    console.print(f"[green]Created experiment:[/green] {exp_id}")


@experiment_group.command("start")
@click.argument("experiment_id")
def start_experiment(experiment_id: str) -> None:
    """Start an experiment (enable variant assignment)."""
    service = _get_service()
    try:
        service.start_experiment(experiment_id)
        console.print(f"[green]Started:[/green] {experiment_id}")
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)


@experiment_group.command("stop")
@click.argument("experiment_id")
@click.option("--winner", default=None, help="Declare winning variant ID")
def stop_experiment(experiment_id: str, winner: str | None) -> None:
    """Stop an experiment."""
    service = _get_service()
    try:
        service.stop_experiment(experiment_id, winner=winner)
        msg = f"[green]Stopped:[/green] {experiment_id}"
        if winner:
            msg += f" (winner: {winner})"
        console.print(msg)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)


@experiment_group.command("results")
@click.argument("experiment_id")
def show_results(experiment_id: str) -> None:
    """Show analysis results for an experiment."""
    service = _get_service()
    try:
        results = service.get_experiment_results(experiment_id)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    console.print(f"\n[cyan]Experiment Results:[/cyan] {experiment_id}")
    console.print(f"Sample size: {results.get('sample_size', 0)}")

    rec = results.get("recommendation")
    rec_val = rec.value if rec is not None and hasattr(rec, "value") else str(rec)
    confidence = results.get("confidence", 0.0)
    console.print(f"Recommendation: {rec_val}")
    console.print(f"Confidence: {confidence:.2%}")

    winner = results.get("recommended_winner")
    if winner:
        console.print(f"Recommended winner: {winner}")

    variant_metrics = results.get("variant_metrics", {})
    if variant_metrics:
        table = Table(title="Variant Metrics")
        table.add_column("Variant")
        table.add_column("Mean")
        table.add_column("Std")
        table.add_column("Count")
        for vname, metrics in variant_metrics.items():
            table.add_row(
                vname,
                f"{metrics.get('mean', 0):.4f}",
                f"{metrics.get('std', 0):.4f}",
                str(metrics.get("count", 0)),
            )
        console.print(table)

    violations = results.get("guardrail_violations", [])
    if violations:
        console.print(f"\n[yellow]Guardrail violations: {len(violations)}[/yellow]")
        for v in violations:
            console.print(f"  - {v.get('variant', '?')}: {v.get('metric', '?')} = {v.get('value', '?')}")
