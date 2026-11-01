"""What a database error may say once its text leaves temper.

On Postgres a database error's text carries the server's DETAIL: the whole
failing row for not-null and check failures ("Failing row contains (...)") and
the key values for unique and foreign-key failures ("Key (col)=(value)").
SQLAlchemy's text adds the failing statement and its parameters, and a data
exception's primary message quotes the input it could not read. Log lines and
error replies outlive the rows, so text that leaves temper uses the safe text
built here instead:

* the driver's exception class and the SQLSTATE;
* the schema, table, column, datatype and constraint names the server reports;
* the server's primary message, with every double-quoted span that is not one
  of those names withheld, and every byte sequence it shows in hex.

Never the DETAIL, HINT or CONTEXT, the statement or its parameters. Another
driver's error (SQLite's) keeps its message's first line, quoted spans withheld:
SQLite names tables and columns, not values, but a syntax error quotes the
token it stopped at, which can be a literal.

Nothing here changes an exception: code inside temper keeps the whole error.
Classes are looked up only among modules already imported (an error object
implies its module), so importing this loads neither SQLAlchemy nor a driver.
Where the safe text is used: docs/database-error-text.md.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Collection, Iterator

WITHHELD = "<withheld>"

# How Postgres shows bytes it could not read (22021, 22P05): "0xe2 0x80", unquoted.
_BYTE_SEQUENCE = re.compile(r"\b0x[0-9A-Fa-f]{2}(?: 0x[0-9A-Fa-f]{2})*\b")

# Where SQLAlchemy's PendingRollbackError starts quoting the earlier error's whole text.
_EARLIER_ERROR = " Original exception was: "

# The names the server reports with an error, and how the safe text labels them.
_DIAG_NAMES = (
    ("schema_name", "schema"),
    ("table_name", "table"),
    ("column_name", "column"),
    ("datatype_name", "datatype"),
    ("constraint_name", "constraint"),
)

# What else the server sends with an error; any of it may hold row values.
_DIAG_EXTRAS = ("message_detail", "message_hint", "context", "internal_query")


def text_without_database_values(exc: BaseException) -> str:
    """``exc``'s text as it may leave temper (a log line, an error reply).

    A database error gives its safe text. Any other exception keeps its own
    text, except where it quotes a database error from its chain (a wrapper
    often embeds ``str(err)``): that part is withheld the same way.
    """
    safe = _safe_text(exc)
    if safe is not None:
        return safe
    return withhold_database_values(_text_of(exc), exc)


def error_line_without_database_values(exc: BaseException) -> str:
    """``"<class>: <text>"``, the line a status page or a reply shows for ``exc``, its text
    as ``text_without_database_values`` gives it."""
    return f"{type(exc).__name__}: {text_without_database_values(exc)}"


def withhold_database_values(text: str, exc: BaseException) -> str:
    """``text`` with every database error of ``exc``'s chain given its safe text.

    For text built elsewhere: a traceback, or a message that embedded an error.
    The chain is ``exc``, its causes and contexts (a suppressed one too), a
    SQLAlchemy error's driver error and an exception group's members. Each
    error's own texts (its str, its message, the driver's pgerror), trimmed, as
    they are or escaped the way repr shows them, are swapped whole for its safe
    text; its DETAIL, HINT, CONTEXT and internal query are withheld wherever
    else they show. A text spread over several lines is found with a margin
    before each line after the first too, as an exception group's traceback
    shows its members ("    | ").
    """
    swaps = _swaps(exc)
    if not swaps:
        return text
    raws = sorted(swaps, key=len, reverse=True)
    pattern = re.compile("|".join(f"({_as_shown(raw)})" for raw in raws))

    def replacement(found: re.Match[str]) -> str:
        return swaps[raws[(found.lastindex or 1) - 1]]

    return pattern.sub(replacement, text)


def withhold_database_values_in_body(body: object, exc: BaseException) -> object:
    """A reply body (a string, or dicts and lists of them) with ``withhold_database_values``
    applied to every string in it, however nested; keys and other values as they are."""
    if isinstance(body, str):
        return withhold_database_values(body, exc)
    if isinstance(body, dict):
        return {key: withhold_database_values_in_body(value, exc) for key, value in body.items()}
    if isinstance(body, list | tuple):
        return [withhold_database_values_in_body(value, exc) for value in body]
    return body


def carries_database_error(exc: BaseException) -> bool:
    """Whether a database error is anywhere in ``exc``'s chain (``exc`` itself included)."""
    return any(_safe_text(link) is not None for link in _chain(exc))


def _safe_text(exc: BaseException) -> str | None:
    """The safe text of one database error; None for any other exception."""
    if _is_instance(exc, "sqlalchemy.exc", "StatementError"):
        return _statement_error_text(exc)
    if _is_instance(exc, "sqlalchemy.exc", "PendingRollbackError"):
        return _pending_rollback_text(exc)
    if _is_instance(exc, "psycopg2", "Error"):
        return _postgres_error_text(exc)
    if _is_instance(exc, "sqlite3", "Error"):
        return _first_line_without_values(_text_of(exc))
    return None


def _statement_error_text(exc: BaseException) -> str:
    """SQLAlchemy's error: the driver error's class and safe text, no statement or parameters."""
    orig = getattr(exc, "orig", None)
    if not isinstance(orig, BaseException):
        # SQLAlchemy's own words, its statement left out.
        return _first_line_without_values(_message_of(exc))
    if not _is_instance(exc, "sqlalchemy.exc", "DBAPIError"):
        # Raised before the driver was reached (a bind parameter's own failure): temper's
        # own error, untouched like any other, and its traceback shows it anyway.
        text = _text_of(orig)
    else:
        # A known driver's safe text; any other driver's first line, quotes withheld.
        text = _safe_text(orig) or _first_line_without_values(_text_of(orig))
    return f"({type(orig).__module__}.{type(orig).__name__}) {text}"


