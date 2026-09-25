"""The subscription pool: rotate between agents, never within one.

Several subscriptions multiply the rate-limit ceiling, but Anthropic's
prompt cache is per credential and a tool-using run re-sends its transcript
every iteration — so an agent that hops tokens pays full price for context
it already sent. These tests pin that rule down, and the failover that is
allowed to break it when a subscription is actually limited.
"""

import time
from unittest.mock import MagicMock

import pytest

from temper_ai.llm import token_pool as pool_mod
from temper_ai.llm.token_pool import (
    DEFAULT_COOLDOWN_S,
    PoolExhausted,
    TokenPool,
    sticky_key_from_kwargs,
    tokens_from_env,
)

TOKENS = [f"sk-ant-oat-{i}" for i in range(4)]


def _pool():
    return TokenPool(name="test", tokens=list(TOKENS))


class TestStickiness:
    def test_same_key_always_lands_on_the_same_subscription(self):
        """One agent in one run keeps its cache warm across every iteration."""
        pool = _pool()
        picks = {pool.pick("run-1-planner") for _ in range(50)}
        assert len(picks) == 1

    def test_different_agents_spread_across_the_pool(self):
        """Different keys are what multiply the ceiling."""
        pool = _pool()
        picks = {pool.pick(f"run-1-agent-{i}") for i in range(40)}
        assert len(picks) > 1

    def test_no_key_still_keeps_one_conversation_on_one_subscription(self):
        """Picking at random per call looked harmless and was not: each account
        holds its own cache, so a keyless loop alternated between them and every
        other turn was a full miss (measured on a live 9-turn probe)."""
        pool = _pool()
        assert len({pool.pick(None) for _ in range(60)}) == 1

    def test_keyless_default_still_fails_over_when_cooled(self):
        pool = _pool()
        default = pool.pick(None)
        pool.cool(default)
        assert pool.pick(None) != default

    def test_single_token_pool_is_not_random(self):
        pool = TokenPool(name="test", tokens=["only"])
        assert pool.pick("anything") == "only"
        assert pool.pick(None) == "only"


class TestCooling:
    def test_a_cooled_favourite_fails_over_rather_than_stalling_the_run(self):
        pool = _pool()
        mine = pool.pick("run-1-planner")
        pool.cool(mine)
        second = pool.pick("run-1-planner")
        assert second != mine
        assert second in TOKENS

    def test_the_favourite_comes_back_when_its_window_resets(self, monkeypatch):
        pool = _pool()
        mine = pool.pick("run-1-planner")
        pool.cool(mine, until=time.time() + 60)
        assert pool.pick("run-1-planner") != mine
        later = time.time() + 3600
        monkeypatch.setattr(pool_mod.time, "time", lambda: later)
        assert pool.pick("run-1-planner") == mine, "the warm cache is worth returning to"

    def test_exhausted_pool_refuses_instead_of_handing_back_a_limited_token(self):
        """The alternative once cost 12k empty completions on a dark pool."""
        pool = _pool()
        for t in TOKENS:
            pool.cool(t)
        with pytest.raises(PoolExhausted) as exc:
            pool.pick("run-1-planner")
        assert "4 tokens cooling" in str(exc.value)
        assert exc.value.reset_at is not None

    def test_default_cooldown_when_the_provider_named_no_reset(self):
        pool = _pool()
        deadline = pool.cool(TOKENS[0])
        assert DEFAULT_COOLDOWN_S - 5 < deadline - time.time() <= DEFAULT_COOLDOWN_S

    def test_a_reset_in_the_past_still_cools_briefly(self):
        """A zero-length cooling would send the next attempt straight back into
        the same limit."""
        pool = _pool()
        deadline = pool.cool(TOKENS[0], until=time.time() - 3600)
        assert 0 < deadline - time.time() <= pool_mod.MIN_COOLDOWN_S

    def test_empty_pool_is_exhausted(self):
        with pytest.raises(PoolExhausted):
            TokenPool(name="test", tokens=[]).pick(None)


class TestStickyKey:
    def test_session_id_wins(self):
        assert sticky_key_from_kwargs({"session_id": "s1", "execution_id": "r", "agent_name": "a"}) == "s1"

    def test_run_and_agent_together(self):
        assert sticky_key_from_kwargs({"execution_id": "r1", "agent_name": "planner"}) == "r1-planner"

    def test_run_alone_is_not_enough(self):
        """A run-only key would pin every agent of a run to one subscription."""
        assert sticky_key_from_kwargs({"execution_id": "r1"}) is None
        assert sticky_key_from_kwargs({}) is None


