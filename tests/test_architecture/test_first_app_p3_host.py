"""#125 host wire (first_app_p3_host): H-125-HOSTROWS-1 and -2's fixed cases, with fakes only.

The request side is #126's real ops_host_client (read_sequence, make_request, validate_request, write_request) on a
tmp host_dir; P5's load and judge are fakes (the real ones need QA's whole published binding). The fake controller is
a sleep hook that writes a receipt file. The fixture turns WRITES_ADMITTED on for the wire's own cases; the shipped
value is off. No real host, socket, browser or Docker.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

BIN = Path(__file__).resolve().parents[2] / "configs" / "architecture" / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))


def _load(name):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


hw = _load("first_app_p3_host")
hc = hw.hc
T0 = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
RESTART = "stop exit 0 within 10.000 s; then GET /api/items 200 within 30.000 s"
DECISION_6 = {  # lead DECISION-6 (08a42dc1) D6.1 and D6.2, typed from the decision's table
    "R-1": ("restart: graceful stop with TERM, then start the same app and forwarder", RESTART, 120),
    "R-1i": ("restart: graceful stop with INT, then start the same app and forwarder", RESTART, 120),
    "D-1": ("crash: KILL the app", "exit 137; no health; Ops crash wait 5 s", 60),
    "D-5": ("start the app and forwarder after D-1's recorded crash", "GET /api/items 200 within 30.000 s", 60),
}


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def iso(dt):
    return dt.isoformat(timespec="milliseconds")


def write600(path: Path, data: bytes):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def window(host_dir: Path) -> dict:
    return {"window_id": "w-test", "host_dir": str(host_dir), "origin": "http://100.110.162.4:8970",
            "binding": {"mode": "project", "project_id": "p3", "run_id": "run-1", "build_sums_sha256": "a" * 64,
                        "kit_id": "kit", "kit_sha256": "b" * 64},
            "window_expires_at": iso(T0 + timedelta(hours=1)),
            "row_table": {r: {"operation": hc.ROWS["checker"][r], "writer": "checker"}
                          for r in ("R-1", "R-1i", "D-1", "D-5", "W-IMG")}}


def seq(host_dir: Path, expected=3):
    write600(host_dir / "SEQ-checker.json", json.dumps(
        {"window_id": "w-test", "writer": "checker", "expected_sequence": expected, "last_request_id": None,
         "updated_at": iso(T0 - timedelta(minutes=5))}).encode())


def receipt_for(req_raw: bytes, at: datetime, **extra) -> dict:
    """An Ops-shaped receipt root that echoes the request file in full (fake; P5 is faked too)."""
    req = json.loads(req_raw)
    rec = {k: req[k] for k in hw.ECHO_KEYS}
    rec.update(schema="ops-host-receipt/1", request_sha256=hashlib.sha256(req_raw).hexdigest(), sequence_used=True,
               expected_sequence=req["sequence"] + 1, decision="DONE", at=iso(at), seen_at=iso(at),
               started_at=iso(at), ended_at=iso(at))
    rec.update(extra)
    return rec


def prior_receipt(w: dict, row="R-1", **extra) -> dict:
    """A validated earlier receipt of this window, binding, row, writer and operation (sequence 2, ended before T0)."""
    rec = {"schema": "ops-host-receipt/1", "row": row, "operation": hc.ROWS["checker"][row],
           "host_action": hc.ROW_SIGNAL.get(row), "writer": "checker", "request_id": "old", "sequence": 2,
           "window_id": "w-test", "binding": w["binding"], "sequence_used": True, "decision": "DONE",
           "ended_at": iso(T0 - timedelta(minutes=1))}
    rec.update(extra)
    return rec


@pytest.fixture
def wire(tmp_path, monkeypatch):
    host_dir = tmp_path / "host"
    host_dir.mkdir(mode=0o700)
    seq(host_dir)
    w = window(host_dir)
    calls = SimpleNamespace(load=[], judge=[], verdict=("PASS", "NONE"))

    def load(path, sha, *, data_context, uid):
        calls.load.append((path, sha, data_context, uid))
        return SimpleNamespace(trust="UNTRUSTED", window=MappingProxyType(dict(w)))

    def judge(request_raw, ref, *, window, now):
        calls.judge.append((request_raw, dict(ref), now))
        return SimpleNamespace(trust="UNTRUSTED", verdict=calls.verdict[0], code=calls.verdict[1],
                               identities=(("receipt", ref["sha256"]),))

    monkeypatch.setattr(hw.p5, "load_bound_candidate_window", load)
    monkeypatch.setattr(hw.p5, "judge_candidate_receipt", judge)
    monkeypatch.setattr(hw, "WRITES_ADMITTED", True)
    ctx = tmp_path / "ctx"
    ctx.mkdir(mode=0o700)
    doc = json.dumps({"window_path": "/w/window.json", "window_sha256": "c" * 64, "data_context": {"k": 1}}).encode()
    write600(ctx / "context.json", doc)
    binding = {"context_path": str(ctx / "context.json"), "context_sha256": hashlib.sha256(doc).hexdigest(),
               "uid": os.getuid()}
    return SimpleNamespace(host_dir=host_dir, w=w, calls=calls, binding=binding, ctx=ctx)


def controller(host_dir: Path, clock: Clock, *, after=1, mutate=None, row="R-1"):
    """A sleep hook: advances the clock; on the after-th sleep writes a receipt echoing WAITING-<row>.json."""
    state = {"n": 0}

    async def sleep(_s):
        state["n"] += 1
        clock.now += timedelta(seconds=hw.POLL_S)
        if state["n"] == after:
            rec = receipt_for((host_dir / f"WAITING-{row}.json").read_bytes(), clock.now)
            if mutate:
                mutate(rec)
            write600(host_dir / f"{row}.json", json.dumps(rec).encode())
    return sleep, state


def files(host_dir: Path):
    return sorted(p.name for p in host_dir.iterdir())


def opened(binding, clock):
    s = hw.open_host(binding, clock=clock)
    asyncio.run(hw.settle(s, clock=clock, sleep=controller(Path("/nonexistent"), clock, after=0)[0]))
    return s


def pending(wire, row="D-1", *, at=T0 - timedelta(seconds=10), budget=12) -> bytes:
    """Publish a real earlier request of this writer through #126 (as an interrupted run would have left it)."""
    req = hc.make_request(wire.w, row, 3, writer="checker", action="earlier run", expected="earlier run",
                          expires_at=iso(at + timedelta(seconds=budget)), now=at)
    return hc.write_request(wire.w, req, clock=lambda: at)


