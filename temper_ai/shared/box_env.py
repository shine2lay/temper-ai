"""Which of the server's environment variables a run box gets: an allow-list.

A box (spawner/docker_spawner.py) is where a run's agents, scripts and Bash
execute, so whatever is in its environment can be read from inside it with
one ``env``. It gets only the variables named in ``configs/boxes/env.yaml``
(generic temper names, tracked) and ``configs/boxes/local/env.yaml`` (this
install's names, git-ignored). Anything not listed stays in the server: a new
secret added to .env stays out of boxes until somebody lists it on purpose.

Each group in a file says which names, why a box needs them, and whether the
box's agent tool processes (the Claude CLI, the Bash tool, script steps, git)
may see them too (``agent_tools: true``), or only the box's own Python process
that records the run (the default). ``env_for_agent_tool`` (shared/agent_env.py)
reads the second half.

Fixed rules, whatever the files say:

- TEMPER_RUN_CONTAINER is always set by the spawner (the box's own name).
- The GitHub app's keys (integrations.github.secret.SERVER_ONLY) can never be
  listed: loading refuses them.
- A name that holds a secret (database URL, secret key, a *_KEY, *_TOKEN,
  *_SECRET, *_PASSWORD) can be listed for the box's process only, never with
  ``agent_tools: true``.

``TEMPER_BOX_ENV=inherit`` in the worker's environment brings back the old
copy-everything box (minus the GitHub app's keys), as an emergency rollback
only: off by default, and every spawn logs a warning while it is on.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from temper_ai.integrations.github.secret import SERVER_ONLY

logger = logging.getLogger(__name__)

#: The worker's switch for the emergency rollback; also passed into an inheriting box.
MODE_ENV = "TEMPER_BOX_ENV"
MODE_LIST = "list"
MODE_INHERIT = "inherit"

#: Always set by the spawner to the box's own container name.
RUN_CONTAINER_ENV = "TEMPER_RUN_CONTAINER"

#: A run's GitHub-token key (api/run_tokens.py) is for the run's own process only. It is put in
#: no environment today; should a later way of handing keys to the box ever put it in the box's
#: own, this name, and any value that looks like one of these keys, still never reaches a tool
#: process (shared/agent_env.py).
RUN_GITHUB_KEY_ENV = "TEMPER_RUN_GITHUB_KEY"
RUN_GITHUB_KEY_PREFIX = "tghk_"

#: Never handed to an agent tool process, listed or not.
NEVER_FOR_AGENT_TOOLS = frozenset({
    "TEMPER_DATABASE_URL", "DATABASE_URL", "TEMPER_SECRET_KEY",
    "TEMPER_REDIS_URL", "REDIS_URL", "TEMPER_HOST_DATABASE_URL",
    RUN_GITHUB_KEY_ENV,
}) | SERVER_ONLY
#: A name ending like this holds a secret: the box's process may hold it, its tools may not.
SECRET_SUFFIXES = ("_KEY", "_TOKEN", "_TOKENS", "_SECRET", "_PASSWORD", "_CREDENTIALS")

_GROUP_KEYS = frozenset({"names", "why", "agent_tools"})
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class BoxEnvError(ValueError):
    """The box's allow-list cannot be read or breaks a fixed rule."""


@dataclass(frozen=True)
class BoxEnv:
    """The allow-list as loaded: every listed name, and those agent tools may see."""

    names: frozenset[str]
    agent_tools: frozenset[str]
    files: tuple[str, ...] = field(default=())

    def allows(self, name: str) -> bool:
        return name in self.names


def looks_secret(name: str) -> bool:
    """Whether a variable name holds a secret, by the names temper and its providers use."""
    upper = name.upper()
    return upper in NEVER_FOR_AGENT_TOOLS or upper.endswith(SECRET_SUFFIXES)


