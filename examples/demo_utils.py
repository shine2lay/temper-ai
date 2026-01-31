"""
Shared utilities for demo scripts.

Common formatting, display, and helper functions used across demo scripts.
"""
from typing import Dict, Any, Optional
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()


def print_section(title: str, char: str = "=", width: int = 60) -> None:
    """
    Print a formatted section header.

    Args:
        title: Section title
        char: Character to use for border (default: "=")
        width: Total width of border (default: 60)

    Example:
        >>> print_section("My Section")
        ============================================================
          My Section
        ============================================================
    """
    print(f"\n{char * width}")
    print(f"  {title}")
    print(char * width)


def print_rich_section(title: str, subtitle: Optional[str] = None) -> None:
    """
    Print a Rich-formatted section header.

    Args:
        title: Section title
        subtitle: Optional subtitle

    Example:
        >>> print_rich_section("Configuration", "Loading configs from disk")
    """
    console.print()
    if subtitle:
        console.print(f"[bold cyan]{title}[/bold cyan] - {subtitle}")
    else:
        console.print(f"[bold cyan]{title}[/bold cyan]")
    console.print()


def create_metrics_table(metrics: Dict[str, Any], title: str = "Metrics") -> Table:
    """
    Create a Rich table for displaying metrics.

    Args:
        metrics: Dict of metric name -> value
        title: Table title

    Returns:
        Rich Table object

    Example:
        >>> metrics = {"Duration": "5.2s", "Tokens": 1234, "Cost": "$0.05"}
        >>> table = create_metrics_table(metrics)
        >>> console.print(table)
    """
    table = Table(box=box.ROUNDED, show_header=False, title=title)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    for key, value in metrics.items():
        table.add_row(key, str(value))

    return table


def print_metrics(metrics: Dict[str, Any], title: str = "Metrics") -> None:
    """
    Print metrics in a Rich table.

    Args:
        metrics: Dict of metric name -> value
        title: Table title
    """
    table = create_metrics_table(metrics, title)
    console.print(table)


def print_success(message: str) -> None:
    """
    Print a success message with green checkmark.

    Args:
        message: Success message
    """
    console.print(f"[green]✓ {message}[/green]")


def print_error(message: str) -> None:
    """
    Print an error message with red X.

    Args:
        message: Error message
    """
    console.print(f"[red]✗ {message}[/red]")


def print_warning(message: str) -> None:
    """
    Print a warning message with yellow icon.

    Args:
        message: Warning message
    """
    console.print(f"[yellow]⚠️  {message}[/yellow]")


def print_info(message: str) -> None:
    """
    Print an info message with blue icon.

    Args:
        message: Info message
    """
    console.print(f"[cyan]ℹ️  {message}[/cyan]")


def create_summary_panel(
    title: str,
    content: str,
    border_style: str = "green"
) -> Panel:
    """
    Create a Rich panel for summary/result display.

    Args:
        title: Panel title
        content: Panel content (can be Rich markup)
        border_style: Border color (green, red, yellow, cyan)

    Returns:
        Rich Panel object

    Example:
        >>> panel = create_summary_panel(
        ...     "Execution Complete",
        ...     "All tests passed!\\nDuration: 5.2s"
        ... )
        >>> console.print(panel)
    """
    return Panel(
        content,
        title=f"[bold]{title}[/bold]",
        border_style=border_style
    )


def print_summary_panel(
    title: str,
    content: str,
    border_style: str = "green"
) -> None:
    """
    Print a Rich panel for summary/result display.

    Args:
        title: Panel title
        content: Panel content (can be Rich markup)
        border_style: Border color (green, red, yellow, cyan)
    """
    panel = create_summary_panel(title, content, border_style)
    console.print(panel)


def get_project_root() -> Path:
    """
    Get project root directory.

    Returns:
        Path to project root

    Example:
        >>> root = get_project_root()
        >>> configs = root / "configs"
    """
    # Assume this file is in examples/, so parent is project root
    return Path(__file__).parent.parent


def format_duration(seconds: float) -> str:
    """
    Format duration in human-readable format.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration string

    Example:
        >>> format_duration(125.5)
        "2m 5.5s"
        >>> format_duration(5.234)
        "5.23s"
        >>> format_duration(0.123)
        "123ms"
    """
    if seconds < 1:
        return f"{int(seconds * 1000)}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    else:
        minutes = int(seconds // 60)
        remaining_seconds = seconds % 60
        return f"{minutes}m {remaining_seconds:.1f}s"


def format_cost(cost_usd: float) -> str:
    """
    Format cost in USD.

    Args:
        cost_usd: Cost in USD

    Returns:
        Formatted cost string

    Example:
        >>> format_cost(0.00123)
        "$0.0012"
        >>> format_cost(1.5)
        "$1.50"
    """
    if cost_usd < 0.01:
        return f"${cost_usd:.4f}"
    else:
        return f"${cost_usd:.2f}"


def format_tokens(tokens: int) -> str:
    """
    Format token count with thousands separator.

    Args:
        tokens: Number of tokens

    Returns:
        Formatted token string

    Example:
        >>> format_tokens(12345)
        "12,345"
    """
    return f"{tokens:,}"


def print_demo_header(demo_name: str, description: str) -> None:
    """
    Print a formatted demo header.

    Args:
        demo_name: Name of the demo
        description: Brief description
    """
    console.print()
    panel = Panel(
        f"[bold cyan]{demo_name}[/bold cyan]\n{description}",
        border_style="cyan",
        box=box.DOUBLE
    )
    console.print(panel)
    console.print()


def print_demo_footer(success: bool = True) -> None:
    """
    Print a formatted demo footer.

    Args:
        success: Whether demo completed successfully
    """
    console.print()
    if success:
        console.print("[bold green]✅ Demo completed successfully![/bold green]")
    else:
        console.print("[bold red]❌ Demo failed![/bold red]")
    console.print()
