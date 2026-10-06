"""`temper check` on the Team page's settings and trial names (M3 E5, E7).

The server skips a config file that uses a team trial's name (the Team page writes those and
they stay frozen), and reads project_roots from configs/team/; the check says both out loud.
"""

from __future__ import annotations

from pathlib import Path

from temper_ai.cli.check import check, check_team_settings


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_a_clean_tree_reads_its_team_settings_and_has_no_problem(tmp_path):
    _write(tmp_path / "team" / "team.yaml", "project_roots: []\n")
    _write(tmp_path / "team" / "local" / "team.yaml", "project_roots: [/srv/projects]\n")
    files, problems = check_team_settings(tmp_path)
    assert problems == []
    assert files == [str(tmp_path / "team" / "team.yaml"),
                     str(tmp_path / "team" / "local" / "team.yaml")]


def test_a_config_file_with_a_trials_name_is_reported_word_for_word(tmp_path):
    trial = _write(tmp_path / "workflows" / "t.yaml",
                   "workflow:\n  name: team-trial-0123456789ab\n  nodes: []\n")
    _, problems = check_team_settings(tmp_path)
    assert problems == [f"{trial}: 'team-trial-0123456789ab' is a team trial's name "
                        "(team-trial-...), which only the Team page writes; the server skips "
                        "this file"]


def test_a_bad_settings_file_is_named(tmp_path):
    local = _write(tmp_path / "team" / "local" / "team.yaml",
                   "project_roots: [relative/path]\nextra: 1\n")
    _, problems = check_team_settings(tmp_path)
    assert (f"{local}: unknown key 'extra' (known: project_roots, owner_callers, "
            "account_slots, account_room_file)") in problems
    assert any(p.startswith(f"{local}: project_roots[0] must be an absolute path")
               for p in problems)


def test_the_command_fails_on_a_trial_named_file_and_says_where_to_read(tmp_path, capsys):
    _write(tmp_path / "agents" / "t.yaml",
           "agent:\n  name: team-trial-0123456789ab-design\n  type: llm\n  provider: anthropic\n")
    assert check(tmp_path) == 1
    out = capsys.readouterr().out
    assert "problem(s) for the Team page" in out and "docs/pi-team-api.md" in out


def test_the_command_says_the_team_settings_read_cleanly(tmp_path, capsys):
    _write(tmp_path / "team" / "team.yaml", "project_roots: []\n")
    check(tmp_path)
    out = capsys.readouterr().out
    assert f"Team page settings read: {tmp_path / 'team' / 'team.yaml'}" in out
    assert "the Team page's settings read cleanly and no config file uses a trial's name" in out
