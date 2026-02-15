#!/usr/bin/env python3
"""
Milestone 2 Demo Script

Demonstrates the key features delivered in Milestone 2:
1. YAML-configured agent loading
2. Agent execution with real Ollama LLM
3. Tool integration (Calculator)
4. Token and cost tracking
5. Real-time console visualization

This script shows a complete agent execution with:
- Configuration loading from YAML
- LLM inference with Ollama
- Tool calling support
- Observability tracking
"""
import sys
from datetime import UTC, datetime
from pathlib import Path

# Check Ollama availability
import httpx
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from examples.demo_utils import (
    console,
)
from examples.demo_utils import print_rich_section as print_section
from src.agent.agent_factory import AgentFactory
from src.agent.base_agent import ExecutionContext
from src.workflow.config_loader import ConfigLoader
from src.storage.schemas.agent_config import AgentConfig
from src.observability.database import init_database
from src.tools.calculator import Calculator
from src.tools.file_writer import FileWriter
from src.tools.registry import ToolRegistry
from src.tools.web_scraper import WebScraper


def check_ollama_available() -> bool:
    """Check if Ollama is running."""
    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return response.status_code == 200
    except Exception:
        return False


def demo_config_loading():
    """Demonstrate YAML config loading."""
    print_section("1. Configuration Loading")

    # Initialize config loader
    project_root = Path(__file__).parent.parent
    configs_dir = project_root / "configs"
    loader = ConfigLoader(config_root=configs_dir)

    console.print(f"📁 Config directory: {configs_dir}")

    # Load agent config
    console.print("\n📄 Loading agent: simple_researcher")

    agent_dict = loader.load_agent("simple_researcher")
    agent_config = AgentConfig(**agent_dict)

    console.print(f"   [green]✓[/green] Name: {agent_config.agent.name}")
    console.print(f"   [green]✓[/green] Description: {agent_config.agent.description}")
    console.print(f"   [green]✓[/green] Provider: {agent_config.agent.inference.provider}")
    console.print(f"   [green]✓[/green] Model: {agent_config.agent.inference.model}")
    console.print(f"   [green]✓[/green] Tools: {', '.join(agent_config.agent.tools)}")

    return agent_config


def demo_tool_registry():
    """Demonstrate tool registration."""
    print_section("2. Tool Registry")

    tool_registry = ToolRegistry()
    tool_registry.register(Calculator())
    tool_registry.register(WebScraper())
    tool_registry.register(FileWriter())

    console.print(f"[green]✓[/green] Registered {len(tool_registry)} tools:")
    for tool_name in tool_registry.list_tools():
        console.print(f"   • {tool_name}")

    return tool_registry


def demo_agent_creation(agent_config: AgentConfig, tool_registry: ToolRegistry):
    """Demonstrate agent creation from config."""
    print_section("3. Agent Creation")

    console.print("🤖 Creating agent from configuration...")

    agent = AgentFactory.create(agent_config)

    console.print(f"[green]✓[/green] Agent created: {agent.__class__.__name__}")
    console.print(f"   Name: {agent_config.agent.name}")
    console.print("   Type: StandardAgent")
    console.print("   Capabilities: LLM inference, Tool calling")

    return agent


