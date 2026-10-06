"""Temper AI CLI entry point.

Usage:
    temper run <workflow> [--input key=value ...] [--detach] [-v]   # starts it on the server
    temper serve [--port N] [--dev]
    temper connect <mcp-server>          # one-time OAuth, grant stored
    temper connections                   # what is authorized
    temper validate <workflow>
    temper check                         # settings that would not land (effort, Slack access, Pi loops)
"""

import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)

#: Set only in a run's box (spawner/box_view.py PROFILE_ENV); spelled out here so a CLI
#: started anywhere else doesn't import the spawner just to find it unset.
_BOX_PROFILE_ENV = "TEMPER_BOX_PROFILE"


def take_box_delivery_first() -> None:
    """In a oneshot box, block until the runner has taken its one-shot delivery, or exit.

    Elsewhere (no box profile, or a box whose secrets are its environment) this returns
    at once. A refused delivery ends the process (exit 4) before a tool or a secret is
    used; the reason is fixed words, never a value (spawner/box_bootstrap.py).
    """
    if not os.environ.get(_BOX_PROFILE_ENV):
        return
    from temper_ai.spawner import box_bootstrap

    try:
        box_bootstrap.receive()
    except box_bootstrap.DeliveryRefused as exc:
        print(f"box refused: {exc}", file=sys.stderr)
        sys.exit(box_bootstrap.REFUSED_EXIT)


