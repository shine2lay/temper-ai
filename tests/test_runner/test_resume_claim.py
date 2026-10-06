"""One start at a time for a Pi run cut off while it ran (SW-80, L3 F2; runner/resume_claim.py).

Three resumes sent at the same moment all passed Resume's "is it going already?" check and
started three attempts. The claim is one database write that exactly one asker wins. These
tests run on SQLite and on the Postgres tier (tests/pgtier.py), where the askers hold
connections of their own and only the database can decide between them.
"""

from __future__ import annotations

import threading
from datetime import timedelta

from temper_ai.database import get_session
from temper_ai.observability.event_types import EventType
from temper_ai.observability.models import Event
from temper_ai.observability.recorder import record, update_event
from temper_ai.runner import resume_claim
from temper_ai.runner.models import ResumeClaim
from temper_ai.runner.parked import CLAIM_STARTS_WITHIN, parked_attempt
from temper_ai.shared.clock import utcnow


def _attempt(execution_id: str, status: str, *, minutes_ago: float, parked: bool = False) -> str:
    """One attempt of the run (a ``workflow.started`` event), started that long ago; parked:
    waiting on the owner with its worker let go (status ``waiting``)."""
    data: dict = {"name": "pi_talk"}
    if parked:
        data["parked"] = {"waits": ["recovery-1"]}
    event_id = record(EventType.WORKFLOW_STARTED, data=data,
                      execution_id=execution_id, status=status)
    with get_session() as session:
        row = session.get(Event, event_id)
        assert row is not None
        row.timestamp = utcnow() - timedelta(minutes=minutes_ago)
        session.add(row)
    return event_id


def _age_the_claim(execution_id: str, by: timedelta) -> None:
    with get_session() as session:
        row = session.get(ResumeClaim, execution_id)
        assert row is not None
        row.claimed_at = utcnow() - by
        session.add(row)


