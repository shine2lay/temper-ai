#!/usr/bin/env python3
"""Cancel a temper run when a box watch writes a record whose verdict isn't PASS.

    python3 scripts/pi_watch_stop.py --records /path/to/records --run <run id> \\
        --since 2026-10-09T17:00:00Z --key-file ~/.config/temper/api-keys/watch-stop.key

A box watch (for a team Project: Security's) checks each box and writes one JSON
record per check into a folder. This reader polls that folder and reads every
new top-level ``*.json`` once (names starting with "." and subfolders are left
alone). It logs each record it reads. The first record dated at or after
``--since`` whose verdict is not exactly ``PASS`` gets the run's ordinary cancel,
``POST /api/runs/<run>/cancel`` with a reason, the same as the owner's Stop; then
the reader exits. Notes never count, only the verdict.

It fails closed:
- a record that still doesn't parse when read again after ``--reread`` seconds
  counts as COULD NOT CHECK;
- so does the watch's own user unit (``--watch-unit``) being anything other
  than "active" for longer than ``--watch-grace`` seconds;
- so does the records folder becoming unreadable.

Every start replays the folder from ``--since``, so a reader restarted by systemd
still acts on a record written while it was down. A second cancel of a run that
already ended is harmless: the server answers with the run's status.

It never writes, moves or deletes anything in the records folder, and it never
prints the key. docs/pi-watch-stop.md has the why and the systemd unit.

Exit codes: 0 the cancel was answered (run cancelled or already ended); 1 the
cancel kept failing for ``--retry-for`` seconds (systemd starts it again, and
the replay tries again); 2 bad arguments or setup; 3 the server has no such run.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REASON_MAX_CHARS = 2000  # the cancel route refuses a longer reason (docs/api-access.md)
DEFAULT_SERVER = "http://127.0.0.1:8420"
DEFAULT_WATCH_UNIT = "security-trial-watch"
MAX_RECORD_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 64


def safe_text(text: str) -> str:
    """Keep valid Unicode; escape unpaired surrogates and controls on one line."""
    text = text.encode("utf-8", "backslashreplace").decode("utf-8")
    return "".join(ch if ch >= " " and ch != "\x7f" else f"\\x{ord(ch):02x}" for ch in text)


def log(text: str) -> None:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        encoding = sys.stdout.encoding or "utf-8"
        line = f"{stamp} {safe_text(text)}".encode(encoding, "backslashreplace").decode(encoding)
        print(line, flush=True)
    except (OSError, UnicodeError, ValueError):
        # A broken log stream must not prevent the ordinary cancel request.
        pass


def parse_time(text: str, *, need_zone: bool = True) -> datetime:
    """Parse a full ISO datetime, requiring a zone by default.
    Missing or unusable record dates must fall back to the file's mtime."""
    if not isinstance(text, str):
        raise ValueError("not a datetime string")
    raw = text.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})?", raw):
        raise ValueError("expected a full ISO datetime, not a date alone")
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        when = datetime.fromisoformat(raw)
        if when.tzinfo is None:
            if need_zone:
                raise ValueError("time has no zone (add Z for UTC)")
            when = when.replace(tzinfo=UTC)
        return when.astimezone(UTC)
    except OverflowError:
        raise ValueError("datetime is out of range") from None


