"""Project 3 host rows (#125): requests through #126's request side, receipts judged by P5, never counted.

Hypotheses H-125-HOSTROWS-1 and -2, H-125-PRIOR-1 and -2, H-125-SETTLE-1 (rule 20; the #125 work folder's
HYPOTHESIS.md); lead DECISION-6 (08a42dc1) D6.1-D6.4, DECISION-7 (25b0b8cc) D7.3-D7.5 and QA's answer rm-568d6d6e.
- Live writes are off. WRITES_ADMITTED stays False until a reviewed change turns it on, after a real admitted run
  bundle (D6.3) loads through P5, every native, access and Owner requirement holds, and #259's fresh R5' landing and
  QA's fresh receiving hold (D6.4). While it is off, open_host and run_row read nothing, load nothing and write
  nothing: the row is BLOCKED.
- The window is loaded through P5 (ops_host_client_bound.load_bound_candidate_window) once per run.
- Run start (Ops' plan 6.2, QA duty a, D7.4): each of this writer's pending WAITING-<row>.json files must be this
  writer's valid request for that row (#126's validate_request, writer, row) and is waited on up to its ORIGINAL
  expires_at; a <row>.json with its request id settles it only if it echoes it in full. Settled requests are
  recorded; nothing is judged with P5 or counted here. A receipt beside it with another id must be a validated
  earlier one. Unresolved or malformed: the session is BLOCKED before SEQ is read.
- Each row (QA duty b) carries the D6.1 action/expected texts and the D6.2 budget. #126's ops_host_client makes,
  checks and publishes the request (read_sequence, make_request, write_request), byte-unchanged, from a plain copy of
  P5's frozen window: since = not_before = now, wait_seconds = budget, expires_at = since + budget. Less window time
  left than the budget: BLOCKED, nothing written, never shortened. A <row>.json present before writing must be a
  validated earlier receipt (#126 execute's _prior rule with its same-sequence unadmitted-REFUSED exception, plus
  Ops' ended_at <= since); only those exact unchanged bytes are ignored. Any other bytes must echo the request in
  full (Ops' echo keys, value and type, plus request_sha256 of the exact request file), else BLOCKED.
- P5 judges the receipt's exact bytes (judge_candidate_receipt); the row is UNQUALIFIED with
  "P5 assessment: <verdict>, not counted", never PASS (DECISION-5: P5's verdicts are data).
Missing binding, refused window, a write or read failure, or no receipt by the request's own expires_at is BLOCKED,
never FAIL: missing host evidence is not an app timeout. One checker process per window (Ops' plan 6.2) is how runs
are started; this module does not lock across processes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType

import ops_host_client as hc
import ops_host_client_bound as p5

WRITER = "checker"
HOST_ROWS = ("R-1", "R-1i", "D-1", "D-5")
DECISION = "lead DECISION-6 (08a42dc1)"
# D6.4: a reviewed code change turns this on, once the conditions above hold. No flag, file or profile key does.
WRITES_ADMITTED = False
WRITES_OFF = (f"live host writes are not admitted ({DECISION} D6.4: a real admitted run bundle, every native, access "
              "and Owner requirement, and #259's fresh R5' landing with QA's receiving come first): nothing read, "
              "no request written")
_RESTART_EXPECTED = "stop exit 0 within 10.000 s; then GET /api/items 200 within 30.000 s"
# D6.1: descriptive caller constants, never parsed or executed; operation and signal stay fixed by the row.
REQUEST_TEXTS = MappingProxyType({
    "R-1": MappingProxyType({"action": "restart: graceful stop with TERM, then start the same app and forwarder",
                             "expected": _RESTART_EXPECTED}),
    "R-1i": MappingProxyType({"action": "restart: graceful stop with INT, then start the same app and forwarder",
                              "expected": _RESTART_EXPECTED}),
    "D-1": MappingProxyType({"action": "crash: KILL the app", "expected": "exit 137; no health; Ops crash wait 5 s"}),
    "D-5": MappingProxyType({"action": "start the app and forwarder after D-1's recorded crash",
                             "expected": "GET /api/items 200 within 30.000 s"}),
})
# D6.2: the client's wait per request, in seconds. The row limits P5 judges (stop 10 s, health 30 s) are unchanged.
BUDGET_S = MappingProxyType({"R-1": 120, "R-1i": 120, "D-1": 60, "D-5": 60})
# Ops' fresh-receipt echo (hostproto repeat_receipt_state): value and type, plus request_sha256.
ECHO_KEYS = ("row", "operation", "host_action", "writer", "request_id", "sequence", "window_id", "binding")
# #126 execute's _prior identity.
PRIOR_KEYS = ("schema", "window_id", "binding", "row", "writer", "operation")
BINDING_KEYS = frozenset(("context_path", "context_sha256", "uid"))
CONTEXT_KEYS = frozenset(("window_path", "window_sha256", "data_context"))
CONTEXT_MAX = 1 << 20
POLL_S = 0.25
_HEX = frozenset("0123456789abcdef")


def utc_now() -> datetime:
    return datetime.now(UTC)


def binding_problems(value) -> list[str]:
    """The profile's host_binding: null (host rows BLOCKED) or {context_path, context_sha256, uid}."""
    if value is None:
        return []
    if not isinstance(value, dict) or set(value) != BINDING_KEYS:
        return ["host_binding is not null or exactly {context_path, context_sha256, uid}"]
    out = []
    path = value["context_path"]
    if not (isinstance(path, str) and path.startswith("/") and "\x00" not in path and "/../" not in path + "/"):
        out.append("host_binding.context_path is not an absolute path")
    digest = value["context_sha256"]
    if not (isinstance(digest, str) and len(digest) == 64 and set(digest) <= _HEX):
        out.append("host_binding.context_sha256 is not 64 lowercase hex characters")
    uid = value["uid"]
    if type(uid) is not int or uid < 0:
        out.append("host_binding.uid is not a whole number >= 0")
    return out


