"""Which thinking knob each Anthropic generation actually obeys.

The two dialects fail differently. `output_config.effort` on a model that
wants `thinking.budget_tokens` is not an error -- the API accepts it and
thinks as little as it likes, so a run configured for deep reasoning quietly
does none, and nothing in the logs says so. That silence is the reason this
is pinned per model id rather than by family prefix: a prefix decides the
dialect for models nobody has called yet, in whichever direction the last
release happened to go.
"""

from temper_ai.llm.providers.anthropic import (
    _ADAPTIVE_EFFORT_MODELS,
    _apply_thinking_control,
    _honours_effort,
)


def control_for(model: str, *, effort: str | None = None, budget: int | None = None) -> dict:
    kwargs: dict = {}
    _apply_thinking_control(kwargs, model, effort, budget)
    return kwargs


class TestOpus55SpeaksEffort:
    def test_opus_5_5_is_listed_in_its_own_right(self):
        """The id is in the table, not merely covered by a prefix.

        Asserting behaviour cannot see this: "claude-opus-5-5" starts with
        "claude-opus-5", so `_honours_effort` answers True either way and a
        behavioural test passes with the entry deleted. What is being pinned
        is the decision to state each model, so that the next id -- which may
        not share a prefix, or may share one and disagree -- has to be looked
        at rather than inherited.
        """
        assert "claude-opus-5-5" in _ADAPTIVE_EFFORT_MODELS
        assert _honours_effort("claude-opus-5-5")
        assert _honours_effort("claude-opus-5-5-20260115")

    def test_effort_goes_out_as_output_config(self):
        assert control_for("claude-opus-5-5", effort="max") == {"output_config": {"effort": "max"}}

    def test_a_budget_aimed_at_5_5_is_translated_not_dropped(self):
        """The wrong dialect is still a request for thinking; honour it."""
        assert control_for("claude-opus-5-5", budget=16_000) == {"output_config": {"effort": "high"}}
        assert control_for("claude-opus-5-5", budget=1_000) == {"output_config": {"effort": "low"}}

    def test_the_legacy_line_still_gets_a_budget(self):
        """Proof the dialects are actually distinguished, not all one branch."""
        legacy = control_for("claude-opus-4-1", effort="high")
        assert legacy["thinking"]["type"] == "enabled"
        assert "output_config" not in legacy

    def test_asking_for_nothing_sends_nothing(self):
        assert control_for("claude-opus-5-5") == {}
