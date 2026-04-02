"""Temper AI CLI entry point.

Usage:
    temper run <workflow> [--input key=value ...] [-v] [-vv] [--provider X] [--model Y]
    temper serve [--port N] [--dev]
    temper validate <workflow>
"""

import argparse
import logging
import os
import sys
import uuid

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="temper",
        description="Temper AI — composable multi-agent workflows",
    )
    subparsers = parser.add_subparsers(dest="command")

    # -- temper run --
    run_parser = subparsers.add_parser("run", help="Run a workflow in the terminal")
    run_parser.add_argument("workflow", help="Workflow config name (e.g., demo_quickstart)")
    run_parser.add_argument(
        "--input", "-i", action="append", default=[],
        help="Input key=value pairs (repeatable)",
    )
    run_parser.add_argument("--verbose", "-v", action="count", default=0, help="Increase verbosity (-v, -vv)")
    run_parser.add_argument("--provider", help="Override LLM provider")
    run_parser.add_argument("--model", help="Override LLM model")
    run_parser.add_argument("--workspace", help="Workspace path for tools")
    run_parser.add_argument("--config-dir", default="configs", help="Config directory (default: configs)")
    run_parser.add_argument("--no-db", action="store_true", help="Skip database (ephemeral run)")

    # -- temper serve --
    serve_parser = subparsers.add_parser("serve", help="Start the API server + dashboard")
    serve_parser.add_argument("--port", type=int, default=8420, help="Port (default: 8420)")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    serve_parser.add_argument("--dev", action="store_true", help="Enable hot reload")
    serve_parser.add_argument("--config-dir", default="configs", help="Config directory")

    # -- temper validate --
    validate_parser = subparsers.add_parser("validate", help="Validate a workflow config")
    validate_parser.add_argument("workflow", help="Workflow config name")
    validate_parser.add_argument("--config-dir", default="configs", help="Config directory")

    args = parser.parse_args()

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "serve":
        _cmd_serve(args)
    elif args.command == "validate":
        _cmd_validate(args)
    else:
        parser.print_help()
        sys.exit(1)


