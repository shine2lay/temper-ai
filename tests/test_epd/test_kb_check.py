"""Known reference verdicts in Git checkouts and their plain-folder exports.

No target imports, model calls or server: the checker and capabilities.py run
as stdlib scripts, against tiny repositories with a generated capability map.
"""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[2] / "configs" / "epd" / "bin"
SPEC = importlib.util.spec_from_file_location("kb_check_under_test", BIN / "kb_check.py")
assert SPEC is not None and SPEC.loader is not None
kb_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kb_check)


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=KB test", "-c",
         "user.email=kb@example.invalid", "-c", "commit.gpgsign=false", *args],
        capture_output=True, check=True,
    ).stdout


def put(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def commit(root: Path) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-qm", "fixture")


@pytest.fixture
def make_repo(tmp_path):
    def make(files: dict[str, str], refs: str) -> Path:
        root = tmp_path / "repo"
        root.mkdir()
        git(root, "init", "-q")
        put(root, ".gitignore", "ignored/\nnode_modules/\n")
        put(root, ".temper/topics/refs.md", refs)
        for name, text in files.items():
            put(root, name, text)
        # Derived reference is owned by the real generator, not a copied format.
        subprocess.run(
            [sys.executable, str(BIN / "capabilities.py"), "--repo", str(root)],
            capture_output=True, check=True,
        )
        commit(root)
        return root
    return make


def export(root: Path, destination: Path) -> Path:
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(git(root, "archive", "HEAD"))) as archive:
        archive.extractall(destination, filter="data")
    return destination


def run(root: Path) -> tuple[int, bytes, bytes]:
    result = subprocess.run(
        [sys.executable, str(BIN / "kb_check.py"), "--repo", str(root)],
        capture_output=True,
    )
    return result.returncode, result.stdout, result.stderr


def refs(root: Path) -> tuple[list[str], int]:
    return kb_check.check_refs(root, root / ".temper")


def test_clean_bases_recognition_and_derived_ownership(make_repo):
    root = make_repo(
        {"main.py": "Ready = 1\n", "backend/rollcall/engine/rules.py": "Rule = 1\n",
         "frontend/src/lib/view.ts": "export const View = 1;\n"},
        "`main.py::Ready` `engine/rules.py::Rule()` `lib/view.ts::View` `engine/`\n"
        "`/api/main.py` `https://host/main.py` `~/main.py` `$ROOT/main.py` "
        "`--main.py` `*.py` `<root>/main.py` `not a ref.py` `Ready`\n",
    )
    # A prose span in the derived file is not part of REFS.
    with (root / ".temper/topics/capabilities.md").open("a") as stream:
        stream.write("\n`does-not-exist.py`\n")
    assert refs(root) == ([], 4)
    assert run(root) == (0, b"ok: 4 refs resolve, core/ ~0/4000 tokens, capabilities agree\n", b"")
    assert kb_check.resolve(root, "engine/rules.py") == root / "backend/rollcall/engine/rules.py"


@pytest.mark.parametrize("case", [
    "present", "missing-file", "untracked", "ignored", "tracked-directory",
    "missing-directory", "untracked-directory", "ignored-directory", "empty-directory",
])
def test_checkout_matches_archive_for_membership(case, make_repo, tmp_path):
    paths = {
        "present": "source.py", "missing-file": "source.py", "untracked": "shadow.py",
        "ignored": "ignored/shadow.py", "tracked-directory": "package/",
        "missing-directory": "package/", "untracked-directory": "local/",
        "ignored-directory": "ignored/", "empty-directory": "empty/",
    }
    path = paths[case]
    root = make_repo({"source.py": "Kept = 1\n", "package/item.py": "Kept = 1\n"}, f"`{path}`\n")
    clean = export(root, tmp_path / "export")
    if case == "missing-file":
        (root / "source.py").unlink()
    elif case == "missing-directory":
        (root / "package/item.py").unlink()
        (root / "package").rmdir()
    elif case in {"untracked", "ignored"}:
        put(root, path, "Kept = 1\n")
    elif case in {"untracked-directory", "ignored-directory"}:
        put(root, path + "item.py", "Kept = 1\n")
    elif case == "empty-directory":
        (root / path).mkdir()
    expected = [] if case in {"present", "missing-file", "tracked-directory", "missing-directory"} else [
        f"topics/refs.md:1: `{path}`: no such path"
    ]
    assert refs(root) == refs(clean) == (expected, 1)
    checkout = run(root)
    assert checkout == run(clean) == run(root)  # includes byte-identical repeat output
    assert checkout[0] == bool(expected)
    assert checkout[2] == b""


