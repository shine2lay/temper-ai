"""What each provider's credential pool can serve right now.

    GET /api/pools    every pooled provider: per model family, its slots and when each cools down;
                      and each Claude account's week: the share used, when that was seen, when it
                      resets, and whether it is at or above the week line

A caller about to start long work asks first. When every slot for its model is cooled, the work
stops at its first model call: b009 on 2026-09-24 started with every opus slot rate limited, its
plan step died on "token pool exhausted", and the run went on as if it had built (gap 17). The
cooldowns live in this process, which is the only place that learns of each refusal. Labels and
times only, never a credential. A provider with a fixed credential (an API key) has no pool and is
not listed. The Claude accounts are pi's slots the pools file lists now (temper_ai.llm.pi_logins).

The week figures come only from calls made through the claude provider (temper_ai.llm.week_usage),
so an account temper hasn't used through the claude tool lately shows none (``week_used`` null),
which counts as under the line.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from temper_ai.llm import pi_logins, week_usage
from temper_ai.llm.token_pool import TokenPool

router = APIRouter(prefix="/api/pools", tags=["pools"])


@router.get("")
def list_pools() -> dict[str, Any]:
    from temper_ai.api.routes import _state

    pools = []
    try:
        for provider, llm in sorted(_state().llm_providers.items()):
            pool_now = getattr(llm, "pool_now", None)
            pool = pool_now() if callable(pool_now) else getattr(llm, "_pool", None)
            if isinstance(pool, TokenPool):
                pools.append({"provider": provider, "name": pool.name, "size": len(pool),
                              "families": pool.state()})
        labels = pi_logins.configured_slots()
    except pi_logins.PiLoginsMisconfigured as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None
    line = week_usage.week_line()
    return {"pools": pools, "week_line": line, "accounts": week_usage.accounts(labels, line=line)}
