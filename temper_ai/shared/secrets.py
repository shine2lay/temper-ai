"""Blank out anything that looks like a password, a key or a token.

Used wherever text from outside is about to be shown to a model or posted:
a container's log, a commit message, an issue's text. It is a last line, not
a licence to pass secrets around — nothing should be reading them in the
first place — but "never print a secret" has to hold even when something
else slipped.

``scripts/roamee_reader.py`` keeps the same rules in its own copy on purpose:
it runs on the host with plain ``python3`` and nothing of temper installed,
so it cannot import this. ``tests/test_shared/test_secrets.py`` holds the two
to the same answers.
"""

from __future__ import annotations

import re
from typing import Any

BLANK = "[hidden]"

# user:password@host in any connection string
_DSN = re.compile(r"(?i)\b([a-z+]+://[^\s:@/]+):([^\s@/]+)@")
# NAME=value / NAME: value, where the name says what the value is
# The name may stand alone (`password=…`) or carry a prefix (`db_password=…`).
_ASSIGNED = re.compile(
    r"(?i)\b([a-z0-9_.\-]*(?:password|passwd|secret|token|api[_-]?key|apikey|access[_-]?key"
    # the closing quote of a JSON key: {"secret": "..."} counts too
    r"|private[_-]?key|credential|session|cookie|auth[a-z_]*))\b([\"']?\s*[=:]\s*)"
    # not `authorization: Bearer <token>`: that is the next rule's, and it
    # would otherwise blank the word Bearer and leave the token standing.
    r"(?!(?:bearer|basic)\b)(\"[^\"]*\"|'[^']*'|\S+)"
)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]{8,}")
# the shapes of the keys this box actually holds
_KNOWN_SHAPES = re.compile(
    r"\b("
    r"sk-[A-Za-z0-9._\-]{12,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|xox[abposr]-[A-Za-z0-9-]{10,}"
    r"|lin_(?:api|oauth)_[A-Za-z0-9]{10,}"
    r"|eyJ[A-Za-z0-9._\-]{20,}"
    r"|AIza[A-Za-z0-9._\-]{20,}"
    r")"
)


def blank_secrets(text: Any) -> str:
    """The text with passwords, keys and tokens replaced by ``[hidden]``."""
    out = str(text or "")
    out = _DSN.sub(r"\1:" + BLANK + "@", out)
    out = _ASSIGNED.sub(lambda m: f"{m.group(1)}{m.group(2)}{BLANK}", out)
    out = _BEARER.sub(lambda m: f"{m.group(1)} {BLANK}", out)
    return _KNOWN_SHAPES.sub(BLANK, out)
