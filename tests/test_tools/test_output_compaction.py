"""Bash output compaction.

A Bash result is not read once. With no prompt caching on the anthropic
provider, every tool result stays in the transcript and is re-sent on every
later iteration, so a 7,000-token `git log` costs that much per turn for the
rest of the node.

The tests that matter here are the ones about what compaction must NOT do:
never drop a failure, never touch a diff, never remove anything silently.
"""

import pytest

from temper_ai.tools._output_compaction import (
    collapse_progress,
    compact,
    condense_git_log,
    looks_like_diff,
    strip_ansi,
    window,
)
from temper_ai.tools.bash import Bash

GIT_LOG = """commit 3863cc6aa1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6
Author: shine <s@example.com>
Date:   Wed Sep 18 07:12:00 2026 -0700

    Replace the file tools with pi's behaviours

    A very long body that continues for several lines and would be
    re-sent on every subsequent iteration of the run.

commit ab71d4300000000000000000000000000000beef
Author: shine <s@example.com>
Date:   Wed Sep 18 06:40:00 2026 -0700

    fix(llm): let a tool result be a whole file

    More body text here.
"""


class TestSafety:
    """What compaction must never do."""

    def test_a_diff_is_left_alone(self):
        diff = "diff --git a/x.py b/x.py\nindex 111..222 100644\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n"
        out, notes = compact("git diff", diff)
        assert out == diff
        assert notes == []

    def test_diff_is_detected_even_after_a_command_prefix(self):
        assert looks_like_diff("diff --git a/x b/x\n@@ -1 +1 @@\n")
        assert not looks_like_diff("just some output\nwith lines\n")

    def test_failing_test_lines_are_never_collapsed(self):
        """A file line containing F or E names something the agent must see."""
        lines = [f"tests/test_{i}.py ......   [ {i}%]" for i in range(10)]
        lines[4] = "tests/test_4.py ..F...   [ 4%]"
        out, _ = compact("pytest", "\n".join(lines))
        assert "tests/test_4.py ..F..." in out

    def test_short_runs_are_kept_verbatim_not_dropped(self):
        """Under the run threshold, keep the bytes: silent deletion is worse than the tokens."""
        text = "header\n1 2 3\n4 5 6\nfooter"
        out, removed = collapse_progress(text)
        assert out == text
        assert removed == 0

    def test_every_reduction_is_announced(self):
        text = "start\n" + "\n".join("." * 70 + f" [ {i}%]" for i in range(30)) + "\nend"
        out, notes = compact("pytest", text)
        assert notes, "a reduction must always leave a note"
        assert "progress lines" in out


class TestStages:
    def test_ansi_is_stripped(self):
        assert strip_ansi("\x1b[31merror\x1b[0m") == "error"
        out, notes = compact("npm run build", "\x1b[32mok\x1b[0m\n")
        assert "\x1b" not in out
        assert any("ANSI" in n for n in notes)

    def test_long_progress_runs_collapse_to_a_count(self):
        text = "start\n" + "\n".join("." * 70 + f" [ {i}%]" for i in range(20)) + "\nend"
        out, removed = collapse_progress(text)
        assert removed == 20
        assert "[20 progress lines]" in out
        assert out.startswith("start") and out.endswith("end")

    def test_download_noise_collapses(self):
        text = "\n".join(f"Downloading package-{i}.whl" for i in range(8))
        _, removed = collapse_progress(text)
        assert removed == 8

    def test_git_log_condenses_to_one_line_per_commit(self):
        out, commits = condense_git_log(GIT_LOG)
        assert commits == 2
        assert "3863cc6aa" in out and "Replace the file tools" in out
        assert "A very long body" not in out
        assert len(out) < len(GIT_LOG) / 2

    def test_git_log_with_a_patch_is_not_condensed(self):
        """-p means the agent asked for the diff; do not take it away."""
        out, notes = compact("git log -p -2", GIT_LOG)
        assert "A very long body" in out
        assert not any("commits condensed" in n for n in notes)

    def test_git_log_detected_through_a_cd_prefix(self):
        out, notes = compact("cd /repo && git log -20", GIT_LOG)
        assert any("commits condensed" in n for n in notes)


class TestWindow:
    def test_keeps_head_and_tail_with_a_marker(self):
        text = "\n".join(f"line {i}" for i in range(5000))
        out, omitted = window(text, max_chars=4000)
        assert omitted > 0
        assert "line 0" in out, "head kept"
        assert "line 4999" in out, "tail kept — failures and summaries live at the end"
        assert "omitted from the middle" in out
        assert "use Read with offset" in out, "tells the agent what to do instead"

    def test_few_very_long_lines_cut_from_the_middle(self):
        text = "x" * 100_000
        out, _ = window(text, max_chars=10_000)
        assert len(out) < 11_000
        assert "characters omitted from the middle" in out

    def test_under_budget_is_untouched(self):
        text = "short output"
        assert window(text, 40_000) == (text, 0)


class TestBashIntegration:
    def test_compaction_is_on_by_default_and_reports_itself(self, tmp_path):
        script = "; ".join(f"echo 'Downloading pkg-{i}'" for i in range(10))
        r = Bash(config={"workspace_root": str(tmp_path)}).execute(command=script, _skip_allowlist=True)
        assert r.success is True
        assert r.metadata["compacted"] is True
        assert "[output compacted:" in r.result

    def test_can_be_switched_off(self, tmp_path):
        script = "; ".join(f"echo 'Downloading pkg-{i}'" for i in range(10))
        r = Bash(config={"workspace_root": str(tmp_path), "compact_output": False}).execute(
            command=script, _skip_allowlist=True
        )
        assert r.metadata.get("compacted") is not True
        assert "Downloading pkg-9" in r.result

    def test_stderr_survives_a_huge_stdout(self, tmp_path):
        """Streams are compacted separately so a noisy stdout cannot bury the error."""
        cmd = "python3 -c \"import sys; [print('x'*200) for _ in range(3000)]; print('THE REAL ERROR', file=sys.stderr)\""
        r = Bash(config={"workspace_root": str(tmp_path), "max_output_chars": 5_000}).execute(
            command=cmd, _skip_allowlist=True
        )
        assert "THE REAL ERROR" in r.result
        assert len(r.result) < 20_000

    def test_exit_code_and_error_are_unchanged(self, tmp_path):
        r = Bash(config={"workspace_root": str(tmp_path)}).execute(command="exit 3", _skip_allowlist=True)
        assert r.success is False
        assert r.metadata["exit_code"] == 3

    @pytest.mark.parametrize("cmd", ["echo hi", "printf 'a\\nb\\nc\\n'"])
    def test_small_output_passes_through_unchanged(self, tmp_path, cmd):
        r = Bash(config={"workspace_root": str(tmp_path)}).execute(command=cmd, _skip_allowlist=True)
        assert "[output compacted" not in r.result