class TestTokensFromEnv:
    def test_collects_base_backup_and_numbered(self, monkeypatch):
        monkeypatch.setenv("T", "a")
        monkeypatch.setenv("T_BACKUP", "b")
        monkeypatch.setenv("T_2", "c")
        monkeypatch.setenv("T_5", "d")
        assert tokens_from_env("T") == ["a", "b", "c", "d"]

    def test_blank_and_duplicate_entries_do_not_become_slots(self, monkeypatch):
        monkeypatch.setenv("T", "a")
        monkeypatch.setenv("T_2", "  ")
        monkeypatch.setenv("T_3", "a")
        assert tokens_from_env("T") == ["a"]


class TestPromptCaching:
    """Stickiness is only worth having if we ask for a cache at all.

    A 60-iteration agent re-sends its transcript every call; before this the
    provider never sent `cache_control`, so every one of those calls paid full
    input price for text it had already sent 59 times.
    """

    def _sent(self, monkeypatch, **provider_kwargs):
        from temper_ai.llm.providers import anthropic as mod

        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-only")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        sent: list[dict] = []

        def fake_anthropic(**_kw):
            client = MagicMock()
            client.messages.create.side_effect = lambda **c: (
                sent.append(c),
                MagicMock(content=[], usage=MagicMock(input_tokens=1, output_tokens=1), stop_reason="end_turn"),
            )[1]
            return client

        monkeypatch.setattr(mod, "_ensure_anthropic", lambda: MagicMock(Anthropic=fake_anthropic))
        provider = mod.AnthropicLLM(model="claude-opus-5", **provider_kwargs)
        return provider, sent

    def test_every_request_asks_for_caching(self, monkeypatch):
        provider, sent = self._sent(monkeypatch)
        provider.complete([{"role": "system", "content": "rules"}, {"role": "user", "content": "hi"}])
        assert sent[-1]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}

    def test_a_long_running_agent_can_buy_the_hour(self, monkeypatch):
        """A test suite between two calls outlasts the 5-minute tier, and the
        next call then re-writes the whole prefix at full price."""
        provider, sent = self._sent(monkeypatch, cache_ttl="1h")
        provider.complete([{"role": "user", "content": "hi"}])
        assert sent[-1]["cache_control"]["ttl"] == "1h"

        provider.complete([{"role": "user", "content": "hi"}], cache_ttl="5m")
        assert sent[-1]["cache_control"]["ttl"] == "5m", "per call overrides the agent default"

    def test_cached_input_is_priced_as_cached(self):
        """The bill is dominated by re-sent transcript; at the full input rate a
        cached run reads about ten times its real cost."""
        from temper_ai.llm.pricing import estimate_cost

        # opus-5: $5 / MTok in, $25 out. 100k prompt of which 90k is a cache read.
        cached = estimate_cost("claude-opus-5", prompt_tokens=100_000, completion_tokens=1_000,
                               cached_prompt_tokens=90_000)
        uncached = estimate_cost("claude-opus-5", prompt_tokens=100_000, completion_tokens=1_000)
        # uncached: 100k x $5 + 1k x $25 = $0.525
        # cached:    10k x $5 + 90k x $0.50 + 1k x $25 = $0.12
        assert uncached == pytest.approx(0.525)
        assert cached == pytest.approx(0.12)
        assert cached < uncached / 4

    def test_writing_the_cache_costs_a_premium(self):
        from temper_ai.llm.pricing import estimate_cost

        written = estimate_cost("claude-opus-5", prompt_tokens=10_000, completion_tokens=0,
                                cache_write_tokens=10_000)
        fresh = estimate_cost("claude-opus-5", prompt_tokens=10_000, completion_tokens=0)
        assert written == pytest.approx(fresh * 1.25)

    def test_cached_input_is_counted_as_prompt_tokens(self):
        """Anthropic reports cache reads separately; ignoring them makes a
        well-cached run look like it stopped sending a prompt."""
        from temper_ai.llm.providers.anthropic import _parse_response

        response = MagicMock(
            content=[],
            stop_reason="end_turn",
            usage=MagicMock(input_tokens=300, output_tokens=50,
                            cache_read_input_tokens=40_000, cache_creation_input_tokens=1_000),
        )
        parsed = _parse_response(response, "claude-opus-5")
        assert parsed.prompt_tokens == 41_300
        assert parsed.total_tokens == 41_350
        assert parsed.cached_prompt_tokens == 40_000
        assert parsed.cache_write_tokens == 1_000


