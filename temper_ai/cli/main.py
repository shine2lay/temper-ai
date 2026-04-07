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
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    subparsers = parser.add_subparsers(dest="command")

    # -- temper run --
    run_parser = subparsers.add_parser("run", help="Run a workflow in the terminal")
    run_parser.add_argument("workflow", help="Workflow config name (e.g., blog_writer)")
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
    run_parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    # -- temper serve --
    serve_parser = subparsers.add_parser("serve", help="Start the API server + dashboard")
    serve_parser.add_argument("--port", type=int, default=8420, help="Port (default: 8420)")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")  # noqa: B104
    serve_parser.add_argument("--dev", action="store_true", help="Enable hot reload")
    serve_parser.add_argument("--config-dir", default="configs", help="Config directory")
    serve_parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    # -- temper validate --
    validate_parser = subparsers.add_parser("validate", help="Validate a workflow config")
    validate_parser.add_argument("workflow", help="Workflow config name")
    validate_parser.add_argument("--config-dir", default="configs", help="Config directory")
    validate_parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    # F28: --debug flag sets logging to DEBUG
    log_level = logging.DEBUG if getattr(args, 'debug', False) else logging.WARNING
    logging.basicConfig(level=log_level, format="%(levelname)s %(name)s: %(message)s" if log_level == logging.DEBUG else "%(message)s")

    # F17: auto-load .env file if present
    _load_dotenv()

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "serve":
        _cmd_serve(args)
    elif args.command == "validate":
        _cmd_validate(args)
    else:
        parser.print_help()
        sys.exit(1)