def read_raw(directory: Path, leaf: str, cap: int, *, uid: int) -> bytes | None:
    """Exact bytes of a regular 0600 file owned by uid, never through a link; None when absent."""
    dir_fd = fd = None
    try:
        dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
        except FileNotFoundError:
            return None
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise hc.Blocked(f"{leaf}: not a regular file")
        if stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != uid:
            raise hc.Blocked(f"{leaf}: must be mode 0600 and owned by the controller user")
        if info.st_size > cap:
            raise hc.Blocked(f"{leaf}: oversize ({info.st_size} > {cap} bytes)")
        raw = os.read(fd, cap + 1)
        if len(raw) != info.st_size:
            raise hc.Blocked(f"{leaf}: changed while read")
        return raw
    except OSError as exc:
        raise hc.Blocked(f"{leaf}: {exc.__class__.__name__}: {exc.strerror or exc}") from exc
    finally:
        for handle in (fd, dir_fd):
            if handle is not None:
                os.close(handle)


def _read(directory: Path, leaf: str, cap: int, *, uid: int) -> tuple[dict, bytes] | None:
    """A host_dir file through #126's read_bound (no link, 0600, owner, cap, strict JSON object); None when absent."""
    try:
        doc, raw, _ = hc.read_bound(directory, leaf, cap, uid=uid)
    except FileNotFoundError:
        return None
    return doc, raw


def thaw(value):
    """P5's frozen window as the plain JSON shapes #126's request side checks."""
    if isinstance(value, MappingProxyType | dict):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, tuple | list):
        return [thaw(v) for v in value]
    return value


class HostSession:
    """One run's host wire: the P5 window (UNTRUSTED data), its uid, and a record for the receipt."""

    def __init__(self, record: dict, window=None, plain: dict | None = None, uid: int | None = None):
        self.record, self.window, self.plain, self.uid = record, window, plain, uid

    @property
    def loaded(self) -> bool:
        return self.record.get("status") == "LOADED"


def _blocked_session(*reasons, **extra) -> HostSession:
    return HostSession(dict({"status": "BLOCKED", "reasons": list(reasons)}, **extra))


def open_host(binding, *, clock=utc_now) -> HostSession:
    """Load the run's window through P5; never raises. Pending own requests are settled by settle()."""
    if not WRITES_ADMITTED:
        return _blocked_session(WRITES_OFF)
    if binding is None:
        return _blocked_session("no host_binding in the profile: no request is written")
    try:
        path = Path(binding["context_path"])
        raw = read_raw(path.parent, path.name, CONTEXT_MAX, uid=binding["uid"])
        if raw is None:
            return _blocked_session("host_binding.context_path does not exist")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != binding["context_sha256"]:
            return _blocked_session("host_binding context file sha256 differs", context_sha256=digest)
        doc = json.loads(raw.decode("utf-8"))
        if not isinstance(doc, dict) or set(doc) != CONTEXT_KEYS:
            return _blocked_session("host_binding context is not exactly {window_path, window_sha256, data_context}")
        window = p5.load_bound_candidate_window(doc["window_path"], doc["window_sha256"],
                                                data_context=doc["data_context"], uid=binding["uid"])
    except p5.TargetRefused as exc:
        return _blocked_session(f"P5 refused the window: {exc}", code=str(exc))
    except Exception as exc:  # any unreadable binding is BLOCKED, never a guess
        return _blocked_session(f"host binding unreadable: {type(exc).__name__}: {exc}"[:400])
    record = {"status": "LOADED", "reasons": [], "trust": window.trust, "window_sha256": doc["window_sha256"],
              "context_sha256": digest, "window_id": window.window.get("window_id"), "loaded_at": hc._iso(clock()),
              "settled": []}
    return HostSession(record, window, thaw(window.window), binding["uid"])