def test_shipped_switch_is_off_and_reads_and_writes_nothing(tmp_path, monkeypatch):
    assert hw.WRITES_ADMITTED is False
    loads = []
    monkeypatch.setattr(hw.p5, "load_bound_candidate_window", lambda *a, **k: loads.append(a))
    binding = {"context_path": str(tmp_path / "absent" / "context.json"), "context_sha256": "c" * 64,
               "uid": os.getuid()}
    s = hw.open_host(binding)
    assert s.record == {"status": "BLOCKED", "reasons": [hw.WRITES_OFF]} and loads == []
    host_dir = tmp_path / "host"
    host_dir.mkdir(mode=0o700)  # no SEQ file: a read would show up as another reason
    loaded = hw.HostSession({"status": "LOADED", "reasons": []}, object(), window(host_dir), os.getuid())
    out = asyncio.run(hw.run_row(loaded, "R-1"))
    assert out == {"status": "BLOCKED", "reasons": [hw.WRITES_OFF], "writer": "checker"}
    assert files(host_dir) == []


def test_shipped_tables_equal_decision_6():
    assert set(hw.REQUEST_TEXTS) == set(hw.BUDGET_S) == set(hw.HOST_ROWS) == set(DECISION_6)
    for row, (action, expected, budget) in DECISION_6.items():
        assert dict(hw.REQUEST_TEXTS[row]) == {"action": action, "expected": expected}
        assert type(hw.BUDGET_S[row]) is int and hw.BUDGET_S[row] == budget
    with pytest.raises(TypeError):
        hw.REQUEST_TEXTS["R-1"]["action"] = "changed"  # type: ignore[index]


