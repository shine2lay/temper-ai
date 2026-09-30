"""How hard an agent asked the model to think, and who can hear it.

`effort` is the one dial an agent config has over thinking. It costs money
-- thinking is billed as output -- so it is set deliberately, and a provider
that cannot pass it on must say so rather than drop it: for three months every
`effort:` line aimed at the Claude Code CLI did nothing at all, and nothing
anywhere said so.

Each provider declares the levels it can actually ask for in `HONOURS_EFFORT`.
An empty tuple means the provider has no effort dial at all. `temper check`
reads those declarations and names every agent whose setting goes nowhere.
"""

from __future__ import annotations

#: Every level an agent config may name, weakest first. The names are temper's
#: own; each provider translates them into whatever its model understands (a
#: token budget, a CLI flag, an API field).
EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")


def normalise(effort: object) -> str | None:
    """`effort` as a known level, or None when it is unset.

    Raises ValueError on a level nobody could honour -- a typo in a config is
    worth failing on, because the silent alternative is a setting that reads
    like a control and is not one.
    """
    if effort is None or effort == "":
        return None
    level = str(effort).strip().lower()
    if level not in EFFORT_LEVELS:
        raise ValueError(
            f"unknown effort '{effort}'; use one of {', '.join(EFFORT_LEVELS)}"
        )
    return level


def unhonoured(provider_name: str, honours: tuple[str, ...], effort: object) -> str | None:
    """Why this effort goes nowhere on this provider, or None when it lands.

    The message is the whole point of the check, so it says what was asked,
    who was asked, and what that provider can do instead.
    """
    if effort is None or effort == "":
        return None
    level = str(effort).strip().lower()
    if level in honours:
        return None
    if not honours:
        return (
            f"effort: {level} is dropped — the {provider_name} provider has no "
            f"effort dial, so the model is asked for nothing in particular"
        )
    if level not in EFFORT_LEVELS:
        return (
            f"effort: {level} is not an effort level; the {provider_name} "
            f"provider takes {', '.join(honours)}"
        )
    return (
        f"effort: {level} is dropped — the {provider_name} provider takes "
        f"{', '.join(honours)}"
    )
