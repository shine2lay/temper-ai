"""Tests for canonical ExecutionContext.

Verifies the unified ExecutionContext class covers all fields from the
previously separate definitions and maintains backward compatibility.
"""

from src.shared.core.context import ExecutionContext


class TestExecutionContext:
    """Test canonical ExecutionContext."""

    def test_default_construction(self):
        """All fields default to None/empty."""
        ctx = ExecutionContext()
        assert ctx.workflow_id is None
        assert ctx.stage_id is None
        assert ctx.agent_id is None
        assert ctx.session_id is None
        assert ctx.user_id is None
        assert ctx.tool_name is None
        assert ctx.metadata == {}

    def test_full_construction(self):
        """All fields can be set at once."""
        ctx = ExecutionContext(
            workflow_id="wf-1",
            stage_id="stage-1",
            agent_id="agent-1",
            session_id="sess-1",
            user_id="user-1",
            tool_name="calculator",
            metadata={"key": "value"},
        )
        assert ctx.workflow_id == "wf-1"
        assert ctx.stage_id == "stage-1"
        assert ctx.agent_id == "agent-1"
        assert ctx.session_id == "sess-1"
        assert ctx.user_id == "user-1"
        assert ctx.tool_name == "calculator"
        assert ctx.metadata == {"key": "value"}

    def test_partial_construction(self):
        """Subsets of fields work (backward compat with tracker/base_agent)."""
        # Tracker-style: only workflow/stage/agent
        ctx = ExecutionContext(workflow_id="wf-1", stage_id="s-1", agent_id="a-1")
        assert ctx.workflow_id == "wf-1"
        assert ctx.session_id is None
        assert ctx.tool_name is None

        # Exception-style: workflow/stage/agent/tool_name
        ctx = ExecutionContext(
            workflow_id="wf-1", agent_id="a-1", tool_name="web_search"
        )
        assert ctx.tool_name == "web_search"
        assert ctx.user_id is None

        # Cache-style: user_id/session_id
        ctx = ExecutionContext(user_id="u-1", session_id="s-1")
        assert ctx.user_id == "u-1"
        assert ctx.session_id == "s-1"
        assert ctx.workflow_id is None

    def test_to_dict(self):
        """to_dict returns all fields."""
        ctx = ExecutionContext(workflow_id="wf-1", tool_name="calc")
        d = ctx.to_dict()
        assert d == {
            "workflow_id": "wf-1",
            "stage_id": None,
            "agent_id": None,
            "session_id": None,
            "user_id": None,
            "tool_name": "calc",
            "metadata": {},
        }

    def test_to_dict_full(self):
        """to_dict includes all populated fields."""
        ctx = ExecutionContext(
            workflow_id="wf-1",
            stage_id="s-1",
            agent_id="a-1",
            session_id="sess-1",
            user_id="u-1",
            tool_name="tool-1",
            metadata={"k": "v"},
        )
        d = ctx.to_dict()
        assert d["workflow_id"] == "wf-1"
        assert d["session_id"] == "sess-1"
        assert d["user_id"] == "u-1"
        assert d["tool_name"] == "tool-1"
        assert d["metadata"] == {"k": "v"}

    def test_repr_empty(self):
        """Repr with no fields set."""
        ctx = ExecutionContext()
        assert repr(ctx) == "ExecutionContext()"

    def test_repr_partial(self):
        """Repr shows only set fields."""
        ctx = ExecutionContext(workflow_id="wf-1", agent_id="a-1")
        r = repr(ctx)
        assert "workflow=wf-1" in r
        assert "agent=a-1" in r
        assert "session=" not in r
        assert "tool=" not in r

    def test_repr_full(self):
        """Repr shows all fields when set."""
        ctx = ExecutionContext(
            workflow_id="wf-1",
            stage_id="s-1",
            agent_id="a-1",
            session_id="sess-1",
            user_id="u-1",
            tool_name="calc",
        )
        r = repr(ctx)
        assert "workflow=wf-1" in r
        assert "stage=s-1" in r
        assert "agent=a-1" in r
        assert "session=sess-1" in r
        assert "user=u-1" in r
        assert "tool=calc" in r

    def test_metadata_default_not_shared(self):
        """Each instance gets its own metadata dict."""
        ctx1 = ExecutionContext()
        ctx2 = ExecutionContext()
        ctx1.metadata["key"] = "value"
        assert "key" not in ctx2.metadata

    def test_is_dataclass(self):
        """ExecutionContext is a proper dataclass."""
        import dataclasses
        assert dataclasses.is_dataclass(ExecutionContext)

    def test_equality(self):
        """Dataclass equality works."""
        ctx1 = ExecutionContext(workflow_id="wf-1", agent_id="a-1")
        ctx2 = ExecutionContext(workflow_id="wf-1", agent_id="a-1")
        assert ctx1 == ctx2

    def test_no_import_shadowing(self):
        """Verify the canonical import path doesn't collide."""
        from src.shared.core.context import ExecutionContext as EC
        assert EC is ExecutionContext


class TestBackwardCompatibility:
    """Verify the canonical class supports all usage patterns from the 4 old definitions."""

    def test_base_agent_pattern(self):
        """base_agent.py used: workflow_id, stage_id, agent_id, session_id, user_id, metadata."""
        ctx = ExecutionContext(
            workflow_id="wf-1",
            stage_id="s-1",
            agent_id="a-1",
            session_id="sess-1",
            user_id="u-1",
            metadata={"env": "test"},
        )
        assert ctx.workflow_id == "wf-1"
        assert ctx.session_id == "sess-1"
        assert ctx.user_id == "u-1"
        assert ctx.metadata == {"env": "test"}

    def test_exceptions_pattern(self):
        """exceptions.py used: workflow_id, stage_id, agent_id, tool_name, metadata + to_dict."""
        ctx = ExecutionContext(
            workflow_id="wf-1",
            stage_id="s-1",
            agent_id="a-1",
            tool_name="web_search",
            metadata={"error": "timeout"},
        )
        d = ctx.to_dict()
        assert d["tool_name"] == "web_search"
        assert d["metadata"] == {"error": "timeout"}

    def test_tracker_pattern(self):
        """tracker.py used: workflow_id, stage_id, agent_id only."""
        ctx = ExecutionContext(
            workflow_id="wf-1", stage_id="s-1", agent_id="a-1"
        )
        assert ctx.workflow_id == "wf-1"
        assert ctx.stage_id == "s-1"
        assert ctx.agent_id == "a-1"