def test_no_binding_blocks_and_writes_nothing(wire):
    s = hw.open_host(None)
    assert s.record["status"] == "BLOCKED" and "no host_binding" in s.record["reasons"][0]
    out = asyncio.run(hw.run_row(s, "R-1"))
    assert out["status"] == "BLOCKED" and "no request written" in out["reasons"][0]
    assert files(wire.host_dir) == ["SEQ-checker.json"] and wire.calls.load == []


@pytest.mark.parametrize("fault", ["hash", "missing", "keys", "link"])
def test_bad_binding_file_blocks_before_p5(wire, fault):
    b = dict(wire.binding)
    if fault == "hash":
        b["context_sha256"] = "0" * 64
    elif fault == "missing":
        b["context_path"] = str(wire.ctx / "absent.json")
    elif fault == "keys":
        doc = json.dumps({"window_path": "/w", "window_sha256": "c" * 64}).encode()
        write600(wire.ctx / "context.json", doc)
        b["context_sha256"] = hashlib.sha256(doc).hexdigest()
    else:
        os.symlink(wire.ctx / "context.json", wire.ctx / "link.json")
        b["context_path"] = str(wire.ctx / "link.json")
    s = hw.open_host(b)
    assert s.record["status"] == "BLOCKED" and wire.calls.load == []
    assert asyncio.run(hw.run_row(s, "R-1"))["status"] == "BLOCKED"
    assert files(wire.host_dir) == ["SEQ-checker.json"]


def test_p5_refusal_blocks_with_its_code_and_writes_nothing(wire, monkeypatch):
    def refuse(*a, **k):
        raise hw.p5.TargetRefused("TARGET_BINDING_INVALID")
    monkeypatch.setattr(hw.p5, "load_bound_candidate_window", refuse)
    s = hw.open_host(wire.binding)
    assert s.record["status"] == "BLOCKED" and s.record["code"] == "TARGET_BINDING_INVALID"
    assert asyncio.run(hw.run_row(s, "R-1"))["status"] == "BLOCKED"
    assert files(wire.host_dir) == ["SEQ-checker.json"]


@pytest.mark.parametrize("row", sorted(DECISION_6))
def test_each_row_carries_its_decision_6_texts_and_full_budget(wire, row):
    clock = Clock()
    s = opened(wire.binding, clock)
    assert s.loaded and wire.calls.load[0][3] == os.getuid()
    sleep, _ = controller(wire.host_dir, clock, after=2, row=row)
    out = asyncio.run(hw.run_row(s, row, clock=clock, sleep=sleep))
    assert out["status"] == "UNQUALIFIED"
    req = json.loads((wire.host_dir / f"WAITING-{row}.json").read_bytes())
    action, expected, budget = DECISION_6[row]
    assert (req["action"], req["expected"], req["operation"]) == (action, expected, hc.ROWS["checker"][row])
    assert req["since"] == req["not_before"] == iso(T0) and req["wait_seconds"] == budget
    assert req["expires_at"] == iso(T0 + timedelta(seconds=budget))


@pytest.mark.parametrize("left_ms, written", [(119_999, False), (120_000, True)])
def test_budget_that_does_not_fit_the_window_is_blocked_never_shortened(wire, left_ms, written):
    wire.w["window_expires_at"] = iso(T0 + timedelta(milliseconds=left_ms))
    clock = Clock()
    sleep, _ = controller(wire.host_dir, clock, after=1)
    out = asyncio.run(hw.run_row(opened(wire.binding, clock), "R-1", clock=clock, sleep=sleep))
    if written:
        assert out["status"] == "UNQUALIFIED" and out["request"]["expires_at"] == wire.w["window_expires_at"]
    else:
        assert out["status"] == "BLOCKED" and "window time left < request budget" in out["reasons"][0]
        assert files(wire.host_dir) == ["SEQ-checker.json"] and wire.calls.judge == []


