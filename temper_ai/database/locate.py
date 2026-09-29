"""Find temper's own database for commands run on the host.

The server and worker get ``TEMPER_DATABASE_URL`` from docker compose. A
command typed on the host (``temper connect``, ``temper connections``) does
not, or gets one left in a shell profile for some other project. Both the
engine's default and such a leftover pointed at ``localhost:5432``, another
project's Postgres, so a grant written there was invisible to the server.
On the host these commands therefore use temper's compose database, check
that it holds temper's tables, and refuse otherwise.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from temper_ai.database.engine import TEMPER_DATABASE_URL_ENV

# docker-compose.yml publishes temper's Postgres on ${POSTGRES_PORT:-5433}.
COMPOSE_PORT_DEFAULT = "5433"
# A table only temper's schema has, to tell its database from a stranger's.
MARKER_TABLE = "workflow_runs"
# Set this to point a host command somewhere else on purpose.
HOST_OVERRIDE_ENV = "TEMPER_HOST_DATABASE_URL"


class DatabaseNotFound(Exception):
    """Temper's database could not be found; the message says what to do."""


def compose_url(env: Mapping[str, str] | None = None) -> str:
    """The URL of the compose Postgres as seen from the host."""
    env = os.environ if env is None else env
    password = env.get("POSTGRES_PASSWORD") or "temper_dev"
    port = env.get("POSTGRES_PORT") or COMPOSE_PORT_DEFAULT
    host = env.get("TEMPER_BIND") or "127.0.0.1"
    if host in ("0.0.0.0", ""):  # noqa: S104 - a bind address, read back as loopback
        host = "127.0.0.1"
    return f"postgresql://temper_ai:{password}@{host}:{port}/temper_ai"


def in_container() -> bool:
    return Path("/.dockerenv").exists()


def _looks_like_temper(url: str) -> bool:
    from sqlalchemy import create_engine, inspect

    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    try:
        return inspect(engine).has_table(MARKER_TABLE)
    finally:
        engine.dispose()


def resolve_host_database_url(env: Mapping[str, str] | None = None,
                              probe: Callable[[str], bool] | None = None,
                              container: bool | None = None) -> str:
    """The database a command that writes grants should use.

    Inside temper's containers ``TEMPER_DATABASE_URL`` is compose's own and
    is used as is. On the host, ``TEMPER_HOST_DATABASE_URL`` wins if set;
    otherwise the compose database is used after checking it holds temper's
    tables. A host ``TEMPER_DATABASE_URL`` is not trusted, and there is no
    fallback to ``localhost:5432``.
    """
    env = os.environ if env is None else env
    container = in_container() if container is None else container
    # Looked up now, not pinned as a default argument: the test suite
    # replaces this so that nothing under pytest can go looking for a
    # database a real temper is serving from.
    probe = _looks_like_temper if probe is None else probe
    explicit = env.get(TEMPER_DATABASE_URL_ENV)
    if container and explicit:
        return explicit
    override = env.get(HOST_OVERRIDE_ENV)
    if override:
        return override
    url = compose_url(env)
    try:
        ok = probe(url)
    except AssertionError:
        # A failed assertion is a broken caller, not a database that is
        # down. Reporting it as "can't reach temper's database" would bury
        # the one message that says what actually went wrong.
        raise
    except Exception as exc:  # noqa: BLE001 - any connection failure means "not found"
        raise DatabaseNotFound(
            f"Can't reach temper's database at {_redact(url)} ({type(exc).__name__}). "
            "Start it with `docker compose up -d postgres`, run the command inside the "
            "server (`docker exec -it temper-ai-server-1 temper ...`), or set "
            f"{HOST_OVERRIDE_ENV}."
        ) from exc
    if not ok:
        raise DatabaseNotFound(
            f"The database at {_redact(url)} has no {MARKER_TABLE} table, so it isn't "
            f"temper's. Set {HOST_OVERRIDE_ENV} to temper's database."
        )
    if explicit and explicit != url:
        print(f"Note: using temper's database {_redact(url)}, not TEMPER_DATABASE_URL "
              f"({_redact(explicit)}).", file=sys.stderr)
    return url


def _redact(url: str) -> str:
    """The URL without its password."""
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.rsplit("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"
