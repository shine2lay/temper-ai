"""temper-ci's live look tries the owner's own controls on the live temper.

The live temper is stood in for (tests/test_ci/live_fake.py): nothing here starts a run,
a container or a server. What is tested is what each check asks for, what it calls a
pass, that every run it starts is quiet, and that it never leaves a run going: a run left
waiting would hold every later deploy, and this deploy's revert too.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from tests.test_ci.live_fake import FakeLiveTemper

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from temper_ci import deploy, live_checks  # noqa: E402

API = "http://127.0.0.1:8420"
KEY = {"Authorization": "Bearer not-a-real-key"}
NAMES = [live_checks.BOX_ENV, live_checks.STOP_THEN_RESUME, live_checks.GATE_THROUGH_API]
TEAM_RUN = "someone else's run is going: c8626bf7 (team-trial-5e1b72713191, running)"


@pytest.fixture(autouse=True)
def _current_modules(monkeypatch):
    """Use the temper_ci modules imported now, not the ones from when this file was read.

    The fixtures in test_deploy.py and test_gate.py import temper_ci afresh, and the tests run
    in a random order. The fake patches the live_checks it imports itself, so a stale one here
    would run with nothing patched, and ask the real Docker.
    """
    from temper_ci import deploy as now_deploy  # noqa: PLC0415
    from temper_ci import live_checks as now_live_checks  # noqa: PLC0415

    monkeypatch.setitem(globals(), "deploy", now_deploy)
    monkeypatch.setitem(globals(), "live_checks", now_live_checks)


def _run_all(fake: FakeLiveTemper, headers: dict | None = None) -> list[dict]:
    return live_checks.run_all(API, KEY if headers is None else headers, "temper-ci",
                               sleep=fake.sleep, clock=fake.clock)


def _by_name(results: list[dict]) -> dict[str, dict]:
    return {r["name"]: r for r in results}


def test_each_control_passes_on_a_temper_that_works(monkeypatch):
    fake = FakeLiveTemper().install(monkeypatch)

    results = _run_all(fake)

    assert [r["name"] for r in results] == NAMES
    assert all(r["ok"] for r in results), results
    got = _by_name(results)
    assert "stopped mid-step (cancelled), 1 checkpoint(s), resumed and completed" in got[
        live_checks.STOP_THEN_RESUME]["detail"]
    assert "the gate on 'decide' answered by temper-ci, and the run completed" in got[
        live_checks.GATE_THROUGH_API]["detail"]
    assert "completed in its own box (an ordinary run's)" in got[live_checks.BOX_ENV]["detail"]
    assert "Pi member boxes are not covered" in got[live_checks.BOX_ENV]["detail"]
    assert fake.going() == [], "no run is left going"
    assert all("cancelled its own" not in r["detail"] for r in results), "nothing needed tidying"


def test_every_run_it_starts_is_quiet(monkeypatch):
    """The live temper sends notices of API-started runs to the owner; none of these may."""
    fake = FakeLiveTemper().install(monkeypatch)

    _run_all(fake)
    live_checks.run_one(live_checks.FREE_RUN, live_checks.free_run,
                        live_checks.Live(API, dict(KEY), sleep=fake.sleep, clock=fake.clock))

    started = fake.started()
    assert [w for w, _ in started] == ["ci_box_env", "ci_slow", "gate_smoke", "smoke_test"]
    assert all(notify == live_checks.QUIET for _, notify in started), started


def test_quiet_turns_off_every_kind_of_notice_temper_knows():
    """If temper learns a new kind of notice, this says so before it reaches the owner."""
    from temper_ai.integrations.notify.config import KINDS, parse_block

    assert set(live_checks.QUIET) == set(KINDS)
    assert set(live_checks.QUIET.values()) == {"off"}
    parse_block(live_checks.QUIET, "notify")  # the server's own reading of it says yes


def test_its_list_of_runs_not_over_is_the_deploys():
    """The runs it tidies are exactly the ones that would hold a deploy."""
    assert live_checks.NOT_OVER == deploy.LIVE_STATUSES


def test_every_call_carries_temper_cis_key(monkeypatch):
    fake = FakeLiveTemper().install(monkeypatch)

    _run_all(fake)

    assert fake.calls
    assert all(headers.get("Authorization") == KEY["Authorization"] for _, _, _, headers in fake.calls)


def test_stop_then_resume_waits_for_the_long_step_and_stops_it_once(monkeypatch):
    fake = FakeLiveTemper().install(monkeypatch)

    _run_all(fake)

    slow = next(r for r in fake.runs.values() if r.workflow == "ci_slow")
    assert slow.inputs == {"seconds": "40"}
    cancels = [(m, p, b) for m, p, b, _ in fake.calls if p == f"/api/runs/{slow.run_id}/cancel"]
    assert len(cancels) == 1 and "on purpose" in cancels[0][2]["reason"]
    assert any(p == f"/api/runs/{slow.run_id}/resume" for _, p, _, _ in fake.calls)
    assert slow.status == "completed"


def test_a_run_stopped_with_nothing_to_resume_from_fails(monkeypatch):
    fake = FakeLiveTemper(no_checkpoint=True).install(monkeypatch)

    got = _by_name(_run_all(fake))[live_checks.STOP_THEN_RESUME]

    assert got["ok"] is False
    assert "left no checkpoint to resume from" in got["detail"]
    assert fake.going() == []


def test_a_gate_answered_under_another_name_fails(monkeypatch):
    """The decision has to say temper-ci answered it: that is what the owner's record shows."""
    fake = FakeLiveTemper(caller_recorded="unknown").install(monkeypatch)

    got = _by_name(_run_all(fake))[live_checks.GATE_THROUGH_API]

    assert got["ok"] is False
    assert "does not name temper-ci; callers: ['unknown']" in got["detail"]


