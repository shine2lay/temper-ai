"""One turn, run directly against the stand-in worker: what happens before the prompt, the
credential allowance, and the redaction of handed-over secrets."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from temper_ai.pi_agent.turn import TurnRequest, run_turn
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox


class Recorder:
    def __init__(self):
        self.events: list[dict] = []
        self.chunks: list[dict] = []

    def record(self, event_type, data=None, parent_id=None, execution_id=None, status=None,
               event_id=None):
        self.events.append({"type": str(event_type), "data": data, "status": status,
                            "id": event_id})
        return event_id or f"ev{len(self.events)}"

    def broadcast_stream_chunk(self, agent_id, content, chunk_type="content", done=False,
                               call_id=None):
        self.chunks.append({"content": content, "type": chunk_type})


class Ledger:
    """The turn's own writes, each fenced by the turn's epoch: ``taken`` = a newer attempt
    took the turn over, so every write of this one is refused."""

    def __init__(self, taken: bool = False):
        self.effects: list[str] = []
        self.boxes: list[str | None] = []
        self.taken = taken

    def record_box(self, turn_id, epoch, name):
        assert epoch == 1, "every write of the turn names its epoch"
        self.boxes.append(name)
        return not self.taken

    def mark_effect(self, turn_id, state, *, epoch=None):
        assert epoch == 1, "every write of the turn names its epoch"
        self.effects.append(state)
        return not self.taken


def _req(tmp_path: Path, rec: Recorder, **over) -> TurnRequest:
    pdir = tmp_path / "p"
    role = pdir / "memory" / "identities" / sup.ROLE
    role.mkdir(parents=True, exist_ok=True)
    (role / "notebook.md").write_text(f"The check word is {sup.CHECK_WORD}.\n")
    (pdir / "workspace").mkdir(parents=True, exist_ok=True)
    (pdir / "workspace" / "note.txt").write_text(f"{sup.NOTE_WORD} is the first word.")
    values = dict(run_id="run-1", agent_name="talk", node_path="talk",
                  participant={"participant_id": "p1"},
                  turn={"turn_id": "t1", "turn_no": 1, "epoch": 1},
                  text="Read note.txt with the read tool.", spec=sup.spec(pdir),
                  agent_event_id="agent-1", recorder=rec, first_start=True)
    values.update(over)
    return TurnRequest(**values)


def test_a_turn_runs_only_after_its_checks_and_opens_the_allowance_last(tmp_path):
    cfg = sup.box_config(tmp_path / "box")
    rec, led = Recorder(), Ledger()
    report = run_turn(cfg, _req(tmp_path, rec), led, box_factory=FakeBox)
    assert report.state == "completed", report.error
    assert sup.NOTE_WORD in report.output and sup.CHECK_WORD in report.output
    start = FakeBox.STARTS[0]
    assert start["commands"][:2] == ["get_state", "get_commands"]
    assert start["allowance_at_prompt"] == cfg.model_calls_per_turn
    assert led.effects == ["intent"]
    assert report.checks["role"]["tools_exact"] and report.checks["session_after"]["settled"]
    assert report.effective["model"] == "gpt-6.1-sol"
    ends = [e for e in rec.events if e["type"].endswith("agent.completed")]
    assert len(ends) == 1 and ends[0]["data"]["pi_effective"] == report.effective
    assert all("seq" not in c for c in rec.chunks)


def test_an_unsettled_session_without_an_owner_decision_starts_no_worker(tmp_path):
    cfg = sup.box_config(tmp_path / "box")
    rec = Recorder()
    req = _req(tmp_path, rec, first_start=False)
    sessions = Path(req.spec.participant_dir) / "sessions"
    sessions.mkdir(parents=True)
    (sessions / f"x_{req.spec.session_id}.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"type": "session", "id": req.spec.session_id, "cwd": "/w/workspace"},
        {"type": "custom", "customType": "identity", "id": "a", "parentId": None,
         "data": {"id": sup.ROLE}},
        {"type": "message", "id": "b", "parentId": "a",
         "message": {"role": "user", "content": []}}]) + "\n")
    report = run_turn(cfg, req, Ledger(), box_factory=FakeBox)
    assert report.state == "failed" and "session_not_settled" in report.error
    assert FakeBox.STARTS == [] and report.model_call_ids == []
    # With the owner's decision, the worker goes back to the settled entry first.
    report = run_turn(cfg, _req(tmp_path, rec, first_start=False, rewind_allowed=True), Ledger(),
                      box_factory=FakeBox)
    assert report.state == "completed", report.error
    assert FakeBox.STARTS[0]["rewinds"] == ["a"]
    assert report.checks["rewound"] == {"from_leaf": "b", "to": "a"}


def test_a_folder_with_another_session_is_refused(tmp_path):
    cfg = sup.box_config(tmp_path / "box")
    req = _req(tmp_path, Recorder())
    sessions = Path(req.spec.participant_dir) / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "x_someone-else.jsonl").write_text("{}\n")
    report = run_turn(cfg, req, Ledger(), box_factory=FakeBox)
    assert report.state == "failed" and "session_folder_not_private" in report.error
    assert FakeBox.STARTS == []


def test_a_secret_handed_over_mid_turn_never_reaches_the_record(tmp_path):
    cfg = sup.box_config(tmp_path / "box")
    rec = Recorder()
    secret = "sk-handed-over-0123456789"

    def leak(box):
        box.redactor.add(secret)  # what the handoff does before Pi has the token
        note = Path(box.spec.participant_dir) / "workspace" / "note.txt"
        note.write_text(f"{secret} is the first word.")
    FakeBox.on_prompt = leak
    report = run_turn(cfg, _req(tmp_path, rec), Ledger(), box_factory=FakeBox)
    assert report.state == "completed", report.error
    dumped = json.dumps([rec.events, rec.chunks, report.output], default=str)
    assert secret not in dumped
    # Nor spread over live chunks: the words as the page joins them hold no part of it.
    joined = "".join(c["content"] for c in rec.chunks)
    assert secret not in joined and secret[:12] not in joined and secret[-12:] not in joined
    assert "[redacted]" in dumped


def test_the_turn_never_raises(tmp_path):
    cfg = sup.box_config(tmp_path / "box")

    class Broken(FakeBox):
        def start(self, sink, *, fence):
            raise RuntimeError("boom")
    report = run_turn(cfg, _req(tmp_path, Recorder()), Ledger(), box_factory=Broken)
    assert report.state == "failed" and report.error == "turn runner error: RuntimeError"
    assert report.worker.get("container_removed") is True
    _ = SimpleNamespace


def test_only_the_pinned_runtimes_own_extensions_may_add_commands(tmp_path):
    import pytest

    from temper_ai.pi_agent.turn import TurnFailure, _check_commands, bundled_extensions

    runtime = tmp_path / "runtime"
    (runtime / "pi" / "dist" / "extensions" / "llama").mkdir(parents=True)
    (runtime / "pi" / "dist" / "extensions" / "index.js").write_text("")
    bundled = bundled_extensions(runtime)
    assert bundled == {"llama"}
    ours = [{"name": "identity", "source": "extension", "sourceInfo": {"path": "/ext/identity/core.ts"}},
            {"name": "temper-box-state", "source": "extension",
             "sourceInfo": {"path": "/ext/temper-box/index.ts"}}]
    builtin = {"name": "llama", "source": "extension",
               "sourceInfo": {"source": "inline", "path": "<inline:llama.cpp>"}}
    got = _check_commands(ours + [builtin], None, bundled)
    assert got["pinned_runtime_builtin"] == ["llama"] and got["stray"] == 0
    # an inline command whose name the pinned runtime does not ship is still refused
    other = {**builtin, "name": "sneaky"}
    with pytest.raises(TurnFailure) as err:
        _check_commands(ours + [other], None, bundled)
    assert err.value.code == "extensions_not_allowed"
    with pytest.raises(TurnFailure):
        _check_commands(ours + [builtin], None, frozenset())


# --- messages handed into a running turn: one steer at a time (#116) ---------------------


class _SteerRpc:
    """Pi's RPC as the running turn's live side uses it: ``send`` alone, each steer logged.
    ``gone``: the worker is gone, every send fails."""

    def __init__(self, gone: bool = False):
        self.steers: list[str] = []
        self.gone = gone

    def send(self, command, **fields):
        from temper_ai.pi_agent.rpc import RpcError

        if self.gone:
            raise RpcError("command_pipe_closed")
        assert command == "steer"
        self.steers.append(fields["message"])
        return f"s{len(self.steers)}"


def _handed(seq: int) -> str:
    from temper_ai.pi_agent.turn import TEAM_MESSAGE_PREFIX

    return f"{TEAM_MESSAGE_PREFIX}message {seq}"


def _running(*polls: list[dict], gone: bool = False):
    """A running turn's live side whose inbox gives ``polls`` in turn (then nothing), at a
    clock that never moves (it polls only after a tool call ends). Its rpc, and its polls."""
    from temper_ai.pi_agent.turn import _MidTurn

    left, polled = list(polls), []

    def inbox():
        polled.append(len(polled) + 1)
        return left.pop(0) if left else []
    mid = _MidTurn(inbox, None, clock=lambda: 0.0)
    mid.rpc = _SteerRpc(gone)
    mid.observe({"type": "agent_start"})
    return mid, polled


def _answer(mid, rid: str, ok: bool) -> None:
    assert mid.observe({"type": "response", "command": "steer", "id": rid, "success": ok,
                        **({} if ok else {"error": "refused"})})


def _tool_ended(mid, call_id: str) -> None:
    mid.observe({"type": "tool_execution_end", "toolCallId": call_id, "toolName": "read"})


def test_handed_messages_are_steered_one_at_a_time_and_none_after_a_refusal():
    mid, polled = _running([{"seq": s, "text": _handed(s)} for s in (5, 8, 9)],
                           [{"seq": 12, "text": _handed(12)}])
    mid.tick()
    assert mid.rpc.steers == [_handed(5)]  # one steer, waiting for Pi's answer
    _tool_ended(mid, "c1")
    mid.tick()
    assert mid.rpc.steers == [_handed(5)] and polled == [1]  # no next steer, no poll
    _answer(mid, "s1", True)
    mid.tick()
    assert mid.rpc.steers == [_handed(5), _handed(8)]
    _answer(mid, "s2", False)  # Pi refuses 8: nothing more in this turn
    _tool_ended(mid, "c2")
    mid.tick()
    assert mid.rpc.steers == [_handed(5), _handed(8)] and polled == [1]

    report = mid.handed_in([_handed(5)])
    assert (report["confirmed"], report["unconfirmed"], report["refused"]) == ([5], [8, 9], [8])
    assert report["problems"] == ["a handed message was never steered: not sent"]


def test_nothing_is_polled_while_the_last_steer_awaits_its_answer():
    """S2 of #116's land check: nothing is queued, but the last steer still awaits Pi's
    answer. Neither a tool's end nor the poll interval polls the inbox then (what comes in
    meanwhile stays pending in the ledger); the answer lets the deferred poll happen."""
    from temper_ai.pi_agent.turn import INBOX_POLL_S

    mid, polled = _running([{"seq": 5, "text": _handed(5)}], [{"seq": 8, "text": _handed(8)}])
    now = [0.0]
    mid.clock = lambda: now[0]
    mid.tick()
    assert polled == [1] and mid.rpc.steers == [_handed(5)]  # 5's steer awaits its answer
    _tool_ended(mid, "c1")
    now[0] += INBOX_POLL_S
    mid.tick()
    assert polled == [1] and mid.rpc.steers == [_handed(5)]
    _answer(mid, "s1", True)
    mid.tick()
    assert polled == [1, 2] and mid.rpc.steers == [_handed(5), _handed(8)]


def test_all_steers_accepted_the_inbox_is_polled_again():
    mid, polled = _running([{"seq": 5, "text": _handed(5)}], [{"seq": 8, "text": _handed(8)}])
    mid.tick()
    _answer(mid, "s1", True)
    _tool_ended(mid, "c1")
    mid.tick()
    assert polled == [1, 2] and mid.rpc.steers == [_handed(5), _handed(8)]
    _answer(mid, "s2", True)
    assert mid.handed_in([_handed(5), _handed(8)]) == {
        "confirmed": [5, 8], "unconfirmed": [], "unexpected": 0}


def test_a_message_that_cannot_be_sent_stops_the_steering_as_a_refusal_does():
    mid, _ = _running([{"text": _handed(4)}, {"seq": 5, "text": "no prefix"},
                       {"seq": 8, "text": _handed(8)}])
    mid.tick()  # the seq-less one is noted and skipped; 5 is never sent, nor 8 after it
    assert mid.rpc.steers == []
    report = mid.handed_in(None)
    assert (report["confirmed"], report["unconfirmed"]) == ([], [5, 8])
    assert report["problems"] == ["a handed message had no seq: not sent",
                                  "a handed message lacked the team-message prefix: not sent",
                                  "a handed message was never steered: not sent"]


def test_a_gone_worker_leaves_the_rest_unsent():
    import pytest

    from temper_ai.pi_agent.rpc import RpcError

    mid, _ = _running([{"seq": 5, "text": _handed(5)}, {"seq": 8, "text": _handed(8)}],
                      gone=True)
    with pytest.raises(RpcError):
        mid.tick()
    assert mid.handed_in(None)["unconfirmed"] == [5, 8]