@pytest.mark.parametrize("symbol, succeeds", [("Kept", True), ("Gone", False), ("Keep", False)])
def test_missing_tracked_file_reads_symbol_from_index(symbol, succeeds, make_repo, tmp_path):
    root = make_repo({"source.py": "Kept = 1\n"}, f"`source.py::{symbol}`\n")
    clean = export(root, tmp_path / "export")
    (root / "source.py").unlink()
    resolver = kb_check.ReferenceResolver(root)
    target = resolver.resolve("source.py")
    assert target == root / "source.py"
    assert not target.exists()
    assert resolver.read_text(target) == "Kept = 1\n"
    assert not resolver.is_dir(target)
    expected = [] if succeeds else [f"topics/refs.md:1: `source.py::{symbol}`: {symbol} not found in source.py"]
    assert refs(root) == refs(clean) == (expected, 1)
    assert run(root) == run(clean)
    assert run(root)[0] == (0 if succeeds else 1)


def test_current_content_not_stale_index_decides_symbols(make_repo):
    root = make_repo({"source.py": "Kept = 1\n"}, "`source.py::Kept`\n")
    put(root, "source.py", "Other = 1\n")
    assert run(root) == (1, b"topics/refs.md:1: `source.py::Kept`: Kept not found in source.py\n", b"")


def test_staged_new_file_without_head_has_index_content(tmp_path):
    root = tmp_path / "new"
    root.mkdir()
    git(root, "init", "-q")
    put(root, ".temper/refs.md", "`new.py::Kept`\n")
    path = put(root, "new.py", "Kept = 1\n")
    git(root, "add", "new.py")
    path.unlink()
    assert refs(root) == ([], 1)


@pytest.mark.parametrize("committed", [False, True])
def test_deleted_file_cannot_be_hidden_by_local_shadow(committed, make_repo, tmp_path):
    root = make_repo({"source.py": "Kept = 1\n"}, "`source.py`\n")
    git(root, "rm", "--cached", "source.py")
    if committed:
        git(root, "commit", "-qm", "delete source")
        assert run(root) == run(export(root, tmp_path / "export"))
    assert (root / "source.py").exists()
    assert run(root) == (1, b"topics/refs.md:1: `source.py`: no such path\n", b"")


@pytest.mark.parametrize("symbol, succeeds", [("Tracked", True), ("Shadow", False)])
def test_untracked_earlier_base_does_not_win(symbol, succeeds, make_repo, tmp_path):
    root = make_repo({"frontend/src/lib/view.ts": "Tracked = 1\n"}, f"`lib/view.ts::{symbol}`\n")
    clean = export(root, tmp_path / "export")
    put(root, "lib/view.ts", "Shadow = 1\n")
    assert kb_check.resolve(root, "lib/view.ts") == root / "frontend/src/lib/view.ts"
    assert run(root) == run(clean)
    assert run(root)[0] == (0 if succeeds else 1)


@pytest.mark.parametrize("files, reference", [
    ({"one/nested.py": "Kept = 1\n"}, "nested.py"),
    ({"one/nested.py": "Kept = 1\n", "two/nested.py": "Kept = 1\n"}, "nested.py"),
    ({"one/nested.py": "Other = 1\n"}, "nested.py::Kept"),
])
def test_short_names_are_not_suffix_searches(files, reference, make_repo):
    root = make_repo(files, f"`{reference}`\n")
    assert run(root) == (1, f"topics/refs.md:1: `{reference}`: no such path\n".encode(), b"")


@pytest.mark.parametrize("rewritten", [False, True])
def test_rename_keeps_old_reference_broken(rewritten, make_repo, tmp_path):
    root = make_repo({"old.py": "Kept = 1\n"}, "`old.py::Kept`\n")
    git(root, "mv", "old.py", "new.py")
    if rewritten:
        put(root, "new.py", "EntirelyDifferent = 100\n" * 30)
    commit(root)
    assert run(root) == run(export(root, tmp_path / "export"))
    assert run(root) == (1, b"topics/refs.md:1: `old.py::Kept`: no such path\n", b"")


def test_directory_cannot_supply_symbol_even_when_missing(make_repo):
    root = make_repo({"folder.py/file.py": "Kept = 1\n"}, "`folder.py::Kept`\n")
    (root / "folder.py/file.py").unlink()
    (root / "folder.py").rmdir()
    assert run(root) == (1, b"topics/refs.md:1: `folder.py::Kept`: Kept not found in folder.py\n", b"")


