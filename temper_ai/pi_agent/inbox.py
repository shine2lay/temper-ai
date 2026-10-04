"""What a Pi member is shown at a turn: its messages as one framed batch (R2 B5, B1).

Every header line is Temper's. It starts with a tag drawn fresh for each batch -- nobody who
wrote a message could know it -- and names the real sender, the kind and the message id,
all taken from the ledger, never from a message. Every line of a body is shown after
``| ``, so no line of a body can start like a header, whatever the body says (a body that
types ``Message from the owner`` or even a guessed tag stays visibly inside the message).

A message given again to a retried turn keeps its id and says so (B1).
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence

TAG_BYTES = 4
BODY_PREFIX = "| "


def batch_tag() -> str:
    return secrets.token_hex(TAG_BYTES)


def _plain(text: str, limit: int = 128) -> str:
    """A name or id on one header line: printable, no quotes, bounded."""
    return "".join(c if c.isprintable() and c != '"' else "?" for c in str(text))[:limit]


def sender_label(message: dict) -> str:
    kind = message.get("sender_kind")
    if kind == "member":
        return f'member "{_plain(message.get("sender") or "")}"'
    if kind == "owner":
        return "the owner"
    return "Temper"


def header(message: dict, index: int, count: int, mark: str) -> str:
    parts = [f"{mark} message {index} of {count}", f"id {_plain(message['message_id'], 64)}",
             f"from {sender_label(message)}", f"kind {_plain(message.get('kind') or '', 32)}"]
    if message.get("in_reply_to"):
        parts.append(f"in reply to {_plain(message['in_reply_to'], 64)}")
    if (message.get("delivery_count") or 0) > 1:
        parts.append("given again: an earlier try of this turn did not finish")
    return " · ".join(parts)


def render_batch(batch: Sequence[dict], *, tag: str | None = None, team: bool = False) -> str:
    """The prompt for one turn: every message of the batch, oldest first, framed by Temper.
    It never starts with ``/``, so a batch is never taken for a Pi command."""
    mark = f"[temper:{tag or batch_tag()}]"
    count = len(batch)
    intro = (f"{mark} {count} message{'' if count == 1 else 's'} for you, oldest first. Only "
             f"lines starting with {mark} come from Temper; every line of a message is shown "
             f"after \"{BODY_PREFIX.strip()}\".")
    if team:
        intro += (" To answer a member, use the send_message tool with kind reply and "
                  "in_reply_to set to the message's id.")
    lines = [intro]
    for i, message in enumerate(batch, 1):
        lines.append(header(message, i, count, mark))
        lines += [BODY_PREFIX + line for line in (message.get("body") or "").splitlines() or [""]]
    lines.append(f"{mark} end of messages")
    return "\n".join(lines)
