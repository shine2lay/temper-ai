"""CLI commands for portfolio management.

Usage:
    temper-ai portfolio list                       List available portfolios
    temper-ai portfolio show <name>                Show portfolio details + allocation status
    temper-ai portfolio run <name> [--product X]   Run next product (or specific)
    temper-ai portfolio scorecards <name>          Show product scorecards
    temper-ai portfolio recommend <name>           Show invest/sunset recommendations
    temper-ai portfolio components <name>          Analyze cross-product component sharing
    temper-ai portfolio graph stats                Knowledge graph statistics
    temper-ai portfolio graph query <concept>      Query related concepts
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from temper_ai.portfolio.loader import PortfolioLoader
    from temper_ai.portfolio.store import PortfolioStore

import click
from rich.console import Console
from rich.table import Table

console = Console()

_COL_NAME = "Name"
_COL_PRODUCT = "Product"
_ID_DISPLAY_LEN = 12  # noqa: scanner: skip-magic

DEFAULT_PORTFOLIO_DB = "sqlite:///./portfolio.db"
DEFAULT_PORTFOLIO_CONFIG_DIR = "configs/portfolios"
_OPT_DB = "--db"
_HELP_DB = "Portfolio database URL"
_OPT_CONFIG_DIR = "--config-dir"
_HELP_CONFIG_DIR = "Portfolio config directory"


def _get_store(db: str) -> "PortfolioStore":
    """Create a PortfolioStore instance."""
    from temper_ai.portfolio.store import PortfolioStore as _Store

    return _Store(database_url=db)


def _get_loader(config_dir: str) -> "PortfolioLoader":
    """Create a PortfolioLoader instance."""
    from temper_ai.portfolio.loader import PortfolioLoader as _Loader

    return _Loader(config_dir=config_dir)


@click.group("portfolio")
def portfolio_group() -> None:
    """Portfolio management -- multi-product orchestration and analysis."""


# -- list -----------------------------------------------------------------


@portfolio_group.command("list")
@click.option(_OPT_DB, default=DEFAULT_PORTFOLIO_DB, help=_HELP_DB)
@click.option(_OPT_CONFIG_DIR, default=DEFAULT_PORTFOLIO_CONFIG_DIR, help=_HELP_CONFIG_DIR)
def list_portfolios(db: str, config_dir: str) -> None:
    """List available portfolios (YAML configs + DB)."""
    loader = _get_loader(config_dir)
    store = _get_store(db)

    yaml_names = set(loader.list_available())
    db_records = store.list_portfolios()
    db_names = {r.name for r in db_records}
    all_names = sorted(yaml_names | db_names)

    if not all_names:
        console.print("[yellow]No portfolios found[/yellow]")
        return

    table = Table(title="Portfolios")
    table.add_column(_COL_NAME, style="cyan")
    table.add_column("Source")
    table.add_column("Products", style="yellow")
    table.add_column("Strategy")
    table.add_column("Enabled")

    for name in all_names:
        source = _source_label(name in yaml_names, name in db_names)
        products = ""
        strategy = ""
        enabled = ""
        try:
            cfg = loader.load(name)
            products = str(len(cfg.products))
            strategy = cfg.strategy.value
        except FileNotFoundError:
            pass
        db_rec = next((r for r in db_records if r.name == name), None)
        if db_rec is not None:
            enabled = "[green]yes[/green]" if db_rec.enabled else "[red]no[/red]"
        table.add_row(name, source, products, strategy, enabled)

    console.print(table)


def _source_label(in_yaml: bool, in_db: bool) -> str:
    """Build a source label from YAML/DB presence."""
    parts = []
    if in_yaml:
        parts.append("yaml")
    if in_db:
        parts.append("db")
    return "+".join(parts)


# -- show -----------------------------------------------------------------


@portfolio_group.command("show")
@click.argument("name")
@click.option(_OPT_DB, default=DEFAULT_PORTFOLIO_DB, help=_HELP_DB)
@click.option(_OPT_CONFIG_DIR, default=DEFAULT_PORTFOLIO_CONFIG_DIR, help=_HELP_CONFIG_DIR)
def show_portfolio(name: str, db: str, config_dir: str) -> None:
    """Show portfolio details and allocation status."""
    from temper_ai.portfolio.scheduler import ResourceScheduler

    loader = _get_loader(config_dir)
    store = _get_store(db)

    try:
        cfg = loader.load(name)
    except FileNotFoundError:
        console.print(f"[red]Portfolio not found:[/red] {name}")
        raise SystemExit(1)

    console.print(f"\n[cyan]Portfolio:[/cyan] {cfg.name}")
    console.print(f"[cyan]Description:[/cyan] {cfg.description}")
    console.print(f"[cyan]Strategy:[/cyan] {cfg.strategy.value}")
    console.print(f"[cyan]Max Concurrent:[/cyan] {cfg.max_total_concurrent}")
    if cfg.total_budget_usd > 0:
        console.print(f"[cyan]Budget:[/cyan] ${cfg.total_budget_usd:.2f}")

    if cfg.products:
        table = Table(title="Products")
        table.add_column(_COL_NAME, style="cyan")
        table.add_column("Weight", style="yellow")
        table.add_column("Max Concurrent")
        table.add_column("Budget Limit")

        for p in cfg.products:
            budget = f"${p.budget_limit_usd:.2f}" if p.budget_limit_usd > 0 else "unlimited"
            table.add_row(p.name, f"{p.weight:.2f}", str(p.max_concurrent), budget)

        console.print(table)

    scheduler = ResourceScheduler(store=store)
    alloc_map = scheduler.get_allocation_status(cfg)

    if alloc_map:
        alloc_table = Table(title="Allocation Status")
        alloc_table.add_column(_COL_PRODUCT, style="cyan")
        alloc_table.add_column("Active", style="yellow")
        alloc_table.add_column("Completed")
        alloc_table.add_column("Budget Used")
        alloc_table.add_column("Utilization")

        for a in alloc_map.values():
            budget_str = f"${a.budget_used_usd:.2f}"
            util_str = f"{a.utilization:.1%}"
            alloc_table.add_row(
                a.product_type, str(a.active_runs), str(a.completed_runs),
                budget_str, util_str,
            )

        console.print(alloc_table)


# -- run ------------------------------------------------------------------


@portfolio_group.command("run")
@click.argument("name")
@click.option("--product", default=None, help="Specific product type to run")
@click.option(_OPT_DB, default=DEFAULT_PORTFOLIO_DB, help=_HELP_DB)
@click.option(_OPT_CONFIG_DIR, default=DEFAULT_PORTFOLIO_CONFIG_DIR, help=_HELP_CONFIG_DIR)
def run_product(name: str, product: str | None, db: str, config_dir: str) -> None:
    """Run next product (or a specific one) from the portfolio."""
    from temper_ai.portfolio.scheduler import ResourceScheduler

    loader = _get_loader(config_dir)
    store = _get_store(db)

    try:
        cfg = loader.load(name)
    except FileNotFoundError:
        console.print(f"[red]Portfolio not found:[/red] {name}")
        raise SystemExit(1)

    scheduler = ResourceScheduler(store=store)

    selected: str
    if product is not None:
        if not scheduler.can_execute(cfg, product):
            console.print(f"[red]Cannot execute:[/red] {product} (capacity or budget exceeded)")
            raise SystemExit(1)
        selected = product
    else:
        next_p = scheduler.next_product(cfg)
        if next_p is None:
            console.print("[yellow]No product eligible for execution[/yellow]")
            return
        selected = next_p

    import uuid

    workflow_id = str(uuid.uuid4())
    scheduler.record_start(selected, workflow_id, portfolio_id=name)
    console.print(f"[green]Started run:[/green] {workflow_id[:_ID_DISPLAY_LEN]} ({selected})")


# -- scorecards -----------------------------------------------------------


@portfolio_group.command("scorecards")
@click.argument("name")
@click.option(_OPT_DB, default=DEFAULT_PORTFOLIO_DB, help=_HELP_DB)
@click.option(_OPT_CONFIG_DIR, default=DEFAULT_PORTFOLIO_CONFIG_DIR, help=_HELP_CONFIG_DIR)
def scorecards(name: str, db: str, config_dir: str) -> None:
    """Show product scorecards for a portfolio."""
    from temper_ai.portfolio.optimizer import PortfolioOptimizer

    loader = _get_loader(config_dir)
    store = _get_store(db)

    try:
        cfg = loader.load(name)
    except FileNotFoundError:
        console.print(f"[red]Portfolio not found:[/red] {name}")
        raise SystemExit(1)

    optimizer = PortfolioOptimizer(store=store)
    cards = optimizer.compute_scorecards(cfg)

    if not cards:
        console.print("[yellow]No scorecards available (no run data)[/yellow]")
        return

    table = Table(title="Product Scorecards")
    table.add_column(_COL_PRODUCT, style="cyan")
    table.add_column("Success Rate")
    table.add_column("Cost Efficiency")
    table.add_column("Trend")
    table.add_column("Utilization")
    table.add_column("Composite", style="yellow")

    for c in cards:
        table.add_row(
            c.product_type,
            f"{c.success_rate:.3f}",
            f"{c.cost_efficiency:.3f}",
            f"{c.trend:+.3f}",
            f"{c.utilization:.3f}",
            f"{c.composite_score:.3f}",
        )

    console.print(table)


# -- recommend -------------------------------------------------------------


@portfolio_group.command("recommend")
@click.argument("name")
@click.option(_OPT_DB, default=DEFAULT_PORTFOLIO_DB, help=_HELP_DB)
@click.option(_OPT_CONFIG_DIR, default=DEFAULT_PORTFOLIO_CONFIG_DIR, help=_HELP_CONFIG_DIR)
def recommend(name: str, db: str, config_dir: str) -> None:
    """Show invest/sunset recommendations for a portfolio."""
    from temper_ai.portfolio.optimizer import PortfolioOptimizer

    loader = _get_loader(config_dir)
    store = _get_store(db)

    try:
        cfg = loader.load(name)
    except FileNotFoundError:
        console.print(f"[red]Portfolio not found:[/red] {name}")
        raise SystemExit(1)

    optimizer = PortfolioOptimizer(store=store)
    cards = optimizer.compute_scorecards(cfg)
    recs = optimizer.recommend(cards)

    if not recs:
        console.print("[yellow]No recommendations available[/yellow]")
        return

    table = Table(title="Recommendations")
    table.add_column(_COL_PRODUCT, style="cyan")
    table.add_column("Action", style="yellow")
    table.add_column("Composite Score")
    table.add_column("Weight Delta")
    table.add_column("Rationale")

    for r in recs:
        table.add_row(
            r.product_type,
            r.action.value,
            f"{r.scorecard.composite_score:.3f}",
            f"{r.suggested_weight_delta:+.2f}",
            r.rationale,
        )

    console.print(table)


# -- components ------------------------------------------------------------


@portfolio_group.command("components")
@click.argument("name")
@click.option(_OPT_DB, default=DEFAULT_PORTFOLIO_DB, help=_HELP_DB)
@click.option(_OPT_CONFIG_DIR, default=DEFAULT_PORTFOLIO_CONFIG_DIR, help=_HELP_CONFIG_DIR)
def components(name: str, db: str, config_dir: str) -> None:
    """Analyze cross-product component sharing."""
    from temper_ai.portfolio.component_analyzer import ComponentAnalyzer

    loader = _get_loader(config_dir)
    store = _get_store(db)

    try:
        cfg = loader.load(name)
    except FileNotFoundError:
        console.print(f"[red]Portfolio not found:[/red] {name}")
        raise SystemExit(1)

    analyzer = ComponentAnalyzer(store=store)
    matches = analyzer.analyze_portfolio(cfg)

    if not matches:
        console.print("[yellow]No shared components detected[/yellow]")
        return

    table = Table(title="Shared Components")
    table.add_column("Source Stage", style="cyan")
    table.add_column("Target Stage", style="cyan")
    table.add_column("Similarity", style="yellow")
    table.add_column("Shared Keys")
    table.add_column("Differing Keys")

    for m in matches:
        table.add_row(
            m.source_stage,
            m.target_stage,
            f"{m.similarity:.3f}",
            ", ".join(m.shared_keys[:5]),  # noqa: scanner: skip-magic
            ", ".join(m.differing_keys[:5]),  # noqa: scanner: skip-magic
        )

    console.print(table)


# -- graph subgroup --------------------------------------------------------


@portfolio_group.group("graph")
def graph_group() -> None:
    """Knowledge graph operations."""


@graph_group.command("stats")
@click.option(_OPT_DB, default=DEFAULT_PORTFOLIO_DB, help=_HELP_DB)
def graph_stats(db: str) -> None:
    """Show knowledge graph statistics."""
    from temper_ai.portfolio.knowledge_graph import KnowledgeQuery

    store = _get_store(db)
    query = KnowledgeQuery(store=store)
    stats = query.concept_stats()

    console.print("\n[cyan]Knowledge Graph Statistics[/cyan]")
    concepts_by_type: dict = stats.get("concepts_by_type", {})
    edges_by_relation: dict = stats.get("edges_by_relation", {})
    console.print("[cyan]Concepts by type:[/cyan]")
    for ctype, count in concepts_by_type.items():
        console.print(f"  {ctype}: {count}")
    console.print("[cyan]Edges by relation:[/cyan]")
    for rel, count in edges_by_relation.items():
        console.print(f"  {rel}: {count}")


@graph_group.command("query")
@click.argument("concept")
@click.option("--depth", default=1, help="BFS traversal depth")
@click.option(_OPT_DB, default=DEFAULT_PORTFOLIO_DB, help=_HELP_DB)
def graph_query(concept: str, depth: int, db: str) -> None:
    """Query related concepts in the knowledge graph."""
    from temper_ai.portfolio.knowledge_graph import KnowledgeQuery

    store = _get_store(db)
    query = KnowledgeQuery(store=store)
    results = query.get_related_concepts(concept, depth=depth)

    if not results:
        console.print(f"[yellow]No results for:[/yellow] {concept}")
        return

    table = Table(title=f"Related Concepts: {concept}")
    table.add_column(_COL_NAME, style="cyan")
    table.add_column("Type")
    table.add_column("Relation", style="yellow")
    table.add_column("Depth")

    for r in results:
        table.add_row(
            r.get("name", ""),
            r.get("concept_type", ""),
            r.get("relation", ""),
            str(r.get("depth", 0)),
        )

    console.print(table)
