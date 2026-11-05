#!/usr/bin/env python3
"""Messages from RollCall's continuous deployer: one job, deliver a line and say whether it went.

    import rollcall_cd_notify as notify
    notify.role("rollcall", "fyi", "deployed ca76f3c1 -> 5243d892: ok")   # -> bool
    notify.owner("RollCall's release 5243d892 was undone: ...")           # -> bool

Shared with the money-test undo (RollCall CD 2): the deployer and the undo both speak through this
module, so the routes live in one place.

owner(text): the owner's Telegram, sent through pi-web-ui's CLI (`pi-web-ui notify telegram --text -
--from RollCall`, Ops #783, pi-web-ui docs/script-notice.md). The subprocess runs under spark's Node 22
binary with PI_WEB_DATA_DIR=/home/shinelay/.pi-web-ui; the text goes over stdin. Exit 0 means sent;
exits 2, 3, 4 mean not sent (logged and queued in the outbox for retry); exit 5 means maybe sent
(logged and recorded in the outbox with maybe_sent=true, NEVER resent).

announce_deploy(...): formats and sends the owner Telegram ping on every prod deploy (forward or undo,
success, self-undone failure, or UNDO INCOMPLETE). Refusals before any change are not deploys and do
not call announce_deploy.

role(role_id, kind, text, key=None): a note in the role's home chat, through pi-web-ui's script_notice
route on its control socket (pi-web-ui docs/script-notice.md, Ops #782): the app token is read from
PI_WEB_UI/app-token at send time and goes only into the socket, never into argv, logs or the outbox.
kind is "fyi" (added without a turn) or "request" (one turn; a script can't read a reply). Every
notice carries a key, so a resend is a duplicate on pi-web-ui's side, never a second message.

Anything not delivered is appended to the outbox (STATE_DIR/outbox.jsonl, 0600), one JSON line each:
{ts, to, kind, text, key, delivered: false, why, refused}. Nothing in it is secret: the texts are the
deployer's own notices. Before each new message the undelivered retryable lines are sent again, oldest
first, and leave the outbox once taken; a line pi-web-ui refused (refused: true) or an owner telegram
that exited 5 (maybe_sent: true) stays, never retried, for a person to read.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

STATE_DIR = Path(os.environ.get("ROLLCALL_CD_STATE", str(Path.home() / ".local" / "state" / "rollcall-cd")))
OUTBOX = STATE_DIR / "outbox.jsonl"
OUTBOX_LOCK = STATE_DIR / "outbox.lock"  # held around every read-modify-write of the outbox
# pi-web-ui's data directory: its control socket and its app token (docs/script-notice.md).
PI_WEB_UI = Path(os.environ.get("ROLLCALL_CD_PI_WEB_UI_DIR",
                                os.environ.get("PI_WEB_DATA_DIR", str(Path.home() / ".pi-web-ui"))))
PI_WEB_UI_DIR = PI_WEB_UI
NOTICE_SENDER = {"id": "rollcall-cd", "title": "RollCall deployer"}
NOTICE_TIMEOUT_SECONDS = 10
NOTICE_MAX_CHARS = 1500  # pi-web-ui counts JavaScript string length (UTF-16 code units)
# Line starts pi-web-ui keeps for its own headers; a notice line starting with one is refused.
RESERVED_LINE_STARTS = ("[Role message", "[Board", "[Queue]", "[System", "[Owner question]")
REFUSED = "pi-web-ui refused it"
# Owner Telegram CLI route (Ops #783, pi-web-ui docs/script-notice.md "From Python (the deployer)").
DEFAULT_NODE_BIN = Path("/home/shinelay/.nvm/versions/node/v22.22.0/bin/node")
DEFAULT_PI_WEB_UI_CLI = Path("/home/shinelay/.nvm/versions/node/v22.22.0/bin/pi-web-ui")
NODE_BIN = Path(os.environ.get("ROLLCALL_CD_NODE", str(DEFAULT_NODE_BIN)))
PI_WEB_UI_CLI = Path(os.environ.get("ROLLCALL_CD_PI_WEB_UI_CLI", str(DEFAULT_PI_WEB_UI_CLI)))
PI_WEB_UI_BIN = PI_WEB_UI_CLI
TELEGRAM_FROM = os.environ.get("ROLLCALL_CD_TELEGRAM_FROM", "RollCall")
TELEGRAM_TIMEOUT_SECONDS = 30
# Optional file sink for rehearsal/tests: when set, role() and owner() append JSONL here instead of live sends.
NOTIFY_SINK = os.environ.get("ROLLCALL_CD_NOTIFY_SINK", "").strip()

ROLE_KINDS = ("fyi", "request")  # what script_notice takes; a script can't read an answer to a question
ROLE_ID = re.compile(r"^[a-z][a-z0-9-]{0,39}$")


def _text(text: object, what: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{what}: a non-empty text is needed, got {text!r}")
    return text


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


@contextlib.contextmanager
def _outbox_lock():
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(OUTBOX_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _outbox(to: str, kind: str, text: str, why: str, key: str | None = None, refused: bool = False,
            extra: dict | None = None) -> None:
    line = {"ts": _now(), "to": to, "kind": kind, "text": text, "delivered": False, "why": why}
    if key is not None:
        line.update(key=key, refused=refused)
    elif refused:
        line["refused"] = True
    if extra:
        line.update(extra)
    with _outbox_lock():
        fd = os.open(OUTBOX, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (json.dumps(line) + "\n").encode())
        finally:
            os.close(fd)


def _sink(to: str, kind: str, text: str, **extra) -> bool:
    if not NOTIFY_SINK:
        return False
    sink = Path(NOTIFY_SINK)
    sink.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    line = {"ts": _now(), "to": to, "kind": kind, "text": text, **extra}
    with _outbox_lock():
        fd = os.open(sink, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (json.dumps(line) + "\n").encode())
        finally:
            os.close(fd)
    return True


def _js_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def notice_text(text: str) -> str:
    """`text` as script_notice takes it: control characters but line breaks made spaces, a line that
    starts like one of pi-web-ui's own headers indented, and at most NOTICE_MAX_CHARS (cut with ...)."""
    text = "".join(c if c == "\n" or (c >= " " and c != "\x7f") else " " for c in text)
    text = "\n".join("  " + line if line.startswith(RESERVED_LINE_STARTS) else line for line in text.split("\n"))
    if _js_length(text) > NOTICE_MAX_CHARS:
        while _js_length(text) > NOTICE_MAX_CHARS - 3:
            text = text[:-1]
        text += "..."
    return text


