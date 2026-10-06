"""Nothing token-like leaves a Pi run (M4 ADR-M4-12, SW-52).

Everything that leaves a run -- a member's answer and messages, files and git content brought
out (the trial branch), version records, the run's done record, and the logs -- is scanned
for the run's login tokens before it goes. A hit is refused and reported by rule name, path
and count only: the matched text is never printed, stored or logged.

Two kinds of rule:

* ``run_token`` -- the exact tokens this process handed to the run's boxes (and the account
  ids inside them), remembered where the hand-off happens (:func:`remember`, box.py);
* shapes -- an Anthropic OAuth access or refresh token, or an API key, whoever's it is.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field

from temper_ai.pi_agent.route.model import INVALID_MESSAGE
from temper_ai.pi_agent.route.router import Refusal

#: Shorter strings are never remembered as a run's token (an id fragment would match prose).
MIN_SECRET_LENGTH = 16
#: The rules by name: what a hit reports.
SHAPES: dict[str, re.Pattern[str]] = {
    "anthropic_oauth_access_token": re.compile(r"sk-ant-oat\d{2}-[A-Za-z0-9_\-]{20,}"),
    "anthropic_oauth_refresh_token": re.compile(r"sk-ant-ort\d{2}-[A-Za-z0-9_\-]{20,}"),
    "anthropic_api_key": re.compile(r"sk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_\-]{20,}"),
}
RUN_TOKEN = "run_token"
WITHHELD = "[withheld: a login token]"

_LOCK = threading.Lock()
_SECRETS: set[str] = set()


def remember(*secrets: str | None) -> None:
    """Remember tokens this process handed to a run's box (and ids inside them)."""
    with _LOCK:
        for s in secrets:
            if isinstance(s, str) and len(s) >= MIN_SECRET_LENGTH:
                _SECRETS.add(s)


def forget_all() -> None:
    """Drop every remembered token (tests)."""
    with _LOCK:
        _SECRETS.clear()


def _secrets() -> tuple[str, ...]:
    with _LOCK:
        return tuple(_SECRETS)


@dataclass
class Hits:
    """What a scan found: rule names and counts, and where (paths) -- never the text."""

    rules: dict[str, int] = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, record: dict | None) -> Hits:
        """The hits a stored :meth:`record` holds."""
        record = record or {}
        return cls(rules=dict(record.get("rules") or {}), paths=list(record.get("paths") or []))

    def __bool__(self) -> bool:
        return bool(self.rules)

    def add(self, rule: str, count: int, where: str | None = None) -> None:
        self.rules[rule] = self.rules.get(rule, 0) + count
        if where:
            where = withhold(where)  # a file whose name is the token is named without it
            if where not in self.paths:
                self.paths.append(where)

    def merge(self, other: Hits) -> Hits:
        for rule, n in other.rules.items():
            self.add(rule, n)
        for p in other.paths:
            if p not in self.paths:
                self.paths.append(p)
        return self

    def words(self) -> str:
        rules = ", ".join(f"{r} x{n}" for r, n in sorted(self.rules.items()))
        where = f" in {', '.join(self.paths[:10])}" if self.paths else ""
        return f"{sum(self.rules.values())} login-token match(es) ({rules}){where}"

    def record(self) -> dict:
        return {"refused": True, "rules": dict(sorted(self.rules.items())),
                "paths": self.paths[:50]}


def scan(text: str | bytes | None, where: str | None = None) -> Hits:
    """The token rules' hits in ``text`` (bytes are read as Latin-1: tokens are ASCII)."""
    hits = Hits()
    if not text:
        return hits
    if isinstance(text, bytes):
        text = text.decode("latin-1")
    for secret in _secrets():
        n = text.count(secret)
        if n:
            hits.add(RUN_TOKEN, n, where)
    for name, pattern in SHAPES.items():
        n = len(pattern.findall(text))
        if n:
            hits.add(name, n, where)
    return hits


def scan_all(items: Iterable[tuple[str | None, str | bytes | None]]) -> Hits:
    """One scan over ``(where, text)`` pairs."""
    hits = Hits()
    for where, text in items:
        hits.merge(scan(text, where))
    return hits


def scan_obj(obj: object, where: str | None = None) -> Hits:
    """Every string inside a JSON-shaped value (keys too)."""
    hits = Hits()

    def walk(v: object) -> None:
        if isinstance(v, str):
            hits.merge(scan(v, where))
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(k)
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)

    walk(obj)
    return hits


class TokenRefusal(Refusal):
    """A member's call refused because its arguments hold a login token: nothing of it is
    stored, not even in the refusal's audit entry."""


def refuse_tokens(payload: object) -> None:
    """Refuse a member's message or review-tool call whose arguments hold a login token
    (SW-52): it never reaches another member, the owner or the run's records. The refusal
    names the rules only."""
    hits = scan_obj(payload)
    if hits:
        raise TokenRefusal(INVALID_MESSAGE, f"refused: it holds {hits.words()}; nothing was "
                           "sent or recorded. Never put a login token in a message or a note")


def withhold(text: str) -> str:
    """``text`` with every rule's match replaced by :data:`WITHHELD` (for logs only)."""
    for secret in _secrets():
        text = text.replace(secret, WITHHELD)
    for pattern in SHAPES.values():
        text = pattern.sub(WITHHELD, text)
    return text


class LogGuard(logging.Filter):
    """A handler filter: a log record's message leaves with every token withheld."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad record is the logging module's to report
            return True
        guarded = withhold(message)
        if guarded != message:
            record.msg, record.args = guarded, None
        if record.exc_info and not record.exc_text:
            # The handler's formatter keeps a filled-in exc_text: the traceback leaves with
            # every token withheld too.
            record.exc_text = withhold(logging.Formatter().formatException(record.exc_info))
        elif record.exc_text:
            record.exc_text = withhold(record.exc_text)
        return True


def guard_logs(logger: logging.Logger | None = None) -> None:
    """Put :class:`LogGuard` on every handler of ``logger`` (the root by default), once."""
    target = logger or logging.getLogger()
    for handler in target.handlers:
        if not any(isinstance(f, LogGuard) for f in handler.filters):
            handler.addFilter(LogGuard())