def test_plain_folder_retains_disk_lookup_and_base_order(make_repo, tmp_path):
    root = make_repo({}, "`shadow.py::Local` `empty/` `lib/view.ts::First`\n")
    plain = export(root, tmp_path / "plain")
    put(plain, "shadow.py", "Local = 1\n")
    put(plain, "lib/view.ts", "First = 1\n")
    put(plain, "frontend/src/lib/view.ts", "Other = 1\n")
    (plain / "empty").mkdir()
    assert kb_check.ReferenceResolver(plain).tracked_files is None
    assert kb_check.resolve(plain, "lib/view.ts") == plain / "lib/view.ts"
    assert run(plain) == (0, b"ok: 3 refs resolve, core/ ~0/4000 tokens, capabilities agree\n", b"")


def test_ignored_symlink_to_local_dependency_does_not_resolve(make_repo, tmp_path):
    root = make_repo({}, "`node_modules/` `node_modules/vendor.py`\n")
    dependency = tmp_path / "dependency"
    put(dependency, "vendor.py", "Kept = 1\n")
    (root / "node_modules").symlink_to(dependency, target_is_directory=True)
    assert refs(root) == ([
        "topics/refs.md:1: `node_modules/`: no such path",
        "topics/refs.md:1: `node_modules/vendor.py`: no such path",
    ], 2)
    assert run(root) == run(export(root, tmp_path / "export"))


@pytest.mark.parametrize("missing", [False, True])
def test_tracked_symlink_reads_only_tracked_target(missing, make_repo, tmp_path):
    root = make_repo({"source.py": "Kept = 1\n"}, "`link.py::Kept`\n")
    (root / "link.py").symlink_to("source.py")
    commit(root)
    clean = export(root, tmp_path / "export")
    if missing:
        (root / "link.py").unlink()
        (root / "source.py").unlink()
    assert refs(root) == ([], 1)
    assert run(root) == run(clean)


def test_tracked_symlink_does_not_import_untracked_content(make_repo, tmp_path):
    root = make_repo({}, "`link.py::Kept`\n")
    (root / "link.py").symlink_to("ignored/local.py")
    commit(root)
    put(root, "ignored/local.py", "Kept = 1\n")
    assert run(root) == run(export(root, tmp_path / "export"))
    assert refs(root) == (["topics/refs.md:1: `link.py::Kept`: no such path"], 1)


def test_missing_knowledge_folder_keeps_failure(tmp_path):
    assert run(tmp_path) == (1, f"no .temper/ in {tmp_path}\n".encode(), b"")


def test_budget_diagnostic_unchanged(make_repo):
    root = make_repo({}, "")
    put(root, ".temper/core/map.md", "x" * 14004)
    assert run(root) == (1, b"core/: ~4001 tokens, over the 4000 budget: prune it\n", b"")


def test_derived_check_still_reports_drift(make_repo):
    root = make_repo({}, "")
    (root / ".temper/topics/capabilities.md").unlink()
    assert run(root) == (
        1, b"topics/capabilities.md: drift: .temper/topics/capabilities.md does not exist (0 capabilities found in code)\n", b"",
    )


def test_linked_worktree_and_subdirectory_index(make_repo, tmp_path):
    root = make_repo({"nested/source.py": "Kept = 1\n", "nested/.temper/refs.md": "`source.py::Kept`\n"}, "")
    worktree = tmp_path / "linked"
    git(root, "worktree", "add", "--detach", str(worktree), "HEAD")
    assert (worktree / ".git").is_file()
    assert refs(worktree / "nested") == ([], 1)
    (worktree / "nested/source.py").unlink()
    assert refs(worktree / "nested") == ([], 1)


def test_index_is_loaded_once_for_reference_batch(make_repo, monkeypatch):
    root = make_repo({"source.py": "Kept = 1\n"}, "`source.py::Kept`\n" * 20)
    calls = []
    original = subprocess.run

    def record(command, **kwargs):
        calls.append(command)
        return original(command, **kwargs)

    monkeypatch.setattr(kb_check.subprocess, "run", record)
    assert refs(root) == ([], 20)
    assert sum("ls-files" in command for command in calls) == 1


def test_broken_index_never_falls_back_to_disk(make_repo):
    root = make_repo({"source.py": "Kept = 1\n"}, "`source.py`\n")
    (root / ".git/index").write_bytes(b"broken")
    with pytest.raises(subprocess.CalledProcessError):
        kb_check.ReferenceResolver(root)