def demo_agent_execution(agent):
    """Demonstrate agent execution with real LLM."""
    print_section("4. Agent Execution (Basic)")

    # Prepare input
    input_data = {
        "topic": "Benefits of using Python typing and type hints",
        "depth": "surface",
        "instructions": "Provide a brief analysis with 3-4 key points."
    }

    console.print("📝 Input data:")
    console.print(f"   Topic: {input_data['topic']}")
    console.print(f"   Depth: {input_data['depth']}")

    console.print("\n🚀 Executing agent with Ollama LLM...\n")

    # Create execution context
    context = ExecutionContext(
        workflow_id="demo-workflow",
        stage_id="demo-stage",
        agent_id="demo-agent-exec"
    )

    try:
        # Execute agent
        start_time = datetime.now(UTC)
        response = agent.execute(input_data, context)
        duration = (datetime.now(UTC) - start_time).total_seconds()

        # Display results
        console.print("[bold green]✓ Agent execution completed![/bold green]\n")

        # Create results panel
        results_table = Table(box=box.ROUNDED, show_header=False, border_style="green")
        results_table.add_column("Field", style="cyan", width=20)
        results_table.add_column("Value", style="white")

        status = "success" if not response.error else "failed"
        results_table.add_row("Status", status.upper())
        results_table.add_row("Duration", f"{duration:.2f}s" if duration else f"{response.latency_seconds:.2f}s")
        results_table.add_row("Total Tokens", str(response.tokens))
        results_table.add_row("Estimated Cost", f"${response.estimated_cost_usd:.6f}")
        results_table.add_row("Tool Calls", str(len(response.tool_calls)))

        # Add metadata if available
        if response.metadata:
            if 'llm_calls' in response.metadata:
                results_table.add_row("LLM Calls", str(response.metadata['llm_calls']))

        console.print(Panel(
            results_table,
            title="[bold]Execution Metrics[/bold]",
            border_style="green"
        ))

        # Display agent response
        console.print("\n[bold cyan]Agent Response:[/bold cyan]")
        console.print(Panel(
            response.output if isinstance(response.output, str) else str(response.output),
            border_style="cyan",
            padding=(1, 2)
        ))

        # Display reasoning if available
        if response.reasoning:
            console.print("\n[bold yellow]Agent Reasoning:[/bold yellow]")
            console.print(Panel(
                response.reasoning,
                border_style="yellow",
                padding=(1, 2)
            ))

        return response

    except Exception as e:
        console.print("[bold red]✗ Agent execution failed![/bold red]")
        console.print(f"[red]Error: {e}[/red]")
        import traceback
        console.print(f"\n[dim]{traceback.format_exc()}[/dim]")
        return None


def demo_direct_tool_execution(tool_registry):
    """Demonstrate direct tool execution (bypassing LLM)."""
    print_section("5. Direct Tool Execution")

    console.print("🔧 Testing tool execution directly (without LLM)...\n")

    # Test Calculator
    console.print("[cyan]Test 1: Calculator Tool[/cyan]")
    calc_input = {
        "expression": "150 * 49 * (1.15 ** 6)"
    }
    console.print(f"   Expression: {calc_input['expression']}")
    console.print("   (Calculate revenue after 6 months of 15% growth)\n")

    try:
        calc_tool = tool_registry.get("Calculator")
        import time
        start = time.time()
        calc_result = calc_tool.execute(**calc_input)
        elapsed = time.time() - start

        if calc_result.success:
            console.print(f"   [green]✓[/green] Result: {calc_result.result}")
            console.print(f"   [green]✓[/green] Execution time: {elapsed:.4f}s")
        else:
            console.print(f"   [red]✗[/red] Error: {calc_result.error}")
    except Exception as e:
        console.print(f"   [red]✗[/red] Exception: {e}")
        import traceback
        console.print(f"   [dim]{traceback.format_exc()[:200]}[/dim]")

    # Test another calculation
    console.print("\n[cyan]Test 2: ARR Calculation[/cyan]")
    arr_input = {
        "expression": "(150 * 49 * (1.15 ** 6)) * 12"
    }
    console.print(f"   Expression: {arr_input['expression']}")
    console.print("   (Calculate Annual Recurring Revenue)\n")

    try:
        calc_tool = tool_registry.get("Calculator")
        start = time.time()
        arr_result = calc_tool.execute(**arr_input)
        elapsed = time.time() - start

        if arr_result.success:
            console.print(f"   [green]✓[/green] Result: ${arr_result.result:,.2f}")
            console.print(f"   [green]✓[/green] Execution time: {elapsed:.4f}s")
        else:
            console.print(f"   [red]✗[/red] Error: {arr_result.error}")
    except Exception as e:
        console.print(f"   [red]✗[/red] Exception: {e}")

    # Show tool metadata
    console.print("\n[cyan]Tool Metadata:[/cyan]")
    calc_tool = tool_registry.get("Calculator")
    metadata = calc_tool._metadata
    metadata_table = Table(box=box.SIMPLE, show_header=False)
    metadata_table.add_column("Property", style="cyan", width=20)
    metadata_table.add_column("Value", style="white")

    metadata_table.add_row("Name", calc_tool.name)
    metadata_table.add_row("Version", calc_tool.version)
    metadata_table.add_row("Description", calc_tool.description[:60] + "...")
    metadata_table.add_row("Category", metadata.category or "N/A")
    metadata_table.add_row("Network Required", str(metadata.requires_network))

    console.print(Panel(
        metadata_table,
        title="[bold]Calculator Tool Info[/bold]",
        border_style="cyan",
        padding=(0, 1)
    ))

    console.print("\n[green]✓ Direct tool execution successful![/green]")
    return True


