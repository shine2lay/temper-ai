"""The validation engine's configs fit together: every script step parses under /bin/sh, the model steps
keep Claude Code's own tools, every template variable is fed by the workflow, and every condition and
output names a field the engine really prints (a misspelt one would silently skip a step)."""

import subprocess

import pytest
import yaml
from jinja2 import BaseLoader, ChainableUndefined, meta
from jinja2.sandbox import SandboxedEnvironment

from temper_ai.agent.script_agent import (
    BARE_FILTER,
    ENV_FILTER,
    QUOTED_FILTER,
    _rewrite_interpolations,
    _ValueStash,
)
from temper_ai.config.helpers import substitute_env_vars

from .conftest import ENGINE, run_ve

AGENTS = sorted((ENGINE / "agents").glob("*.yaml"))
WORKFLOW = ENGINE / "workflows" / "validation_engine.yaml"
INJECTED = {"workspace_path", "run_id"}  # the script agent adds these to every template


def served(path):
    """The config as the server hands it out (ConfigStore.get runs the env substitution)."""
    return substitute_env_vars(yaml.safe_load(path.read_text()))


def agent(path):
    return served(path)["agent"]


def workflow():
    return served(WORKFLOW)["workflow"]


def template_of(cfg):
    return cfg["script_template"] if cfg.get("type") == "script" else cfg["task_template"]


def test_every_step_of_the_spec_is_there():
    names = {agent(p)["name"] for p in AGENTS}
    assert {"ve_page", "ve_deploy", "ve_campaign", "ve_collect", "ve_decide", "ve_interview"} <= names
    assert {p.stem for p in AGENTS} == names, "each agent file is named after its agent"
    nodes = {n["name"]: n for n in workflow()["nodes"]}
    assert {n["agent"] for n in nodes.values()} == names, "the workflow runs every agent, and only these"


@pytest.mark.parametrize("path", [p for p in AGENTS if agent(p).get("type") == "script"], ids=lambda p: p.stem)
def test_every_script_step_parses_under_sh(path):
    cfg = agent(path)
    stash = _ValueStash()
    env = SandboxedEnvironment(loader=BaseLoader(), undefined=ChainableUndefined)
    env.filters[QUOTED_FILTER] = stash.quoted
    env.filters[BARE_FILTER] = stash.bare
    env.filters[ENV_FILTER] = stash.name
    script = env.from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render()
    done = subprocess.run(["sh", "-n", "-c", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, f"{path.name} does not parse under /bin/sh: {done.stderr.strip()}"
    assert "${" not in path.read_text(), "the config store would substitute it as an env var"


@pytest.mark.parametrize("path", [p for p in AGENTS if agent(p).get("type") != "script"], ids=lambda p: p.stem)
def test_the_model_steps_keep_claude_codes_own_tools(path):
    cfg = agent(path)
    assert cfg["provider"] == "claude"
    assert "tools" not in cfg, "provider claude refuses temper tool schemas; it uses its own Bash/Read/Write/Web tools"


def test_every_template_variable_is_fed_by_the_workflow():
    by_agent = {agent(p)["name"]: agent(p) for p in AGENTS}
    env = SandboxedEnvironment()
    for node in workflow()["nodes"]:
        used = meta.find_undeclared_variables(env.parse(template_of(by_agent[node["agent"]])))
        fed = set(node.get("input_map") or {}) | INJECTED
        assert used <= fed, f"{node['name']} uses {sorted(used - fed)} that the workflow never passes"


def test_conditions_inputs_and_outputs_name_fields_the_engine_prints(dry_run, tmp_path):
    blocked = run_ve("decide", "--dir", str(tmp_path / "none"), "--stop", "live mode needs rails")
    printed = {
        "ve_setup": set(dry_run["setup"]),
        "ve_decide": set(dry_run["decide"]) & set(blocked),  # a stopped run prints the same fields
    }
    wf = workflow()
    refs = [n["condition"]["source"] for n in wf["nodes"] if n.get("condition")]
    refs += [v for n in wf["nodes"] for v in (n.get("input_map") or {}).values() if isinstance(v, str)]
    refs += list(wf["outputs"].values())
    for ref in refs:
        node, _, field = ref.partition(".structured.")
        if node in printed:
            assert field in printed[node], f"{ref}: {node} never prints `{field}`"
        else:
            assert ref.startswith("input.") and ref.split(".", 1)[1] in wf["inputs"], f"{ref} is not a workflow input"


def test_live_steps_run_only_on_the_live_flag():
    nodes = {n["name"]: n for n in workflow()["nodes"]}
    assert nodes["ve_campaign"]["condition"] == {"source": "ve_setup.structured.live", "operator": "equals", "value": True}
    assert nodes["ve_simulate"]["condition"]["source"] == "ve_setup.structured.simulate"
    assert nodes["ve_interview"]["condition"]["source"] == "ve_decide.structured.run_interview"
    assert "condition" not in nodes["ve_decide"], "the verdict (or the rails checklist) is always written"
