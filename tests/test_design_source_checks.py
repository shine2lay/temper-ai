"""Model-free tests for Design's source-check step (queue #139, hypothesis H15; widened by queue #143).

configs/design/bin/design_source_checks.py runs the four accepted homepage source checks (A3 input guard
#133, A2 one h1 #134, A1 headline words #136, A2 type-scale steps #137) through their kernels' pure
functions on frozen fixtures, and compares every answer exactly with the frozen keys: source-checks-v1
(copied unchanged from the accepted packets under ~/design-lab/rubric/2026-10-22-next-steps/) for all
four, and source-checks-v2 (public test pages in the homepage build stage's dialect, planted and frozen
before H16's widened A2-01 and A1-02 kernels came in; FREEZE.md) for the two H16 widened. H16's
real-page key is git-ignored (configs/design/local/source-checks-real-v1): its test runs where the key
was copied and is skipped elsewhere. workflows/design_source_checks_next.yaml runs the step as one
ordinary script step. Security's condition for Design runs (rm-4a562384, condition 3: llm and script
agents only) is checked here on the workflow's own config.
"""
import hashlib
import importlib.util
import inspect
import json
import re
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
V1 = DESIGN / "testpages/source-checks-v1"
V2 = DESIGN / "testpages/source-checks-v2"
REAL = DESIGN / "local/source-checks-real-v1"
WORKFLOW = DESIGN / "workflows/design_source_checks_next.yaml"

_spec = importlib.util.spec_from_file_location("design_source_checks", SCRIPT)
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

# Each key's frozen denominators (one repetition): the accepted packets (v1), the planted public pages
# (v2: 4 pages x 6 variants) and H16's real-page key (12 built homepages x 6 variants, local only).
RECORDS = {
    "v1": {"a3-01-preflight": 60, "a2-01-source-h1": 50, "a1-02-headline-words": 60, "a2-05-scale-steps": 80},
    "v2": {"a2-01-source-h1": 24, "a1-02-headline-words": 24},
    "real-v1": {"a2-01-source-h1": 72, "a1-02-headline-words": 72},
}
HAS_REAL = REAL.is_dir()
PRESENT = {key: checks for key, checks in RECORDS.items() if key != "real-v1" or HAS_REAL}
SPECS = {spec["check"]: spec for spec in sc.CHECKS}
# H16's shared reader/guard prefix of the two widened kernels: its length in bytes (through the newline
# after `await page.close()`, the convention of the d158dfa comments' 10462) and its sha256.
WIDENED = ("source_h1_kernel.py", "headline_words_kernel.py")
PREFIX = 11983
PREFIX_SHA256 = "5cdf2c23647c9911530b35ac15d7a0aa9af115f17bb94102262df24341e21ce4"


@pytest.fixture(scope="module")
def everything():
    return sc.run_all()


@pytest.fixture(scope="module")
def frozen(everything):
    return {(c["key"], c["check"]): c for c in everything["checks"]}


def _key_copy(tmp_path: Path, key: Path = V1) -> Path:
    copy = tmp_path / "key"
    shutil.copytree(key, copy)
    return copy


def _rewrite_expected(key: Path, check: str, index: int, change) -> str:
    path = key / check / "EXPECTED.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    answer = SPECS[check]["answer"]
    rows[index][answer] = change(rows[index][answer])
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
    return rows[index]["slot"]


def _all_exact(frozen, key):
    for name, n in RECORDS[key].items():
        result = frozen[(key, name)]
        wrong = [r["slot"] for r in result["results"] if r["state"] != "EXACT"]
        assert (result["records"], result["exact"], result["mismatch"], result["missing"]) == (n, n, 0, 0), (
            key, name, wrong)
        assert result["order_matches_inputs"] and not result["duplicate_slots"] and not result["unkeyed_slots"]
        assert sc.clean(result)


def test_every_frozen_record_of_the_v1_and_v2_keys_matches_exactly(everything, frozen):
    assert list(frozen) == [(key, name) for key, checks in PRESENT.items() for name in checks]
    _all_exact(frozen, "v1")
    _all_exact(frozen, "v2")
    assert everything["verdict"] == "ALL_EXACT"
    assert [(k["key"], k["present"], k["verdict"], k["records"], k["exact"]) for k in everything["keys"]] == [
        (key, key in PRESENT, "ALL_EXACT" if key in PRESENT else "ABSENT", sum(PRESENT.get(key, {}).values()),
         sum(PRESENT.get(key, {}).values())) for key in RECORDS]


