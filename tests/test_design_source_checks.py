"""Model-free tests for Design's source-check step (queue #139, hypothesis H15).

configs/design/bin/design_source_checks.py runs the four accepted homepage source checks (A3 input guard
#133, A2 one h1 #134, A1 headline words #136, A2 type-scale steps #137) through their kernels' pure
functions on the frozen fixtures, and compares every answer exactly with the frozen key in
configs/design/testpages/source-checks-v1 (copied unchanged from the accepted packets under
~/design-lab/rubric/2026-10-22-next-steps/). workflows/design_source_checks_next.yaml runs it as one
ordinary script step. Security's condition for Design runs (rm-4a562384, condition 3: llm and script
agents only) is checked here on the workflow's own config.
"""
import hashlib
import importlib.util
import inspect
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from temper_ai.stage.models import WorkflowConfig

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "configs/design"
SCRIPT = DESIGN / "bin/design_source_checks.py"
KEY = DESIGN / "testpages/source-checks-v1"
WORKFLOW = DESIGN / "workflows/design_source_checks_next.yaml"

_spec = importlib.util.spec_from_file_location("design_source_checks", SCRIPT)
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

# The accepted packets' frozen denominators (one repetition of each).
RECORDS = {"a3-01-preflight": 60, "a2-01-source-h1": 50, "a1-02-headline-words": 60, "a2-05-scale-steps": 80}
SPECS = {spec["check"]: spec for spec in sc.CHECKS}


@pytest.fixture(scope="module")
def frozen():
    return {c["check"]: c for c in sc.run_all()["checks"]}


def _key_copy(tmp_path: Path) -> Path:
    key = tmp_path / "key"
    shutil.copytree(KEY, key)
    return key


def _rewrite_expected(key: Path, check: str, index: int, change) -> str:
    path = key / check / "EXPECTED.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    answer = SPECS[check]["answer"]
    rows[index][answer] = change(rows[index][answer])
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
    return rows[index]["slot"]


def test_every_frozen_record_of_the_four_keys_matches_exactly(frozen):
    assert list(frozen) == list(RECORDS)
    for name, result in frozen.items():
        wrong = [r["slot"] for r in result["results"] if r["state"] != "EXACT"]
        assert (result["records"], result["exact"], result["mismatch"], result["missing"]) == (
            RECORDS[name], RECORDS[name], 0, 0), (name, wrong)
        assert result["order_matches_inputs"] and not result["duplicate_slots"] and not result["unkeyed_slots"]
        assert sc.clean(result)


def test_the_keys_hold_cases_to_catch_and_clean_cases_to_pass(frozen):
    """The same mix the packets froze: guard refusals, true and false answers, unbound or invalid inputs."""
    a3 = [r["expected"][0] for r in frozen["a3-01-preflight"]["results"]]
    assert sum(x is None for x in a3) == 40 and sum(x is not None and x["route"] == "REFUSE" for x in a3) == 20

    def mix(check, flag, status=None):
        rows = [r["expected"] for r in frozen[check]["results"]]
        return (sum(r[flag] is True for r in rows), sum(r[flag] is False for r in rows),
                sum(r["guard_decision"] is not None for r in rows),
                sum(r["guard_decision"] is None and r[flag] is None and r.get(status) is not None for r in rows))

    assert mix("a2-01-source-h1", "source_count_equals_one") == (25, 15, 10, 0)
    assert mix("a1-02-headline-words", "source_word_count_lte_12", "binding_status") == (20, 10, 10, 20)
    assert mix("a2-05-scale-steps", "declared_steps_lte_7", "scale_status") == (25, 10, 10, 35)


@pytest.mark.parametrize("change", [
    pytest.param(lambda r: {**r, "source_h1_count": 2}, id="value"),
    pytest.param(lambda r: {**r, "source_h1_count": 1.0}, id="int-to-float"),
    pytest.param(lambda r: {**r, "source_count_equals_one": 1}, id="bool-to-int"),
    pytest.param(lambda r: dict(reversed(list(r.items()))), id="key-order"),
])
def test_an_altered_expected_value_is_a_mismatch(tmp_path, change):
    key = _key_copy(tmp_path)
    slot = _rewrite_expected(key, "a2-01-source-h1", 0, change)
    result = sc.run_check(SPECS["a2-01-source-h1"], key)
    assert (result["records"], result["exact"], result["mismatch"], result["missing"]) == (50, 49, 1, 0)
    assert [r["slot"] for r in result["results"] if r["state"] == "MISMATCH"] == [slot] == ["H01@1440x900"]
    assert not sc.clean(result)
    everything = sc.run_all(key)
    assert everything["verdict"] == "NOT_ALL_EXACT" and everything["mismatch"] == 1 and everything["exact"] == 249


def test_a_removed_fixture_is_missing_not_skipped(tmp_path):
    key = _key_copy(tmp_path)
    (key / "a1-02-headline-words/fixtures/W03.html").unlink()
    result = sc.run_check(SPECS["a1-02-headline-words"], key)
    assert (result["records"], result["exact"], result["mismatch"], result["missing"]) == (60, 55, 0, 5)
    missing = [r for r in result["results"] if r["state"] == "MISSING"]
    assert [r["slot"] for r in missing] == [f"W03@{w}x{h}" for w, h in ((1440, 900), (1024, 768), (768, 1024),
                                                                        (390, 844), (320, 844))]
    assert {r["reason"] for r in missing} == {"FIXTURE_UNREADABLE"} and not sc.clean(result)
    everything = sc.run_all(key)
    assert (everything["verdict"], everything["records"], everything["missing"]) == ("NOT_ALL_EXACT", 250, 5)