@pytest.mark.parametrize("verdict", [("PASS", "NONE"), ("FAIL", "NONE"), ("BLOCKED", "TARGET_EVIDENCE_INVALID")])
def test_receipt_is_judged_by_p5_and_never_counted(wire, verdict):
    wire.calls.verdict = verdict
    clock = Clock()
    s = opened(wire.binding, clock)
    sleep, _ = controller(wire.host_dir, clock, after=2)
    out = asyncio.run(hw.run_row(s, "R-1", clock=clock, sleep=sleep))
    code = "" if verdict[1] == "NONE" else f" ({verdict[1]})"
    assert out["status"] == "UNQUALIFIED" and out["reasons"] == [f"P5 assessment: {verdict[0]}{code}, not counted"]
    assert files(wire.host_dir) == ["R-1.json", "SEQ-checker.json", "WAITING-R-1.json"]
    raw_req = (wire.host_dir / "WAITING-R-1.json").read_bytes()
    req = json.loads(raw_req)
    assert req["sequence"] == 3 and req["writer"] == "checker"
    assert req["receipt_file"] == str(wire.host_dir / "R-1.json")
    (judged_raw, ref, _now), = wire.calls.judge
    rec = (wire.host_dir / "R-1.json").read_bytes()
    assert judged_raw == raw_req and ref == {"path": str(wire.host_dir / "R-1.json"),
                                             "sha256": hashlib.sha256(rec).hexdigest(), "byte_length": len(rec)}
    assert out["request"]["sha256"] == hashlib.sha256(raw_req).hexdigest()
    assert oct((wire.host_dir / "WAITING-R-1.json").stat().st_mode & 0o777) == "0o600"


@pytest.mark.parametrize("extra", [{}, {"sequence": 3, "sequence_used": False, "decision": "REFUSED"}])
def test_validated_prior_receipt_is_ignored_then_the_new_one_judged(wire, extra):
    clock = Clock()
    write600(wire.host_dir / "R-1.json", json.dumps(prior_receipt(wire.w, **extra)).encode())
    s = opened(wire.binding, clock)
    sleep, state = controller(wire.host_dir, clock, after=5)
    out = asyncio.run(hw.run_row(s, "R-1", clock=clock, sleep=sleep))
    assert out["status"] == "UNQUALIFIED" and state["n"] == 5 and len(wire.calls.judge) == 1
    assert json.loads((wire.host_dir / "R-1.json").read_bytes())["request_id"] == out["request"]["request_id"]


@pytest.mark.parametrize("bad", [{"window_id": "other"}, {"ended_at": iso(T0 + timedelta(minutes=1))},
                                 {"sequence": 3}, {"sequence": 3, "decision": "REFUSED"},
                                 {"sequence": 4, "sequence_used": False, "decision": "REFUSED"},
                                 {"schema": "ops-host-receipt/3"}, {"operation": "crash"}, {"sequence": "2"},
                                 # DECISION-7 D7.3: one field each
                                 {"binding": {"mode": "calibration"}}, {"row": "R-1i"}, {"writer": "api-check"},
                                 {"sequence": 2.5}, b"not json", b"[]"])
