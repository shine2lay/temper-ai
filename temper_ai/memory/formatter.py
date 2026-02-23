"""Format memory search results into markdown for prompt injection."""

from __future__ import annotations

from collections import defaultdict

from temper_ai.memory._schemas import MemorySearchResult
from temper_ai.memory.constants import (
    MAX_MEMORY_CONTEXT_CHARS,
    TRUNCATION_SUFFIX,
    TRUNCATION_SUFFIX_LEN,
)


def format_memory_context(
    result: MemorySearchResult,
    max_chars: int = MAX_MEMORY_CONTEXT_CHARS,
) -> str:
    """Format search results as markdown grouped by memory type.

    Output:
        # Relevant Memories

        ## Episodic
        - [0.92] Previous research found OAuth2 preferred...

        ## Procedural
        - [0.88] For fintech products, always include...
    """
    if not result.entries:
        return ""

    grouped: dict[str, list[str]] = defaultdict(list)
    for entry in sorted(result.entries, key=lambda e: e.relevance_score, reverse=True):
        label = entry.memory_type.replace("_", " ").title()
        line = f"- [{entry.relevance_score:.2f}] {entry.content}"
        grouped[label].append(line)

    sections: list[str] = []
    for type_label, lines in grouped.items():
        section = f"## {type_label}\n" + "\n".join(lines)
        sections.append(section)

    body = "\n\n".join(sections)
    header = "# Relevant Memories\n\n"
    full = header + body

    if len(full) > max_chars:
        return full[: max_chars - TRUNCATION_SUFFIX_LEN] + TRUNCATION_SUFFIX
    return full
