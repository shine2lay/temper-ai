"""`temper check` — settings in agent configs that go nowhere, and Slack's access rules.


A config line that is read, accepted and then dropped is worse than one that
fails: it looks like a control for as long as nobody measures it. `effort:` was
exactly that for three months — every agent on the Claude Code provider asked
for thinking and the CLI was never told.

The check reads the config files, not a running server: it answers "would this
land?" before anything is spent on finding out. It reports what it looked at,
names each setting that goes nowhere with the agent and the provider it was
aimed at, and exits non-zero when there is one, so it can stand in a gate.

The same goes for who may do what in Slack (``configs/slack/access.yaml``): a
role allowing a workflow that no longer exists, or forcing an input the
workflow does not take, would look like a fence and be a hole, so it is named
here rather than found when somebody is refused or let through.
"""

from __future__ import annotations

import os
import re
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


# -- who may do what in Slack ---------------------------------------------------------

#: The repo names the question workflow can answer about, read from the copier
#: script's own table, so a typo in a role's repos: is caught here.
_REPO_LINE = re.compile(r'^\s*\("([A-Za-z0-9._-]+)",\s*"(?:git@|https://)', re.MULTILINE)


def _workflows(root: Path) -> dict[str, dict[str, Any]]:
    """Every workflow by name, with the inputs it declares."""
    out: dict[str, dict[str, Any]] = {}
    folder = root / "workflows"
    if not folder.is_dir():
        return out
    for path in sorted(folder.rglob("*.yaml")) + sorted(folder.rglob("*.yml")):
        try:
            body = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(body, dict):
            continue
        workflow = body.get("workflow", body)
        if isinstance(workflow, dict) and workflow.get("name"):
            inputs = workflow.get("inputs")
            out[str(workflow["name"])] = dict(inputs) if isinstance(inputs, dict) else {}
    return out


def _answerable_repos(root: Path) -> set[str]:
    path = root / "agents" / "repo_copies.yaml"
    try:
        return set(_REPO_LINE.findall(path.read_text()))
    except OSError:
        return set()


def _access_problems(path: Path, workflows: dict[str, dict[str, Any]],
                     repos: set[str]) -> tuple[list[str], list[str]]:
    """(holes, notes) for one access file, in the words of the file.

    A hole is a rule that cannot do what it says. A note is something worth
    seeing that is not wrong: the tracked file names roles and leaves the
    people to the local one, so a role with nobody in it is normal.
    """
    from temper_ai.integrations.slack import access as rules

    try:
        body = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        return [f"{path}: cannot be read: {exc}"], []
    try:
        cfg = rules.parse_config(body, str(path))
    except rules.AccessConfigError as exc:
        return [f"{path}: {exc}"], []

    known = sorted(workflows)
    problems: list[str] = []
    notes: list[str] = []
    for role in cfg.roles.values():
        where = f"{path}: roles.{role.name}"
        if not role.commands:
            problems.append(f"{where}: no commands, so this role can do nothing at all")
        if role.workflows == ():
            problems.append(f"{where}.workflows: an empty list means no workflow at all; "
                            "leave the key out to allow every one")
        for name in role.workflows or ():
            if name not in workflows:
                problems.append(f"{where}.workflows: there is no workflow '{name}' "
                                f"(there are {len(known)}: {', '.join(known[:8])}\u2026)")
        for name in sorted(role.auto):
            if name not in workflows:
                problems.append(f"{where}.auto: there is no workflow '{name}'")
            elif not role.may_use(name):
                problems.append(f"{where}.auto: '{name}' starts without a click but the role may not use it")
        for name, forced in role.force.items():
            if name == rules.ANY:
                targets = sorted(role.workflows or ())
            elif name not in workflows:
                problems.append(f"{where}.force: there is no workflow '{name}'")
                continue
            else:
                targets = [name]
                if not role.may_use(name):
                    problems.append(f"{where}.force: inputs are forced on '{name}', "
                                    "which this role may not use")
            for target in targets:
                declared = workflows.get(target) or {}
                if not declared:
                    continue
                for key in forced:
                    if key not in declared:
                        problems.append(
                            f"{where}.force.{name}: '{key}' is not an input of {target} "
                            f"(its inputs: {', '.join(sorted(declared)) or 'none'})")
        for repo in role.repos:
            if repos and repo not in repos:
                problems.append(f"{where}.repos: there is no repository '{repo}' "
                                f"(there are: {', '.join(sorted(repos))})")
    used = set(cfg.people.values()) | ({cfg.default} if cfg.default else set())
    for name in sorted(set(cfg.roles) - used):
        notes.append(f"{path}: roles.{name}: nobody has this role here (the local file names the people)")
    if not cfg.default:
        notes.append(f"{path}: no default role, so anyone not named can only ask for help")
    return problems, notes


def check_access(config_dir: str | Path = "configs") -> tuple[list[str], list[str], list[str]]:
    """(files read, problems) for Slack's access rules under `config_dir`.

    The file in use is checked, and the tracked one too when a local file is
    standing in for it: a broken tracked file would only be found in the gate.
    """
    from temper_ai.integrations.slack import access as rules

    root = Path(config_dir)
    in_use = rules.config_path(root)
    if in_use is None:
        return [], [], []
    tracked = root / "slack" / "access.yaml"
    files = [in_use] + ([tracked] if tracked.is_file() and tracked != in_use else [])
    workflows = _workflows(root)
    repos = _answerable_repos(root)
    problems: list[str] = []
    notes: list[str] = []
    for path in files:
        holes, said = _access_problems(path, workflows, repos)
        problems.extend(holes)
        notes.extend(said)
    return [str(p) for p in files], problems, notes


def check(config_dir: str | Path = "configs") -> int:
    """Print the report. 0 when every setting lands, 1 when one does not."""
    seen, problems = check_effort(config_dir)
    print(f"Agent configs read: {seen}  (under {config_dir})")
    print(f"Effort levels: {', '.join(EFFORT_LEVELS)}")
    for provider in registered_providers():
        honours = honoured_effort(provider) or ()
        print(f"  {provider:12} effort: {', '.join(honours) if honours else 'no effort dial'}")
    if problems:
        print(f"\n\u26a0 {len(problems)} setting(s) go nowhere:")
        for line in problems:
            print(f"  {line}")
        print(
            "\nEither move the agent to a provider that takes it, or drop the line: "
            "a setting that is read and dropped reads like a control and is not one."
        )
    else:
        print("\n\u2713 every effort setting reaches the provider it is aimed at")

    files, access_problems, notes = check_access(config_dir)
    print()
    if not files:
        print("Slack access: no access file, so everyone in the workspace may do everything")
    else:
        print(f"Slack access rules read: {', '.join(files)}")
        for line in notes:
            print(f"  note: {line}")
        if access_problems:
            print(f"\n\u26a0 {len(access_problems)} problem(s) in the access rules:")
            for line in access_problems:
                print(f"  {line}")
            print("\nA role that allows a workflow that is not there, or forces an input it "
                  "does not take, is a fence with a hole in it.")
        else:
            print("\u2713 every role allows workflows that exist and forces inputs they take")
    return 1 if (problems or access_problems) else 0


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "check", help="Settings the provider cannot honour (effort), and Slack's access rules",
    )
    parser.add_argument("--config-dir", default="configs", help="Config directory")


def main(args) -> int:
    return check(args.config_dir)