def test_prior_receipt_that_is_not_a_validated_earlier_one_blocks_before_writing(wire, bad):
    body = bad if isinstance(bad, bytes) else json.dumps(prior_receipt(wire.w, **bad)).encode()
    write600(wire.host_dir / "R-1.json", body)
    clock = Clock()
    sleep, state = controller(wire.host_dir, clock, after=10 ** 9)  # a wrong client reaches its deadline, never spins
    out = asyncio.run(hw.run_row(opened(wire.binding, clock), "R-1", clock=clock, sleep=sleep))
    assert out["status"] == "BLOCKED" and "never ignored silently" in out["reasons"][0] and state["n"] == 0
    assert "WAITING-R-1.json" not in files(wire.host_dir) and wire.calls.judge == []


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(request_id="someone-else"), lambda r: r.update(sequence=9), lambda r: r.update(sequence="3"),
    lambda r: r.update(sequence=3.0),  # equal in value, not in type
    lambda r: r.update(window_id="other"), lambda r: r.update(host_action="KILL"),
    lambda r: r.update(binding={"mode": "project"}), lambda r: r.update(request_sha256="0" * 64),
    lambda r: r.pop("request_sha256"), lambda r: r.pop("operation")])
def test_receipt_that_does_not_echo_the_request_in_full_blocks_and_is_not_judged(wire, mutate):
    clock = Clock()
    sleep, _ = controller(wire.host_dir, clock, after=1, mutate=mutate)
    out = asyncio.run(hw.run_row(opened(wire.binding, clock), "R-1", clock=clock, sleep=sleep))
    assert out["status"] == "BLOCKED" and "does not echo" in out["reasons"][0] and wire.calls.judge == []


def test_no_receipt_by_the_deadline_is_blocked_never_fail(wire):
    clock = Clock()
    sleep, state = controller(wire.host_dir, clock, after=10 ** 9)
    out = asyncio.run(hw.run_row(opened(wire.binding, clock), "R-1", clock=clock, sleep=sleep))
    assert out["status"] == "BLOCKED" and "not an app FAIL" in out["reasons"][0]
    assert state["n"] == int(120 / hw.POLL_S) and wire.calls.judge == []


@pytest.mark.parametrize("fault", ["link", "oversize", "mode", "duplicate_key", "nan"])
def test_unsafe_or_malformed_receipt_blocks_without_following_it(wire, fault):
    clock = Clock()
    target = wire.ctx / "elsewhere.json"

    async def sleep(_s):
        clock.now += timedelta(seconds=hw.POLL_S)
        body = json.dumps(receipt_for((wire.host_dir / "WAITING-R-1.json").read_bytes(), clock.now)).encode()
        if fault == "link":
            write600(target, body)
            os.symlink(target, wire.host_dir / "R-1.json")
        elif fault == "oversize":
            write600(wire.host_dir / "R-1.json", body + b" " * (hw.p5.RECEIPT_MAX + 1))
        elif fault == "mode":
            write600(wire.host_dir / "R-1.json", body)
            os.chmod(wire.host_dir / "R-1.json", 0o644)
        elif fault == "duplicate_key":
            write600(wire.host_dir / "R-1.json", body[:-1] + b', "sequence": 3}')
        else:
            write600(wire.host_dir / "R-1.json", body[:-1] + b', "seconds": NaN}')
    out = asyncio.run(hw.run_row(opened(wire.binding, clock), "R-1", clock=clock, sleep=sleep))
    assert out["status"] == "BLOCKED" and wire.calls.judge == []


def test_settle_records_a_fully_matching_receipt_and_judges_nothing(wire):
    raw = pending(wire)
    body = json.dumps(receipt_for(raw, T0 - timedelta(seconds=5))).encode()
    write600(wire.host_dir / "D-1.json", body)
    clock = Clock()
    s = hw.open_host(wire.binding, clock=clock)
    asyncio.run(hw.settle(s, clock=clock))
    assert s.loaded and [x["row"] for x in s.record["settled"]] == ["D-1"]
    entry = s.record["settled"][0]
    assert entry["counted"] is False and "assessment" not in entry and wire.calls.judge == []  # D7.4
    assert entry["request_id"] == json.loads(raw)["request_id"]
    assert entry["receipt"]["sha256"] == hashlib.sha256(body).hexdigest()