class TestThinkingControl:
    """Thinking is billed as output, and on a real planning run it was 65% of
    the bill and effectively all of the 33-minute wall clock.

    Which knob works flipped with the model generation, and the ignored one is
    accepted in silence. Measured, output tokens on one hard prompt:

        opus-5      effort low 427 -> max 1,302 | budget 1k 753 vs 16k 734
        sonnet-4-6  effort low 1,143 vs max 1,139 | budget 1k 4,760 -> 16k 7,232
    """

    def _sent(self, monkeypatch, **provider_kwargs):
        from temper_ai.llm.providers import anthropic as mod

        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-only")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        sent: list[dict] = []

        def fake_anthropic(**_kw):
            client = MagicMock()
            client.messages.create.side_effect = lambda **c: (
                sent.append(c),
                MagicMock(content=[], usage=MagicMock(input_tokens=1, output_tokens=1), stop_reason="end_turn"),
            )[1]
            return client

        monkeypatch.setattr(mod, "_ensure_anthropic", lambda: MagicMock(Anthropic=fake_anthropic))
        model = provider_kwargs.pop("model", "claude-opus-5")
        provider = mod.AnthropicLLM(model=model, **provider_kwargs)
        provider.complete([{"role": "user", "content": "hi"}])
        return sent[-1]

    def test_nothing_is_sent_by_default(self, monkeypatch):
        """Unset means the model's own judgement — for Opus 5, high effort."""
        sent = self._sent(monkeypatch)
        assert "thinking" not in sent
        assert "output_config" not in sent

    def test_a_claude_5_model_gets_the_effort_dial(self, monkeypatch):
        sent = self._sent(monkeypatch, effort="low")
        assert sent["output_config"] == {"effort": "low"}
        assert "thinking" not in sent

    def test_a_budget_aimed_at_a_claude_5_model_becomes_an_effort(self, monkeypatch, caplog):
        """Passing it through would be worse than refusing it: the model accepts
        the budget, ignores it, and the caller believes spending is capped."""
        from temper_ai.llm.providers import anthropic as mod

        mod._thinking_warned.clear()
        sent = self._sent(monkeypatch, thinking_budget=1024)
        assert sent["output_config"] == {"effort": "low"}
        assert "thinking" not in sent
        assert "ignores thinking budgets" in caplog.text

    def test_an_explicit_effort_is_not_overridden_by_a_budget(self, monkeypatch):
        sent = self._sent(monkeypatch, effort="max", thinking_budget=1024)
        assert sent["output_config"] == {"effort": "max"}

    def test_a_legacy_model_gets_a_real_budget(self, monkeypatch):
        sent = self._sent(monkeypatch, model="claude-sonnet-4-6", thinking_budget=1024)
        assert sent["thinking"] == {"type": "enabled", "budget_tokens": 1024}
        assert "output_config" not in sent

    def test_effort_on_a_legacy_model_becomes_a_budget(self, monkeypatch, caplog):
        from temper_ai.llm.providers import anthropic as mod

        mod._thinking_warned.clear()
        sent = self._sent(monkeypatch, model="claude-sonnet-4-6", effort="high")
        assert sent["thinking"]["budget_tokens"] == 8_000
        assert "no effort dial" in caplog.text

    def test_low_effort_on_a_legacy_model_leaves_thinking_off(self, monkeypatch):
        """There, enabling thinking *raises* output (sonnet-4-6: 1,099 tokens off,
        4,760 at a 1k budget), so the cheapest setting is not to enable it."""
        sent = self._sent(monkeypatch, model="claude-sonnet-4-6", effort="low")
        assert "thinking" not in sent
        assert "output_config" not in sent

    def test_max_tokens_is_raised_to_leave_room_for_an_answer(self, monkeypatch):
        """max_tokens covers thinking and the reply together: a budget at or above
        it leaves nothing to answer with and the API refuses the request."""
        sent = self._sent(monkeypatch, model="claude-sonnet-4-6",
                          thinking_budget=30_000, max_tokens=8_000)
        assert sent["max_tokens"] > 30_000

    def test_a_budget_drops_temperature(self, monkeypatch):
        """Extended thinking accepts no temperature but 1 and refuses the request
        otherwise; an agent that set 0.7 did not mean to forbid thinking."""
        sent = self._sent(monkeypatch, model="claude-sonnet-4-6",
                          thinking_budget=1024, temperature=0.7)
        assert "temperature" not in sent


