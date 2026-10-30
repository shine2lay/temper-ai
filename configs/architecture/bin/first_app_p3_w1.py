#!/usr/bin/env python3
"""W1 for Project 3's WebKit rows from two plain container readings (DECISION-11, #125; task #280).

W1 used to come only from the W-IMG engine-image host operation (Ops), which needs an armed window that has never
existed. DECISION-11 takes it instead from two closed webkit-reading/1 files that Ops' read-only reading tool writes
(`chromium-reading take --webkit`, Ops #534, agent-tools docs/ops-host-chromium-reading.md): one taken before the
checker starts, one after the rows and teardown. The checker never asks Docker anything. It reads only the closed
files it is given, ties their hashes to its WebKit steps, and has no Docker, network or subprocess access (F3).

- gate(): the pre-check, run before the first WebKit MCP call. Any failure leaves WebKit NOT RUN with the first
  failing rule, and no WebKit MCP call is made.
- mark_steps(): every WebKit step records the before-reading's path and sha256 and "W1: provisional until the
  after-check". A measured PASS is PROVISIONAL: never PASS or counted before finalize says COUNT.
- finalize (command line): reads files only (the receipt, the before-reading it names, the after-reading) and writes
  one new closed W1 record next to the receipt (w1.json, 0600, never overwritten): COUNT, or BLOCKED with the first
  failing rule.

Security's conditions (rm-46a8c5a7), checked at both ends: the full id; image = ops_host_client.ENGINE_PIN; Running
true, Paused false, Restarting false (a missing or non-boolean state is not a reading); exactly one endpoint holder,
and it is the id; the before-reading earlier than the run's start, the after-reading later than its end. COUNT needs
the same id, image, StartedAt, RestartCount and sorted networks: a recreation is BLOCKED even with the same image.
Stated limit: readings are endpoint samples, not continuous monitoring, and nothing here protects against deliberate
changes by the same user or inside the container.

Hypothesis H-125-W1-READING-1 (rule 20; DECISION-11, written before this code):
- What is wrong: W1 could come only from the W-IMG host operation, whose armed window has never existed (Ops #299's
  chain behind owner cards #403 and #508, undated), so WebKit can't run at all.
- The one change: take W1 from two plain readings of the WebKit container by Ops' read-only reading tool, as
  DECISION-9 (c) does for Chromium.
- Expected, and how measured: WebKit stops waiting on #299; every rule here has a test that fails when the rule is
  broken; the first WebKit control run has a before-reading with image = pin and a finalize result of COUNT.
- Wrong if: a reading can't show a rule, or the first WebKit control run can't be judged from its two files.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import sys

import first_app_p3_admission as admission
import first_app_p3_guard as guard
import ops_host_client as hc

SCHEMA = "webkit-reading/1"
RECORD_SCHEMA = "p3-w1/1"
ALIAS = "playwright-mcp-webkit"
NETWORK = "temper-ai_default"
# The fixed limits line of every webkit-reading/1 record (Ops #534); the W1 record carries the same line.
LIMITS = ("same-UID actors and in-container changes are not detected; readings are endpoint samples, not continuous "
          "monitoring")
KEYS = frozenset({"endpoint", "id", "image", "limits", "networks", "paused", "reason", "restart_count", "restarting",
                  "running", "schema", "started_at", "status", "taken_at"})
ENDPOINT_KEYS = frozenset({"alias", "count", "holders", "network"})
REASONS = frozenset({"docker-not-found", "container-inspect-failed", "container-inspect-invalid",
                     "container-id-mismatch", "endpoint-list-failed", "endpoint-list-invalid",
                     "endpoint-inspect-failed", "endpoint-inspect-invalid"})
STATE = ("running", "paused", "restarting")
SAME = ("id", "image", "started_at", "restart_count", "networks")  # must not change between the readings
FACTS = ("id", "image", "started_at", "restart_count", "running", "paused", "restarting", "networks", "taken_at")
READING_MAX = 1 << 16
OUT_NAME = "w1.json"
HEX64 = re.compile(r"[0-9a-f]{64}")
IMAGE_RE = re.compile(r"sha256:[0-9a-f]{64}")
TAKEN_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z")
STARTED_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z")
NOTE = "W1: provisional until the after-check"
MISSING = ("W1: no WebKit before-reading (webkit-reading/1) is named (profile key w1_before, or --w1-before for the "
           "controls), so the WebKit rows are NOT RUN and no WebKit MCP call is made")
PENDING = "W1 pending: "  # a verdict's why with this prefix becomes PASS only when finalize says COUNT
FINALIZE = ("after the run and its teardown: chromium-reading take --webkit --id <before id> --out <after file>; then "
            "first_app_p3_w1.py finalize --receipt <this receipt> --after <after file> --after-sha256 <its sha256>")


class Refused(Exception):
    """One W1 rule failed: its name (e.g. image-not-pin:before; the Chromium judge's names where they match) and a
    plain-words text."""

    def __init__(self, rule: str, text: str, *, image: str | None = None):
        super().__init__(f"{rule}: {text}")
        self.rule = rule
        self.text = text
        self.image = image  # image-not-pin only: the image the reading named, for Security's FYI


def ref_problems(ref, where: str = "w1_before") -> list[str]:
    """Shape of the profile key w1_before and the --w1-before flag: exactly {path, sha256}."""
    if not isinstance(ref, dict):
        return [f"{where} is not an object"]
    out = []
    if set(ref) != {"path", "sha256"}:
        out.append(f"{where} must have exactly the keys path and sha256, not {sorted(ref)}")
    path, digest = ref.get("path"), ref.get("sha256")
    if not (isinstance(path, str) and os.path.isabs(path) and "\x00" not in path):
        out.append(f"{where}.path must be an absolute path")
    if not (isinstance(digest, str) and HEX64.fullmatch(digest)):
        out.append(f"{where}.sha256 must be 64 lowercase hex characters")
    return out


def _unique_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def load(path: str, digest: str, side: str):
    """Read one reading the admission way (no symlink in any component, a regular file, capped), check its sha256
    against the named one and parse it.

    The path is the caller's, so a refusal says only the rule and what the caller named: never why the read
    failed, the file's own sha256 or what JSON error it hit. Anything more would tell whoever starts a run
    whether any path on the box exists, its type, and the sha256 of any file the checker can read (#339)."""
    try:
        data = admission.read_regular(pathlib.Path(path), READING_MAX, f"W1 {side}-reading {path}")
    except admission.Refused:
        raise Refused(f"missing:{side}", f"{path} is not a readable regular file of at most {READING_MAX} bytes "
                                         "with no symlink in its path") from None
    if hashlib.sha256(data).hexdigest() != digest:
        raise Refused(f"sha256:{side}", f"{path} does not have the named sha256 {digest}")
    try:
        return json.loads(data, object_pairs_hook=_unique_keys)
    except (UnicodeDecodeError, ValueError):
        raise Refused(f"bad-schema:{side}", "not JSON with unique keys") from None


def _bad(side: str, text: str) -> Refused:
    return Refused(f"bad-schema:{side}", text)


def shape(rec, side: str) -> None:
    """Exactly a closed webkit-reading/1 record with status OK. UNKNOWN raises unknown:<side>; anything else that
    is not the closed shape raises bad-schema:<side>. A refusal names the check that failed, never the file's own
    keys or values (the file is the caller's: #339)."""
    if not isinstance(rec, dict):
        raise _bad(side, "not a JSON object")
    if set(rec) != KEYS:
        raise _bad(side, "not the closed webkit-reading/1 key set")
    if rec["schema"] != SCHEMA:
        raise _bad(side, f"schema is not {SCHEMA}")
    if rec["limits"] != LIMITS:
        raise _bad(side, "limits is not the fixed webkit-reading/1 line")
    status, reason = rec["status"], rec["reason"]
    if status == "UNKNOWN":
        if not (isinstance(reason, str) and reason in REASONS):
            raise _bad(side, "an UNKNOWN record whose reason is not one of the tool's fixed reasons")
        raise Refused(f"unknown:{side}", f"reason={reason}: the reading was UNKNOWN")
    if status != "OK":
        raise _bad(side, "status is neither OK nor UNKNOWN")
    if reason is not None:
        raise _bad(side, "an OK record has a reason")
    if not (isinstance(rec["taken_at"], str) and TAKEN_RE.fullmatch(rec["taken_at"])):
        raise _bad(side, "taken_at is not a UTC time with microseconds")
    if not (isinstance(rec["id"], str) and HEX64.fullmatch(rec["id"])):
        raise _bad(side, "id is not a full 64-hex container id")
    if not (isinstance(rec["image"], str) and IMAGE_RE.fullmatch(rec["image"])):
        raise _bad(side, "image is not sha256:<64 hex>")
    if not (isinstance(rec["started_at"], str) and STARTED_RE.fullmatch(rec["started_at"])):
        raise _bad(side, "started_at is not Docker's UTC StartedAt")
    if type(rec["restart_count"]) is not int or rec["restart_count"] < 0:
        raise _bad(side, "restart_count is not a whole number of at least 0")
    for key in STATE:
        if type(rec[key]) is not bool:
            raise _bad(side, f"{key} is not a boolean")
    nets = rec["networks"]
    if not (isinstance(nets, list) and all(isinstance(n, str) and n for n in nets)):
        raise _bad(side, "networks is not a list of network names")
    if nets != sorted(nets):
        raise _bad(side, "networks are not sorted")
    ep = rec["endpoint"]
    if not (isinstance(ep, dict) and set(ep) == ENDPOINT_KEYS):
        raise _bad(side, "endpoint is not exactly {alias, count, holders, network}")
    holders, count = ep["holders"], ep["count"]
    if not (isinstance(holders, list) and all(isinstance(h, str) and HEX64.fullmatch(h) for h in holders)):
        raise _bad(side, "endpoint.holders is not a list of full 64-hex ids")
    if holders != sorted(holders):
        raise _bad(side, "endpoint.holders are not sorted")
    if type(count) is not int or count != len(holders):
        raise _bad(side, "endpoint.count is not the number of holders")
    if ep["alias"] != ALIAS:
        raise _bad(side, f"endpoint.alias is not {ALIAS}")
    if ep["network"] != NETWORK:
        raise _bad(side, f"endpoint.network is not {NETWORK}")
    for key in ("taken_at", "started_at"):
        try:
            hc.instant(rec[key], key)
        except hc.Blocked as exc:
            raise _bad(side, str(exc)) from exc


def semantics(rec: dict, side: str) -> None:
    """Security's conditions on one well-formed OK reading, in order (rm-46a8c5a7)."""
    if rec["image"] != hc.ENGINE_PIN:
        raise Refused(f"image-not-pin:{side}", f"image {rec['image']} is not the pinned WebKit engine image "
                                               f"{hc.ENGINE_PIN}", image=rec["image"])
    if rec["running"] is not True:
        raise Refused(f"not-running:{side}", "the WebKit browser container was not running")
    if rec["paused"] is not False:
        raise Refused(f"paused:{side}", "the WebKit browser container was paused")
    if rec["restarting"] is not False:
        raise Refused(f"restarting:{side}", "the WebKit browser container was restarting")
    holders = rec["endpoint"]["holders"]
    if len(holders) != 1:
        raise Refused(f"count-not-1:{side}", f"{len(holders)} containers answered {ALIAS} on {NETWORK}, not one")
    if holders != [rec["id"]]:
        raise Refused(f"holder-not-id:{side}", f"the one container answering {ALIAS} is {holders[0]}, not the "
                                               f"reading's id {rec['id']}")


def _before_start(taken_at: str, start, what: str) -> None:
    try:
        earlier = hc.instant(taken_at, "before-reading taken_at") < hc.instant(start, what)
    except hc.Blocked as exc:
        raise Refused("before-not-earlier", str(exc)) from exc
    if not earlier:
        raise Refused("before-not-earlier", f"the before-reading was taken at {taken_at}, not earlier than {what} "
                                            f"{start}")


def precheck(ref, start) -> dict:
    """Rule 2: the before-reading, checked before the first WebKit MCP call. The first failing rule raises."""
    problems = ref_problems(ref)
    if problems:
        raise Refused("input", "; ".join(problems))
    rec = load(ref["path"], ref["sha256"], "before")
    shape(rec, "before")
    semantics(rec, "before")
    _before_start(rec["taken_at"], start, "the checker's start")
    return rec


def gate(ref, start, service: str) -> dict:
    """The receipt's w1 entry for one WebKit service; never raises. NOT GIVEN (no before-reading named), REFUSED
    (rule and reason; WebKit NOT RUN) or PROVISIONAL (the before-reading's facts; the rows may run)."""
    if ref is None:
        return {"service": service, "status": "NOT GIVEN", "rule": None, "reason": MISSING, "before": None,
                "note": NOTE}
    named = {"path": ref.get("path"), "sha256": ref.get("sha256")} if isinstance(ref, dict) else None
    try:
        rec = precheck(ref, start)
    except Refused as exc:
        return {"service": service, "status": "REFUSED", "rule": exc.rule,
                "reason": f"W1 before-reading refused: {exc}", "before": named, "note": NOTE,
                **({"image": exc.image} if exc.image else {})}
    except Exception as exc:  # a reader bug never becomes a provisional W1
        return {"service": service, "status": "REFUSED", "rule": "error",
                "reason": f"W1 before-reading check failed: {exc.__class__.__name__}: {exc}", "before": named,
                "note": NOTE}
    return {"service": service, "status": "PROVISIONAL", "rule": None, "reason": None,
            "before": {**(named or {}), **{key: rec[key] for key in FACTS}}, "note": NOTE, "finalize": FINALIZE}


def measured(step: dict) -> str:
    """A step's own measured status (PROVISIONAL steps keep it in measured)."""
    return step.get("measured", step["status"])


def mark_steps(r: dict) -> None:
    """Rule 3, idempotent: with a PROVISIONAL W1, every WebKit step records the before-reading's path and sha256
    and the provisional note, and a measured PASS becomes PROVISIONAL. Other statuses stay as measured."""
    w = r.get("w1") or {}
    if w.get("status") != "PROVISIONAL":
        return
    before = {"path": w["before"]["path"], "sha256": w["before"]["sha256"]}
    for step in r.get("steps") or []:
        if step.get("engine") != "webkit":
            continue
        step["w1"] = {"before": before, "note": NOTE}
        if step.get("status") == "PASS":
            step["measured"] = "PASS"
            step["status"] = "PROVISIONAL"


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="microseconds")


def _judge(d, after: str, after_sha256: str, record: dict) -> None:
    """Rule 5 on the run's receipt and its two readings; the first failing rule raises."""
    if not isinstance(d, dict) or d.get("journey") != "p3":
        raise Refused("receipt", "not a Project 3 checker receipt (journey p3)")
    w = d.get("w1")
    if not isinstance(w, dict) or w.get("status") != "PROVISIONAL":
        status = w.get("status") if isinstance(w, dict) else None
        raise Refused("receipt", f"the receipt's W1 is {status}, not PROVISIONAL: its WebKit rows did not run on a "
                                 "checked before-reading")
    ref: dict = {"path": (w.get("before") or {}).get("path"), "sha256": (w.get("before") or {}).get("sha256")}
    if ref_problems(ref, "the receipt's w1.before"):
        raise Refused("receipt", "; ".join(ref_problems(ref, "the receipt's w1.before")))
    record["before"] = ref
    for key in ("started_at", "finished_at"):
        try:
            hc.instant(d.get(key), f"the receipt's {key}")
        except hc.Blocked as exc:
            raise Refused("receipt", str(exc)) from exc
    before = load(ref["path"], ref["sha256"], "before")
    shape(before, "before")
    semantics(before, "before")
    _before_start(before["taken_at"], d["started_at"], "the run's started_at")
    aft = load(after, after_sha256, "after")
    shape(aft, "after")
    for key in SAME:
        if aft[key] != before[key]:
            raise Refused(f"field-differs:{key}", f"{key} was {before[key]!r} before and {aft[key]!r} after")
    semantics(aft, "after")
    end = hc.instant(d["finished_at"], "the receipt's finished_at")
    taken = hc.instant(aft["taken_at"], "after-reading taken_at")
    if not (taken > end and taken > hc.instant(before["taken_at"], "before-reading taken_at")):
        raise Refused("after-not-later", f"the after-reading was taken at {aft['taken_at']}, not later than the "
                                         f"run's finished_at {d['finished_at']}")


def finalize(receipt: str, after: str, after_sha256: str) -> tuple[int, dict | None, str]:
    """Write <receipt folder>/w1.json once: (0, record, text) COUNT, (1, record, text) BLOCKED, (2, None, why)
    nothing written (bad input, an unreadable receipt, or a W1 record already there: never overwritten)."""
    problems = [f"{name} must be an absolute path" for name, value in (("--receipt", receipt), ("--after", after))
                if not (isinstance(value, str) and os.path.isabs(value) and "\x00" not in value)]
    if not (isinstance(after_sha256, str) and HEX64.fullmatch(after_sha256)):
        problems.append("--after-sha256 must be 64 lowercase hex characters")
    if problems:
        return 2, None, "; ".join(problems)
    rpath = pathlib.Path(receipt)
    out = rpath.parent / OUT_NAME
    if os.path.lexists(out):
        return 2, None, f"{out} already exists: a W1 record is never overwritten"
    try:
        data = admission.read_regular(rpath, admission.RECEIPT_MAX, f"receipt {receipt}")
    except admission.Refused as exc:
        return 2, None, str(exc)
    record: dict = {"after": {"path": after, "sha256": after_sha256}, "before": None, "finalized_at": None,
                    "limits": LIMITS, "receipt": {"path": receipt, "sha256": hashlib.sha256(data).hexdigest()},
                    "result": "BLOCKED", "rule": None, "schema": RECORD_SCHEMA}
    try:
        try:
            d = json.loads(data)
        except (UnicodeDecodeError, ValueError) as exc:
            raise Refused("receipt", f"not JSON ({exc.__class__.__name__})") from exc
        _judge(d, after, after_sha256, record)
        record["result"] = "COUNT"
    except Refused as exc:
        record["rule"] = str(exc)
    except Exception as exc:  # fail closed: a reader bug is BLOCKED, never COUNT
        record["rule"] = f"error: {exc.__class__.__name__}: {exc}"
    record["finalized_at"] = _now()
    try:
        guard.write_private(out, json.dumps(record, indent=1, sort_keys=True) + "\n")
    except FileExistsError:
        return 2, None, f"{out} already exists: a W1 record is never overwritten"
    except (OSError, ValueError) as exc:
        return 2, None, f"{out} not written: {exc.__class__.__name__}: {exc}"
    code = 0 if record["result"] == "COUNT" else 1
    return code, record, record["rule"] or "COUNT"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_app_p3_w1.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    fin = sub.add_parser("finalize", help="judge a run's W1 from its receipt and two readings; files only")
    fin.add_argument("--receipt", required=True, help="the run's receipt.json (or controls.json), absolute path")
    fin.add_argument("--after", required=True, help="the after-reading (webkit-reading/1), absolute path")
    fin.add_argument("--after-sha256", required=True, help="the after-reading's sha256, as take printed it")
    a = ap.parse_args(argv)
    code, record, text = finalize(a.receipt, a.after, a.after_sha256)
    out = str(pathlib.Path(a.receipt).parent / OUT_NAME)
    print(json.dumps({"result": record["result"] if record else "NOT WRITTEN", "rule": text if code else None,
                      "record": out if record else None}, sort_keys=True))
    print(LIMITS)
    return code


if __name__ == "__main__":
    sys.exit(main())