def _pending_rollback_text(exc: BaseException) -> str:
    """SQLAlchemy's 'rolled back due to a previous exception' quotes that whole earlier
    error and keeps no link to it: its first line only, quotes withheld."""
    message = _message_of(exc)
    head, found, earlier = message.partition(_EARLIER_ERROR)
    if not found:
        return message
    return f"{head}{found}{_first_line_without_values(earlier)}"


def _postgres_error_text(exc: BaseException) -> str:
    """The server's primary message with its values withheld, then SQLSTATE and the names."""
    diag = getattr(exc, "diag", None)
    names = [(label, value) for field, label in _DIAG_NAMES if (value := _diag_field(diag, field))]
    primary = _diag_field(diag, "message_primary")
    if primary:
        text = _withhold_values(primary, keep={value for _label, value in names})
    else:
        # A client-side error (no server message): the driver's first line, quotes withheld.
        text = _first_line_without_values(_text_of(exc))
    sqlstate = getattr(exc, "pgcode", None) or _diag_field(diag, "sqlstate")
    facts = ([f"SQLSTATE {sqlstate}"] if sqlstate else []) + [f"{label}={value}" for label, value in names]
    return f"{text} ({', '.join(facts)})" if facts else text


def _withhold_values(text: str, keep: Collection[str] = ()) -> str:
    """``text`` with what may be a value withheld: every double-quoted span but the
    names in ``keep``, and every byte sequence shown in hex.

    Postgres quotes names and values alike and does not escape a quote inside a
    value, so everything from the first quote that does not open a kept name to
    the last such quote is withheld as one span; a lone quote takes the rest.
    """
    kept: list[tuple[int, int]] = []
    if keep:
        names = re.compile("|".join(re.escape(f'"{name}"') for name in sorted(keep, key=len, reverse=True)))
        kept = [found.span() for found in names.finditer(text)]
    quotes = [at for at, char in enumerate(text) if char == '"' and not any(start <= at < end for start, end in kept)]
    if quotes:
        end = quotes[-1] + 1 if len(quotes) > 1 else len(text)
        text = f'{text[:quotes[0]]}"{WITHHELD}"{text[end:]}'
    return _BYTE_SEQUENCE.sub(WITHHELD, text)


def _first_line_without_values(text: str) -> str:
    lines = text.strip().splitlines()
    return _withhold_values(lines[0] if lines else "")


def _swaps(exc: BaseException) -> dict[str, str]:
    """Each raw text of a database error in the chain, and what replaces it."""
    swaps: dict[str, str] = {}
    extras: dict[str, str] = {}
    for link in _chain(exc):
        safe = _safe_text(link)
        if safe is None:
            continue
        for raw in _shown_forms(_own_texts(link)):
            if raw != safe:
                swaps.setdefault(raw, safe)
        if _is_instance(link, "psycopg2", "Error"):
            diag = getattr(link, "diag", None)
            values = [value for field in _DIAG_EXTRAS if (value := _diag_field(diag, field))]
            for raw in _shown_forms(values):
                extras.setdefault(raw, WITHHELD)
    for raw, replacement in extras.items():
        swaps.setdefault(raw, replacement)
    return swaps


def _own_texts(exc: BaseException) -> list[str]:
    """The texts a database error shows: its str, its message and the driver's pgerror."""
    pgerror = getattr(exc, "pgerror", None) if _is_instance(exc, "psycopg2", "Error") else None
    return [_text_of(exc), _message_of(exc), pgerror if isinstance(pgerror, str) else ""]


def _shown_forms(texts: Collection[str]) -> set[str]:
    """Each text trimmed, as it is and escaped the way repr shows it inside quotes."""
    forms: set[str] = set()
    for text in texts:
        form = text.strip()
        if form:
            forms.update((form, repr(form)[1:-1]))
    return forms


def _as_shown(raw: str) -> str:
    """A pattern for ``raw``, with room for a margin before each of its lines after the first."""
    return r"\n[ \t|]*".join(re.escape(line) for line in raw.split("\n"))


def _chain(exc: BaseException) -> Iterator[BaseException]:
    """``exc``, its causes and contexts (a suppressed context too), a SQLAlchemy error's
    driver error and an exception group's members: each once, cycles included."""
    seen: set[int] = set()
    pending: list[object] = [exc]
    while pending:
        link = pending.pop()
        if not isinstance(link, BaseException) or id(link) in seen:
            continue
        seen.add(id(link))
        yield link
        pending += [link.__cause__, link.__context__]
        if _is_instance(link, "sqlalchemy.exc", "StatementError"):
            pending.append(getattr(link, "orig", None))
        if isinstance(link, BaseExceptionGroup):
            pending += list(link.exceptions)


def _is_instance(exc: BaseException, module: str, name: str) -> bool:
    """Whether ``exc`` is an instance of ``module.name``, looked up only if already imported."""
    found = getattr(sys.modules.get(module), name, None)
    return isinstance(found, type) and isinstance(exc, found)


def _diag_field(diag: object, field: str) -> str | None:
    value = getattr(diag, field, None) if diag is not None else None
    return value if isinstance(value, str) and value else None


def _message_of(exc: BaseException) -> str:
    """An exception's message argument (SQLAlchemy keeps the statement out of it)."""
    first = exc.args[0] if exc.args else ""
    return first if isinstance(first, str) else ""


def _text_of(exc: BaseException) -> str:
    try:
        return str(exc)
    except Exception:  # noqa: BLE001 - a broken __str__ must not break the line that shows it
        return f"<{type(exc).__name__}: its text could not be read>"