def _load_dotenv() -> None:
    """Load .env file if present. Falls back to manual parsing if python-dotenv not installed."""
    from pathlib import Path

    env_file = Path(".env")
    if not env_file.exists():
        return

    try:
        from dotenv import load_dotenv
        load_dotenv()
        return
    except ImportError:
        pass

    # Minimal .env parser fallback
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _cmd_run(args) -> None:
    """Run a workflow directly in the terminal."""
    inputs = _parse_inputs(args.input)

    os.environ.setdefault("TEMPER_DATABASE_URL", "sqlite:///data/dev.db")
    from temper_ai.database import init_database
    init_database()

    _load_configs(args.config_dir)

    nodes, config = _load_workflow(args.workflow)

    from temper_ai.server import _init_llm_providers
    llm_providers = _init_llm_providers()

    from temper_ai.memory import InMemoryStore, MemoryService
    memory_service = MemoryService(InMemoryStore())

    tool_executor = _build_tool_executor(args, config, nodes)

    printer, recorder, context = _build_execution_context(
        args, config, nodes, llm_providers, memory_service, tool_executor,
    )

    _print_workflow_header(printer, config)

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
    except Exception as exc:  # noqa: broad-except
        print(f"\nExecution failed: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        tool_executor.shutdown(wait=False)

    if args.verbose >= 1 and result.output:
        from rich.console import Console
        from rich.panel import Panel
        console = Console(stderr=True)
        console.print()
        console.print(Panel(result.output[:2000], title="Final Output", border_style="green"))

    sys.exit(0 if result.status == "completed" else 1)


def _parse_inputs(input_args: list) -> dict:
    """Parse key=value input arguments into a dict."""
    inputs = {}
    for item in input_args:
        if "=" not in item:
            print(f"Error: invalid input format '{item}' (expected key=value)", file=sys.stderr)
            sys.exit(1)
        key, value = item.split("=", 1)
        inputs[key] = value
    return inputs


def _load_configs(config_dir_path: str) -> None:
    """Load YAML configs from a directory into the ConfigStore."""
    from pathlib import Path
    from temper_ai.config import ConfigStore
    from temper_ai.config.importer import import_yaml

    config_dir = Path(config_dir_path)
    if config_dir.is_dir():
        store = ConfigStore()
        for yaml_file in sorted(config_dir.rglob("*.yaml")):
            try:
                import_yaml(str(yaml_file), store)
            except Exception as exc:
                # F16: log config loading errors instead of silently swallowing
                logger.warning("Failed to load config %s: %s", yaml_file, exc)


def _load_workflow(workflow_name: str):
    """Load a workflow by name. Exits on failure."""
    from temper_ai.config import ConfigStore
    from temper_ai.stage.loader import GraphLoader

    store = ConfigStore()
    loader = GraphLoader(store)
    try:
        return loader.load_workflow(workflow_name)
    except Exception as exc:  # noqa: broad-except
        print(f"Error loading workflow '{workflow_name}': {exc}", file=sys.stderr)
        sys.exit(1)


def _build_tool_executor(args, config, nodes):
    """Build the ToolExecutor with safety policies and MCP tools wired in."""
    from temper_ai.tools import TOOL_CLASSES
    from temper_ai.tools.executor import ToolExecutor

    policy_engine = None
    if config.safety:
        from temper_ai.safety import PolicyEngine
        policy_engine = PolicyEngine.from_config(config.safety)

    tool_executor = ToolExecutor(
        workspace_root=args.workspace,
        policy_engine=policy_engine,
    )
    tool_executor.register_tools({name: cls() for name, cls in TOOL_CLASSES.items()})

    _init_mcp_tools(tool_executor, nodes, args.config_dir)
    return tool_executor


def _init_mcp_tools(tool_executor, nodes, config_dir: str) -> None:
    """Initialize MCP tools and pre-connect required servers. No-op if mcp not installed."""
    try:
        import asyncio
        import threading
        from temper_ai.tools.mcp_client import MCPClientManager
        from temper_ai.tools.mcp_tool import create_mcp_tools_from_agents
    except ImportError:
        return

    mcp_manager = MCPClientManager()
    mcp_loop = asyncio.new_event_loop()
    mcp_thread = threading.Thread(target=mcp_loop.run_forever, daemon=True)
    mcp_thread.start()

    mcp_manager._event_loop = mcp_loop
    future = asyncio.run_coroutine_threadsafe(
        mcp_manager.start(config_dir=config_dir), mcp_loop
    )
    future.result(timeout=10)

    agent_configs = [node.agent_config for node in nodes if hasattr(node, "agent_config")]
    mcp_tools = create_mcp_tools_from_agents(mcp_manager, agent_configs)
    if not mcp_tools:
        return

    tool_executor.register_tools(dict(mcp_tools))
    _preconnect_mcp_servers(mcp_tools, mcp_manager, mcp_loop)


def _preconnect_mcp_servers(mcp_tools, mcp_manager, mcp_loop) -> None:
    """Pre-connect all MCP servers referenced by the loaded tools. Exits on failure."""
    import asyncio

    errors = []
    server_names = {t._server_name for t in mcp_tools.values()}
    for name in server_names:
        try:
            f = asyncio.run_coroutine_threadsafe(
                mcp_manager.ensure_connected(name), mcp_loop
            )
            f.result(timeout=30)
        except Exception as e:  # noqa: broad-except
            errors.append(f"MCP server '{name}': {e}")

    if errors:
        print("Error: Required MCP servers failed to connect:", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        sys.exit(1)


def _build_execution_context(args, config, nodes, llm_providers, memory_service, tool_executor):
    """Create the CLI printer, event recorder, and ExecutionContext."""
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
    return printer, recorder, context


def _print_workflow_header(printer, config) -> None:
    """Print the workflow header with provider/model/budget details."""
    defaults = config.defaults or {}
    printer.print_header(
        workflow_name=config.name,
        provider=defaults.get("provider", ""),
        model=defaults.get("model", ""),
        budget=str(config.safety.get("policies", [{}])[0].get("max_cost_usd", ""))
        if config.safety else "",
    )


def _cmd_serve(args) -> None:
    """Start the API server."""
    import uvicorn

    os.environ.setdefault("TEMPER_DATABASE_URL", "sqlite:///data/dev.db")
    os.environ.setdefault("TEMPER_CONFIG_DIR", args.config_dir)

    uvicorn.run(
        "temper_ai.server:app",
        host=args.host,
        port=args.port,
        reload=args.dev,
        reload_dirs=["temper_ai"] if args.dev else None,
        log_level="debug" if args.debug else "info",
    )


def _cmd_validate(args) -> None:
    """Validate a workflow config without executing."""
    os.environ.setdefault("TEMPER_DATABASE_URL", "sqlite:///data/dev.db")

    from pathlib import Path
    from temper_ai.config import ConfigStore
    from temper_ai.config.importer import import_yaml
    from temper_ai.database import init_database

    init_database()

    # F27: use a single ConfigStore — don't create a second one
    config_dir = Path(args.config_dir)
    store = ConfigStore()
    if config_dir.is_dir():
        for yaml_file in sorted(config_dir.rglob("*.yaml")):
            try:
                import_yaml(str(yaml_file), store)
            except Exception as exc:
                logger.warning("Failed to load config %s: %s", yaml_file, exc)

    from temper_ai.stage.loader import GraphLoader

    loader = GraphLoader(store)

    try:
        nodes, config = loader.load_workflow(args.workflow)
        print(f"✓ Workflow '{config.name}' is valid")
        print(f"  Nodes: {len(nodes)}")
        for node in nodes:
            print(f"    {node.name} ({node.config.type})")

        # F24: Check that the workflow's provider is available
        from temper_ai.server import _init_llm_providers
        providers = _init_llm_providers()
        default_provider = (config.defaults or {}).get("provider")
        if default_provider and default_provider not in providers:
            print(f"\n⚠ Warning: provider '{default_provider}' is not configured.")
            print(f"  Available providers: {list(providers.keys()) or ['none — set API keys in .env']}")
            print(f"  Set the appropriate API key in .env or change the workflow's defaults.provider")
    except Exception as exc:  # noqa: broad-except
        print(f"✗ Validation failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