def test_the_gate_is_answered_by_its_event_id_with_temper_cis_name_on_it(monkeypatch):
    fake = FakeLiveTemper().install(monkeypatch)

    _run_all(fake)

    gate = next(r for r in fake.runs.values() if r.workflow == "gate_smoke")
    [(_, path, body, _)] = [c for c in fake.calls if c[1].startswith(f"/api/runs/{gate.run_id}/approve/")]
    assert path.endswith("/approve/decide")
    assert body["event_id"] == f"ev-{gate.run_id}" and "temper-ci" in body["by"]


def test_a_gate_that_never_opens_fails_and_its_run_is_cancelled(monkeypatch):
    fake = FakeLiveTemper(gate_never_opens=True).install(monkeypatch)

    got = _by_name(_run_all(fake))[live_checks.GATE_THROUGH_API]

    gate = next(r for r in fake.runs.values() if r.workflow == "gate_smoke")
    assert got["ok"] is False
    assert f"no gate opened on {gate.run_id[:8]} within 180 s" in got["detail"]
    assert f"cancelled its own {gate.run_id[:8]}" in got["detail"]
    assert gate.status == "cancelled" and fake.going() == []


def test_a_run_that_will_not_end_fails_its_check_and_says_so(monkeypatch):
    """Even a check that went well fails when a run of its own is still going: it would hold
    the next deploy."""
    fake = FakeLiveTemper(gate_never_opens=True, stuck=("gate_smoke",)).install(monkeypatch)

    got = _by_name(_run_all(fake))[live_checks.GATE_THROUGH_API]

    assert got["ok"] is False
    assert "LEFT GOING" in got["detail"] and "still cancelling" in got["detail"]


@pytest.mark.parametrize("workflow", ["ci_box_env", "ci_slow"])
def test_a_run_that_ends_badly_fails_its_check(monkeypatch, workflow):
    fake = FakeLiveTemper(ends_as={workflow: "failed"}).install(monkeypatch)

    results = _by_name(_run_all(fake))

    name = live_checks.BOX_ENV if workflow == "ci_box_env" else live_checks.STOP_THEN_RESUME
    assert results[name]["ok"] is False
    assert "ended as failed" in results[name]["detail"]
    assert [r["ok"] for n, r in results.items() if n != name] == [True, True], "only that one fails"
    assert fake.going() == []


def test_a_box_env_run_whose_step_did_not_complete_fails(monkeypatch):
    """Fail closed (Security): only a completed run whose probe completed is a pass."""
    fake = FakeLiveTemper(steps_end_as={"ci_box_env": "failed"}).install(monkeypatch)

    got = _by_name(_run_all(fake))[live_checks.BOX_ENV]

    assert got["ok"] is False
    assert "completed, but not every step did: {'probe': 'failed'}" in got["detail"]


