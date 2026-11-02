"""Mutation witnesses for the classifier; no shell, application or supplier execution."""
from __future__ import annotations

import subprocess
import sys
import types
from dataclasses import replace

import pytest

from tests.test_scripts import test_host_contract_route as route
from tests.test_scripts.host_contract_fixture import ROOT
from tests.test_scripts.test_select_tests import RULES, st


def test_broader_config_cannot_make_a_mixed_change_pure():
    broad = st.Rule("too broad", "fixture", ("**",), (st.HOST_CONTRACTS,), (st.glob_to_regex("**"),))
    rules = replace(RULES, rules=(broad,))
    result = st.select([st.Change(st.HOST_DOC), st.Change("docs/unrelated.md")], rules, route.TREE, lambda: None)
    assert result.everything


def test_leaf_requires_its_explicit_rule_and_safe_complete_tree():
    missing_rule = replace(RULES, rules=tuple(r for r in RULES.rules if r.parts != (st.HOST_CONTRACTS,)))
    result = st.select([st.Change(st.HOST_DOC)], missing_rule, route.TREE, lambda: None)
    assert result.everything
    assert route.classify([st.HOST_DOC], route.TREE | {"p3_host_contracts/unsafe name.py"}).everything
    assert route.classify(["docs/unsafe name.md"]).everything


# These are executable changes to the production classifier, not second implementations.
# Each named existing assertion must fail after its own guard is removed or loosened.
MUTANTS = [
    ("empty", "if not changes:", "if False:", "empty", ()),
    ("changed-path", "if not all(safe_path(c.path) for c in changes):", "if False:", "rules", ()),
    ("mixed", "if len(host_changes) != len(changes):", "if False:", "broad", ()),
    ("explicit-rule", "elif not all((r := rules.rule_for(c.path)) and r.parts == (HOST_CONTRACTS,) for c in changes):", "elif False:", "rules", ()),
    ("package-present", 'HOST_PACKAGE + "/__init__.py" not in tree', "False", "missing", ({"tests/test_p3_host_contracts/test_value.py"},)),
    ("tests-present", 'not any(p.startswith(HOST_TESTS + "/") for p in tests_in_tree)', "False", "missing", ({"p3_host_contracts/__init__.py"},)),
    ("tree-path", 'elif not all(safe_path(p) for p in tree if p.startswith((HOST_PACKAGE + "/", HOST_TESTS + "/"))):', "elif False:", "rules", ()),
    ("doc-prefix", "path == HOST_DOC", "path.startswith(HOST_DOC)", "boundary", ("docs/p3-host-contracts.md.extra",)),
    ("doc-contains", "path == HOST_DOC", "HOST_DOC in path", "boundary", ("before/docs/p3-host-contracts.md",)),
    ("package-prefix", 'path.startswith((HOST_PACKAGE + "/", HOST_TESTS + "/"))', "path.startswith((HOST_PACKAGE, HOST_TESTS))", "boundary", ("p3_host_contracts_extra/value.py",)),
    ("tests-prefix", 'path.startswith((HOST_PACKAGE + "/", HOST_TESTS + "/"))', "path.startswith((HOST_PACKAGE, HOST_TESTS))", "boundary", ("tests/test_p3_host_contracts_extra/test_value.py",)),
    ("package-contains", 'path.startswith((HOST_PACKAGE + "/", HOST_TESTS + "/"))', 'HOST_PACKAGE + "/" in path or HOST_TESTS + "/" in path', "boundary", ("before/p3_host_contracts/value.py",)),
    ("component", 'not ({".", ".."} & set(path.split("/")))', "True", "boundary", ("p3_host_contracts/../temper_ai/x.py",)),
    ("fullmatch", "SAFE_PATH.fullmatch(path)", "SAFE_PATH.match(path)", "boundary", ("p3_host_contracts/x.py\nunrelated",)),
]


@pytest.mark.parametrize(("label", "old", "new", "witness", "args"), MUTANTS, ids=[m[0] for m in MUTANTS])
def test_each_classification_guard_has_a_named_bite(monkeypatch, label, old, new, witness, args):
    source = (ROOT / "scripts/select_tests.py").read_text()
    assert source.count(old) == 1, "mutation no longer names exactly one guard"
    name = "host_contract_guard_mutant"
    mutant = types.ModuleType(name)
    mutant.__file__ = str(ROOT / "scripts/select_tests.py")
    monkeypatch.setitem(sys.modules, name, mutant)
    exec(compile(source.replace(old, new), mutant.__file__, "exec"), mutant.__dict__)
    monkeypatch.setattr(route, "st", mutant)
    monkeypatch.setattr(sys.modules[__name__], "st", mutant)
    witnesses = {
        "empty": route.test_empty_unknown_and_invalid_paths_fail_closed,
        "rules": test_leaf_requires_its_explicit_rule_and_safe_complete_tree,
        "broad": test_broader_config_cannot_make_a_mixed_change_pure,
        "missing": route.test_missing_package_or_test_files_are_not_a_leaf_success,
        "boundary": route.test_path_boundaries_and_allowed_word_canaries_do_not_enter_leaf,
    }
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        witnesses[witness](*args)


@pytest.mark.parametrize("metadata", [b"120000 abc 0", b"160000 abc 0", b"100644 abc 2", b"100644extra abc 0"])
def test_file_modes_and_unmerged_index_fail_closed(monkeypatch, tmp_path, metadata):
    git = st.Git(tmp_path)
    monkeypatch.setattr(git, "_run", lambda *args: subprocess.CompletedProcess([], 0, metadata + b"\tfile.py\0", b""))
    assert not git.regular_files(st.INDEX, [st.HOST_PACKAGE])


def test_locked_check_tools_require_every_exact_version(monkeypatch, tmp_path):
    source = (ROOT / "scripts/show_versions.py").read_text()
    module = types.ModuleType("host_contract_versions")
    module.__file__ = str(ROOT / "scripts/show_versions.py")
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    lock = tmp_path / "uv.lock"
    wanted = dict.fromkeys(module.CHECK_TOOLS, "1.2.3")
    lock.write_text("".join(f'[[package]]\nname = "{name}"\nversion = "{version}"\n' for name, version in wanted.items()))
    monkeypatch.setattr(sys, "argv", ["show_versions.py", "--check", "--tools", "--lock", str(lock)])
    monkeypatch.setattr(module, "installed", lambda names: wanted.copy())
    assert module.main() == 0
    monkeypatch.setattr(module, "installed", lambda names: {k: v for k, v in wanted.items() if k != "mypy"})
    assert module.main() == 1
    monkeypatch.setattr(module, "installed", lambda names: {**wanted, "mypy": "9.9.9"})
    assert module.main() == 1
    lock.unlink()
    assert module.main() == 1
