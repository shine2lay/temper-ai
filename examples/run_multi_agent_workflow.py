#!/usr/bin/env python3
"""Multi-Agent Workflow Demo Script - M3 Features

This script demonstrates M3 multi-agent collaboration features:
- Parallel agent execution
- Consensus synthesis
- Debate-based decision making
- Convergence detection

Usage:
    python examples/run_multi_agent_workflow.py parallel-research
    python examples/run_multi_agent_workflow.py debate-decision
    python examples/run_multi_agent_workflow.py --list

Requirements:
    - Ollama running locally (or update configs for other LLM providers)
    - Database initialized (run init_database() if needed)
"""

import sys
import os
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.compiler.config_loader import ConfigLoader
from src.compiler.langgraph_compiler import LangGraphCompiler
from src.observability.tracker import ExecutionTracker
from src.observability.database import init_database
from src.observability.visualize_trace import create_gantt_chart, print_console_gantt

console = Console()


def print_banner():
    """Print demo banner."""
    console.print(Panel.fit(
        "[bold cyan]M3 Multi-Agent Workflow Demo[/bold cyan]\n"
        "Demonstrating parallel execution, consensus, and debate",
        border_style="cyan"
    ))


def list_workflows():
    """List available M3 demo workflows."""
    table = Table(title="Available M3 Workflows", show_header=True)
    table.add_column("Name", style="cyan", width=20)
    table.add_column("Description", style="white", width=50)
    table.add_column("Features", style="yellow", width=30)

    workflows = [
        (
            "parallel-research",
            "3 agents research in parallel, synthesize via consensus",
            "Parallel, Consensus"
        ),
        (
            "debate-decision",
            "Multi-round debate with convergence detection",
            "Debate, Convergence"
        ),
    ]

    for name, desc, features in workflows:
        table.add_row(name, desc, features)

    console.print(table)
    console.print("\n[cyan]Usage:[/cyan] python examples/run_multi_agent_workflow.py <workflow-name>\n")


def run_parallel_research():
    """Run parallel multi-agent research workflow."""
    console.print("\n[bold cyan]Running: Parallel Multi-Agent Research[/bold cyan]\n")

    # Initialize database
    console.print("[yellow]Initializing database...[/yellow]")
    init_database("sqlite:///observability.db")

    # Load workflow
    console.print("[yellow]Loading workflow config...[/yellow]")
    config_loader = ConfigLoader()
    workflow_config = config_loader.load_workflow("multi_agent_research")

    # Create compiler and tracker
    console.print("[yellow]Compiling workflow...[/yellow]")
    compiler = LangGraphCompiler(config_loader=config_loader)
    tracker = ExecutionTracker()

    # Compile workflow
    graph = compiler.compile(workflow_config)

    # Prepare inputs
    inputs = {
        "topic": "Electric Vehicle Market Analysis",
        "focus_areas": ["Market Size", "Key Players", "Technology Trends"],
        "depth": "comprehensive",
        "tracker": tracker,
        "config_loader": config_loader
    }

    console.print("\n[bold green]Executing workflow with 3 parallel agents...[/bold green]")
    console.print("[dim]Agents: Market Researcher, Competitor Researcher, User Researcher[/dim]\n")

    # Execute
    try:
        result = graph.invoke(inputs)

        # Display results
        console.print("\n[bold green]✓ Workflow completed![/bold green]\n")

        # Show synthesized output
        if "stage_outputs" in result and "parallel_research" in result["stage_outputs"]:
            console.print(Panel(
                str(result["stage_outputs"]["parallel_research"]),
                title="[cyan]Synthesized Insights (Consensus)[/cyan]",
                border_style="cyan"
            ))

        # Show agent outputs if available
        # Note: In real implementation, these would be in result metadata

        # Show observability
        console.print("\n[bold cyan]Execution Trace:[/bold cyan]")
        if tracker.execution_id:
            execution = tracker.get_execution(tracker.execution_id)
            if execution:
                trace = tracker.get_full_trace(tracker.execution_id)
                print_console_gantt(trace)

                # Generate HTML Gantt chart
                html_path = f"m3_parallel_research_{tracker.execution_id}.html"
                create_gantt_chart(trace, html_path)
                console.print(f"\n[green]✓ Gantt chart saved to:[/green] {html_path}")

    except Exception as e:
        console.print(f"\n[bold red]❌ Error:[/bold red] {str(e)}", markup=False)
        import traceback
        console.print(traceback.format_exc(), markup=False, highlight=False)


