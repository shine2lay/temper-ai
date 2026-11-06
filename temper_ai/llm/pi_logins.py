"""Temper's Claude logins, taken from pi's own (docs/pools.md, "Where the logins come from").

Temper keeps no Claude login of its own. The slots it may use are listed in
configs/pools/pools.yaml (``pools.logins.slots``; configs/pools/local/pools.yaml wins when it
exists), named as pi names them (``anthropic``, ``anthropic-2``). Each call asks the host
helper temper-pi-host for that slot's current login (``token <slot> <seconds>``), which it
reads through pi's own SDK and login store, refreshing it under pi's own lock when it would
expire too soon. Signing an account in or out of pi, or renewing it, is the only step: the
next call follows.

Two jobs only:

- :func:`configured_slots`: the slot names, in order. Read again on the next call after the
  file changes, without a restart. A malformed list fails loud, every time it is read.
- :func:`fetch`: one slot's login, good for at least the asked time. It is returned to the
  caller only: never stored, logged or put in an error. There is no other source: when the
  helper can't be reached the call fails with :class:`PiLoginsUnreachable`, naming the
  socket; when it refuses the slot, :class:`PiLoginRefused` carries its plain words.

The socket is the path in ``TEMPER_PI_LOGINS_SOCKET``: the helper's pools door, which serves
only ``token`` and only to the uid temper's run boxes run as. docker-compose.yml mounts its
folder read-only into the server, and each run's box, a copy of the server, inherits it.
"""

from __future__ import annotations

import math
import os
import threading
from pathlib import Path

import yaml

from temper_ai.llm.week_usage import line_path
from temper_ai.shared import pi_host_client

SOCKET_ENV = "TEMPER_PI_LOGINS_SOCKET"
#: Extra time a login must outlast the call it is fetched for.
CALL_MARGIN_S = 300
#: The login validity a caller may ask for (the helper's own range, docs/pi-host-helper.md).
VALIDITY_S_RANGE = pi_host_client.VALIDITY_S_RANGE
#: How long one fetch waits for the helper (its bridge gives up on a token after 30 s).
FETCH_TIMEOUT_S = pi_host_client.TOKEN_TIMEOUT_S


class PiLoginsMisconfigured(ValueError):
    """``pools.logins`` in the pools file is not a list of slot names."""


class PiLoginsUnreachable(RuntimeError):
    """The host helper could not be asked, or gave no usable answer. Not any slot's fault."""


class PiLoginRefused(RuntimeError):
    """The host helper refused this slot; ``why`` is its plain words (they name the slot)."""

    def __init__(self, slot: str, why: str) -> None:
        super().__init__(why)
        self.slot = slot
        self.why = why


_lock = threading.Lock()
#: config dir -> ((path, mtime) of the file read, the slots it listed)
_seen: dict[str, tuple[tuple[str, float] | None, tuple[str, ...]]] = {}


def configured_slots(config_dir: str | Path | None = None) -> list[str]:
    """The pi slots temper's Claude pools use, in the pools file's order. Empty when the file
    lists none (then temper has no Claude login). Raises :class:`PiLoginsMisconfigured` when
    the list is malformed, rather than guessing."""
    path = line_path(config_dir)
    try:
        stamp = (str(path), path.stat().st_mtime) if path else None
    except OSError:
        stamp = None
    key = str(config_dir or "")
    with _lock:
        seen = _seen.get(key)
    if seen is not None and seen[0] == stamp:
        return list(seen[1])
    slots = _read_slots(path) if path else ()
    with _lock:
        _seen[key] = (stamp, slots)
    return list(slots)


def _read_slots(path: Path) -> tuple[str, ...]:
    where = f"{path} pools.logins.slots"
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise PiLoginsMisconfigured(f"{path} can't be read ({exc.__class__.__name__})") from None
    block = raw.get("pools", raw) if isinstance(raw, dict) else None
    if not isinstance(block, dict):
        raise PiLoginsMisconfigured(f"{path} has no pools settings")
    logins = block.get("logins")
    if logins is None:
        return ()
    if not isinstance(logins, dict) or set(logins) != {"slots"}:
        raise PiLoginsMisconfigured(f"{path} pools.logins must hold exactly one key, slots")
    slots = logins["slots"]
    if not isinstance(slots, list):
        raise PiLoginsMisconfigured(f"{where} must be a list of pi slot names")
    for slot in slots:
        if not isinstance(slot, str) or not pi_host_client.SLOT_RE.match(slot):
            raise PiLoginsMisconfigured(f"{where} has {slot!r}, not a pi slot name")
    if len(set(slots)) != len(slots):
        raise PiLoginsMisconfigured(f"{where} names a slot twice")
    return tuple(slots)


def validity_for(call_seconds: float | None) -> int:
    """The login validity to ask for a call that may take ``call_seconds``: the call plus
    CALL_MARGIN_S, within the helper's range (unknown -> the low end). A call longer than the
    range's top gets the top, and may outlive its login."""
    low, high = VALIDITY_S_RANGE
    if call_seconds is None or not math.isfinite(call_seconds) or call_seconds <= 0:
        return low
    return max(low, min(high, math.ceil(call_seconds) + CALL_MARGIN_S))


def socket_path() -> str:
    return (os.environ.get(SOCKET_ENV) or "").strip()


def fetch(slot: str, call_seconds: float | None = None, *, timeout: float = FETCH_TIMEOUT_S) -> str:
    """The current login for pi slot ``slot``, good for at least ``call_seconds`` plus a
    margin. Raises :class:`PiLoginsUnreachable` or :class:`PiLoginRefused`; never falls back
    to another source."""
    path = socket_path()
    if not path:
        raise PiLoginsUnreachable(
            f"temper's Claude logins come from pi through temper-pi-host, and {SOCKET_ENV} "
            f"(its socket) is not set here (docs/pools.md)")
    try:
        return pi_host_client.token_or_raise(path, slot, timeout, validity_for(call_seconds))
    except pi_host_client.HelperUnreachable as exc:
        raise PiLoginsUnreachable(
            f"temper's Claude logins come from pi through temper-pi-host at {path}, "
            f"which is not answering ({exc})") from None
    except pi_host_client.HelperRefused as exc:
        raise PiLoginRefused(slot, str(exc)) from None
