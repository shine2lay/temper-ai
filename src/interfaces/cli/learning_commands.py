"""CLI commands for continuous learning.

Usage:
    maf learning mine       Mine patterns from execution history
    maf learning patterns   List learned patterns
    maf learning recommend  Generate recommendations from patterns
    maf learning tune       Preview or apply auto-tune recommendations
    maf learning stats      Show mining run history and convergence
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from src.learning.store import LearningStore

console = Console()

DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_PATTERN_LIMIT = 20
DEFAULT_CONFIDENCE_THRESHOLD = 0.7
DEFAULT_LEARNING_DB = "sqlite:///./learning.db"
_HELP_DB = "Learning database URL"
_OPT_DB = "--db"
_COL_WIDTH_ID = 12
_COL_WIDTH_RATIONALE = 40
_ID_DISPLAY_LEN = 12


def _get_store(db_url: str = DEFAULT_LEARNING_DB) -> LearningStore:
    """Create a LearningStore instance."""
    from src.learning.store import LearningStore
    return LearningStore(database_url=db_url)


@click.group("learning")
def learning_group() -> None:
    """Continuous learning — mine patterns, recommend, auto-tune."""


@learning_group.command("mine")
@click.option("--lookback", default=DEFAULT_LOOKBACK_HOURS, help="Hours of history to analyze")
@click.option(_OPT_DB, default=DEFAULT_LEARNING_DB, help=_HELP_DB)
def mine(lookback: int, db: str) -> None:
    """Mine patterns from execution history."""
    from src.learning.orchestrator import MiningOrchestrator

    store = _get_store(db)
    orch = MiningOrchestrator(store=store)
    run = orch.run_mining(lookback_hours=lookback)

    console.print(f"[green]Mining complete[/green] — {run.patterns_found} found, {run.patterns_new} new")
    console.print(f"Novelty score: {run.novelty_score:.2f}")
    if run.miner_stats:
        table = Table(title="Miner Results")
        table.add_column("Miner")
        table.add_column("Patterns")
        for miner_name, count in run.miner_stats.items():
            table.add_row(miner_name, str(count))
        console.print(table)


@learning_group.command("patterns")
@click.option("--type", "pattern_type", default=None, help="Filter by pattern type")
@click.option("--limit", default=DEFAULT_PATTERN_LIMIT, help="Max patterns to show")
@click.option(_OPT_DB, default=DEFAULT_LEARNING_DB, help=_HELP_DB)
def patterns(pattern_type: str | None, limit: int, db: str) -> None:
    """List learned patterns."""
    store = _get_store(db)
    results = store.list_patterns(pattern_type=pattern_type, limit=limit)

    if not results:
        console.print("[yellow]No patterns found[/yellow]")
        return

    table = Table(title=f"Learned Patterns ({len(results)})")
    table.add_column("ID", width=_COL_WIDTH_ID)
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Confidence")
    table.add_column("Impact")
    for p in results:
        table.add_row(
            p.id[:_ID_DISPLAY_LEN], p.pattern_type, p.title,
            f"{p.confidence:.2f}", f"{p.impact_score:.2f}",
        )
    console.print(table)


@learning_group.command("recommend")
@click.option("--min-confidence", default=DEFAULT_CONFIDENCE_THRESHOLD, help="Min confidence threshold")
@click.option(_OPT_DB, default=DEFAULT_LEARNING_DB, help=_HELP_DB)
def recommend(min_confidence: float, db: str) -> None:
    """Generate recommendations from learned patterns."""
    from src.learning.recommender import RecommendationEngine

    store = _get_store(db)
    engine = RecommendationEngine(store)
    recs = engine.generate_recommendations(min_confidence=min_confidence)

    if not recs:
        console.print("[yellow]No recommendations generated[/yellow]")
        return

    table = Table(title=f"Recommendations ({len(recs)})")
    table.add_column("ID", width=_COL_WIDTH_ID)
    table.add_column("Field")
    table.add_column("Current")
    table.add_column("Recommended")
    table.add_column("Rationale", width=_COL_WIDTH_RATIONALE)
    for r in recs:
        table.add_row(
            r.id[:_ID_DISPLAY_LEN], r.field_path,
            r.current_value, r.recommended_value,
            r.rationale[:_COL_WIDTH_RATIONALE],
        )
    console.print(table)


@learning_group.command("tune")
@click.option("--apply", "apply_ids", multiple=True, help="Recommendation IDs to apply")
@click.option("--preview", is_flag=True, help="Preview changes without applying")
@click.option(_OPT_DB, default=DEFAULT_LEARNING_DB, help=_HELP_DB)
def tune(apply_ids: tuple, preview: bool, db: str) -> None:
    """Preview or apply auto-tune recommendations."""
    from src.learning.auto_tune import AutoTuneEngine

    store = _get_store(db)
    engine = AutoTuneEngine(store)

    if not apply_ids:
        pending = store.list_recommendations(status="pending")
        if not pending:
            console.print("[yellow]No pending recommendations[/yellow]")
            return
        apply_ids = tuple(r.id for r in pending)

    ids = list(apply_ids)
    if preview:
        changes = engine.preview_changes(ids)
    else:
        changes = engine.apply_recommendations(ids)

    for c in changes:
        status = c.get("status", "unknown")
        color = "green" if status == "applied" else "cyan" if status == "preview" else "red"
        console.print(f"[{color}]{status}[/{color}] {c.get('field_path', c.get('id', ''))}")


@learning_group.command("stats")
@click.option(_OPT_DB, default=DEFAULT_LEARNING_DB, help=_HELP_DB)
def stats(db: str) -> None:
    """Show mining run history and convergence status."""
    from src.learning.convergence import ConvergenceDetector

    store = _get_store(db)
    detector = ConvergenceDetector(store)
    trend = detector.get_trend()
    converged = detector.is_converged()

    console.print(f"Convergence: {'[green]converged[/green]' if converged else '[yellow]not converged[/yellow]'}")
    console.print(f"Data points: {trend['data_points']}")
    console.print(f"Moving avg novelty: {trend['moving_average']:.4f}")

    runs = store.list_mining_runs()
    if runs:
        table = Table(title="Recent Mining Runs")
        table.add_column("ID", width=_COL_WIDTH_ID)
        table.add_column("Status")
        table.add_column("Found")
        table.add_column("New")
        table.add_column("Novelty")
        for r in runs:
            table.add_row(
                r.id[:_ID_DISPLAY_LEN], r.status,
                str(r.patterns_found), str(r.patterns_new),
                f"{r.novelty_score:.2f}",
            )
        console.print(table)
