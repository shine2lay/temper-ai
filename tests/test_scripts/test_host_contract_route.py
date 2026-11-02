"""Exact leaf route: a real ordinary-hook happy path first, then fail-closed controls.

Real-tool tests are synthetic public fixtures, not Ops' package acceptance. Recorded full-route
phase controls prove dispatch only; they do not claim a full-suite pass. Child diagnostics are
queried as fixed booleans via Ran; failures never echo a child's argv, stderr or stdout.
"""
from __future__ import annotations

import subprocess
import sys

import pytest
import yaml

from tests.test_scripts.host_contract_fixture import ROOT, LeafRepo
from tests.test_scripts.test_select_tests import RULES, st
from tests.test_shared_test_cpu_entry import (
    FAKE_TOOL,
    phases,
    program,
    run_hook,
    split,
)
from tests.test_shared_test_cpu_entry import (
    host as host,
)


@pytest.fixture
def leaf(tmp_path):
    return LeafRepo(tmp_path / "repo")


def saw(result, text):
    return result.said(text) or result.warned(text) > 0


def picked(leaf, *args):
    return st.run(st._parse(["--repo", str(leaf.root), *args]))[0]


def test_ordinary_hook_checks_staged_leaf_then_committed_diff_and_docs_only(leaf):
    """Combined nonzero lint/type/tests, fixture loading, import isolation, staged/CI agreement."""
    staged = picked(leaf, "--staged")
    assert staged.route == st.HOST_CONTRACTS and staged.python == "some"
    # Environment-injected plugins/options and dirty working files cannot change the check.
    leaf.env.update(PYTEST_PLUGINS="temper_ai", PYTEST_ADDOPTS="--forbidden-root-option", PYTHONPATH=str(leaf.root))
    # The hook must test the index, not the dirty working tree's source or conftest.
    leaf.put("p3_host_contracts/__init__.py", "raise RuntimeError('UNSTAGED_PACKAGE')\n")
    leaf.put("tests/test_p3_host_contracts/conftest.py", "raise RuntimeError('UNSTAGED_FIXTURE')\n")
    result = leaf.call("git", "commit", "-m", "synthetic pure leaf")
    assert (result.code, saw(result, "locked lint"), saw(result, "All checks passed!"),
            saw(result, "Success: no issues found"), saw(result, "2 passed")) == (0, True, True, True, True)
    leaf.git("restore", ".")
    committed = picked(leaf, "--base", "master", "--head", "HEAD")
    automatic = picked(leaf)
    assert committed.route == automatic.route == staged.route
    assert committed.tests == automatic.tests == staged.tests
    assert committed.base == st.Git(leaf.root).commit("master")
    assert "route=host-contracts" in committed.github_output()
    # An ordinary manual hook is wt's no-staged-files entry; no alternate hook or route flag.
    assert leaf.hook().code == 0
    leaf.put("docs/p3-host-contracts.md", "Documentation change still checks contracts.\n")
    leaf.git("add", "docs/p3-host-contracts.md")
    result = leaf.hook()
    assert (result.code, result.said("2 passed"), result.said("Success: no issues found")) == (0, True, True)


@pytest.mark.parametrize(("path", "body", "diagnostic"), [
    ("p3_host_contracts/__init__.py", "def value() -> int:\n    return 'wrong'\n", "Incompatible return value type"),
    ("p3_host_contracts/__init__.py", "def value() -> int:\n    return NOT_DEFINED\n", "F821"),
    ("tests/test_p3_host_contracts/test_contract.py", "def test_wrong():\n    assert 1 == 2\n", "1 failed"),
    ("tests/test_p3_host_contracts/test_contract.py", "VALUE = 1\n", "no tests ran"),
    ("tests/test_p3_host_contracts/test_contract.py", "from importlib import import_module\n\n\ndef test_import():\n    import_module('temper_ai')\n", "Application/provider import forbidden"),
    ("tests/test_p3_host_contracts/test_contract.py", "from importlib import import_module\n\n\ndef test_import():\n    import_module('anthropic')\n", "Application/provider import forbidden"),
    ("tests/test_p3_host_contracts/conftest.py", "raise RuntimeError('FORBIDDEN_ROOT_BOOTSTRAP')\n", "FORBIDDEN_ROOT_BOOTSTRAP"),
    ("tests/test_p3_host_contracts/test_contract.py", "import subprocess\n\n\ndef test_native():\n    subprocess.run(['docker'], check=True)\n", "FORBIDDEN_NATIVE_ACCESS"),
], ids=["type", "lint", "test", "zero-tests", "application-import", "provider-import", "sentinel-bites", "native-sentinel"])
def test_real_locked_leaf_failures_fail_the_ordinary_hook(leaf, path, body, diagnostic):
    leaf.put(path, body)
    leaf.git("add", ".")
    result = leaf.hook()
    assert result.code is not None and result.code != 0
    seen = saw(result, diagnostic)
    assert seen, "the intended leaf check did not produce its fixed failure"
    assert not result.said("All pre-commit checks passed")


