"""CLI command for project scaffolding.

Usage:
    temper-ai create <project_name> --type <product_type>
"""
import logging
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from temper_ai.interfaces.cli.constants import (
    CLI_OPTION_CONFIG_ROOT,
    DEFAULT_CONFIG_ROOT,
    ENV_VAR_CONFIG_ROOT,
    HELP_CONFIG_ROOT,
)
from temper_ai.interfaces.cli.create_constants import (
    DEFAULT_OUTPUT_DIR,
    ENV_EXAMPLE_TEMPLATE,
    ERR_DIR_EXISTS,
    ERR_TEMPLATE_NOT_FOUND,
    GITIGNORE_TEMPLATE,
    README_TEMPLATE,
)

console = Console()
logger = logging.getLogger(__name__)


def _write_boilerplate(project_dir: Path, project_name: str, product_type: str) -> None:
    """Write .gitignore, .env.example, and README.md to project directory."""
    (project_dir / ".gitignore").write_text(GITIGNORE_TEMPLATE, encoding="utf-8")
    (project_dir / ".env.example").write_text(ENV_EXAMPLE_TEMPLATE, encoding="utf-8")
    readme = README_TEMPLATE.format(project_name=project_name, product_type=product_type)
    (project_dir / "README.md").write_text(readme, encoding="utf-8")


def _generate_from_template(
    project_dir: Path,
    product_type: str,
    project_name: str,
    provider: Optional[str],
    model: Optional[str],
    config_root: str,
) -> Path:
    """Generate workflow configs from template into project directory."""
    from temper_ai.workflow.templates.generator import TemplateGenerator
    from temper_ai.workflow.templates.registry import TemplateRegistry

    templates_dir = Path(config_root) / "templates"
    registry = TemplateRegistry(templates_dir=templates_dir)
    generator = TemplateGenerator(registry=registry)

    inference_overrides: dict = {}
    if provider:
        inference_overrides["provider"] = provider
    if model:
        inference_overrides["model"] = model

    return generator.generate(
        product_type=product_type,
        project_name=project_name,
        output_dir=project_dir,
        inference_overrides=inference_overrides or None,
    )


@click.command("create")
@click.argument("project_name")
@click.option("--type", "product_type", required=True, help="Template product type (e.g., web_app, api, cli_tool)")
@click.option("--provider", default=None, help="LLM provider override")
@click.option("--model", default=None, help="Model name override")
@click.option("--output-dir", default=DEFAULT_OUTPUT_DIR, show_default=True, help="Parent directory for project")
@click.option("--force", is_flag=True, help="Overwrite existing directory")
@click.option(
    CLI_OPTION_CONFIG_ROOT,
    default=DEFAULT_CONFIG_ROOT,
    show_default=True,
    envvar=ENV_VAR_CONFIG_ROOT,
    help=HELP_CONFIG_ROOT,
)
def create(
    project_name: str,
    product_type: str,
    provider: Optional[str],
    model: Optional[str],
    output_dir: str,
    force: bool,
    config_root: str,
) -> None:
    """Scaffold a new Temper AI project from a template."""
    from temper_ai.workflow.templates.registry import TemplateNotFoundError

    project_dir = Path(output_dir) / project_name

    if project_dir.exists() and not force:
        console.print(f"[red]Error:[/red] {ERR_DIR_EXISTS.format(path=project_dir)}")
        raise SystemExit(1)

    project_dir.mkdir(parents=True, exist_ok=True)

    try:
        workflow_path = _generate_from_template(
            project_dir, product_type, project_name, provider, model, config_root,
        )
        _write_boilerplate(project_dir, project_name, product_type)
    except TemplateNotFoundError:
        console.print(f"[red]Error:[/red] {ERR_TEMPLATE_NOT_FOUND.format(product_type=product_type)}")
        raise SystemExit(1)
    except (OSError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    console.print(f"[green]Project created:[/green] {project_dir}")
    console.print(f"  Workflow: {workflow_path}")
    console.print(f"  Type: {product_type}")
    console.print("\nNext steps:")
    console.print(f"  cd {project_dir}")
    console.print("  cp .env.example .env")
    console.print(f"  temper-ai run {workflow_path.name} --show-details")
