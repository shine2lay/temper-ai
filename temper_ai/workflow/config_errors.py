"""Structured config validation errors with fuzzy-match suggestions.

Provides ``ConfigError`` dataclass for rich, user-friendly error
reporting and ``suggest_name()`` for typo recovery via
``difflib.get_close_matches``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import get_close_matches

# Fuzzy match cutoff — 0.6 catches common typos like
# "reseracher" → "researcher", "Calculater" → "Calculator"
_FUZZY_CUTOFF = 0.6


@dataclass
class ConfigError:
    """A single config validation error with location and fix suggestions."""

    code: str
    message: str
    location: str
    suggestion: str | None = None
    available: list[str] = field(default_factory=list)

    def format(self, index: int | None = None) -> str:
        """Format as a human-readable block for terminal/log output."""
        prefix = f"  {index}. " if index is not None else "  "
        lines = [f"{prefix}{self.message}"]
        lines.append(f"     Location:  {self.location}")
        if self.suggestion:
            lines.append(f"     Suggestion: {self.suggestion}")
        if self.available:
            lines.append(f"     Available:  {', '.join(self.available)}")
        return "\n".join(lines)


def suggest_name(name: str, available: list[str]) -> str | None:
    """Fuzzy-match *name* against *available* options.

    Returns a human-readable suggestion string like
    ``"Did you mean 'researcher'?"`` or ``None`` when no close match
    is found.
    """
    if not available:
        return None
    matches = get_close_matches(name, available, n=1, cutoff=_FUZZY_CUTOFF)
    return f"Did you mean '{matches[0]}'?" if matches else None


def format_error_report(errors: list[ConfigError]) -> str:
    """Format a list of ConfigErrors into a numbered report string."""
    header = f"Config validation failed ({len(errors)} error(s)):\n"
    blocks = [e.format(index=i + 1) for i, e in enumerate(errors)]
    return header + "\n\n".join(blocks)
