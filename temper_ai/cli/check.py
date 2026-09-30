"""`temper check` — settings in agent configs that go nowhere.

A config line that is read, accepted and then dropped is worse than one that
fails: it looks like a control for as long as nobody measures it. `effort:` was
exactly that for three months — every agent on the Claude Code provider asked
for thinking and the CLI was never told.

The check reads the config files, not a running server: it answers "would this
land?" before anything is spent on finding out. It reports what it looked at,
names each setting that goes nowhere with the agent and the provider it was
aimed at, and exits non-zero when there is one, so it can stand in a gate.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from temper_ai.llm.effort import EFFORT_LEVELS, unhonoured
from temper_ai.llm.providers.factory import honoured_effort, registered_providers

#: Where an agent config's provider comes from when it names none.
_DEFAULT_PROVIDER_ENV = "TEMPER_DEFAULT_PROVIDER"


def _agent_configs(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Every agent config under `root`, path and body, in a stable order.

    A file that will not parse is skipped rather than fatal: one broken YAML
    should not hide the answer for the other two hundred.
    """
    found: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml")):
        try:
            body = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(body, dict):
            continue
        agent = body.get("agent")
        if isinstance(agent, dict) and agent.get("name"):
            found.append((path, agent))
    return found


def _effort_of(agent: dict[str, Any]) -> Any:
    config = agent.get("provider_config")
    return config.get("effort") if isinstance(config, dict) else None


def _fallback_efforts(agent: dict[str, Any]) -> list[tuple[str | None, Any]]:
    """(provider, effort) for each fallback entry that sets one.

    A fallback is where a run spends its hours once the first account is out,
    so a setting dropped there is dropped for the half of the run nobody
    watches.
    """
    out: list[tuple[str | None, Any]] = []
    entries = agent.get("fallback")
    if not isinstance(entries, list):
        return out
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        config = entry.get("provider_config")
        effort = config.get("effort") if isinstance(config, dict) else None
        if effort is not None:
            out.append((entry.get("provider"), effort))
    return out


def _problems(path: Path, agent: dict[str, Any], default_provider: str | None) -> list[str]:
    """Every effort setting on this agent that the provider cannot ask for."""
    lines: list[str] = []
    name = agent.get("name") or path.stem
    own_provider = agent.get("provider") or default_provider

    for provider, effort in [(own_provider, _effort_of(agent)), *_fallback_efforts(agent)]:
        if effort is None:
            continue
        provider = provider or own_provider
        if not provider:
            lines.append(
                f"{name} ({path}): effort: {effort} but no provider is named here "
                f"and {_DEFAULT_PROVIDER_ENV} is not set"
            )
            continue
        honours = honoured_effort(str(provider))
        if honours is None:
            lines.append(
                f"{name} ({path}): provider '{provider}' is not configured in this "
                f"install, so effort: {effort} cannot be checked "
                f"(known: {', '.join(registered_providers())})"
            )
            continue
        problem = unhonoured(str(provider), honours, effort)
        if problem:
            lines.append(f"{name} ({path}): {problem}")
    return lines


def check_effort(config_dir: str | Path = "configs") -> tuple[int, list[str]]:
    """(agents seen, problems) for the agent configs under `config_dir`."""
    root = Path(config_dir)
    if not root.is_dir():
        return 0, [f"{root} is not a directory"]
    default_provider = os.environ.get(_DEFAULT_PROVIDER_ENV)
    agents = _agent_configs(root)
    problems: list[str] = []
    for path, agent in agents:
        problems.extend(_problems(path, agent, default_provider))
    return len(agents), problems


def check(config_dir: str | Path = "configs") -> int:
    """Print the report. 0 when every setting lands, 1 when one does not."""
    seen, problems = check_effort(config_dir)
    print(f"Agent configs read: {seen}  (under {config_dir})")
    print(f"Effort levels: {', '.join(EFFORT_LEVELS)}")
    for provider in registered_providers():
        honours = honoured_effort(provider) or ()
        print(f"  {provider:12} effort: {', '.join(honours) if honours else 'no effort dial'}")
    if not problems:
        print("\n\u2713 every effort setting reaches the provider it is aimed at")
        return 0
    print(f"\n\u26a0 {len(problems)} setting(s) go nowhere:")
    for line in problems:
        print(f"  {line}")
    print(
        "\nEither move the agent to a provider that takes it, or drop the line: "
        "a setting that is read and dropped reads like a control and is not one."
    )
    return 1


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "check", help="Agent settings that the provider cannot honour (effort, for now)",
    )
    parser.add_argument("--config-dir", default="configs", help="Config directory")


def main(args) -> int:
    return check(args.config_dir)
