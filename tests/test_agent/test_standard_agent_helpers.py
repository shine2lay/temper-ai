"""Tests for temper_ai.agent._standard_agent_helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from temper_ai.agent._standard_agent_helpers import (
    _fetch_memory_text,
    _fetch_procedural_text,
    build_memory_scope,
    inject_memory_context,
    retrieve_memory_text,
)
from temper_ai.memory._schemas import MemoryScope

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mem_cfg(
    tenant_id="t1",
    memory_namespace=None,
    retrieval_k=5,
    relevance_threshold=0.7,
    decay_factor=1.0,
    shared_namespace=None,
):
    mem_cfg = MagicMock()
    mem_cfg.tenant_id = tenant_id
    mem_cfg.memory_namespace = memory_namespace
    mem_cfg.retrieval_k = retrieval_k
    mem_cfg.relevance_threshold = relevance_threshold
    mem_cfg.decay_factor = decay_factor
    mem_cfg.shared_namespace = shared_namespace
    return mem_cfg


def _make_config(
    tenant_id="t1",
    memory_namespace=None,
    retrieval_k=5,
    relevance_threshold=0.7,
    decay_factor=1.0,
    shared_namespace=None,
    agent_name="test_agent",
    persistent=False,
    agent_id=None,
):
    mem_cfg = _make_mem_cfg(
        tenant_id=tenant_id,
        memory_namespace=memory_namespace,
        retrieval_k=retrieval_k,
        relevance_threshold=relevance_threshold,
        decay_factor=decay_factor,
        shared_namespace=shared_namespace,
    )
    inner = MagicMock()
    inner.name = agent_name
    inner.persistent = persistent
    inner.agent_id = agent_id
    inner.memory = mem_cfg

    config = MagicMock()
    config.agent = inner
    return config


def _make_svc(
    scope=None,
    memory_text=None,
    shared_scope=None,
    procedural_text=None,
):
    svc = MagicMock()
    if scope is None:
        scope = MemoryScope(tenant_id="t1", agent_name="test_agent")
    svc.build_scope.return_value = scope
    svc.build_shared_scope.return_value = shared_scope or MemoryScope(
        tenant_id="t1", agent_name="shared"
    )
    svc.retrieve_context.return_value = memory_text
    svc.retrieve_with_shared.return_value = memory_text
    svc.retrieve_procedural_context.return_value = procedural_text
    return svc


def _base_scope():
    return MemoryScope(tenant_id="t1", agent_name="agent")


# ---------------------------------------------------------------------------
# _fetch_memory_text
# ---------------------------------------------------------------------------


class TestFetchMemoryText:
    def test_no_shared_namespace_calls_retrieve_context(self):
        scope = _base_scope()
        mem_cfg = _make_mem_cfg(shared_namespace=None)
        svc = _make_svc(scope=scope, memory_text="some memory")

        result = _fetch_memory_text(svc, scope, "query", mem_cfg)

        svc.retrieve_context.assert_called_once_with(
            scope,
            "query",
            retrieval_k=mem_cfg.retrieval_k,
            relevance_threshold=mem_cfg.relevance_threshold,
            decay_factor=mem_cfg.decay_factor,
        )
        svc.retrieve_with_shared.assert_not_called()
        assert result == "some memory"

    def test_shared_namespace_calls_retrieve_with_shared(self):
        scope = _base_scope()
        shared_scope = MemoryScope(tenant_id="t1", agent_name="shared")
        mem_cfg = _make_mem_cfg(shared_namespace="shared_ns")
        svc = _make_svc(
            scope=scope, shared_scope=shared_scope, memory_text="shared mem"
        )

        result = _fetch_memory_text(svc, scope, "query", mem_cfg)

        svc.build_shared_scope.assert_called_once_with(scope, "shared_ns")
        svc.retrieve_with_shared.assert_called_once_with(
            scope,
            shared_scope,
            "query",
            retrieval_k=mem_cfg.retrieval_k,
            relevance_threshold=mem_cfg.relevance_threshold,
            decay_factor=mem_cfg.decay_factor,
        )
        svc.retrieve_context.assert_not_called()
        assert result == "shared mem"

    def test_returns_empty_string_when_retrieve_context_returns_none(self):
        scope = _base_scope()
        mem_cfg = _make_mem_cfg(shared_namespace=None)
        svc = _make_svc(scope=scope, memory_text=None)

        assert _fetch_memory_text(svc, scope, "query", mem_cfg) == ""

    def test_returns_empty_string_when_retrieve_with_shared_returns_none(self):
        scope = _base_scope()
        mem_cfg = _make_mem_cfg(shared_namespace="ns")
        svc = _make_svc(scope=scope, memory_text=None)

        assert _fetch_memory_text(svc, scope, "query", mem_cfg) == ""

    def test_returns_text_from_retrieve_context(self):
        scope = _base_scope()
        mem_cfg = _make_mem_cfg(shared_namespace=None)
        svc = _make_svc(scope=scope, memory_text="episodic memory content")

        assert (
            _fetch_memory_text(svc, scope, "query", mem_cfg)
            == "episodic memory content"
        )


# ---------------------------------------------------------------------------
# _fetch_procedural_text
# ---------------------------------------------------------------------------


class TestFetchProceduralText:
    def test_returns_procedural_text(self):
        scope = _base_scope()
        mem_cfg = _make_mem_cfg()
        svc = MagicMock()
        svc.retrieve_procedural_context.return_value = "procedural instructions"

        assert (
            _fetch_procedural_text(svc, scope, "q", mem_cfg, "agent")
            == "procedural instructions"
        )

    def test_returns_empty_string_when_none_returned(self):
        scope = _base_scope()
        mem_cfg = _make_mem_cfg()
        svc = MagicMock()
        svc.retrieve_procedural_context.return_value = None

        assert _fetch_procedural_text(svc, scope, "q", mem_cfg, "agent") == ""

    def test_catches_value_error_returns_empty_string(self):
        scope = _base_scope()
        mem_cfg = _make_mem_cfg()
        svc = MagicMock()
        svc.retrieve_procedural_context.side_effect = ValueError("bad value")

        assert _fetch_procedural_text(svc, scope, "q", mem_cfg, "agent") == ""

    def test_catches_runtime_error_returns_empty_string(self):
        scope = _base_scope()
        mem_cfg = _make_mem_cfg()
        svc = MagicMock()
        svc.retrieve_procedural_context.side_effect = RuntimeError("store failed")

        assert _fetch_procedural_text(svc, scope, "q", mem_cfg, "agent") == ""

    def test_passes_correct_retrieval_params(self):
        scope = _base_scope()
        mem_cfg = _make_mem_cfg(retrieval_k=10, relevance_threshold=0.5)
        svc = MagicMock()
        svc.retrieve_procedural_context.return_value = "text"

        _fetch_procedural_text(svc, scope, "my query", mem_cfg, "agent_name")

        svc.retrieve_procedural_context.assert_called_once_with(
            scope,
            "my query",
            retrieval_k=10,
            relevance_threshold=0.5,
        )


# ---------------------------------------------------------------------------
# build_memory_scope
# ---------------------------------------------------------------------------


class TestBuildMemoryScope:
    def test_no_context_passes_empty_workflow_name(self):
        config = _make_config(tenant_id="t1", agent_name="agent")
        base_scope = MemoryScope(tenant_id="t1", agent_name="agent")
        svc = _make_svc(scope=base_scope)

        build_memory_scope(config, "agent", svc, context=None)

        svc.build_scope.assert_called_once_with(
            tenant_id="t1",
            workflow_name="",
            agent_name="agent",
            namespace=config.agent.memory.memory_namespace,
        )

    def test_returns_scope_from_build_scope(self):
        config = _make_config()
        base_scope = MemoryScope(tenant_id="t1", agent_name="agent")
        svc = _make_svc(scope=base_scope)

        result = build_memory_scope(config, "agent", svc, context=None)

        assert result is base_scope

    def test_uses_workflow_name_from_context_metadata(self):
        config = _make_config()
        base_scope = MemoryScope(
            tenant_id="t1", agent_name="agent", workflow_name="wf-1"
        )
        svc = _make_svc(scope=base_scope)
        context = MagicMock()
        context.metadata = {"workflow_name": "wf-1"}

        build_memory_scope(config, "agent", svc, context=context)

        call_kwargs = svc.build_scope.call_args[1]
        assert call_kwargs["workflow_name"] == "wf-1"

    def test_empty_workflow_name_when_not_in_metadata(self):
        config = _make_config()
        base_scope = MemoryScope(tenant_id="t1", agent_name="agent")
        svc = _make_svc(scope=base_scope)
        context = MagicMock()
        context.metadata = {"other_key": "value"}

        build_memory_scope(config, "agent", svc, context=context)

        call_kwargs = svc.build_scope.call_args[1]
        assert call_kwargs["workflow_name"] == ""

    def test_empty_workflow_name_when_context_metadata_is_none(self):
        config = _make_config()
        base_scope = MemoryScope(tenant_id="t1", agent_name="agent")
        svc = _make_svc(scope=base_scope)
        context = MagicMock()
        context.metadata = None

        build_memory_scope(config, "agent", svc, context=context)

        call_kwargs = svc.build_scope.call_args[1]
        assert call_kwargs["workflow_name"] == ""

    def test_persistent_true_rewrites_namespace(self):
        from temper_ai.registry.constants import PERSISTENT_NAMESPACE_PREFIX

        config = _make_config(agent_name="my_agent", persistent=True)
        base_scope = MemoryScope(tenant_id="t1", agent_name="my_agent")
        svc = _make_svc(scope=base_scope)

        result = build_memory_scope(config, "my_agent", svc, context=None)

        assert result.namespace == f"{PERSISTENT_NAMESPACE_PREFIX}my_agent"

    def test_persistent_true_clears_workflow_name(self):
        config = _make_config(agent_name="my_agent", persistent=True)
        base_scope = MemoryScope(
            tenant_id="t1", agent_name="my_agent", workflow_name="old-wf"
        )
        svc = _make_svc(scope=base_scope)

        result = build_memory_scope(config, "my_agent", svc, context=None)

        assert result.workflow_name == ""

    def test_persistent_true_preserves_tenant_id(self):
        config = _make_config(
            tenant_id="my_tenant", agent_name="my_agent", persistent=True
        )
        base_scope = MemoryScope(tenant_id="my_tenant", agent_name="my_agent")
        svc = _make_svc(scope=base_scope)

        result = build_memory_scope(config, "my_agent", svc, context=None)

        assert result.tenant_id == "my_tenant"

    def test_persistent_true_with_agent_id(self):
        config = _make_config(
            agent_name="my_agent", persistent=True, agent_id="uuid-42"
        )
        base_scope = MemoryScope(tenant_id="t1", agent_name="my_agent")
        svc = _make_svc(scope=base_scope)

        result = build_memory_scope(config, "my_agent", svc, context=None)

        assert result.agent_id == "uuid-42"

    def test_persistent_true_without_agent_id(self):
        config = _make_config(agent_name="my_agent", persistent=True, agent_id=None)
        base_scope = MemoryScope(tenant_id="t1", agent_name="my_agent")
        svc = _make_svc(scope=base_scope)

        result = build_memory_scope(config, "my_agent", svc, context=None)

        assert result.agent_id is None

    def test_persistent_false_returns_original_scope(self):
        config = _make_config(agent_name="my_agent", persistent=False)
        base_scope = MemoryScope(tenant_id="t1", agent_name="my_agent")
        svc = _make_svc(scope=base_scope)

        result = build_memory_scope(config, "my_agent", svc, context=None)

        assert result is base_scope

    def test_passes_tenant_id_to_build_scope(self):
        config = _make_config(tenant_id="my_tenant")
        base_scope = MemoryScope(tenant_id="my_tenant", agent_name="agent")
        svc = _make_svc(scope=base_scope)

        build_memory_scope(config, "agent", svc)

        call_kwargs = svc.build_scope.call_args[1]
        assert call_kwargs["tenant_id"] == "my_tenant"

    def test_passes_agent_name_parameter(self):
        config = _make_config()
        base_scope = MemoryScope(tenant_id="t1", agent_name="specific_agent")
        svc = _make_svc(scope=base_scope)

        build_memory_scope(config, "specific_agent", svc)

        call_kwargs = svc.build_scope.call_args[1]
        assert call_kwargs["agent_name"] == "specific_agent"


# ---------------------------------------------------------------------------
# inject_memory_context
# ---------------------------------------------------------------------------


class TestInjectMemoryContext:
    def test_returns_template_unchanged_when_no_memory(self):
        config = _make_config()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.return_value = None
        svc.retrieve_procedural_context.return_value = None

        result = inject_memory_context(
            "Base template", {"input": "hello"}, config, "agent", svc, scope
        )

        assert result == "Base template"

    def test_appends_episodic_memory_text(self):
        config = _make_config()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.return_value = "episodic memory"
        svc.retrieve_procedural_context.return_value = None

        result = inject_memory_context(
            "Base template", {"input": "hello"}, config, "agent", svc, scope
        )

        assert result == "Base template\n\n---\n\nepisodic memory"

    def test_appends_procedural_text(self):
        config = _make_config()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.return_value = None
        svc.retrieve_procedural_context.return_value = "procedural steps"

        result = inject_memory_context(
            "Base template", {"input": "hello"}, config, "agent", svc, scope
        )

        assert result == "Base template\n\nprocedural steps"

    def test_appends_both_memory_and_procedural(self):
        config = _make_config()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.return_value = "episodic"
        svc.retrieve_procedural_context.return_value = "procedural"

        result = inject_memory_context(
            "Base", {"input": "hello"}, config, "agent", svc, scope
        )

        assert "episodic" in result
        assert "procedural" in result
        assert "---" in result

    def test_returns_template_unchanged_on_retrieve_context_error(self):
        config = _make_config()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.side_effect = ValueError("error in retrieve")

        result = inject_memory_context(
            "Base template", {"input": "hello"}, config, "agent", svc, scope
        )

        assert result == "Base template"

    def test_returns_template_unchanged_on_key_error(self):
        config = _make_config()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.side_effect = KeyError("missing_key")

        result = inject_memory_context(
            "Base", {"input": "q"}, config, "agent", svc, scope
        )

        assert result == "Base"

    def test_returns_template_unchanged_on_os_error(self):
        config = _make_config()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.side_effect = OSError("disk error")

        result = inject_memory_context(
            "Base", {"input": "q"}, config, "agent", svc, scope
        )

        assert result == "Base"

    def test_episodic_present_when_procedural_errors(self):
        config = _make_config()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.return_value = "episodic memory"
        svc.retrieve_procedural_context.side_effect = RuntimeError("procedural fail")

        result = inject_memory_context(
            "Base", {"input": "hello"}, config, "agent", svc, scope
        )

        assert "episodic memory" in result

    def test_builds_query_from_string_values(self):
        config = _make_config()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.return_value = None
        svc.retrieve_procedural_context.return_value = None

        inject_memory_context(
            "Base",
            {"key1": "hello", "key2": "world"},
            config,
            "agent",
            svc,
            scope,
        )

        call_args = svc.retrieve_context.call_args
        query = call_args[0][1]
        assert "hello" in query
        assert "world" in query

    def test_query_truncated_at_max_chars(self):
        from temper_ai.memory.constants import MEMORY_QUERY_MAX_CHARS

        config = _make_config()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.return_value = None
        svc.retrieve_procedural_context.return_value = None

        inject_memory_context(
            "Base",
            {"input": "x" * (MEMORY_QUERY_MAX_CHARS + 200)},
            config,
            "agent",
            svc,
            scope,
        )

        call_args = svc.retrieve_context.call_args
        query = call_args[0][1]
        assert len(query) <= MEMORY_QUERY_MAX_CHARS

    def test_non_string_values_excluded_from_query(self):
        config = _make_config()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.return_value = None
        svc.retrieve_procedural_context.return_value = None

        inject_memory_context(
            "Base",
            {"count": 42, "flag": True, "text": "hello"},
            config,
            "agent",
            svc,
            scope,
        )

        call_args = svc.retrieve_context.call_args
        query = call_args[0][1]
        assert "hello" in query
        assert "42" not in query
        assert "True" not in query


# ---------------------------------------------------------------------------
# retrieve_memory_text
# ---------------------------------------------------------------------------


class TestRetrieveMemoryText:
    def test_returns_empty_string_when_no_memory(self):
        mem_cfg = _make_mem_cfg()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.return_value = None
        svc.retrieve_procedural_context.return_value = None

        assert retrieve_memory_text(svc, scope, mem_cfg, "query", "agent") == ""

    def test_returns_episodic_with_separator(self):
        mem_cfg = _make_mem_cfg()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.return_value = "episodic content"
        svc.retrieve_procedural_context.return_value = None

        result = retrieve_memory_text(svc, scope, mem_cfg, "query", "agent")

        assert result == "\n\n---\n\nepisodic content"

    def test_returns_procedural_only(self):
        mem_cfg = _make_mem_cfg()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.return_value = None
        svc.retrieve_procedural_context.return_value = "procedural content"

        result = retrieve_memory_text(svc, scope, mem_cfg, "query", "agent")

        assert result == "\n\nprocedural content"

    def test_returns_combined_episodic_and_procedural(self):
        mem_cfg = _make_mem_cfg()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.return_value = "episodic"
        svc.retrieve_procedural_context.return_value = "procedural"

        result = retrieve_memory_text(svc, scope, mem_cfg, "query", "agent")

        assert "episodic" in result
        assert "procedural" in result
        assert "---" in result

    def test_episodic_returned_when_procedural_fails(self):
        mem_cfg = _make_mem_cfg()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.return_value = "episodic content"
        svc.retrieve_procedural_context.side_effect = RuntimeError("proc failed")

        result = retrieve_memory_text(svc, scope, mem_cfg, "query", "agent")

        assert "episodic content" in result

    def test_returns_empty_when_procedural_fails_no_episodic(self):
        mem_cfg = _make_mem_cfg()
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.return_value = None
        svc.retrieve_procedural_context.side_effect = ValueError("proc failed")

        result = retrieve_memory_text(svc, scope, mem_cfg, "query", "agent")

        assert result == ""

    def test_uses_shared_namespace_when_configured(self):
        mem_cfg = _make_mem_cfg(shared_namespace="shared_ns")
        shared_scope = MemoryScope(tenant_id="t1", agent_name="shared")
        scope = _base_scope()
        svc = MagicMock()
        svc.build_shared_scope.return_value = shared_scope
        svc.retrieve_with_shared.return_value = "shared memory"
        svc.retrieve_procedural_context.return_value = None

        result = retrieve_memory_text(svc, scope, mem_cfg, "query", "agent")

        svc.retrieve_with_shared.assert_called_once()
        svc.retrieve_context.assert_not_called()
        assert "shared memory" in result

    def test_no_shared_namespace_calls_retrieve_context(self):
        mem_cfg = _make_mem_cfg(shared_namespace=None)
        scope = _base_scope()
        svc = MagicMock()
        svc.retrieve_context.return_value = "mem"
        svc.retrieve_procedural_context.return_value = None

        retrieve_memory_text(svc, scope, mem_cfg, "query", "agent")

        svc.retrieve_context.assert_called_once()
        svc.retrieve_with_shared.assert_not_called()