class TestTruncation:
    """A reply cut off by max_tokens must say so.

    Live: a planner explored for 24 iterations, was truncated while writing its
    plan, returned empty, and the node — seeing an empty output with no reason —
    ran the entire exploration again and was truncated at the same place.
    """

    def _run(self, finish_reason: str, content: str | None):
        from temper_ai.llm.models import LLMResponse
        from temper_ai.llm.service import LLMService

        from .conftest import MockProvider

        response = LLMResponse(
            content=content, model="claude-opus-5", provider="MockProvider",
            prompt_tokens=10, completion_tokens=32_000, total_tokens=32_010,
            latency_ms=1, finish_reason=finish_reason,
        )
        return LLMService(MockProvider([response])).run([{"role": "user", "content": "plan it"}])

    def test_an_empty_truncated_reply_names_its_cause(self):
        result = self._run("max_tokens", "")
        assert result.output == ""
        assert "max_tokens" in (result.error or "")
        assert "provider_config" in result.error, "say what to change, not just what broke"

    def test_a_truncated_reply_that_still_said_something_is_kept(self):
        """Partial text is worth returning; only a silent truncation is a fault."""
        result = self._run("max_tokens", "## Plan\nhalf a plan")
        assert result.output.startswith("## Plan")
        assert result.error is None

    def test_an_ordinary_empty_reply_is_still_unexplained(self):
        """The retry-on-empty path stays for the glitches it was built for."""
        result = self._run("stop", "")
        assert result.output == ""
        assert result.error is None


