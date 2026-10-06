"""Shared test fixtures."""

import pytest

from temper_ai.database import init_database, locate, reset_database
from temper_ai.tools.executor import ToolExecutor
from tests.pgtier import database_tier_url, truncate_everything

# The database this test got, so the guard below can hand back the same one.
TEST_DATABASE_URL = pytest.StashKey[str]()

# Kept before the guard replaces it, so the guard itself can be tested.
REAL_RESOLVE_HOST_DATABASE_URL = locate.resolve_host_database_url


@pytest.fixture(autouse=True)
def _test_db(request):
    """A fresh database for each test.

    In-memory SQLite by default: fast, and every test gets its own.

    With ``TEMPER_TEST_DATABASE_URL`` set, the tests of the database tier
    (tests/pgtier.py says which) run against the real thing instead —
    Postgres is what temper runs on, and SQLite hid a whole class of bug:
    the time-zone rules, the unique constraints and the row locking are all
    Postgres's, not SQLite's. Everything else stays on SQLite in the same
    run, so the tier costs seconds, not minutes.
    """
    reset_database()
    url = database_tier_url(request.node)
    if url:
        init_database(url)
        truncate_everything()
    else:
        url = "sqlite:///:memory:"
        init_database(url)
    request.node.stash[TEST_DATABASE_URL] = url
    yield
    reset_database()


@pytest.fixture(autouse=True)
def _never_the_live_database(request, monkeypatch):
    """No test may reach the database a running temper is using.

    ``temper connect`` and friends are typed on the host, where
    ``TEMPER_DATABASE_URL`` is absent or belongs to another project, so
    ``resolve_host_database_url`` goes looking for temper's compose Postgres
    on port 5433 and ``_init_db`` points the global engine at whatever it
    finds. Under pytest that is a live database: on a developer's machine
    these tests quietly stored their grants in it and passed, and on GitHub,
    where nothing answers on 5433, the same tests failed. Seven of them did,
    which is how this was found.

    So the probe is taken away and the answer is the test's own database.
    A test that wants to exercise the real lookup passes its own ``probe``
    and ``env``, which is untouched here.
    """
    def refuse(url: str) -> bool:
        raise AssertionError(
            f"A test tried to reach {locate._redact(url)} to see whether it is "
            "temper's database. Tests get the database the _test_db fixture "
            "made; nothing under pytest may touch a real one."
        )

    monkeypatch.setattr(locate, "_looks_like_temper", refuse)
    monkeypatch.setattr(
        locate,
        "resolve_host_database_url",
        lambda *a, **kw: request.node.stash[TEST_DATABASE_URL],
    )

    # ...and the engine stays the one the fixture opened. Only the host
    # commands re-import this inside the call, so only they are affected;
    # opening "sqlite:///:memory:" a second time would hand back a fresh
    # empty database with none of the test's tables in it.
    from temper_ai.database import session as db_session

    def keep_the_test_database(url: str, *a, **kw):
        expected = request.node.stash[TEST_DATABASE_URL]
        assert url == expected, (
            f"A test tried to open {url!r} while its own database is "
            f"{expected!r}. Tests share one database per test; opening "
            "another mid-test loses the first one's tables."
        )

    monkeypatch.setattr(db_session, "init_database", keep_the_test_database)


@pytest.fixture(autouse=True)
def _no_shared_rate_limits():
    """Rate-limit coolings are shared through Redis when TEMPER_REDIS_URL is
    set. A test must neither read nor clear a real Redis's list, nor leave
    its own coolings for the next test: sharing starts off in every test,
    and the tests of sharing turn it on over a fake Redis."""
    from temper_ai.llm import shared_cooldowns

    shared_cooldowns.use(shared_cooldowns.SharedCooldowns(None))
    yield
    shared_cooldowns.use(None)


@pytest.fixture(autouse=True)
def _no_sealed_box_guard():
    """A test that ran a sealed box's runner leaves no launch guard behind for the next one
    (temper_ai/spawner/box_guard.py holds it for the process, as a box runs one launch)."""
    from temper_ai.spawner import box_guard

    box_guard.reset()
    yield
    box_guard.reset()


@pytest.fixture(autouse=True)
def _no_trigger_scheduler(monkeypatch):
    """A test server must not fire the repo's schedules in the background,
    nor connect to Slack."""
    monkeypatch.setenv("TEMPER_TRIGGER_SCHEDULER", "0")
    monkeypatch.setenv("TEMPER_SLACK", "0")


@pytest.fixture(autouse=True)
def _scratch_dirs_under_pytest_tmp(tmp_path_factory, monkeypatch):
    """Keep every executor's scratch directory under pytest's own tmp.

    An executor makes its scratch directory the first time a path strays
    outside the workspace and removes it on shutdown(). Tests make executors
    by the dozen and rarely shut them down, so left alone the suite would
    leave one temper-scratch-* in /tmp per straying test, forever. pytest
    prunes its own tmp tree (last three runs)."""
    monkeypatch.setattr(
        ToolExecutor, "_make_scratch_dir",
        lambda self: str(tmp_path_factory.mktemp("temper-scratch-")),
    )


_CREDENTIAL_ENV = (
    "OPENAI_API_KEY", "OPENAI_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN",
    "GEMINI_API_KEY",
    "TYPESAFE_API_KEY", "TYPESAFE_BASE_URL",
)


@pytest.fixture(autouse=True)
def _no_provider_credentials(monkeypatch):
    """Providers resolve credentials from the environment. A developer with a
    token exported in their shell would otherwise make a test that builds a
    provider "with no key" build one with a key — test_headers_no_api_key
    failed exactly that way the first time OPENAI_OAUTH_TOKEN was exported.
    Tests that want a credential set it themselves."""
    for name in _CREDENTIAL_ENV:
        monkeypatch.delenv(name, raising=False)


_DOCKER_SPAWNER_ENV = (
    "TEMPER_DOCKER_WORKSPACES", "TEMPER_DOCKER_RUN_COMMAND",
    "TEMPER_DOCKER_TEMPLATE_CONTAINER", "TEMPER_DOCKER_IMAGE",
    "TEMPER_DOCKER_MEMORY", "TEMPER_DOCKER_CPUS", "TEMPER_DOCKER_PIDS_LIMIT",
)


@pytest.fixture(autouse=True)
def _no_docker_spawner_settings(monkeypatch):
    """The Docker spawner reads its settings from the environment, and a test
    that runs the CLI from the repo root loads the real .env into it (the CLI
    loads .env on start). The variables then stay for every later test in
    that worker: test_a_run_without_a_workspace_gets_no_writable_host_path
    failed that way once the owner's .env said TEMPER_DOCKER_WORKSPACES=all.
    Tests that want a setting set it themselves."""
    for name in _DOCKER_SPAWNER_ENV:
        monkeypatch.delenv(name, raising=False)
