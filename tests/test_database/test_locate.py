"""Host commands find temper's compose database or refuse; never localhost:5432."""

from __future__ import annotations

import pytest

from temper_ai.database.locate import (
    DatabaseNotFound,
    compose_url,
    resolve_host_database_url,
)


def test_inside_the_container_compose_url_is_used():
    seen = []
    url = resolve_host_database_url({"TEMPER_DATABASE_URL": "postgresql://x@postgres/t"},
                                    probe=seen.append, container=True)
    assert url == "postgresql://x@postgres/t" and seen == []


def test_host_ignores_a_stray_temper_database_url(capsys):
    env = {"TEMPER_DATABASE_URL": "postgresql://temper_ai:pw@localhost:5432/temper_ai"}
    url = resolve_host_database_url(env, probe=lambda u: True, container=False)
    assert ":5433/" in url and ":5432/" not in url
    assert "not TEMPER_DATABASE_URL" in capsys.readouterr().err


def test_host_override_wins():
    env = {"TEMPER_HOST_DATABASE_URL": "sqlite:///x.db"}
    assert resolve_host_database_url(env, probe=lambda u: False, container=False) == "sqlite:///x.db"


def test_compose_database_is_used_when_it_is_temper():
    env = {"POSTGRES_PASSWORD": "pw", "POSTGRES_PORT": "6000"}
    url = resolve_host_database_url(env, probe=lambda u: True, container=False)
    assert url == "postgresql://temper_ai:pw@127.0.0.1:6000/temper_ai"


def test_default_is_the_compose_port_not_5432():
    url = compose_url({})
    assert ":5433/" in url and ":5432/" not in url


def test_refuses_a_database_without_temper_tables():
    with pytest.raises(DatabaseNotFound, match="isn't temper's"):
        resolve_host_database_url({}, probe=lambda u: False, container=False)


def test_refuses_when_unreachable_and_hides_the_password():
    def boom(url):
        raise OSError("refused")

    with pytest.raises(DatabaseNotFound) as err:
        resolve_host_database_url({"POSTGRES_PASSWORD": "s3cret"}, probe=boom, container=False)
    assert "s3cret" not in str(err.value) and "docker compose" in str(err.value)


def test_pin_key_writes_once_and_never_prints(tmp_path, monkeypatch, capsys):
    from cryptography.fernet import Fernet

    from temper_ai.cli.connect import pin_key

    key = Fernet.generate_key()
    monkeypatch.delenv("TEMPER_SECRET_KEY", raising=False)
    monkeypatch.setattr("temper_ai.tools.mcp_auth._load_or_create_key", lambda *a: key)
    env = tmp_path / ".env"
    env.write_text("A=1\n")
    assert pin_key(env) == 0
    assert env.read_text() == f"A=1\nTEMPER_SECRET_KEY={key.decode()}\n"
    assert pin_key(env) == 0  # same key: nothing to do
    assert env.read_text().count("TEMPER_SECRET_KEY") == 1
    env.write_text("TEMPER_SECRET_KEY=other\n")
    assert pin_key(env) == 1 and env.read_text() == "TEMPER_SECRET_KEY=other\n"
    assert key.decode() not in capsys.readouterr().out


def test_connect_commands_refuse_instead_of_using_the_default(monkeypatch, capsys):
    from temper_ai.cli import connect

    def refuse(*a, **k):
        raise DatabaseNotFound("nope")

    monkeypatch.setattr("temper_ai.database.locate.resolve_host_database_url", refuse)
    called = []
    monkeypatch.setattr("temper_ai.database.session.init_database", lambda *a: called.append(a))
    assert connect._init_db() is False
    assert called == [] and "nope" in capsys.readouterr().err


class TestNoTestReachesALiveDatabase:
    """The guard in tests/conftest.py, pinned.

    Seven tests of `temper connect` used to pass on the owner's machine and
    fail on GitHub, for one reason: the command looks for temper's compose
    Postgres on port 5433, found the live one, and stored its grants there.
    A test that writes to the database a real temper is serving from is a
    bug whichever way it ends, so conftest takes the probe away.
    """

    def test_the_answer_is_this_tests_own_database(self, request):
        from temper_ai.database import locate
        from tests.conftest import TEST_DATABASE_URL

        assert locate.resolve_host_database_url() == request.node.stash[TEST_DATABASE_URL]

    def test_looking_for_a_real_one_is_an_error(self):
        from temper_ai.database import locate

        with pytest.raises(AssertionError, match="nothing under pytest"):
            locate._looks_like_temper("postgresql://temper_ai:pw@127.0.0.1:5433/temper_ai")

    def test_even_the_real_lookup_cannot_get_past_it(self):
        """Not just the shortcut: the actual function refuses too.

        The probe used to be pinned as a default argument, so replacing it
        did nothing and the lookup dialled 5433 regardless. It is looked up
        at call time now, and this is what says so.
        """
        from tests.conftest import REAL_RESOLVE_HOST_DATABASE_URL

        with pytest.raises(AssertionError, match="nothing under pytest"):
            REAL_RESOLVE_HOST_DATABASE_URL(env={}, container=False)

    def test_the_password_is_not_in_the_complaint(self):
        from temper_ai.database import locate

        with pytest.raises(AssertionError) as caught:
            locate._looks_like_temper("postgresql://temper_ai:hunter2@127.0.0.1:5433/temper_ai")
        assert "hunter2" not in str(caught.value)

    def test_opening_a_second_database_mid_test_is_an_error(self):
        from temper_ai.database import session as db_session

        with pytest.raises(AssertionError, match="loses the first one's tables"):
            db_session.init_database("postgresql://someone@elsewhere/other")
