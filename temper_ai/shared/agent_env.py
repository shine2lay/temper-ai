"""The environment one agent tool process starts with: only what it needs.

An agent tool process is anything temper starts for an agent to use: the
Claude CLI (and so its own Bash), the Bash tool, script steps, git. Whatever
is in its environment the agent can print, so it gets only:

- PATH, HOME, the locale and TZ, and the proxy settings, when set;
- TEMPER_RUN_CONTAINER and the names the box's allow-list marks
  ``agent_tools: true`` (shared/box_env.py), when set;
- the one model credential that call uses (``credential``), never the pool;
- the variables the agent's config passes explicitly (``extra``), as given.

Never the database URL, the secret key, another provider's keys, or anything
not on the box's list. The box's own Python process may hold those
(docs/boxes.md); its tools do not inherit them.

With ``TEMPER_BOX_ENV=inherit`` (the emergency rollback) a tool process gets
the old deny-list environment instead: everything but secret-looking names.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path

from temper_ai.shared import box_env

logger = logging.getLogger(__name__)

#: What every tool process gets when the box has it.
BASE_NAMES = frozenset({
    "PATH", "HOME", "TZ", "LANG", "LANGUAGE", "LC_ALL",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    box_env.RUN_CONTAINER_ENV,
})

_cache: dict[tuple, frozenset[str]] = {}
_warned: set[str] = set()


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _agent_tool_names(config_dir: str | Path | None) -> frozenset[str]:
    """The list's agent_tools names, read again when either file changes.

    A list that cannot be read gives none (fail closed), with one warning per
    error: the tool still starts, with the base names only.
    """
    tracked, local = box_env.list_paths(config_dir)
    key = (str(tracked), _mtime(tracked), _mtime(local))
    if key in _cache:
        return _cache[key]
    try:
        names = box_env.load_box_env(config_dir).agent_tools
    except box_env.BoxEnvError as exc:
        if str(exc) not in _warned:
            _warned.add(str(exc))
            logger.warning("Agent tools get only the base environment: %s", exc)
        names = frozenset()
    _cache.clear()
    _cache[key] = names
    return names


def _deny_list_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The old environment for tool processes: everything but secret-looking names."""
    drop_exact = box_env.NEVER_FOR_AGENT_TOOLS | {
        "SUDO_ASKPASS", "SSH_AUTH_SOCK", "TEMPER_DASHBOARD_TOKEN", "CLAUDE_CONFIG_DIR"}
    # A pool's numbered or backup slots (CLAUDE_CODE_OAUTH_TOKEN_2, ..._BACKUP) are secrets too.
    secret = re.compile(r"(_API_KEY|_SECRET|_SECRET_KEY|_TOKEN|_PASSWORD|_PRIVATE_KEY)(_BACKUP|_\d+)?$")
    return {k: v for k, v in environ.items()
            if k not in drop_exact and not secret.search(k)}


def env_for_agent_tool(
    *,
    credential: Mapping[str, str] | None = None,
    extra: Mapping[str, object] | None = None,
    environ: Mapping[str, str] | None = None,
    config_dir: str | Path | None = None,
) -> dict[str, str]:
    """A scrubbed environment for one agent tool process.

    ``credential``: the model credential this one call uses (one slot of a pool),
    added after the scrub. ``extra``: variables the agent's config passes
    explicitly, added last and as given. ``environ`` defaults to os.environ.
    """
    source = os.environ if environ is None else environ
    if box_env.box_env_mode(dict(source)) == box_env.MODE_INHERIT:
        env = _deny_list_env(source)
    else:
        wanted = BASE_NAMES | _agent_tool_names(config_dir)
        env = {k: v for k, v in source.items()
               if (k in wanted or k.startswith("LC_")) and k not in box_env.NEVER_FOR_AGENT_TOOLS}
    if credential:
        env.update({str(k): str(v) for k, v in credential.items()})
    if extra:
        # Caller-supplied values, applied after the scrub so they are never mistaken for
        # inherited secrets and removed. This is how script agents pass data to a script:
        # a value in the environment is data the shell will never parse as code.
        env.update({str(k): str(v) for k, v in extra.items()})
    return env