def _cmd_run(args) -> None:
    """Run a workflow directly in the terminal."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(message)s",
    )

    # Parse inputs
    inputs = {}
    for item in args.input:
        if "=" not in item:
            print(f"Error: invalid input format '{item}' (expected key=value)", file=sys.stderr)
            sys.exit(1)
        key, value = item.split("=", 1)
        inputs[key] = value

    # Initialize database — always needed for config store,
    # --no-db only skips event persistence
    os.environ.setdefault("DATABASE_URL", "sqlite:///data/dev.db")
    from temper_ai.database import init_database
    init_database()

    # Import config loader and load YAML configs into DB
    from pathlib import Path
    from temper_ai.config import ConfigStore
    from temper_ai.config.importer import import_yaml

    config_dir = Path(args.config_dir)
    if config_dir.is_dir():
        store = ConfigStore()
        for yaml_file in sorted(config_dir.rglob("*.yaml")):
            try:
                import_yaml(str(yaml_file), store)
            except Exception:
                pass

    # Load workflow
    from temper_ai.stage.loader import GraphLoader

    store = ConfigStore()
    loader = GraphLoader(store)

    try:
        nodes, config = loader.load_workflow(args.workflow)
    except Exception as exc:
        print(f"Error loading workflow '{args.workflow}': {exc}", file=sys.stderr)
        sys.exit(1)

    # Initialize LLM providers
    from temper_ai.server import _init_llm_providers

    llm_providers = _init_llm_providers()

    # Initialize memory
    from temper_ai.memory import InMemoryStore, MemoryService
    memory_service = MemoryService(InMemoryStore())

    # Safety policies
    policy_engine = None
    if config.safety:
        from temper_ai.safety import PolicyEngine
        policy_engine = PolicyEngine.from_config(config.safety)

    # Tool executor
    from temper_ai.tools import TOOL_CLASSES
    from temper_ai.tools.executor import ToolExecutor

    tool_executor = ToolExecutor(
        workspace_root=args.workspace,
        policy_engine=policy_engine,
    )
    tool_executor.register_tools({name: cls() for name, cls in TOOL_CLASSES.items()})

    # MCP tools (lazy connect — configured from YAML or env)
    _mcp_loop = None
    _mcp_thread = None
    try:
        import asyncio
        import threading
        from temper_ai.tools.mcp_client import MCPClientManager
        from temper_ai.tools.mcp_tool import create_mcp_tools_from_agents

        mcp_manager = MCPClientManager()

        # Background event loop for MCP (stays alive for lazy connections)
        _mcp_loop = asyncio.new_event_loop()
        _mcp_thread = threading.Thread(target=_mcp_loop.run_forever, daemon=True)
        _mcp_thread.start()

        mcp_manager._event_loop = _mcp_loop
        future = asyncio.run_coroutine_threadsafe(
            mcp_manager.start(config_dir=args.config_dir), _mcp_loop
        )
        future.result(timeout=10)

        # Scan loaded nodes for MCP tool references
        agent_configs = []
        for node in nodes:
            if hasattr(node, "agent_config"):
                agent_configs.append(node.agent_config)

        mcp_tools = create_mcp_tools_from_agents(mcp_manager, agent_configs)
        if mcp_tools:
            tool_executor.register_tools(mcp_tools)
            # Pre-connect servers this workflow needs
            server_names = {t._server_name for t in mcp_tools.values()}
            for name in server_names:
                try:
                    f = asyncio.run_coroutine_threadsafe(
                        mcp_manager.ensure_connected(name), _mcp_loop
                    )
                    f.result(timeout=30)
                except Exception as e:
                    logger.warning("MCP pre-connect '%s' failed: %s", name, e)
    except Exception as e:
        logger.warning("MCP setup failed: %s", e)

    # CLI printer + event recorder
    from temper_ai.cli.printer import CLIPrinter
    from temper_ai.observability.event_recorder import EventRecorder
    from temper_ai.shared.types import ExecutionContext

    execution_id = str(uuid.uuid4())
    printer = CLIPrinter(verbosity=args.verbose)
    recorder = EventRecorder(
        execution_id,
        notifier=printer,
        persist=not args.no_db,
    )

    # Build context
    context = ExecutionContext(
        run_id=execution_id,
        workflow_name=config.name,
        node_path="",
        agent_name="",
        event_recorder=recorder,
        tool_executor=tool_executor,
        memory_service=memory_service,
        llm_providers=llm_providers,
        workspace_path=args.workspace,
    )

    # Print header
    defaults = config.defaults or {}
    printer.print_header(
        workflow_name=config.name,
        provider=defaults.get("provider", ""),
        model=defaults.get("model", ""),
        budget=str(config.safety.get("policies", [{}])[0].get("max_cost_usd", ""))
        if config.safety else "",
    )

    # Execute
    from temper_ai.stage.executor import execute_graph

    try:
        result = execute_graph(
            nodes, inputs, context,
            graph_name=config.name,
            is_workflow=True,
        )
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"\nExecution failed: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        tool_executor.shutdown(wait=False)

    # Print final output if verbose
    if args.verbose >= 1 and result.output:
        from rich.console import Console
        from rich.panel import Panel
        console = Console(stderr=True)
        console.print()
        console.print(Panel(result.output[:2000], title="Final Output", border_style="green"))

    sys.exit(0 if result.status == "completed" else 1)


def _cmd_serve(args) -> None:
    """Start the API server."""
    import uvicorn

    os.environ.setdefault("DATABASE_URL", "sqlite:///data/dev.db")
    os.environ.setdefault("TEMPER_CONFIG_DIR", args.config_dir)

    uvicorn.run(
        "temper_ai.server:app",
        host=args.host,
        port=args.port,
        reload=args.dev,
        reload_dirs=["temper_ai"] if args.dev else None,
        log_level="info",
    )


def _cmd_validate(args) -> None:
    """Validate a workflow config without executing."""
    os.environ.setdefault("DATABASE_URL", "sqlite:///data/dev.db")

    from pathlib import Path
    from temper_ai.config import ConfigStore
    from temper_ai.config.importer import import_yaml
    from temper_ai.database import init_database

    init_database()

    config_dir = Path(args.config_dir)
    store = ConfigStore()
    if config_dir.is_dir():
        for yaml_file in sorted(config_dir.rglob("*.yaml")):
            try:
                import_yaml(str(yaml_file), store)
            except Exception:
                pass

    from temper_ai.stage.loader import GraphLoader

    store = ConfigStore()
    loader = GraphLoader(store)

    try:
        nodes, config = loader.load_workflow(args.workflow)
        print(f"✓ Workflow '{config.name}' is valid")
        print(f"  Nodes: {len(nodes)}")
        for node in nodes:
            print(f"    {node.name} ({node.config.type})")
    except Exception as exc:
        print(f"✗ Validation failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