def test_a_fixture_that_is_not_its_declared_bytes_is_not_run(tmp_path):
    key = _key_copy(tmp_path)
    fixture = key / "a2-05-scale-steps/fixtures/S01.html"
    fixture.write_bytes(fixture.read_bytes() + b" ")
    result = sc.run_check(SPECS["a2-05-scale-steps"], key)
    assert (result["exact"], result["mismatch"], result["missing"]) == (75, 0, 5)
    assert {r["reason"] for r in result["results"] if r["state"] == "MISSING"} == {"FIXTURE_BINDING_MISMATCH"}


def test_a_dropped_key_row_is_reported_not_silently_shorter(tmp_path):
    key = _key_copy(tmp_path)
    path = key / "a3-01-preflight/EXPECTED.jsonl"
    path.write_text("".join(path.read_text().splitlines(keepends=True)[1:]))
    result = sc.run_check(SPECS["a3-01-preflight"], key)
    assert result["records"] == 59 and result["unkeyed_slots"] == ["F01@1440x900"]
    assert not result["order_matches_inputs"] and not sc.clean(result)
    assert sc.run_all(key)["verdict"] == "NOT_ALL_EXACT"


def _run(tmp_path, *args):
    return subprocess.run([sys.executable, str(SCRIPT), "--out", "source-checks/results.json", *args],
                          cwd=tmp_path, capture_output=True, text=True, timeout=60)


def test_the_script_prints_one_summary_writes_every_record_and_repeats_byte_for_byte(tmp_path):
    first = _run(tmp_path)
    assert first.returncode == 0, first.stderr
    data = (tmp_path / "source-checks/results.json").read_bytes()
    second = _run(tmp_path)
    assert second.returncode == 0 and second.stdout == first.stdout
    assert (tmp_path / "source-checks/results.json").read_bytes() == data
    assert len(first.stdout.strip().splitlines()) == 1
    summary = json.loads(first.stdout)
    assert set(summary) == {"status", "verdict", "records", "exact", "mismatch", "missing", "checks", "python",
                            "platform", "results_path", "results_sha256"}
    assert (summary["verdict"], summary["records"], summary["exact"], summary["mismatch"], summary["missing"]) == (
        "ALL_EXACT", 250, 250, 0, 0)
    assert {k: (v["records"], v["exact"], v["mismatch"], v["missing"]) for k, v in summary["checks"].items()} == {
        k: (n, n, 0, 0) for k, n in RECORDS.items()}
    assert summary["python"]["version"] == ".".join(map(str, sys.version_info[:3])) and summary["platform"]
    assert summary["results_path"] == "source-checks/results.json"
    assert summary["results_sha256"] == hashlib.sha256(data).hexdigest()
    results = json.loads(data)
    assert sum(len(c["results"]) for c in results["checks"]) == 250


def test_a_mismatch_still_exits_zero_and_a_crash_does_not(tmp_path):
    key = _key_copy(tmp_path)
    _rewrite_expected(key, "a2-05-scale-steps", 3, lambda r: {**r, "declared_step_count": 6})
    altered = _run(tmp_path, "--key", str(key))
    assert altered.returncode == 0, altered.stderr
    summary = json.loads(altered.stdout)
    assert (summary["verdict"], summary["mismatch"]) == ("NOT_ALL_EXACT", 1)
    assert summary["checks"]["a2-05-scale-steps"]["not_exact"] == ["S01@390x844"]
    assert _run(tmp_path, "--key", str(tmp_path / "no-such-key")).returncode != 0


def test_the_step_calls_only_the_kernels_pure_functions():
    for spec in sc.CHECKS:
        module = sc.load_kernel(sc.KERNELS / spec["kernel"])
        function = getattr(module, spec["function"])
        assert inspect.isfunction(function) and not inspect.iscoroutinefunction(function), spec["check"]
        assert spec["function"] not in {"check", "_main", "_guard_main", "_stdin_main"}


def test_the_workflow_is_one_ordinary_script_step():
    raw = yaml.safe_load(WORKFLOW.read_text())["workflow"]
    assert WorkflowConfig.from_dict(raw).name == "design_source_checks_next"
    assert [n["agent"] for n in raw["nodes"]] == ["design_source_checks_next"]
    for node in raw["nodes"]:
        text = (DESIGN / "agents" / f"{node['agent']}.yaml").read_text()
        agent = yaml.safe_load(text)["agent"]
        assert node["type"] == "agent" and agent["type"] == "script", node["name"]
        assert "${" not in text and not {"model", "provider", "system_prompt", "tools"} & set(agent)
        assert ('"$TEMPER_PYTHON" /app/configs/design/bin/design_source_checks.py --out source-checks/results.json'
                in agent["script_template"])
    assert all(v.startswith("check.structured.") for v in raw["outputs"].values())
    assert not raw.get("inputs")


def test_no_other_workflow_runs_the_test_step():
    users = sorted(p.name for p in (ROOT / "configs").rglob("*.yaml")
                   if "workflows" in p.parts and "design_source_checks_next" in p.read_text())
    assert users == ["design_source_checks_next.yaml"]
