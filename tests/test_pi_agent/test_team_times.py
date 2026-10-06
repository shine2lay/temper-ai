"""The Team API's times (#60): each one it sends is ISO 8601 with ``+00:00``, and owner
actions sort by the moment, not the text. The routes themselves are walked in
tests/test_runner/pi_parking/test_team_api.py (test_every_time_the_team_api_sends_...)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from temper_ai.pi_agent.team_view import owner_actions, utc_moment, utc_text


@pytest.mark.parametrize(("value", "sent"), [
    # a naive datetime is UTC (every zoneless time temper stores is)
    (datetime(2026, 10, 6, 9, 28, 0, 882441, tzinfo=UTC).replace(tzinfo=None),
     "2026-10-06T09:28:00.882441+00:00"),
    # an aware one elsewhere is moved to UTC
    (datetime(2026, 10, 6, 2, 28, tzinfo=timezone(timedelta(hours=-7))),
     "2026-10-06T09:28:00+00:00"),
    (datetime(2026, 10, 6, 9, 28, tzinfo=UTC), "2026-10-06T09:28:00+00:00"),
    # a recorded event's timestamp: ISO text without a zone
    ("2026-10-06T09:28:00.882441", "2026-10-06T09:28:00.882441+00:00"),
    # text with an offset keeps its moment
    ("2026-10-06T11:28:00+02:00", "2026-10-06T09:28:00+00:00"),
    ("2026-10-06T09:28:00.000001+00:00", "2026-10-06T09:28:00.000001+00:00"),
    ("2026-10-06 09:28:00", "2026-10-06T09:28:00+00:00"),
    (None, None),
    ("", None),
])
def test_utc_text_writes_the_offset_out(value, sent):
    assert utc_text(value) == sent


def test_text_that_is_no_time_is_refused_not_passed_on():
    with pytest.raises(ValueError):
        utc_text("yesterday")


def test_utc_moment_is_aware_utc():
    got = utc_moment("2026-10-06T09:28:00")
    assert got == datetime(2026, 10, 6, 9, 28, tzinfo=UTC) and got.tzinfo is not None


def test_owner_actions_carry_the_offset_and_sort_by_the_moment():
    """Caller actions come from events whose timestamps have no zone; whatever the text looks
    like (precision, offset, separator), they sort by the moment it means."""
    events = [
        {"timestamp": "2026-10-06 09:28:02.5", "data": {"action": "cancel"}},
        {"timestamp": "2026-10-06T11:28:01+02:00", "data": {"action": "message"}},
        {"timestamp": "2026-10-06T09:28:00.900000", "data": {"action": "start"}},
        {"timestamp": "2026-10-06T09:28:03", "data": {"action": "approve"}},  # not shown
    ]
    got = owner_actions(None, events, ["owner-dashboard"])
    assert [(a["kind"], a["at"]) for a in got] == [
        ("start", "2026-10-06T09:28:00.900000+00:00"),
        ("message", "2026-10-06T09:28:01+00:00"),
        ("stop", "2026-10-06T09:28:02.500000+00:00")]
