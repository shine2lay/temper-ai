"""The positioning workflow (configs/workflows/positioning.yaml, Product marketing) fits together.

It drafts a product's positioning from an evidence folder in the run workspace: a setup script
checks the inputs and stages positioning_grade's FORMAT.md, rubric.md and checker; four model steps
write the competitive alternatives, the attributes and value, the segment and category, and the
document with its messaging hierarchy; a check script derives positioning.json and runs
positioning_grade's own checker, and a reviser fixes only what it found, at most twice. The
evidence folder comes from configs/marketing/bin/gather_evidence.py, run on the host. Here: the
configs run in that order with the right conditions, the scripts parse under /bin/sh and are fed
every value they use, the model steps keep Claude Code's own tools and work from the files only,
the setup and check steps do what the writers rely on, positioning.json is derived the way the
grade reads it, and gather_evidence.py copies sources with their origin and refuses what it must.
No model and no network.
"""

import json
import os
import shutil
import subprocess
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

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

ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = ROOT / "configs" / "agents"
WORKFLOW = ROOT / "configs" / "workflows" / "positioning.yaml"
TOOLS = AGENTS_DIR / "positioning_assets" / "positioning_tools.py"
GRADE_ASSETS = AGENTS_DIR / "positioning_grade_assets"
GATHER = ROOT / "configs" / "marketing" / "bin" / "gather_evidence.py"
BENCH = ROOT / "tests" / "test_positioning_grade" / "benchmark"
WRITERS = ["positioning_alternatives", "positioning_value", "positioning_segment", "positioning_hierarchy"]
SCRIPTS = ["positioning_setup", "positioning_check"]
MODEL_STEPS = [*WRITERS, "positioning_reviser"]
AGENTS = [AGENTS_DIR / f"{name}.yaml" for name in [*SCRIPTS, *MODEL_STEPS]]
INJECTED = {"workspace_path", "run_id"}  # the script agent adds these to every template
READY = {"source": "setup.structured.status", "operator": "equals", "value": "ready"}


def served(path):
    """The config as the server hands it out (ConfigStore.get runs the env substitution)."""
    return substitute_env_vars(yaml.safe_load(path.read_text()))


def by_name(name):
    return served(AGENTS_DIR / f"{name}.yaml")["agent"]


def workflow():
    return served(WORKFLOW)["workflow"]


def templates_of(cfg):
    if cfg.get("type") == "script":
        return [cfg["script_template"]]
    return [cfg["task_template"], cfg.get("system_prompt", "")]


def jinja(stash=None):
    """Jinja as the script agent sets it up, with its value filters."""
    env = SandboxedEnvironment(loader=BaseLoader(), undefined=ChainableUndefined)
    stash = stash if stash is not None else _ValueStash()
    env.filters[QUOTED_FILTER] = stash.quoted
    env.filters[BARE_FILTER] = stash.bare
    env.filters[ENV_FILTER] = stash.name
    return env


def load(path, name):
    """A helper script loaded as a module, without leaving bytecode next to it."""
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module


gatherer = load(GATHER, "gather_evidence")


