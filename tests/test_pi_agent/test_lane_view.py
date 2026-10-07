"""ADR-M4-21 (finding F-ROLELIST): the Pi lane view, piece by piece (shared/pi_lane_view.py,
pi_agent/team_check.py's ``load_box_or_lane_view``, and the Pi lane watcher's write).

pi-worker writes the view from its disk while its preflight passes; outside the Pi lane the team
checks read only the view and say what the disk says, word for word; in the Pi lane they read
only the disk. A stand-in Redis (lane_view_support.py); no network, no container, no model.
The whole happy path comes first, then the role-folder cases, the writer's and the reader's
edges, the one-way rule (H4), the watcher and the switch off. The Team page's routes over the
view are tests/test_runner/pi_parking/test_lane_view_api.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import signal
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from temper_ai.cli import watch_queue as wq
from temper_ai.pi_agent import team_check
from temper_ai.pi_agent.box import BoxConfig
from temper_ai.pi_agent.team_check import LaneView, RoleList, check_team
from temper_ai.runner import pi_lane
from temper_ai.runner.lanes import LANE_ENV, PI_LANE
from temper_ai.shared import pi_lane_view
from temper_ai.shared.clock import utcnow
from tests.test_pi_agent import lane_view_support as lv
from tests.test_pi_agent import test_team as tt
from tests.test_pi_agent.support import WORKTREE
from tests.test_runner.pi_lane import test_drain as drain
from tests.test_runner.pi_lane import test_redis_decides_nothing as h4

team_on = tt.team_on
mark = drain.mark

KEY = pi_lane_view.KEY
LOGGER = pi_lane_view.__name__
NONE_PUBLISHED = pi_lane_view.problem(f"none published in the last {pi_lane_view.TTL_S} s")
#: One member whose role is a near miss, so both sides must give the same hint.
NEAR_MISS = {"name": "frontend", "type": "pi", "role": "frontnd", "tools": ["Read", "Edit"]}


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def no_disk(cls, path=None):
    raise AssertionError("the checks read the worker box config from the disk")


def logged(caplog) -> str:
    """What the view's module logged (other modules' lines left out)."""
    return "\n".join(r.getMessage() for r in caplog.records if r.name == LOGGER)


def team() -> list[dict]:
    first, _, last = tt.members()
    return [first, NEAR_MISS, last]


# --- the happy path -------------------------------------------------------------------------


def test_the_view_is_written_from_disk_and_outside_the_lane_says_what_the_disk_says(
        team_on, monkeypatch, caplog):
    """In one: pi-worker (in the Pi lane, its preflight passed) writes the view, with its
    expiry and names only; in the Pi lane the checks read the disk and never Redis; outside it
    they read only the view and give the disk's role cards and the disk's words, a near miss's
    hint included; the writer waits between writes, keeps a passed preflight for 300 s and
    never reads; and once it withdraws the view the checks say the lane isn't running."""
    disk_box = BoxConfig.load(str(team_on))
    roles = RoleList(Path(disk_box.identities_dir))
    preflights: list[int] = []
    clock = Clock()
    monkeypatch.setenv(LANE_ENV, PI_LANE)  # as conftest.py sets it; said here, as it matters
    fake = lv.serve(monkeypatch)
    writer = lv.publisher(fake, str(team_on), clock=clock,
                          preflight=lambda: preflights.append(1) or [])
    with caplog.at_level(logging.INFO, logger=LOGGER):
        assert writer.tick() == "published"
    assert fake.calls == ["set"] and fake.ttl[KEY] == pi_lane_view.TTL_S
    raw = fake.data[KEY]
    view = json.loads(raw)
    assert set(view) == pi_lane_view.VIEW_KEYS
    assert all(set(card) == pi_lane_view.CARD_KEYS for card in view["roles"])
    assert view["box_config_sha256"] == hashlib.sha256(team_on.read_bytes()).hexdigest()
    assert (view["routes"], view["add_ons"], view["search_tools"]) == (
        sorted(disk_box.routes), sorted(disk_box.add_ons), sorted(disk_box.search_tools))
    assert view["role_ids"] == roles.ids() == sorted(tt.ROLES)
    assert view["roles"] == [roles.card(role) for role in roles.ids()]
    for private in (str(team_on.parent.parent), "homeChat", "/home/owner", ".jsonl"):
        assert private not in raw and private not in logged(caplog), private
    assert "Pi lane view: published (3 role(s), box config " in logged(caplog)

    box, problem = team_check.load_box_or_lane_view()  # the Pi lane: the disk only
    assert isinstance(box, BoxConfig) and problem is None and fake.calls == ["set"]

    monkeypatch.delenv(LANE_ENV)
    with monkeypatch.context() as m:  # outside the Pi lane: the view only
        m.setattr(BoxConfig, "load", classmethod(no_disk))
        lane_box, problem = team_check.load_box_or_lane_view()
    assert isinstance(lane_box, LaneView) and problem is None
    assert lane_box.box_config_sha256 == view["box_config_sha256"]
    listed = team_check.role_list(lane_box)
    assert listed.ids() == roles.ids()
    assert [listed.card(role) for role in listed.ids()] == view["roles"]
    by_disk = check_team(team(), tt.RUNNABLE, inputs=tt.GOAL, box=disk_box)
    assert by_disk == ["member 'frontend': role 'frontnd' is not in the role list (did you mean "
                       "'frontend'? Not picked automatically)"]
    assert check_team(team(), tt.RUNNABLE, inputs=tt.GOAL, box=lane_box) == by_disk
    assert check_team(tt.members(), tt.RUNNABLE, inputs=tt.GOAL, box=lane_box) == []

    assert writer.tick() == "waiting"
    clock.t += pi_lane_view.PUBLISH_EVERY_S
    assert writer.tick() == "published" and len(preflights) == 1
    clock.t += pi_lane_view.PREFLIGHT_EVERY_S
    assert writer.tick() == "published" and len(preflights) == 2
    writer.withdraw()
    assert KEY not in fake.data
    assert team_check.load_box_or_lane_view() == (None, NONE_PUBLISHED)
    assert [c for c in fake.calls if c != "get"] == ["set", "set", "set", "delete"]
    assert fake.calls.count("get") == 2  # the two reads outside the lane; the writer never