def _since_arg(text: str) -> datetime:
    try:
        return parse_time(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


@dataclass(frozen=True)
class Finding:
    """A reason to cancel: one non-PASS record, or the watch itself."""

    verdict: str
    kind: str
    subject: str
    first_reason: str
    source: str  # the record's file name, or the watch unit

    def reason(self) -> str:
        what = self.kind if self.subject == self.kind else f"{self.kind} {self.subject}"
        return safe_text(f"Security watch {self.verdict}: {what}: {self.first_reason}")[:REASON_MAX_CHARS]


def _mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None


def read_record(path: Path) -> dict[str, Any]:
    """Bound bytes and nesting before decoding; every failure follows re-read."""
    with path.open("rb") as source:
        raw = source.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES:
        raise ValueError(f"record exceeds {MAX_RECORD_BYTES} bytes")
    text = raw.decode("utf-8")
    depth, in_string, escaped = 0, False, False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError(f"record exceeds {MAX_JSON_DEPTH} nesting levels")
        elif ch in "]}":
            depth -= 1
    rec = json.loads(text)
    if not isinstance(rec, dict):
        raise ValueError("not a JSON object")
    return rec


def _describe(rec: dict[str, Any], name: str) -> tuple[str, str]:
    """(kind, subject). Older watch records have no kind or subject: a box record
    has ``box`` with a name; anything else falls back to the file name."""
    box = rec.get("box")
    box_name = box.get("name") if isinstance(box, dict) else box
    kind = str(rec.get("kind") or ("box" if box_name else "record"))
    subject = str(rec.get("subject") or box_name or name)
    return kind, subject


def unit_state(systemctl: str, unit: str) -> str:
    """What ``systemctl --user is-active <unit>`` says ("active", "activating",
    "inactive", "failed", ...), or "unknown (...)" if it can't be asked."""
    try:
        done = subprocess.run([systemctl, "--user", "is-active", unit],
                              capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        return f"unknown ({type(exc).__name__})"
    lines = done.stdout.strip().splitlines()
    return lines[0].strip() if lines else "unknown (no answer)"


class Reader:
    """The folder and the watch unit, polled. :meth:`poll` returns the first
    reason to cancel, or None."""

    def __init__(self, records: Path, since: datetime, *, watch_unit: str, watch_grace: float,
                 reread: float, systemctl: str) -> None:
        self.records = records
        self.since = since
        self.watch_unit = watch_unit
        self.watch_grace = watch_grace
        self.reread = reread
        self.systemctl = systemctl
        self.done: set[str] = set()  # names read for good: never opened again
        self.again_at: dict[str, float] = {}  # names that didn't parse: when to read them again
        self.unit_down_since: float | None = None
        self.unit_last_state: str | None = None

    def poll(self) -> Finding | None:
        found = self._poll_records()
        return found if found is not None else self._poll_unit()

    def _poll_records(self) -> Finding | None:
        try:
            names = sorted(e.name for e in os.scandir(self.records)
                           if e.name.endswith(".json") and not e.name.startswith(".")
                           and e.is_file(follow_symlinks=False))
        except OSError as exc:
            log(f"records folder {self.records} can't be read: {type(exc).__name__}: {exc}")
            return Finding("COULD NOT CHECK", "records", str(self.records),
                           f"records folder can't be read ({type(exc).__name__})", str(self.records))
        now = time.monotonic()
        found: list[tuple[datetime, str, Finding]] = []
        for name in names:
            if name in self.done or self.again_at.get(name, 0.0) > now:
                continue
            item = self._read(name)
            if item is not None:
                found.append(item)
        if not found:
            return None
        found.sort(key=lambda item: (item[0], item[1]))
        return found[0][2]

    def _read(self, name: str) -> tuple[datetime, str, Finding] | None:
        path = self.records / name
        try:
            rec = read_record(path)
        except (OSError, ValueError, RecursionError) as exc:
            problem = f"{type(exc).__name__}: {str(exc)[:200]}"
            if name not in self.again_at:
                self.again_at[name] = time.monotonic() + self.reread
                log(f"read {name}: doesn't parse ({problem}); reading it again in {self.reread:g} s")
                return None
            self.done.add(name)
            self.again_at.pop(name, None)
            when = _mtime(path) or datetime.now(UTC)
            if when < self.since:
                log(f"read {name} again: still doesn't parse, but it is older than --since: not acted on")
                return None
            log(f"read {name} again: still doesn't parse ({problem}): COULD NOT CHECK")
            return when, name, Finding("COULD NOT CHECK", "record", name,
                                       f"record does not parse ({problem})", name)
        self.done.add(name)
        self.again_at.pop(name, None)
        try:
            when = parse_time(rec.get("checked_at"), need_zone=True)
        except ValueError:
            when = _mtime(path) or datetime.now(UTC)
        kind, subject = _describe(rec, name)
        verdict = str(rec.get("verdict") or "no verdict")
        if when < self.since:
            log(f"read {name}: {kind} {subject}: {verdict}, checked {when:%Y-%m-%dT%H:%M:%SZ}, "
                "older than --since: not acted on")
            return None
        log(f"read {name}: {kind} {subject}: {verdict}")
        if verdict == "PASS":
            return None
        reasons = rec.get("reasons")
        first = str(reasons[0]) if isinstance(reasons, list) and reasons else "no reason given"
        return when, name, Finding(verdict, kind, subject, first, name)

    def _poll_unit(self) -> Finding | None:
        state = unit_state(self.systemctl, self.watch_unit)
        if state != self.unit_last_state:
            log(f"watch unit {self.watch_unit}: {state}")
            self.unit_last_state = state
        if state == "active":
            self.unit_down_since = None
            return None
        now = time.monotonic()
        if self.unit_down_since is None:
            self.unit_down_since = now
        if now - self.unit_down_since > self.watch_grace:
            return Finding("COULD NOT CHECK", "watch", self.watch_unit,
                           f"watch unit {state} for over {self.watch_grace:g} s", self.watch_unit)
        return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward the key, or mistake a different endpoint for a cancel."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def post_cancel(server: str, run: str, key: str, reason: str, *,
                timeout: float = 15.0) -> tuple[int | None, str]:
    """One POST to the configured cancel URL, with no proxies or redirects.
    Return content-free transport errors: header exceptions can contain keys."""
    try:
        url = f"{server.rstrip('/')}/api/runs/{run}/cancel"
        request = urllib.request.Request(
            url, data=json.dumps({"reason": reason}).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=timeout) as reply:
                return reply.status, reply.read(2000).decode("utf-8", "replace").replace(key, "[redacted]")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(2000).decode("utf-8", "replace").replace(key, "[redacted]")
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as exc:
        return None, f"{type(exc).__name__}: request failed"


def cancel(server: str, run: str, key: str, finding: Finding, *, retry_every: float,
           retry_for: float) -> int:
    reason = finding.reason()
    log(f"{finding.verdict} from {finding.source}: cancelling run {run}: {reason}")
    started = time.monotonic()
    deadline = started + retry_for
    attempt = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            log(f"cancel still failing after {retry_for:g} s (elapsed {time.monotonic() - started:.2f} s): "
                "exit 1 (systemd starts the reader again; it replays the records and tries again)")
            return 1
        attempt += 1
        status, body = post_cancel(server, run, key, reason, timeout=min(15.0, remaining))
        if status is not None and 200 <= status < 300:
            log(f"cancel answered {status}: {body.strip()[:300]}")
            log(f"done: run {run} cancel answered after {finding.verdict} from {finding.source}")
            return 0
        if status == 404:
            log(f"cancel answered 404: {server} has no run {run} ({body.strip()[:300]}); check --run")
            return 3
        log(f"cancel attempt {attempt} failed: {status if status is not None else 'no answer'}: "
            f"{body.strip()[:300]}")
        time.sleep(min(retry_every, max(0.0, deadline - time.monotonic())))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--records", type=Path, required=True,
                        help="the watch's records folder (absolute); only read")
    parser.add_argument("--run", required=True, help="the run to cancel")
    parser.add_argument("--since", type=_since_arg, required=True,
                        help="act on records checked at or after the fixed Project open-word time, e.g. 2026-10-09T17:00:00Z")
    parser.add_argument("--key-file", type=Path, required=True,
                        help="a named API key's file (docs/api-access.md); the key is never printed")
    parser.add_argument("--server", default=os.environ.get("TEMPER_SERVER_URL") or DEFAULT_SERVER,
                        help=f"temper's API (default TEMPER_SERVER_URL, else {DEFAULT_SERVER})")
    parser.add_argument("--watch-unit", default=DEFAULT_WATCH_UNIT,
                        help=f"the watch's systemd user unit (default {DEFAULT_WATCH_UNIT})")
    parser.add_argument("--watch-grace", type=float, default=60.0,
                        help="seconds the watch unit may be other than active before it counts as COULD NOT CHECK")
    parser.add_argument("--poll", type=float, default=2.0, help="seconds between looks (default 2)")
    parser.add_argument("--reread", type=float, default=2.0,
                        help="seconds before a record that doesn't parse is read again (default 2)")
    parser.add_argument("--retry-every", type=float, default=5.0,
                        help="seconds between cancel attempts that fail (default 5)")
    parser.add_argument("--retry-for", type=float, default=60.0,
                        help="seconds of failed cancel attempts before exit 1 (default 60)")
    parser.add_argument("--systemctl", default="systemctl", help="the systemctl to ask (default systemctl)")
    args = parser.parse_args(argv)

    run = args.run.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run):
        parser.error("--run must be a non-empty URL-safe run id")
    try:
        server = urllib.parse.urlsplit(args.server)
        args.server.encode("ascii")
        valid_server = (server.scheme in {"http", "https"} and bool(server.hostname)
                        and server.username is None and server.password is None
                        and not server.query and not server.fragment
                        and not any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in args.server))
        _ = server.port  # validate the port, including its range
    except (ValueError, UnicodeError):
        valid_server = False
    if not valid_server:
        parser.error("--server must be an http(s) URL with a host and no credentials, query or fragment")
    for option in ("poll", "reread", "retry_every", "retry_for", "watch_grace"):
        value = getattr(args, option)
        if not math.isfinite(value) or value < 0 or (value == 0 and option != "watch_grace"):
            parser.error(f"--{option.replace('_', '-')} must be finite and {'non-negative' if option == 'watch_grace' else 'positive'}")
    if not args.watch_unit or args.watch_unit.startswith("-"):
        parser.error("--watch-unit must name a user unit")
    if not args.records.is_absolute():
        parser.error(f"--records {args.records} is not an absolute path")
    try:
        key = args.key_file.expanduser().read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        parser.error(f"--key-file can't be read ({type(exc).__name__}); contents withheld")
    if not key:
        parser.error("--key-file is empty")
    if not re.fullmatch(r"[!-~]+", key):
        parser.error("--key-file must hold one printable ASCII token; contents withheld")

    reader = Reader(args.records, args.since, watch_unit=args.watch_unit,
                    watch_grace=args.watch_grace, reread=args.reread, systemctl=args.systemctl)
    log(f"watching {args.records} for run {run}: records checked from "
        f"{args.since:%Y-%m-%dT%H:%M:%SZ}; watch unit {args.watch_unit} (grace {args.watch_grace:g} s); "
        f"cancel via {args.server} with the key in {args.key_file}")
    while True:
        finding = reader.poll()
        if finding is not None:
            return cancel(args.server, run, key, finding,
                          retry_every=args.retry_every, retry_for=args.retry_for)
        time.sleep(args.poll)


if __name__ == "__main__":
    sys.exit(main())
