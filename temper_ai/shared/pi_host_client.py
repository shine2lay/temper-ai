"""The client of the host helper temper-pi-host (``scripts/pi_host/temper_pi_host.py``,
docs/pi-host-helper.md): one request line per connection over its Unix socket, and its
``token`` verb.

``token <slot>`` (or ``token <slot> <seconds>`` for a login good for at least that long) is
answered ``ok <token>`` or ``denied <reason>``. The helper serves only its listed slots,
through Pi's own login store, and refuses plainly, naming the slot, otherwise.

Two callers share it: the Pi agent's login hand-off (:mod:`temper_ai.pi_agent.host_helper`,
which adds the ``usage`` verb) and temper's Claude pools (:mod:`temper_ai.llm.pi_logins`).
It lives outside ``temper_ai.pi_agent`` so the pools can use it while the Pi agent is
switched off (nothing of ``temper_ai.pi_agent`` is imported then).

The token goes back to the caller only: never logged, stored or put in a reason. A refusal's
reason is the helper's plain words (which name the slot and never hold a token), or this
module's own when the helper can't be reached.
"""

from __future__ import annotations

import re
import socket

#: The worker's hand-off client waits 60 s for the host; the helper's bridge gives up on a
#: token after 30 s. In between, a refusal still reaches the turn's record.
TOKEN_TIMEOUT_S = 45.0
#: An answer line: ``ok `` and a token (at most 8192 characters), or a refusal.
ANSWER_LIMIT = 16 * 1024
SLOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TOKEN_RE = re.compile(r"^[\x21-\x7e]{1,8192}$")
REASON_LIMIT = 300
#: The login floor a caller may ask for, in seconds (the helper's VALIDITY_S_RANGE): its own
#: default is the low end.
VALIDITY_S_RANGE = (1800, 4 * 3600)


class HelperUnreachable(Exception):
    """The helper could not be asked or gave no answer (a plain message, never a token)."""


class HelperRefused(Exception):
    """The helper answered and refused the slot, or the request was never sent because it was
    malformed (the plain reason names the slot, never a token)."""


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


def token(path: str, slot: str, timeout: float = TOKEN_TIMEOUT_S,
          min_validity_s: int | None = None) -> tuple[str, str]:
    """The login token for ``slot`` from the helper: ``(token, "")``, or ``("", reason)``
    with a plain reason that names the slot.  ``min_validity_s`` asks for a login good for at
    least that many seconds (within VALIDITY_S_RANGE); None keeps the helper's 30 minutes."""
    try:
        return token_or_raise(path, slot, timeout, min_validity_s), ""
    except (HelperUnreachable, HelperRefused) as exc:
        return "", str(exc)


def token_or_raise(path: str, slot: str, timeout: float = TOKEN_TIMEOUT_S,
                   min_validity_s: int | None = None) -> str:
    """As :func:`token`, for callers that act differently on the two failures: the token, or
    :class:`HelperUnreachable` (no usable answer: not running, timed out, empty or unknown
    answer) or :class:`HelperRefused` (the helper said no, or the request was malformed and
    never sent). Either message names the slot and never holds a token."""
    if not SLOT_RE.match(slot or ""):
        raise HelperRefused("the account slot name is missing or malformed; the host helper was not asked")
    line = f"token {slot}"
    if min_validity_s is not None:
        low, high = VALIDITY_S_RANGE
        if isinstance(min_validity_s, bool) or not isinstance(min_validity_s, int) \
                or not low <= min_validity_s <= high:
            raise HelperRefused(f"slot {slot}: the asked login validity must be whole seconds from "
                                f"{low} to {high}; the host helper was not asked")
        line += f" {min_validity_s}"
    try:
        answer = ask(path, line, timeout)
    except HelperUnreachable as exc:
        raise HelperUnreachable(f"slot {slot}: {exc}") from None
    verb, _, rest = answer.partition(" ")
    if verb == "ok" and TOKEN_RE.match(rest):
        return rest
    if verb == "denied":
        raise HelperRefused(_plain(slot, rest))
    if not answer:
        raise HelperUnreachable(f"slot {slot}: the host helper gave no answer")
    # Never echoed: an answer this client doesn't know could hold anything.
    raise HelperUnreachable(f"slot {slot}: the host helper gave an answer this Temper doesn't know")
