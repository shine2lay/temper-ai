"""Temper's side of the host helper's ``token`` and ``usage`` verbs
(``scripts/pi_host/temper_pi_host.py``,
M4 ADR-M4-02 and ADR-M4-15; docs/pi-host-helper.md).

When the box config names the helper's socket (``host_helper_socket``), a worker's login
hand-off asks the helper for the run's pinned account slot -- one line per connection,
``token <slot>``, answered ``ok <token>`` or ``denied <reason>`` -- instead of running the
host Pi CLI in this process. The helper serves only that slot, through Pi's own login store,
and refuses plainly, naming the slot, otherwise.

The token goes back to the caller only: never logged, stored or put in a reason. A refusal's
reason is the helper's plain words (which name the slot and never hold a token), or this
module's own when the helper can't be reached. ``usage <slot>`` reads only that slot's
subscription windows, without refreshing its login or calling a model. Its reply is rebuilt
from allowed fields; an unavailable, stale or malformed reading is never proof of a reset.
The ``branch`` verb's client is :mod:`temper_ai.pi_agent.team_branch`.
"""

from __future__ import annotations

import json
import math
import re
import socket
from datetime import UTC, datetime
from typing import Any

#: The worker's hand-off client waits 60 s for the host; the helper's bridge gives up on a
#: token after 30 s. In between, a refusal still reaches the turn's record.
TOKEN_TIMEOUT_S = 45.0
#: An answer line: ``ok `` and a token (at most 8192 characters), or a refusal.
ANSWER_LIMIT = 16 * 1024
SLOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TOKEN_RE = re.compile(r"^[\x21-\x7e]{1,8192}$")
REASON_LIMIT = 300
#: The usage bridge gives up after 30 s; leave room for its plain answer to reach us.
USAGE_TIMEOUT_S = 40.0
USAGE_WINDOW_RE = re.compile(r"^(?:5h|7d|7d:[a-z0-9-]{1,40})$")
USAGE_TIME_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
USAGE_REASONS = frozenset({
    "signed_out", "not_subscription", "sign_in_expired", "busy", "timeout", "no_answer",
    "incomplete_reading", "stale_reading", "check_failed", "auth_unreadable", "login_changed",
    "sdk_changed", "sdk_unreadable", "checker_unreadable", "unsupported", "bridge_down",
})


class HelperUnreachable(Exception):
    """The helper could not be asked or gave no answer (a plain message, never a token)."""


def ask(path: str, line: str, timeout: float) -> str:
    """Send one request line to the helper; its answer line (without the newline)."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        try:
            sock.connect(path)
        except (FileNotFoundError, ConnectionRefusedError):
            raise HelperUnreachable(f"the host helper isn't running ({path})") from None
        sock.sendall(line.encode() + b"\n")
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        answer = b""
        while b"\n" not in answer and len(answer) <= ANSWER_LIMIT:
            chunk = sock.recv(4096)
            if not chunk:
                break
            answer += chunk
    except TimeoutError:
        raise HelperUnreachable(f"the host helper gave no answer within {timeout:g} s") from None
    except OSError as exc:
        raise HelperUnreachable(
            f"the host helper could not be asked ({exc.__class__.__name__})") from None
    finally:
        sock.close()
    return answer.split(b"\n", 1)[0].decode("utf-8", "replace").strip()


def _plain(slot: str, words: str) -> str:
    text = " ".join("".join(c if c.isprintable() else " " for c in words).split())
    text = text[:REASON_LIMIT] or "no reason given"
    return text if slot in text else f"slot {slot}: {text}"


def token(path: str, slot: str, timeout: float = TOKEN_TIMEOUT_S) -> tuple[str, str]:
    """The login token for ``slot`` from the helper: ``(token, "")``, or ``("", reason)``
    with a plain reason that names the slot."""
    if not SLOT_RE.match(slot or ""):
        return "", "the account slot name is missing or malformed; the host helper was not asked"
    try:
        answer = ask(path, f"token {slot}", timeout)
    except HelperUnreachable as exc:
        return "", f"slot {slot}: {exc}"
    verb, _, rest = answer.partition(" ")
    if verb == "ok" and TOKEN_RE.match(rest):
        return rest, ""
    if verb == "denied":
        return "", _plain(slot, rest)
    if not answer:
        return "", f"slot {slot}: the host helper gave no answer"
    # Never echoed: an answer this client doesn't know could hold anything.
    return "", f"slot {slot}: the host helper gave an answer this Temper doesn't know"


def _usage_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not USAGE_TIME_RE.fullmatch(value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def usage(path: str, slot: str, timeout: float = USAGE_TIMEOUT_S) -> dict[str, Any]:
    """Read the kept slot's usage now; never pick a slot, refresh a login or call a model.

    ``status: ok`` has only ``observed_at`` and validated ``windows`` (5h, 7d and any
    per-model weekly windows). Otherwise ``status: unavailable`` has our fixed reason code.
    An answer's other fields and all plain denied/error text are never passed through.
    """
    def unavailable(reason: str) -> dict[str, Any]:
        return {"status": "unavailable", "reason": reason}

    if not SLOT_RE.fullmatch(slot or ""):
        return unavailable("bad_slot")
    if not path:
        return unavailable("not_configured")
    asked_at = datetime.now(UTC).timestamp()
    try:
        answer = ask(path, f"usage {slot}", timeout)
    except HelperUnreachable:
        return unavailable("helper_unreachable")
    if len(answer.encode()) > ANSWER_LIMIT:
        return unavailable("invalid_reading")
    verb, _, body = answer.partition(" ")
    if verb == "denied":
        return unavailable("denied")
    if verb != "ok":
        return unavailable("invalid_reading")
    try:
        got = json.loads(body)
        if not isinstance(got, dict):
            return unavailable("invalid_reading")
        if got.get("status") == "unavailable":
            reason = got.get("reason")
            return unavailable(reason if isinstance(reason, str) and reason in USAGE_REASONS
                               else "check_failed")
        if got.get("status") != "ok":
            return unavailable("invalid_reading")
        observed = _usage_time(got.get("observed_at"))
        windows = got.get("windows")
        if observed is None or not isinstance(windows, list) or len(windows) > 40:
            return unavailable("invalid_reading")
        # The wire clock has whole seconds. Neither an old cached row nor a future reading
        # proves that the provider's limit has reset.
        if observed.timestamp() < math.floor(asked_at) - 1 \
                or observed.timestamp() > datetime.now(UTC).timestamp() + 1:
            return unavailable("stale_reading")
        rebuilt: list[dict[str, Any]] = []
        keys: set[str] = set()
        for window in windows:
            if not isinstance(window, dict) or set(window) != {"key", "used_percent", "resets_at"}:
                return unavailable("invalid_reading")
            key, used, resets = window["key"], window["used_percent"], window["resets_at"]
            if not isinstance(key, str) or not USAGE_WINDOW_RE.fullmatch(key) or key in keys:
                return unavailable("invalid_reading")
            if isinstance(used, bool) or not isinstance(used, int | float) \
                    or not math.isfinite(used) or not 0 <= used <= 100:
                return unavailable("invalid_reading")
            if resets is not None and _usage_time(resets) is None:
                return unavailable("invalid_reading")
            keys.add(key)
            rebuilt.append({"key": key, "used_percent": float(used), "resets_at": resets})
        if not {"5h", "7d"} <= keys:
            return unavailable("incomplete_reading")
        return {"status": "ok", "observed_at": got["observed_at"], "windows": rebuilt}
    except (ValueError, TypeError, OverflowError):
        return unavailable("invalid_reading")