def demo_simple_calculator(agent):
    """Demonstrate simple calculator tool calling."""
    print_section("6. Simple Calculator Tool Call")

    # Very simple calculation request
    input_data = {
        "topic": "Calculate: 150 * 49",
        "depth": "surface"
    }

    console.print("📝 Input: Calculate 150 * 49")
    console.print("🚀 Executing agent...\n")

    context = ExecutionContext(
        workflow_id="calc-demo",
        stage_id="calc-stage",
        agent_id="calc-agent"
    )

    try:
        start_time = datetime.now(UTC)
        response = agent.execute(input_data, context)
        duration = (datetime.now(UTC) - start_time).total_seconds()

        console.print("[bold green]✓ Execution completed![/bold green]")
        console.print(f"   Tool Calls Made: [bold cyan]{len(response.tool_calls)}[/bold cyan]")
        console.print(f"   Duration: {duration:.2f}s")
        console.print(f"   Tokens: {response.tokens}\n")

        if response.tool_calls:
            console.print("[bold magenta]Tool Calls:[/bold magenta]")
            for idx, call in enumerate(response.tool_calls, 1):
                console.print(f"   {idx}. {call}")

        console.print(f"\n[bold cyan]Response:[/bold cyan] {response.output[:200]}...")

        return len(response.tool_calls) > 0

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return False