def step(name, workspace, **values):
    """A script step rendered the way the script agent renders it and run by /bin/sh."""
    cfg = by_name(name)
    stash = _ValueStash()
    script = jinja(stash).from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render(
        workspace_path=str(workspace), **values)
    env = {**os.environ, **stash.env, "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=120, cwd=workspace, env=env)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def staged(tmp_path, key="run"):
    """A run workspace as a candidate trial stages it: the evidence folder and the tools in _assets."""
    workspace = tmp_path / key
    shutil.copytree(BENCH / "evidence", workspace / "evidence")
    (workspace / "_assets").mkdir()
    shutil.copyfile(TOOLS, workspace / "_assets" / "positioning_tools.py")
    return workspace


def values(**more):
    return {"assets_dir": "_assets", "grade_assets_dir": str(GRADE_ASSETS), **more}


def setup(workspace, **more):
    return step("positioning_setup", workspace, **values(**{"product": "Kettlemark", "evidence_dir": "evidence",
                                                            "document": None, **more}))


def sound_document(workspace):
    """The benchmark's sound control C1, as if the writers had written it."""
    shutil.copyfile(BENCH / "sources" / "c1" / "positioning.md", workspace / "positioning.md")
    return workspace / "positioning.md"


# ---- the configs ---------------------------------------------------------------------------------


def test_the_workflow_runs_the_stages_in_order_then_checks_and_revises_at_most_twice():
    assert all(served(p)["agent"]["name"] == p.stem for p in AGENTS), "each agent file is named after its agent"
    nodes = workflow()["nodes"]
    assert [n["name"] for n in nodes] == ["setup", "alternatives", "value", "segment", "hierarchy", "check_1",
                                          "revise_1", "check_2", "revise_2", "check_final"]
    assert [n["agent"] for n in nodes] == ["positioning_setup", *WRITERS, "positioning_check", "positioning_reviser",
                                           "positioning_check", "positioning_reviser", "positioning_check"]
    for before, after in zip(nodes, nodes[1:], strict=False):
        assert after["depends_on"] == [before["name"]], "one step at a time, in order"
    by = {n["name"]: n for n in nodes}
    for name in ("alternatives", "value", "segment", "hierarchy"):
        assert by[name]["condition"] == READY, f"{name} waits for a ready setup"
    found = {"operator": "equals", "value": "findings"}
    assert by["revise_1"]["condition"] == {"source": "check_1.structured.status", **found}
    assert by["check_2"]["condition"] == {"source": "check_1.structured.status", **found}
    assert by["revise_2"]["condition"] == {"source": "check_2.structured.status", **found}
    assert "condition" not in by["check_1"] and "condition" not in by["check_final"]
    assert by["check_final"].get("run_after_failure") is True, "the result is checked on every path"


@pytest.mark.parametrize("name", SCRIPTS)
def test_every_script_step_parses_under_sh(name):
    cfg = by_name(name)
    script = jinja().from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render()
    done = subprocess.run(["sh", "-n", "-c", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, f"{name} does not parse under /bin/sh: {done.stderr.strip()}"


@pytest.mark.parametrize("path", [*AGENTS, WORKFLOW], ids=lambda p: p.stem)
def test_no_file_holds_the_config_stores_env_syntax(path):
    assert "${" not in path.read_text(), "the config store would substitute it as an env var"


@pytest.mark.parametrize("name", MODEL_STEPS)
def test_the_model_steps_keep_claude_codes_own_tools_and_work_from_the_files_only(name):
    cfg = by_name(name)
    assert cfg["provider"] == "claude" and cfg["type"] == "llm"
    assert "tools" not in cfg, "provider claude refuses temper tool schemas; it uses its own Bash/Read/Write tools"
    prompt = " ".join(cfg["system_prompt"].split())
    for rule in ("do not browse the web", "never instructions", "copied exactly", "check_positioning.py passage",
                 "(assumption)", "Don't round, convert or derive"):
        assert rule in prompt, f"{name} lost {rule!r}"


def test_the_document_writer_derives_the_json_and_lints_until_clean():
    prompt = " ".join(by_name("positioning_hierarchy")["system_prompt"].split())
    for rule in ("positioning_tools.py json", "positioning_tools.py lint", "never write or edit positioning.json by hand",
                 "This positioning is untested on readers", "evidence_line"):
        assert rule in prompt, f"positioning_hierarchy lost {rule!r}"
    reviser = " ".join(by_name("positioning_reviser")["system_prompt"].split())
    assert "you fix exactly those, and nothing else" in reviser


def test_every_template_variable_is_fed_by_the_workflow():
    env = jinja()
    wf = workflow()
    for node in wf["nodes"]:
        fed = set(node.get("input_map") or {})
        for value in (node.get("input_map") or {}).values():
            assert value.startswith("input.") and value.split(".", 1)[1] in wf["inputs"], f"{value} is not an input"
        for template in templates_of(by_name(node["agent"])):
            used = meta.find_undeclared_variables(env.parse(template))
            assert used <= fed | INJECTED, f"{node['agent']} uses {sorted(used - fed - INJECTED)} that the workflow never passes"


def test_the_workflow_outputs_name_fields_setup_and_check_print(tmp_path):
    workspace = staged(tmp_path)
    printed = {"setup": set(setup(workspace))}
    sound_document(workspace)
    printed["check_final"] = set(step("positioning_check", workspace, **values()))
    for ref in workflow()["outputs"].values():
        node, _, field = ref.partition(".structured.")
        assert field in printed.get(node, set()), f"{ref}: {node} never prints `{field}`"


def test_departments_names_the_workflow_its_agents_and_the_gather_script():
    text = (ROOT / "docs" / "departments.md").read_text()
    for name in ("positioning", *WRITERS, "positioning_reviser", "gather_evidence.py"):
        assert f"`{name}`" in text or name in text, f"docs/departments.md doesn't name {name}"


# ---- setup and check -------------------------------------------------------------------------------


def test_setup_stages_the_grades_own_files_and_an_evidence_index(tmp_path):
    workspace = staged(tmp_path)
    out = setup(workspace)
    assert out["status"] == "ready" and out["files"] == 8 and out["document"] == "positioning.md"
    state = workspace / "state" / "positioning"
    for name in ("FORMAT.md", "rubric.md", "check_positioning.py"):
        assert (state / "tools" / name).read_bytes() == (GRADE_ASSETS / name).read_bytes()
    assert (state / "tools" / "positioning_tools.py").read_bytes() == TOOLS.read_bytes()
    assert (state / "FORMAT.md").is_file() and (state / "rubric.md").is_file()
    saved = json.loads((state / "setup.json").read_text())
    assert saved["evidence_line"] == "Evidence: evidence" and saved["json"] == "positioning.json"
    index = (state / "evidence_index.md").read_text()
    assert all(f"| {p.relative_to(BENCH / 'evidence').as_posix()} |" in index
               for p in (BENCH / "evidence").rglob("*") if p.is_file())


def test_setup_puts_the_evidence_line_relative_to_the_document(tmp_path):
    workspace = staged(tmp_path)
    out = setup(workspace, document="out/kettlemark.md")
    assert out["status"] == "ready"
    saved = json.loads((workspace / "state" / "positioning" / "setup.json").read_text())
    assert saved["evidence_line"] == "Evidence: ../evidence" and saved["json"] == "out/positioning.json"


@pytest.mark.parametrize("given, problem", [
    ({"product": None}, "no product name"),
    ({"product": "two\nlines"}, "one short line"),
    ({"evidence_dir": "nowhere"}, "no evidence folder"),
    ({"evidence_dir": "/etc"}, "outside the run workspace"),
    ({"evidence_dir": "../elsewhere"}, "leaves the run workspace"),
    ({"document": "positioning.txt"}, "must be a .md file"),
    ({"grade_assets_dir": "/nonexistent"}, "missing /nonexistent/FORMAT.md"),
])
def test_setup_stops_at_no_cost_on_a_bad_input(tmp_path, given, problem):
    workspace = staged(tmp_path)
    inputs = values(product="Kettlemark", evidence_dir="evidence", document=None)
    inputs.update(given)
    out = step("positioning_setup", workspace, **inputs)
    assert out["status"] == "not_ready" and problem in out["problems"][0], out
    assert not (workspace / "state" / "positioning" / "setup.json").exists()


def test_setup_refuses_a_workspace_that_already_holds_a_positioning(tmp_path):
    workspace = staged(tmp_path)
    sound_document(workspace)
    assert "already exists" in setup(workspace)["problems"][0]
    used = staged(tmp_path, "used")
    assert setup(used)["status"] == "ready"
    assert "fresh workspace" in setup(used)["problems"][0]


def test_the_check_finds_nothing_on_a_sound_document_and_numbers_its_rounds(tmp_path):
    workspace = staged(tmp_path)
    setup(workspace)
    sound_document(workspace)
    first = step("positioning_check", workspace, **values())
    assert first["status"] == "clean" and first["round"] == "1" and first["findings"] == 0, first
    second = step("positioning_check", workspace, **values())
    assert second["round"] == "2" and (workspace / "state" / "positioning" / "check_2.md").is_file()


def test_the_check_names_each_defect_with_its_line_for_the_reviser(tmp_path):
    workspace = staged(tmp_path)
    setup(workspace)
    doc = sound_document(workspace)
    text = doc.read_text()
    quote = text.split('"')[1]
    doc.write_text(text.replace(quote, quote + " and more", 1))
    out = step("positioning_check", workspace, **values())
    assert out["status"] == "findings" and out["citation_failures"] == 1 and out["kinds"] == {"quote_not_found": 1}
    report = (workspace / "state" / "positioning" / "check_1.md").read_text()
    line = next(n for n, row in enumerate(doc.read_text().split("\n"), 1) if quote + " and more" in row)
    assert f"quote_not_found, line {line}" in report and f"line {line}: " in report


def test_the_check_reports_not_checked_without_setup_or_document(tmp_path):
    workspace = staged(tmp_path)
    out = step("positioning_check", workspace, **values())
    assert out["status"] == "not_checked" and "setup did not finish" in out["problems"][0]
    setup(workspace)
    out = step("positioning_check", workspace, **values())
    assert out["status"] == "not_checked" and "no document" in out["problems"][0]


def test_positioning_json_is_derived_the_way_the_grade_reads_it(tmp_path):
    workspace = staged(tmp_path)
    setup(workspace)
    sound_document(workspace)
    done = subprocess.run(["python3", str(TOOLS), "--checker", str(GRADE_ASSETS / "check_positioning.py"),
                           "json", "--doc", "positioning.md"], cwd=workspace, capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    derived = json.loads((workspace / "positioning.json").read_text())
    assert derived == json.loads((BENCH / "sources" / "c1" / "positioning.json").read_text())
    lint = subprocess.run(["python3", "state/positioning/tools/positioning_tools.py", "lint", "--doc",
                           "positioning.md", "--evidence", "evidence"], cwd=workspace, capture_output=True,
                          text=True, timeout=60)
    assert lint.returncode == 0 and "0 findings" in lint.stdout, lint.stdout


# ---- gather_evidence.py ------------------------------------------------------------------------------


def gather_into(tmp_path, sources, out="evidence"):
    spec = tmp_path / "sources.json"
    spec.write_text(json.dumps({"product": "Example", "sources": sources}))
    return gatherer.gather(spec, tmp_path / out)


def test_gather_copies_each_source_with_its_origin_and_writes_an_index(tmp_path):
    doc = tmp_path / "guide.md"
    doc.write_text("# Guide\n\nOpening line.\n\n## 1. Setup\nStep one.\n```\n## not a heading\n```\n"
                   "## 2. Limits\nIt needs Linux.\npassword: hunter2\n## 3. Other\nLeft out.\n")
    manifest = gather_into(tmp_path, [
        {"kind": "file", "path": str(doc), "as": "docs/whole.md"},
        {"kind": "file", "path": str(doc), "as": "docs/limits.md", "sections": ["## 2."], "intro": True,
         "exclude": "(?i)password", "note": "the makers' guide"},
        {"kind": "file", "path": str(doc), "as": "lines.md", "lines": "5-6"},
        {"kind": "excerpt", "path": str(doc), "match": "Linux", "as": "excerpt.md"},
        {"kind": "file", "path": str(doc), "as": "alt/page.md", "origin": "https://example.com/x",
         "captured": "2026-10-04"}])
    out = tmp_path / "evidence"
    assert sorted(manifest["files"]) == ["alt/page.md", "docs/limits.md", "docs/whole.md", "excerpt.md",
                                         "index.md", "lines.md"]
    limits = (out / "docs/limits.md").read_text()
    head, _, body = limits.partition("\n---\n\n")
    assert head.startswith(f"Source: {doc}") or head.startswith("Source: ~")
    assert "1 lines matching" in head and "Note: the makers' guide" in head
    assert "Opening line." in body and "It needs Linux." in body
    assert "hunter2" not in body and "Step one." not in body and "Left out." not in body
    assert "## not a heading" in (out / "docs/whole.md").read_text()
    assert (out / "lines.md").read_text().rstrip().endswith("Step one.")
    page = (out / "alt/page.md").read_text()
    assert page.startswith("Source: https://example.com/x\nCaptured: 2026-10-04\n")
    index = (out / "index.md").read_text()
    assert "| docs/limits.md |" in index and "| alt/page.md | https://example.com/x |" in index


@pytest.mark.parametrize("name", ["dev-secrets.env", ".env", "trades.db", "auth.json", "api_token.txt",
                                  "server.key", "id_ed25519"])
def test_gather_refuses_files_that_look_like_secrets_or_databases(tmp_path, name):
    path = tmp_path / name
    path.write_text("x\n")
    with pytest.raises(gatherer.GatherError, match="secret or a database"):
        gather_into(tmp_path, [{"kind": "file", "path": str(path), "as": "x.md"}])


@pytest.mark.parametrize("source, problem", [
    ({"kind": "file", "path": "x", "as": "../x.md"}, "relative path inside the folder"),
    ({"kind": "file", "path": "x", "as": "/x.md"}, "relative path inside the folder"),
    ({"kind": "file", "path": "x", "as": "index.md"}, "relative path inside the folder"),
    ({"kind": "ftp", "as": "x.md"}, "is not one of"),
    ({"kind": "excerpt", "path": "x", "as": "x.md"}, "missing match"),
])
def test_gather_checks_the_sources_file_first(tmp_path, source, problem):
    with pytest.raises(gatherer.GatherError, match=problem.replace("(", r"\(")):
        gather_into(tmp_path, [source])


def test_gather_refuses_a_folder_that_is_not_empty(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("a\n")
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "old.md").write_text("old\n")
    with pytest.raises(gatherer.GatherError, match="not empty"):
        gather_into(tmp_path, [{"kind": "file", "path": str(doc), "as": "a.md"}])


def test_html_becomes_plain_text_without_scripts_or_navigation():
    title, text = gatherer.html_to_text(
        "<html><head><title>Plans</title><script>var x = 1;</script><style>p{}</style></head><body>"
        "<nav>Home | Login</nav><h1>Pricing</h1><p>Free for <b>one</b> user.</p><ul><li>Pro: $10</li></ul>"
        "</body></html>")
    assert title == "Plans"
    assert "var x" not in text and "p{}" not in text and "Login" not in text
    assert "Pricing" in text and "Free for one user." in text and "Pro: $10" in text


def run_row(n, name, status, cost=1.0, seconds=60.0, start=None):
    return {"id": f"r{n}", "workflow_name": name, "status": status, "total_cost_usd": cost,
            "duration_seconds": seconds, "start_time": (start or datetime.now(UTC)).replace(tzinfo=None).isoformat()}


def test_stats_count_completed_share_and_medians_over_completed_runs():
    rows = [run_row(1, "a", "completed", 1.0, 60), run_row(2, "a", "completed", 3.0, 180),
            run_row(3, "a", "failed", 9.0, 600), run_row(4, "a", "running", 0, None),
            run_row(5, "b", "cancelled", 0, 5)]
    table, total = gatherer.stats_table(rows)
    assert table[2] == "| a | 4 | 2 | 1 | 0 | 66.7% | $2.00 | 2.0 |"
    assert table[3] == "| b | 1 | 0 | 0 | 1 | 0.0% | - | - |"
    assert (total["runs"], total["completed"], total["share"], total["cost"], total["workflows"]) == (
        5, 2, "50.0%", "$2.00", 2)


def test_stats_say_plainly_when_the_list_does_not_reach_back_far_enough(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    rows = [run_row(1, "a", "completed", start=(now - timedelta(days=3)).replace(second=0, microsecond=0)),
            run_row(2, "a", "completed", start=now - timedelta(hours=1)),
            run_row(3, "a", "completed", start=now + timedelta(hours=1))]
    monkeypatch.setattr(gatherer, "listed_runs", lambda api: (rows, [f"{api}/api/workflows?limit=1000&offset=0"]))
    raw = tmp_path / "raw.json"
    text, origin = gatherer.gather_temper_stats({"api": "http://server", "days": 30, "raw": str(raw)})
    assert origin == "http://server"
    assert "Query: GET http://server/api/workflows?limit=1000&offset=0" in text
    assert "not the 30 asked for" in text and "Totals: 2 runs of 1 workflows" in text
    saved = json.loads(raw.read_text())
    assert [r["id"] for r in saved["runs"]] == ["r1", "r2"], "a run is in the window from its first whole minute"


def test_listed_runs_keeps_each_run_once_while_the_list_grows(monkeypatch):
    pages = {0: [{"id": "c"}, {"id": "b"}], 2: [{"id": "b"}, {"id": "a"}], 4: [{"id": "z"}]}
    monkeypatch.setattr(gatherer, "fetch_json", lambda url: {"runs": pages[int(url.rsplit("=", 1)[1])]})
    runs, queries = gatherer.listed_runs("http://server/", page=2)
    assert [r["id"] for r in runs] == ["c", "b", "a", "z"] and len(queries) == 3