SAFE = ["p3_host_contracts/__init__.py", "p3_host_contracts/sub/value.py", "tests/test_p3_host_contracts/test_value.py",
        "tests/test_p3_host_contracts/conftest.py", "tests/test_p3_host_contracts/fixtures/value.json", "docs/p3-host-contracts.md"]
UNSAFE = ["p3_host_contracts_extra/value.py", "before/p3_host_contracts/value.py", "p3_host_contracts",
          "tests/test_p3_host_contracts_extra/test_value.py", "before/tests/test_p3_host_contracts/test_value.py",
          "docs/p3-host-contracts.md.extra", "before/docs/p3-host-contracts.md", "docs/p3-host-contracts.md/unrelated.py",
          "p3_host_contracts/../temper_ai/x.py", "p3_host_contracts/./x.py", "/p3_host_contracts/x.py",
          "p3_host_contracts/x.py\nunrelated", "p3_host_contracts/x\t.py", "p3_host_contracts/x py", "p3_host_contracts\\x.py"]
TREE = {"p3_host_contracts/__init__.py", "tests/test_p3_host_contracts/test_value.py"}


def classify(paths, tree=TREE):
    return st.select([st.Change(p) for p in paths], RULES, tree, lambda: pytest.fail("leaf classification built an application graph"))


@pytest.mark.parametrize("path", SAFE)
def test_exact_scope_including_new_leaf_fixtures_never_reads_application_graph(path):
    assert st.host_contract_path(path)
    result = classify([path])
    assert result.route == st.HOST_CONTRACTS and result.tests == {"tests/test_p3_host_contracts/test_value.py"}
    assert not result.frontend and not result.e2e


@pytest.mark.parametrize("path", UNSAFE)
def test_path_boundaries_and_allowed_word_canaries_do_not_enter_leaf(path):
    assert not st.host_contract_path(path)
    # Pair with one true leaf so the mixed/all-paths check must bite too.
    result = classify(["p3_host_contracts/__init__.py", path])
    assert result.route == "ordinary" and result.everything


@pytest.mark.parametrize("path", [
    "tests/conftest.py", "tests/__init__.py", "tests/machine_slot.py", "pyproject.toml", "uv.lock",
    "scripts/select_tests.py", "scripts/test-selection.toml", "scripts/dependency_graph.py",
    "scripts/git-hooks/pre-commit", "scripts/check_host_contracts.py", "scripts/host_contract_pytest.py",
    "scripts/show_versions.py", "tests/test_scripts/test_host_contract_route.py",
    "tests/test_scripts/host_contract_fixture.py", ".github/workflows/ci.yml", "docs/other.md", "unknown/thing.bin",
])
def test_mixed_changes_infrastructure_and_unrelated_docs_keep_full_route(path):
    result = classify([*SAFE, path])
    assert result.everything and result.frontend and result.e2e and result.python == "all"


@pytest.mark.parametrize("tree", [set(), {"p3_host_contracts/__init__.py"}, {"tests/test_p3_host_contracts/test_value.py"}])
def test_missing_package_or_test_files_are_not_a_leaf_success(tree):
    assert classify([st.HOST_DOC], tree).everything


def test_empty_unknown_and_invalid_paths_fail_closed():
    for paths in ([], ["unknown.py"], ["p3_host_contracts/x.py\nother.py"]):
        assert classify(paths).everything


def test_staged_renames_both_sides_deletions_and_symlinks(leaf):
    # Initial supplier additions are staged; outside-to-inside appears as D+A, never just the target.
    leaf.git("mv", "README.md", "p3_host_contracts/old-readme.md")
    assert picked(leaf, "--staged").everything
    leaf.git("mv", "p3_host_contracts/old-readme.md", "README.md")
    assert picked(leaf, "--staged").route == st.HOST_CONTRACTS
    leaf.git("mv", "tests/test_p3_host_contracts/test_contract.py", "tests/test_p3_host_contracts/test_renamed.py")
    assert picked(leaf, "--staged").route == st.HOST_CONTRACTS
    leaf.git("mv", "tests/test_p3_host_contracts/test_renamed.py", "tests/test_outside.py")
    assert picked(leaf, "--staged").everything
    leaf.git("mv", "tests/test_outside.py", "tests/test_p3_host_contracts/test_contract.py")
    leaf.remove("tests/test_p3_host_contracts")
    assert picked(leaf, "--staged").everything
    leaf.put("tests/test_p3_host_contracts/test_minimal.py", "def test_minimal():\n    pass\n")
    leaf.git("add", ".")
    (leaf.root / "p3_host_contracts/link.py").symlink_to("../temper_ai/__init__.py")
    leaf.git("add", ".")
    assert picked(leaf, "--staged").everything