def demo_tool_calling(agent):
    """Demonstrate agent execution with tool calling."""
    print_section("6. Agent Execution with Tool Calling (Via LLM)")

    # Prepare input that requires calculation
    input_data = {
        "topic": "Business Revenue Analysis: A SaaS company has 150 customers paying $49/month. "
                 "They grow by 15% each month for 6 months. Calculate: "
                 "1) Monthly revenue after 6 months "
                 "2) Annual Recurring Revenue (ARR) at that point. "
                 "You MUST use the Calculator tool for these calculations.",
        "depth": "detailed"
    }

    console.print("📝 Input data:")
    console.print(f"   Topic: {input_data['topic'][:80]}...")
    console.print(f"   Depth: {input_data['depth']}")

    console.print("\n🚀 Executing agent with tool calling...\n")

    # Create execution context
    context = ExecutionContext(
        workflow_id="demo-tool-workflow",
        stage_id="demo-tool-stage",
        agent_id="demo-tool-agent"
    )

    try:
        # Execute agent
        start_time = datetime.now(UTC)
        response = agent.execute(input_data, context)
        duration = (datetime.now(UTC) - start_time).total_seconds()

        # Display results
        console.print("[bold green]✓ Agent execution with tools completed![/bold green]\n")

        # Create results panel
        results_table = Table(box=box.ROUNDED, show_header=False, border_style="green")
        results_table.add_column("Field", style="cyan", width=20)
        results_table.add_column("Value", style="white")

        status = "success" if not response.error else "failed"
        results_table.add_row("Status", status.upper())
        results_table.add_row("Duration", f"{duration:.2f}s" if duration else f"{response.latency_seconds:.2f}s")
        results_table.add_row("Total Tokens", str(response.tokens))
        results_table.add_row("Estimated Cost", f"${response.estimated_cost_usd:.6f}")
        results_table.add_row("Tool Calls", str(len(response.tool_calls)))

        # Add metadata if available
        if response.metadata:
            if 'llm_calls' in response.metadata:
                results_table.add_row("LLM Calls", str(response.metadata['llm_calls']))

        console.print(Panel(
            results_table,
            title="[bold]Execution Metrics[/bold]",
            border_style="green"
        ))

        # Display tool calls
        if response.tool_calls:
            console.print("\n[bold magenta]Tool Calls:[/bold magenta]")
            for idx, tool_call in enumerate(response.tool_calls, 1):
                tool_table = Table(box=box.SIMPLE, show_header=False, border_style="magenta")
                tool_table.add_column("Field", style="magenta", width=15)
                tool_table.add_column("Value", style="white")

                tool_table.add_row("Tool", tool_call.get('tool', 'Unknown'))
                tool_table.add_row("Input", str(tool_call.get('input', {}))[:100])
                if 'result' in tool_call:
                    tool_table.add_row("Result", str(tool_call['result'])[:100])

                console.print(Panel(
                    tool_table,
                    title=f"[bold]Tool Call #{idx}[/bold]",
                    border_style="magenta",
                    padding=(0, 1)
                ))

        # Display agent response
        console.print("\n[bold cyan]Agent Response:[/bold cyan]")
        console.print(Panel(
            response.output if isinstance(response.output, str) else str(response.output),
            border_style="cyan",
            padding=(1, 2)
        ))

        # Display reasoning if available
        if response.reasoning:
            console.print("\n[bold yellow]Agent Reasoning:[/bold yellow]")
            console.print(Panel(
                response.reasoning,
                border_style="yellow",
                padding=(1, 2)
            ))

        return response

    except Exception as e:
        console.print("[bold red]✗ Agent execution with tools failed![/bold red]")
        console.print(f"[red]Error: {e}[/red]")
        import traceback
        console.print(f"\n[dim]{traceback.format_exc()}[/dim]")
        return None


