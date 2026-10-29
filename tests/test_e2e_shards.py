"""The browser suite as 3 time-balanced shards, and the check that together they ran all of it, once.

Known answers (AGENTS.md rule 16). tests/fixtures/e2e_shards/reports/ holds real Playwright 1.63
reports of a tiny suite of plain node tests (tests/fixtures/e2e_shards/suite/: no page, no browser,
no server), made by

    python3 tests/fixtures/e2e_shards/generate.py

The clean set, one file a shard, has a pass, a test that passes only on its retry, a skipped
test, a nested describe, the same title in two files and a title with " › " in it; the failing
set adds a test that fails on both attempts. Every way the check must catch a bad run is a small
edit of a copy of the clean set. The CI side is in .github/workflows/ci.yml (jobs e2e-shard and
e2e) and docs/ci-gate.md, "Browser test shards".
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "e2e_shards"
REPORTS = FIXTURES / "reports"
CI = REPO / ".github" / "workflows" / "ci.yml"

SHA = "5ad0f1c7" * 5  # the commit the fixture shards' meta.json names
OK = {"e2e-shard": {"result": "success", "outputs": {}}}
CLEAN = ["alpha.spec.ts", "beta.spec.ts", "gamma.spec.ts"]
FLAKY = ("", "alpha.spec.ts", "passes only on its retry")
FAILS = ("", "delta.spec.ts", "fails on every attempt")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


shards = _load("e2e_shards")
flaky_report = _load("flaky_report")


@pytest.fixture(autouse=True)
def _no_job_summary(monkeypatch):
    """GitHub sets GITHUB_STEP_SUMMARY for the job running these tests; keep out of it."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


@pytest.fixture
def run(tmp_path) -> Path:
    """A copy of the clean set's downloaded shard artifacts, to break."""
    root = tmp_path / "shards"
    shutil.copytree(REPORTS / "clean", root)
    return root


def check(root: Path, needs: dict | None = None, files: list[str] | None = None):
    return shards.check(root, 3, SHA, OK if needs is None else needs, CLEAN if files is None else files)


def problems(root: Path, **kwargs) -> str:
    return "\n".join(check(root, **kwargs).problems)


def edit_junit(root: Path, shard: int, change) -> None:
    path = root / f"e2e-shard-{shard}-of-3" / "playwright-junit.xml"
    tree = ET.parse(path)
    change(tree.getroot())
    tree.write(path, encoding="utf-8", xml_declaration=True)


def edit_json(path: Path, change) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    change(doc)
    path.write_text(json.dumps(doc), encoding="utf-8")


def meta(root: Path, shard: int) -> Path:
    return root / f"e2e-shard-{shard}-of-3" / "meta.json"


# -- the check: a good run passes ----------------------------------------------------------


def test_the_clean_run_passes_and_names_its_retry_only_pass_once(run):
    result = check(run)

    assert result.problems == []
    assert result.tests == 8, "the test that passed on its retry still counts once"
    assert result.retried == [FLAKY]
    assert result.failed == [] and result.failed_with_reruns == []
    text = shards.markdown(result)
    assert "All 8 test(s) of the listing ran exactly once" in text
    assert text.count("passes only on its retry") == 1


def test_files_tell_alike_titles_apart_and_the_reports_match_the_listing():
    tests, errors = shards.listing(REPORTS / "clean" / "e2e-shard-1-of-3" / "list.json")
    assert errors == 0 and len(tests) == len(set(tests)) == 8
    assert ("", "beta.spec.ts", "a › b") in tests, "describe 'a', test 'b'"
    assert ("", "gamma.spec.ts", "a › b") in tests, "a test titled 'a › b'"
    assert ("", "alpha.spec.ts", "outer › inner › nested") in tests
    assert ("", "beta.spec.ts", "same title in two files") in tests
    assert ("", "gamma.spec.ts", "same title in two files") in tests

    ran = [case.identity for i in (1, 2, 3)
           for case in shards.junit(REPORTS / "clean" / f"e2e-shard-{i}-of-3" / "playwright-junit.xml")[1]]
    assert sorted(ran) == sorted(tests)
    counter, cases = shards.junit(REPORTS / "clean" / "e2e-shard-2-of-3" / "playwright-junit.xml")
    assert counter == 3 and [case.outcome for case in cases].count("skipped") == 1


