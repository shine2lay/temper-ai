"""ADR-M4-21 (finding F-ROLELIST): the server holds no Pi folder (it is the run boxes'
template), so outside the Pi lane the Team page's role list and its checks read only the Pi
lane view pi-worker publishes (shared/pi_lane_view.py); the Pi lane itself checks on its disk.

Through a real in-process Temper (test_team_api.py's ``api``), a stand-in Redis
(tests/test_pi_agent/lane_view_support.py), scripted members and no network. The whole happy
path comes first, then a forged view, bad values and the switch off. No helper and no token
are involved: the members are scripted.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from temper_ai.pi_agent import team_check
from temper_ai.pi_agent.box import BoxConfig
from temper_ai.runner.lanes import LANE_ENV
from temper_ai.shared import pi_lane_view
from temper_ai.shared.clock import utcnow
from tests.test_pi_agent import lane_view_support as lv
from tests.test_pi_agent import test_team as tt
from tests.test_runner.pi_lane import support as lane
from tests.test_runner.pi_parking import support as pw
from tests.test_runner.pi_parking import test_team_api as tapi
from tests.test_runner.pi_parking import test_team_runs as runs
from tests.test_runner.pi_parking.test_team_runs import prompts

team_on = tt.team_on
tr = runs.tr
api = tapi.api

KEY = pi_lane_view.KEY
NO_TURNS = {"design": 0, "frontend": 0, "qa": 0}


def disk_cards() -> list[dict]:
    """The role cards as the Pi lane reads them, from the box config's role folder."""
    roles = team_check.RoleList(Path(BoxConfig.load().identities_dir))
    return [roles.card(role) for role in roles.ids()]


def as_the_server(m) -> None:
    """The server as production runs it: not the Pi lane, Pi runs left to pi-worker, and no
    Pi folder it could read (any read of the box config from the disk fails the test)."""
    def no_disk(cls, path=None):
        raise AssertionError("the server read the worker box config from the disk")

    m.delenv(LANE_ENV, raising=False)
    m.setenv("TEMPER_EXECUTION_MODE", "external")
    m.setattr(BoxConfig, "load", classmethod(no_disk))


def roles_problem(text: str) -> str:
    return f"roles: {text}"


# --- the happy path -------------------------------------------------------------------------


def test_pi_worker_publishes_the_server_lists_and_checks_and_the_pi_lane_runs_the_team(
        api, monkeypatch):
    """The whole path in one: pi-worker (in the Pi lane, preflight passed) writes the view
    once, with its expiry; the server, holding no Pi folder, lists the same role cards the disk
    gives, passes the check and queues the trial for the Pi lane, reading Redis only; only the
    Pi lane claims it; and the Pi lane runs the same trial on its own disk checks (run start
    and the team node's start) to done without reading the view."""
    disk = disk_cards()
    fake = lv.serve(monkeypatch)
    assert lv.publisher(fake).tick() == "published"
    assert fake.calls == ["set"] and fake.ttl[KEY] == pi_lane_view.TTL_S

    with monkeypatch.context() as m:
        as_the_server(m)
        status = api.client.get("/api/team/status").json()
        assert status["roles_configured"] is True and status["roles_problem"] is None
        assert api.client.get("/api/team/roles").json() == {
            "configured": True, "problem": None, "roles": disk}
        assert api.client.post("/api/team/check", json=tapi.body(api)).json() == {
            "ok": True, "problems": [], "notes": []}
        queued = tapi.start_trial(api, tapi.body(api, "view-1"))
        assert queued["status"] == "queued", queued
        assert queued["execution_id"] not in api.state.running
    assert fake.calls[0] == "set" and set(fake.calls[1:]) == {"get"}, fake.calls
    lane.only_the_pi_lane_claims(queued["execution_id"])

    read_so_far = len(fake.calls)
    runs.script(api.led, ["done"])
    ran = tapi.start_trial(api, tapi.body(api, "view-2"))
    assert pw.wait_ended(ran["execution_id"], 1)[-1]["status"] == "completed"
    run = tapi.team_run(api, ran["execution_id"])
    assert run["state"] == "done" and run["outcome"]["decision"] == "done"
    assert fake.calls[read_so_far:] == [], "the Pi lane read the view"


# --- the view is advisory --------------------------------------------------------------------


