"""A stop's records say what was said and who said it (queue #111).

1. The run's stopped reason is the stop's own words, however the stop reached the run: a
   live worker that notices the cancel (run 92f0123a's way), a box that let go at a wait, a
   parked run. "Workflow cancelled by user" only when the stop gave no words.
2. A stopped team's phase words name who stopped it, as its outcome records it: the owner,
   a role's key, an unknown caller, or plain "Stopped" when nobody is recorded.
"""

from __future__ import annotations

import pytest

from temper_ai.runner.parked import CANCEL_MESSAGE
from tests.test_pi_agent import support as sup
from tests.test_runner.pi_parking import support as pw
from tests.test_runner.pi_parking import test_external as te
from tests.test_runner.pi_parking import test_team_api as ta
from tests.test_runner.pi_parking.test_external import _box, _reaper, _row
from tests.test_runner.pi_parking.test_team_api import (
    CI_KEY,
    OWNER_KEY,
    answer,
    body,
    key,
    parked,
    start_trial,
    team_run,
)
from tests.test_runner.pi_parking.test_team_runs import script

# The fixtures: a trial on the Team API (team switched on), and a run in external mode.
tr, team_on, api, ext = ta.tr, ta.team_on, ta.api, te.ext

WORDS = "account 5 is being removed, so the project ends now"


def stopped_reason(attempt: dict) -> tuple[str | None, str | None]:
    data = attempt.get("data") or {}
    return data.get("error"), (data.get("stopped") or {}).get("reason")


def outcome_with_words(api, eid: str) -> dict:
    def words():
        out = team_run(api, eid)["outcome"]
        return out if out and out.get("owner_words") else None
    return sup.wait_for(words, what="the stop's words on the team's outcome")


def test_a_live_team_run_stopped_by_a_role_keeps_its_words_and_names_the_role(api, monkeypatch):
    """Happy path, run 92f0123a's way: the run's worker is still going (its wait is held, not
    parked) when a role's key stops it with words. The run ends with those words as its
    stopped reason, the team's ended record keeps them, and the phase names the role."""
    from temper_ai.checkpoint.service import CheckpointService

    def cannot_save(self, *args, **kwargs):
        raise RuntimeError("the checkpoint store is full")

    monkeypatch.setattr(CheckpointService, "save_wait_parked", cannot_save)
    script(api.led, ["keep_going", "done"])
    eid = start_trial(api, body(api))["execution_id"]

    def asked():
        view = team_run(api, eid)["open_waits"]
        return view[0] if view and view[0]["asked"] else None
    sup.wait_for(asked, what=f"an asked wait in {eid}")
    assert [a["status"] for a in pw.attempts(eid)] == ["running"]  # held, not parked

    r = api.client.post(f"/api/runs/{eid}/cancel", json={"reason": WORDS}, headers=key(CI_KEY))
    assert r.status_code == 200 and r.json()["status"] == "cancelling", r.text
    attempt = pw.wait_ended(eid, 1, timeout=30)[-1]
    assert attempt["status"] == "cancelled"
    assert stopped_reason(attempt) == (WORDS, WORDS)

    out = outcome_with_words(api, eid)
    assert (out["decision"], out["owner_words"], out["by"]) == ("cancelled", WORDS, "temper-ci")
    phase = team_run(api, eid)["phase"]
    assert (phase["name"], phase["words"]) == ("stopped", "Stopped by temper-ci")


def test_a_parked_team_run_stopped_by_the_owner_keeps_his_words_and_names_him(api):
    script(api.led, ["keep_going", "done"])
    eid = start_trial(api, body(api))["execution_id"]
    parked(api, eid, 1)
    r = api.client.post(f"/api/runs/{eid}/cancel", json={"reason": WORDS},
                        headers={**key(OWNER_KEY), "Origin": "http://testserver"})
    assert r.status_code == 200, r.text
    attempt = pw.wait_ended(eid, 1)[-1]
    assert attempt["status"] == "cancelled" and stopped_reason(attempt) == (WORDS, WORDS)
    assert outcome_with_words(api, eid)["by"] == "owner"
    assert team_run(api, eid)["phase"]["words"] == "Stopped by the owner"


