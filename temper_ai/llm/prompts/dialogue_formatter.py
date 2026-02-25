"""Pure formatting functions for auto-injecting dialogue context into agent prompts.

These functions convert structured dialogue data (lists/dicts) into
human-readable markdown that can be appended to any agent prompt.
"""

# Max characters for dialogue history formatting
DIALOGUE_HISTORY_MAX_CHARS = 8000

# Buffer size reserved for truncation message
TRUNCATION_MESSAGE_BUFFER_CHARS = 30

# Max characters for stage agent outputs formatting
STAGE_AGENT_OUTPUTS_MAX_CHARS = 4000


def _group_history_by_round(history: list) -> dict[int, list[dict]]:  # noqa: long
    """Group valid history entries by round number."""
    rounds: dict[int, list[dict]] = {}
    for entry in history:
        if not isinstance(entry, dict):
            continue
        round_num = entry.get("round", 0)
        rounds.setdefault(round_num, []).append(entry)
    return rounds


def _format_round_text(round_num: int, entries: list[dict]) -> str:
    """Format all entries for a single round into a text block."""
    round_parts: list[str] = []
    for entry in entries:
        agent = entry.get("agent", "unknown")
        output = str(entry.get("output", ""))
        reasoning = str(entry.get("reasoning", ""))
        confidence = entry.get("confidence", "?")
        stance = entry.get("stance", "")
        section = (
            f"### Round {round_num} - {agent}\n"
            f"**Decision:** {output}\n"
            f"**Reasoning:** {reasoning}\n"
            f"**Confidence:** {confidence}\n"
        )
        if stance:
            section += f"**Stance:** {stance}\n"
        round_parts.append(section)
    return "\n".join(round_parts)


def format_dialogue_history(  # scanner: skip-radon
    history: list,
    max_chars: int = DIALOGUE_HISTORY_MAX_CHARS,
) -> str:
    """Format dialogue history as markdown for prompt injection.

    Args:
        history: List of dialogue entries, each with keys:
            agent, round, output, reasoning, confidence, stance (optional)
        max_chars: Maximum characters in output (truncates oldest rounds first)

    Returns:
        Formatted markdown string, or empty string if no valid entries
    """
    if not history:
        return ""
    rounds = _group_history_by_round(history)
    if not rounds:
        return ""
    header = "## Prior Dialogue\n"
    parts: list[str] = []
    total_chars = len(header)
    for round_num in sorted(rounds.keys()):
        round_text = _format_round_text(round_num, rounds[round_num])
        if total_chars + len(round_text) > max_chars:
            if not parts:
                truncated = round_text[
                    : max_chars - total_chars - TRUNCATION_MESSAGE_BUFFER_CHARS
                ]
                parts.append(truncated + "\n*[truncated]*\n")
            else:
                parts.insert(0, "*[Earlier rounds truncated for context limits]*\n")
            break
        parts.append(round_text)
        total_chars += len(round_text)
    if not parts:
        return ""
    return header + "\n".join(parts)


def format_stage_agent_outputs(
    agents: dict,
    max_chars: int = STAGE_AGENT_OUTPUTS_MAX_CHARS,
) -> str:
    """Format current stage agent outputs as markdown.

    Args:
        agents: Dict mapping agent_name to output (str or dict with 'output' key)
        max_chars: Maximum characters in output

    Returns:
        Formatted markdown string, or empty string if no valid entries
    """
    if not agents:
        return ""

    parts: list[str] = []
    total_chars = 0
    header = "## Prior Agent Outputs\n"
    total_chars += len(header)

    for agent_name, output in agents.items():
        if isinstance(output, dict):
            text = str(output.get("output", output))
        else:
            text = str(output)

        section = f"### {agent_name}\n{text}\n"

        if total_chars + len(section) > max_chars:
            parts.append("*[Additional agent outputs truncated]*\n")
            break
        parts.append(section)
        total_chars += len(section)

    if not parts:
        return ""

    return header + "\n".join(parts)
