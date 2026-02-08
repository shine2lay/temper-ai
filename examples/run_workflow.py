#!/usr/bin/env python3
"""
Run workflow demo script for Milestone 2.

This is a user-facing CLI demo that shows the full workflow execution
with real-time console visualization.

Usage:
    python examples/run_workflow.py configs/workflows/simple_research.yaml
    python examples/run_workflow.py configs/workflows/simple_research.yaml --prompt "Research TypeScript benefits"
    python examples/run_workflow.py configs/workflows/simple_research.yaml --verbose
    python examples/run_workflow.py configs/workflows/simple_research.yaml --output results.json

Requirements:
    - Ollama running: ollama serve
    - Model available: ollama pull llama3.2:3b

DEPENDENCIES:
- m2-04: StandardAgent implementation
- m2-04b: AgentFactory
- m2-05: LangGraph compiler
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Check dependencies
try:
    from src.compiler.engine_registry import EngineRegistry  # m2.5-03
    COMPONENTS_READY = True
except ImportError as e:
    COMPONENTS_READY = False
    IMPORT_ERROR = str(e)

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.compiler.config_loader import ConfigLoader
from src.observability.console import StreamingVisualizer
from src.observability.database import get_session, init_database
from src.observability.models import WorkflowExecution
from src.observability.tracker import ExecutionTracker
from src.tools.calculator import Calculator
from src.tools.file_writer import FileWriter
from src.tools.registry import ToolRegistry
from src.tools.web_scraper import WebScraper

console = Console()


def check_ollama_available() -> bool:
    """Check if Ollama is running."""
    import httpx
    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return response.status_code == 200
    except Exception:
        return False


def setup_database(db_path: Optional[str] = None) -> None:
    """Initialize observability database."""
    if db_path:
        init_database(f"sqlite:///{db_path}")
    else:
        init_database("sqlite:///workflow_execution.db")


def load_workflow_config(workflow_path: str, config_loader: ConfigLoader) -> Dict[str, Any]:
    """Load workflow configuration."""
    # If it's a file path, load directly
    if Path(workflow_path).exists():
        import yaml
        with open(workflow_path) as f:
            return yaml.safe_load(f)

    # Otherwise, assume it's a workflow name
    return config_loader.load_workflow(workflow_path)


def execute_workflow(
    workflow_config: Dict[str, Any],
    input_data: Dict[str, Any],
    tool_registry: ToolRegistry,
    tracker: ExecutionTracker,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Execute workflow with tracking and visualization.

    Args:
        workflow_config: Workflow configuration
        input_data: Input data for workflow
        tool_registry: Tool registry
        tracker: Execution tracker
        verbose: Whether to show verbose output

    Returns:
        Workflow execution result
    """
    workflow_name = workflow_config["workflow"]["name"]

    # Compile workflow
    if verbose:
        console.print("[cyan]Compiling workflow...[/cyan]")

    # Use engine registry to get execution engine
    registry = EngineRegistry()
    engine = registry.get_engine("langgraph", tool_registry=tool_registry)
    compiled = engine.compile(workflow_config)

    if verbose:
        console.print("[green]✓ Workflow compiled[/green]")

    try:
        # Execute with tracking
        with tracker.track_workflow(
            workflow_name=workflow_name,
            workflow_config=workflow_config,
            trigger_type="manual",
            environment="demo"
        ) as workflow_id:

            if verbose:
                console.print(f"[cyan]Executing workflow: {workflow_id}[/cyan]")

            # Start streaming visualizer with workflow_id
            visualizer = StreamingVisualizer(workflow_id=workflow_id)
            visualizer.start()

            try:
                # Execute compiled workflow
                result = compiled.invoke({
                    **input_data,
                    "tracker": tracker,
                    "workflow_id": workflow_id,
                    "visualizer": visualizer
                })

                return {
                    "workflow_id": workflow_id,
                    "result": result,
                    "status": "success"
                }

            finally:
                visualizer.stop()

    except Exception as e:
        console.print(f"[red]✗ Workflow failed: {e}[/red]")
        import traceback
        if verbose:
            traceback.print_exc()
        return {
            "workflow_id": None,
            "result": None,
            "status": "failed",
            "error": str(e)
        }


def display_summary(workflow_id: str, verbose: bool = False):
    """Display execution summary from database."""
    from sqlmodel import select

    with get_session() as session:
        statement = select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
        workflow_exec = session.exec(statement).first()

        if not workflow_exec:
            console.print("[red]No execution data found[/red]")
            return

        # Create summary panel
        table = Table(box=box.ROUNDED, show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Workflow", workflow_exec.workflow_name)
        table.add_row("Status", workflow_exec.status.upper())
        table.add_row("Duration", f"{workflow_exec.duration_seconds:.2f}s")
        table.add_row("LLM Calls", str(workflow_exec.total_llm_calls))
        table.add_row("Tool Calls", str(workflow_exec.total_tool_calls))
        table.add_row("Total Tokens", str(workflow_exec.total_tokens))
        table.add_row("Cost", f"${workflow_exec.total_cost_usd:.6f}")

        console.print()
        console.print(Panel(
            table,
            title="[bold]Execution Summary[/bold]",
            border_style="green"
        ))

        if verbose:
            # Show detailed execution data
            console.print()
            console.print("[bold cyan]Detailed Execution:[/bold cyan]")
            console.print(f"Workflow ID: {workflow_exec.id}")
            console.print(f"Started: {workflow_exec.start_time}")
            console.print(f"Ended: {workflow_exec.end_time}")
            if workflow_exec.error_message:
                console.print(f"[red]Error: {workflow_exec.error_message}[/red]")


def create_gantt_chart(workflow_id: str, auto_open: bool = True) -> bool:
    """Create and optionally open hierarchical Gantt chart."""
    try:
        console.print()
        console.print("[cyan]📊 Creating hierarchical Gantt chart...[/cyan]")

        from examples.export_waterfall import export_waterfall_trace
        from src.observability.visualize_trace import visualize_trace

        # Export trace data
        trace = export_waterfall_trace(workflow_id)

        if "error" in trace:
            console.print(f"[yellow]⚠️  Could not export trace: {trace['error']}[/yellow]")
            return False

        # Create visualization
        output_file = f"{trace['name'].replace(' ', '_').lower()}_gantt.html"
        visualize_trace(trace, output_file=output_file, auto_open=auto_open)

        console.print(f"[green]✓ Interactive Gantt chart: {output_file}[/green]")
        return True

    except ImportError:
        console.print("[yellow]⚠️  Plotly not installed. Install with: pip install plotly[/yellow]")
        return False
    except Exception as e:
        console.print(f"[yellow]⚠️  Could not create Gantt chart: {e}[/yellow]")
        return False


def save_results(result: Dict[str, Any], output_path: str):
    """Save execution results to file."""
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2, default=str)
    console.print(f"[green]✓ Results saved to {output_path}[/green]")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run Meta-Autonomous Framework workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python examples/run_workflow.py configs/workflows/simple_research.yaml
  python examples/run_workflow.py simple_research --prompt "Research TypeScript"
  python examples/run_workflow.py simple_research --verbose --output results.json

