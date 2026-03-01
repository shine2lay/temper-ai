"""Tests for observability sampling context."""

from temper_ai.observability.sampling import SamplingContext


class TestSamplingContext:
    def test_defaults(self) -> None:
        ctx = SamplingContext()
        assert ctx.workflow_id == ""
        assert ctx.workflow_name == ""
        assert ctx.environment == ""
        assert ctx.tags == []
        assert ctx.metadata == {}

    def test_custom_values(self) -> None:
        ctx = SamplingContext(
            workflow_id="abc",
            workflow_name="my_wf",
            environment="prod",
            tags=["a"],
            metadata={"k": "v"},
        )
        assert ctx.workflow_id == "abc"
        assert ctx.metadata == {"k": "v"}