def _send_notice(role_id: str, kind: str, text: str, key: str) -> tuple[str | None, str]:
    """(pi-web-ui's message id, "") when it took the notice, else (None, why not)."""
    try:
        token = (PI_WEB_UI / "app-token").read_text().strip()
    except OSError as e:
        return None, f"pi-web-ui's app token could not be read ({type(e).__name__})"
    req = {"cmd": "script_notice", "token": token, "role": role_id, "kind": kind,
           "sender": NOTICE_SENDER, "text": text, "key": key}
    buf = b""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(NOTICE_TIMEOUT_SECONDS)
            s.connect(str(PI_WEB_UI / "pi-web-ui.sock"))
            s.sendall((json.dumps(req) + "\n").encode())
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
    except OSError as e:  # no socket (pi-web-ui down or restarting), refused, timed out
        return None, f"pi-web-ui's control socket did not answer ({type(e).__name__})"
    try:
        answer = json.loads(buf.split(b"\n", 1)[0])
    except ValueError:
        return None, "pi-web-ui's control socket gave no JSON answer"
    if isinstance(answer, dict) and answer.get("ok") is True and isinstance(answer.get("id"), str):
        return answer["id"], ""
    error = answer.get("error") if isinstance(answer, dict) else None
    return None, f"{REFUSED}: {error or 'no reason given'}"