def test_committed_rename_outside_supplier_keeps_both_sides(leaf):
    # Make a source-only comparison without running any check bypass: git's tree plumbing creates
    # a synthetic commit object, not a product commit or a hook success claim.
    git = st.Git(leaf.root)
    tree = git._text("write-tree")
    commit = subprocess.run(["git", "-C", str(leaf.root), "commit-tree", tree, "-p", "HEAD", "-m", "fixture tree"],
                            capture_output=True, text=True, env=leaf.env)
    code = commit.returncode
    assert code == 0
    base = commit.stdout.strip()
    leaf.git("mv", "README.md", "p3_host_contracts/readme.md")
    tree = git._text("write-tree")
    commit = subprocess.run(["git", "-C", str(leaf.root), "commit-tree", tree, "-p", base, "-m", "fixture rename"],
                            capture_output=True, text=True, env=leaf.env)
    code = commit.returncode
    assert code == 0
    result = picked(leaf, "--base", base, "--head", commit.stdout.strip())
    assert result.everything


@pytest.mark.parametrize("selection", [None, "python none", "route host-contracts-extra\npython none",
    "route ordinary\npython tests/x.py --bad", "route ordinary\npython all",
    "route ordinary\npython none\nfrontend\nfrontend", "route ordinary\npython none\ne2e\ne2e",
    "route host-contracts\npython none", "route host-contracts\npython tests/unrelated.py",
    "route host-contracts\npython tests/test_p3_host_contracts/test_x.py\nfrontend",
    "route ordinary\nroute ordinary\npython none", "route ordinary\npython none\npython none"])
def test_selector_failure_or_malformed_output_keeps_recorded_full_phases(host, selection):
    """Recording tools only: phase routing, NOT a real full-suite pass."""
    host.install("absent")
    source = "raise SystemExit(2)\n" if selection is None else f"print({selection!r})\n"
    program(host.repo / "scripts/select_tests.py", FAKE_TOOL + source, host.dir)
    result = run_hook(host)
    assert result.code == 0
    expected = [(kind, ["tests/" if arg == "tests/test_probe.py" else arg for arg in args])
                for kind, args in phases(host.repo)]
    assert split(host.calls()) == ([], [(*phase, False) for phase in expected])


def test_runner_reclassifies_instead_of_trusting_a_leaf_claim(leaf):
    leaf.put("docs/unrelated.md", "mixed\n")
    leaf.git("add", ".")
    result = leaf.call(sys.executable, "scripts/check_host_contracts.py")
    assert (result.code, result.warned("Host-contract check refused")) == (2, 1)


def test_ci_uses_same_committed_base_and_preserves_required_full_fallbacks():
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    assert ci["select"]["outputs"]["route"] == "${{ steps.pick.outputs.route }}"
    assert ci["select"]["outputs"]["base"] == "${{ steps.pick.outputs.base }}"
    for job, phase in (("lint", "lint"), ("typecheck", "type"), ("test", "test")):
        assert ci[job]["needs"] == "select"
        steps = ci[job]["steps"]
        ordinary = [s for s in steps if s.get("if") == "needs.select.outputs.route != 'host-contracts'"]
        leaf = [s for s in steps if s.get("if") == "needs.select.outputs.route == 'host-contracts'"]
        assert len(ordinary) == len(leaf) == 1
        assert f'--base "$CHECK_BASE" --head HEAD --phase {phase}' in leaf[0]["run"]
        assert leaf[0]["env"]["CHECK_BASE"] == "${{ needs.select.outputs.base }}"
        assert steps[0]["with"]["fetch-depth"] == 0
    assert "route != 'host-contracts'" in ci["test-postgres"]["if"]
    assert "!= 'none'" in ci["test-postgres"]["if"]
    assert "!= 'false'" in ci["frontend"]["if"] and "!= 'false'" in ci["e2e"]["if"]


def test_git_malformed_changes_are_rejected(monkeypatch, tmp_path):
    git = st.Git(tmp_path)
    for output in (b"M\0p3_host_contracts/x.py", b"R100\0p3_host_contracts/x.py\0", b"M\0\0"):
        monkeypatch.setattr(git, "_run", lambda *args: subprocess.CompletedProcess([], 0, output, b""))
        with pytest.raises(st.SelectionError):
            git.changes("--cached")
