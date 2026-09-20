"""Read / Write / Edit / Grep / Glob — the file tools ported from pi's behaviours.

The properties under test are the reasons the port happened, not incidental
details:

* Read bounds its output and says how to continue. temper had no reader at all;
  agents ran `cat`, so one lock file could return ~118k tokens — the whole
  context window in a single tool result, re-sent on every later iteration
  because this provider has no prompt caching.
* Edit applies several edits per call, all-or-nothing. One edit per call meant
  one round-trip per edit, and each round-trip resends the transcript.
* Grep and Glob are bounded and say what they left out, so an agent can narrow
  the query instead of assuming it saw everything.
* Paths are workspace-relative, which is what removes the "always pass an
  absolute path" instruction from the prompts.
"""

from pathlib import Path

import pytest

from temper_ai.tools.edit import Edit
from temper_ai.tools.glob import Glob
from temper_ai.tools.grep import Grep
from temper_ai.tools.read import MAX_BYTES, MAX_LINES, Read
from temper_ai.tools.write import Write


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("import os\n\n\ndef main():\n    print('hello')\n")
    (tmp_path / "README.md").write_text("# Project\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.py").write_text("print('vendored')\n")
    return tmp_path


def tool(cls, ws: Path):
    """Tools get workspace_root injected by ToolExecutor.register_tools in production."""
    return cls(config={"workspace_root": str(ws), "allowed_root": str(ws)})


class TestRead:
    def test_reads_a_file_by_workspace_relative_path(self, ws):
        r = tool(Read, ws).execute(path="src/app.py")
        assert r.success is True
        assert "def main():" in r.result
        assert r.metadata["lines"] == 5
        assert r.metadata["truncated"] is False

    def test_long_file_is_capped_and_says_how_to_continue(self, ws):
        (ws / "big.txt").write_text("\n".join(f"line {i}" for i in range(1, 5001)) + "\n")
        r = tool(Read, ws).execute(path="big.txt")
        assert r.success is True
        assert r.metadata["truncated"] is True
        assert r.result.count("\n") < 5000
        assert f"[Showing lines 1-{MAX_LINES} of 5000." in r.result
        assert f"Use offset={MAX_LINES + 1} to continue.]" in r.result

    def test_byte_cap_catches_few_lined_giant_files(self, ws):
        """A minified bundle is one line; a line cap alone would not bound it."""
        (ws / "bundle.js").write_text("x" * (MAX_BYTES * 3) + "\n")
        r = tool(Read, ws).execute(path="bundle.js")
        assert r.success is True
        assert len(r.result) < MAX_BYTES * 2
        assert "KB limit" in r.result

    def test_offset_and_limit_read_a_window(self, ws):
        (ws / "big.txt").write_text("\n".join(f"line {i}" for i in range(1, 101)) + "\n")
        r = tool(Read, ws).execute(path="big.txt", offset=50, limit=3)
        assert r.result.startswith("line 50\nline 51\nline 52")
        assert "Use offset=53 to continue.]" in r.result

    def test_offset_past_end_is_an_error_not_an_empty_result(self, ws):
        r = tool(Read, ws).execute(path="README.md", offset=999)
        assert r.success is False
        assert "past the end" in r.error

    def test_missing_file_and_directory_are_distinct_errors(self, ws):
        assert "not found" in tool(Read, ws).execute(path="nope.txt").error
        assert "is a directory" in tool(Read, ws).execute(path="src").error

    def test_does_not_modify_state_and_paths_are_local(self):
        assert Read.modifies_state is False
        assert Read.local_paths is True


class TestWrite:
    def test_creates_parent_directories(self, ws):
        r = tool(Write, ws).execute(path="a/b/c.txt", content="hi")
        assert r.success is True
        assert (ws / "a" / "b" / "c.txt").read_text() == "hi"

    def test_append_adds_instead_of_replacing(self, ws):
        t = tool(Write, ws)
        t.execute(path="log.txt", content="one\n")
        r = t.execute(path="log.txt", content="two\n", append=True)
        assert r.success is True
        assert (ws / "log.txt").read_text() == "one\ntwo\n"
        assert "Appended to" in r.result

    def test_overwrite_false_refuses_existing(self, ws):
        t = tool(Write, ws)
        t.execute(path="x.txt", content="first")
        r = t.execute(path="x.txt", content="second", overwrite=False)
        assert r.success is False
        assert "already exists" in r.error
        assert (ws / "x.txt").read_text() == "first"

    def test_accepts_the_old_file_path_alias(self, ws):
        assert tool(Write, ws).execute(file_path="alias.txt", content="ok").success is True