def test_a_stop_answer_from_a_role_names_the_role_not_the_owner(api):
    script(api.led, ["keep_going", "done"])
    eid = start_trial(api, body(api))["execution_id"]
    wait = parked(api, eid, 1)
    r = answer(api, eid, wait["wait_id"], "stop", "we have what we need", rid="s-1", auth=CI_KEY)
    assert r.status_code == 200, r.text
    assert pw.wait_ended(eid, 2)[-1]["status"] == "cancelled"
    run = team_run(api, eid)
    assert run["outcome"]["by"] == "temper-ci"
    assert run["phase"]["words"] == "Stopped by temper-ci"


def test_a_box_that_let_go_ends_with_the_stops_recorded_words(ext, monkeypatch):
    """A cancel while the run's box lets go at a wait: the row's flag carries no words, so
    the reaper that ends the run reads them from the stop's own record."""
    eid = sup.start(ext.client, "pw_before_pi", ext.ws)
    _box(ext, eid, monkeypatch)
    r = ext.client.post(f"/api/runs/{eid}/cancel", json={"reason": WORDS})
    assert r.status_code == 200 and r.json()["status"] == "cancelling", r.text
    _reaper().tick()
    assert _row(eid)["status"] == "cancelled"
    (attempt,) = pw.attempts(eid)
    assert attempt["status"] == "cancelled" and stopped_reason(attempt) == (WORDS, WORDS)
    assert attempt["data"]["cancelled_reason"] == WORDS


def test_without_words_the_reason_stays_workflow_cancelled_by_user(ext, monkeypatch):
    eid = sup.start(ext.client, "pw_before_pi", ext.ws)
    _box(ext, eid, monkeypatch)
    assert ext.client.post(f"/api/runs/{eid}/cancel", json={}).status_code == 200
    _reaper().tick()
    (attempt,) = pw.attempts(eid)
    assert stopped_reason(attempt) == (CANCEL_MESSAGE, CANCEL_MESSAGE)


def test_a_box_workers_flag_reads_the_words_from_the_stops_record(ext):
    """A box's worker learns of a cancel by a signal (no words): its flag reads them from the
    record the cancel wrote, once set, and the first words given stay."""
    import threading

    from temper_ai.api.caller import Caller, record_action, recorded_cancel_words
    from temper_ai.stage.exceptions import CancelFlag, stop_words

    eid = sup.start(ext.client, "pw_before_pi", ext.ws)
    flag = CancelFlag(words_from=lambda: recorded_cancel_words(eid))
    record_action(eid, "cancel", Caller(name="temper"), reason=WORDS)
    assert stop_words(flag) is None  # not set: no stop yet
    flag.set()
    assert stop_words(flag) == WORDS

    given = CancelFlag(words_from=lambda: "from the record")
    given.cancel("  said at the stop  ")
    given.cancel("a second stop")
    assert stop_words(given) == "said at the stop"
    assert stop_words(threading.Event()) is None


@pytest.mark.parametrize(("decided_by", "owners", "words"), [
    ("owner-dashboard", ["owner-dashboard"], "Stopped by the owner"),
    ("slack:U123", ["owner-dashboard", "slack:U123"], "Stopped by the owner"),
    ("temper", ["owner-dashboard"], "Stopped by temper"),
    ("unknown", ["owner-dashboard"], "Stopped by an unknown caller"),
    (None, ["owner-dashboard"], "Stopped"),
])
def test_the_phase_words_name_the_recorded_stopper_and_never_guess(decided_by, owners, words):
    from temper_ai.pi_agent.flow_view import stopped_words
    from temper_ai.pi_agent.team_view import outcome_view

    out = outcome_view({"decision": "cancelled", "reason": "the run was cancelled",
                        "decided_by": decided_by}, owners)
    assert stopped_words(out["by"]) == words
