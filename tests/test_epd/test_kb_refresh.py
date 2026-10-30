"""Fixed classification answers, not historical automatic-rewrite accuracy.

The initial real replay array is empty (H2 miss). These invented repositories
prove only classification, conservative hints and report-only byte safety.
Reuse the checker's repository factory and actual capabilities generator.
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_epd.test_kb_check import BIN, commit, export, git, kb_check, put
from tests.test_epd.test_kb_check import make_repo as make_repo  # noqa: F401

sys.path.insert(0, str(BIN))
try:
    refresh = importlib.import_module("kb_refresh")
finally:
    sys.path.pop(0)


def snapshot(root: Path) -> dict[str, tuple[str, bytes | str | int]]:
    """Include all bytes, modes, directories and links, even .git and ignored files."""
    result = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[name] = ("link", os.readlink(path))
        elif path.is_dir():
            result[name] = ("directory", path.stat().st_mode)
        else:
            result[name] = ("file", path.read_bytes())
            result[name + "\0mode"] = ("mode", path.stat().st_mode)
    return result


def run(root: Path, *args: str, script: Path = BIN / "kb_refresh.py") -> tuple[int, bytes, bytes]:
    result = subprocess.run([sys.executable, str(script), "--repo", str(root), *args], capture_output=True)
    return result.returncode, result.stdout, result.stderr


def unchanged_cli(root: Path, status: int, *expected: str, script: Path = BIN / "kb_refresh.py") -> bytes:
    """Every fixture gets two default runs and two explicitly refused write attempts."""
    before = snapshot(root)
    outputs = []
    for args in [(), ("--write",)]:
        first = run(root, *args, script=script)
        assert first == run(root, *args, script=script)
        assert first[0] == status
        assert (first[2] != b"") == (status == 2)
        assert refresh.REPORT_ONLY.encode() in first[1]
        assert (refresh.WRITE_REFUSAL.encode() in first[1]) == bool(args)
        for text in expected:
            assert text.encode() in first[1]
        outputs.append(first[1])
        assert snapshot(root) == before
    assert outputs[1].replace((refresh.WRITE_REFUSAL + "\n").encode(), b"", 1) == outputs[0]
    return outputs[0]


def classifier(root: Path):
    return refresh.ReferenceClassifier(refresh.ReferenceResolver(root))


def test_clean_uses_shared_recognition_and_skips_generated_file(make_repo):
    root = make_repo(
        {"main.py": "Ready = 1\n", "backend/rollcall/engine/rules.py": "Rule = 1\n",
         "frontend/src/lib/view.ts": "View = 1\n"},
        "`main.py::Ready` `engine/rules.py::Rule()` `lib/view.ts::View` `engine/`\n"
        "`/api/main.py` `https://host/main.py` `~/main.py` `$ROOT/main.py` "
        "`--main.py` `*.py` `<root>/main.py` `not a ref.py` `Ready`\n",
    )
    generated = root / ".temper/topics/capabilities.md"
    generated.write_bytes(generated.read_bytes() + b"\n`absent-generated.py`\n")
    put(root, ".temper/core/long.md", "x" * 14004)  # the budget is kb_check's job
    assert kb_check.check_refs(root, root / ".temper") == ([], 4)
    output = unchanged_cli(root, 0, "4 refs checked; 0 findings; 0 writes.")
    assert b"absent-generated" not in output
    assert b"--- " not in output  # no pretend-to-apply diff
    assert refresh.iter_refs is sys.modules["kb_check"].iter_refs
    assert refresh.has_symbol is sys.modules["kb_check"].has_symbol
    assert refresh.ReferenceResolver is sys.modules["kb_check"].ReferenceResolver


def test_deleted_is_not_a_symbol_based_move(make_repo):
    root = make_repo({"old.py": "Kept = 1\n", "elsewhere.py": "Kept = 1\n"}, "`old.py::Kept`\n")
    git(root, "rm", "old.py")
    commit(root)
    finding = classifier(root).classify("old.py::Kept")
    assert finding.category == "DELETED"
    assert finding.candidates == ()
    assert finding.renames == ()
    assert finding.symbol_hints == ("elsewhere.py",)
    assert finding.suggestion is None
    unchanged_cli(root, 1, "DELETED", "symbol occurrence (not a definition or repair): `elsewhere.py`")


@pytest.mark.parametrize("elsewhere", [False, True])
def test_removed_symbol_and_exhaustive_occurrence_hints(elsewhere, make_repo):
    files = {"source.py": "KeptExtra = 1\n", "z.py": "KeptExtra = 2\n"}
    if elsewhere:
        files.update({"b.py": "# Kept is only a comment\n", "a.py": "Kept = 1\n"})
    root = make_repo(files, "`source.py::Kept()`\n")
    put(root, "local.py", "Kept = 10\n")
    put(root, "ignored/shadow.py", "Kept = 20\n")
    put(root, ".temper/topics/self.md", "Kept `source.py::Kept()`\n")
    commit(root)
    # local.py was committed above; explicitly make it a local-only shadow again.
    git(root, "rm", "--cached", "local.py")
    finding = classifier(root).classify("source.py::Kept()")
    assert finding.category == ("SYMBOL_ELSEWHERE" if elsewhere else "SYMBOL_GONE")
    assert finding.symbol_hints == (("a.py", "b.py") if elsewhere else ())
    assert finding.suggestion is None
    unchanged_cli(root, 1, finding.category, "2 refs checked; 2 findings; 0 writes.")


@pytest.mark.parametrize("destination,expected", [
    ("nested/source.py", "nested/source.py::Kept()"),
    ("backend/rollcall/engine/source.py", "engine/source.py::Kept()"),
    ("frontend/src/lib/source.ts", "lib/source.ts::Kept()"),
])
def test_unique_short_path_uses_shortest_resolving_form(destination, expected, make_repo):
    ref = Path(destination).name + "::Kept()"
    root = make_repo({destination: "Kept = 1\n"}, f"`{ref}`\n")
    finding = classifier(root).classify(ref)
    assert finding.category == "SHORT"
    assert finding.candidates == (destination,)
    assert finding.suggestion == expected
    unchanged_cli(root, 1, f"candidate reference (review only): `{expected}`")


def test_shortening_cannot_select_an_earlier_base(make_repo):
    root = make_repo(
        {"frontend/src/lib/source.ts": "Kept = 1\n", "lib/source.ts": "Other = 1\n"},
        "`src/lib/source.ts::Kept`\n",
    )
    finding = classifier(root).classify("src/lib/source.ts::Kept")
    assert finding.category == "SHORT"
    assert finding.candidates == ("frontend/src/lib/source.ts",)
    assert finding.suggestion == "frontend/src/lib/source.ts::Kept"
    unchanged_cli(root, 1, "candidate reference (review only): `frontend/src/lib/source.ts::Kept`")


def test_ambiguous_lists_every_tracked_match_without_symbol_tiebreak(make_repo):
    root = make_repo(
        {"z/source.py": "Other = 1\n", "a/source.py": "Kept = 1\n", "m/source.py": "Other = 2\n",
         "not-source.py": "Kept = 1\n"}, "`source.py::Kept`\n",
    )
    finding = classifier(root).classify("source.py::Kept")
    assert finding.category == "AMBIGUOUS"
    assert finding.candidates == ("a/source.py", "m/source.py", "z/source.py")
    assert finding.suggestion is None
    unchanged_cli(root, 1, "AMBIGUOUS", "path: `a/source.py`", "path: `m/source.py`", "path: `z/source.py`")


def test_unique_path_missing_symbol_is_not_a_suggestion(make_repo):
    root = make_repo({"pkg/source.py": "KeptExtra = 1\n", "other.py": "Kept = 2\n"}, "`source.py::Kept`\n")
    finding = classifier(root).classify("source.py::Kept")
    assert finding.category == "SYMBOL_NOT_IN_CANDIDATE"
    assert finding.candidates == ("pkg/source.py",)
    assert finding.symbol_hints == ("other.py",)
    assert finding.suggestion is None
    unchanged_cli(root, 1, "SYMBOL_NOT_IN_CANDIDATE")


def test_git_move_records_unfiltered_diff_and_caches_queries(make_repo, monkeypatch):
    root = make_repo({"old.py": "Kept = 1\n", "another.py": "Other = 2\n"}, "`old.py::Kept`\n" * 2)
    git(root, "mv", "old.py", "new.py")
    git(root, "mv", "another.py", "another-new.py")
    commit(root)
    sha = git(root, "rev-parse", "HEAD").decode().strip()
    calls = []
    original = subprocess.run

    def record(command, **kwargs):
        calls.append(command)
        return original(command, **kwargs)

    monkeypatch.setattr(refresh.subprocess, "run", record)
    inspect = classifier(root)
    finding = inspect.classify("old.py::Kept")
    assert finding.category == "MOVED"
    assert finding.candidates == ("new.py",)
    assert finding.suggestion == "new.py::Kept"
    assert finding.renames == (refresh.Rename(sha, "old.py", "new.py"),)
    assert inspect.classify("old.py::Kept") is finding
    assert inspect.classify("old.py").category == "MOVED"
    diffs = [call for call in calls if "diff" in call]
    assert len(diffs) == 1
    assert diffs[0][-2:] == [f"{sha}^", sha]
    assert "-M" in diffs[0] and "--name-status" in diffs[0] and "-z" in diffs[0]
    assert "--" not in diffs[0]  # no pathspec: destination and unrelated rename are visible
    assert sum("ls-files" in call for call in calls) == 1
    unchanged_cli(root, 1, f"git rename {sha}: `old.py` -> `new.py`")


@pytest.mark.parametrize("case", ["beyond-detection", "missing-symbol", "unrecognized-suffix"])
def test_rename_does_not_overclaim(case, make_repo):
    root = make_repo({"old.py": "Kept = 1\n"}, "`old.py::Kept`\n")
    destination = "new.cpp" if case == "unrecognized-suffix" else "new.py"
    git(root, "mv", "old.py", destination)
    if case == "beyond-detection":
        put(root, destination, "EntirelyDifferent = 100\n" * 30)
    commit(root)
    if case == "missing-symbol":
        put(root, destination, "KeptExtra = 1\n")  # current content wins over the index
    finding = classifier(root).classify("old.py::Kept")
    expected = {"beyond-detection": "DELETED", "missing-symbol": "SYMBOL_NOT_IN_CANDIDATE",
                "unrecognized-suffix": "MOVED"}[case]
    assert finding.category == expected
    assert finding.suggestion is None
    if case == "beyond-detection":
        assert finding.renames == ()
    unchanged_cli(root, 1, expected)


@pytest.mark.parametrize("case", ["deleted-target", "untracked-target", "rename-chain", "latest-deletion"])
def test_historical_rename_is_not_enough(case, make_repo):
    root = make_repo({"old.py": "Kept = 1\n"}, "`old.py::Kept`\n")
    git(root, "mv", "old.py", "new.py")
    commit(root)
    if case in {"deleted-target", "untracked-target"}:
        git(root, "rm", "new.py")
        commit(root)
        if case == "untracked-target":
            put(root, "new.py", "Kept = 1\n")
    elif case == "rename-chain":
        git(root, "mv", "new.py", "third.py")
        commit(root)
    else:
        put(root, "old.py", "Different = 20\n")
        commit(root)
        git(root, "rm", "old.py")
        commit(root)
    finding = classifier(root).classify("old.py::Kept")
    assert finding.category == "DELETED"
    assert finding.suggestion is None
    assert finding.candidates == ()
    unchanged_cli(root, 1, "DELETED")


def test_multiple_historical_bases_are_ambiguous(make_repo):
    root = make_repo(
        {"old.py": "First = 1\n", "frontend/src/old.py": "Second = 2\n"}, "`old.py`\n",
    )
    git(root, "mv", "old.py", "first.py")
    git(root, "mv", "frontend/src/old.py", "frontend/src/second.py")
    commit(root)
    finding = classifier(root).classify("old.py")
    assert finding.category == "AMBIGUOUS"
    assert finding.candidates == ("first.py", "frontend/src/second.py")
    assert len(finding.renames) == 2
    assert finding.suggestion is None
    unchanged_cli(root, 1, "AMBIGUOUS", "path: `first.py`", "path: `frontend/src/second.py`")


@pytest.mark.parametrize("conflict", ["none", "tracked-target", "deleted-target"])
def test_short_and_move_evidence_is_combined_not_guessed(conflict, make_repo):
    files = {"old.py": "Kept = 1\n"}
    if conflict != "none":
        files["pkg/old.py"] = "Other = 2\n"
    root = make_repo(files, "`old.py`\n")
    if conflict == "none":
        (root / "pkg").mkdir()
    git(root, "mv", "old.py", "pkg/old.py" if conflict == "none" else "new.py")
    commit(root)
    if conflict == "deleted-target":
        git(root, "rm", "new.py")
        commit(root)
    finding = classifier(root).classify("old.py")
    assert finding.category == ("MOVED" if conflict == "none" else "AMBIGUOUS")
    assert finding.candidates == (("pkg/old.py",) if conflict == "none" else ("new.py", "pkg/old.py"))
    assert finding.suggestion == ("pkg/old.py" if conflict == "none" else None)
    unchanged_cli(root, 1, finding.category)


@pytest.mark.parametrize("path", ["shadow.py", "ignored/shadow.py", "local/", "ignored/", "empty/"])
def test_untracked_or_ignored_shadows_are_never_candidates(path, make_repo):
    root = make_repo({"pkg/shadow.py": "Kept = 1\n"}, f"`{path}`\n")
    if path.endswith("/"):
        (root / path).mkdir(parents=True, exist_ok=True)
        if path != "empty/":
            put(root, path + "item.py", "Kept = 1\n")
    else:
        put(root, path, "Kept = 1\n")
    finding = classifier(root).classify(path)
    assert finding.category == "UNTRACKED"
    assert finding.candidates == (path.rstrip("/"),)
    assert finding.suggestion is None
    unchanged_cli(root, 1, "UNTRACKED")


@pytest.mark.parametrize("symbol", ["Tracked", "Shadow"])
def test_local_shadow_does_not_beat_later_tracked_base(symbol, make_repo):
    root = make_repo({"frontend/src/lib/view.ts": "Tracked = 1\n"}, f"`lib/view.ts::{symbol}`\n")
    put(root, "lib/view.ts", "Shadow = 1\n")
    finding = classifier(root).classify(f"lib/view.ts::{symbol}")
    if symbol == "Tracked":
        assert finding is None
    else:
        assert finding.category == "SYMBOL_GONE" and finding.symbol_hints == ()
    unchanged_cli(root, 0 if symbol == "Tracked" else 1)


@pytest.mark.parametrize("case", ["file", "directory", "short-symbol"])
def test_missing_tracked_content_uses_index(case, make_repo):
    span = {"file": "package/source.py::Kept", "directory": "package/", "short-symbol": "source.py::Kept"}[case]
    root = make_repo({"package/source.py": "Kept = 1\n"}, f"`{span}`\n")
    (root / "package/source.py").unlink()
    (root / "package").rmdir()
    finding = classifier(root).classify(span)
    if case == "short-symbol":
        assert finding.category == "SHORT"
        assert finding.suggestion == "package/source.py::Kept"
    else:
        assert finding is None
    unchanged_cli(root, 1 if case == "short-symbol" else 0)


def test_staged_addition_without_head_and_staged_deletion(tmp_path, make_repo):
    root = tmp_path / "unborn"
    root.mkdir()
    git(root, "init", "-q")
    put(root, ".temper/refs.md", "`new.py::Kept` `short.py::Kept`\n")
    put(root, "new.py", "Kept = 1\n")
    put(root, "pkg/short.py", "Kept = 1\n")
    git(root, "add", "new.py", "pkg/short.py")
    (root / "new.py").unlink()
    inspect = classifier(root)
    assert inspect.classify("new.py::Kept") is None
    assert inspect.classify("short.py::Kept").category == "SHORT"
    unchanged_cli(root, 1, "SHORT")
    other = make_repo({"source.py": "Kept = 1\n"}, "`source.py`\n")
    git(other, "rm", "--cached", "source.py")
    assert classifier(other).classify("source.py").category == "UNTRACKED"
    unchanged_cli(other, 1, "UNTRACKED")


def test_directory_with_symbol_and_directory_move_are_not_file_candidates(make_repo):
    root = make_repo({"old/item.py": "Kept = 1\n", "folder.py/item.py": "Kept = 1\n"},
                     "`old/` `folder.py::Kept`\n")
    git(root, "mv", "old", "new")
    commit(root)
    inspect = classifier(root)
    assert inspect.classify("old/").category == "DELETED"
    finding = inspect.classify("folder.py::Kept")
    assert finding.category == "SYMBOL_ELSEWHERE"
    assert finding.symbol_hints == ("folder.py/item.py", "new/item.py")
    unchanged_cli(root, 1, "DELETED", "SYMBOL_ELSEWHERE")


@pytest.mark.parametrize("valid", [False, True])
def test_suffix_symlink_requires_a_tracked_target(valid, make_repo):
    root = make_repo({"source.py": "Kept = 1\n"}, "`link.py::Kept`\n")
    (root / "pkg").mkdir()
    (root / "pkg/link.py").symlink_to("../source.py" if valid else "../ignored/local.py")
    commit(root)
    put(root, "ignored/local.py", "Kept = 2\n")
    finding = classifier(root).classify("link.py::Kept")
    assert finding.category == ("SHORT" if valid else "DELETED")
    assert finding.suggestion == ("pkg/link.py::Kept" if valid else None)
    unchanged_cli(root, 1, finding.category)


def test_unsafe_symlink_does_not_remove_an_ambiguity(make_repo):
    root = make_repo({"a/source.py": "Kept = 1\n"}, "`source.py::Kept`\n")
    (root / "b").mkdir()
    (root / "b/source.py").symlink_to("../ignored/local.py")
    commit(root)
    put(root, "ignored/local.py", "Kept = 1\n")
    finding = classifier(root).classify("source.py::Kept")
    assert finding.category == "AMBIGUOUS"
    assert finding.candidates == ("a/source.py", "b/source.py")
    assert finding.suggestion is None
    unchanged_cli(root, 1, "AMBIGUOUS")


def test_plain_folder_retains_disk_lookup_without_invented_tracked_search(make_repo, tmp_path):
    root = make_repo({"pkg/short.py": "Kept = 1\n", "source.py": "Other = 1\n"},
                     "`shadow.py::Local` `empty/` `short.py` `source.py::Kept`\n")
    plain = export(root, tmp_path / "plain")
    put(plain, "shadow.py", "Local = 1\n")
    (plain / "empty").mkdir()
    inspect = classifier(plain)
    assert inspect.tracked is None
    assert inspect.classify("shadow.py::Local") is None
    assert inspect.classify("empty/") is None
    assert inspect.classify("short.py").category == "DELETED"
    assert inspect.classify("source.py::Kept").category == "SYMBOL_GONE"
    unchanged_cli(plain, 1, "4 refs checked; 2 findings; 0 writes.")
    put(plain, ".temper/topics/refs.md", "`shadow.py::Local` `empty/`\n")
    unchanged_cli(plain, 0, "2 refs checked; 0 findings; 0 writes.")


def test_unicode_adjacent_spans_crlf_generated_content_and_in_repo_cli(make_repo):
    root = make_repo({"pkg/café.py": "Kept = 1\n", "old.py": "Kept = 1\n"}, "")
    git(root, "mv", "old.py", "renamed.py")
    commit(root)
    (root / ".temper/topics/refs.md").write_bytes(
        "前🙂`café.py::Kept``old.py::Kept`後\r\n`deleted.py` é\t\r\n".encode()
    )
    for name in ["kb_check.py", "kb_reference_history.py", "kb_refresh.py"]:
        (root / "tools").mkdir(exist_ok=True)
        shutil.copyfile(BIN / name, root / "tools" / name)
    output = unchanged_cli(root, 1, "SHORT", "MOVED", "DELETED", script=root / "tools/kb_refresh.py")
    assert "`café.py::Kept`".encode() in output
    assert not (root / "tools/__pycache__").exists()


def test_linked_worktree_subdirectory_and_quoted_git_names(make_repo, tmp_path):
    root = make_repo({"nested/old.py": "Kept = 1\n",
                      "nested/.temper/refs.md": "`old.py::Kept`\n"}, "")
    git(root, "mv", "nested/old.py", "nested/café.py")
    commit(root)
    linked = tmp_path / "linked"
    git(root, "worktree", "add", "--detach", str(linked), "HEAD")
    parent_before = snapshot(root)
    inspect = classifier(linked / "nested")
    finding = inspect.classify("old.py::Kept")
    assert finding.category == "MOVED"
    assert finding.suggestion == "café.py::Kept"
    assert finding.renames[0].old_path == "nested/old.py"
    assert finding.renames[0].new_path == "nested/café.py"
    unchanged_cli(linked, 0, "0 refs checked; 0 findings; 0 writes.")
    unchanged_cli(linked / "nested", 1, "MOVED")
    assert snapshot(root) == parent_before


@pytest.mark.parametrize("suffix", [False, True])
def test_rename_outside_repo_subdirectory_cannot_supply_a_candidate(suffix, make_repo):
    files = {"nested/old.py": "Kept = 1\n", "nested/.temper/refs.md": "`old.py`\n"}
    if suffix:
        files["nested/pkg/old.py"] = "Other = 2\n"
    root = make_repo(files, "")
    git(root, "mv", "nested/old.py", "outside.py")
    commit(root)
    finding = classifier(root / "nested").classify("old.py")
    assert finding.category == ("AMBIGUOUS" if suffix else "DELETED")
    assert finding.candidates == (("../outside.py", "pkg/old.py") if suffix else ())
    assert finding.suggestion is None
    unchanged_cli(root / "nested", 1, finding.category)


def test_rename_to_filename_with_whitespace_is_hint_not_reference(make_repo):
    root = make_repo({"old.py": "Kept = 1\n"}, "`old.py::Kept`\n")
    git(root, "mv", "old.py", "new name.py")
    commit(root)
    finding = classifier(root).classify("old.py::Kept")
    assert finding.category == "MOVED"
    assert finding.candidates == ("new name.py",)
    assert finding.suggestion is None
    unchanged_cli(root, 1, "path: `new name.py`")


def test_missing_knowledge_folder_is_a_finding(tmp_path):
    unchanged_cli(tmp_path, 1, f"no .temper/ in {tmp_path}")


@pytest.mark.parametrize("case", ["index", "markdown", "source"])
def test_internal_errors_are_exit_two_and_never_write(case, make_repo):
    root = make_repo({"source.py": "Kept = 1\n"}, "`source.py::Kept`\n")
    if case == "index":
        (root / ".git/index").write_bytes(b"broken")
    elif case == "markdown":
        (root / ".temper/topics/refs.md").write_bytes(b"\xff")
    else:
        (root / "source.py").unlink()
        (root / "source.py").mkdir()
    unchanged_cli(root, 2)


def test_usage_errors_are_exit_two(tmp_path):
    before = snapshot(tmp_path)
    assert run(tmp_path, "--unknown")[0] == 2
    assert run(tmp_path / "absent")[0] == 2
    assert run(tmp_path, "--write", "--unknown")[0] == 2
    assert snapshot(tmp_path) == before