def _same(a, b) -> bool:
    """JSON equality that also keeps types apart (1 is not true, 3 is not "3")."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def echo_problem(doc: dict, request: dict, request_raw: bytes) -> str | None:
    """None when the receipt is this request's: every echo key equal in value and type, and the exact file's hash."""
    for key in ECHO_KEYS:
        if key not in doc or not _same(doc[key], request[key]):
            return f"does not echo this request's {key}"
    if doc.get("request_sha256") != hashlib.sha256(request_raw).hexdigest():
        return "does not echo this request file's sha256 (request_sha256)"
    return None


def prior_problem(doc: dict, request: dict) -> str | None:
    """None when the receipt is a validated earlier one of this window, binding, row, writer and operation."""
    for key in PRIOR_KEYS:
        want = hc.RECEIPT_SCHEMA if key == "schema" else request[key]
        if key not in doc or not _same(doc[key], want):
            return f"another {key}"
    seq = doc.get("sequence")
    if type(seq) is not int:
        return "no whole-number sequence"
    if doc.get("request_id") == request["request_id"]:
        return "it carries this request's id"
    # A request refused at identity or sequence keeps its number, so its receipt may carry this sequence (#126 _prior).
    unadmitted = doc.get("sequence_used") is False and doc.get("decision") == "REFUSED"
    if seq > request["sequence"] or (seq == request["sequence"] and not unadmitted):
        return "it is not older than this request"
    try:
        if hc.instant(doc.get("ended_at"), "prior.ended_at") > hc.instant(request["since"], "since"):
            return "it ended after this request's since"
    except hc.Blocked as exc:
        return str(exc)
    return None


async def _await_receipt(host: HostSession, row: str, request: dict, request_raw: bytes, ignore: bytes | None, *,
                         clock, sleep, mismatch: str | None = None) -> bytes:
    """Look-only wait up to the request's own expires_at; returns the receipt bytes that echo it in full."""
    host_dir = Path(host.plain["host_dir"])
    deadline = hc.instant(request["expires_at"], "expires_at")
    while True:
        found = _read(host_dir, f"{row}.json", p5.RECEIPT_MAX, uid=host.uid)
        if found is not None and found[1] != ignore:
            problem = echo_problem(found[0], request, request_raw)
            if problem:
                raise hc.Blocked(f"{mismatch or row + '.json changed but'} {problem}")
            return found[1]
        if hc.instant(hc._iso(clock()), "now") >= deadline:
            raise hc.Blocked(f"no receipt for {request['request_id']} by its expires_at: missing host evidence, "
                             "not an app FAIL")
        await sleep(POLL_S)


def _ref(host: HostSession, row: str, raw: bytes) -> dict:
    return {"path": str(Path(host.plain["host_dir"]) / f"{row}.json"), "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_length": len(raw)}


def _judge(host: HostSession, request_raw: bytes, row: str, raw: bytes, *, clock) -> tuple[dict, dict]:
    ref = _ref(host, row, raw)
    a = p5.judge_candidate_receipt(request_raw, ref, window=host.window, now=clock())
    return ref, {"trust": a.trust, "verdict": a.verdict, "code": a.code,
                 "identities": [list(x) for x in a.identities]}


async def settle(host: HostSession, *, clock=utc_now, sleep=asyncio.sleep) -> None:
    """Ops' plan 6.2 / QA duty a / DECISION-7 D7.4: before SEQ is read, each pending WAITING request of this writer
    gets a receipt that matches it in full by its ORIGINAL expires_at. Settled requests are recorded; nothing is
    judged with P5 and nothing is counted here. Unresolved, foreign or malformed: BLOCKED."""
    if not host.loaded:
        return
    w, host_dir = host.plain, Path(host.plain["host_dir"])
    rows = sorted(r for r, spec in (w.get("row_table") or {}).items()
                  if isinstance(spec, dict) and spec.get("writer") == WRITER)
    try:
        for row in rows:
            try:
                pending = _read(host_dir, f"WAITING-{row}.json", p5.REQUEST_MAX, uid=host.uid)
                if pending is None:
                    continue
                request, request_raw = pending
                hc.validate_request(request, w)
                if request.get("writer") != WRITER or request.get("row") != row:
                    raise hc.Blocked(f"writer {request.get('writer')!r}, row {request.get('row')!r}")
            except Exception as exc:  # D7.4 check 1
                raise hc.Blocked(f"WAITING-{row}.json is not this writer's valid request: {exc}") from exc
            mismatch = f"{row}.json does not match its pending request:"  # D7.4 check 2
            existing = _read(host_dir, f"{row}.json", p5.RECEIPT_MAX, uid=host.uid)
            if existing is not None and existing[0].get("request_id") == request["request_id"]:
                problem = echo_problem(existing[0], request, request_raw)
                if problem:
                    raise hc.Blocked(f"{mismatch} {problem}")
                raw = existing[1]
            else:
                ignore = None
                if existing is not None:
                    problem = prior_problem(existing[0], request)
                    if problem:
                        raise hc.Blocked(f"{row}.json beside pending WAITING-{row}.json is neither its receipt nor "
                                         f"a validated earlier one: {problem}")
                    ignore = existing[1]
                raw = await _await_receipt(host, row, request, request_raw, ignore, clock=clock, sleep=sleep,
                                           mismatch=mismatch)
            host.record["settled"].append({"row": row, "request_id": request["request_id"],
                                           "sequence": request["sequence"], "receipt": _ref(host, row, raw),
                                           "counted": False})
    except Exception as exc:  # hc.Blocked or anything unexpected: the sequence state is unknown
        host.record.update(status="BLOCKED", reasons=host.record["reasons"] + [
            f"run-start settle: {type(exc).__name__}: {exc}"[:400] + ": the checker's sequence state is unknown"])
    host.record["settled_at"] = hc._iso(clock())