def _all_at_once(execution_id: str, askers: int) -> list[str | None]:
    """``askers`` threads claim the run at the same moment; what each got."""
    start = threading.Barrier(askers)
    got: list[str | None] = [None] * askers

    def ask(i: int) -> None:
        start.wait(timeout=10)
        got[i] = resume_claim.claim(execution_id, by=f"asker-{i}")

    threads = [threading.Thread(target=ask, args=(i,)) for i in range(askers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads)
    return got


def test_the_first_asker_wins_and_the_next_is_told_no():
    _attempt("cut-1", "interrupted", minutes_ago=5)

    first = resume_claim.claim("cut-1", by="resume")
    second = resume_claim.claim("cut-1", by="pickup")

    assert first is not None
    assert second is None


def test_of_many_askers_at_the_same_moment_exactly_one_wins():
    _attempt("cut-2", "interrupted", minutes_ago=5)

    got = _all_at_once("cut-2", askers=8)

    assert sum(token is not None for token in got) == 1


def test_a_claim_lasts_while_the_attempt_it_started_runs_and_ends_with_it():
    """The claimed start writes its attempt down; nobody else starts one while it runs. Once
    it has ended, a later Resume may carry the run on again."""
    _attempt("cut-3", "interrupted", minutes_ago=5)
    assert resume_claim.claim("cut-3", by="resume") is not None
    _age_the_claim("cut-3", CLAIM_STARTS_WITHIN * 2)  # its start was long ago
    started = _attempt("cut-3", "running", minutes_ago=1)

    assert resume_claim.claim("cut-3", by="pickup") is None, "its attempt is still going"

    update_event(started, status="failed")
    assert resume_claim.claim("cut-3", by="resume") is not None, "that attempt is over"


def test_a_claim_whose_start_never_wrote_its_attempt_down_ends_by_itself():
    """A start lost on the way (the server died between the claim and the attempt): the
    claim holds for CLAIM_STARTS_WITHIN, then Resume may try again."""
    _attempt("cut-4", "interrupted", minutes_ago=5)
    assert resume_claim.claim("cut-4", by="resume") is not None

    _age_the_claim("cut-4", CLAIM_STARTS_WITHIN - timedelta(seconds=30))
    assert resume_claim.claim("cut-4", by="resume") is None
    _age_the_claim("cut-4", CLAIM_STARTS_WITHIN + timedelta(seconds=1))
    assert resume_claim.claim("cut-4", by="resume") is not None


def test_a_claim_given_back_can_be_taken_again():
    _attempt("cut-5", "interrupted", minutes_ago=5)
    token = resume_claim.claim("cut-5", by="resume")
    assert token is not None

    resume_claim.release("cut-5", token)

    assert resume_claim.claim("cut-5", by="resume") is not None


def test_giving_back_touches_only_the_claim_one_holds():
    """A start that gave up late must not give back the claim someone took over since."""
    _attempt("cut-6", "interrupted", minutes_ago=5)
    late = resume_claim.claim("cut-6", by="slow")
    assert late is not None
    _age_the_claim("cut-6", CLAIM_STARTS_WITHIN * 2)
    assert resume_claim.claim("cut-6", by="resume") is not None

    resume_claim.release("cut-6", late)

    assert resume_claim.claim("cut-6", by="pickup") is None, "the newer claim still holds"


def test_of_many_askers_taking_over_an_ended_claim_exactly_one_wins():
    """The take-over is one conditional update on the token that was read: only one asker's
    update still finds it."""
    _attempt("cut-7", "interrupted", minutes_ago=5)
    assert resume_claim.claim("cut-7", by="resume") is not None
    _age_the_claim("cut-7", CLAIM_STARTS_WITHIN * 2)
    _attempt("cut-7", "failed", minutes_ago=1)  # what that start ran has ended

    got = _all_at_once("cut-7", askers=8)

    assert sum(token is not None for token in got) == 1


def test_each_run_has_a_claim_of_its_own():
    _attempt("cut-8a", "interrupted", minutes_ago=5)
    _attempt("cut-8b", "interrupted", minutes_ago=5)

    assert resume_claim.claim("cut-8a", by="resume") is not None
    assert resume_claim.claim("cut-8b", by="resume") is not None


# The SW-80 flake (queue #63): an asker that saw the cut-off attempt reached its claim only
# after another asker's attempt had started and parked at its first question.


def test_a_claim_lasts_while_its_attempt_waits_parked_on_the_owner():
    """The attempt the claimed start began has parked at its first question, its worker let
    go: it is not over. Only its own parked claim carries it on (runner/parked.py); nobody
    takes this claim over to start another attempt beside it."""
    _attempt("cut-9", "interrupted", minutes_ago=5)
    assert resume_claim.claim("cut-9", by="resume") is not None
    parked = _attempt("cut-9", "waiting", minutes_ago=1, parked=True)

    assert resume_claim.claim("cut-9", by="late") is None, "it waits on the owner"
    assert resume_claim.claim("cut-9", by="late", seen=parked) is None

    update_event(parked, status="cancelled")
    assert resume_claim.claim("cut-9", by="resume", seen=parked) is not None, "that one is over"


def test_an_asker_whose_run_moved_on_since_it_looked_starts_nothing():
    """An asker saw the cut-off attempt; by the time it claims, somebody else's attempt has
    started (and here even ended): that attempt was theirs, so this asker is told no, with or
    without a claim row left to find. An asker who saw the newer attempt may claim."""
    seen = _attempt("cut-10", "interrupted", minutes_ago=5)
    assert resume_claim.claim("cut-10", by="resume") is not None
    newer = _attempt("cut-10", "failed", minutes_ago=1)

    assert resume_claim.claim("cut-10", by="late", seen=seen) is None
    assert resume_claim.claim("cut-10", by="resume", seen=newer) is not None

    seen = _attempt("cut-11", "interrupted", minutes_ago=5)
    _attempt("cut-11", "running", minutes_ago=1)  # started through a parked claim: no row here
    assert resume_claim.claim("cut-11", by="late", seen=seen) is None


def test_what_an_asker_sees_decides_what_it_may_carry_on():
    """``look`` reads the newest attempt as the asker asks. A parked attempt is carried on only
    by an asker that saw it parked; temper's pick-up only while the attempt its stop cut off is
    still the newest."""
    cut = _attempt("cut-12", "interrupted", minutes_ago=5)
    assert resume_claim.look("cut-12") == resume_claim.Look(attempt=cut, parked=False, cut_off=True)
    with resume_claim.only_while_cut_off():
        picking_up = resume_claim.look("cut-12")
    assert picking_up.cut_off_only and not picking_up.leaves_alone(None)
    assert not resume_claim.look("cut-12").cut_off_only, "only inside"

    parked = _attempt("cut-12", "waiting", minutes_ago=1, parked=True)
    waiting = parked_attempt("cut-12")
    assert waiting is not None and waiting["id"] == parked
    seen = resume_claim.look("cut-12")
    assert seen == resume_claim.Look(attempt=parked, parked=True, cut_off=False)
    assert not seen.leaves_alone(waiting), "it saw this attempt parked"
    assert picking_up.leaves_alone(waiting), "started since the pick-up chose the run"
    assert resume_claim.Look(attempt=cut, parked=False, cut_off=True).leaves_alone(waiting)
    assert resume_claim.Look(attempt=parked, parked=False, cut_off=False).leaves_alone(waiting), (
        "seen while it ran, before it parked")
    with resume_claim.only_while_cut_off():
        assert resume_claim.look("cut-12").leaves_alone(None), "carried on since the stop"
