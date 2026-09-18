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

    def test_no_key_means_no_locality(self):
        """Without a key there is nothing to keep warm, so spread the load."""
        pool = _pool()
        assert len({pool.pick(None) for _ in range(60)}) > 1

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

    def _sent(self, messages, system=None, tools=None):
        from temper_ai.llm.providers.anthropic import _apply_prompt_caching

        kwargs = {"messages": messages}
        if system is not None:
            kwargs["system"] = system
        if tools is not None:
            kwargs["tools"] = tools
        _apply_prompt_caching(kwargs)
        return kwargs

    def test_the_system_prompt_is_cached(self):
        sent = self._sent([{"role": "user", "content": "hi"}], system="rules")
        assert sent["system"] == [
            {"type": "text", "text": "rules", "cache_control": {"type": "ephemeral"}},
        ]

    def test_only_the_last_system_block_carries_the_breakpoint(self):
        """One breakpoint covers everything before it; four is the whole budget."""
        blocks = [{"type": "text", "text": "identity"}, {"type": "text", "text": "agent rules"}]
        sent = self._sent([{"role": "user", "content": "hi"}], system=blocks)
        assert "cache_control" not in sent["system"][0]
        assert sent["system"][1]["cache_control"] == {"type": "ephemeral"}

    def test_the_breakpoint_moves_to_the_newest_turn(self):
        """Each turn caches the transcript up to it, so the next turn reads it back."""
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": [{"type": "text", "text": "thinking"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "out"}]},
        ]
        sent = self._sent(messages, system="rules")
        assert sent["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in sent["messages"][1]["content"][0]

    def test_an_existing_breakpoint_is_left_alone(self):
        block = {"type": "text", "text": "x", "cache_control": {"type": "persistent"}}
        sent = self._sent([{"role": "user", "content": [block]}])
        assert sent["messages"][0]["content"][0]["cache_control"] == {"type": "persistent"}

    def test_no_messages_no_crash(self):
        assert self._sent([], system="rules")["system"][0]["cache_control"]

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


class TestProviderUsesThePool:
    """The provider side: one agent-run pins to one client, a 429 moves it on."""

    def _provider(self, monkeypatch, n=3):
        from temper_ai.llm.providers import anthropic as mod

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
