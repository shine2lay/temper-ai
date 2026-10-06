"""When a subscription account's own message can be trusted, and what it says.

A Claude subscription does not always fail the way an API does. When an
account runs out, or its organisation has turned it off, the Claude CLI can
hand back one sentence where the answer should be:

- a limit: "You've hit your session limit · resets 10:50pm (UTC)". Waiting
  fixes it: the account cools until the reset it names.
- a refusal: "Your organization has disabled Claude subscription access for
  Claude Code · Use an Anthropic API key instead, or ask your admin to enable
  access". No wait fixes it: the account is taken out of use.

Either sentence is the account talking, not the model, so it is never an
answer. But a model may well write about limits -- an agent summarising an
incident may quote these very sentences -- and that must neither drop a
healthy account nor fail the agent's step. So a sentence counts only:

- in an error: the call itself reported failure (the CLI's ``is_error``, an
  API 403 ``permission_error``, an ``error`` finish reason). The sentence may
  then sit anywhere in the error's text.
- as the whole result: the result, trimmed, is that sentence alone, and the
  call did no model work (no tool calls, no other content).

Never inside a longer answer. The Claude CLI provider (temper-local) and the
Pi lane read these sentences through this module, so both read them the same
way.
"""

from __future__ import annotations

import re

LIMIT = "limit"
DISABLED = "disabled"

# The CLI's limit banner is "You've hit your <name>[ · resets <when>][ · progress
# saved]", <name> one of: session limit, weekly limit, Opus limit, Sonnet limit,
# Fable limit, usage credit limit. Older CLIs said "Claude AI usage limit
# reached|<epoch>".
_LIMIT_IN_ERROR = re.compile(
    r"you(?:'|\u2019)ve (?:hit|reached) your\b|\b(?:session|weekly) limit\b"
    r"|claude ai usage limit reached",
    re.IGNORECASE,
)
# Alone, the banner is the limit's name and at most a few " \u00b7 " parts after it
# ("resets 10:50pm (UTC)", "progress saved"), nothing else.
_AFTER = r"(?:\s*\u00b7[^\n\u00b7]{1,120}){0,3}\.?"
_LIMIT_ALONE = re.compile(
    r"you(?:'|\u2019)ve (?:hit|reached) your [\w '\u2019-]{0,40}?limit" + _AFTER
    + r"|claude ai usage limit reached(?:\|\d+)?",
    re.IGNORECASE,
)

# The CLI's refusal for an account whose organisation turned subscription
# access off, and the API's words for it (a 403 permission_error). Not every
# "not available for your organization" is one: file sync and projects say so
# too, about themselves.
_DISABLED_IN_ERROR = re.compile(
    r"organi[sz]ation has disabled claude subscription access"
    r"|claude code is not available for your organi[sz]ation"
    r"|oauth_not_allowed_for_organization|\bpermission_error\b",
    re.IGNORECASE,
)
_DISABLED_ALONE = re.compile(
    r"(?:(?:your )?organi[sz]ation has disabled claude subscription access(?: for claude code)?"
    r"|claude code is not available for your organi[sz]ation)" + _AFTER,
    re.IGNORECASE,
)


def account_trouble(text: str | None, *, is_error: bool = False, model_work: bool = False) -> str | None:
    """What a call's text says about its account: ``LIMIT``, ``DISABLED`` or None.

    ``is_error``: the call reported failure, so ``text`` is an error message
    and a signature anywhere in it counts. Otherwise ``text`` is the call's
    result: a signature counts only when the trimmed result is that sentence
    alone and the call did no model work (``model_work``: tool calls or other
    content). Never when the sentence sits inside a longer answer.
    """
    if not text:
        return None
    if is_error:
        if _DISABLED_IN_ERROR.search(text):
            return DISABLED
        if _LIMIT_IN_ERROR.search(text):
            return LIMIT
        return None
    if model_work:
        return None
    alone = text.strip()
    if _DISABLED_ALONE.fullmatch(alone):
        return DISABLED
    if _LIMIT_ALONE.fullmatch(alone):
        return LIMIT
    return None


def is_limit(text: str | None, *, is_error: bool = False, model_work: bool = False) -> bool:
    """Whether the text is an account's limit, under the guard above."""
    return account_trouble(text, is_error=is_error, model_work=model_work) == LIMIT


def is_disabled(text: str | None, *, is_error: bool = False, model_work: bool = False) -> bool:
    """Whether the text is an account refused by its organisation, under the guard above."""
    return account_trouble(text, is_error=is_error, model_work=model_work) == DISABLED