Requirements:
  - Ollama running: ollama serve
  - Model available: ollama pull llama3.2:3b
        """
    )

    parser.add_argument(
        "workflow",
        help="Workflow config file path or workflow name"
    )
    parser.add_argument(
        "--prompt",
        "--topic",
        dest="topic",
        help="Research topic or prompt (default: 'Benefits of Python typing')"
    )
    parser.add_argument(
        "--depth",
        choices=["surface", "medium", "deep"],
        default="surface",
        help="Analysis depth (default: surface)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show verbose output"
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Save results to JSON file"
    )
    parser.add_argument(
        "--db",
        help="Database path (default: workflow_execution.db)"
    )

    args = parser.parse_args()

    # Check dependencies
    if not COMPONENTS_READY:
        console.print(Panel(
            f"[red bold]ERROR: M2 components not ready[/red bold]\n\n"
            f"Missing: {IMPORT_ERROR}\n\n"
            f"This demo requires:\n"
            f"  - m2-04: StandardAgent implementation\n"
            f"  - m2-04b: AgentFactory\n"
            f"  - m2.5-03: EngineRegistry\n\n"
            f"Please wait for these tasks to complete.",
            title="Dependency Error",
            border_style="red"
        ))
        return 1

    # Check Ollama
    if not check_ollama_available():
        console.print(Panel(
            "[yellow bold]WARNING: Ollama not detected[/yellow bold]\n\n"
            "Please start Ollama:\n"
            "  ollama serve\n\n"
            "And ensure model is available:\n"
            "  ollama pull llama3.2:3b",
            title="Ollama Required",
            border_style="yellow"
        ))
        response = input("Continue anyway? [y/N]: ")
        if response.lower() != 'y':
            return 1

    # Display header
    console.print()
    console.print(Panel(
        "[bold cyan]Meta-Autonomous Framework[/bold cyan]\n"
        "Workflow Execution Demo",
        border_style="cyan"
    ))
    console.print()

    try:
        # Setup
        if args.verbose:
            console.print("[cyan]Initializing...[/cyan]")

        setup_database(args.db)
        config_loader = ConfigLoader(config_root="configs")

        # Register tools
        tool_registry = ToolRegistry()
        tool_registry.register(Calculator())
        tool_registry.register(WebScraper())
        tool_registry.register(FileWriter())

        if args.verbose:
            console.print(f"[green]✓ Registered {len(tool_registry)} tools[/green]")

        # Load workflow
        if args.verbose:
            console.print(f"[cyan]Loading workflow: {args.workflow}[/cyan]")

        workflow_config = load_workflow_config(args.workflow, config_loader)

        if args.verbose:
            console.print("[green]✓ Workflow loaded[/green]")

        # Prepare input
        input_data = {
            "topic": args.topic or "Benefits of Python typing",
            "depth": args.depth
        }

        if args.verbose:
            console.print(f"[cyan]Topic: {input_data['topic']}[/cyan]")
            console.print(f"[cyan]Depth: {input_data['depth']}[/cyan]")

        # Execute
        tracker = ExecutionTracker()

        console.print()
        console.print("[bold green]Starting workflow execution...[/bold green]")
        console.print()

        result = execute_workflow(
            workflow_config=workflow_config,
            input_data=input_data,
            tool_registry=tool_registry,
            tracker=tracker,
            verbose=args.verbose
        )

        # Display results
        if result["status"] == "success":
            console.print()
            console.print("[bold green]✓ Workflow completed successfully![/bold green]")

            # Display summary
            display_summary(result["workflow_id"], verbose=args.verbose)

            # Create Gantt chart visualization
            create_gantt_chart(result["workflow_id"], auto_open=True)

            # Save results if requested
            if args.output:
                save_results(result, args.output)

            return 0

        else:
            console.print()
            console.print(f"[bold red]✗ Workflow failed: {result.get('error', 'Unknown error')}[/bold red]")
            return 1

    except KeyboardInterrupt:
        console.print()
        console.print("[yellow]Workflow interrupted by user[/yellow]")
        return 130

    except Exception as e:
        console.print()
        console.print(f"[red bold]ERROR: {e}[/red bold]")
        if args.verbose:
            import traceback
            console.print()
            console.print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