class TestPerAgentMaxTokens:
    def test_an_agent_may_ask_for_more_room_than_the_shared_provider(self, monkeypatch):
        from temper_ai.llm.providers import anthropic as mod

        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-only")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        sent: list[dict] = []

        def fake_anthropic(**_kw):
            client = MagicMock()
            client.messages.create.side_effect = lambda **c: (
                sent.append(c),
                MagicMock(content=[], usage=MagicMock(input_tokens=1, output_tokens=1), stop_reason="end_turn"),
            )[1]
            return client

        monkeypatch.setattr(mod, "_ensure_anthropic", lambda: MagicMock(Anthropic=fake_anthropic))
        provider = mod.AnthropicLLM(model="claude-opus-5")

        provider.complete([{"role": "user", "content": "hi"}])
        assert sent[-1]["max_tokens"] == 32_000, "the default is no longer a 2023 ceiling"

        provider.complete([{"role": "user", "content": "hi"}], max_tokens=64_000)
        assert sent[-1]["max_tokens"] == 64_000


    """The provider side: one agent-run pins to one client, a 429 moves it on."""

    def _provider(self, monkeypatch, n=3):
        from temper_ai.llm.providers import anthropic as mod

        # Every other token name is set empty, not deleted: once any test in the process has run the
        # CLI's load_dotenv(override=False), the real .env refills a missing name (its _BACKUP token
        # made this pool 4, not 3, under xdist). See tests/test_llm/test_pool_is_live_in_the_server.py.
        for name in ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_BACKUP",
                     *[f"CLAUDE_CODE_OAUTH_TOKEN_{i}" for i in range(2, 10)]):
            monkeypatch.setenv(name, "")
        for i in range(n):
            monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN" if i == 0 else f"CLAUDE_CODE_OAUTH_TOKEN_{i+1}",
                               f"sk-ant-oat-{i}")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        made: dict[str, MagicMock] = {}
        # The side effect must be installed by the factory: clients are built
        # lazily, so a test that wires them up afterwards only ever reaches the
        # one client that existed at construction.
        on_create = kwargs_holder = {}

        def fake_anthropic(**kw):
            client = MagicMock()
            credential = kw.get("auth_token") or kw.get("api_key")
            client._credential = credential
            if on_create.get("fn"):
                client.messages.create.side_effect = lambda **c: on_create["fn"](credential, **c)
            made[credential] = client
            return client

        monkeypatch.setattr(mod, "_ensure_anthropic", lambda: MagicMock(Anthropic=fake_anthropic))
        return mod.AnthropicLLM(model="claude-opus-5"), made, kwargs_holder

    def test_every_call_of_one_agent_run_uses_one_subscription(self, monkeypatch):
        provider, made, _ = self._provider(monkeypatch)
        assert provider._pool is not None and len(provider._pool) == 3
        for _ in range(8):
            provider.complete([{"role": "user", "content": "hi"}],
                              execution_id="run-1", agent_name="planner")
        used = [c for c in made.values() if c.messages.create.called]
        assert len(used) == 1, "an agent that hops tokens re-pays for its whole transcript"
        assert used[0].messages.create.call_count == 8

    def test_a_rate_limited_subscription_is_cooled_and_the_call_retried(self, monkeypatch):
        provider, made, hook = self._provider(monkeypatch)
        limited = provider._pool.pick("run-1-planner")
        err = RuntimeError("rate limited")
        err.status_code = 429
        err.response = MagicMock(headers={"retry-after": "120"})
        served: list[str] = []

        def on_call(credential, **_c):
            if credential == limited:
                raise err
            served.append(credential)
            return MagicMock(content=[], usage=MagicMock(input_tokens=1, output_tokens=1), stop_reason="end_turn")

        hook["fn"] = on_call
        provider._clients.clear()  # rebuild through the factory now the hook is set

        provider.complete([{"role": "user", "content": "hi"}],
                          execution_id="run-1", agent_name="planner")

        assert served and served[0] != limited, "the call must land on another subscription"
        assert limited not in provider._pool.available()
        assert 100 < provider._pool.soonest_reset() - time.time() < 200, "retry-after drives the cooling"

    def test_every_subscription_limited_raises_rather_than_looping(self, monkeypatch):
        provider, _, hook = self._provider(monkeypatch)
        err = RuntimeError("rate limited")
        err.status_code = 429
        err.response = MagicMock(headers={})
        calls: list[str] = []

        def on_call(credential, **_c):
            calls.append(credential)
            raise err

        hook["fn"] = on_call
        provider._clients.clear()

        with pytest.raises(PoolExhausted):
            provider.complete([{"role": "user", "content": "hi"}],
                              execution_id="run-1", agent_name="planner")
        assert len(calls) == 3, "one attempt per subscription, then stop"

    def test_a_failure_that_is_not_a_limit_is_not_retried_elsewhere(self, monkeypatch):
        """A bad request is bad on every subscription; spending the pool on it
        hides the error and burns quota."""
        provider, _, hook = self._provider(monkeypatch)
        calls: list[str] = []

        def on_call(credential, **_c):
            calls.append(credential)
            raise ValueError("unsupported parameter: temperature")

        hook["fn"] = on_call
        provider._clients.clear()

        with pytest.raises(ValueError, match="unsupported parameter"):
            provider.complete([{"role": "user", "content": "hi"}],
                              execution_id="run-1", agent_name="planner")
        assert len(calls) == 1

    def test_a_model_that_refuses_temperature_is_retried_without_it(self, monkeypatch):
        """Opus 5 and Sonnet 5 answer 400 `temperature is deprecated`, which
        killed the request instead of the parameter."""
        from temper_ai.llm.providers import anthropic as mod

        mod._NO_TEMPERATURE.discard("claude-opus-5")
        provider, _, hook = self._provider(monkeypatch)
        seen: list[bool] = []

        err = RuntimeError("Error code: 400 - `temperature` is deprecated for this model.")
        err.status_code = 400

        def on_call(_credential, **c):
            seen.append("temperature" in c)
            if "temperature" in c:
                raise err
            return MagicMock(content=[], usage=MagicMock(input_tokens=1, output_tokens=1), stop_reason="end_turn")

        hook["fn"] = on_call
        provider._clients.clear()

        provider.complete([{"role": "user", "content": "hi"}], execution_id="r", agent_name="a")
        assert seen == [True, False], "the retry must drop the parameter, not the request"

        # and the process has learned: the next call never sends it
        provider.complete([{"role": "user", "content": "hi"}], execution_id="r", agent_name="a")
        assert seen == [True, False, False]
        mod._NO_TEMPERATURE.discard("claude-opus-5")

    def test_an_explicit_credential_is_not_pooled(self, monkeypatch):
        """A caller that passed a token means that token, not a hunt for siblings."""
        provider, _, _ = self._provider(monkeypatch)
        assert provider._pool is not None
        from temper_ai.llm.providers import anthropic as mod

        explicit = mod.AnthropicLLM(model="claude-opus-5", api_key="sk-ant-oat-explicit")
        assert explicit._pool is None