def default_config_dir() -> Path:
    """$TEMPER_CONFIG_DIR, else the repo's configs/ (the same root the runner reads)."""
    configured = os.environ.get("TEMPER_CONFIG_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "configs"


def list_paths(config_dir: str | Path | None = None) -> tuple[Path, Path]:
    """(tracked file, local file) under ``config_dir``."""
    root = (Path(config_dir) if config_dir else default_config_dir()) / "boxes"
    return root / "env.yaml", root / "local" / "env.yaml"


def _groups(path: Path) -> list[tuple[list[str], bool]]:
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise BoxEnvError(f"{path}: cannot be read: {exc}") from exc
    if data is None:
        return []
    if not isinstance(data, dict) or set(data) != {"box_env"}:
        raise BoxEnvError(f"{path}: must hold one key, box_env: a list of groups")
    groups = data["box_env"] or []
    if not isinstance(groups, list):
        raise BoxEnvError(f"{path}: box_env must be a list of groups")
    out: list[tuple[list[str], bool]] = []
    for i, group in enumerate(groups):
        where = f"{path}: box_env[{i}]"
        if not isinstance(group, dict):
            raise BoxEnvError(f"{where}: must be a mapping with names, why and optionally agent_tools")
        unknown = set(group) - _GROUP_KEYS
        if unknown:
            raise BoxEnvError(f"{where}: unknown key(s) {sorted(unknown)}; allowed: {sorted(_GROUP_KEYS)}")
        why = group.get("why")
        if not isinstance(why, str) or not why.strip():
            raise BoxEnvError(f"{where}: why is required: say who in the box reads these names")
        names = group.get("names")
        if not isinstance(names, list) or not names:
            raise BoxEnvError(f"{where}: names must be a non-empty list")
        agent_tools = group.get("agent_tools", False)
        if not isinstance(agent_tools, bool):
            raise BoxEnvError(f"{where}: agent_tools must be true or false")
        for name in names:
            if not isinstance(name, str) or not _NAME.match(name):
                raise BoxEnvError(f"{where}: {name!r} is not a variable name")
            if name in SERVER_ONLY:
                raise BoxEnvError(
                    f"{where}: {name} stays in the server and can never be listed "
                    "(integrations.github.secret.SERVER_ONLY)")
            if agent_tools and looks_secret(name):
                raise BoxEnvError(
                    f"{where}: {name} holds a secret: list it without agent_tools "
                    "(the box's process only), never for agent tools")
        out.append((list(names), agent_tools))
    return out


def load_box_env(config_dir: str | Path | None = None) -> BoxEnv:
    """The allow-list from the tracked file and, when present, the local one.

    The tracked file must exist: without it a box would get nothing it needs, so a
    spawn fails loudly instead. A name listed twice is an error, so each name has
    exactly one reason and one answer to "may agent tools see it?".
    """
    tracked, local = list_paths(config_dir)
    if not tracked.is_file():
        raise BoxEnvError(f"{tracked}: missing; a box's allow-list must exist (docs/boxes.md)")
    names: dict[str, str] = {}
    agent_tools: set[str] = set()
    files = [tracked] + ([local] if local.is_file() else [])
    for path in files:
        for group_names, tools in _groups(path):
            for name in group_names:
                if name in names:
                    raise BoxEnvError(f"{path}: {name} is listed again (first in {names[name]})")
                names[name] = str(path)
                if tools:
                    agent_tools.add(name)
    return BoxEnv(names=frozenset(names), agent_tools=frozenset(agent_tools),
                  files=tuple(str(p) for p in files))


def box_env_mode(environ: dict[str, str] | None = None) -> str:
    """``list`` (the default) or ``inherit`` (the emergency rollback).

    Anything else is read as ``list``, with a warning: a mistyped switch never
    opens the box.
    """
    value = (environ if environ is not None else os.environ).get(MODE_ENV, "").strip().lower()
    if value in ("", MODE_LIST):
        return MODE_LIST
    if value == MODE_INHERIT:
        return MODE_INHERIT
    logger.warning("%s=%r is not 'list' or 'inherit'; using the allow-list", MODE_ENV, value)
    return MODE_LIST


def check_box_env(config_dir: str | Path = "configs") -> tuple[list[str], list[str]]:
    """(files read, problems) for ``temper check``.

    A config folder with no list at all reads as none (nothing to check there); a
    local list without the tracked one, or a list that does not load, is a problem.
    """
    tracked, local = list_paths(config_dir)
    files = [str(p) for p in (tracked, local) if p.is_file()]
    if not files:
        return [], []
    try:
        load_box_env(config_dir)
    except BoxEnvError as exc:
        return files, [str(exc)]
    return files, []