class TestEdit:
    def test_several_edits_in_one_call(self, ws):
        r = tool(Edit, ws).execute(
            path="src/app.py",
            edits=[
                {"old_text": "import os", "new_text": "import sys"},
                {"old_text": "print('hello')", "new_text": "print('goodbye')"},
            ],
        )
        assert r.success is True
        assert r.metadata["edits"] == 2
        text = (ws / "src" / "app.py").read_text()
        assert "import sys" in text and "goodbye" in text

    def test_all_or_nothing_when_one_edit_fails(self, ws):
        """A half-applied batch leaves a file nobody expects; the agent cannot tell which half landed."""
        original = (ws / "src" / "app.py").read_text()
        r = tool(Edit, ws).execute(
            path="src/app.py",
            edits=[
                {"old_text": "import os", "new_text": "import sys"},
                {"old_text": "this text is not in the file", "new_text": "x"},
            ],
        )
        assert r.success is False
        assert "not found" in r.error
        assert (ws / "src" / "app.py").read_text() == original, "the first edit must not have landed"

    def test_ambiguous_old_text_is_refused_with_the_count(self, ws):
        (ws / "dup.txt").write_text("value\nvalue\n")
        r = tool(Edit, ws).execute(path="dup.txt", edits=[{"old_text": "value", "new_text": "x"}])
        assert r.success is False
        assert "found 2 occurrences" in r.error
        assert "replace_all=true" in r.error
        assert (ws / "dup.txt").read_text() == "value\nvalue\n"

    def test_replace_all_allows_it(self, ws):
        (ws / "dup.txt").write_text("value\nvalue\n")
        r = tool(Edit, ws).execute(
            path="dup.txt", edits=[{"old_text": "value", "new_text": "x", "replace_all": True}]
        )
        assert r.success is True
        assert r.metadata["replacements"] == 2
        assert (ws / "dup.txt").read_text() == "x\nx\n"

    def test_single_edit_form_from_the_old_tool(self, ws):
        r = tool(Edit, ws).execute(path="README.md", old_text="# Project", new_text="# Renamed")
        assert r.success is True
        assert (ws / "README.md").read_text() == "# Renamed\n"

    def test_missing_file_reports_it(self, ws):
        r = tool(Edit, ws).execute(path="nope.txt", edits=[{"old_text": "a", "new_text": "b"}])
        assert r.success is False
        assert "not found" in r.error

    def test_edits_sent_as_a_json_string_are_taken(self, ws):
        """claude-haiku-4-5 JSON-encodes the array into a string in most calls
        (11 of 12 in one live run, each refused with 'must be a non-empty
        array', each a lost iteration). The intent is unambiguous."""
        import json

        edits = [{"old_text": "import os", "new_text": "import sys"}]
        r = tool(Edit, ws).execute(path="src/app.py", edits=json.dumps(edits))
        assert r.success is True, r.error
        assert "import sys" in (ws / "src" / "app.py").read_text()

    def test_a_string_that_is_not_json_is_refused_with_the_shape(self, ws):
        r = tool(Edit, ws).execute(path="src/app.py", edits="replace import os with import sys")
        assert r.success is False
        assert "array of {old_text, new_text}" in r.error


class TestGrep:
    def test_structured_output_and_skips_vendored_dirs(self, ws):
        r = tool(Grep, ws).execute(pattern="print")
        assert r.success is True
        assert "src/app.py:5: " in r.result
        assert "node_modules" not in r.result, "vendored directories are skipped"

    def test_bounded_with_a_tail_saying_what_was_omitted(self, ws):
        (ws / "many.txt").write_text("\n".join("match me" for _ in range(500)) + "\n")
        r = tool(Grep, ws).execute(pattern="match me")
        assert r.metadata["omitted"] > 0
        assert "matches shown" in r.result

    def test_no_match_is_success_not_failure(self, ws):
        r = tool(Grep, ws).execute(pattern="zzz-not-here")
        assert r.success is True
        assert r.metadata["matches"] == 0

    def test_invalid_regex_is_reported(self, ws):
        r = tool(Grep, ws).execute(pattern="(unclosed")
        assert r.success is False
        assert "Invalid regular expression" in r.error

    def test_glob_narrows_the_search(self, ws):
        assert tool(Grep, ws).execute(pattern="Project", glob="**/*.py").metadata["matches"] == 0
        assert tool(Grep, ws).execute(pattern="Project", glob="**/*.md").metadata["matches"] == 1