def main() -> None:
    # First, before anything else runs: a oneshot box's runner takes its secrets now,
    # after making itself unreadable to the box's other processes (BS2).
    take_box_delivery_first()
    parser = argparse.ArgumentParser(
        prog="temper",
        description="Temper AI — composable multi-agent workflows",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    subparsers = parser.add_subparsers(dest="command")

    # -- temper run: start a workflow on the server and follow it (cli/run_on_server.py) --
    run_parser = subparsers.add_parser(
        "run",
        help="Start a workflow on the temper server and follow it",
        description=(
            "Start a workflow on the temper server, print its dashboard link and follow it until it "
            "ends. The server runs it with its own configs, the ~/temper-ai master folder, not the "
            "folder you type this in; nothing runs in the terminal, so every run shows on the "
            "dashboard. Waits on you are answered on the dashboard or in Slack/Telegram. To try a "
            "config that hasn't landed, save it under a new name through the Studio config API "
            "(docs/product-runs.md) or use a throwaway stack (scripts/temper_ci/stack.py)."
        ),
        epilog=(
            "Exit codes: 0 completed, 1 failed, 2 cancelled, 3 nothing was started (the server "
            "isn't answering or refused it), 4 stopped following before the end, 130 Ctrl+C; after "
            "4 and 130 the run keeps going on the server. Server: --server, else $TEMPER_SERVER_URL, "
            "else http://127.0.0.1:8420. Links: $TEMPER_UI_URL, else https://temper.wai2shine.com."
        ),
    )
    run_parser.add_argument("workflow", help="Workflow config name, as the server has it (e.g. ci_slow)")
    run_parser.add_argument(
        "--input", "-i", action="append", default=[],
        help="Input as key=value (repeatable); a value that parses as JSON is sent as JSON",
    )
    run_parser.add_argument(
        "--workspace", help="Workspace folder for the run's tools; it must be a path the server can see",
    )
    run_parser.add_argument(
        "--detach", action="store_true", help="Print the run's link and return at once, without following it",
    )
    run_parser.add_argument(
        "--verbose", "-v", action="count", default=0,
        help="While following, show nested stages too, and the output at the end",
    )
    run_parser.add_argument(
        "--server", help="The temper server (default: $TEMPER_SERVER_URL, else http://127.0.0.1:8420)",
    )
    run_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    # The old in-terminal run's flags: still parsed, so each is refused with what to do instead.
    for gone in ("--provider", "--model", "--config-dir"):
        run_parser.add_argument(gone, help=argparse.SUPPRESS)
    run_parser.add_argument("--no-db", action="store_true", help=argparse.SUPPRESS)

    # -- temper serve --
    serve_parser = subparsers.add_parser("serve", help="Start the API server + dashboard")
    serve_parser.add_argument("--port", type=int, default=8420, help="Port (default: 8420)")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")  # noqa: B104
    serve_parser.add_argument("--dev", action="store_true", help="Enable hot reload")
    serve_parser.add_argument("--config-dir", default="configs", help="Config directory")
    serve_parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    # -- temper mcp --
    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Serve temper's MCP tools over stdio (proxies to a running server)",
    )
    mcp_parser.add_argument(
        "--url",
        default="http://localhost:8420/mcp",
        help="MCP endpoint of a running temper server (default: %(default)s)",
    )
    mcp_parser.add_argument(
        "--token",
        default=None,
        help="API token, if the server requires one (default: $TEMPER_API_TOKEN)",
    )
    mcp_parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    # -- temper connect / connections / disconnect --
    connect_parser = subparsers.add_parser(
        "connect",
        help="Authorize an OAuth MCP server once; the grant is stored and reused",
    )
    connect_parser.add_argument("server", help="Configured MCP server name (e.g. notion)")
    connect_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Local port for the OAuth redirect (default: %(default)s)",
    )
    connect_parser.add_argument(
        "--manual",
        action="store_true",
        help=(
            "Paste the redirected URL instead of listening locally "
            "(for headless or remote machines whose browser is elsewhere)"
        ),
    )
    connect_parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    connections_parser = subparsers.add_parser(
        "connections",
        help="Show configured HTTP MCP servers and whether they are authorized",
    )
    connections_parser.add_argument(
        "--debug", action="store_true", help="Enable debug logging"
    )
    connections_parser.add_argument(
        "--pin-key", metavar="ENV_FILE",
        help="Write this machine's sealing key into ENV_FILE as TEMPER_SECRET_KEY "
             "(never printed), so the server reads grants sealed here",
    )

    disconnect_parser = subparsers.add_parser(
        "disconnect", help="Forget a stored MCP authorization"
    )
    disconnect_parser.add_argument("server", help="Configured MCP server name")
    disconnect_parser.add_argument(
        "--debug", action="store_true", help="Enable debug logging"
    )

    # -- temper linear check / issue / comment --
    from temper_ai.cli.linear import add_parser as add_linear_parser

    add_linear_parser(subparsers)

    # -- temper github setup / convert / manifest / check --
    from temper_ai.cli.github import add_parser as add_github_parser

    add_github_parser(subparsers)

    # -- temper slack check --
    from temper_ai.cli.slack import add_parser as add_slack_parser

    add_slack_parser(subparsers)

    # -- temper telegram check --
    from temper_ai.cli.telegram import add_parser as add_telegram_parser

    add_telegram_parser(subparsers)

    # -- temper notion check --
    from temper_ai.cli.notion import add_parser as add_notion_parser

    add_notion_parser(subparsers)

    # -- temper events list / show / replay --
    from temper_ai.cli.events import add_parser as add_events_parser

    add_events_parser(subparsers)

    # -- temper check --
    from temper_ai.cli.check import add_parser as add_check_parser

    add_check_parser(subparsers)

    # -- temper validate --
    validate_parser = subparsers.add_parser("validate", help="Validate a workflow config")
    validate_parser.add_argument("workflow", help="Workflow config name")
    validate_parser.add_argument(
        "--input", "-i", action="append", default=[],
        help="Input as key=value (repeatable). Required to validate workflows "
             "with `type: template` nodes, whose size depends on an input.",
    )
    validate_parser.add_argument("--config-dir", default="configs", help="Config directory")
    validate_parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    # -- temper run-workflow (worker entry point — spawned by server, not user-facing) --
    rw_parser = subparsers.add_parser(
        "run-workflow",
        help="Worker entry point: execute a pre-queued WorkflowRun row by id",
    )
    rw_parser.add_argument(
        "--execution-id", required=True,
        help="WorkflowRun.execution_id of the queued row to execute",
    )
    rw_parser.add_argument(
        "--config-dir", default=None,
        help="Workflow config directory (default: $TEMPER_CONFIG_DIR or repo configs/)",
    )
    rw_parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    # -- temper watch-queue (long-lived daemon — spawns workers from queued rows) --
    wq_parser = subparsers.add_parser(
        "watch-queue",
        help="Daemon: poll Postgres for queued WorkflowRun rows, spawn each as a subprocess",
    )
    wq_parser.add_argument(
        "--poll-interval", type=float, default=2.0,
        help="Seconds between scans for new queued rows (default: 2.0)",
    )
    wq_parser.add_argument(
        "--reaper-interval", type=float, default=5.0,
        help="Seconds between reaper liveness sweeps (default: 5.0)",
    )
    wq_parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    # -- temper trim (weekly housekeeping: old runs' sent material) --
    from temper_ai.cli.trim import add_parser as _add_trim_parser
    _add_trim_parser(subparsers)

    args = parser.parse_args()

    # F28: --debug flag sets logging to DEBUG
    log_level = logging.DEBUG if getattr(args, 'debug', False) else logging.WARNING
    logging.basicConfig(level=log_level, format="%(levelname)s %(name)s: %(message)s" if log_level == logging.DEBUG else "%(message)s")

    # F17: auto-load .env file if present
    _load_dotenv()
    # ...and take the GitHub app's secrets back out of the environment it just filled
    from temper_ai.integrations.github import secret as github_secret

    github_secret.take()

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "serve":
        _cmd_serve(args)
    elif args.command == "mcp":
        from temper_ai.mcp.bridge import run_bridge
        run_bridge(args.url, args.token)
    elif args.command == "connect":
        from temper_ai.cli.connect import cmd_connect
        sys.exit(cmd_connect(args))
    elif args.command == "connections":
        from temper_ai.cli.connect import cmd_connections
        sys.exit(cmd_connections(args))
    elif args.command == "disconnect":
        from temper_ai.cli.connect import cmd_disconnect
        sys.exit(cmd_disconnect(args))
    elif args.command == "linear":
        from temper_ai.cli.linear import cmd_linear
        sys.exit(cmd_linear(args))
    elif args.command == "github":
        from temper_ai.cli.github import cmd_github
        sys.exit(cmd_github(args))
    elif args.command == "slack":
        from temper_ai.cli.slack import cmd_slack
        sys.exit(cmd_slack(args))
    elif args.command == "telegram":
        from temper_ai.cli.telegram import cmd_telegram
        sys.exit(cmd_telegram(args))
    elif args.command == "notion":
        from temper_ai.cli.notion import cmd_notion
        sys.exit(cmd_notion(args))
    elif args.command == "events":
        from temper_ai.cli.events import cmd_events
        sys.exit(cmd_events(args))
    elif args.command == "trim":
        from temper_ai.cli.trim import cmd_trim
        sys.exit(cmd_trim(args))
    elif args.command == "check":
        from temper_ai.cli.check import main as cmd_check
        sys.exit(cmd_check(args))
    elif args.command == "validate":
        _cmd_validate(args)
    elif args.command == "run-workflow":
        from temper_ai.cli.run_workflow import cmd_run_workflow
        sys.exit(cmd_run_workflow(args))
    elif args.command == "watch-queue":
        # Configure logging at INFO so the daemon is observable in docker logs
        if not args.debug:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                stream=sys.stdout,
                force=True,
            )
        from temper_ai.cli.watch_queue import cmd_watch_queue
        sys.exit(cmd_watch_queue(args))
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
        load_dotenv(dotenv_path=env_file, override=False)
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
    """Start the workflow on the temper server and follow it (temper_ai/cli/run_on_server.py).

    Nothing runs in the terminal, under any flag: a run started here used to be recorded in
    whatever database the shell named and never reached the dashboard.
    """
    from temper_ai.cli import run_on_server

    refused = run_on_server.refusals(args)
    for line in refused:
        print(line, file=sys.stderr)
    if refused:
        sys.exit(run_on_server.NOT_STARTED)
    inputs = _parse_inputs(args.input, exit_code=run_on_server.NOT_STARTED)
    sys.exit(run_on_server.run(
        args.workflow, inputs, workspace=args.workspace, server=args.server,
        detach=args.detach, verbose=args.verbose,
    ))


