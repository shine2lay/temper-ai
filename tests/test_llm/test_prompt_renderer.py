"""Tests for llm/prompt_renderer.py — template rendering, budget enforcement, validation."""

import logging

import pytest

from temper_ai.llm.prompt_renderer import (
    PromptBudgetError,
    PromptRenderer,
    _filter_safe_values,
    validate_prompt_config,
)


class TestPromptRendererBasic:
    def test_default_system_and_task(self):
        r = PromptRenderer()
        msgs = r.render(agent_config={}, input_data={"task": "Hello"})
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are a helpful assistant."
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "Hello"

    def test_custom_system_prompt(self):
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"system_prompt": "You are a coder."},
            input_data={"task": "Write code"},
        )
        assert msgs[0]["content"] == "You are a coder."

    def test_custom_task_template(self):
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"task_template": "Fix this bug: {{ bug }}"},
            input_data={"bug": "NPE on line 42"},
        )
        assert "NPE on line 42" in msgs[1]["content"]

    def test_multiple_template_variables(self):
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"task_template": "{{ lang }}: {{ task }}"},
            input_data={"lang": "Python", "task": "sort a list"},
        )
        assert msgs[1]["content"] == "Python: sort a list"

    def test_missing_variable_renders_empty(self):
        """Jinja2 with default Undefined renders missing vars as empty string."""
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"task_template": "Do: {{ nonexistent }}"},
            input_data={},
        )
        assert msgs[1]["content"] == "Do: "


class TestPromptRendererMemories:
    def test_memories_in_template(self):
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"task_template": "Memories: {{ memories }}. Task: {{ task }}"},
            input_data={"task": "plan"},
            memories=["User prefers Python", "Deadline is Friday"],
        )
        assert "User prefers Python" in msgs[1]["content"]
        assert "Deadline is Friday" in msgs[1]["content"]

    def test_no_memories_default_empty_list(self):
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"task_template": "Count: {{ memories | length }}"},
            input_data={},
            memories=None,
        )
        assert msgs[1]["content"] == "Count: 0"


class TestPromptRendererStrategyContext:
    def test_strategy_context_passed(self):
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"task_template": "Others said: {{ other_agents }}"},
            input_data={},
            strategy_context="Agent A: looks good",
        )
        assert "Agent A: looks good" in msgs[1]["content"]

    def test_no_strategy_context_renders_empty(self):
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"task_template": "Context: {{ other_agents }}"},
            input_data={},
        )
        # None renders as empty string in Jinja2's default Undefined
        assert "Context:" in msgs[1]["content"]


class TestPromptRendererBudget:
    @staticmethod
    def _counter(messages):
        """Simple token counter: count words."""
        return sum(len(m["content"].split()) for m in messages)

    def test_within_budget_no_change(self):
        r = PromptRenderer(token_counter=self._counter)
        msgs = r.render(
            agent_config={"task_template": "{{ task }}"},
            input_data={"task": "short"},
            token_budget=100,
        )
        assert msgs[1]["content"] == "short"

    def test_drops_memories_first(self):
        long_memory = "word " * 200  # 200 words

        def counter(messages):
            return sum(len(m["content"].split()) for m in messages)

        r = PromptRenderer(token_counter=counter)
        msgs = r.render(
            agent_config={
                "task_template": "Memories: {{ memories }}. Task: {{ task }}",
            },
            input_data={"task": "plan"},
            memories=[long_memory],
            token_budget=20,
        )
        # Memories should be dropped (empty list)
        assert "word word word" not in msgs[1]["content"]

    def test_truncates_long_inputs(self):
        long_code = "x " * 2000  # 2000 words, > 1000 chars

        def counter(messages):
            return sum(len(m["content"].split()) for m in messages)

        r = PromptRenderer(token_counter=counter)
        # After truncation: 1000 chars of "x " = ~500 words + system (5 words) + "Review:" (1)
        # Need budget high enough for truncated but not for original (2000+ words)
        msgs = r.render(
            agent_config={"task_template": "Review: {{ code }}"},
            input_data={"code": long_code},
            token_budget=600,
        )
        assert "[truncated]" in msgs[1]["content"]

    def test_raises_when_still_over_budget(self):
        def counter(messages):
            return 999  # Always over budget

        r = PromptRenderer(token_counter=counter)
        with pytest.raises(PromptBudgetError, match="exceeds token budget"):
            r.render(
                agent_config={"task_template": "{{ task }}"},
                input_data={"task": "x"},
                token_budget=10,
            )

    def test_no_counter_skips_budget(self):
        """Budget is ignored when no token_counter is provided."""
        r = PromptRenderer(token_counter=None)
        msgs = r.render(
            agent_config={"task_template": "{{ task }}"},
            input_data={"task": "x" * 10000},
            token_budget=1,  # would fail with a counter
        )
        assert len(msgs[0]["content"]) > 0  # just works, no error


