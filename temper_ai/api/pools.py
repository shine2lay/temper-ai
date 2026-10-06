"""What each provider's credential pool can serve right now.

    GET /api/pools    every pooled provider: per model family, its slots and when each cools down;
                      and each Claude account's week: the share used, when that was seen, when it
                      resets, and whether it is at or above the week line

A caller about to start long work asks first. When every slot for its model is cooled, the work
stops at its first model call: b009 on 2026-09-24 started with every opus slot rate limited, its
plan step died on "token pool exhausted", and the run went on as if it had built (gap 17). The
cooldowns live in this process, which is the only place that learns of each refusal. Labels and
times only, never a credential. A provider with a single credential has no pool and is not listed.

The week figures come only from calls made through the claude provider (temper_ai.llm.week_usage),
so an account temper hasn't used through the claude tool lately shows none (``week_used`` null),
which counts as under the line.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from temper_ai.llm import week_usage
from temper_ai.llm.token_pool import TokenPool, named_tokens_from_env

router = APIRouter(prefix="/api/pools", tags=["pools"])

# The Claude accounts every pool and the claude provider draw on, by the variables they come from.
CLAUDE_TOKENS_ENV = "CLAUDE_CODE_OAUTH_TOKEN"  # noqa: S105 - name, not a secret


@router.get("")
def list_pools() -> dict[str, Any]:
    from temper_ai.api.routes import _state

    pools = []
    for provider, llm in sorted(_state().llm_providers.items()):
        pool = getattr(llm, "_pool", None)
        if isinstance(pool, TokenPool):
            pools.append({"provider": provider, "name": pool.name, "size": len(pool),
                          "families": pool.state()})
    line = week_usage.week_line()
    labels = [n.label for n in named_tokens_from_env(CLAUDE_TOKENS_ENV)]
    return {"pools": pools, "week_line": line, "accounts": week_usage.accounts(labels, line=line)}