def resend_outbox() -> int:
    """Send the outbox's undelivered role lines again, oldest first, until one does not go; those that
    went leave the outbox, a refused one is marked and kept. Returns how many went."""
    with _outbox_lock():
        if not OUTBOX.exists():
            return 0
        lines = [json.loads(x) for x in OUTBOX.read_text().splitlines() if x.strip()]
        kept, sent, stuck = [], 0, False
        for line in lines:
            if stuck or line.get("to") == "owner" or line.get("refused") or not line.get("key"):
                kept.append(line)
                continue
            msg_id, why = _send_notice(line["to"], line["kind"], line["text"], line["key"])
            if msg_id:
                sent += 1
                continue
            line.update(why=why, refused=why.startswith(REFUSED))
            stuck = not line["refused"]  # pi-web-ui is not answering: keep the rest in order
            kept.append(line)
        if sent or any(line.get("refused") for line in kept):
            tmp = OUTBOX.with_name(OUTBOX.name + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.writelines(json.dumps(line) + "\n" for line in kept)
            os.replace(tmp, OUTBOX)
        return sent


def role(role_id: str, kind: str, text: str, key: str | None = None) -> bool:
    """A note in a role's home chat. True only when pi-web-ui took it; else it is in the outbox.

    `key` (optional, one line, at most 200 characters): a repeat with the same key is not sent again.
    Without one, the key is made from the time, the role, the kind and the text.
    """
    if not isinstance(role_id, str) or not ROLE_ID.match(role_id):
        raise ValueError(f"role(): role_id must be a role id like 'rollcall', got {role_id!r}")
    if kind not in ROLE_KINDS:
        raise ValueError(f"role(): kind must be one of {', '.join(ROLE_KINDS)}, got {kind!r}")
    text = notice_text(_text(text, "role()"))
    if key is None:
        key = "rollcall-cd-" + hashlib.sha256(f"{_now()}|{role_id}|{kind}|{text}".encode()).hexdigest()[:32]
    elif not isinstance(key, str) or not key.strip() or len(key) > 200 or any(c < " " for c in key):
        raise ValueError(f"role(): key must be one line of 1-200 characters, got {key!r}")
    if _sink(role_id, kind, text, key=key):
        return True
    resend_outbox()
    msg_id, why = _send_notice(role_id, kind, text, key)
    if msg_id:
        return True
    _outbox(role_id, kind, text, why, key=key, refused=why.startswith(REFUSED))
    return False


def _send_owner(text: str, *, from_name: str = TELEGRAM_FROM,
                run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> tuple[bool, str, int | None, bool]:
    """Run `pi-web-ui notify telegram`; returns (sent, why, exit_code, maybe_sent)."""
    cli_bin = PI_WEB_UI_BIN if PI_WEB_UI_BIN != PI_WEB_UI_CLI else PI_WEB_UI_CLI
    data_dir = PI_WEB_UI_DIR if PI_WEB_UI_DIR != PI_WEB_UI else PI_WEB_UI
    if not NODE_BIN.is_file():
        return False, f"the node binary {NODE_BIN} is missing", None, False
    if not cli_bin.is_file():
        return False, f"the pi-web-ui CLI {cli_bin} is missing", None, False
    cmd = [str(NODE_BIN), str(cli_bin), "notify", "telegram", "--text", "-", "--from", from_name]
    env = {**os.environ, "PI_WEB_DATA_DIR": str(data_dir)}
    try:
        r = run(cmd, input=text, text=True, capture_output=True, timeout=TELEGRAM_TIMEOUT_SECONDS, env=env)
    except subprocess.TimeoutExpired:
        return False, "pi-web-ui notify telegram timed out (maybe sent; never resending)", 5, True
    except OSError as e:
        return False, f"pi-web-ui notify telegram did not run: {type(e).__name__}", None, False
    if r.returncode == 0:
        return True, "", 0, False
    lines = (r.stderr or r.stdout or "").strip().splitlines()
    detail = lines[-1] if lines else "no reason given"
    if r.returncode == 5:
        return False, f"Telegram exit 5 (maybe sent; never resending): {detail}", 5, True
    label = {2: "invalid args", 3: "refused by server", 4: "not reachable or no app token"}.get(
        r.returncode, "not sent")
    return False, f"Telegram did not take it (exit {r.returncode}, {label}): {detail}", r.returncode, False


def resend_owner_outbox(run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> int:
    """Retry undelivered owner Telegram lines from the outbox when they are retryable (exits 2, 3, 4).
    Lines with maybe_sent=True (exit 5) or refused=True stay in the outbox and are NEVER resent."""
    with _outbox_lock():
        if not OUTBOX.exists():
            return 0
        lines = [json.loads(x) for x in OUTBOX.read_text().splitlines() if x.strip()]
        kept, sent, stuck, changed = [], 0, False, False
        for line in lines:
            if (stuck or line.get("to") != "owner" or line.get("refused")
                    or line.get("maybe_sent") or line.get("uncertain")):
                kept.append(line)
                continue
            ok, why, code, maybe_sent = _send_owner(
                line["text"], from_name=line.get("from") or TELEGRAM_FROM, run=run)
            if ok:
                sent += 1
                changed = True
                continue
            line.update(why=why, exit_code=code, refused=maybe_sent,
                        maybe_sent=maybe_sent, uncertain=maybe_sent)
            changed = True
            stuck = not maybe_sent
            kept.append(line)
        if changed:
            tmp = OUTBOX.with_name(OUTBOX.name + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.writelines(json.dumps(line) + "\n" for line in kept)
            os.replace(tmp, OUTBOX)
        return sent


def owner(text: str, run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
          *, from_name: str = TELEGRAM_FROM) -> bool:
    """A Telegram message to the owner via `pi-web-ui notify telegram`. True only when exit 0."""
    text = _text(text, "owner()")
    if _sink("owner", "telegram", text, **({"from": from_name} if from_name else {})):
        return True
    resend_owner_outbox(run=run)
    ok, why, code, maybe_sent = _send_owner(text, from_name=from_name, run=run)
    if ok:
        return True
    print(f"rollcall_cd_notify: {why}", file=sys.stderr, flush=True)
    _outbox("owner", "telegram", text, why, refused=maybe_sent,
            extra={"from": from_name, "exit_code": code, "maybe_sent": maybe_sent, "uncertain": maybe_sent})
    return False


def _format_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return "first tagged deploy"
    s = max(0, int(round(seconds)))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s" if s % 60 else f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    return f"{s // 86400}d {(s % 86400) // 3600}h"


def format_deploy_ping(
    *,
    outcome: str,
    sha: str,
    kind: str = "deploy",
    tag: str | None = None,
    previous_sha: str | None = None,
    subjects: Sequence[str] = (),
    health: str = "ok",
    scheduler_lock: str | None = None,
    scheduler_lock_waited_s: int = 0,
    since_previous_seconds: float | None = None,
    restored_sha: str | None = None,
    error: str | None = None,
) -> str:
    """Format the owner's Telegram ping for one prod deploy (forward or undo, success or failure)."""
    sha8 = sha[:8] if sha else "unknown"
    tag_label = tag if tag else "no tag"
    if outcome == "deployed" and kind == "undo":
        head_line = f"RollCall deploy: undo to {sha8} ({tag_label}) — live"
    elif outcome == "deployed":
        head_line = f"RollCall deploy: {sha8} ({tag_label}) — live"
    elif outcome == "failed_self_undone":
        back = f" (restored {restored_sha[:8]})" if restored_sha else ""
        head_line = f"RollCall deploy: {kind} {sha8} ({tag_label}) — FAILED, self-undone{back}"
    elif outcome == "undo_incomplete":
        head_line = f"RollCall deploy: {kind} {sha8} ({tag_label}) — UNDO INCOMPLETE"
    else:
        head_line = f"RollCall deploy: {kind} {sha8} ({tag_label}) — {outcome}"

    lines = [head_line]
    items = [s.strip() for s in subjects if s and s.strip()]
    shown, extra = items[:5], max(0, len(items) - 5)
    if previous_sha:
        prev8 = previous_sha[:8]
        if shown:
            lines.append(f"Commits since {prev8} ({len(items)}):")
            lines.extend(f"• {s}" for s in shown)
            if extra:
                lines.append(f"+{extra} more")
        else:
            lines.append(f"Previous prod: {prev8} (no new commits)")
    else:
        if shown:
            lines.append("Commits (first tagged deploy):")
            lines.extend(f"• {s}" for s in shown)
            if extra:
                lines.append(f"+{extra} more")
        else:
            lines.append("Commits: first tagged deploy (no previous prod tag)")

    if scheduler_lock == "held_elsewhere":
        lines.append(
            f"Health: {health} (WARNING: scheduler_lock=held_elsewhere after {scheduler_lock_waited_s}s — flagged, not undone)"
        )
    elif scheduler_lock:
        lines.append(f"Health: {health} (scheduler_lock={scheduler_lock})")
    else:
        lines.append(f"Health: {health}")

    lines.append(f"Since previous deploy: {_format_elapsed(since_previous_seconds)}")
    if error:
        tail = (error.strip().splitlines() or [""])[-1][:240]
        if tail:
            lines.append(f"Error: {tail}")
    return "\n".join(lines)


def announce_deploy(
    *,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    **kwargs,
) -> bool:
    """Send the owner Telegram ping for one prod deploy; logs and returns False on send failure."""
    try:
        text = format_deploy_ping(**kwargs)
        return owner(text, run=run, from_name=TELEGRAM_FROM)
    except Exception as e:
        print(f"rollcall_cd_notify: announce_deploy failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return False
