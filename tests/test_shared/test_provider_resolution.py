"""Which provider runs when a workflow does not name one.

Every shipped workflow used to hard-code `provider: openai`, so a fresh
install configured for anything else failed on all of them — 8 of the 10
examples in the repo. They now leave the provider out and land here.
"""

import pytest

from temper_ai.shared.types import ExecutionContext


def _context(*providers):
    return ExecutionContext(
        run_id="r",
        workflow_name="w",
        node_path="n",
        agent_name="a",
        event_recorder=None,
        tool_executor=None,
        llm_providers={name: f"<{name}>" for name in providers},
    )


class TestResolveProvider:
    def test_uses_the_only_configured_provider(self):
        assert _context("claude").resolve_provider() == "claude"

    def test_prefers_a_hosted_provider_over_a_local_endpoint(self, monkeypatch):
        """A stray OLLAMA_BASE_URL or VLLM_BASE_URL with nothing listening
        is common, and picking it fails as a connection refused rather
        than anything explanatory."""
        monkeypatch.delenv("TEMPER_DEFAULT_PROVIDER", raising=False)
        assert _context("vllm", "ollama", "claude").resolve_provider() == "claude"
        assert _context("vllm", "openai").resolve_provider() == "openai"

    def test_the_choice_does_not_depend_on_configuration_order(self, monkeypatch):
        monkeypatch.delenv("TEMPER_DEFAULT_PROVIDER", raising=False)
        assert _context("openai", "claude").resolve_provider() == "claude"
        assert _context("claude", "openai").resolve_provider() == "claude"

    def test_the_environment_wins(self, monkeypatch):
        monkeypatch.setenv("TEMPER_DEFAULT_PROVIDER", "openai")
        assert _context("claude", "openai").resolve_provider() == "openai"

    def test_an_unconfigured_default_says_so(self, monkeypatch):
        monkeypatch.setenv("TEMPER_DEFAULT_PROVIDER", "gemini")
        with pytest.raises(KeyError, match="not configured"):
            _context("claude").resolve_provider()

    def test_no_providers_at_all_names_the_keys_to_set(self, monkeypatch):
        monkeypatch.delenv("TEMPER_DEFAULT_PROVIDER", raising=False)
        with pytest.raises(KeyError, match="ANTHROPIC_API_KEY"):
            _context().resolve_provider()

    def test_an_unknown_provider_still_resolves_to_something(self, monkeypatch):
        monkeypatch.delenv("TEMPER_DEFAULT_PROVIDER", raising=False)
        assert _context("my_custom_provider").resolve_provider() == "my_custom_provider"


class TestGetLlm:
    def test_none_means_whatever_is_configured(self, monkeypatch):
        monkeypatch.delenv("TEMPER_DEFAULT_PROVIDER", raising=False)
        assert _context("claude").get_llm(None) == "<claude>"

    def test_a_named_provider_is_never_silently_swapped(self):
        """Asking for one provider and being billed for another is worse
        than failing."""
        with pytest.raises(KeyError) as exc:
            _context("claude").get_llm("openai")
        assert "not configured" in str(exc.value)

    def test_the_error_says_how_to_fix_it(self):
        with pytest.raises(KeyError) as exc:
            _context("claude").get_llm("openai")
        message = str(exc.value)
        assert "Remove the `provider:` line" in message
        assert "TEMPER_DEFAULT_PROVIDER" in message