class TestIgnoreRules:
    """Grep and Glob skip what the repo already declared uninteresting.

    A search tool that walks `build/` or `fixtures/huge/` spends the agent's
    context on files the humans decided not to look at. The baseline list is kept
    on top of .gitignore because a workspace is not always a git repo, and
    `.venv` is never worth searching even when untracked.
    """

    @pytest.fixture
    def ignored_ws(self, ws: Path) -> Path:
        (ws / ".gitignore").write_text("generated/\n*.snap\nsecret.txt\n")
        (ws / "generated").mkdir()
        (ws / "generated" / "api.py").write_text("TOKEN = 'in generated dir'\n")
        (ws / "ui.snap").write_text("TOKEN = 'in snapshot'\n")
        (ws / "secret.txt").write_text("TOKEN = 'in secret'\n")
        (ws / "kept.py").write_text("TOKEN = 'in tracked file'\n")
        return ws

    def test_grep_skips_gitignored_files(self, ignored_ws):
        r = tool(Grep, ignored_ws).execute(pattern="TOKEN")
        assert "kept.py" in r.result
        for skipped in ("generated/api.py", "ui.snap", "secret.txt"):
            assert skipped not in r.result, f"{skipped} is gitignored"
        assert r.metadata["matches"] == 1

    def test_glob_skips_gitignored_files(self, ignored_ws):
        r = tool(Glob, ignored_ws).execute(pattern="**/*.py")
        assert "kept.py" in r.result
        assert "generated/api.py" not in r.result

    def test_include_ignored_opts_back_in(self, ignored_ws):
        r = tool(Grep, ignored_ws).execute(pattern="TOKEN", include_ignored=True)
        assert r.metadata["matches"] == 4
        g = tool(Glob, ignored_ws).execute(pattern="**/*.py", include_ignored=True)
        assert "generated/api.py" in g.result

    def test_baseline_dirs_skipped_even_without_gitignore(self, ws):
        """node_modules is never interesting, tracked or not."""
        assert not (ws / ".gitignore").exists()
        r = tool(Grep, ws).execute(pattern="vendored")
        assert r.metadata["matches"] == 0


class TestLimits:
    def test_grep_limit_raises_the_cap(self, ws):
        (ws / "many.txt").write_text("\n".join("match me" for _ in range(500)) + "\n")
        default = tool(Grep, ws).execute(pattern="match me")
        raised = tool(Grep, ws).execute(pattern="match me", limit=400)
        assert default.metadata["matches"] == 200
        assert raised.metadata["matches"] == 400
        assert "raise limit" in raised.result

    def test_glob_limit_raises_the_cap(self, ws):
        for i in range(300):
            (ws / f"f{i}.log").write_text("x")
        assert tool(Glob, ws).execute(pattern="*.log").metadata["shown"] == 200
        assert tool(Glob, ws).execute(pattern="*.log", limit=250).metadata["shown"] == 250

    def test_grep_literal_escapes_regex_metacharacters(self, ws):
        (ws / "code.py").write_text("value = calc(a[0])\n")
        assert tool(Grep, ws).execute(pattern="calc(a[0])").metadata["matches"] == 0
        assert tool(Grep, ws).execute(pattern="calc(a[0])", literal=True).metadata["matches"] == 1


class TestGlob:
    def test_finds_by_pattern_newest_first(self, ws):
        r = tool(Glob, ws).execute(pattern="**/*.py")
        assert r.success is True
        assert "src/app.py" in r.result
        assert "node_modules/junk.py" not in r.result

    def test_absolute_pattern_is_refused_with_a_hint(self, ws):
        r = tool(Glob, ws).execute(pattern="/etc/*")
        assert r.success is False
        assert "must be relative" in r.error

    def test_no_match_is_success(self, ws):
        r = tool(Glob, ws).execute(pattern="**/*.rs")
        assert r.success is True
        assert r.metadata["count"] == 0


def test_registry_exposes_the_new_names_and_not_the_old():
    from temper_ai.tools import TOOL_CLASSES

    assert {"Read", "Write", "Edit", "Grep", "Glob"} <= set(TOOL_CLASSES)
    assert not {"FileWriter", "FileEdit", "FileAppend"} & set(TOOL_CLASSES)