# --- the view says what the disk says --------------------------------------------------------


def _identity(**fields) -> str:
    return json.dumps(fields)


BROKEN = {
    "no identity": lambda f: (f / "identity.json").unlink(),
    "unreadable identity": lambda f: (f / "identity.json").write_text("{not json"),
    "identity not an object": lambda f: (f / "identity.json").write_text("[1]"),
    "no about page": lambda f: (f / "about.md").unlink(),
    "no home chat": lambda f: (f / "identity.json").write_text(_identity(id="qa", title="QA")),
    "blank title": lambda f: (f / "identity.json").write_text(
        _identity(id="qa", title=" ", homeChat="/home/owner/.pi/sessions/qa.jsonl")),
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_a_role_reads_the_same_from_the_view_as_from_the_disk(team_on, monkeypatch, case):
    disk_box = BoxConfig.load(str(team_on))
    BROKEN[case](Path(disk_box.identities_dir) / "qa")
    lv.publish(monkeypatch, str(team_on))
    monkeypatch.delenv(LANE_ENV)  # this package's tests run as the Pi lane (conftest.py)
    lane_box, problem = team_check.load_box_or_lane_view()
    assert isinstance(lane_box, LaneView) and problem is None
    disk, view = RoleList(Path(disk_box.identities_dir)), team_check.role_list(lane_box)
    for role in [*disk.ids(), "frontnd", "nobody", "../qa", "QA", ""]:
        assert view.problems(role) == disk.problems(role), role
        assert view.card(role) == disk.card(role), role
    by_disk = check_team(tt.members(), tt.RUNNABLE, inputs=tt.GOAL, box=disk_box)
    assert check_team(tt.members(), tt.RUNNABLE, inputs=tt.GOAL, box=lane_box) == by_disk
    assert bool(by_disk) is (case != "blank title"), by_disk


# --- the writer ------------------------------------------------------------------------------


def test_without_redis_the_writer_does_nothing(caplog):
    def never(*a):
        raise AssertionError("it ran something with no Redis set")

    writer = pi_lane_view.Publisher(None, preflight=never, connect=never, config_path=never)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        assert writer.tick() == writer.tick() == "off"
        writer.withdraw()
    assert logged(caplog).count("not published (no Redis is set for pi-worker)") == 1


def test_a_failed_or_raising_preflight_withdraws_the_view_and_runs_again_at_each_write(
        team_on, monkeypatch, caplog):
    answers: list = [[], [("check_pins", "a pin's digest differs")], RuntimeError("boom"), []]

    def preflight():
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    clock = Clock()
    fake = lv.serve(monkeypatch)
    writer = lv.publisher(fake, str(team_on), clock=clock, preflight=preflight)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        assert writer.tick() == "published"
        clock.t += pi_lane_view.PREFLIGHT_EVERY_S
        assert writer.tick() == "withdrawn" and KEY not in fake.data
        clock.t += pi_lane_view.PUBLISH_EVERY_S  # a failed one runs again at the next write
        assert writer.tick() == "withdrawn" and KEY not in fake.data
        clock.t += pi_lane_view.PUBLISH_EVERY_S
        assert writer.tick() == "published" and KEY in fake.data
    assert answers == []
    assert fake.calls == ["set", "delete", "delete", "set"]
    said = logged(caplog)
    assert "withdrawn, the preflight failed (check_pins)" in said
    assert "withdrawn, the preflight failed (preflight)" in said
    assert "digest differs" not in said and "boom" not in said


def test_an_unreadable_box_config_or_too_many_roles_withdraws_the_view(
        team_on, monkeypatch, tmp_path, caplog):
    fake = lv.publish(monkeypatch, str(team_on))
    missing = tmp_path / "gone" / "box.json"
    with caplog.at_level(logging.INFO, logger=LOGGER):
        assert lv.publisher(fake, str(missing)).tick() == "withdrawn"
        assert KEY not in fake.data
        monkeypatch.setattr(pi_lane_view, "MAX_ROLES", 2)
        assert lv.publisher(fake, str(team_on)).tick() == "withdrawn"
    said = logged(caplog)
    assert "the box config could not be read (FileNotFoundError)" in said
    assert str(missing) not in said
    assert "withdrawn, too big (3 roles, " in said
    assert fake.calls == ["set", "delete", "delete"]


def test_redis_down_fails_open_and_the_writer_tries_again(team_on, monkeypatch, caplog):
    clock = Clock()
    fake = lv.serve(monkeypatch, lv.FakeRedis(down=True))
    writer = lv.publisher(fake, str(team_on), clock=clock)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        assert writer.tick() == "failed"
        clock.t += pi_lane_view.PUBLISH_EVERY_S
        assert writer.tick() == "failed"
        fake.down = False
        clock.t += pi_lane_view.PUBLISH_EVERY_S
        assert writer.tick() == "published"
    assert logged(caplog).count("Redis did not answer (ConnectionError); trying again") == 1

    def refused(url):
        raise ConnectionRefusedError("no Redis here")

    unreachable = pi_lane_view.Publisher(lv.URL, preflight=lambda: [], connect=refused,
                                         config_path=lambda: str(team_on))
    assert unreachable.tick() == "failed"
    unreachable.withdraw()  # nothing to delete it from: no error either


# --- the reader ------------------------------------------------------------------------------


def _good(monkeypatch, team_on) -> dict:
    return json.loads(lv.publish(monkeypatch, str(team_on)).data[KEY])


def _mutations(good: dict) -> dict[str, tuple[object, str]]:
    now = utcnow()
    card = good["roles"][0]
    later = {**good, "published_at": (now + timedelta(seconds=10)).isoformat()}
    return {
        "an extra key": ({**good, "slot": "anthropic-2"}, "not in the expected format"),
        "a missing key": ({k: v for k, v in good.items() if k != "routes"},
                          "not in the expected format"),
        "a card's extra key": ({**good, "roles": [{**card, "home": "x"}, *good["roles"][1:]]},
                               "not in the expected format"),
        "a card under another id": ({**good, "roles": [{**card, "id": "other"},
                                                       *good["roles"][1:]]},
                                    "not in the expected format"),
        "the same id twice": ({**good, "role_ids": [good["role_ids"][0]] * 3},
                              "not in the expected format"),
        "a bad digest": ({**good, "box_config_sha256": "A" * 64}, "not in the expected format"),
        "a schema of true": ({**good, "schema": True},
                             "published in a format this server doesn't read"),
        "a time without a zone": ({**good, "published_at": now.replace(tzinfo=None).isoformat()},
                                  "not in the expected format"),
        "a name too long": ({**good, "routes": ["r" * 201]}, "not in the expected format"),
        "too many names": ({**good, "add_ons": [f"a{i}" for i in range(101)]},
                           "not in the expected format"),
        "a problem that isn't text": ({**good, "roles": [{**card, "problems": [1]},
                                                         *good["roles"][1:]]},
                                      "not in the expected format"),
        "a list": ([good], "not in the expected format"),
        "a number": (7, "unreadable"),
        "bytes that aren't UTF-8": (b"\xff\xfe", "unreadable"),
        "too many bytes": (b"x" * (pi_lane_view.MAX_BYTES + 1), "too big"),
        "ten seconds ahead": (later, ""),
        "no about page": ({**good, "roles": [{**card, "about": None}, *good["roles"][1:]]}, ""),
    }


def test_the_reader_takes_exactly_the_view_s_names_and_types(team_on, monkeypatch):
    good = _good(monkeypatch, team_on)
    now = utcnow()
    assert pi_lane_view.parse(pi_lane_view.encode(good).encode("utf-8"), now=now) == (good, None)
    for case, (value, why) in _mutations(good).items():
        raw = value if isinstance(value, (bytes, int)) else pi_lane_view.encode(value)
        view, problem = pi_lane_view.parse(raw, now=now)
        if why:
            assert (view, problem) == (None, pi_lane_view.problem(why)), case
        else:
            assert problem is None and view == value, case


def test_the_reader_refuses_a_view_older_than_its_limit(team_on, monkeypatch):
    good = _good(monkeypatch, team_on)
    published = pi_lane_view._when(good["published_at"])
    at_limit = published + timedelta(seconds=pi_lane_view.MAX_AGE_S)
    assert pi_lane_view.parse(pi_lane_view.encode(good), now=at_limit) == (good, None)
    over = at_limit + timedelta(seconds=1)
    assert pi_lane_view.parse(pi_lane_view.encode(good), now=over) == (
        None, pi_lane_view.problem("its last list is 121 s old"))


# --- one way (H4, SW-78) ---------------------------------------------------------------------


def test_only_the_checks_outside_the_lane_read_the_view_and_only_the_pi_lane_writes_it():
    """The view reads Redis, so the modules the Pi lane decides in may hold it only in two
    places: team_check.py, which reads it only outside the Pi lane (the happy path above), and
    the Pi lane's watcher, which only writes it. Nothing else in temper imports it."""
    users = sorted(
        str(path.relative_to(h4.ROOT)) for path in sorted((h4.ROOT / "temper_ai").rglob("*.py"))
        if "temper_ai.shared.pi_lane_view" in h4._imports(path))
    assert users == ["temper_ai/cli/watch_queue.py", "temper_ai/pi_agent/team_check.py"]
    deciding = {str(p.relative_to(h4.ROOT)) for part in h4.DECIDING
                for p in ((h4.ROOT / part).rglob("*.py") if (h4.ROOT / part).is_dir()
                          else [h4.ROOT / part])}
    assert set(users) <= deciding


# --- the watcher -----------------------------------------------------------------------------


def _watch(monkeypatch, tmp_path, *, lane: str | None, scans_before_stop: int) -> list:
    monkeypatch.setenv("TEMPER_DATABASE_URL", f"sqlite:///{tmp_path / 'watch.db'}")
    monkeypatch.setenv("TEMPER_PI_AGENT", "1")
    if lane:
        monkeypatch.setenv(LANE_ENV, lane)
    else:  # this package's tests run as the Pi lane (conftest.py)
        monkeypatch.delenv(LANE_ENV)
    monkeypatch.setattr(wq, "get_spawner", lambda: drain.Live([]))
    monkeypatch.setattr(pi_lane, "eager_import", lambda: (0, []))
    monkeypatch.setattr(pi_lane, "start_up", lambda: {})
    monkeypatch.setattr(wq, "_requeue_stuck_claims", lambda spawner, lane=None: 0)
    monkeypatch.setattr(wq, "Reaper", lambda *a, **kw: SimpleNamespace(
        start=lambda: None, stop=lambda: None))
    scans: list = []

    def scan(spawner, lane=None):
        scans.append(lane)
        if len(scans) == scans_before_stop:
            signal.raise_signal(signal.SIGTERM)
        return 0

    monkeypatch.setattr(wq, "_scan_and_dispatch", scan)
    before = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        assert wq.cmd_watch_queue(argparse.Namespace(poll_interval=0.01,
                                                     reaper_interval=60)) == 0
    finally:
        for sig, handler in before.items():
            signal.signal(sig, handler)
    return scans


def test_the_pi_lane_watcher_writes_the_view_each_tick_and_withdraws_it_when_it_stops(
        tmp_path, mark, monkeypatch):
    said: list[str] = []

    class View:
        def tick(self) -> str:
            said.append("tick")
            if len(said) == 2:
                raise RuntimeError("a failed write never stops the watcher")
            return "published"

        def withdraw(self) -> None:
            said.append("withdraw")

    monkeypatch.setattr(wq, "_lane_view_publisher", View)
    assert _watch(monkeypatch, tmp_path, lane=PI_LANE, scans_before_stop=3) == [PI_LANE] * 3
    assert said == ["tick", "tick", "withdraw"]  # none after the signal; withdrawn at the stop


def test_the_main_lane_watcher_never_writes_the_view(tmp_path, monkeypatch):
    def never():
        raise AssertionError("the main lane made a Pi lane view writer")

    monkeypatch.setattr(wq, "_lane_view_publisher", never)
    assert _watch(monkeypatch, tmp_path, lane=None, scans_before_stop=2) == [None, None]


# --- the switch off --------------------------------------------------------------------------


OFF_PROBE = r"""
import json, sys
from temper_ai.database import init_database
init_database(sys.argv[1])
from temper_ai.server import app
import temper_ai.cli.watch_queue
print(json.dumps({
    "team_routes": sorted(r.path for r in app.routes if r.path.startswith("/api/team")),
    "view": "temper_ai.shared.pi_lane_view" in sys.modules,
}))
"""


def test_switched_off_nothing_imports_the_view_and_there_is_no_team_api(tmp_path):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("TEMPER_PI_") and k not in (LANE_ENV, "TEMPER_DATABASE_URL")}
    env.update({"PYTHONPATH": str(WORKTREE), "TEMPER_EXECUTION_MODE": "inprocess",
                "TEMPER_LOG_DIR": str(tmp_path / "logs")})
    out = subprocess.run([sys.executable, "-c", OFF_PROBE, f"sqlite:///{tmp_path / 'off.db'}"],
                         cwd=WORKTREE, env=env, capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-3000:]
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {"team_routes": [], "view": False}