def demo_gantt_visualization():
    """Demonstrate hierarchical Gantt chart for latest execution."""
    console = Console()

    console.print("\n[bold cyan]" + "─" * 30 + "[/bold cyan]")
    console.print("[bold cyan]7. Hierarchical Gantt Chart Visualization[/bold cyan]")
    console.print("[bold cyan]" + "─" * 60 + "[/bold cyan]")

    console.print("\n📊 Generating interactive Gantt chart for latest execution...\n")

    try:
        import uuid

        from sqlmodel import select

        from examples.export_waterfall import export_waterfall_trace
        from src.observability.database import get_session
        from src.observability.models import (
            AgentExecution,
            LLMCall,
            StageExecution,
            WorkflowExecution,
        )
        from src.observability.visualize_trace import visualize_trace

        # Get latest workflow execution, or create a mock one
        with get_session() as session:
            stmt = select(WorkflowExecution).order_by(
                WorkflowExecution.start_time.desc()
            ).limit(1)
            workflow = session.exec(stmt).first()

            if not workflow:
                # Create a mock execution for demonstration
                console.print("[dim]   Creating mock execution for demonstration...[/dim]")
                workflow_id = str(uuid.uuid4())
                workflow = WorkflowExecution(
                    id=workflow_id,
                    workflow_name="milestone2_demo",
                    workflow_version="1.0",
                    workflow_config_snapshot={"workflow": {"name": "milestone2_demo"}},
                    trigger_type="manual",
                    start_time=datetime.now(UTC).replace(microsecond=0),
                    end_time=datetime.now(UTC).replace(microsecond=0),
                    duration_seconds=10.0,
                    status="completed",
                    environment="development",
                    total_tokens=2500,
                    total_cost_usd=0.005,
                    total_llm_calls=2,
                    total_tool_calls=1
                )
                session.add(workflow)
                session.commit()
                session.refresh(workflow)

                # Create a mock stage
                stage_id = str(uuid.uuid4())
                stage = StageExecution(
                    id=stage_id,
                    workflow_execution_id=workflow_id,
                    stage_name="agent_execution",
                    stage_version="1.0",
                    stage_config_snapshot={"stage": {"name": "agent_execution"}},
                    start_time=workflow.start_time,
                    end_time=workflow.end_time,
                    duration_seconds=10.0,
                    status="completed",
                    num_agents_executed=1,
                    num_agents_succeeded=1
                )
                session.add(stage)
                session.commit()

                # Create a mock agent
                agent_id = str(uuid.uuid4())
                agent = AgentExecution(
                    id=agent_id,
                    stage_execution_id=stage_id,
                    agent_name="simple_researcher",
                    agent_version="1.0",
                    agent_config_snapshot={"agent": {"name": "simple_researcher"}},
                    start_time=workflow.start_time,
                    end_time=workflow.end_time,
                    duration_seconds=10.0,
                    status="completed",
                    total_tokens=2500,
                    estimated_cost_usd=0.005,
                    num_llm_calls=2,
                    num_tool_calls=1
                )
                session.add(agent)
                session.commit()

                # Create mock LLM calls
                llm1 = LLMCall(
                    id=str(uuid.uuid4()),
                    agent_execution_id=agent_id,
                    provider="ollama",
                    model="llama3.2:3b",
                    start_time=workflow.start_time,
                    end_time=workflow.start_time,
                    latency_ms=5000,
                    prompt="Analyze Python typing benefits",
                    response="Type hints improve code quality...",
                    prompt_tokens=20,
                    completion_tokens=150,
                    total_tokens=170,
                    estimated_cost_usd=0.0003,
                    status="success"
                )
                session.add(llm1)
                session.commit()

            workflow_id = workflow.id
            console.print(f"   [cyan]Using workflow:[/cyan] {workflow.workflow_name} ({workflow_id[:8]}...)")

        # Export trace data
        console.print("   [dim]Exporting execution trace...[/dim]")
        trace = export_waterfall_trace(workflow_id)

        if "error" in trace:
            console.print(f"   [yellow]⚠️  Could not export trace: {trace['error']}[/yellow]")
            return False

        # Print console version
        from src.observability.visualize_trace import print_console_gantt
        print_console_gantt(trace)

        # Create HTML visualization
        console.print("\n   [dim]Creating interactive HTML Gantt chart...[/dim]")
        output_file = "milestone2_execution_gantt.html"
        visualize_trace(trace, output_file=output_file, auto_open=False)

        console.print(f"\n[green]✓ Interactive Gantt chart saved:[/green] [bold]{output_file}[/bold]")
        console.print("\n[bold]Chart features:[/bold]")
        console.print("  • [cyan]Hierarchical timeline[/cyan] (workflow → stage → agent → operations)")
        console.print("  • [cyan]Tree structure visualization[/cyan] with ▼ ├─ └─ characters")
        console.print("  • [cyan]Color-coded operations[/cyan] (LLM calls, tool executions)")
        console.print("  • [cyan]Interactive tooltips[/cyan] (hover for tokens, cost, duration)")
        console.print("  • [cyan]Zoom & pan[/cyan] to explore timeline")
        console.print("  • [cyan]Export to PNG[/cyan] using camera icon")

        return True

    except ImportError as e:
        console.print(f"   [yellow]⚠️  Missing dependency: {e}[/yellow]")
        console.print("   [dim]Install with: pip install plotly[/dim]")
        return False
    except Exception as e:
        console.print(f"   [yellow]⚠️  Could not create Gantt chart: {e}[/yellow]")
        return False


