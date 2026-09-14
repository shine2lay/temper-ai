"""Tests for stage/template_expansion.py — load-time `type: template` nodes."""

import pytest

from temper_ai.stage.template_expansion import TemplateExpansionError, expand_templates


def _workflow(template_node):
    return {
        "workflow": {
            "name": "t",
            "nodes": [
                {"name": "plan", "type": "agent", "agent": "planner"},
                template_node,
            ],
        }
    }


class TestExpansion:
    def test_expands_n_times(self):
        raw = _workflow({
            "name": "lanes",
            "type": "template",
            "for_each": "input.n",
            "as": "i",
            "template": [{
                "name": "lane_{{ i }}",
                "type": "agent",
                "agent": "worker",
                "depends_on": ["plan"],
            }],
        })

        out = expand_templates(raw, {"n": 3})

        names = [n["name"] for n in out["workflow"]["nodes"]]
        assert names == ["plan", "lane_0", "lane_1", "lane_2"]

    def test_runtime_variables_survive_expansion(self):
        """Load-time expansion must not consume the agent's own variables.

        `{{ i }}` is substituted now; `{{ item }}` belongs to the agent's
        renderer at run time and used to abort the whole run with
        "'item' is undefined".
        """
        raw = _workflow({
            "name": "lanes",
            "type": "template",
            "for_each": "input.n",
            "as": "i",
            "template": [{
                "name": "lane_{{ i }}",
                "type": "agent",
                "agent": "worker",
                "task_template": "Lane {{ i }} about {{ item }} ({{ thing.name }})",
            }],
        })

        out = expand_templates(raw, {"n": 1})

        lane = out["workflow"]["nodes"][1]
        assert lane["name"] == "lane_0"
        assert lane["task_template"] == "Lane 0 about {{ item }} ({{ thing.name }})"

    def test_raw_block_still_supported(self):
        raw = _workflow({
            "name": "lanes",
            "type": "template",
            "for_each": 1,
            "as": "i",
            "template": [{
                "name": "lane_{{ i }}",
                "type": "agent",
                "agent": "worker",
                "task_template": "{% raw %}{{ item }}{% endraw %}",
            }],
        })

        out = expand_templates(raw, {})

        assert out["workflow"]["nodes"][1]["task_template"] == "{{ item }}"

    def test_missing_for_each_input_still_errors(self):
        raw = _workflow({
            "name": "lanes",
            "type": "template",
            "for_each": "input.missing",
            "as": "i",
            "template": [{"name": "lane_{{ i }}", "type": "agent", "agent": "worker"}],
        })

        with pytest.raises(TemplateExpansionError):
            expand_templates(raw, {"n": 1})
