"""The database tier: the tests that also run against a real Postgres.

Every test used an in-memory SQLite, including on GitHub, which started a
Postgres and never connected to it. SQLite is not what temper runs on, and
the difference is not academic — the time-zone rules, ``ON CONFLICT``, row
locking and ``RETURNING`` all behave differently. A bug in any of them
would have reached the live database untested.

So: set ``TEMPER_TEST_DATABASE_URL`` and the tests listed in ``TIER`` run
against that Postgres instead of SQLite, in the same pytest run. The rest
stay on SQLite, which keeps the whole suite at about twenty seconds.

Isolation, because the tier runs under ``pytest -n``:

* one **schema per xdist worker** (``tier_gw0``, ``tier_gw1``, ...), created
  on demand and owned by that worker alone;
* every table truncated before each test, so no test sees another's rows.

Safety: :func:`database_tier_url` refuses anything that could be a real
database. Live temper is ``temper_ai`` on port 5433; nothing the tests can
be pointed at may be called that, and the name must say ``test``.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import pytest

TIER_ENV = "TEMPER_TEST_DATABASE_URL"

#: Test files and folders that talk to the database. Paths are matched against
#: the test's path from the repository root, as a prefix, so a folder covers
#: everything under it. Add to this when a new test starts storing something.
TIER = (
    "tests/test_database/",                       # engine, session, URL handling
    "tests/test_checkpoint/",                     # checkpoints
    "tests/test_observability/",                  # events, and the reconciler
    "tests/test_runner/",                         # runs
    "tests/test_integrations/test_inbox.py",      # the event inbox
    "tests/test_integrations/test_notify_loop.py",  # notify copies
    "tests/test_integrations/test_notify_store.py",
    "tests/test_integrations/test_telegram.py",   # telegram threads and updates
    "tests/test_integrations/test_slack_door.py",
    "tests/test_integrations/test_slack_handlers.py",
    "tests/test_triggers/",                       # trigger fires
    "tests/test_memory/",                         # memory rows
)

# temper's own live database, which no test may ever open.
_FORBIDDEN_PORTS = {5433}
_FORBIDDEN_NAMES = {"temper_ai", "temper", "postgres"}

_worker_schema_ready: set[str] = set()


def in_tier(path: str) -> bool:
    """Is this test file part of the database tier?"""
    posix = f"/{str(path).replace(os.sep, '/').lstrip('/')}/"
    return any(f"/{entry}" in posix for entry in TIER)


def check_url(url: str) -> str:
    """Return the URL, or raise if it could be a real database.

    Loud on purpose. A test suite that truncates every table must never be
    able to point at anything but a throwaway.
    """
    parsed = urlparse(url)
    if parsed.scheme.split("+")[0] not in ("postgresql", "postgres"):
        raise RuntimeError(f"{TIER_ENV} must be a postgresql:// URL, got {parsed.scheme!r}")
    name = (parsed.path or "").lstrip("/")
    if parsed.port in _FORBIDDEN_PORTS:
        raise RuntimeError(
            f"{TIER_ENV} points at port {parsed.port}, where temper's live database runs. "
            "Start a throwaway Postgres on another port (scripts/test-postgres.sh)."
        )
    if name in _FORBIDDEN_NAMES or not re.search(r"test", name, re.I):
        raise RuntimeError(
            f"{TIER_ENV} names the database {name!r}. The tests truncate every table, "
            "so the name must say 'test' (for example temper_ai_test)."
        )
    live = os.environ.get("TEMPER_DATABASE_URL", "")
    if live and not live.startswith("sqlite") and urlparse(live).netloc == parsed.netloc \
            and urlparse(live).path == parsed.path:
        raise RuntimeError(f"{TIER_ENV} is the same database as TEMPER_DATABASE_URL ({name!r}).")
    return url


def _worker() -> str:
    """This xdist worker's name — ``gw0``, ``gw1``... or ``master`` when serial."""
    return os.environ.get("PYTEST_XDIST_WORKER", "master")


def database_tier_url(node: pytest.Item | None = None) -> str | None:
    """The Postgres URL this test should use, or None to stay on SQLite."""
    raw = os.environ.get(TIER_ENV, "").strip()
    if not raw:
        return None
    if node is not None and not in_tier(str(getattr(node, "path", node.fspath))):  # type: ignore[attr-defined]
        return None
    return _with_schema(check_url(raw), f"tier_{_worker()}")


def _with_schema(url: str, schema: str) -> str:
    """Point the connection at a schema of this worker's own."""
    if schema not in _worker_schema_ready:
        _create_schema(url, schema)
        _worker_schema_ready.add(schema)
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}options=-csearch_path%3D{schema}"


def _create_schema(url: str, schema: str) -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    finally:
        engine.dispose()


def truncate_everything() -> None:
    """Empty every table of this worker's schema, keeping the tables."""
    from sqlalchemy import text
    from sqlmodel import SQLModel

    from temper_ai.database import get_database

    names = [f'"{t.name}"' for t in SQLModel.metadata.sorted_tables]
    if not names:
        return
    engine = get_database().engine
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(names)} RESTART IDENTITY CASCADE"))
