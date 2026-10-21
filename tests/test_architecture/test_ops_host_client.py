"""Ops host client on fixed, model-free fixtures; never runs a host action.

Fixtures follow the QA-HOME accepted tuple (base v3 a9244fd5 + CORRECTION-1 +
QA host-publication-v2). Parameter ids are the report's fixture names. A fake
controller (file writes only) answers requests in the client round-trip tests.
"""

import asyncio
import copy
import hashlib
import importlib.util
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[2] / "configs" / "architecture" / "bin"
SPEC = importlib.util.spec_from_file_location("ops_host_client", BIN / "ops_host_client.py")
host = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = host
SPEC.loader.exec_module(host)

BASE = datetime(2026, 10, 20, 18, 0, tzinfo=UTC)
WID = "window-p3-1"
APP, FWD, ENGINE = "a" * 64, "b" * 64, "9" * 64
CTRL, EXEC = "c" * 64, "d" * 64
PORT = 8970
ORIGIN = f"http://100.110.162.4:{PORT}"
HOST_HEADER = f"100.110.162.4:{PORT}"
ZERO = "0001-01-01T00:00:00Z"
PIN = host.ENGINE_PIN
PROJECT = {"mode": "project", "project_id": "project-3", "run_id": "run-1", "build_sums_sha256": "1" * 64,
           "kit_id": "qa-project3-v2", "kit_sha256": "2" * 64}
CALIBRATION = {"mode": "calibration", "manifest_sha256": "3" * 64, "entry": "reference",
               "build_sums_sha256": "1" * 64, "calibration_run": "calibration-1"}
RUNTIME = {key: None for key in host.INSPECT_RUNTIME} | {
    "image_id": "sha256:" + "e" * 64, "command": ["python", "app.py"], "data_bind": {"target": "/data"}}
ENTRIES = [{"name": "todo.db", "type": "regular", "size": 8192, "mtime_ns": 1, "target": None,
            "target_truncated": False, "sha256": "f" * 64}]
PRIOR = {"D-5": "D-1", "API-D-5": "API-D-1"}