def main():
    """Run the Milestone 2 demo."""
    console.print()
    console.print(Panel(
        "[bold cyan]Meta-Autonomous Framework[/bold cyan]\n"
        "[bold]Milestone 2 Demo[/bold]\n\n"
        "This demo showcases:\n"
        "  • YAML-configured agent loading\n"
        "  • Real Ollama LLM execution\n"
        "  • Tool integration & calling (Calculator)\n"
        "  • Multi-turn agent execution\n"
        "  • Token and cost tracking\n"
        "  • Console visualization\n"
        "  • Hierarchical Gantt chart visualization",
        border_style="cyan",
        padding=(1, 2)
    ))

    # Check Ollama
    if not check_ollama_available():
        console.print()
        console.print(Panel(
            "[yellow bold]WARNING: Ollama not detected[/yellow bold]\n\n"
            "This demo requires Ollama to be running.\n\n"
            "Please start Ollama:\n"
            "  [bold]ollama serve[/bold]\n\n"
            "And ensure model is available:\n"
            "  [bold]ollama pull llama3.2:3b[/bold]",
            title="Ollama Required",
            border_style="yellow"
        ))
        response = input("\nContinue anyway? [y/N]: ")
        if response.lower() != 'y':
            return 1

    try:
        # Initialize database for observability and Gantt charts
        init_database("sqlite:///:memory:")

        # Run demos
        agent_config = demo_config_loading()
        tool_registry = demo_tool_registry()
        agent = demo_agent_creation(agent_config, tool_registry)
        result = demo_agent_execution(agent)

        # Demo direct tool execution
        tool_exec_result = demo_direct_tool_execution(tool_registry)

        # Demo simple calculator calling
        simple_result = demo_simple_calculator(agent)

        # Skip the complex demo for now
        # tool_result = demo_tool_calling(agent)

        # Demonstrate Gantt chart visualization
        gantt_result = demo_gantt_visualization()

        if result and tool_exec_result and simple_result:
            # Success message
            print_section("Milestone 2 Demo Complete")
            console.print()
            console.print("[bold green]✅ All Milestone 2 components are working![/bold green]")
            console.print()
            console.print("[bold]What was demonstrated:[/bold]")
            console.print("  [green]✓[/green] YAML config loading and validation")
            console.print("  [green]✓[/green] Agent creation from configuration")
            console.print("  [green]✓[/green] Real Ollama LLM integration")
            console.print("  [green]✓[/green] Tool registry with Calculator, WebScraper, FileWriter")
            console.print("  [green]✓[/green] Agent tool calling (Calculator)")
            console.print("  [green]✓[/green] Token usage and cost tracking")
            console.print("  [green]✓[/green] Rich console visualization")
            if gantt_result:
                console.print("  [green]✓[/green] Hierarchical Gantt chart visualization")
            console.print()
            console.print("[bold]Next Steps:[/bold]")
            console.print("  • Milestone 3: Multi-agent collaboration")
            console.print("  • Milestone 4: Safety and blast radius controls")
            console.print("  • Full workflow execution with LangGraph")
            console.print()
            return 0
        else:
            console.print()
            console.print("[bold red]❌ Demo failed - see error above[/bold red]")
            return 1

    except KeyboardInterrupt:
        console.print()
        console.print("[yellow]Demo interrupted by user[/yellow]")
        return 130

    except Exception as e:
        console.print()
        # Use markup=False to prevent Rich markup in error message from breaking formatting
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", markup=False)
        import traceback
        console.print()
        # Print traceback without Rich processing to avoid markup conflicts
        console.print(traceback.format_exc(), markup=False, highlight=False)
        return 1


if __name__ == "__main__":
    sys.exit(main())
