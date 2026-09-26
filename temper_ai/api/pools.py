"""What each provider's credential pool can serve right now.

    GET /api/pools    every pooled provider: per model family, its slots and when each cools down

A caller about to start long work asks first. When every slot for its model is cooled, the work
stops at its first model call: b009 on 2026-09-24 started with every opus slot rate limited, its
plan step died on "token pool exhausted", and the run went on as if it had built (gap 17). The
cooldowns live in this process, which is the only place that learns of each refusal. Labels and
times only, never a credential. A provider with a single credential has no pool and is not listed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from temper_ai.llm.token_pool import TokenPool

router = APIRouter(prefix="/api/pools", tags=["pools"])


@router.get("")
def list_pools() -> dict[str, Any]:
    from temper_ai.api.routes import _state

    pools = []
    for provider, llm in sorted(_state().llm_providers.items()):
        pool = getattr(llm, "_pool", None)
        if isinstance(pool, TokenPool):
            pools.append({"provider": provider, "name": pool.name, "size": len(pool),
                          "families": pool.state()})
    return {"pools": pools}
