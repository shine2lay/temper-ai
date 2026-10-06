"""Temper's side of the host helper's ``token`` verb (``scripts/pi_host/temper_pi_host.py``,
M4 ADR-M4-02 and ADR-M4-15; docs/pi-host-helper.md).

When the box config names the helper's socket (``host_helper_socket``), a worker's login
hand-off asks the helper for the run's pinned account slot -- one line per connection,
``token <slot>``, answered ``ok <token>`` or ``denied <reason>`` -- instead of running the
host Pi CLI in this process. The helper serves only that slot, through Pi's own login store,
and refuses plainly, naming the slot, otherwise.

The token goes back to the caller only: never logged, stored or put in a reason. A refusal's
reason is the helper's plain words (which name the slot and never hold a token), or this
module's own when the helper can't be reached. The ``branch`` verb's client is
:mod:`temper_ai.pi_agent.team_branch`.
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
