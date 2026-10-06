"""The longest owner texts the server takes where more than one part checks them (M3 E13).

The cancel route checks a cancel's reason for every run, with the Pi switch on or off; the
Team page's stop answers take words of the same length. One number for both, here, so the
switched-off server never imports the Pi agent package's modules to know it.
"""

from __future__ import annotations

#: A cancel's reason, and the words given with a team's stop (M3 E13, E18).
STOP_REASON_MAX_CHARS = 2000


def too_long(what: str, size: int, limit: int) -> str:
    """The refusal for an owner text over its limit, e.g. ``the reason is too long (2345
    characters; at most 2000)``."""
    return f"{what} is too long ({size} characters; at most {limit})"