@pytest.mark.skipif(not HAS_REAL, reason="H16's real-page key is git-ignored: present only where it was copied")
def test_every_record_of_the_local_real_page_key_matches_exactly(frozen):
    _all_exact(frozen, "real-v1")


def test_an_absent_optional_key_is_listed_not_run_and_a_missing_required_key_crashes(tmp_path):
    absent = str(tmp_path / "absent")
    result = sc.run_all((sc.KEYS[1], {**sc.KEYS[2], "folder": absent}))
    assert (result["verdict"], result["records"], result["exact"]) == ("ALL_EXACT", 48, 48)
    assert result["keys"][1] == {"key": "real-v1", "folder": absent, "required": False, "present": False,
                                 "verdict": "ABSENT", "checks": [], "records": 0, "exact": 0, "mismatch": 0,
                                 "missing": 0}
    with pytest.raises(FileNotFoundError):
        sc.run_all(({**sc.KEYS[1], "folder": absent},))


def test_the_keys_hold_cases_to_catch_and_clean_cases_to_pass(frozen):
    """The mix each key froze: guard refusals, true and false answers, unbound or invalid inputs."""
    a3 = [r["expected"][0] for r in frozen[("v1", "a3-01-preflight")]["results"]]
    assert sum(x is None for x in a3) == 40 and sum(x is not None and x["route"] == "REFUSE" for x in a3) == 20

    def mix(key, check, flag, status=None):
        rows = [r["expected"] for r in frozen[(key, check)]["results"]]
        return (sum(r[flag] is True for r in rows), sum(r[flag] is False for r in rows),
                sum(r["guard_decision"] is not None for r in rows),
                sum(r["guard_decision"] is None and r[flag] is None and r.get(status) is not None for r in rows))

    assert mix("v1", "a2-01-source-h1", "source_count_equals_one") == (25, 15, 10, 0)
    assert mix("v1", "a1-02-headline-words", "source_word_count_lte_12", "binding_status") == (20, 10, 10, 20)
    assert mix("v1", "a2-05-scale-steps", "declared_steps_lte_7", "scale_status") == (25, 10, 10, 35)
    # v2, per page: P0, P4 and P5 have one h1, P1 and P3 two, P2 none; P0 binds within 12 words, P4 binds
    # at 15, P1, P2, P3 and P5 do not bind; every page passes the guard.
    assert mix("v2", "a2-01-source-h1", "source_count_equals_one") == (12, 12, 0, 0)
    assert mix("v2", "a1-02-headline-words", "source_word_count_lte_12", "binding_status") == (4, 4, 0, 16)


def test_the_v2_key_is_the_one_frozen_before_the_widened_kernels_came_in():
    text = (V2 / "FREEZE.md").read_text()
    block = re.search(r"\n```\n(.*?)\n```\n", text, re.S).group(1).splitlines()
    listed = {path: digest for digest, path in (line.split("  ", 1) for line in block)}
    assert len(listed) == len(block) == 29
    assert sorted(str(p.relative_to(V2)) for p in V2.rglob("*") if p.is_file()) == sorted([*listed, "FREEZE.md"])
    for path, digest in listed.items():
        assert hashlib.sha256((V2 / path).read_bytes()).hexdigest() == digest, path
    assert hashlib.sha256(("\n".join(block) + "\n").encode()).hexdigest() in text