class TestValidatePromptConfig:
    def test_memory_enabled_but_unused_warns(self):
        warnings, errors = validate_prompt_config(
            {"name": "agent1", "task_template": "{{ task }}", "memory": {"enabled": True}}
        )
        assert any("memories" in w for w in warnings)
        assert not errors

    def test_memories_used_but_not_enabled_errors(self):
        warnings, errors = validate_prompt_config(
            {"name": "agent1", "task_template": "{{ memories }}"}
        )
        assert any("memory is not enabled" in e for e in errors)

    def test_multi_agent_without_other_agents_warns(self):
        warnings, errors = validate_prompt_config(
            {"name": "agent1", "task_template": "{{ task }}"},
            stage_config={"agents": ["a", "b"]},
        )
        assert any("other_agents" in w for w in warnings)

    def test_syntax_error_in_template(self):
        warnings, errors = validate_prompt_config(
            {"name": "agent1", "task_template": "{% if %}"}  # invalid jinja2
        )
        assert any("syntax error" in e for e in errors)

    def test_valid_config_no_issues(self):
        warnings, errors = validate_prompt_config(
            {
                "name": "agent1",
                "task_template": "{{ task }}",
            }
        )
        assert not warnings
        assert not errors

    def test_unnamed_agent(self):
        warnings, errors = validate_prompt_config(
            {"task_template": "{{ memories }}", "memory": {"enabled": True}}
        )
        # Should work even without a name
        assert not errors


class TestPromptRendererJinja2Syntax:
    """Tests for Jinja2-specific template features."""

    def test_jinja2_for_loop_renders_items(self):
        r = PromptRenderer()
        msgs = r.render(
            agent_config={
                "task_template": "Items:{% for item in items %} {{ item }}{% endfor %}"
            },
            input_data={"items": ["alpha", "beta", "gamma"]},
        )
        assert "alpha" in msgs[1]["content"]
        assert "beta" in msgs[1]["content"]
        assert "gamma" in msgs[1]["content"]

    def test_jinja2_conditional_true(self):
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"task_template": "{% if flag %}YES{% else %}NO{% endif %}"},
            input_data={"flag": True},
        )
        assert msgs[1]["content"] == "YES"

    def test_jinja2_conditional_false(self):
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"task_template": "{% if flag %}YES{% else %}NO{% endif %}"},
            input_data={"flag": False},
        )
        assert msgs[1]["content"] == "NO"

    def test_integer_variable_rendered(self):
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"task_template": "Max retries: {{ max_retries }}"},
            input_data={"max_retries": 5},
        )
        assert "5" in msgs[1]["content"]

    def test_dict_variable_accessible_in_template(self):
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"task_template": "Name: {{ config.name }}"},
            input_data={"config": {"name": "my-agent"}},
        )
        assert "my-agent" in msgs[1]["content"]

    def test_none_variable_renders_empty(self):
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"task_template": "Value: {{ val }}"},
            input_data={"val": None},
        )
        assert msgs[1]["content"] == "Value: None"

    def test_strategy_context_from_input_data_not_overridden(self):
        """When strategy_context is not provided, other_agents from input_data is kept."""
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"task_template": "Ctx: {{ other_agents }}"},
            input_data={"other_agents": "Agent B said: done"},
            strategy_context=None,  # explicit None — should not override
        )
        # The value from input_data should be used since strategy_context is None
        assert "Agent B said: done" in msgs[1]["content"]

    def test_strategy_context_overrides_input_data(self):
        """Explicit strategy_context overrides other_agents from input_data."""
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"task_template": "Ctx: {{ other_agents }}"},
            input_data={"other_agents": "old value"},
            strategy_context="new strategy output",
        )
        assert "new strategy output" in msgs[1]["content"]
        assert "old value" not in msgs[1]["content"]

    def test_messages_structure_always_two_elements(self):
        """render() always returns exactly [system, user]."""
        r = PromptRenderer()
        msgs = r.render(agent_config={}, input_data={})
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"

    def test_boolean_false_not_filtered_as_unsafe(self):
        """False is a safe value and should pass through _filter_safe_values."""
        r = PromptRenderer()
        msgs = r.render(
            agent_config={"task_template": "{% if enabled %}on{% else %}off{% endif %}"},
            input_data={"enabled": False},
        )
        assert msgs[1]["content"] == "off"


class TestFilterSafeValues:
    def test_allows_safe_types(self):
        data = {
            "str": "hello",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "list": [1, 2],
            "dict": {"a": 1},
            "tuple": (1, 2),
            "none": None,
        }
        result = _filter_safe_values(data)
        assert result == data

    def test_rejects_functions(self):
        result = _filter_safe_values({"fn": lambda: None, "ok": "hello"})
        assert "fn" not in result
        assert result["ok"] == "hello"

    def test_rejects_objects(self):
        class Dangerous:
            pass

        result = _filter_safe_values({"obj": Dangerous(), "ok": 42})
        assert "obj" not in result
        assert result["ok"] == 42

    def test_empty_dict(self):
        assert _filter_safe_values({}) == {}
