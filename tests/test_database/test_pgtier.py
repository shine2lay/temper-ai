"""The database tier tests itself: the right engine, and never the live one."""

from __future__ import annotations

import os
import re
import subprocess

import pytest

from temper_ai.database import get_database
from tests import pgtier


class TestItRunsWhereItSays:
    def test_this_test_is_on_postgres_exactly_when_the_tier_is_on(self):
        """tests/test_database/ is in the tier, so this file proves the switch.

        Without the switch the tier could quietly fall back to SQLite and the
        whole point — running against what temper runs on — would be lost
        with nothing to show it.
        """
        url = str(get_database().engine.url)
        if os.environ.get(pgtier.TIER_ENV, "").strip():
            assert url.startswith("postgresql"), url
        else:
            assert url.startswith("sqlite"), url

    def test_each_worker_gets_a_schema_of_its_own(self):
        if not os.environ.get(pgtier.TIER_ENV, "").strip():
            pytest.skip("the tier is off")
        from sqlalchemy import text
        with get_database().engine.connect() as conn:
            schema = conn.execute(text("SELECT current_schema()")).scalar()
        assert schema == pgtier.schema_name()
        assert re.fullmatch(rf"tier_p\d+_{os.environ.get('PYTEST_XDIST_WORKER', 'master')}", schema)

    def test_a_schema_is_left_behind_only_once_its_run_has_ended(self):
        """Two runs share the test Postgres: one never drops a schema of a run still going."""
        ended = subprocess.Popen(["true"])
        ended.wait()

        assert pgtier._run_is_gone(f"tier_p{ended.pid}_gw3")
        assert not pgtier._run_is_gone(f"tier_p{os.getpid()}_gw3")
        assert not pgtier._run_is_gone("tier_gw3")  # the old names: never dropped by anyone else

    def test_a_stored_time_comes_back_with_its_zone(self):
        """The bug that broke CI for eight days, on the database that matters."""
        from datetime import UTC, datetime, timedelta

        from sqlmodel import select

        from temper_ai.database import get_session
        from temper_ai.integrations.inbox.models import InboxEvent
        from temper_ai.shared.clock import as_utc

        at = datetime.now(UTC) - timedelta(hours=3)
        with get_session() as session:
            session.add(InboxEvent(source="tz", delivery="d-1", received_at=at, updated_at=at))
            session.commit()
        with get_session() as session:
            row = session.exec(select(InboxEvent).where(InboxEvent.source == "tz")).one()
            assert as_utc(row.received_at) == at


class TestItRefusesARealDatabase:
    @pytest.mark.parametrize("url, why", [
        ("postgresql://temper_ai:x@127.0.0.1:5433/temper_ai_test", "5433"),
        ("postgresql://temper_ai:x@127.0.0.1:5455/temper_ai", "test"),
        ("postgresql://temper_ai:x@127.0.0.1:5455/postgres", "test"),
        ("postgresql://temper_ai:x@db.example.com/production", "test"),
        ("sqlite:///x.db", "postgresql"),
    ])
    def test_refuses(self, url, why):
        with pytest.raises(RuntimeError) as exc:
            pgtier.check_url(url)
        assert why in str(exc.value)

    def test_refuses_the_url_the_server_itself_uses(self, monkeypatch):
        monkeypatch.setenv("TEMPER_DATABASE_URL", "postgresql://u:p@host:5432/temper_ai_test")
        with pytest.raises(RuntimeError, match="same database"):
            pgtier.check_url("postgresql://u:p@host:5432/temper_ai_test")

    def test_allows_a_throwaway(self):
        url = "postgresql://temper_ai:test@127.0.0.1:5455/temper_ai_test"
        assert pgtier.check_url(url) == url


class TestWhatIsInTheTier:
    @pytest.mark.parametrize("path", [
        "tests/test_database/test_engine.py",
        "/home/x/temper-ai/tests/test_checkpoint/test_store.py",
        "tests/test_observability/test_reconcile.py",
        "tests/test_integrations/test_inbox.py",
        "tests/test_runner/test_runs.py",
    ])
    def test_in(self, path):
        assert pgtier.in_tier(path)

    @pytest.mark.parametrize("path", [
        "tests/test_llm/test_service.py",
        "tests/test_integrations/test_inbox_helpers.py",   # a near name is not the file
        "tests/test_tools/test_http.py",
    ])
    def test_out(self, path):
        assert not pgtier.in_tier(path)