async def run_row(host: HostSession, row: str, *, clock=utc_now, sleep=asyncio.sleep) -> dict:
    """One host row: {status UNQUALIFIED|BLOCKED, reasons, request, receipt, assessment}. Never PASS, never raises."""
    out: dict = {"status": "BLOCKED", "reasons": [], "writer": WRITER}
    if row not in HOST_ROWS:
        out["reasons"].append(f"{row} is not a checker host row")
        return out
    if not WRITES_ADMITTED:
        out["reasons"].append(WRITES_OFF)
        return out
    if not host.loaded:
        out["reasons"] += ["host wire not loaded: no request written"] + list(host.record.get("reasons") or [])
        return out
    texts, budget = REQUEST_TEXTS.get(row), BUDGET_S.get(row)
    if not texts or not budget:
        out["reasons"].append(f"{row}: no {DECISION} request text or budget: no request written")
        return out
    w, host_dir = host.plain, Path(host.plain["host_dir"])
    try:
        sequence = hc.read_sequence(w, WRITER, uid=host.uid)
        now = clock()
        since = hc._iso(now)
        left = hc.instant(w.get("window_expires_at"), "window_expires_at") - hc.instant(since, "since")
        if left < budget:
            raise hc.Blocked(f"window time left < request budget ({left} s < {budget} s; {DECISION} D6.2: a request "
                             "is never shortened)")
        request = hc.make_request(w, row, sequence, writer=WRITER, action=texts["action"],
                                  expected=texts["expected"], expires_at=hc._iso(now + timedelta(seconds=budget)),
                                  now=now)
        span = hc.instant(request["expires_at"], "expires_at") - hc.instant(request["since"], "since")
        if request["since"] != since or request["not_before"] != since or request["wait_seconds"] != budget \
                or span != budget:
            raise hc.Blocked("request times are not since = not_before = now and wait_seconds = expires_at - since "
                             "= budget")
        try:
            prior = _read(host_dir, f"{row}.json", p5.RECEIPT_MAX, uid=host.uid)
        except hc.Blocked as exc:  # H-125-PRIOR-2
            raise hc.Blocked(f"{row}.json before the request is unreadable: {exc} (never ignored silently)") from exc
        if prior is not None:
            problem = prior_problem(prior[0], request)
            if problem:
                raise hc.Blocked(f"{row}.json before the request is not a validated earlier receipt: {problem} "
                                 "(never ignored silently)")
        request_raw = hc.write_request(w, request, clock=clock)
    except hc.Blocked as exc:
        out["reasons"].append(f"request not written: {exc}")
        return out
    except Exception as exc:
        out["reasons"].append(f"request not written: {type(exc).__name__}: {exc}"[:400])
        return out
    out["request"] = {"request_id": request["request_id"], "sequence": request["sequence"],
                      "since": request["since"], "expires_at": request["expires_at"],
                      "wait_seconds": request["wait_seconds"], "sha256": hashlib.sha256(request_raw).hexdigest()}
    try:
        raw = await _await_receipt(host, row, request, request_raw, prior[1] if prior else None,
                                   clock=clock, sleep=sleep)
        ref, assessment = _judge(host, request_raw, row, raw, clock=clock)
    except hc.Blocked as exc:
        out["reasons"].append(str(exc))
        return out
    except Exception as exc:
        out["reasons"].append(f"receipt not judged: {type(exc).__name__}: {exc}"[:400])
        return out
    out["receipt"], out["assessment"] = ref, assessment
    code = "" if assessment["code"] == p5.NONE else f" ({assessment['code']})"
    out.update(status="UNQUALIFIED", reasons=[f"P5 assessment: {assessment['verdict']}{code}, not counted"])
    return out
