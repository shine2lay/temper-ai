"""The failures that actually killed runs, replayed against the new rule.

Not the runs themselves -- the *condition* they died on, taken from what they
recorded. The point of the feature is these, so the honest question is which
of them it would have saved, and the answer is not "all of them".

What the event log held (eight days to 2026-09-30):

  * 8 x ``token pool exhausted — all N tokens cooling; soonest reset
    2026-09-26 14:00Z``, raised on 09-22 and 09-24. That reset is *two days*
    out: a weekly ceiling, not the rolling five-hour one. Past the six-hour
    ceiling, so these still fail -- by design, and the reason the ceiling
    exists. A workflow that would rather sit one out says ``wait_for_allowance:
    3d`` and gets the park.
  * 6 x a plain ``429 rate_limit_error`` ("this request would exceed your
    account's rate limit"), which names no time in its body but does in its
    headers -- seconds to minutes. Those park.
  * 4 x ``max_tokens before any text was returned`` on claude-opus-5-5, every
    one an agent whose whole ceiling went on thinking. Those get their retry.
"""

from datetime import UTC, datetime

import httpx
import pytest

from temper_ai.llm import allowance
from temper_ai.llm.token_pool import PoolExhausted

HOUR = 3600.0
# 2026-09-24 12:45Z -- when the last of the eight died.
DIED = datetime(2026, 9, 24, 12, 45, tzinfo=UTC).timestamp()
# What every one of them named as the soonest reset.
RESET = datetime(2026, 9, 26, 14, 0, tzinfo=UTC).timestamp()


def _the_pools_refusal() -> PoolExhausted:
    """Word for word what the eight recorded, reset and all."""
    return PoolExhausted(3, RESET)


def _a_plain_429(headers: dict[str, str]) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.HTTPStatusError(
        "Error code: 429 - {'type': 'error', 'error': {'type': 'rate_limit_error', "
        "'message': \"This request would exceed your account's rate limit. "
        "Please try again later.\"}}",
        request=request,
        response=httpx.Response(429, request=request, headers=headers))


class TestTheEightThatDiedOnASpentPool:
    def test_the_reset_they_named_is_read_correctly(self):
        assert allowance.reset_at(_the_pools_refusal()) == RESET

    def test_at_the_default_ceiling_they_still_fail(self):
        """Two days out is a weekly ceiling. Parking a run for two days is the
        thing the ceiling exists to stop -- it holds its box, its worktree and
        its branch the whole time, and a person resuming on Monday is better."""
        assert allowance.decide(_the_pools_refusal(), now=DIED) is None

    def test_a_workflow_that_would_rather_wait_gets_the_park(self):
        """The ceiling is a default, not a rule: a workflow prepared to sit out
        a weekly reset says so and keeps its place."""
        wait = allowance.decide(_the_pools_refusal(), now=DIED, max_wait=3 * 24 * HOUR)
        assert wait is not None
        assert wait.until == pytest.approx(RESET + allowance.WAKE_PAD_S)
        assert wait.seconds == pytest.approx(RESET - DIED + allowance.WAKE_PAD_S)

    def test_the_same_pool_on_its_rolling_ceiling_parks_by_default(self):
        """The common case, and the one this is for: the five-hour window.

        Same refusal, same code path -- only the reset is hours out instead of
        days, and the run waits it out instead of needing a person.
        """
        rolling = PoolExhausted(3, DIED + 4 * HOUR)
        wait = allowance.decide(rolling, now=DIED)
        assert wait is not None
        assert allowance.how_long(wait.seconds) == "4h"


class TestTheSixThatDiedOnAPlainRateLimit:
    @pytest.mark.parametrize("headers, waited", [
        ({"retry-after": "60"}, "1m"),
        ({"retry-after": "1800"}, "30m"),
        ({"anthropic-ratelimit-unified-reset": "2026-09-24T13:00:00Z"}, "15m"),
    ])
    def test_they_park_on_what_the_headers_say(self, headers, waited):
        wait = allowance.decide(_a_plain_429(headers), now=DIED)
        assert wait is not None
        assert allowance.how_long(wait.seconds) == waited

    def test_one_that_says_nothing_anywhere_still_fails(self):
        """No body time, no header time: nothing to wake at, so no guessing."""
        assert allowance.decide(_a_plain_429({}), now=DIED) is None
