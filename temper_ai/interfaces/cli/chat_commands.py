"""Interactive chat mode for single-agent conversations (R0.4).

Usage: temper-ai chat configs/agents/researcher.yaml
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import click
import yaml
from rich.console import Console

from temper_ai.interfaces.cli.chat_constants import (
    CHAT_CLEAR_COMMAND,
    CHAT_EXIT_COMMANDS,
    CHAT_HELP_COMMANDS,
    CHAT_HELP_TEXT,
    CHAT_PROMPT_MARKER,
    CHAT_RESPONSE_PREFIX,
    CHAT_WELCOME_MESSAGE,
    MAX_CHAT_HISTORY_TURNS,
)

logger = logging.getLogger(__name__)
console = Console()


def _load_agent(agent_config_path: str) -> Any:
    """Load agent YAML and create agent via factory.

    Args:
        agent_config_path: Path to agent YAML config file.

    Returns:
        Initialized agent instance.

    Raises:
        SystemExit: On load or creation failure.
    """
    try:
        with open(agent_config_path) as f:
            raw_config = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        console.print(f"[red]Error loading config:[/red] {exc}")
        raise SystemExit(1)

    if not raw_config:
        console.print("[red]Error:[/red] Empty agent config file")
        raise SystemExit(1)

    try:
        from temper_ai.storage.schemas.agent_config import AgentConfig
        from temper_ai.agent.utils.agent_factory import AgentFactory

        config = AgentConfig(**raw_config)
        return AgentFactory.create(config)
    except (ImportError, ValueError, TypeError) as exc:
        console.print(f"[red]Error creating agent:[/red] {exc}")
        raise SystemExit(1)


def _handle_special_command(user_input: str) -> Optional[str]:
    """Check user input for special commands.

    Args:
        user_input: Raw user input string.

    Returns:
        Action string ("exit", "help", "clear") or None for normal input.
    """
    stripped = user_input.strip().lower()
    if stripped in CHAT_EXIT_COMMANDS:
        return "exit"
    if stripped in CHAT_HELP_COMMANDS:
        return "help"
    if stripped == CHAT_CLEAR_COMMAND:
        return "clear"
    return None


def _run_chat_loop(agent: Any) -> None:
    """Run the interactive chat REPL loop.

    Args:
        agent: Initialized agent instance with execute() method.
    """
    turn_count = 0
    while True:
        try:
            user_input = console.input(CHAT_PROMPT_MARKER)
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Chat ended[/yellow]")
            return

        if not user_input.strip():
            continue

        action = _handle_special_command(user_input)
        if action == "exit":
            console.print("[yellow]Goodbye![/yellow]")
            return
        if action == "help":
            console.print(CHAT_HELP_TEXT)
            continue
        if action == "clear":
            turn_count = 0
            console.print("[dim]History cleared[/dim]")
            continue

        turn_count += 1
        if turn_count > MAX_CHAT_HISTORY_TURNS:
            console.print(
                "[yellow]Warning:[/yellow] Max history reached, "
                "older context may be lost"
            )

        try:
            response = agent.execute({"task": user_input})
            output = getattr(response, "output", str(response))
            console.print(
                f"\n[bold cyan]{CHAT_RESPONSE_PREFIX}:[/bold cyan] {output}\n"
            )
        except (RuntimeError, ValueError, ConnectionError) as exc:
            console.print(f"[red]Agent error:[/red] {exc}")


@click.command("chat")
@click.argument("agent_config", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def chat(agent_config: str, verbose: bool) -> None:
    """Start interactive chat session with an agent."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    agent_name = Path(agent_config).stem
    agent = _load_agent(agent_config)

    console.print(
        CHAT_WELCOME_MESSAGE.format(agent_name=agent_name)
    )
    console.print(CHAT_HELP_TEXT)

    _run_chat_loop(agent)
