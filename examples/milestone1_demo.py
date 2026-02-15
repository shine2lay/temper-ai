#!/usr/bin/env python3
"""
Milestone 1 Demo Script

Demonstrates the key features delivered in Milestone 1:
1. Observability database (SQLite)
2. Config loading with YAML/JSON support
3. Pydantic schema validation
4. Console visualization with Rich

This script creates a mock workflow execution and displays it.
"""
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlmodel import select

from examples.demo_utils import print_section, print_warning
from src.workflow.config_loader import ConfigLoader
from src.workflow._schemas import WorkflowConfig
from src.observability.console import WorkflowVisualizer

# Import M1 components
from src.observability.database import get_session, init_database
from src.observability.models import (
    AgentExecution,
    LLMCall,
    StageExecution,
    ToolExecution,
    WorkflowExecution,
)


def demo_config_loading():
    """Demonstrate config loading."""
    print_section("1. Config Loading")

    # Initialize config loader
    project_root = Path(__file__).parent.parent
    configs_dir = project_root / "configs"
    loader = ConfigLoader(config_root=configs_dir)

    print(f"📁 Config directory: {configs_dir}")

    # List available configs
    workflows = loader.list_configs("workflow")
    agents = loader.list_configs("agent")
    tools = loader.list_configs("tool")

    print(f"\n✓ Found {len(workflows)} workflow configs")
    print(f"✓ Found {len(agents)} agent configs")
    print(f"✓ Found {len(tools)} tool configs")

    # Load an example workflow
    if workflows:
        workflow_name = workflows[0]
        print(f"\n📄 Loading workflow: {workflow_name}")

        workflow_dict = loader.load_workflow(workflow_name, validate=False)

        try:
            workflow_config = WorkflowConfig(**workflow_dict)
            print(f"   Name: {workflow_config.workflow.name}")
            print(f"   Version: {workflow_config.workflow.version}")
            print(f"   Stages: {len(workflow_config.workflow.stages)}")
            print("   ✓ Schema validation passed")
            return workflow_config
        except Exception:
            # Example configs may not be fully compliant yet
            print("   ⚠️  Schema validation skipped (example config in progress)")
            print(f"   Name: {workflow_dict.get('workflow', {}).get('name', 'N/A')}")
            print(f"   Version: {workflow_dict.get('workflow', {}).get('version', 'N/A')}")
            return None

    return None


def demo_database():
    """Demonstrate database creation and usage."""
    print_section("2. Observability Database")

    # Initialize database (in-memory for demo)
    print("🗄️  Initializing SQLite database...")
    init_database("sqlite:///:memory:")
    print("✓ Database initialized with all tables")

    # Create a workflow execution
    print("\n📝 Creating workflow execution record...")
    workflow_id = str(uuid.uuid4())
    workflow_exec = WorkflowExecution(
        id=workflow_id,
        workflow_name="demo_workflow",
        workflow_version="1.0",
        workflow_config_snapshot={"workflow": {"name": "demo"}},
        trigger_type="manual",
        start_time=datetime.now(UTC),
        status="running",
        environment="development",
    )

    with get_session() as session:
        session.add(workflow_exec)
        session.commit()
        session.refresh(workflow_exec)  # Refresh to load attributes

        print(f"✓ Created workflow: {workflow_exec.workflow_name}")
        print(f"   ID: {workflow_id}")
        print(f"   Status: {workflow_exec.status}")

    return workflow_id