def run_debate_decision():
    """Run debate-based decision workflow."""
    console.print("\n[bold cyan]Running: Debate-Based Decision Making[/bold cyan]\n")

    # Initialize database
    console.print("[yellow]Initializing database...[/yellow]")
    init_database("sqlite:///observability.db")

    # Load workflow
    console.print("[yellow]Loading workflow config...[/yellow]")
    config_loader = ConfigLoader()
    workflow_config = config_loader.load_workflow("debate_decision")

    # Create compiler and tracker
    console.print("[yellow]Compiling workflow...[/yellow]")
    compiler = LangGraphCompiler(config_loader=config_loader)
    tracker = ExecutionTracker()

    # Compile workflow
    graph = compiler.compile(workflow_config)

    # Prepare inputs
    inputs = {
        "decision_prompt": "Should we adopt a microservices architecture?",
        "context": "Our team has 10 engineers. Current monolith is becoming hard to maintain. "
                   "We deploy 2-3 times per week. Key concern is operational complexity.",
        "options": ["Adopt microservices", "Improve monolith", "Hybrid approach"],
        "max_rounds": 3,
        "tracker": tracker,
        "config_loader": config_loader
    }

    console.print("\n[bold green]Starting debate with 3 agents...[/bold green]")
    console.print("[dim]Agents: Advocate, Skeptic, Analyst[/dim]")
    console.print("[dim]Max rounds: 3, Convergence threshold: 80%[/dim]\n")

    # Execute
    try:
        result = graph.invoke(inputs)

        # Display results
        console.print("\n[bold green]✓ Debate completed![/bold green]\n")

        # Show final decision
        if "stage_outputs" in result and "debate_and_decide" in result["stage_outputs"]:
            console.print(Panel(
                str(result["stage_outputs"]["debate_and_decide"]),
                title="[cyan]Final Decision[/cyan]",
                border_style="cyan"
            ))

        # Show observability
        console.print("\n[bold cyan]Execution Trace:[/bold cyan]")
        if tracker.execution_id:
            execution = tracker.get_execution(tracker.execution_id)
            if execution:
                trace = tracker.get_full_trace(tracker.execution_id)
                print_console_gantt(trace)

                # Generate HTML Gantt chart
                html_path = f"m3_debate_decision_{tracker.execution_id}.html"
                create_gantt_chart(trace, html_path)
                console.print(f"\n[green]✓ Gantt chart saved to:[/green] {html_path}")

    except Exception as e:
        console.print(f"\n[bold red]❌ Error:[/bold red] {str(e)}", markup=False)
        import traceback
        console.print(traceback.format_exc(), markup=False, highlight=False)


def main():
    """Main entry point."""
    print_banner()

    if len(sys.argv) < 2 or sys.argv[1] in ["--help", "-h"]:
        list_workflows()
        return

    workflow = sys.argv[1].lower()

    if workflow in ["--list", "-l"]:
        list_workflows()
        return

    # Route to workflow
    if workflow == "parallel-research":
        run_parallel_research()
    elif workflow == "debate-decision":
        run_debate_decision()
    else:
        console.print(f"[bold red]Unknown workflow:[/bold red] {workflow}")
        console.print("[yellow]Run with --list to see available workflows[/yellow]")
        sys.exit(1)

    console.print("\n[bold green]Demo complete![/bold green] 🎉\n")


if __name__ == "__main__":
    main()
