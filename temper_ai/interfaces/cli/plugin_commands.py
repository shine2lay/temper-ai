"""CLI commands for the plugin system."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from temper_ai.interfaces.cli.plugin_constants import (
    COL_FRAMEWORK,
    COL_INSTALL,
    COL_STATUS,
    ERR_SOURCE_NOT_FOUND,
    ERR_UNKNOWN_FRAMEWORK,
    STATUS_AVAILABLE,
    STATUS_NOT_INSTALLED,
)


@click.group("plugin")
def plugin_group() -> None:
    """Manage external agent framework plugins."""


@plugin_group.command("list")
def plugin_list() -> None:
    """List available plugin frameworks and their install status."""
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    from temper_ai.plugins.registry import list_plugins  # lazy import

    console = Console()
    table = Table(title="Agent Plugins")
    table.add_column(COL_FRAMEWORK, style="cyan")
    table.add_column(COL_STATUS, style="green")
    table.add_column(COL_INSTALL, style="dim")

    plugins = list_plugins()
    for name, info in sorted(plugins.items()):
        status = STATUS_AVAILABLE if info["available"] else STATUS_NOT_INSTALLED
        style = "green" if info["available"] else "yellow"
        # Use Text() to avoid Rich markup interpretation of brackets
        hint = Text(info["install_hint"])
        table.add_row(name, f"[{style}]{status}[/{style}]", hint)

    console.print(table)


@plugin_group.command("import")
@click.argument("framework")
@click.argument("source_path", type=click.Path(exists=False))
@click.option(
    "--output", "-o",
    type=click.Path(),
    default=".",
    help="Output directory for generated config files",
)
def plugin_import(framework: str, source_path: str, output: str) -> None:
    """Import agents from an external framework config file."""
    from rich.console import Console

    from temper_ai.plugins.constants import ALL_PLUGIN_TYPES  # lazy import

    console = Console()
    src = Path(source_path)

    if not src.exists():
        console.print(f"[red]{ERR_SOURCE_NOT_FOUND.format(source_path)}[/red]")
        raise SystemExit(1)

    if framework not in ALL_PLUGIN_TYPES:
        supported = ", ".join(sorted(ALL_PLUGIN_TYPES))
        console.print(f"[red]{ERR_UNKNOWN_FRAMEWORK.format(framework, supported)}[/red]")
        raise SystemExit(1)

    _do_import(framework, src, Path(output), console)


def _do_import(
    framework: str,
    src: Path,
    output_dir: Path,
    console: Any,
) -> None:
    """Execute the import for a specific framework."""
    from temper_ai.agent.utils.agent_factory import AgentFactory
    from temper_ai.plugins._import_helpers import write_agent_yaml
    from temper_ai.plugins.registry import ensure_plugin_registered

    if not ensure_plugin_registered(framework):
        console.print(
            f"[red]Cannot import '{framework}': required package not installed. "
            f"Install with: pip install 'temper-ai[{framework}]'[/red]"
        )
        raise SystemExit(1)

    adapter_cls = AgentFactory.list_types()[framework]
    configs = adapter_cls.translate_config(src)  # type: ignore[attr-defined]

    if not configs:
        console.print("[yellow]No agents found in source file.[/yellow]")
        return

    written = write_agent_yaml(configs, output_dir)
    for path in written:
        console.print(f"[green]Written: {path}[/green]")
    console.print(f"\n[bold]Imported {len(written)} agent(s) from {framework}[/bold]")