def test_it_tries_only_the_parts_it_is_asked_to(monkeypatch):
    """What temper-ci tries again, once a part was owed (deploy.settle_owed)."""
    fake = FakeLiveTemper().install(monkeypatch)

    results = live_checks.run_all(API, KEY, "temper-ci", only={live_checks.GATE_THROUGH_API},
                                  sleep=fake.sleep, clock=fake.clock)

    assert [(r["name"], r["ok"]) for r in results] == [(live_checks.GATE_THROUGH_API, True)]
    assert [w for w, _ in fake.started()] == ["gate_smoke"]


def test_a_dropped_read_is_asked_again_not_counted_as_a_failure(monkeypatch):
    fake = FakeLiveTemper(flaky_reads=2).install(monkeypatch)

    results = _run_all(fake)

    assert all(r["ok"] for r in results), results


def test_a_temper_that_does_not_answer_fails_every_check_without_hanging(monkeypatch):
    import urllib.error
    import urllib.request

    def down(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", down)
    fake = FakeLiveTemper()

    results = _run_all(fake)

    assert [r["ok"] for r in results] == [False, False, False]
    assert all("could not read which runs are going: URLError" in r["detail"] for r in results), results
    assert fake.now == 3 * 30, "each part asked for 30 s, started nothing, and gave up"


# -- never beside someone else's run (Security, rm-ddba2969) ------------------------


def test_it_starts_nothing_while_someone_elses_run_is_going(monkeypatch):
    """A box of the look's own beside a Team Project is a STOP for Security's watch of it."""
    fake = FakeLiveTemper(someone_else=(0.0, "team-trial-5e1b72713191")).install(monkeypatch)

    got = _by_name(_run_all(fake))

    assert fake.started() == [], "not one run started"
    for name in NAMES:
        assert (got[name]["ok"], got[name].get("owed")) == (None, True), "not tried: neither passed nor failed"
        assert got[name]["detail"].startswith(f"owed, not started: {TEAM_RUN}; the look never runs "
                                              "beside another run, so temper-ci tries it again")
        # temper-ci's own record of it (Security, reply to rm-e71dc2dc): whose run, and what of
        # its own it cancelled. Ids only.
        assert got[name]["because"] == ["c8626bf7-team-project"]
        assert got[name]["cancelled"] == []


def test_the_box_env_steps_aside_like_the_rest(monkeypatch):
    """Security first had it fail closed (rm-ddba2969), then let it be owed on temper-ci's own
    record (reply to rm-e71dc2dc): failing it would only revert, and the revert waits for the
    runs too."""
    fake = FakeLiveTemper(someone_else=(0.0, "team-trial-5e1b72713191")).install(monkeypatch)

    got = _by_name(_run_all(fake))[live_checks.BOX_ENV]

    assert (got["ok"], got.get("owed")) == (None, True)
    assert fake.started() == []


def test_a_run_of_someone_elses_that_starts_part_way_stops_the_part(monkeypatch):
    fake = FakeLiveTemper(someone_else=(7.0, "team-trial-5e1b72713191"),
                          gate_never_opens=True).install(monkeypatch)

    got = _by_name(_run_all(fake))

    gate = next(r for r in fake.runs.values() if r.workflow == "gate_smoke")
    for name in (live_checks.BOX_ENV, live_checks.STOP_THEN_RESUME):
        assert (got[name]["ok"], "owed" in got[name]) == (True, False), "done before the other run began"
    waiting = got[live_checks.GATE_THROUGH_API]
    assert (waiting["ok"], waiting.get("owed")) == (None, True)
    assert waiting["detail"].startswith("owed, stopped part-way: someone else's run is going")
    assert f"cancelled its own {gate.run_id[:8]}" in waiting["detail"]
    assert (waiting["because"], waiting["cancelled"]) == (["c8626bf7-team-project"], [gate.run_id])
    assert [w for w, _ in fake.started()] == ["ci_box_env", "ci_slow", "gate_smoke"]
    assert gate.status == "cancelled" and fake.going() == []
    assert fake.boxes_asked == [gate.run_id], "its box is gone, and only its own was asked about"
    assert fake.now <= 5 + live_checks.OTHERS_EVERY + 2 * live_checks.POLL_SECONDS, "it stepped aside quickly"


def test_a_part_that_steps_aside_but_leaves_a_run_going_still_fails(monkeypatch):
    fake = FakeLiveTemper(someone_else=(7.0, "team-trial-5e1b72713191"), gate_never_opens=True,
                          stuck=("gate_smoke",)).install(monkeypatch)

    got = _by_name(_run_all(fake))[live_checks.GATE_THROUGH_API]

    assert got["ok"] is False and "owed" not in got
    assert "LEFT GOING" in got["detail"]
    assert "did not leave the temper as it found it, so it fails" in got["detail"]


def test_a_part_that_steps_aside_but_leaves_its_box_up_fails(monkeypatch):
    """Owed only once its runs have ended with no box left (Security, reply to rm-e71dc2dc):
    a box of its own still up beside a Team Project is the very thing stepping aside is for."""
    fake = FakeLiveTemper(someone_else=(7.0, "team-trial-5e1b72713191"), gate_never_opens=True,
                          boxes_linger=("gate_smoke",)).install(monkeypatch)

    got = _by_name(_run_all(fake))[live_checks.GATE_THROUGH_API]

    gate = next(r for r in fake.runs.values() if r.workflow == "gate_smoke")
    assert got["ok"] is False and "owed" not in got
    assert f"BOX LEFT UP: {gate.run_id[:8]}'s box is up" in got["detail"]
    assert got["seconds"] >= live_checks.BOX_GONE_SECONDS, "it gave the box its minute to go"


def test_a_part_that_steps_aside_where_docker_cannot_say_fails(monkeypatch):
    """Not knowing whether the box is gone is not knowing it is gone."""
    fake = FakeLiveTemper(someone_else=(7.0, "team-trial-5e1b72713191"), gate_never_opens=True,
                          boxes_unknown=True).install(monkeypatch)

    got = _by_name(_run_all(fake))[live_checks.GATE_THROUGH_API]

    assert got["ok"] is False and "owed" not in got
    assert "BOX LEFT UP" in got["detail"] and "docker could not say" in got["detail"]


def test_a_part_that_never_started_asks_docker_nothing(monkeypatch):
    fake = FakeLiveTemper(someone_else=(0.0, "team-trial-5e1b72713191"),
                          boxes_unknown=True).install(monkeypatch)

    got = _run_all(fake)

    assert all(r.get("owed") for r in got), "no run of its own, so no box of its own"
    assert fake.boxes_asked == []


def test_a_part_that_passes_asks_docker_nothing(monkeypatch):
    """Its runs ended the ordinary way: their boxes are temper's to take down, as for any run."""
    fake = FakeLiveTemper(boxes_unknown=True).install(monkeypatch)

    assert all(r["ok"] for r in _run_all(fake))
    assert fake.boxes_asked == []


def test_its_own_runs_are_not_someone_elses(monkeypatch):
    """The run-list shows the look's own run too; that one never makes it step aside."""
    fake = FakeLiveTemper().install(monkeypatch)
    live = live_checks.Live(API, dict(KEY), sleep=fake.sleep, clock=fake.clock)
    live.start("gate_smoke")

    assert live.others() == []
    live.step_aside(now=True)


def test_an_owed_part_reads_owed_and_a_failed_one_fail():
    from temper_ci import report

    assert report.mark({"name": "x", "ok": None, "owed": True}) == "owed"
    assert report.mark({"name": "x", "ok": False}) == "FAIL"
    assert report.mark({"name": "x", "ok": None}) == "FAIL", "no result, and not owed, is a failure"
    assert report.mark({"name": "x", "ok": True}) == "ok"


def test_a_check_that_crashes_still_tidies_its_runs(monkeypatch):
    fake = FakeLiveTemper().install(monkeypatch)
    live = live_checks.Live(API, dict(KEY), sleep=fake.sleep, clock=fake.clock)

    def crashes(live):
        live.start("gate_smoke")
        raise RuntimeError("something it did not expect")

    got = live_checks.run_one("a check that crashes", crashes, live)

    assert got["ok"] is False
    assert got["detail"].startswith("RuntimeError: something it did not expect; cancelled its own run-0001")
    assert fake.going() == []


def test_a_box_starts_its_smoke_test_quietly_too():
    """ci_run_token's box starts a run of its own; that one says notify off as well."""
    agent = Path(__file__).resolve().parents[2] / "configs" / "agents" / "ci_run_token.yaml"
    script = yaml.safe_load(agent.read_text(encoding="utf-8"))["agent"]["script_template"]

    assert 'quiet = {"question": "off", "stuck": "off", "failed": "off", "finished": "off"}' in script
    assert '"notify": quiet}' in script