def test_a_forged_all_ok_view_passes_the_server_but_the_pi_lane_refuses_on_disk(
        api, monkeypatch):
    """A view that says a missing role and a broken one are fine: the server's check passes
    it and queues the run for the Pi lane (the view is all the server has); the Pi lane's
    run-start check refuses the same trial with the disk's words before anything is saved or
    any member turn, without reading the view. (The team node's start check passes the disk's
    box config itself, team_leader.py, so it never reads the view either.)"""
    fake = lv.publish(monkeypatch)
    view = json.loads(fake.data[KEY])
    roles_dir = Path(BoxConfig.load().identities_dir)
    (roles_dir / "qa" / "about.md").unlink()  # broken on disk after pi-worker published
    view["role_ids"] = sorted([*view["role_ids"], "ghost"])
    ghost = {"id": "ghost", "title": "Ghost", "about": "# Ghost\n", "has_home_chat": True,
             "problems": []}
    view["roles"] = sorted([*view["roles"], ghost], key=lambda card: card["id"])
    fake.data[KEY] = pi_lane_view.encode(view)
    raw = tapi.body(api, "forged-1", members=[
        {"name": "design", "role": "architecture"},
        {"name": "frontend", "role": "ghost", "tools": ["Read", "Edit"]},
        {"name": "qa", "role": "qa", "tools": ["Read", "Grep"]}])

    with monkeypatch.context() as m:  # outside the Pi lane, the view is the only word
        as_the_server(m)
        assert api.client.post("/api/team/check", json=raw).json() == {
            "ok": True, "problems": [], "notes": []}
        queued = tapi.start_trial(api, raw)
        assert queued["status"] == "queued", queued
    lane.only_the_pi_lane_claims(queued["execution_id"])

    gets = fake.calls.count("get")
    # in the Pi lane, the run-start check reads the disk and refuses with the disk's words
    lane_said = api.client.post("/api/team/check", json={**raw, "request_id": "forged-2"}).json()
    assert lane_said["ok"] is False
    texts = [p["text"] for p in lane_said["problems"]]
    assert any(t.startswith("member 'frontend': role 'ghost' is not in the role list")
               for t in texts), texts
    assert any(t.startswith("member 'qa': ") and "about page" in t for t in texts), texts
    r = api.client.post("/api/team/trials", json={**raw, "request_id": "forged-2"})
    assert r.status_code == 400, r.text
    assert len(tapi.trial_rows(api)) == 1 and prompts() == NO_TURNS
    assert fake.calls.count("get") == gets, "the Pi lane read the view"


# --- no usable view: a plain roles problem, never the disk, never a 500 ---------------------


def test_no_usable_view_is_a_plain_roles_problem_on_every_route(api, monkeypatch):
    """Missing or expired, stale, from the future, another schema, oversized, unreadable,
    wrongly typed, or Redis not answering: each is the roles problem 'the Pi lane isn't
    running ...' on the status, the role list, the check and the start, and nothing starts."""
    fresh = json.loads(lv.publish(monkeypatch).data[KEY])
    now = utcnow()
    old = {**fresh, "published_at": (now - timedelta(seconds=600)).isoformat()}
    ahead = {**fresh, "published_at": (now + timedelta(seconds=600)).isoformat()}
    typed = {**fresh, "roles": [{**fresh["roles"][0], "has_home_chat": "yes"},
                                *fresh["roles"][1:]]}
    cases = {
        "none published in the last 120 s": None,
        "its last list is 600 s old": pi_lane_view.encode(old),
        "its list is dated in the future": pi_lane_view.encode(ahead),
        "published in a format this server doesn't read": pi_lane_view.encode(
            {**fresh, "schema": 2}),
        "too big": "x" * (pi_lane_view.MAX_BYTES + 1),
        "unreadable": "{not json",
        "not in the expected format": pi_lane_view.encode(typed),
        "Redis did not answer: ConnectionError": "down",
    }
    with monkeypatch.context() as m:
        as_the_server(m)
        for why, value in cases.items():
            fake = lv.serve(m, lv.FakeRedis(down=value == "down"))
            if value not in (None, "down"):
                fake.data[KEY] = value
            status = api.client.get("/api/team/status")
            assert status.status_code == 200, (why, status.text)
            got = status.json()
            assert got["roles_configured"] is False, why
            assert got["roles_problem"].startswith(pi_lane_view.NOT_RUNNING), got
            assert why.split(" 600 s")[0] in got["roles_problem"], (why, got)  # 600 or 601
            assert api.client.get("/api/team/roles").json() == {
                "configured": False, "problem": got["roles_problem"], "roles": []}
            check = api.client.post("/api/team/check", json=tapi.body(api))
            assert check.status_code == 200 and check.json()["ok"] is False, (why, check.text)
            assert roles_problem(got["roles_problem"]) in [
                p["text"] for p in check.json()["problems"]], check.json()
            start = api.client.post("/api/team/trials", json=tapi.body(api, f"bad-{len(why)}"))
            assert start.status_code == 400, (why, start.text)
    assert tapi.trial_rows(api) == [] and prompts() == NO_TURNS
