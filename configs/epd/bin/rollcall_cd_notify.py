#!/usr/bin/env python3
"""Messages from RollCall's continuous deployer: one job, deliver a line and say whether it went.

    import rollcall_cd_notify as notify
    notify.role("rollcall", "fyi", "deployed ca76f3c1 -> 5243d892: ok")   # -> bool
    notify.owner("RollCall's release 5243d892 was undone: ...")           # -> bool

Shared with the money-test undo (RollCall CD 2): the deployer and the undo both speak through this
module, so the routes live in one place.

owner(text): the owner's Telegram, sent by temper's bot through the sender agent-tools already uses
for its backup and CI notices (lib/pi-backup.mjs sendTelegram), called here rather than copied. The
bot token is read by that sender from temper's env file at send time; it never passes through this
process, its argv or its logs. The text goes over stdin.

role(role_id, kind, text, key=None): a note in the role's home chat, through pi-web-ui's script_notice
route on its control socket (pi-web-ui docs/script-notice.md, Ops #782): the app token is read from
PI_WEB_UI/app-token at send time and goes only into the socket, never into argv, logs or the outbox.
kind is "fyi" (added without a turn) or "request" (one turn; a script can't read a reply). Every
notice carries a key, so a resend is a duplicate on pi-web-ui's side, never a second message.

Anything not delivered is appended to the outbox (STATE_DIR/outbox.jsonl, 0600), one JSON line each:
{ts, to, kind, text, key, delivered: false, why, refused}. Nothing in it is secret: the texts are the
deployer's own notices. Before each new role message the undelivered role lines are sent again, oldest
first, and leave the outbox once pi-web-ui takes them; a line pi-web-ui refused (refused: true) stays,
not retried, for a person to read. Owner lines stay too: Telegram has no dedupe key, so a resend could
say it twice.
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
from collections.abc import Callable
from pathlib import Path

STATE_DIR = Path(os.environ.get("ROLLCALL_CD_STATE", str(Path.home() / ".local" / "state" / "rollcall-cd")))
OUTBOX = STATE_DIR / "outbox.jsonl"
OUTBOX_LOCK = STATE_DIR / "outbox.lock"  # held around every read-modify-write of the outbox
# pi-web-ui's data directory: its control socket and its app token (docs/script-notice.md).
PI_WEB_UI = Path(os.environ.get("ROLLCALL_CD_PI_WEB_UI_DIR", str(Path.home() / ".pi-web-ui")))
NOTICE_SENDER = {"id": "rollcall-cd", "title": "RollCall deployer"}
NOTICE_TIMEOUT_SECONDS = 10
NOTICE_MAX_CHARS = 1500  # pi-web-ui counts JavaScript string length (UTF-16 code units)
# Line starts pi-web-ui keeps for its own headers; a notice line starting with one is refused.
RESERVED_LINE_STARTS = ("[Role message", "[Board", "[Queue]", "[System", "[Owner question]")
REFUSED = "pi-web-ui refused it"
# The sender agent-tools' watchers use (pi-backup, ci-watch, standee-backup-watch), and its inputs.
TELEGRAM_SENDER = Path(os.environ.get("ROLLCALL_CD_TELEGRAM_SENDER",
                                      "/home/shinelay/projects/agent-tools/lib/pi-backup.mjs"))
TEMPER_ENV_FILE = Path(os.environ.get("ROLLCALL_CD_TEMPER_ENV", "/home/shinelay/temper-ai/.env"))
TELEGRAM_CONFIG = Path(os.environ.get("ROLLCALL_CD_TELEGRAM_CONFIG",
                                      "/home/shinelay/temper-ai/configs/telegram/local/telegram.yaml"))
TELEGRAM_TIMEOUT_SECONDS = 60

ROLE_KINDS = ("fyi", "request")  # what script_notice takes; a script can't read an answer to a question
ROLE_ID = re.compile(r"^[a-z][a-z0-9-]{0,39}$")

# Imports the sender, reads the text from stdin, exits 0 only when Telegram took the message.
# Its log lines (which already hide the token) go to stderr.
_SEND_JS = """
import { pathToFileURL } from "node:url";
const [sender, envFile, configFile] = process.argv.slice(1);
const { sendTelegram } = await import(pathToFileURL(sender).href);
let text = "";
for await (const chunk of process.stdin) text += chunk;
const sent = await sendTelegram(text, { envFile, configFile, log: (m) => console.error(m) });
process.exit(sent ? 0 : 1);
"""


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


def _outbox(to: str, kind: str, text: str, why: str, key: str | None = None, refused: bool = False) -> None:
    line = {"ts": _now(), "to": to, "kind": kind, "text": text, "delivered": False, "why": why}
    if key is not None:
        line.update(key=key, refused=refused)
    with _outbox_lock():
        fd = os.open(OUTBOX, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (json.dumps(line) + "\n").encode())
        finally:
            os.close(fd)


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
    resend_outbox()
    msg_id, why = _send_notice(role_id, kind, text, key)
    if msg_id:
        return True
    _outbox(role_id, kind, text, why, key=key, refused=why.startswith(REFUSED))
    return False


def owner(text: str, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> bool:
    """A Telegram message to the owner from temper's bot. True only when Telegram took it."""
    text = _text(text, "owner()")
    why = None
    if not TELEGRAM_SENDER.is_file():
        why = f"the Telegram sender {TELEGRAM_SENDER} is missing"
    else:
        try:
            r = run(["node", "--input-type=module", "-e", _SEND_JS, "--",
                     str(TELEGRAM_SENDER), str(TEMPER_ENV_FILE), str(TELEGRAM_CONFIG)],
                    input=text, text=True, capture_output=True, timeout=TELEGRAM_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as e:
            why = f"the Telegram sender did not run: {type(e).__name__}"
        else:
            if r.returncode == 0:
                return True
            lines = (r.stderr or "").strip().splitlines()
            why = f"Telegram did not take it (exit {r.returncode}): {lines[-1] if lines else 'no reason given'}"
    _outbox("owner", "telegram", text, why)
    return False
