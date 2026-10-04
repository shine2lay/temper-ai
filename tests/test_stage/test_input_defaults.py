"""A declared input's ``default:`` (stage/input_defaults.py), and what a script gets for a value
that is not there (agent/script_agent.py).

Left out, null or empty text, an input gets its declared default; anything else is kept. An
input with no default is left exactly as the run sent it. A script never gets the word None:
pmf_evidence's assets_dir once arrived as the text 'None' and the run failed on a folder of
that name.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.stage.input_defaults import (
    declared_default,
    fill_input_defaults,
    is_missing,
    with_default,
)
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.stage_node import StageNode
from temper_ai.tools.base import ToolResult

REPO_CONFIGS = Path(__file__).resolve().parents[2] / "configs"

DECLARED = {
    "word": {"type": "string", "default": "from-the-default"},
    "must": {"type": "string", "required": True, "default": "required-but-defaulted"},
    "plain": {"type": "string"},
    "items": {"type": "array", "default": ["a", "b"]},
    "knobs": {"type": "object", "default": {"depth": 2}},
    "count": {"type": "integer", "default": 3},
    "flag": {"type": "boolean", "default": True},
}


# --- the helper ------------------------------------------------------------------------------


@pytest.mark.parametrize("given", [{}, {"word": None}, {"word": ""}], ids=["absent", "null", "empty"])
def test_left_out_null_or_empty_gets_the_declared_default(given):
    filled = fill_input_defaults(DECLARED, given)
    assert filled["word"] == "from-the-default"
    assert filled["must"] == "required-but-defaulted"  # required, but its default counts as given


@pytest.mark.parametrize("value", [
    "given", " ", "None", 0, 0.0, False, [], {}, ["x"], {"depth": 0}, [None], {"k": None},
])
def test_any_other_value_is_kept_exactly(value):
    for name in ("word", "items", "knobs", "count", "flag"):
        filled = fill_input_defaults(DECLARED, {name: value})
        assert filled[name] == value and type(filled[name]) is type(value), (name, value)


def test_lists_and_objects_given_are_kept_and_defaults_are_copies():
    given = {"items": ["mine"], "knobs": {"depth": 9, "extra": [1]}}
    filled = fill_input_defaults(DECLARED, given)
    assert filled["items"] == ["mine"] and filled["knobs"] == {"depth": 9, "extra": [1]}
    defaulted = fill_input_defaults(DECLARED, {})
    defaulted["items"].append("changed")
    defaulted["knobs"]["depth"] = 99
    # the next run still gets the declared default, not this run's edits of it
    assert fill_input_defaults(DECLARED, {})["items"] == ["a", "b"]
    assert fill_input_defaults(DECLARED, {})["knobs"] == {"depth": 2}
    assert DECLARED["items"]["default"] == ["a", "b"]


@pytest.mark.parametrize("given, expected", [
    ({}, {}),                         # left out stays left out: no key appears
    ({"plain": None}, {"plain": None}),
    ({"plain": ""}, {"plain": ""}),
    ({"plain": "text"}, {"plain": "text"}),
])
def test_an_input_with_no_default_is_left_as_sent(given, expected):
    filled = fill_input_defaults({"plain": {"type": "string"},
                                  "nulled": {"type": "string", "default": None}}, given)
    assert filled == expected


def test_inputs_not_declared_pass_through_and_the_given_dict_is_not_changed():
    given = {"word": "", "extra": "kept", "workspace_path": "/w"}
    filled = fill_input_defaults(DECLARED, given)
    assert filled["extra"] == "kept" and filled["workspace_path"] == "/w"
    assert given == {"word": "", "extra": "kept", "workspace_path": "/w"}
    assert filled is not given


@pytest.mark.parametrize("declared", [None, [], "word", {"word": "goal_text"}, {"word": None}])
def test_shapes_that_declare_no_defaults_change_nothing(declared):
    # a stage's `inputs: {word: goal_text}` names a source, not a schema
    assert fill_input_defaults(declared, {"word": ""}) == {"word": ""}
    assert fill_input_defaults(declared, None) == {}


def test_filling_twice_changes_nothing():
    once = fill_input_defaults(DECLARED, {"word": None, "plain": ""})
    assert fill_input_defaults(DECLARED, once) == once


def test_no_inputs_at_all_gets_every_default():
    filled = fill_input_defaults(DECLARED, None)
    assert filled == {"word": "from-the-default", "must": "required-but-defaulted",
                      "items": ["a", "b"], "knobs": {"depth": 2}, "count": 3, "flag": True}


def test_the_small_parts():
    assert is_missing(None) and is_missing("")
    assert not any(is_missing(v) for v in (" ", 0, False, [], {}, "None"))
    assert declared_default({"default": ""}) == (True, "")
    assert declared_default({"default": None}) == (False, None)
    assert declared_default({"type": "string"}) == (False, None)
    assert declared_default("source.name") == (False, None)
    assert with_default({"default": "d"}, "") == "d"
    assert with_default({"default": "d"}, "x") == "x"
    assert with_default({"type": "string"}, None) is None


# --- a nested stage's input gate ---------------------------------------------------------------


def _stage(inputs: dict) -> StageNode:
    return StageNode(NodeConfig.from_dict({"name": "inner", "type": "stage", "inputs": inputs,
                                           "nodes": []}), [])


def test_a_stage_whose_input_map_leaves_an_input_out_gets_the_stage_default():
    gated = _stage({"word": {"type": "string", "default": "from-the-stage-default"},
                    "plain": {"type": "string"}})._apply_input_gate({"plain": None})
    assert gated == {"word": "from-the-stage-default", "plain": None}


@pytest.mark.parametrize("given", [{}, {"must": None}, {"must": ""}])
def test_a_required_stage_input_with_a_default_counts_as_given(given):
    gated = _stage({"must": {"type": "string", "required": True, "default": "d"}})._apply_input_gate(
        given)
    assert gated == {"must": "d"}


def test_a_required_stage_input_with_no_default_is_still_refused_when_missing():
    with pytest.raises(ValueError, match=r"missing required input\(s\): must"):
        _stage({"must": {"type": "string", "required": True}})._apply_input_gate({})


def test_the_committed_ci_workflow_stage_gets_its_own_default():
    from temper_ai.cli.check import _FileConfigs
    from temper_ai.stage.loader import GraphLoader

    nodes, _ = GraphLoader(_FileConfigs(REPO_CONFIGS)).load_workflow(  # type: ignore[arg-type]
        "ci_input_defaults", inputs={})
    inner = {n.name: n for n in nodes}["inner"]
    assert inner._apply_input_gate({"must": "m", "plain": None}) == {
        "word": "from-the-stage-default", "must": "m", "plain": None}


# --- load time: template expansion -------------------------------------------------------------


def _store(configs: dict):
    st = MagicMock()

    def get(name, config_type):
        key = f"{config_type}:{name}"
        if key in configs:
            return configs[key]
        raise Exception(f"Config not found: {key}")

    st.get = MagicMock(side_effect=get)
    return st


FANNED = {
    "workflow:fan": {"name": "fan",
                     "inputs": {"count": {"type": "integer", "default": 2},
                                "label": {"type": "string", "default": "piece"}},
                     "nodes": [{"name": "fan", "type": "template", "for_each": "input.count",
                                "as": "i",
                                "template": [{"name": "make_{{ i }}", "type": "agent",
                                              "agent": "maker",
                                              "input_map": {"label": "{{ input.label }}-{{ i }}"}}]}]},
    "agent:maker": {"name": "maker", "type": "script", "script_template": "echo {{ label }}"},
}


@pytest.mark.parametrize("given", [{}, {"count": None, "label": None}, {"count": "", "label": ""}],
                         ids=["absent", "null", "empty"])
def test_a_template_node_expands_with_the_declared_defaults(given):
    from temper_ai.stage.loader import GraphLoader

    nodes, _ = GraphLoader(_store(FANNED)).load_workflow("fan", inputs=given)
    assert [n.name for n in nodes] == ["make_0", "make_1"]
    assert [n.config.input_map["label"] for n in nodes] == ["piece-0", "piece-1"]


def test_a_template_node_keeps_given_values():
    from temper_ai.stage.loader import GraphLoader

    nodes, _ = GraphLoader(_store(FANNED)).load_workflow("fan", inputs={"count": 3, "label": "x"})
    assert [n.config.input_map["label"] for n in nodes] == ["x-0", "x-1", "x-2"]


# --- scripts never get the word None -----------------------------------------------------------


def _real_context(tmp_path):
    """A context whose tool_executor genuinely runs Bash, in a throwaway workspace."""
    from temper_ai.tools.bash import Bash
    from temper_ai.tools.executor import ToolExecutor

    executor = ToolExecutor(workspace_root=str(tmp_path))
    executor.register_tools({"Bash": Bash(config={"workspace_root": str(tmp_path)})})
    ctx = MagicMock()
    ctx.run_id = "none-001"
    ctx.node_path = "n"
    ctx.agent_name = "a"
    ctx.workspace_path = str(tmp_path)
    ctx.skip_policies = None
    ctx.parent_event_id = None
    ctx.tool_executor = executor
    return ctx


NONE_SCRIPT = (
    'printf "quoted=[%s]\\n" {{ v }}\n'
    'printf "bare=[%s]\\n" "{{ v }}"\n'
    "python3 - <<'PY'\n"
    "import os\n"
    "print('env=[' + os.environ['{{ v | env }}'] + ']')\n"
    "PY\n"
)


@pytest.mark.parametrize("strict", [False, True])
def test_a_none_value_reaches_the_script_as_empty_text_in_every_form(tmp_path, strict):
    agent = ScriptAgent(config={"name": "s", "script_template": NONE_SCRIPT,
                                "strict_undefined": strict})
    result = agent.run({"v": None}, _real_context(tmp_path))
    assert result.status.value == "completed", result.error
    assert result.output == "quoted=[]\nbare=[]\nenv=[]\n"
    assert "None" not in result.output


def test_a_none_value_is_stored_as_empty_text_never_as_the_word():
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name, ctx.workspace_path = "r", "n", "a", "/tmp"
    ctx.tool_executor.execute.return_value = ToolResult(success=True, result="")
    ScriptAgent(config={"name": "s", "script_template": "echo {{ v }} {{ w }}"}).run(
        {"v": None, "w": 0}, ctx)
    env = ctx.tool_executor.execute.call_args[0][1]["env"]
    stashed = {k: v for k, v in env.items() if k.startswith("TEMPER_V")}
    assert sorted(stashed.values()) == ["", "0"]  # other values still go through as text
    assert "None" not in ctx.tool_executor.execute.call_args[0][1]["command"]


def test_strict_undefined_still_fails_only_a_name_that_does_not_exist():
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name, ctx.workspace_path = "r", "n", "a", "/tmp"
    ctx.tool_executor.execute.return_value = ToolResult(success=True, result="")
    agent = ScriptAgent(config={"name": "s", "script_template": "echo {{ there }} {{ gone }}",
                                "strict_undefined": True})
    result = agent.run({"there": None}, ctx)
    assert result.status.value == "failed"
    assert "undefined value" in result.error
    assert not ctx.tool_executor.execute.called
    assert agent.run({"there": None, "gone": None}, ctx).status.value == "completed"
