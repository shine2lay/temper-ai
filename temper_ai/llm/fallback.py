"""What an agent calls when its own model is out of capacity.

An agent names its provider and model. When that model cannot take the call
-- a rate or usage limit, every pooled subscription cooling, an overload --
the call goes to the next entry of the agent's `fallback` list instead, and so
on down the list:

    agent:
      provider: anthropic
      model: claude-opus-5-5
      fallback:
        - claude-sonnet-5              # same provider, another model
        - provider: openai             # another provider altogether
          model: gpt-5.6-luna
          provider_config: {effort: medium}

The provider's own rollover comes first: a pooled provider already moves a
limited call to its next subscription (temper_ai.llm.token_pool). The list is
for when that has run out -- in practice the weekly allowance of one model
family spent on every account at once, which a rollover between accounts
cannot fix and which, before this, failed the node.

Only a capacity failure moves down the list. A bad request, an auth failure or
a timeout would fail the same way on the next model, or is a fault worth
seeing, so it is raised as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from temper_ai.llm.token_pool import PoolExhausted

# Statuses that mean "not this model, not now": a rate or usage limit (429) and
# Anthropic's overload (529).
CAPACITY_STATUSES = frozenset({429, 529})

# How a capacity failure reads when it arrives without a status -- the Codex
# transport raises one as "Codex endpoint returned HTTP 429: ...", and a
# provider may wrap the HTTP error in its own. Matched lower-case.
_CAPACITY_TEXT = (
    "rate limit",
    "rate_limit",
    "usage limit",
    "usage_limit",
    "too many requests",
    "overloaded",
    "pool exhausted",
    "quota exceeded",
    "quota reached",
    "insufficient_quota",
    "hit your limit",
    "limit reached",
    "credit balance is too low",
    "http 429",
    "http 529",
)

_ENTRY_KEYS = frozenset({"provider", "model", "provider_config"})


@dataclass(frozen=True)
class FallbackTarget:
    """One entry of an agent's fallback list.

    `provider` None is the agent's own provider; `model` None is the default
    model of whichever provider that is. `provider_config` is laid over the
    agent's own, key by key, so an entry states only what differs.
    """

    provider: str | None = None
    model: str | None = None
    provider_config: dict[str, Any] | None = None

    def describe(self, own_provider: str) -> str:
        return f"{self.provider or own_provider}/{self.model or 'default model'}"


def parse_fallback(raw: Any) -> list[FallbackTarget]:
    """An agent's `fallback:` setting as targets, or ValueError saying what is wrong.

    Each entry is a model name (same provider) or a mapping of `provider`,
    `model` and `provider_config`, of which `provider` or `model` must be given.
    """
    if raw is None:
        return []
    if isinstance(raw, (str, dict)):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError(f"fallback must be a list, not {type(raw).__name__}")
    targets: list[FallbackTarget] = []
    for i, entry in enumerate(raw):
        where = f"fallback[{i}]"
        if isinstance(entry, str):
            if not entry.strip():
                raise ValueError(f"{where} is an empty model name")
            targets.append(FallbackTarget(model=entry.strip()))
            continue
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be a model name or a mapping, not {type(entry).__name__}")
        unknown = sorted(set(entry) - _ENTRY_KEYS)
        if unknown:
            raise ValueError(
                f"{where} has unknown key(s) {', '.join(unknown)}; "
                f"allowed: provider, model, provider_config"
            )
        provider, model = entry.get("provider"), entry.get("model")
        config = entry.get("provider_config")
        for key, value in (("provider", provider), ("model", model)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{where}.{key} must be a non-empty string")
        if not provider and not model:
            raise ValueError(f"{where} names neither a provider nor a model")
        if config is not None and not isinstance(config, dict):
            raise ValueError(f"{where}.provider_config must be a mapping")
        targets.append(FallbackTarget(
            provider=provider.strip() if provider else None,
            model=model.strip() if model else None,
            provider_config=dict(config) if config else None,
        ))
    return targets


def _status_of(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def _reads_as_capacity(text: str) -> bool:
    lowered = text.lower()
    return any(p in lowered for p in _CAPACITY_TEXT)


def is_capacity_error(exc: BaseException) -> bool:
    """Whether this failure means the model is out of capacity, not that the call is wrong.

    A status, when the error carries one, decides -- except Anthropic's 400 for
    an API account out of credit, which is a spent allowance in all but name.
    Without a status the message decides.
    """
    if isinstance(exc, PoolExhausted):
        return True
    status = _status_of(exc)
    if status is not None:
        if status in CAPACITY_STATUSES:
            return True
        return status == 400 and "credit balance is too low" in str(exc).lower()
    return _reads_as_capacity(str(exc))
