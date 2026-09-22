"""A credential spent on one model still has its other allowances.

The subscription's weekly ceiling is per model family. The pool used to cool the credential
itself, so when the build loops spent the fable allowance every slot was marked cooling until
the weekly reset -- four days out -- and opus, with its own untouched allowance on the same
accounts, was refused without a request being made:

    token_pool: anthropic-oauth: slot 0 cooled (rate limit) until 2026-09-26 14:00Z
    token_pool: anthropic-oauth: slot 1 cooled (rate limit) until 2026-09-26 19:00Z
    ...later, asking for opus, no 429 in the log at all:
    token_pool: anthropic-oauth: sticky slot 1 is cooling -- failing over
    Workflow 'epd_measure' completed: status=failed, cost=$0.0000, tokens=0

Recovering needed a server restart, because cooldowns are in-memory.
"""

import time

import pytest

from temper_ai.llm.token_pool import ANY_MODEL, PoolExhausted, TokenPool, model_family

TOKENS = ["tok-a", "tok-b"]
HOUR = 3600.0


def pool() -> TokenPool:
    return TokenPool(name="test-pool", tokens=list(TOKENS))


@pytest.mark.parametrize("model,expected", [
    ("claude-opus-5", "opus"),
    ("claude-opus-4-5-20250101", "opus"),
    ("claude-fable-5-1", "fable"),
    ("claude-sonnet-5", "sonnet"),
    ("claude-3-5-haiku-20241022", "haiku"),
    ("some-future-model", "some-future-model"),
    (None, ANY_MODEL),
])
def test_a_model_id_names_the_ceiling_it_draws_on(model, expected):
    assert model_family(model) == expected


def test_spending_fable_leaves_opus_alone():
    """The bug, as it happened: both slots cooled for fable, opus never attempted."""
    p = pool()
    for t in TOKENS:
        p.cool(t, until=time.time() + 4 * 24 * HOUR, model="claude-fable-5-1")

    assert p.available("claude-fable-5-1") == []
    assert p.available("claude-opus-5") == TOKENS, "opus has its own weekly allowance"
    assert p.pick(model="claude-opus-5") in TOKENS
    assert p.available() == [], "asked about nothing in particular, a spent slot reads as spent"

    with pytest.raises(PoolExhausted):
        p.pick(model="claude-fable-5-1")


def test_the_same_model_is_still_refused_on_a_cooled_slot():
    p = pool()
    p.cool(TOKENS[0], until=time.time() + HOUR, model="claude-opus-5")
    assert p.available("claude-opus-5") == [TOKENS[1]]
    assert p.pick(sticky_key="run-1", model="claude-opus-5") == TOKENS[1]


def test_a_cooling_that_names_no_model_blocks_everything():
    """What we cannot attribute, we must assume is account-wide."""
    p = pool()
    for t in TOKENS:
        p.cool(t, until=time.time() + HOUR)
    for model in ("claude-opus-5", "claude-fable-5-1", None):
        assert p.available(model) == [], f"{model} should be blocked by an unattributed cooling"
        with pytest.raises(PoolExhausted):
            p.pick(model=model)


def test_an_account_wide_limit_costs_one_request_per_family_not_four_days():
    """The accepted trade: a shared five-hour window is learned per family, cheaply."""
    p = pool()
    for t in TOKENS:
        p.cool(t, until=time.time() + HOUR, model="claude-fable-5-1")
    # opus is still offered -- that request is the price of finding out.
    assert p.pick(model="claude-opus-5") in TOKENS
    for t in TOKENS:
        p.cool(t, until=time.time() + HOUR, model="claude-opus-5")
    with pytest.raises(PoolExhausted):
        p.pick(model="claude-opus-5")
    # and a third family has still not been charged for either.
    assert p.available("claude-sonnet-5") == TOKENS


def test_soonest_reset_answers_for_the_model_asked_about():
    p = pool()
    now = time.time()
    for t in TOKENS:
        p.cool(t, until=now + 4 * 24 * HOUR, model="claude-fable-5-1")
    p.cool(TOKENS[0], until=now + HOUR, model="claude-opus-5")

    # soonest_reset reports when a cooled slot frees up, per family -- not whether one is
    # free now. Opus has one slot cooling for an hour; fable has both out for days.
    opus = p.soonest_reset("claude-opus-5")
    assert opus is not None and HOUR * 0.9 < opus - now < HOUR * 1.1
    fable = p.soonest_reset("claude-fable-5-1")
    assert fable is not None and fable - now > 3 * 24 * HOUR
    # and the unattributed view is the pessimistic one: the furthest of the two.
    assert p.soonest_reset() == fable


def test_cooling_without_a_model_still_reads_as_before_for_callers_that_never_pass_one():
    """The old signature keeps working; it just means 'every family' now."""
    p = pool()
    deadline = p.cool(TOKENS[0])
    assert deadline > time.time()
    assert p.available() == [TOKENS[1]]
    assert p.available("claude-opus-5") == [TOKENS[1]]


def test_clearing_cooldowns_frees_every_family():
    p = pool()
    p.cool(TOKENS[0], model="claude-opus-5")
    p.cool(TOKENS[1], model="claude-fable-5-1")
    p.clear_cooldowns()
    assert p.available("claude-opus-5") == TOKENS
    assert p.available("claude-fable-5-1") == TOKENS
