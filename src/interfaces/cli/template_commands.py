"""CLI commands for multi-product templates.

Usage:
    maf template list         List available product templates
    maf template info <type>  Show template details and quality gates
    maf template create       Generate project configs from a template
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

import click
from rich.console import Console

if TYPE_CHECKING:
    from src.workflow.templates._schemas import TemplateManifest, TemplateQualityGates
    from src.workflow.templates.registry import TemplateRegistry
from rich.table import Table

from src.interfaces.cli.constants import (
    CLI_OPTION_CONFIG_ROOT,
    DEFAULT_CONFIG_ROOT,
    ENV_VAR_CONFIG_ROOT,
    HELP_CONFIG_ROOT,
)

console = Console()

# Column name constants
_COL_PRODUCT_TYPE = "Product Type"
_COL_NAME = "Name"
_COL_STAGES = "Stages"
_COL_TAGS = "Tags"
_COL_FIELD = "Field"
_COL_VALUE = "Value"


def _get_registry(config_root: str) -> "TemplateRegistry":
    """Create a TemplateRegistry from config root."""
    from src.workflow.templates.registry import TemplateRegistry

    templates_dir = Path(config_root) / "templates"
    return TemplateRegistry(templates_dir=templates_dir)


@click.group("template")
def template_group() -> None:
    """Multi-product templates -- list, inspect, generate."""


@template_group.command("list")
@click.option(
    CLI_OPTION_CONFIG_ROOT,
    default=DEFAULT_CONFIG_ROOT,
    show_default=True,
    envvar=ENV_VAR_CONFIG_ROOT,
    help=HELP_CONFIG_ROOT,
)
def list_templates(config_root: str) -> None:
    """List available product templates."""
    registry = _get_registry(config_root)
    templates = registry.list_templates()

    if not templates:
        console.print("[yellow]No templates found[/yellow]")
        return

    table = Table(title=f"Available Templates ({len(templates)})")
    table.add_column(_COL_PRODUCT_TYPE, style="cyan")
    table.add_column(_COL_NAME)
    table.add_column(_COL_STAGES, style="yellow")
    table.add_column(_COL_TAGS)
    for t in templates:
        table.add_row(
            t.product_type,
            t.name,
            ", ".join(t.stages),
            ", ".join(t.tags),
        )
    console.print(table)


@template_group.command("info")
@click.argument("product_type")
@click.option(
    CLI_OPTION_CONFIG_ROOT,
    default=DEFAULT_CONFIG_ROOT,
    show_default=True,
    envvar=ENV_VAR_CONFIG_ROOT,
    help=HELP_CONFIG_ROOT,
)
def info(product_type: str, config_root: str) -> None:
    """Show template details and quality gates."""
    from src.workflow.templates.registry import TemplateNotFoundError

    registry = _get_registry(config_root)
    try:
        manifest = registry.get_manifest(product_type)
    except TemplateNotFoundError:
        console.print(f"[red]Template not found:[/red] {product_type}")
        raise SystemExit(1)

    _print_manifest_table(manifest)
    _print_quality_gates_table(manifest.quality_gates)


def _print_manifest_table(manifest: TemplateManifest) -> None:
    """Print manifest details as a Rich table."""
    table = Table(title=f"Template: {manifest.name}")
    table.add_column(_COL_FIELD, style="cyan")
    table.add_column(_COL_VALUE)
    table.add_row("Product Type", manifest.product_type)
    table.add_row("Description", manifest.description)
    table.add_row("Version", manifest.version)
    table.add_row("Stages", ", ".join(manifest.stages))
    table.add_row("Required Inputs", ", ".join(manifest.required_inputs))
    table.add_row("Optional Inputs", ", ".join(manifest.optional_inputs))
    table.add_row("Tags", ", ".join(manifest.tags))
    console.print(table)


def _print_quality_gates_table(qg: TemplateQualityGates) -> None:
    """Print quality gates as a Rich table."""
    qg_table = Table(title="Quality Gates")
    qg_table.add_column(_COL_FIELD, style="cyan")
    qg_table.add_column(_COL_VALUE)
    qg_table.add_row("Enabled", str(qg.enabled))
    qg_table.add_row("Min Confidence", f"{qg.min_confidence:.2f}")
    qg_table.add_row("Require Citations", str(qg.require_citations))
    qg_table.add_row("On Failure", qg.on_failure)
    qg_table.add_row("Max Retries", str(qg.max_retries))
    qg_table.add_row("Custom Checks", ", ".join(qg.custom_checks))
    console.print(qg_table)


@template_group.command("create")
@click.option("--type", "product_type", required=True, help="Template product type")
@click.option("--name", "project_name", required=True, help="Project name")
@click.option("--output", "output_dir", default=None, help="Output directory")
@click.option("--provider", default=None, help="LLM provider override")
@click.option("--model", default=None, help="Model name override")
@click.option("--base-url", default=None, help="Base URL override")
@click.option(
    CLI_OPTION_CONFIG_ROOT,
    default=DEFAULT_CONFIG_ROOT,
    show_default=True,
    envvar=ENV_VAR_CONFIG_ROOT,
    help=HELP_CONFIG_ROOT,
)
def create(
    product_type: str,
    project_name: str,
    output_dir: Optional[str],
    provider: Optional[str],
    model: Optional[str],
    base_url: Optional[str],
    config_root: str,
) -> None:
    """Generate project configs from a template."""
    from src.workflow.templates.generator import TemplateGenerator
    from src.workflow.templates.registry import TemplateNotFoundError

    registry = _get_registry(config_root)
    generator = TemplateGenerator(registry=registry)

    inference_overrides = _build_inference_overrides(provider, model, base_url)
    out = Path(output_dir) if output_dir else Path(config_root)

    try:
        result_path = generator.generate(
            product_type=product_type,
            project_name=project_name,
            output_dir=out,
            inference_overrides=inference_overrides or None,
        )
        console.print(f"[green]Generated:[/green] {result_path}")
    except TemplateNotFoundError:
        console.print(f"[red]Template not found:[/red] {product_type}")
        raise SystemExit(1)
    except (OSError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)


def _build_inference_overrides(
    provider: Optional[str],
    model: Optional[str],
    base_url: Optional[str],
) -> dict:
    """Build inference overrides dict from optional CLI args."""
    overrides: dict = {}
    if provider:
        overrides["provider"] = provider
    if model:
        overrides["model"] = model
    if base_url:
        overrides["base_url"] = base_url
    return overrides