def test_the_command_exits_0_on_a_clean_run_and_1_on_a_broken_one(run, tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    argv = ["check", str(run), "--of", "3", "--sha", SHA, "--needs", json.dumps(OK),
            "--files", str(FIXTURES / "suite" / "clean.txt")]

    assert shards.main(argv) == 0
    assert "ran exactly once" in summary.read_text(encoding="utf-8")
    shutil.rmtree(run / "e2e-shard-2-of-3")
    assert shards.main(argv) == 1
    assert "MISSING artifact e2e-shard-2-of-3" in capsys.readouterr().out


# -- the check: every way a run can go wrong fails it ----------------------------------------


def test_a_test_that_never_ran_fails(run):
    def drop(root):
        suite = next(root.iter("testsuite"))
        suite.remove(next(case for case in suite.iter("testcase") if case.get("name") == "passes"))
        root.set("tests", "2")

    edit_junit(run, 1, drop)
    text = problems(run)
    assert "1 test(s) of the listing never ran: alpha.spec.ts › passes" in text
    assert "the reports count 7 test(s), the listing 8" in text


def test_a_test_run_by_two_shards_fails(run):
    def add(root):
        suite = ET.SubElement(root, "testsuite", {"name": "alpha.spec.ts", "hostname": "", "tests": "1"})
        ET.SubElement(suite, "testcase", {"name": "passes", "classname": "alpha.spec.ts", "time": "0.01"})
        root.set("tests", "4")

    edit_junit(run, 2, add)
    text = problems(run)
    assert "ambiguous: 1 test(s) ran more than once: alpha.spec.ts › passes (shards 1, 2)" in text
    assert "shard 2 ran file(s) not on its list: alpha.spec.ts" in text


def test_a_test_the_listing_does_not_name_fails(run):
    def add(root):
        suite = next(s for s in root.iter("testsuite") if s.get("name") == "gamma.spec.ts")
        ET.SubElement(suite, "testcase", {"name": "sneaked in", "classname": "gamma.spec.ts", "time": "0.01"})
        root.set("tests", "3")

    edit_junit(run, 3, add)
    assert "1 test(s) ran but are not in the listing: gamma.spec.ts › sneaked in" in problems(run)


def test_a_test_one_report_holds_twice_is_ambiguous_not_collapsed(run):
    def double(root):
        suite = next(root.iter("testsuite"))
        suite.append(copy.deepcopy(next(suite.iter("testcase"))))
        root.set("tests", "4")

    edit_junit(run, 1, double)
    text = problems(run)
    assert "ambiguous: 1 test(s) ran more than once: alpha.spec.ts › passes (shards 1, 1)" in text
    assert "the reports count 9 test(s), the listing 8" in text


def test_a_test_the_listing_names_twice_is_ambiguous_not_collapsed(run):
    for i in (1, 2, 3):
        edit_json(run / f"e2e-shard-{i}-of-3" / "list.json",
                  lambda doc: doc["suites"][0]["specs"].append(doc["suites"][0]["specs"][0]))

    text = problems(run)
    assert "ambiguous: the listing names 1 test(s) more than once: alpha.spec.ts › passes" in text
    assert "the reports count 8 test(s), the listing 9" in text


def test_a_missing_shard_artifact_fails(run):
    shutil.rmtree(run / "e2e-shard-2-of-3")

    text = problems(run)
    assert "MISSING artifact e2e-shard-2-of-3" in text
    assert "3 test(s) of the listing never ran" in text


@pytest.mark.parametrize("missing", ["meta.json", "test-list.txt", "list.json", "playwright-junit.xml"])
def test_a_shard_artifact_without_one_of_its_files_fails(run, missing):
    (run / "e2e-shard-3-of-3" / missing).unlink()

    assert f"MISSING from e2e-shard-3-of-3: {missing}" in problems(run)


def test_an_extra_shard_artifact_fails(run):
    shutil.copytree(run / "e2e-shard-3-of-3", run / "e2e-shard-4-of-3")

    text = problems(run)
    assert "unexpected artifact e2e-shard-4-of-3" in text
    assert "2 artifacts say they are shard 3" in text


def test_two_artifacts_for_one_shard_fail(run):
    edit_json(meta(run, 2), lambda doc: doc.update(shard=1))

    text = problems(run)
    assert "2 artifacts say they are shard 1" in text
    assert "e2e-shard-2-of-3: its meta says shard 1 of 3" in text


def test_a_shard_that_tested_another_commit_fails(run):
    edit_json(meta(run, 3), lambda doc: doc.update(sha="0" * 40))

    assert f"e2e-shard-3-of-3: its meta is for commit {'0' * 40}, not {SHA}" in problems(run)


def test_a_shard_of_another_split_fails(run):
    edit_json(meta(run, 3), lambda doc: doc.update(of=4))

    assert "e2e-shard-3-of-3: its meta says shard 3 of 4" in problems(run)


def test_shards_that_listed_different_tests_fail(run):
    edit_json(run / "e2e-shard-2-of-3" / "list.json", lambda doc: doc["suites"][2]["specs"].pop())

    assert "shard 2's listing differs from shard 1's: gamma.spec.ts › a › b" in problems(run)


def test_a_report_whose_counter_disagrees_with_its_testcases_fails(run):
    edit_junit(run, 1, lambda root: root.set("tests", "4"))

    text = problems(run)
    assert "shard 1's report says tests=4 but holds 3 testcase(s)" in text
    assert "the reports count 9 test(s), the listing 8" in text


def test_a_file_on_two_lists_fails(run):
    (run / "e2e-shard-2-of-3" / "test-list.txt").write_text("beta.spec.ts\nalpha.spec.ts\n", encoding="utf-8")

    assert "alpha.spec.ts is on the lists of shards 1, 2" in problems(run)


def test_a_file_on_no_list_fails(run):
    (run / "e2e-shard-3-of-3" / "test-list.txt").write_text("", encoding="utf-8")

    text = problems(run)
    assert "gamma.spec.ts is listed in server-free.txt but on no shard's list" in text
    assert "shard 3 ran file(s) not on its list: gamma.spec.ts" in text


def test_a_file_server_free_txt_does_not_list_fails(run):
    text = problems(run, files=["alpha.spec.ts", "gamma.spec.ts"])

    assert "beta.spec.ts is on a shard's list but not in server-free.txt" in text


@pytest.mark.parametrize("outcome", ["failure", "cancelled", "skipped"])
def test_a_shard_job_that_did_not_succeed_fails_the_check(run, outcome):
    text = problems(run, needs={"e2e-shard": {"result": outcome, "outputs": {}}})

    assert f"e2e-shard ended {outcome}, not success" in text


def test_no_shard_results_fail_the_check(run):
    assert "no shard results were handed over" in problems(run, needs={})


def test_with_nothing_listed_only_the_shard_jobs_results_count(tmp_path):
    nothing = shards.check(tmp_path / "shards", 3, SHA, OK, [])
    assert nothing.problems == [] and nothing.nothing_listed and nothing.tests == 0
    assert "No spec file is listed in `frontend/e2e/server-free.txt`, so no shard ran a test." in \
        shards.markdown(nothing)

    cancelled = shards.check(tmp_path / "shards", 3, SHA, {"e2e-shard": {"result": "cancelled", "outputs": {}}}, [])
    assert cancelled.problems == ["e2e-shard ended cancelled, not success"]


def test_a_failing_test_is_named_and_so_is_its_failed_retry(tmp_path):
    root = tmp_path / "shards"
    shutil.copytree(REPORTS / "failing", root)
    files = [*CLEAN, "delta.spec.ts"]

    result = shards.check(root, 3, SHA, {"e2e-shard": {"result": "failure", "outputs": {}}}, files)
    assert result.tests == 9
    assert result.failed == [FAILS] and result.failed_with_reruns == [FAILS]
    assert result.retried == [FLAKY]
    assert "e2e-shard ended failure, not success" in result.problems
    assert "1 test(s) failed: delta.spec.ts › fails on every attempt" in result.problems
    assert "`delta.spec.ts › fails on every attempt` (its retry failed too)" in shards.markdown(result)
    # A red test fails the check even if its shard's job were reported green.
    assert "1 test(s) failed: delta.spec.ts › fails on every attempt" in shards.check(root, 3, SHA, OK, files).problems


def test_the_check_never_repeats_what_a_test_printed_or_why_it_failed(run):
    def leak(root):
        case = next(root.iter("testcase"))
        ET.SubElement(case, "system-out").text = "TOKEN=hunter2"
        ET.SubElement(case, "failure", {"message": "hunter2 in the message"}).text = "hunter2 in the stack"

    edit_junit(run, 1, leak)
    result = check(run)
    assert "1 test(s) failed: alpha.spec.ts › passes" in result.problems
    assert "hunter2" not in shards.markdown(result)


# -- the split -------------------------------------------------------------------------------

WEIGHTS = {"a.spec.ts": 100, "b.spec.ts": 60, "c.spec.ts": 50, "d.spec.ts": 40, "e.spec.ts": 30,
           "f.spec.ts": 20, "g.spec.ts": 10}


def test_the_split_balances_known_weights_as_worked_out_by_hand():
    # Heaviest first to the least-loaded of 6 slots: a, b, c, d, e, f one each, then g joins f.
    p = shards.plan(sorted(WEIGHTS), WEIGHTS, 3)

    assert p.shards == [["a.spec.ts", "b.spec.ts"], ["c.spec.ts", "d.spec.ts"],
                        ["e.spec.ts", "f.spec.ts", "g.spec.ts"]]
    assert p.seconds == [100, 50, 30]
    assert p.unweighted == [] and p.largest == 100


def test_the_split_is_the_same_whatever_order_the_files_come_in():
    first = shards.plan(sorted(WEIGHTS), WEIGHTS, 3)
    for seed in range(5):
        files = sorted(WEIGHTS)
        random.Random(seed).shuffle(files)
        again = shards.plan(files, WEIGHTS, 3)
        assert (again.shards, again.seconds) == (first.shards, first.seconds)


def test_a_shard_time_replays_playwright_in_order_on_two_workers():
    weight = {"a.spec.ts": 10, "b.spec.ts": 10, "c.spec.ts": 30}

    assert shards.simulate(["c.spec.ts", "b.spec.ts", "a.spec.ts"], weight) == 40, "a and b first, then c"
    assert shards.simulate([], weight) == 0
    assert shards.playwright_order(["team.spec.ts", "team-c.spec.ts", "Zeta.spec.ts", "bigView.spec.ts"]) == \
        ["bigView.spec.ts", "team-c.spec.ts", "team.spec.ts", "Zeta.spec.ts"]


def test_the_real_split_puts_every_listed_file_on_exactly_one_shard():
    files = shards.listed()
    p = shards.plan(files, shards.load_weights(), 3)
    placed = [file for names in p.shards for file in names]

    assert len(p.shards) == 3
    assert sorted(placed) == sorted(files) and len(placed) == len(set(placed))


def test_each_shard_works_out_the_same_split_by_itself(tmp_path):
    lists = []
    for i in (1, 2, 3):
        out = tmp_path / f"test-list-{i}.txt"
        assert shards.main(["split", "--shard", str(i), "--of", "3", "--out", str(out)]) == 0
        lists.append(shards.listed(out))

    assert lists == shards.plan(shards.listed(), shards.load_weights(), 3).shards


def test_a_file_without_a_weight_gets_the_largest_and_is_named():
    p = shards.plan(["a.spec.ts", "new.spec.ts"], {"a.spec.ts": 100, "z.spec.ts": 300}, 3)

    assert p.unweighted == ["new.spec.ts"] and p.largest == 300
    assert max(p.seconds) == 300
    assert "no weight yet, so given the largest (300 s): `new.spec.ts`" in shards.describe(p)


def test_an_empty_list_gives_three_empty_shards(tmp_path):
    p = shards.plan([], {"a.spec.ts": 1}, 3)
    assert p.shards == [[], [], []] and p.seconds == [0, 0, 0]

    listed = tmp_path / "server-free.txt"
    listed.write_text("# nothing listed yet\n", encoding="utf-8")
    out = tmp_path / "test-list.txt"
    assert shards.main(["split", "--shard", "2", "--of", "3", "--files", str(listed),
                        "--weights", str(tmp_path / "no-weights.json"), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == ""


def test_the_list_is_read_as_the_workflow_reads_it(tmp_path):
    listed = tmp_path / "server-free.txt"
    listed.write_text("# why these\n a.spec.ts  # a note\n\nb .spec.ts\na.spec.ts\n", encoding="utf-8")

    assert shards.listed(listed) == ["a.spec.ts", "b.spec.ts"]


def test_weights_are_each_files_most_seconds_over_the_reports(tmp_path):
    one = tmp_path / "one.xml"
    one.write_text('<testsuites><testsuite name="a.spec.ts" time="10.2"/><testsuite name="b.spec.ts" time="3"/>'
                   "</testsuites>", encoding="utf-8")
    two = tmp_path / "two.xml"
    two.write_text('<testsuites><testsuite name="a.spec.ts" time="7"/><testsuite name="b.spec.ts" time="4.5"/>'
                   "</testsuites>", encoding="utf-8")

    assert shards.weights_from([one, two]) == {"a.spec.ts": 11, "b.spec.ts": 5}


def test_meta_records_the_shard_attempt_commit_and_image(tmp_path, monkeypatch):
    for name, value in {"GITHUB_RUN_ATTEMPT": "2", "GITHUB_SHA": SHA, "ImageOS": "ubuntu24",
                        "ImageVersion": "20261020.1.0"}.items():
        monkeypatch.setenv(name, value)
    out = tmp_path / "meta.json"

    assert shards.main(["meta", "--shard", "3", "--of", "3", "--out", str(out)]) == 0
    got = json.loads(out.read_text(encoding="utf-8"))
    assert set(got) == {"shard", "of", "run_attempt", "sha", "image_os", "image_version", "node", "playwright"}
    assert {k: got[k] for k in ("shard", "of", "run_attempt", "sha", "image_os", "image_version")} == {
        "shard": 3, "of": 3, "run_attempt": 2, "sha": SHA, "image_os": "ubuntu24", "image_version": "20261020.1.0"}
    with pytest.raises(SystemExit):
        shards.main(["split", "--shard", "4", "--of", "3", "--out", str(out)])


# -- flaky_report.py, old reports and new --------------------------------------------------


def _flaky_report(*reports: Path, soft: bool = True) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_STEP_SUMMARY"}
    return subprocess.run([sys.executable, str(REPO / "scripts" / "flaky_report.py"), *map(str, reports),
                           "--title", "Browser tests", *(["--soft"] if soft else [])],
                          capture_output=True, text=True, env=env, timeout=60, check=False)


def test_flaky_report_names_a_retry_only_pass_from_its_retry_entries():
    seen = flaky_report.outcomes([REPORTS / "failing" / f"e2e-shard-{i}-of-3" / "playwright-junit.xml"
                                  for i in (1, 2, 3)])

    assert seen["alpha.spec.ts :: passes only on its retry"] == {"passed", "failed"}
    assert seen["delta.spec.ts :: fails on every attempt"] == {"failed"}, "failed on its retry too: a plain failure"
    assert seen["alpha.spec.ts :: passes"] == {"passed"}
    assert "beta.spec.ts :: is skipped" not in seen


def test_without_retry_entries_a_retry_only_pass_looks_like_a_plain_pass():
    seen = flaky_report.outcomes([REPORTS / "single" / "no-retries.xml"])

    assert seen["alpha.spec.ts :: passes only on its retry"] == {"passed"}


def test_flaky_report_still_finds_a_test_that_failed_in_one_repeat_and_passed_in_another():
    seen = flaky_report.outcomes([REPORTS / "single" / "repeats.xml"])

    assert seen["alpha.spec.ts :: passes only on its retry"] == {"passed", "failed"}
    assert seen["alpha.spec.ts :: passes"] == {"passed"}


def test_flaky_report_fails_on_a_flaky_test_unless_soft():
    report = REPORTS / "clean" / "e2e-shard-1-of-3" / "playwright-junit.xml"

    hard, soft = _flaky_report(report, soft=False), _flaky_report(report)
    assert hard.returncode == 1 and soft.returncode == 0
    assert "alpha.spec.ts :: passes only on its retry" in soft.stdout
    plain = _flaky_report(REPORTS / "single" / "no-retries.xml", soft=False)
    assert plain.returncode == 0 and "None: every test gave the same answer every time." in plain.stdout


# -- ci.yml ----------------------------------------------------------------------------------


def _jobs() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]


def _posted(jobs: dict) -> dict[str, str]:
    """The check name GitHub shows for each job -> its key, a matrix's names expanded."""
    posted = {}
    for key, job in jobs.items():
        names = [str(job.get("name", key))]
        for axis, values in ((job.get("strategy") or {}).get("matrix") or {}).items():
            pattern = r"\$\{\{\s*matrix\." + re.escape(axis) + r"\s*\}\}"
            if isinstance(values, list) and re.search(pattern, names[0]):
                names = [re.sub(pattern, str(value), name) for name in names for value in values]
        posted.update(dict.fromkeys(names, key))
    return posted


def _required() -> list[str]:
    if str(REPO / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO / "scripts"))
    from temper_ci.cli import PROTECTION  # noqa: PLC0415

    return list(PROTECTION["required_status_checks"]["contexts"])


def _step(steps: list[dict], test) -> dict:
    return next(step for step in steps if test(step))


def test_the_e2e_check_always_runs_after_every_shard_and_runs_no_browser():
    final = _jobs()["e2e"]
    steps = final["steps"]

    assert final.get("name", "e2e") == "e2e"
    # Not success() or !cancelled(): a cancelled or skipped shard must turn this check red, because
    # GitHub and `wt land` count a skipped required check as passed.
    assert final["if"] == "always()"
    assert final["needs"] in ("e2e-shard", ["e2e-shard"])
    check_step = _step(steps, lambda step: "e2e_shards.py check" in step.get("run", ""))
    assert "--of 3" in check_step["run"] and "toJSON(needs)" in json.dumps(check_step.get("env", {}))
    assert check_step["if"].startswith("always()")
    download = _step(steps, lambda step: str(step.get("uses", "")).startswith("actions/download-artifact@"))
    assert download["with"]["pattern"] == "e2e-shard-*-of-3" and not download["with"].get("merge-multiple")
    report = _step(steps, lambda step: (step.get("with") or {}).get("name") == "e2e-failures")
    assert report["if"].startswith("always()") and report["with"]["retention-days"] == 7
    assert not any("npx playwright" in step.get("run", "") for step in steps)


def test_the_shards_run_their_own_list_and_keep_what_the_check_reads():
    shard = _jobs()["e2e-shard"]
    steps = shard["steps"]
    runs = "\n".join(step.get("run", "") for step in steps)

    assert shard["strategy"]["fail-fast"] is False and shard["strategy"]["matrix"]["shard"] == [1, 2, 3]
    assert "e2e_shards.py split --shard ${{ matrix.shard }} --of 3" in runs
    assert "e2e_shards.py meta --shard ${{ matrix.shard }} --of 3" in runs
    assert "npx playwright test -c playwright.server-free.config.ts --list --reporter=json" in runs
    tests = _step(steps, lambda step: "--test-list" in step.get("run", ""))
    assert tests["run"] == ("npx playwright test -c playwright.server-free.config.ts --test-list test-list.txt "
                            "--reporter=list,junit")
    assert tests["env"]["PLAYWRIGHT_JUNIT_INCLUDE_RETRIES"] == "1"
    upload = _step(steps, lambda step: str(step.get("uses", "")).startswith("actions/upload-artifact@"))
    assert upload["with"]["name"] == "e2e-shard-${{ matrix.shard }}-of-3" and upload["with"]["overwrite"] is True
    assert all(f"frontend/{name}" in upload["with"]["path"] for name in shards.NEEDED)
    assert not [k for step in steps for k in (step.get("env") or {}) if k.startswith("PWTEST_")]


def test_no_shard_takes_a_required_name_and_every_required_check_is_still_posted():
    posted = _posted(_jobs())
    required = _required()

    assert sorted(name for name, key in posted.items() if key == "e2e-shard") == [
        "e2e shard (1/3)", "e2e shard (2/3)", "e2e shard (3/3)"]
    assert not {name for name, key in posted.items() if key == "e2e-shard"} & set(required)
    assert posted["e2e"] == "e2e"
    assert [name for name in required if name != "temper/boxes" and name not in posted] == []


def test_with_nothing_listed_the_shards_run_nothing_and_the_check_reads_only_their_results():
    for key in ("e2e-shard", "e2e"):
        steps = _jobs()[key]["steps"]
        after = steps[[step.get("id") for step in steps].index("list") + 1:]
        always = [step for step in after if "steps.list.outputs.count != '0'" not in step.get("if", "")]
        assert len(after) > len(always), key
        if key == "e2e-shard":
            assert always == []
        else:
            # The one step that runs whatever is listed: with nothing listed it still turns red
            # when a shard job did not succeed.
            assert [(step["if"], "e2e_shards.py check" in step["run"]) for step in always] == [("always()", True)]
