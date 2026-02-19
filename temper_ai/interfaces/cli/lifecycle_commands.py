"""CLI commands for self-modifying lifecycle.

Usage:
    temper-ai lifecycle profiles              List all profiles (YAML + DB)
    temper-ai lifecycle profiles show <name>  Show profile rules
    temper-ai lifecycle classify <wf> -i <f>  Classify project characteristics
    temper-ai lifecycle preview <wf> -i <f>   Dry-run: show what would be adapted
    temper-ai lifecycle history               Show recent adaptation records
    temper-ai lifecycle check                 Run rollback check on active profiles
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from temper_ai.lifecycle.profiles import ProfileRegistry

import click
import yaml
from rich.console import Console
from rich.table import Table

console = Console()

DEFAULT_LIFECYCLE_DB = "sqlite:///./lifecycle.db"
DEFAULT_LIFECYCLE_CONFIG_DIR = "configs/lifecycle"
DEFAULT_HISTORY_LIMIT = 20
_OPT_DB = "--db"
_HELP_DB = "Lifecycle database URL"
_OPT_CONFIG_DIR = "--config-dir"
_HELP_CONFIG_DIR = "Lifecycle config directory"
_ID_DISPLAY_LEN = 12
_CONDITION_DISPLAY_WIDTH = 40


@click.group("lifecycle")
def lifecycle_group() -> None:
    """Self-modifying lifecycle — adapt workflow structure automatically."""


# ── profiles ─────────────────────────────────────────────────────────


@lifecycle_group.group("profiles")
def profiles_group() -> None:
    """Manage lifecycle profiles."""


@profiles_group.command("list")
@click.option(_OPT_DB, default=DEFAULT_LIFECYCLE_DB, help=_HELP_DB)
@click.option(
    _OPT_CONFIG_DIR,
    default=DEFAULT_LIFECYCLE_CONFIG_DIR,
    help=_HELP_CONFIG_DIR,
)
def profiles_list(db: str, config_dir: str) -> None:
    """List all lifecycle profiles (YAML + DB)."""
    registry = _get_registry(config_dir, db)
    profiles = registry.list_profiles()

    if not profiles:
        console.print("[yellow]No profiles found[/yellow]")
        return

    table = Table(title="Lifecycle Profiles")
    table.add_column("Name", style="cyan")
    table.add_column("Source")
    table.add_column("Rules", style="yellow")
    table.add_column("Enabled")
    table.add_column("Min Autonomy")

    for p in profiles:
        enabled = "[green]yes[/green]" if p.enabled else "[red]no[/red]"
        table.add_row(
            p.name,
            p.source,
            str(len(p.rules)),
            enabled,
            str(p.min_autonomy_level),
        )

    console.print(table)


@profiles_group.command("show")
@click.argument("name")
@click.option(_OPT_DB, default=DEFAULT_LIFECYCLE_DB, help=_HELP_DB)
@click.option(
    _OPT_CONFIG_DIR,
    default=DEFAULT_LIFECYCLE_CONFIG_DIR,
    help=_HELP_CONFIG_DIR,
)
def profiles_show(name: str, db: str, config_dir: str) -> None:
    """Show details and rules for a profile."""
    registry = _get_registry(config_dir, db)
    profile = registry.get_profile(name)

    if profile is None:
        console.print(f"[red]Profile not found:[/red] {name}")
        raise SystemExit(1)

    console.print(f"\n[cyan]Profile:[/cyan] {profile.name}")
    console.print(f"[cyan]Description:[/cyan] {profile.description}")
    console.print(f"[cyan]Source:[/cyan] {profile.source}")
    console.print(f"[cyan]Confidence:[/cyan] {profile.confidence}")
    console.print(f"[cyan]Min Autonomy:[/cyan] {profile.min_autonomy_level}")
    console.print(f"[cyan]Requires Approval:[/cyan] {profile.requires_approval}")

    if profile.rules:
        table = Table(title="Rules")
        table.add_column("Name", style="cyan")
        table.add_column("Action", style="yellow")
        table.add_column("Stage")
        table.add_column("Condition")
        table.add_column("Priority")

        for r in profile.rules:
            table.add_row(
                r.name, r.action.value, r.stage_name,
                r.condition[:_CONDITION_DISPLAY_WIDTH], str(r.priority),
            )
        console.print(table)


# ── classify ─────────────────────────────────────────────────────────


@lifecycle_group.command("classify")
@click.argument("workflow", type=click.Path(exists=True))
@click.option(
    "--input", "input_file",
    type=click.Path(exists=True),
    help="YAML input file",
)
def classify(workflow: str, input_file: Optional[str]) -> None:
    """Classify project characteristics for a workflow."""
    from temper_ai.lifecycle.classifier import ProjectClassifier

    workflow_config = _load_workflow(workflow)
    inputs = _load_inputs(input_file)

    classifier = ProjectClassifier()
    chars = classifier.classify(workflow_config, inputs)

    console.print("\n[cyan]Project Classification:[/cyan]")
    for key, value in chars.model_dump(mode="json").items():
        console.print(f"  {key}: {value}")


# ── preview ──────────────────────────────────────────────────────────


@lifecycle_group.command("preview")
@click.argument("workflow", type=click.Path(exists=True))
@click.option(
    "--input", "input_file",
    type=click.Path(exists=True),
    help="YAML input file",
)
@click.option(_OPT_DB, default=DEFAULT_LIFECYCLE_DB, help=_HELP_DB)
@click.option(
    _OPT_CONFIG_DIR,
    default=DEFAULT_LIFECYCLE_CONFIG_DIR,
    help=_HELP_CONFIG_DIR,
)
def preview(
    workflow: str,
    input_file: Optional[str],
    db: str,
    config_dir: str,
) -> None:
    """Dry-run: show what lifecycle adaptation would do."""
    from temper_ai.lifecycle.adapter import LifecycleAdapter
    from temper_ai.lifecycle.classifier import ProjectClassifier
    from temper_ai.lifecycle.store import LifecycleStore

    workflow_config = _load_workflow(workflow)
    inputs = _load_inputs(input_file)
    wf = workflow_config.get("workflow", {})
    original_stages = [s.get("name", "") for s in wf.get("stages", [])]

    store = LifecycleStore(database_url=db)
    registry = _get_registry(config_dir, db)
    classifier = ProjectClassifier()
    adapter = LifecycleAdapter(
        profile_registry=registry,
        classifier=classifier,
        store=store,
    )

    try:
        adapted = adapter.adapt(workflow_config, inputs)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    adapted_wf = adapted.get("workflow", {})
    adapted_stages = [
        s.get("name", "") for s in adapted_wf.get("stages", [])
    ]

    console.print("\n[cyan]Original stages:[/cyan]")
    for name in original_stages:
        console.print(f"  - {name}")

    console.print("\n[cyan]Adapted stages:[/cyan]")
    for name in adapted_stages:
        marker = "[green]+[/green]" if name not in original_stages else " "
        console.print(f"  {marker} {name}")

    removed = set(original_stages) - set(adapted_stages)
    if removed:
        console.print("\n[yellow]Removed stages:[/yellow]")
        for name in removed:
            console.print(f"  [red]-[/red] {name}")


# ── history ──────────────────────────────────────────────────────────


@lifecycle_group.command("history")
@click.option(_OPT_DB, default=DEFAULT_LIFECYCLE_DB, help=_HELP_DB)
@click.option(
    "--limit", default=DEFAULT_HISTORY_LIMIT, help="Max records to show"
)
def history(db: str, limit: int) -> None:
    """Show recent adaptation records."""
    from temper_ai.lifecycle.store import LifecycleStore

    store = LifecycleStore(database_url=db)
    records = store.list_adaptations(limit=limit)

    if not records:
        console.print("[yellow]No adaptation records found[/yellow]")
        return

    table = Table(title="Recent Adaptations")
    table.add_column("ID", style="cyan")
    table.add_column("Profile")
    table.add_column("Original Stages")
    table.add_column("Adapted Stages")
    table.add_column("Rules Applied", style="yellow")

    for r in records:
        table.add_row(
            r.id[:_ID_DISPLAY_LEN],
            r.profile_name,
            ", ".join(r.stages_original),
            ", ".join(r.stages_adapted),
            str(len(r.rules_applied)),
        )

    console.print(table)


# ── check ────────────────────────────────────────────────────────────


@lifecycle_group.command("check")
@click.option(_OPT_DB, default=DEFAULT_LIFECYCLE_DB, help=_HELP_DB)
@click.option(
    _OPT_CONFIG_DIR,
    default=DEFAULT_LIFECYCLE_CONFIG_DIR,
    help=_HELP_CONFIG_DIR,
)
def check(db: str, config_dir: str) -> None:
    """Run rollback check on active profiles."""
    from temper_ai.lifecycle.history import HistoryAnalyzer
    from temper_ai.lifecycle.rollback import RollbackMonitor
    from temper_ai.lifecycle.store import LifecycleStore

    store = LifecycleStore(database_url=db)
    history_analyzer = HistoryAnalyzer(db_url=db)
    monitor = RollbackMonitor(store=store, history=history_analyzer)

    registry = _get_registry(config_dir, db)
    profiles = registry.list_profiles()
    issues_found = False

    for profile in profiles:
        if not profile.enabled:
            continue
        report = monitor.check_degradation(profile.name)
        if report is not None:
            issues_found = True
            console.print(
                f"[red]Degradation:[/red] {profile.name} "
                f"(baseline={report.baseline_success_rate:.2f}, "
                f"adapted={report.adapted_success_rate:.2f}, "
                f"drop={report.degradation_pct:.1%})"
            )

    if not issues_found:
        console.print("[green]No degradation detected[/green]")


# ── Helpers ──────────────────────────────────────────────────────────


def _get_registry(config_dir: str, db: str) -> "ProfileRegistry":
    """Create a ProfileRegistry instance."""
    from temper_ai.lifecycle.profiles import ProfileRegistry
    from temper_ai.lifecycle.store import LifecycleStore

    store = LifecycleStore(database_url=db)
    return ProfileRegistry(config_dir=Path(config_dir), store=store)


def _load_workflow(path: str) -> dict:
    """Load a workflow YAML file."""
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _load_inputs(input_file: Optional[str]) -> dict:
    """Load an input YAML file."""
    if not input_file:
        return {}
    with open(input_file) as f:
        return yaml.safe_load(f) or {}