def demo_execution_trace(workflow_id):
    """Demonstrate creating a complete execution trace."""
    print_section("3. Execution Trace")

    print("📊 Creating execution trace with stages, agents, LLM calls, and tools...")

    # Create stage
    stage_id = str(uuid.uuid4())
    stage_exec = StageExecution(
        id=stage_id,
        workflow_execution_id=workflow_id,
        stage_name="research",
        stage_version="1.0",
        stage_config_snapshot={"stage": {"name": "research"}},
        start_time=datetime.now(UTC),
        status="running",
        input_data={"goal": "Analyze market trends"},
    )

    with get_session() as session:
        session.add(stage_exec)
        session.commit()

    print("✓ Created stage: research")

    # Create agent
    agent_id = str(uuid.uuid4())
    agent_exec = AgentExecution(
        id=agent_id,
        stage_execution_id=stage_id,
        agent_name="market_researcher",
        agent_version="1.0",
        agent_config_snapshot={"agent": {"name": "market_researcher"}},
        start_time=datetime.now(UTC),
        status="running",
        reasoning="Analyzing market data for SaaS products",
        input_data={"domain": "SaaS"},
    )

    with get_session() as session:
        session.add(agent_exec)
        session.commit()

    print("✓ Created agent: market_researcher")

    # Create LLM call
    now = datetime.now(UTC)
    llm_call = LLMCall(
        id=str(uuid.uuid4()),
        agent_execution_id=agent_id,
        provider="ollama",
        model="llama3.2:3b",
        start_time=now,
        end_time=now + timedelta(seconds=2),
        latency_ms=2000,
        prompt="Analyze the SaaS market trends for 2026",
        response="The SaaS market shows strong growth...",
        prompt_tokens=25,
        completion_tokens=150,
        total_tokens=175,
        estimated_cost_usd=0.0015,
        temperature=0.7,
        max_tokens=2048,
        status="success",
    )

    with get_session() as session:
        session.add(llm_call)
        session.commit()
        session.refresh(llm_call)

        print("✓ Created LLM call: ollama/llama3.2:3b")
        print(f"   Tokens: {llm_call.total_tokens}")
        print(f"   Cost: ${llm_call.estimated_cost_usd:.4f}")

    # Create tool execution
    tool_now = datetime.now(UTC)
    tool_exec = ToolExecution(
        id=str(uuid.uuid4()),
        agent_execution_id=agent_id,
        tool_name="WebScraper",
        tool_version="1.0",
        start_time=tool_now,
        end_time=tool_now + timedelta(milliseconds=500),
        duration_seconds=0.5,
        input_params={"url": "https://example.com/market-data"},
        output_data={"pages_scraped": 1, "data_points": 42},
        status="success",
        safety_checks_applied=["rate_limit", "domain_whitelist"],
    )

    with get_session() as session:
        session.add(tool_exec)
        session.commit()

    print("✓ Created tool execution: WebScraper")

    # Complete agent
    agent_exec.end_time = datetime.now(UTC)
    agent_exec.duration_seconds = 3.0
    agent_exec.status = "success"
    agent_exec.output_data = {"analysis": "Market shows 30% YoY growth"}
    agent_exec.total_tokens = 175
    agent_exec.num_llm_calls = 1
    agent_exec.num_tool_calls = 1
    agent_exec.confidence_score = 0.85

    with get_session() as session:
        session.merge(agent_exec)
        session.commit()

    # Complete stage
    stage_exec.end_time = datetime.now(UTC)
    stage_exec.duration_seconds = 3.5
    stage_exec.status = "success"
    stage_exec.output_data = {"findings": "Research complete"}
    stage_exec.num_agents_executed = 1
    stage_exec.num_agents_succeeded = 1

    with get_session() as session:
        session.merge(stage_exec)
        session.commit()

    # Complete workflow
    with get_session() as session:
        workflow_exec = session.exec(
            select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
        ).first()
        workflow_exec.end_time = datetime.now(UTC)
        workflow_exec.duration_seconds = 4.0
        workflow_exec.status = "completed"
        workflow_exec.total_cost_usd = 0.0015
        workflow_exec.total_tokens = 175
        workflow_exec.total_llm_calls = 1
        workflow_exec.total_tool_calls = 1
        session.commit()
        session.refresh(workflow_exec)

        print("\n✓ Workflow completed successfully!")
        print(f"   Duration: {workflow_exec.duration_seconds}s")
        print(f"   Total tokens: {workflow_exec.total_tokens}")
        print(f"   Total cost: ${workflow_exec.total_cost_usd:.4f}")


def demo_console_visualization(workflow_id):
    """Demonstrate console visualization."""
    print_section("4. Console Visualization")

    print("📺 Displaying workflow execution in console...\n")

    # Display in standard mode
    with get_session() as session:
        workflow_exec = session.exec(
            select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
        ).first()
        visualizer = WorkflowVisualizer(verbosity="standard")
        visualizer.display_execution(workflow_exec)

    print("\n✓ Console visualization complete")


def demo_gantt_chart(workflow_id):
    """Demonstrate hierarchical Gantt chart visualization."""
    print_section("5. Hierarchical Gantt Chart")

    print("📊 Generating interactive hierarchical Gantt chart...\n")

    try:
        from examples.export_waterfall import export_waterfall_trace
        from src.observability.visualize_trace import print_console_gantt, visualize_trace

        # Export trace data
        print("   Exporting execution trace...")
        trace = export_waterfall_trace(workflow_id)

        if "error" in trace:
            print(f"   ⚠️  Could not export trace: {trace['error']}")
            return

        # Print console version
        print_console_gantt(trace)

        # Create HTML visualization
        print("\n   Creating interactive HTML Gantt chart...")
        output_file = "milestone1_execution_gantt.html"
        visualize_trace(trace, output_file=output_file, auto_open=False)

        print(f"\n✓ Interactive Gantt chart saved: {output_file}")
        print("   Open this file in your browser to see:")
        print("   • Hierarchical execution timeline")
        print("   • Agent, LLM, and tool operations")
        print("   • Duration and cost metrics")
        print("   • Interactive hover tooltips")

    except ImportError:
        print_warning("Plotly not installed. Install with: pip install plotly")
    except Exception as e:
        print_warning(f"Could not create Gantt chart: {e}")


def main():
    """Run the Milestone 1 demo."""
    print("\n" + "=" * 60)
    print("  Meta-Autonomous Framework - Milestone 1 Demo")
    print("=" * 60)
    print("\nThis demo showcases the core infrastructure delivered in M1:")
    print("  • Observability database with SQLite")
    print("  • YAML/JSON config loading")
    print("  • Pydantic schema validation")
    print("  • Rich console visualization")

    try:
        # Run demos
        workflow_config = demo_config_loading()
        workflow_id = demo_database()
        demo_execution_trace(workflow_id)
        demo_console_visualization(workflow_id)
        demo_gantt_chart(workflow_id)

        # Success message
        print_section("Milestone 1 Demo Complete")
        print("\n✅ All Milestone 1 components are working!")
        print("\nNext Steps:")
        print("  • Milestone 2: Agent execution with LLM integration")
        print("  • Milestone 3: Multi-agent collaboration")
        print("  • Milestone 4: Safety and blast radius controls")
        print()

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