def _parse_inputs(input_args: list, *, exit_code: int = 1) -> dict:
    """Parse key=value input arguments into a dict.

    Values that parse as JSON become real lists/dicts/numbers/booleans, so
    workflows taking structured input work from the CLI too:

        --input 'cities=[{"name":"Lisbon"}]'   -> list of dicts
        --input n_lanes=2                        -> int
        --input topic=lighthouses                -> str (unchanged)

    Anything that is not valid JSON stays the plain string it was, so
    ordinary prose inputs need no quoting. A malformed item exits with
    ``exit_code``.
    """
    import json

    inputs = {}
    for item in input_args:
        if "=" not in item:
            print(f"Error: invalid input format '{item}' (expected key=value)", file=sys.stderr)
            sys.exit(exit_code)
        key, value = item.split("=", 1)
        try:
            inputs[key] = json.loads(value)
        except ValueError:
            inputs[key] = value
    return inputs


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
    from temper_ai.config.importer import import_config_tree
    from temper_ai.database import init_database

    init_database()

    # F27: use a single ConfigStore — don't create a second one
    config_dir = Path(args.config_dir)
    store = ConfigStore()
    if config_dir.is_dir():
        # A file that fails to parse is reported at WARNING by the loader, so
        # a broken workflow YAML shows its real error here rather than a bare
        # "not found" below.
        import_config_tree(config_dir, store)

    from temper_ai.stage.loader import GraphLoader

    loader = GraphLoader(store)

    try:
        nodes, config = loader.load_workflow(args.workflow, inputs=_parse_inputs(args.input))
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
            print("  Set the appropriate API key in .env or change the workflow's defaults.provider")
    except Exception as exc:  # noqa: BLE001
        print(f"✗ Validation failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