def ts(ms: int) -> str:
    return (BASE + timedelta(milliseconds=ms)).isoformat(timespec="milliseconds")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_file(path: Path, data, mode=0o600) -> bytes:
    raw = data if isinstance(data, bytes) else (json.dumps(data) + "\n").encode()
    temporary = path.with_name("." + path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    os.write(fd, raw)
    os.close(fd)
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    return raw


BYTES = {"app_copy": 4096, "data": 8192, "tmp": 0, "work": 0, "total": 12288, "complete": True,
         "measured_at": ts(1250)}


class World:
    """One window's host folder: creation inspects, window file, snapshots, receipts."""

    def __init__(self, tmp_path: Path, binding=PROJECT):
        self.dir = tmp_path / "host"
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.dir.mkdir(mode=0o700)
        (self.dir / "evidence").mkdir(mode=0o700)
        self.data_dir = str(self.dir / "data")
        self.count = 0
        creation = {t: self.inspect(t, False, "created", ZERO, ZERO, 0, 10) for t in ("app", "forwarder")}
        self.window_dict = {
            "window_id": WID, "host_dir": str(self.dir), "origin": ORIGIN, "binding": binding, "runtime": {},
            "row_table": {}, "window_started_at": ts(0), "scheduled_use_minutes": 60, "schedule_source": "fixture",
            "schedule_sha256": "6" * 64, "window_ttl_minutes": 90, "window_expires_at": ts(90 * 60_000),
            "bytes_used": BYTES, "app_container_id": APP, "fwd_container_id": FWD, "network_ids": ["7" * 64],
            "creation_inspect": creation, "calibration_selection": None, "data_dir": self.data_dir,
            "data_dev": 2049, "data_inode": 4001, "data_mode": 448, "security_receipt_path": "/fixture",
            "security_receipt_sha256": "8" * 64, "controller_sha256": CTRL, "executor_sha256": EXEC,
            "ops_host_sha256": "9" * 64, "probe_client_sha256": "9" * 64, "forward_py_sha256": "9" * 64,
            "case_list_sha256": "9" * 64, "case_list_path": "/fixture", "app_copy_path": "/fixture",
            "receipts_log_path": "/fixture", "init_check": {}, "port_copy_map": []}
        self.window_path = tmp_path / "window.json"
        self.window_sha = sha(write_file(self.window_path, self.window_dict))
        self.window = host.load_window(self.window_path, self.window_sha)

    def put(self, obj) -> dict:
        self.count += 1
        name = f"snap-{self.count}.json"
        raw = write_file(self.dir / "evidence" / name, obj)
        return {"path": f"{self.dir}/evidence/{name}", "sha256": sha(raw), "byte_length": len(raw)}

    def inspect(self, target, running, status, started, finished, code, observed, runtime=None, cid=None):
        at = lambda v: v if isinstance(v, str) else ts(v)  # noqa: E731
        return self.put({"schema": "ops-host-inspect/1", "window_id": WID,
                         "container_id": cid or (APP if target == "app" else FWD), "runtime": runtime or RUNTIME,
                         "state": {"running": running, "status": status, "started_at": at(started),
                                   "finished_at": at(finished), "exit_code": code, "oom_killed": False,
                                   "restart_count": 0},
                         "observed_at": ts(observed)})

    def listing(self, observed, entries=ENTRIES, truncated=False) -> dict:
        tree = None if truncated else sha(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode())
        return self.put({"schema": "ops-host-listing/1", "window_id": WID, "target": "data", "path": self.data_dir,
                         "observed_at": ts(observed), "entries": entries, "entry_count": len(entries),
                         "truncated": truncated, "complete": not truncated, "error": "limit" if truncated else None,
                         "tree_sha256": tree, "todo_db_sha256": "f" * 64, "todo_db_header_18_19": [1, 1]})

    def request(self, row, seq, writer="checker", now_ms=1000):
        req = host.make_request(self.window, row, seq, writer=writer, expires_at=ts(300_000),
                                action="fixed host step", expected="QA rule (host-publication-v2)",
                                now=BASE + timedelta(milliseconds=now_ms))
        return req, host._encode(req)

    def receipt(self, req, raw, started, ended, exit_code, decision="DONE", kind=None, **fields):
        return {"schema": host.RECEIPT_SCHEMA, "row": req["row"], "operation": req["operation"],
                "host_action": req["operation"], "writer": req["writer"], "request_id": req["request_id"],
                "window_id": WID, "sequence": req["sequence"], "sequence_used": True,
                "expected_sequence": req["sequence"] + 1, "binding": req["binding"], "request_sha256": sha(raw),
                "controller_sha256": CTRL, "executor_sha256": EXEC, "sums_sha256": "5" * 64,
                "done": decision == "DONE", "decision": decision, "failure_kind": kind, "by": "ops-host cccccccc",
                "note": "", "reason": "", "at": ts(ended + 100), "seen_at": ts(ended + 100),
                "started_at": ts(started), "ended_at": ts(ended), "lane": host.LANE[req["operation"]],
                "app_container_id": APP, "fwd_container_id": FWD, "exit_code": exit_code,
                "window_ttl_minutes": 90, "window_expires_at": ts(90 * 60_000), "bytes_used": BYTES, **fields}

    def crash(self, req, raw, exit_code=137, decision="DONE", kind=None, listener_gone=True, origin_refused=True,
              finished=2200):
        term = self.inspect("app", False, "exited", 500, finished, exit_code, 2300)
        return self.receipt(req, raw, 2000, 2500, exit_code, decision, kind, exit_status="exited", signal="KILL",
                            kill_sent_at=ts(2100), exited_at=ts(2200), listener_gone=listener_gone,
                            origin_refused=origin_refused, data_listing_after_exit=self.listing(2250),
                            stop_inspect=term)

    def start_evidence(self, req, prior_exit, after_exit_ref, prior_kind, prior_code, k):
        """Audit from the recorded exit to first 200 / deadline, with QA's probe cadence."""
        s0 = prior_exit + 800
        t0, cmds = s0 + 100, []
        deadline = t0 + 30_000

        def add(kind, op, s, e, params, result, argv=None, code=None):
            cmds.append({"kind": kind, "op": op, "started_at": ts(s), "ended_at": ts(e), "exit_code": code,
                         "argv": argv, "params": params, "result": result})

        def stat(s, inode=4001):
            add("inprocess", "data-stat", s, s + 10, {"path": self.data_dir, "follow_symlinks": False},
                {"outcome": "ok", "dev": 2049, "inode": inode, "mode": 448, "error": None})

        def inspect(target, s, ref):
            cid = APP if target == "app" else FWD
            add("process", "docker-inspect", s, s + 10, {"target": target, "container_id": cid},
                {"outcome": "ok", "snapshot": ref, "error": None}, ["docker", "inspect", cid], 0)

        def listener(s, present):
            add("inprocess", "listener", s, s + 10, {"address": "0.0.0.0", "port": PORT},
                {"outcome": "ok", "present": present, "error": None,
                 "sockets": [{"address": "0.0.0.0", "port": PORT, "protocol": "tcp"}] if present else []})

        before_entries = k.get("before_entries", ENTRIES)
        stat(s0)
        before = self.listing(s0 + 25, before_entries, k.get("truncated", False))
        add("inprocess", "data-list", s0 + 20, s0 + 30, {"path": self.data_dir, "follow_symlinks": False,
                                                          "max_entries": 10_000, "max_depth": 16},
            {"outcome": "ok", "snapshot": before, "error": None})
        app_before = self.inspect("app", False, "exited", 500, prior_exit, prior_code, s0 + 45)
        fwd_before = self.inspect("forwarder", False, "exited", 500, prior_exit, 0, s0 + 65)
        inspect("app", s0 + 40, app_before)
        inspect("forwarder", s0 + 60, fwd_before)
        listener(s0 + 80, False)
        add("process", "docker-start", t0, s0 + 300, {"target": "app", "container_id": APP},
            {"outcome": "ok", "started": True, "error": None}, ["docker", "start", APP], 0)
        add("process", "docker-start", s0 + 310, s0 + 500, {"target": "forwarder", "container_id": FWD},
            {"outcome": "ok", "started": True, "error": None}, ["docker", "start", FWD], 0)
        app_after = self.inspect("app", True, "running", s0 + 200, prior_exit, 0, s0 + 515,
                                 runtime=k.get("after_runtime"), cid=k.get("after_cid"))
        fwd_after = self.inspect("forwarder", True, "running", s0 + 400, prior_exit, 0, s0 + 535)
        inspect("app", s0 + 510, app_after)
        inspect("forwarder", s0 + 530, fwd_after)
        stat(s0 + 550, k.get("inode_after", 4001))
        listener(s0 + 570, True)
        if k.get("extra"):
            add("process", "exec", s0 + 590, s0 + 595, {}, {}, ["sqlite3", "todo.db"], 0)
        probe = {"method": "GET", "url": ORIGIN + "/api/items", "host": HOST_HEADER, "timeout_seconds": 3}
        h = None if k.get("health", 1640) is None else t0 + k.get("health", 1640)
        s, count, last_status, last_start = s0 + 600, 0, None, None
        while s < deadline:
            count, last_start = count + 1, s
            if h is not None and s <= h <= s + 600:
                status = k.get("status", 200)
                add("inprocess", "health", s, h + 1, probe, {"outcome": "response", "status": status,
                                                             "response_at": ts(h), "elapsed_seconds": (h + 1 - s) / 1000,
                                                             "error": None})
                last_status, last_end = status, h + 1
                break
            add("inprocess", "health", s, s + 50, probe, {"outcome": "refused", "status": None, "response_at": None,
                                                          "elapsed_seconds": 0.05, "error": "refused"})
            last_end = s + 50
            s += 1100 if k.get("gap") and count == 3 else 550
        elapsed = (h - t0) / 1000 if h is not None else 30.0
        audit_end = max(last_end, h if h is not None else deadline)
        audit = {"schema": "start-audit/1", "window_id": WID, "writer": req["writer"],
                 "request_id": req["request_id"], "sequence": req["sequence"], "row": req["row"],
                 "operation": req["operation"], "commands_run": cmds}
        leaf = f"audit-{req['request_id']}-{req['sequence']}.json"
        raw = write_file(self.dir / leaf, audit)
        creation = self.window_dict["creation_inspect"]
        identity = {"window_sha256": self.window_sha,
                    "app": {"container_id": APP, "creation_record": creation["app"], "before_inspect": app_before,
                            "after_inspect": app_after, "before_matches_creation": True,
                            "after_matches_creation": True},
                    "forwarder": {"container_id": FWD, "creation_record": creation["forwarder"],
                                  "before_inspect": fwd_before, "after_inspect": fwd_after,
                                  "before_matches_creation": True, "after_matches_creation": True}}
        outcome = "miss" if h is None else ("healthy" if h - t0 <= 30_000 else "late")
        evidence = {
            "start_sent_at": ts(t0), "app_started_at": ts(s0 + 200), "health_at": None if h is None else ts(h),
            "health_code": last_status, "seconds_to_health": None if h is None else elapsed,
            "health_elapsed_seconds": elapsed,
            "health_observation": {"method": "GET", "path": "/api/items", "host": HOST_HEADER, "outcome": outcome,
                                   "probe_count": count, "first_probe_at": ts(s0 + 600),
                                   "last_probe_at": ts(last_start), "observed_until": ts(h or deadline),
                                   "elapsed_seconds": elapsed, "last_http_status": last_status, "complete": True},
            "identity_evidence": identity, "prior_exit_evidence": prior_kind,
            "data_listing_after_exit": after_exit_ref, "data_listing_before_start": before,
            "listings_match": before_entries == ENTRIES,
            "start_audit_ref": {"path": leaf, "sha256": sha(raw), "byte_length": len(raw)},
            "audit_started_at": ts(prior_exit), "audit_ended_at": ts(audit_end), "audit_complete": True,
            "listener_present": True}
        return evidence, s0 - 50, audit_end + 50, outcome == "healthy"

    def start(self, req, raw, prior_raw, **k):
        crash = json.loads(prior_raw)
        prior = {"kind": "receipt", "row": crash["row"], "writer": crash["writer"], "request_id": crash["request_id"],
                 "sequence": crash["sequence"], "sha256": sha(prior_raw), "byte_length": len(prior_raw)}
        evidence, began, ended, healthy = self.start_evidence(req, 2200, crash["data_listing_after_exit"], prior,
                                                              137, k)
        decision = k.get("decision", "DONE" if healthy else "FAILED")
        kind = k.get("kind", None if decision == "DONE" else "app")
        return self.receipt(req, raw, began, ended, None, decision, kind, same_inode=True, **evidence)

    def restart(self, req, raw, **k):
        sig, kill_rel = 2100, k.get("kill_rel")
        exited = sig + kill_rel + 50 if kill_rel else sig + k.get("exit_rel", 400)
        code = k.get("exit_code", 137 if kill_rel else 0)
        stopped, traceback, gone = k.get("stopped", True), k.get("traceback", False), k.get("listener_gone", True)
        after = self.listing(exited + 50)
        stop_e = {"signal": host.ROW_SIGNAL[req["row"]], "signal_sent_at": ts(sig), "exited_at": ts(exited),
                  "seconds_to_exit": (exited - sig) / 1000, "within_10s": exited - sig <= 10_000,
                  "forced_kill": bool(kill_rel), "kill_sent_at": ts(sig + kill_rel) if kill_rel else None,
                  "stopped_line_seen": stopped, "stopped_line_at": ts(sig + 300) if stopped else None,
                  "traceback_seen": traceback,
                  "traceback_line": "Traceback (most recent call last):" if traceback else None,
                  "traceback_first_at": ts(sig + 200) if traceback else None, "data_listing_after_exit": after,
                  "stop_inspect": self.inspect("app", False, "exited", 500, exited, code, exited + 100)}
        stop_fail = code != 0 or exited - sig > 10_000 or kill_rel or not stopped or traceback or not gone
        start_e, began, ended, healthy = self.start_evidence(req, exited, after,
                                                             {"kind": "restart-leg", "leg": "stop-graceful"}, code, k)
        legs = [{"leg": "stop-graceful", "decision": "FAILED" if stop_fail else "DONE",
                 "failure_kind": "app" if stop_fail else None, "started_at": ts(2000), "ended_at": ts(exited + 200),
                 "exit_code": code, "evidence": stop_e},
                {"leg": "start", "decision": "DONE" if healthy else "FAILED", "failure_kind": None if healthy else "app",
                 "started_at": ts(began), "ended_at": ts(ended), "exit_code": None, "evidence": start_e}]
        decision = k.get("decision", "FAILED" if stop_fail or not healthy else "DONE")
        kind = k.get("kind", None if decision == "DONE" else "app")
        return self.receipt(req, raw, 2000, ended + 50, code, decision, kind, legs=legs, listener_gone=gone)

    def engine(self, req, raw, image=PIN, started=500, running=True, decision="DONE", **extra):
        if decision == "REFUSED":
            return self.receipt(req, raw, 2000, 2100, None, "REFUSED", None, reason="0 running matches")
        return self.receipt(req, raw, 2000, 2100, None, decision, None, image_id=image, container_id=ENGINE,
                            container_started_at=ts(started), running=running, **extra)


def build(tmp_path, op, row, writer, knobs):
    w = World(tmp_path)
    if op == "start":
        creq, craw = w.request(PRIOR[row], 1, writer)
        prior_raw = write_file(w.dir / f"{PRIOR[row]}.json", w.crash(creq, craw))
        req, raw = w.request(row, 2, writer)
        return w, req, raw, w.start(req, raw, prior_raw, **knobs)
    req, raw = w.request(row, 1, writer)
    return w, req, raw, getattr(w, op)(req, raw, **knobs)


def judged(w, req, raw, receipt):
    return host.judge_receipt(w.window, req, receipt, raw)


def fail_as_done(r):
    r.update(decision="DONE", failure_kind=None, done=True)


def refused(r):
    r.update(decision="REFUSED", failure_kind=None, done=False)


def failed(kind):
    return lambda r: r.update(decision="FAILED", failure_kind=kind, done=False)


def drop(key):
    return lambda r: r.pop(key)


def setv(key, value):
    return lambda r: r.__setitem__(key, value)


COMMON = [  # (id, mutation, expected) applied to every operation's DONE receipt
    ("FAILED host", failed("host"), "BLOCKED"),
    ("REFUSED", refused, "BLOCKED"),
    ("unknown schema", setv("schema", "ops-host-receipt/2"), "BLOCKED"),
    ("mismatched echo (binding)", lambda r: r.__setitem__("binding", {**r["binding"], "run_id": "run-2"}), "BLOCKED"),
    ("mismatched writer", setv("writer", "qa-runner"), "BLOCKED"),
    ("mismatched sequence", lambda r: r.__setitem__("sequence", r["sequence"] + 1), "BLOCKED"),
    ("mismatched request_id", setv("request_id", str(uuid.uuid4())), "BLOCKED"),
    ("missing exit_code key", drop("exit_code"), "BLOCKED"),
    ("time without offset", lambda r: r.__setitem__("at", r["at"][:-6]), "BLOCKED"),
    ("late (at after expires_at)", setv("at", ts(300_001)), "BLOCKED"),
    ("missing window_ttl_minutes", drop("window_ttl_minutes"), "BLOCKED"),
    ("window_expires_at differs", setv("window_expires_at", ts(91 * 60_000)), "BLOCKED"),
    ("bytes_used total wrong", lambda r: r.__setitem__("bytes_used", {**BYTES, "total": 1}), "BLOCKED"),
    ("legacy alias field", setv("signal_at", ts(2100)), "BLOCKED"),
    ("request_sha256 differs", setv("request_sha256", "0" * 64), "BLOCKED"),
    ("other controller hash", setv("controller_sha256", "0" * 64), "BLOCKED"),
]
OPERATIONS = [("crash", "D-1", "checker"), ("crash", "API-D-1", "api-check"), ("start", "D-5", "checker"),
              ("start", "API-D-5", "api-check"), ("restart", "R-1", "checker"), ("restart", "R-1i", "checker"),
              ("engine", "W-IMG", "checker")]
GOOD = {"crash": "PASS", "start": "PASS", "restart": "PASS", "engine": "PASS"}

STOP = [  # restart stop-leg fixtures: (id, knobs, mutation, expected)
    ("wrong exit (1)", {"exit_code": 1}, None, "FAIL"),
    ("traceback", {"traceback": True}, None, "FAIL"),
    ("KILL fired at 10.5 s", {"kill_rel": 10_500}, None, "FAIL"),
    ("exit at 10.000 s", {"exit_rel": 10_000}, None, "PASS"),
    ("exit at 10.001 s", {"exit_rel": 10_001}, None, "FAIL"),
    ("no Stopped. line", {"stopped": False}, None, "FAIL"),
    ("listener still there", {"listener_gone": False}, None, "FAIL"),
    ("FAILED app stop agreeing", {"exit_code": 1}, None, "FAIL"),
    ("stop miss reported DONE", {"exit_code": 1}, fail_as_done, "BLOCKED"),
    ("good stop reported FAILED app", {}, failed("app"), "BLOCKED"),
    ("seconds_to_exit before the daemon's exit", {}, lambda r: r["legs"][0]["evidence"].update(seconds_to_exit=0.3),
     "BLOCKED"),
    ("seconds_to_exit across 10 s", {"exit_rel": 10_001},
     lambda r: r["legs"][0]["evidence"].update(seconds_to_exit=10.0), "BLOCKED"),
    ("within_10s disagrees", {}, lambda r: r["legs"][0]["evidence"].update(within_10s=False), "BLOCKED"),
    ("stop_inspect at restart root", {}, lambda r: r.update(stop_inspect=r["legs"][0]["evidence"]["stop_inspect"]),
     "BLOCKED"),
    ("stop leg only", {}, lambda r: r.__setitem__("legs", r["legs"][:1]), "BLOCKED"),
    ("parent exit_code differs", {}, setv("exit_code", 1), "BLOCKED"),
    ("start leg exit_code not null", {}, lambda r: r["legs"][1].update(exit_code=0), "BLOCKED"),
    ("signal_sent_at without ms", {},
     lambda r: r["legs"][0]["evidence"].update(signal_sent_at="2026-10-20T18:00:02+00:00"), "BLOCKED"),
    ("start leg health miss", {"health": None}, None, "FAIL"),
]
START = [  # standalone start (and its writer twin) fixtures
    ("health at 30.000 s", {"health": 30_000}, None, "PASS"),
    ("health at 30.001 s", {"health": 30_001}, None, "FAIL"),
    ("measured timeout (no 200)", {"health": None}, None, "FAIL"),
    ("another container id", {"after_cid": "0" * 64}, None, "BLOCKED"),
    ("inspect drift", {"after_runtime": {**RUNTIME, "image_id": "sha256:" + "0" * 64}}, None, "BLOCKED"),
    ("different data listing", {"before_entries": [{**ENTRIES[0], "size": 1}]}, None, "BLOCKED"),
    ("truncated data listing", {"truncated": True}, None, "BLOCKED"),
    ("extra commands_run", {"extra": True}, None, "BLOCKED"),
    ("data inode changed", {"inode_after": 4002}, None, "BLOCKED"),
    ("health 400 Host not allowed", {"status": 400}, None, "BLOCKED"),
    ("probe cadence gap", {"health": None, "gap": True}, None, "BLOCKED"),
    ("200 with null health_at", {}, lambda r: r.update(health_at=None, seconds_to_health=None), "BLOCKED"),
    ("timeout missing null key", {"health": None}, drop("health_at"), "BLOCKED"),
    ("seconds_to_health disagrees", {}, setv("seconds_to_health", 1.7), "BLOCKED"),
    ("FAILED app agreeing (late)", {"health": 30_001}, None, "FAIL"),
    ("healthy reported FAILED app", {}, failed("app"), "BLOCKED"),
    ("timeout reported DONE", {"health": None}, fail_as_done, "BLOCKED"),
    ("start exit_code not null", {}, setv("exit_code", 0), "BLOCKED"),
    ("start_audit_ref at wrong leaf", {}, lambda r: r["start_audit_ref"].update(path="audit-x.json"), "BLOCKED"),
    ("origin_answer on start", {}, setv("origin_answer", None), "BLOCKED"),
    ("listings_match dishonest", {}, setv("listings_match", False), "BLOCKED"),
]
CRASH = [
    ("exit 0 not 137", {"exit_code": 0}, None, "BLOCKED"),
    ("listener still there", {"listener_gone": False}, None, "BLOCKED"),
    ("origin answered", {"origin_refused": False}, None, "BLOCKED"),
    ("FAILED app", {"decision": "FAILED", "kind": "app"}, None, "BLOCKED"),
    ("stale stop_inspect", {"finished": 2150}, None, "BLOCKED"),
    ("stop_inspect null", {}, setv("stop_inspect", None), "BLOCKED"),
    ("exit_status not the inspect state", {}, setv("exit_status", "running"), "BLOCKED"),
    ("retired root oom_killed", {}, setv("oom_killed", False), "BLOCKED"),
]


def _cases():
    for op, row, writer in OPERATIONS:
        yield pytest.param(op, row, writer, {}, None, GOOD[op], id=f"{row}/{writer}: DONE")
        for name, mutation, expected in COMMON:
            yield pytest.param(op, row, writer, {}, mutation, expected, id=f"{row}/{writer}: {name}")
        extra = {"crash": CRASH, "start": START, "restart": STOP}.get(op, [])
        for name, knobs, mutation, expected in extra:
            yield pytest.param(op, row, writer, knobs, mutation, expected, id=f"{row}/{writer}: {name}")


@pytest.mark.parametrize(("op", "row", "writer", "knobs", "mutation", "expected"), list(_cases()))
def test_fixture_verdicts(tmp_path, op, row, writer, knobs, mutation, expected):
    w, req, raw, receipt = build(tmp_path, op, row, writer, knobs)
    if mutation:
        mutation(receipt)
    result = judged(w, req, raw, receipt)
    assert result["status"] == expected, result["reasons"]
    if expected != "BLOCKED" or mutation in (failed("host"),):
        assert result["window_ttl_minutes"] == 90 and result["bytes_used"] == BYTES


def later(value: str, ms: int, us: int = 0) -> str:
    moved = datetime.fromisoformat(value) + timedelta(milliseconds=ms, microseconds=us)
    return moved.isoformat(timespec="microseconds" if us else "milliseconds")


def stop_e(**fields):
    return lambda r: r["legs"][0]["evidence"].update(**fields)


def health_e(seconds, ms=None, us=0, where=None):
    """Set health_elapsed_seconds in both places; observed_until = start_sent_at + ms (+ us) when given."""
    def apply(r):
        e = where(r) if where else r
        e["health_elapsed_seconds"] = seconds
        e["health_observation"]["elapsed_seconds"] = seconds
        if ms is not None:
            e["health_observation"]["observed_until"] = later(e["start_sent_at"], ms, us)
    return apply


# QA TD-1 (TIMING-DECISION-1.md 70dc7eea...): (id, op, row, knobs, mutation, expected, reason substring).
# Stop leg defaults: exited_at = signal_sent_at + 0.400 s, leg ends 0.200 s later (span 0.600 s).
TIMING = [
    ("exit measure ends at the observation (+0.110 s)", "restart", "R-1", {}, stop_e(seconds_to_exit=0.51),
     "PASS", None),
    ("exit measure at the observation (R-1i)", "restart", "R-1i", {}, stop_e(seconds_to_exit=0.51), "PASS", None),
    ("exit measure exactly 1 ms before the daemon's exit", "restart", "R-1", {}, stop_e(seconds_to_exit=0.399),
     "PASS", None),
    ("exit measure 1.5 ms before the daemon's exit", "restart", "R-1", {}, stop_e(seconds_to_exit=0.3985),
     "BLOCKED", "before the daemon's exit"),
    ("exit measure at the leg end + 1 ms", "restart", "R-1", {}, stop_e(seconds_to_exit=0.601), "PASS", None),
    ("exit measure past the leg end + 1 ms", "restart", "R-1", {}, stop_e(seconds_to_exit=0.602),
     "BLOCKED", "after its stop leg"),
    ("FinishedAt at 10.000 s, seen after 10.000 s", "restart", "R-1", {"exit_rel": 10_000},
     stop_e(seconds_to_exit=10.05), "BLOCKED", "different sides of 10.000 s"),
    ("FinishedAt at 10.001 s, measure 10.000 s", "restart", "R-1", {"exit_rel": 10_001},
     stop_e(seconds_to_exit=10.0), "BLOCKED", "different sides of 10.000 s"),
    ("late exit, seen late", "restart", "R-1", {"exit_rel": 10_001}, stop_e(seconds_to_exit=10.1), "FAIL", None),
    ("seconds_to_health exactly 1 ms over the instants (29.999 s)", "start", "D-5", {"health": 29_999},
     setv("seconds_to_health", 30.0), "PASS", None),
    ("seconds_to_health 1 ms under the instants", "start", "D-5", {}, setv("seconds_to_health", 1.639), "PASS", None),
    ("seconds_to_health across 30 s", "start", "D-5", {"health": 30_000}, setv("seconds_to_health", 30.0005),
     "BLOCKED", "seconds_to_health"),
    ("health_elapsed_seconds 1 ms over observed_until", "start", "D-5", {"health": 29_999}, health_e(30.0),
     "PASS", None),
    ("health_elapsed_seconds 2 ms off observed_until", "start", "D-5", {}, health_e(1.642),
     "BLOCKED", "health_elapsed_seconds"),
    ("health_elapsed_seconds not the observation's", "start", "D-5", {}, setv("health_elapsed_seconds", 1.6405),
     "BLOCKED", "health_observation disagrees"),
    ("healthy start, health measure past 30 s", "start", "D-5", {"health": 30_000}, health_e(30.0005, 30_000, 500),
     "PASS", None),
    ("measured timeout to 30.040 s", "start", "D-5", {"health": None}, health_e(30.04, 30_040), "FAIL", None),
    ("timeout measure 2 ms off observed_until", "start", "D-5", {"health": None}, health_e(30.002),
     "BLOCKED", "health_elapsed_seconds"),
    ("timeout measured 0.5 ms short of 30 s", "start", "D-5", {"health": None}, health_e(29.9995),
     "BLOCKED", "not measured through"),
    ("timeout observed_until 0.5 ms short of 30 s", "start", "D-5", {"health": None},
     health_e(30.0, 29_999, 500), "BLOCKED", "not measured through"),
    ("restart start leg: seconds_to_health 1 ms over", "restart", "R-1", {"health": 29_999},
     lambda r: r["legs"][1]["evidence"].update(seconds_to_health=30.0), "PASS", None),
]


@pytest.mark.parametrize(("op", "row", "knobs", "mutation", "expected", "reason"),
                         [pytest.param(*c[1:], id=c[0]) for c in TIMING])
def test_td1_timing_cross_checks(tmp_path, op, row, knobs, mutation, expected, reason):
    w, req, raw, receipt = build(tmp_path, op, row, "checker", knobs)
    mutation(receipt)
    result = judged(w, req, raw, receipt)
    assert result["status"] == expected, result["reasons"]
    if reason:
        assert any(reason in r for r in result["reasons"]), result["reasons"]


@pytest.mark.parametrize(("text", "expected"), [("30.000", "PASS"), ("30.0000000000000000001", "BLOCKED")])
def test_td1_numbers_are_read_from_their_json_text(tmp_path, text, expected):
    assert 30.0 - 29.999 > 0.001  # why TD-1 forbids binary floats: an honest 1 ms would BLOCK
    w, req, raw, receipt = build(tmp_path, "start", "D-5", "checker", {"health": 29_999})
    body = json.dumps(receipt)
    assert body.count('"seconds_to_health": 29.999') == 1
    write_file(w.dir / "D-5.json", (body.replace('"seconds_to_health": 29.999', f'"seconds_to_health": {text}')
                                    + "\n").encode())
    parsed, _, _ = host.read_bound(w.dir, "D-5.json", host.RECEIPT_MAX)
    assert parsed["seconds_to_health"] == Decimal(text) and type(parsed["seconds_to_health"]) is Decimal
    result = judged(w, req, raw, parsed)
    assert result["status"] == expected, result["reasons"]


def test_td1_instants_are_whole_microseconds():
    assert host.instant("2026-10-20T18:00:06.100999999+00:00", "x") == \
        host.instant("2026-10-20T18:00:06.100999+00:00", "x") == Decimal("1792519206.100999")


def test_echo_mismatch_leaves_the_sequence_unknown(tmp_path):
    w, req, raw, receipt = build(tmp_path, "crash", "D-1", "checker", {})
    receipt["writer"] = "api-check"
    assert judged(w, req, raw, receipt)["sequence_valid"] is False
    good = judged(w, req, raw, w.crash(req, raw))
    assert (good["status"], good["sequence_valid"], good["expected_sequence"]) == ("PASS", True, 2)
    assert good["window_expires_at"] == ts(90 * 60_000)


def test_identity_refusal_keeps_the_number(tmp_path):
    w, req, raw, _ = build(tmp_path, "crash", "D-1", "checker", {})
    refusal = w.receipt(req, raw, 2000, 2100, None, "REFUSED", None, reason="identity")
    refusal.update(sequence_used=False, expected_sequence=1)
    result = judged(w, req, raw, refusal)
    assert (result["status"], result["sequence_valid"], result["expected_sequence"]) == ("BLOCKED", True, 1)
    refusal.update(sequence_used=False, decision="DONE", done=True)
    assert judged(w, req, raw, refusal)["sequence_valid"] is False


def test_timing_refusal_uses_the_number(tmp_path):
    w, req, raw, _ = build(tmp_path, "crash", "D-1", "checker", {})
    refusal = w.receipt(req, raw, 2000, 2100, None, "REFUSED", None, reason="expired while held")
    result = judged(w, req, raw, refusal)
    assert (result["status"], result["sequence_used"], result["expected_sequence"]) == ("BLOCKED", True, 2)


# ---------------------------------------------------------------- engine-image (W1 pin)

def engine_reading(tmp_path, name, **knobs):
    w = World(tmp_path / name)
    req, raw = w.request("W-IMG", 1)
    return judged(w, req, raw, w.engine(req, raw, **knobs))


ENGINE_CASES = [
    ("same reading twice", {}, {}, PIN, "PASS", ""),
    ("a different ID", {"image": "sha256:" + "0" * 64}, {"image": "sha256:" + "0" * 64}, PIN, "BLOCKED",
     "new image: tell Security before use"),
    ("prefix-only pin", {}, {}, PIN[:19], "BLOCKED", "never a prefix"),
    ("found no (REFUSED)", {"decision": "REFUSED"}, {}, PIN, "BLOCKED", "not DONE"),
    ("running false", {"running": False}, {"running": False}, PIN, "BLOCKED", "not running"),
    ("changed start time", {}, {"started": 900}, PIN, "BLOCKED", "container_started_at changed"),
    ("image_matches field disagreeing", {"image_matches": False}, {}, PIN, "BLOCKED", "not DONE"),
    ("restart_count field", {"restart_count": 1}, {}, PIN, "BLOCKED", "not DONE"),
]


@pytest.mark.parametrize(("before", "after", "expected", "status", "reason"),
                         [pytest.param(*c[1:], id=f"W-IMG: {c[0]}") for c in ENGINE_CASES])
def test_engine_image(tmp_path, before, after, expected, status, reason):
    result = host.compare_engine(engine_reading(tmp_path, "before", **before),
                                 engine_reading(tmp_path, "after", **after), expected)
    assert result["status"] == status and reason in " ".join(result["reasons"])


def test_engine_missing_reading_blocks():
    assert host.compare_engine(None, None)["status"] == "BLOCKED"


# ---------------------------------------------------------------- requests

@pytest.mark.parametrize("binding", [PROJECT, CALIBRATION], ids=["project", "calibration"])
def test_request_round_trip(tmp_path, binding):
    w = World(tmp_path, binding)
    req, _ = w.request("D-1", 1)
    raw = host.write_request(w.window, req, clock=lambda: BASE + timedelta(seconds=2))
    back, read_raw, info = host.read_bound(w.dir, "WAITING-D-1.json", host.REQUEST_MAX)
    assert back == req and read_raw == raw and oct(info.st_mode & 0o777) == "0o600"
    assert set(back) == host.REQUEST_KEYS and back["write"] is True and back["receipt_format"] == host.RECEIPT_SCHEMA
    assert back["binding"] == binding and back["host_action"] == back["operation"] == "crash"
    assert back["receipt_file"] == str(w.dir / "D-1.json") and len(raw) <= host.REQUEST_MAX
    assert host.validate_request(back, w.window) == back


def test_requests_never_outlive_the_window(tmp_path):
    w = World(tmp_path)
    with pytest.raises(host.Blocked, match="later than window_expires_at"):
        host.make_request(w.window, "D-1", 1, expires_at=ts(90 * 60_000 + 1), action="a", expected="e",
                          now=BASE + timedelta(seconds=1))
    with pytest.raises(host.Blocked, match="window_expires_at has passed"):
        host.make_request(w.window, "D-1", 1, expires_at=ts(90 * 60_000), action="a", expected="e",
                          now=BASE + timedelta(minutes=90))
    req, _ = w.request("D-1", 1)
    with pytest.raises(host.Blocked, match="expired before publication"):
        host.write_request(w.window, req, clock=lambda: BASE + timedelta(seconds=301))
    assert not (w.dir / "WAITING-D-1.json").exists()


@pytest.mark.parametrize(("writer", "row"), [("api-check", "D-1"), ("checker", "API-D-5"), ("checker", "HOST-L"),
                                             ("qa-scan", "D-1"), ("qa-runner", "R-1")])
def test_row_from_the_wrong_writer_is_never_written(tmp_path, writer, row):
    w = World(tmp_path)
    client = host.HostClient(w.window_path, w.window_sha, writer=writer, clock=lambda: BASE)
    result = asyncio.run(client.execute(row, expires_at=ts(300_000), action="a", expected="e"))
    assert result["status"] == "BLOCKED" and "not allowed" in result["reasons"][0]
    assert not list(w.dir.glob("WAITING-*"))


# ---------------------------------------------------------------- the client against a fake controller

class Controller:
    """Answers WAITING files by writing <row>.json; advances a fake clock; runs nothing."""

    def __init__(self, world, answer, fast=False):
        self.world, self.answer, self.fast = world, answer, fast
        self.now, self.seen = BASE + timedelta(seconds=1), set()

    def clock(self):
        return self.now

    async def sleep(self, seconds):
        self.now += timedelta(seconds=seconds) if self.fast else timedelta(milliseconds=1)
        for path in sorted(self.world.dir.glob("WAITING-*.json")):
            raw = path.read_bytes()
            req = json.loads(raw)
            if req["request_id"] in self.seen:
                continue
            self.seen.add(req["request_id"])
            out = self.answer(req, raw)
            target = self.world.dir / f"{req['row']}.json"
            if callable(out):
                out(target)
            elif out is not None:
                write_file(target, out)


def seq_file(w, writer="checker", expected=1, window_id=WID):
    write_file(w.dir / f"SEQ-{writer}.json", {"window_id": window_id, "writer": writer, "expected_sequence": expected,
                                              "last_request_id": None, "updated_at": ts(500)})


def client_for(w, answer, writer="checker", fast=False):
    ctl = Controller(w, answer, fast)
    return host.HostClient(w.window_path, w.window_sha, writer=writer, clock=ctl.clock, sleep=ctl.sleep,
                           poll_seconds=5), ctl


def honest(w):
    def answer(req, raw):
        if req["operation"] == "crash":
            return w.crash(req, raw)
        prior = (w.dir / f"{PRIOR[req['row']]}.json").read_bytes()
        return w.start(req, raw, prior)
    return answer


def run(client, row):
    return asyncio.run(client.execute(row, expires_at=ts(300_000), action="fixed host step", expected="QA rule"))


@pytest.mark.parametrize(("row", "writer"), [("D-1", "checker"), ("API-D-1", "api-check")])
def test_client_crash_then_start(tmp_path, row, writer):
    w = World(tmp_path)
    seq_file(w, writer)
    client, _ = client_for(w, honest(w), writer)
    crash = run(client, row)
    start = run(client, {"D-1": "D-5", "API-D-1": "API-D-5"}[row])
    assert (crash["status"], crash["sequence"], start["status"], start["sequence"]) == ("PASS", 1, "PASS", 2)
    assert client.expected_sequence == 3 and client.crash_sha256[row] == crash["receipt_sha256"]
    waiting = (w.dir / f"WAITING-{start['row']}.json").read_bytes()
    assert start["receipt"]["request_sha256"] == sha(waiting)


def test_client_start_rejects_a_crash_receipt_it_did_not_record(tmp_path):
    w = World(tmp_path)
    seq_file(w)
    client, _ = client_for(w, honest(w))
    run(client, "D-1")
    client.crash_sha256["D-1"] = "0" * 64
    result = run(client, "D-5")
    assert result["status"] == "BLOCKED" and "this client recorded" in result["reasons"][0]


FILE_CASES = [
    ("oversize", lambda w, r: (json.dumps(r | {"note": "x" * 17_000}) + "\n").encode(), "oversize"),
    ("partial JSON", lambda w, r: (json.dumps(r) + "\n").encode()[:200], "incomplete or invalid JSON"),
    ("duplicate key", lambda w, r: b'{"schema": "a", "schema": "b"}', "duplicate JSON key"),
    ("NaN number", lambda w, r: b'{"schema": NaN}', "non-finite"),
    ("symlink", "symlink", "symbolic links"),
    ("mode 0644", "0644", "mode 0600"),
    ("missing", None, "missing receipt"),
]


@pytest.mark.parametrize(("make", "reason"), [pytest.param(c[1], c[2], id=f"D-1 file: {c[0]}") for c in FILE_CASES])
def test_receipt_file_rules(tmp_path, make, reason):
    w = World(tmp_path)
    seq_file(w)

    def answer(req, raw):
        good = w.crash(req, raw)
        if make is None:
            return None
        if make == "symlink":
            real = write_file(w.dir / "real.json", good)
            return lambda target: (target.symlink_to(w.dir / "real.json"), real)
        if make == "0644":
            return lambda target: write_file(target, good, mode=0o644)
        return make(w, good)

    client, _ = client_for(w, answer, fast=make is None)
    result = run(client, "D-1")
    assert result["status"] == "BLOCKED" and reason in " ".join(result["reasons"]), result["reasons"]


@pytest.mark.parametrize(("setup", "reason"), [
    pytest.param(lambda w: None, "SEQ-checker.json is missing", id="SEQ missing"),
    pytest.param(lambda w: (seq_file(w, "api-check"), (w.dir / "SEQ-checker.json").symlink_to(
        w.dir / "SEQ-api-check.json")), "symbolic links", id="SEQ symlinked"),
    pytest.param(lambda w: seq_file(w, window_id="window-other"), "another window or writer", id="SEQ wrong window"),
    pytest.param(lambda w: write_file(w.dir / "SEQ-checker.json", {
        "window_id": WID, "writer": "api-check", "expected_sequence": 1, "last_request_id": None,
        "updated_at": ts(500)}), "another window or writer", id="SEQ wrong writer"),
    pytest.param(lambda w: write_file(w.dir / "SEQ-checker.json", {
        "window_id": WID, "writer": "checker", "expected_sequence": True, "last_request_id": None,
        "updated_at": ts(500)}), "integer", id="SEQ boolean number"),
])
def test_sequence_file_rules(tmp_path, setup, reason):
    w = World(tmp_path)
    setup(w)
    client, _ = client_for(w, honest(w))
    result = run(client, "D-1")
    assert result["status"] == "BLOCKED" and reason in result["reasons"][0]
    assert not (w.dir / "WAITING-D-1.json").exists()


def test_pending_waiting_file_gets_its_receipt_before_seq_is_read(tmp_path):
    w = World(tmp_path)
    req, raw = w.request("D-1", 4)
    host.write_request(w.window, req, clock=lambda: BASE + timedelta(seconds=1))
    seq_file(w, expected=5)
    client, ctl = client_for(w, honest(w))
    assert asyncio.run(client.initialize()) == 5
    assert req["request_id"] in ctl.seen and json.loads((w.dir / "D-1.json").read_bytes())["sequence"] == 4


def test_pending_waiting_file_with_a_bad_receipt_blocks(tmp_path):
    w = World(tmp_path)
    req, raw = w.request("D-1", 4)
    host.write_request(w.window, req, clock=lambda: BASE + timedelta(seconds=1))
    seq_file(w, expected=5)
    client, _ = client_for(w, lambda q, r: w.crash(q, r) | {"writer": "api-check"})
    with pytest.raises(host.Blocked, match="does not echo"):
        asyncio.run(client.initialize())


@pytest.mark.parametrize(("used", "expected", "next_sequence"), [(False, 1, 1), (True, 2, 2)],
                         ids=["sequence_used no: number reused", "sequence_used yes: number spent"])
def test_refusals_drive_the_next_number(tmp_path, used, expected, next_sequence):
    w = World(tmp_path)
    seq_file(w)
    answers = iter([
        lambda req, raw: w.receipt(req, raw, 2000, 2100, None, "REFUSED", None, reason="refused") | {
            "sequence_used": used, "expected_sequence": expected},
        honest(w)])
    client, _ = client_for(w, lambda req, raw: next(answers)(req, raw))
    first = run(client, "D-1")
    second = run(client, "D-1")
    assert first["status"] == "BLOCKED" and first["expected_sequence"] == expected, first["reasons"]
    assert (second["status"], second.get("sequence")) == ("PASS", next_sequence), second["reasons"]


def test_repeat_row_ignores_only_the_unchanged_earlier_receipt(tmp_path):
    w = World(tmp_path)
    seq_file(w)
    client, _ = client_for(w, honest(w))
    assert [run(client, "D-1")["status"], run(client, "D-1")["status"]] == ["PASS", "PASS"]
    assert client.expected_sequence == 3


def test_foreign_receipt_at_row_path_blocks_before_publishing(tmp_path):
    w = World(tmp_path)
    seq_file(w)
    req, raw = w.request("D-1", 1)
    write_file(w.dir / "D-1.json", w.crash(req, raw) | {"window_id": "window-other"})
    client, _ = client_for(w, honest(w))
    result = run(client, "D-1")
    assert result["status"] == "BLOCKED" and "not an earlier receipt" in result["reasons"][0]
    assert not (w.dir / "WAITING-D-1.json").exists()


def test_late_receipt_seen_after_expiry_blocks(tmp_path):
    w = World(tmp_path)
    req, raw = w.request("D-1", 1)
    receipt = w.crash(req, raw)
    result = host.judge_receipt(w.window, req, receipt, raw, seen=BASE + timedelta(seconds=301))
    assert result["status"] == "BLOCKED" and "late" in result["reasons"][0]


def test_window_pin_and_files(tmp_path):
    w = World(tmp_path)
    with pytest.raises(host.Blocked, match="sha256 differs"):
        host.load_window(w.window_path, "0" * 64)
    copy_path = tmp_path / "window-copy.json"
    write_file(copy_path, copy.deepcopy(w.window_dict) | {"window_ttl_minutes": 91})
    with pytest.raises(host.Blocked, match="TTL"):
        host.load_window(copy_path, sha(copy_path.read_bytes()))