def test_each_v2_case_is_checked_against_its_own_role_inventory(tmp_path):
    key = _key_copy(tmp_path, V2)
    path = key / "a1-02-headline-words/INPUTS.json"
    inputs = json.loads(path.read_text())
    assert isinstance(inputs["role_inventory"], str)  # the pages differ: no shared inventory to fall back on
    inputs["cases"][0]["role_inventory"]["roots"].pop()
    path.write_text(json.dumps(inputs))
    result = sc.run_check(SPECS["a1-02-headline-words"], key)
    assert (result["records"], result["exact"], result["mismatch"], result["missing"]) == (24, 23, 1, 0)
    assert [r["slot"] for r in result["results"] if r["state"] == "MISMATCH"] == ["harbor-P0@1440x900"]


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
    everything = sc.run_all(sc.key_from_folder(key))
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
    everything = sc.run_all(sc.key_from_folder(key))
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
    assert sc.run_all(sc.key_from_folder(key))["verdict"] == "NOT_ALL_EXACT"


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
    assert set(summary) == {"status", "verdict", "records", "exact", "mismatch", "missing", "keys", "checks",
                            "python", "platform", "results_path", "results_sha256"}
    total = sum(sum(checks.values()) for checks in PRESENT.values())
    assert (summary["verdict"], summary["records"], summary["exact"], summary["mismatch"], summary["missing"]) == (
        "ALL_EXACT", total, total, 0, 0)
    assert {k: (v["records"], v["exact"], v["mismatch"], v["missing"]) for k, v in summary["checks"].items()} == {
        f"{key}/{name}": (n, n, 0, 0) for key, checks in PRESENT.items() for name, n in checks.items()}
    assert {k: (v["folder"], v["present"], v["verdict"], v["records"]) for k, v in summary["keys"].items()} == {
        k["key"]: (k["folder"], k["key"] in PRESENT, "ALL_EXACT" if k["key"] in PRESENT else "ABSENT",
                   sum(PRESENT.get(k["key"], {}).values())) for k in sc.KEYS}
    assert summary["python"]["version"] == ".".join(map(str, sys.version_info[:3])) and summary["platform"]
    assert summary["results_path"] == "source-checks/results.json"
    assert summary["results_sha256"] == hashlib.sha256(data).hexdigest()
    results = json.loads(data)
    assert results["schema"] == "design-source-checks-results/2"
    assert sum(len(c["results"]) for c in results["checks"]) == total


def test_a_mismatch_still_exits_zero_and_a_crash_does_not(tmp_path):
    key = _key_copy(tmp_path)
    _rewrite_expected(key, "a2-05-scale-steps", 3, lambda r: {**r, "declared_step_count": 6})
    altered = _run(tmp_path, "--key", str(key))
    assert altered.returncode == 0, altered.stderr
    summary = json.loads(altered.stdout)
    assert (summary["verdict"], summary["records"], summary["mismatch"]) == ("NOT_ALL_EXACT", 250, 1)
    assert list(summary["keys"]) == ["key"]
    assert summary["checks"]["key/a2-05-scale-steps"]["not_exact"] == ["S01@390x844"]
    assert _run(tmp_path, "--key", str(tmp_path / "no-such-key")).returncode != 0


def test_the_step_calls_only_the_kernels_pure_functions():
    for spec in sc.CHECKS:
        module = sc.load_kernel(sc.KERNELS / spec["kernel"])
        function = getattr(module, spec["function"])
        assert inspect.isfunction(function) and not inspect.iscoroutinefunction(function), spec["check"]
        assert spec["function"] not in {"check", "_main", "_guard_main", "_stdin_main"}


def test_the_widened_kernels_share_the_reader_and_guard_prefix_their_comments_name():
    for name in WIDENED:
        data = (sc.KERNELS / name).read_bytes()
        assert data[:PREFIX].endswith(b"await page.close()\n"), name
        assert hashlib.sha256(data[:PREFIX]).hexdigest() == PREFIX_SHA256, name
        comment = data[PREFIX:].split(b"\n")[2]
        assert comment.startswith(b"# ") and str(PREFIX).encode() in comment and PREFIX_SHA256[:8].encode() in comment


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
    assert set(raw["outputs"]) == {"verdict", "records", "exact", "mismatch", "missing", "keys", "checks", "python",
                                   "platform", "results_path", "results_sha256"}
    assert all(v == f"check.structured.{k}" for k, v in raw["outputs"].items())
    assert not raw.get("inputs")


def test_no_other_workflow_runs_the_test_step():
    users = sorted(p.name for p in (ROOT / "configs").rglob("*.yaml")
                   if "workflows" in p.parts and "design_source_checks_next" in p.read_text())
    assert users == ["design_source_checks_next.yaml"]
