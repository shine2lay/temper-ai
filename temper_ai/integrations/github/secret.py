"""The GitHub app's secrets, kept in the server's memory, never in an environment an agent can read.

``GITHUB_APP_PRIVATE_KEY`` signs the app's logins; with it anyone can act
as the app on every repository it is installed on. ``GITHUB_APP_WEBHOOK_SECRET``
proves a delivery is GitHub's. Both come from ``.env`` like the other keys,
and temper's own server code is the only thing that may use them.

A value in the environment is handed to every child process, and a run's
box is a copy of the server's container, environment and all: the Bash tool
strips ``*_SECRET`` and ``*_PRIVATE_KEY`` names (tools.bash), but a shell can
still read the environment its box started with. So:

* ``take()`` moves both out of ``os.environ`` into this module the first time
  temper is imported (``temper_ai/__init__.py``, and again after the CLI reads
  ``.env``): whatever the process starts afterwards (a CLI model provider, an
  MCP server) never has them.
* The spawners leave the ``SERVER_ONLY`` names out of a run's environment
  (docker_spawner, subprocess_spawner), so a run's box never starts with them.
  A run acts as the app with short-lived tokens for one repository each,
  which it asks the server for (integrations.github.app.ServerApp).

Nothing here reads a file, logs a value or turns one into a string anywhere
but the caller's HTTP request.
"""

from __future__ import annotations

import os
import threading

PRIVATE_KEY_ENV = "GITHUB_APP_PRIVATE_KEY"
WEBHOOK_SECRET_ENV = "GITHUB_APP_WEBHOOK_SECRET"  # noqa: S105 - a variable name, not a secret
CLIENT_SECRET_ENV = "GITHUB_APP_CLIENT_SECRET"  # noqa: S105 - a variable name, not a secret
NAMES = (PRIVATE_KEY_ENV, WEBHOOK_SECRET_ENV)
# Never in a run's environment: only temper's server may hold these.
SERVER_ONLY = frozenset({PRIVATE_KEY_ENV, WEBHOOK_SECRET_ENV, CLIENT_SECRET_ENV})

_held: dict[str, str] = {}
_lock = threading.Lock()


def take() -> None:
    """Move the secrets from the environment into memory (again if they were set since)."""
    with _lock:
        for name in NAMES:
            value = os.environ.pop(name, None)
            if value is not None:
                if value.strip():
                    _held[name] = value
                else:
                    _held.pop(name, None)
        os.environ.pop(CLIENT_SECRET_ENV, None)  # not used by temper at all


def get(name: str) -> str | None:
    """One secret, or None if it is not set."""
    take()
    with _lock:
        value = _held.get(name, "")
    return value.strip() or None


def private_key() -> str | None:
    return get(PRIVATE_KEY_ENV)


def webhook_secret() -> str | None:
    return get(WEBHOOK_SECRET_ENV)


def without_server_only(env: dict[str, str]) -> dict[str, str]:
    """``env`` without the names only the server may hold (for a run's environment)."""
    return {k: v for k, v in env.items() if k not in SERVER_ONLY}


def forget() -> None:
    """Drop what is held (tests)."""
    with _lock:
        _held.clear()