def test_settle_waits_to_the_original_expiry_and_blocks_when_unresolved(wire):
    raw = pending(wire)  # expires at T0 + 2 s
    clock = Clock()
    s = hw.open_host(wire.binding, clock=clock)
    n = {"sleeps": 0}

    async def sleep(_s):
        n["sleeps"] += 1
        clock.now += timedelta(seconds=hw.POLL_S)
    asyncio.run(hw.settle(s, clock=clock, sleep=sleep))
    assert s.record["status"] == "BLOCKED" and "sequence state is unknown" in s.record["reasons"][-1]
    assert n["sleeps"] == 8 and wire.calls.judge == []
    assert asyncio.run(hw.run_row(s, "R-1", clock=clock))["status"] == "BLOCKED"
    assert files(wire.host_dir) == ["SEQ-checker.json", "WAITING-D-1.json"]

    write600(wire.host_dir / "D-1.json", json.dumps(receipt_for(raw, T0 + timedelta(seconds=1))).encode())
    s2 = hw.open_host(wire.binding, clock=clock)
    asyncio.run(hw.settle(s2, clock=clock, sleep=sleep))
    assert s2.loaded and len(s2.record["settled"]) == 1 and wire.calls.judge == []


def test_settle_ignores_a_validated_earlier_receipt_then_settles_on_its_own(wire):
    pending(wire)
    write600(wire.host_dir / "D-1.json", json.dumps(prior_receipt(wire.w, "D-1",
                                                                  ended_at=iso(T0 - timedelta(minutes=2)))).encode())
    clock = Clock()
    s = hw.open_host(wire.binding, clock=clock)
    sleep, state = controller(wire.host_dir, clock, after=3, row="D-1")
    asyncio.run(hw.settle(s, clock=clock, sleep=sleep))
    assert s.loaded and state["n"] == 3 and len(s.record["settled"]) == 1 and wire.calls.judge == []


def blocked_and_writes_nothing(wire, s, clock):
    """D7.4: a session refused at settle stays BLOCKED, and run_row on it writes nothing."""
    before = {p.name: p.read_bytes() for p in wire.host_dir.iterdir()}
    out = asyncio.run(hw.run_row(s, "R-1", clock=clock, sleep=controller(wire.host_dir, clock, after=10 ** 9)[0]))
    assert out["status"] == "BLOCKED" and "request" not in out
    assert {p.name: p.read_bytes() for p in wire.host_dir.iterdir()} == before and wire.calls.judge == []


@pytest.mark.parametrize("bad", [{"window_id": "other"}, {"sequence": 4}, {"ended_at": iso(T0)}])
def test_settle_blocks_on_an_unvalidated_receipt_with_another_id_beside_the_pending_request(wire, bad):
    pending(wire)
    write600(wire.host_dir / "D-1.json", json.dumps(prior_receipt(wire.w, "D-1", **bad)).encode())
    clock = Clock()
    s = hw.open_host(wire.binding, clock=clock)
    sleep, state = controller(wire.host_dir, clock, after=10 ** 9, row="D-1")
    asyncio.run(hw.settle(s, clock=clock, sleep=sleep))
    assert s.record["status"] == "BLOCKED" and "neither its receipt" in s.record["reasons"][-1]
    assert state["n"] == 0 and wire.calls.judge == []
    blocked_and_writes_nothing(wire, s, clock)


# D7.4 check 2: its request id, one other field (the last case: not the exact request file; #126 _initialize took
# such a receipt as an older one to skip). "arrives": the same receipt shows up during the wait.
@pytest.mark.parametrize("field, value, arrives", [
    ("sequence", 4, False), ("binding", {"mode": "calibration"}, False), ("sequence", 4, True),
    ("request_sha256", "0" * 64, False)])
