"""An approval answers the wait it was meant for, once.

Architecture's Pi proofs (A6-05) found two approvals sent at the same moment both
got a 200, and a retried approval answered the *next* round of a looped gate. Each
wait is now one event -- run, step path, round, event id -- and an approval lands only
while its wait is still open (compare-and-set). These run against Postgres in the
database tier, where the row lock is the real thing.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from temper_ai.api.app_state import AppState
from temper_ai.api.routes import init_app_state
from temper_ai.config import ConfigStore
from temper_ai.memory import InMemoryStore, MemoryService
from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import get_event, record, update_event
from temper_ai.stage.gate import GateSignal, signal_key
from temper_ai.stage.loader import GraphLoader

RUN = "run-approvals-1"


@pytest.fixture(autouse=True)
def _parallel_database(request, tmp_path):
    """A database that parallel requests can share.

    Postgres in the database tier. Otherwise a SQLite file: the default in-memory one is a
    single connection, which threads cannot use at the same moment at all.
    """
    from temper_ai.database import init_database, reset_database
    from tests.conftest import TEST_DATABASE_URL

    if request.node.stash.get(TEST_DATABASE_URL, "").startswith("sqlite"):
        reset_database()
        init_database(f"sqlite:///{tmp_path / 'gates.db'}")


@pytest.fixture
def state():
    store = ConfigStore()
    st = AppState(
        config_store=store,
        graph_loader=GraphLoader(store),
        llm_providers={"mock": MagicMock()},
        memory_service=MemoryService(InMemoryStore()),
    )
    init_app_state(st)
    st.running[RUN] = threading.Event()  # the run is running: approvals reach it now
    return st


@pytest.fixture
def client(state):
    from temper_ai.server import app
    return TestClient(app)


def _wait(name: str = "review", path: str | None = None, round_: int = 1, execution_id: str = RUN) -> str:
    """A wait as the executor records it."""
    return record(
        EventType.STAGE_STARTED,
        data={"name": name, "type": "agent", "gate": True, "gate_status": "waiting",
              "gate_path": path or name, "gate_round": round_},
        execution_id=execution_id,
        status="waiting",
    )


def _used(event_id: str) -> None:
    """The run went on with this approval (what the executor writes after the wait)."""
    update_event(event_id, status="approved", data={"gate_status": "approved", "gate_used_at": "2026-10-03T20:00:00"})


def _approve(client, node: str = "review", **body):
    return client.post(f"/api/runs/{RUN}/approve/{node}", json=body)


class TestOneWinner:
    def test_two_approvals_at_once_one_wins_and_the_other_is_told_who(self, state):
        """Real parallel requests, all aimed at one wait: exactly one gets through."""
        from temper_ai.server import app

        event_id = _wait()
        signal = GateSignal(event_id, "review", "review", 1)
        state.gates[signal_key(RUN, event_id)] = signal
        clients = [TestClient(app) for _ in range(6)]
        start = threading.Barrier(len(clients))

        def go(i: int):
            start.wait()
            return clients[i].post(f"/api/runs/{RUN}/approve/review",
                                   json={"event_id": event_id, "request_id": f"tab-{i}", "by": f"tab {i}",
                                         "response": f"answer {i}"})

        with ThreadPoolExecutor(len(clients)) as pool:
            replies = list(pool.map(go, range(len(clients))))

        codes = sorted(r.status_code for r in replies)
        assert codes == [200] + [409] * (len(clients) - 1)
        won = next(r for r in replies if r.status_code == 200).json()
        stored = get_event(event_id)
        assert stored["status"] == "approved"
        assert stored["data"]["gate_decided_by"] == won["answered_by"]
        assert stored["data"]["gate_response"]["response"] == won["response"]["response"]
        assert signal.is_set() and signal.response["response"] == won["response"]["response"]
        for r in replies:
            if r.status_code == 409:
                detail = r.json()["detail"]
                assert detail["reason"] == "already_answered"
                assert detail["answered_by"] == won["answered_by"]
                assert won["answered_by"] in detail["message"] and detail["answered_at"] in detail["message"]

    def test_a_name_only_approval_racing_one_by_event_id_still_decides_once(self, client):
        event_id = _wait()
        start = threading.Barrier(2)

        def by_name():
            start.wait()
            return _approve(client, by="script")

        def by_event():
            start.wait()
            return _approve(client, event_id=event_id, by="dashboard")

        with ThreadPoolExecutor(2) as pool:
            a, b = pool.submit(by_name), pool.submit(by_event)
            codes = sorted([a.result().status_code, b.result().status_code])

        # The loser either found it answered (409) or, by name, found nothing open (404).
        assert codes[0] == 200 and codes[1] in (404, 409)
        assert get_event(event_id)["status"] == "approved"


class TestRequestId:
    def test_the_same_request_twice_decides_once_and_returns_the_first_result(self, client):
        event_id = _wait()

        first = _approve(client, event_id=event_id, request_id="click-1", response="ship it", by="Ann")
        again = _approve(client, event_id=event_id, request_id="click-1", response="something else", by="Ann")

        assert first.status_code == 200 and again.status_code == 200
        assert first.json()["repeated"] is False and again.json()["repeated"] is True
        assert again.json()["event_id"] == event_id
        assert again.json()["response"]["response"] == "ship it", "the first result, not a second decision"
        assert get_event(event_id)["data"]["gate_response"]["response"] == "ship it"

    def test_a_repeated_request_never_touches_the_next_round(self, client):
        """A6-05's second half: a retried approval answered the loop's next round."""
        round_1 = _wait()
        assert _approve(client, request_id="retry-me").status_code == 200
        _used(round_1)
        round_2 = _wait(round_=2)

        again = _approve(client, request_id="retry-me")

        assert again.status_code == 200 and again.json()["repeated"] is True
        assert again.json()["event_id"] == round_1
        assert get_event(round_2)["status"] == "waiting", "round 2 is still waiting for its own answer"

    def test_the_same_request_racing_itself_decides_once(self, state):
        from temper_ai.server import app

        event_id = _wait()
        clients = [TestClient(app) for _ in range(4)]
        start = threading.Barrier(len(clients))

        def go(c):
            start.wait()
            return c.post(f"/api/runs/{RUN}/approve/review", json={"event_id": event_id, "request_id": "dup"})

        with ThreadPoolExecutor(len(clients)) as pool:
            replies = list(pool.map(go, clients))

        assert [r.status_code for r in replies] == [200] * len(clients)
        assert sorted(r.json()["repeated"] for r in replies) == [False] + [True] * (len(clients) - 1)


class TestStaleApprovals:
    def test_a_stale_tab_approving_round_1_while_round_2_waits_is_refused(self, client):
        round_1 = _wait()
        assert _approve(client, event_id=round_1, by="Ann (dashboard)").status_code == 200
        _used(round_1)
        round_2 = _wait(round_=2)

        stale = _approve(client, event_id=round_1, by="Bob (old tab)")

        assert stale.status_code == 409
        detail = stale.json()["detail"]
        assert detail["reason"] == "already_answered"
        assert "Ann (dashboard)" in detail["message"]
        assert get_event(round_2)["status"] == "waiting"

    def test_a_replaced_wait_says_so(self, client):
        old = _wait()
        new = _wait()
        update_event(old, status="replaced", data={"gate_status": "replaced", "gate_replaced_by": new})

        r = _approve(client, event_id=old)

        assert r.status_code == 409
        assert r.json()["detail"]["reason"] == "replaced"
        assert "replaced" in r.json()["detail"]["message"]
        assert get_event(new)["status"] == "waiting"

    def test_a_turned_down_wait_says_so(self, client):
        ev = _wait()
        update_event(ev, status="rejected", data={"gate_status": "rejected", "gate_decided_by": "Ann"})

        r = _approve(client, event_id=ev)

        assert r.status_code == 409 and r.json()["detail"]["reason"] == "already_rejected"

    def test_an_event_id_from_another_step_is_not_this_ones(self, client):
        ev = _wait("deploy")

        r = _approve(client, "review", event_id=ev)

        assert r.status_code == 404
        assert get_event(ev)["status"] == "waiting"


class TestByNameAlone:
    def test_one_wait_of_that_name_is_approved_as_before(self, client):
        """What EPD's approve_pr.py sends: the step's name, answers, no event id."""
        ev = _wait("deploy")

        r = client.post(f"/api/runs/{RUN}/approve/deploy", json={
            "response": "Merge it.",
            "answers": [{"id": "pr", "question": "Merge?", "selected": ["Merge"], "custom": ""}],
        })

        assert r.status_code == 200 and r.json()["status"] == "approved"
        assert get_event(ev)["data"]["gate_response"]["answers"][0]["selected"] == ["Merge"]

    def test_the_ci_smoke_shape_still_works(self, client):
        """scripts/temper_ci/smoke.py: read the gates, approve the first by its node_name."""
        ev = _wait("approve")
        node = client.get(f"/api/runs/{RUN}/gates").json()["gates"][0]["node_name"]

        r = client.post(f"/api/runs/{RUN}/approve/{node}", json={"response": "the machine check says yes"})

        assert r.status_code == 200
        assert get_event(ev)["status"] == "approved"

    def test_same_named_steps_in_two_stages_are_listed_not_guessed(self, client):
        a = _wait("review", "build.review")
        b = _wait("review", "ship.review")

        r = _approve(client, "review")

        assert r.status_code == 409
        detail = r.json()["detail"]
        assert detail["reason"] == "several_waiting"
        assert sorted(w["path"] for w in detail["waiting"]) == ["build.review", "ship.review"]
        assert a in detail["message"] and b in detail["message"]
        assert get_event(a)["status"] == get_event(b)["status"] == "waiting"

    def test_a_path_names_one_of_them(self, client):
        a = _wait("review", "build.review")
        b = _wait("review", "ship.review")

        assert _approve(client, "ship.review").status_code == 200
        assert get_event(b)["status"] == "approved" and get_event(a)["status"] == "waiting"

    def test_nothing_waiting_is_still_a_404(self, client):
        r = _approve(client, "nobody")

        assert r.status_code == 404 and "No gate waiting" in r.json()["detail"]

    def test_the_gates_listing_names_each_wait(self, client):
        a = _wait("review", "build.review")
        b = _wait("review", "ship.review", round_=2)

        gates = client.get(f"/api/runs/{RUN}/gates").json()["gates"]

        assert [(g["event_id"], g["path"], g["round"]) for g in gates] == [
            (a, "build.review", 1), (b, "ship.review", 2)]


class TestRunNotRunning:
    def test_the_answer_is_kept_and_the_reply_says_it_needs_resume(self, client, state):
        state.running.pop(RUN)
        ev = _wait()

        r = _approve(client, event_id=ev, response="go")

        assert r.status_code == 200
        out = r.json()
        assert out["needs_resume"] is True and "needs Resume" in out["message"]
        stored = get_event(ev)
        assert stored["status"] == "approved" and stored["data"]["gate_kept_for_resume"] is True

    def test_a_running_run_needs_no_resume(self, client):
        out = _approve(client, event_id=_wait()).json()

        assert out["needs_resume"] is False and "message" not in out


class TestCancelLeavesAnApprovalAlone:
    def test_cancel_does_not_overwrite_an_approval_that_got_there_first(self, client):
        ev = _wait()
        assert _approve(client, event_id=ev, by="Ann").status_code == 200

        client.post(f"/api/runs/{RUN}/cancel", json={"reason": "too late"})

        assert get_event(ev)["status"] == "approved"


class TestMcp:
    def test_a_refusal_comes_back_as_a_plain_error(self, state):
        from temper_ai.mcp.tools import TemperTools

        ev = _wait()
        tools = TemperTools()
        assert tools.approve_gate(RUN, "review", event_id=ev, request_id="m-1")["status"] == "approved"

        again = tools.approve_gate(RUN, "review", event_id=ev, request_id="m-2")

        assert again["status"] == 409 and "Already answered" in again["error"]