def test_settle_blocks_on_a_receipt_with_its_id_that_does_not_match_it(wire, field, value, arrives):
    raw = pending(wire)
    clock = Clock()
    if arrives:
        sleep, state = controller(wire.host_dir, clock, after=2, mutate=lambda r: r.update({field: value}), row="D-1")
    else:
        rec = receipt_for(raw, T0 - timedelta(seconds=5), **{field: value})
        write600(wire.host_dir / "D-1.json", json.dumps(rec).encode())
        sleep, state = controller(wire.host_dir, clock, after=10 ** 9, row="D-1")
    s = hw.open_host(wire.binding, clock=clock)
    asyncio.run(hw.settle(s, clock=clock, sleep=sleep))
    assert s.record["status"] == "BLOCKED" and s.record["settled"] == []
    assert "D-1.json does not match its pending request" in s.record["reasons"][-1]
    assert state["n"] == (2 if arrives else 0) and wire.calls.judge == []
    blocked_and_writes_nothing(wire, s, clock)


@pytest.mark.parametrize("fault", ["not_json", "missing_keys", "other_row", "other_window", "other_writer"])
def test_malformed_or_foreign_pending_request_blocks(wire, fault):
    raw = pending(wire, "R-1i")
    req = json.loads(raw)
    os.unlink(wire.host_dir / "WAITING-R-1i.json")
    if fault == "not_json":
        data = b"not json"
    elif fault == "missing_keys":
        data = json.dumps({"request_id": req["request_id"], "expires_at": req["expires_at"]}).encode()
    elif fault == "other_row":
        data = raw  # a valid R-1i request filed under R-1's name
    elif fault == "other_writer":
        data = json.dumps(dict(req, writer="api-check")).encode()
    else:
        data = json.dumps(dict(req, window_id="other")).encode()
    write600(wire.host_dir / ("WAITING-R-1.json" if fault == "other_row" else "WAITING-R-1i.json"), data)
    clock = Clock()
    s = hw.open_host(wire.binding, clock=clock)
    sleep, state = controller(wire.host_dir, clock, after=10 ** 9, row="R-1i")
    asyncio.run(hw.settle(s, clock=clock, sleep=sleep))
    assert s.record["status"] == "BLOCKED" and "run-start settle" in s.record["reasons"][-1]
    assert "is not this writer's valid request" in s.record["reasons"][-1]  # D7.4 check 1
    assert state["n"] == 0 and wire.calls.judge == []  # refused as it stands, not after a wait
    blocked_and_writes_nothing(wire, s, clock)


def test_driver_host_step_maps_the_wire_and_runs_r1i_browser_half(monkeypatch):
    p3 = _load("first_app_p3")
    kit, g = p3.kit, p3.guard
    seen = []

    async def call(s, code):
        seen.append(code)
        return {}

    async def browser(s, r, row, origin, engine, served, allowed, latch, acts=None):
        seen.append(("browser", tuple(a["do"] for a in acts)))
        return {"status": "PASS", "reasons": [], "traffic": []}

    def wire_result(status):
        async def run_row(session, rid):
            return {"status": status, "reasons": [f"wire {status}"], "writer": "checker", "request": {"x": 1}}
        return run_row
    monkeypatch.setattr(p3, "_call", call)
    monkeypatch.setattr(p3, "browser_step", browser)
    r, latch = p3.new_receipt("H", None), g.StopLatch()
    r["origin"] = "http://100.110.162.4:8962"
    for status in ("UNQUALIFIED", "BLOCKED"):
        seen.clear()
        monkeypatch.setattr(p3.host_wire, "run_row", wire_result(status))
        step = asyncio.run(p3.host_step(object(), r, kit.ROW["R-1i"], r["origin"], {"host_session": object()},
                                        latch, "chromium"))
        assert step["status"] == status and step["host"] == {"writer": "checker", "request": {"x": 1}}
        assert step["status"] != "PASS"
        browser_calls = [x for x in seen if isinstance(x, tuple)]
        assert browser_calls == ([("browser", ("reload",))] if status == "UNQUALIFIED" else [])
