"""The Team page's settings, project folders and approved branch (M3 E5, A1, A4, E10; M4 item 0).

No model, no box, no database: the team settings files, the two levels of folder check (lexical
everywhere, real only where the folder is visible) and the ``team/<trial_id>`` branch, made by a
fake host helper over its socket or in this process.
"""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
import threading
from pathlib import Path

import pytest

from temper_ai.pi_agent import team_branch, team_config
from temper_ai.pi_agent.team_folders import (
    DIRTY,
    NOT_GIT,
    NOT_VISIBLE_NOTE,
    folder_check,
    lexical_problems,
    roots_of,
)
from tests.test_runner.pi_team.leader_support import git, project

TRIAL = "0123456789ab"


# --- the settings files ------------------------------------------------------------------------


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_the_tracked_settings_list_no_project_folder_and_the_owner_dashboard_key():
    """The repo's own configs/team/team.yaml: no folder until the owner lists one at switch-on."""
    got = team_config.load_team_config()
    tracked, local = team_config.settings_paths()
    assert tracked.is_file() and tracked.parts[-3:] == ("configs", "team", "team.yaml")
    assert local.parts[-4:] == ("configs", "team", "local", "team.yaml")
    if not local.is_file():  # (an install's own local file may list its folders)
        assert got.project_roots == ()
    assert got.owner_callers == ("owner-dashboard",)


def test_the_local_file_replaces_a_key_of_the_tracked_one(tmp_path):
    _write(tmp_path / "team" / "team.yaml",
           "project_roots: [/srv/a]\nowner_callers: [owner-dashboard]\n")
    _write(tmp_path / "team" / "local" / "team.yaml", "project_roots: [/srv/b, /srv/c/*]\n")
    got = team_config.load_team_config(tmp_path)
    assert got.project_roots == ("/srv/b", "/srv/c/*")
    assert got.owner_callers == ("owner-dashboard",)
    assert got.problems == ()


@pytest.mark.parametrize(("entry", "why"), [
    ("~/projects", "must be an absolute path (inside the containers ~ is /app)"),
    ("relative/path", "must be an absolute path (inside the containers ~ is /app)"),
    ("/srv/../etc", "must be a plain absolute path: no '..', '.', doubled or trailing '/', "
                    "and '*' only as a final '/*'"),
    ("/srv//a", "must be a plain absolute path: no '..', '.', doubled or trailing '/', "
                "and '*' only as a final '/*'"),
    ("/srv/*/a", "must be a plain absolute path: no '..', '.', doubled or trailing '/', "
                 "and '*' only as a final '/*'"),
    ("/", "can't be / itself"),
    ("", "must be a folder path"),
])
def test_a_bad_root_is_dropped_and_named_never_widening_what_a_team_may_touch(tmp_path, entry,
                                                                              why):
    local = tmp_path / "team" / "local" / "team.yaml"
    _write(local, f"project_roots: [/srv/ok, {entry!r}]\n")
    got = team_config.load_team_config(tmp_path)
    assert got.project_roots == ("/srv/ok",)
    assert got.problems == (f"{local}: project_roots[1] {why}",)


def test_a_broken_settings_file_lists_no_folder(tmp_path):
    local = tmp_path / "team" / "local" / "team.yaml"
    _write(local, "project_roots: [unclosed\n")
    got = team_config.load_team_config(tmp_path)
    assert got.project_roots == ()
    assert len(got.problems) == 1
    assert got.problems[0].startswith(f"{local}: can't be read: ")


def test_trial_names_and_ids():
    assert team_config.is_trial_name(f"team-trial-{TRIAL}")
    assert team_config.is_trial_name(f"team-trial-{TRIAL}-design")
    assert not team_config.is_trial_name("team_wf")
    assert team_config.trial_id_of(f"team-trial-{TRIAL}") == TRIAL
    assert team_config.trial_id_of("team-trial-NOT-AN-ID") is None
    assert team_config.trial_id_of("team_wf") is None


# --- lexical folder checks (everywhere, no file access) ------------------------------------------


@pytest.mark.parametrize(("path", "text"), [
    ("projects/app", "project: give the folder's full path (it starts with /)"),
    ("/srv/p/a b", "project: the folder's path can't have spaces or control characters"),
    ("/srv/p/../q", "project: the path can't go up a folder ('..')"),
    ("/srv/q/app", "project: /srv/q/app is outside the allowed project folders (/srv/p/*, /srv/x)"),
    ("/srv/p/a/b", "project: /srv/p/a/b is outside the allowed project folders "
                   "(/srv/p/*, /srv/x)"),
    ("/srv/x/y", "project: /srv/x/y is outside the allowed project folders (/srv/p/*, /srv/x)"),
])
def test_the_lexical_check_refuses_by_the_text_alone(path, text):
    assert lexical_problems(path, roots_of(["/srv/p/*", "/srv/x"])) == [text]


def test_no_listed_root_says_none_are_set():
    assert lexical_problems("/srv/p/app", []) == [
        "project: /srv/p/app is outside the allowed project folders (none are set)"]


def test_the_lexical_check_passes_a_folder_inside_a_root_by_its_text():
    roots = roots_of(["/srv/p/*", "/srv/x"])
    assert lexical_problems("/srv/p/app", roots) == []
    assert lexical_problems("/srv/x", roots) == []


# --- where the folder isn't visible (the server in production) -----------------------------------


def test_a_folder_the_server_cannot_see_gets_the_note_not_a_refusal():
    """M4 item 0: nothing under the roots is mounted into the server, so team_check and trial
    start check the text and leave the real checks to where the team's node starts."""
    roots = roots_of(["/nowhere-on-this-machine/projects/*"])
    problems, notes = folder_check("/nowhere-on-this-machine/projects/app", roots,
                                   authoritative=False)
    assert (problems, notes) == ([], [NOT_VISIBLE_NOTE])
    assert NOT_VISIBLE_NOTE == "folder checks run when the Pi lane starts the team"


def test_where_the_node_starts_a_folder_it_cannot_see_is_a_plain_problem():
    roots = roots_of(["/nowhere-on-this-machine/projects/*"])
    problems, notes = folder_check("/nowhere-on-this-machine/projects/app", roots,
                                   authoritative=True)
    assert problems == ["project: /nowhere-on-this-machine/projects/app isn't reachable inside "
                        "Temper"]
    assert notes == []


def test_a_lexical_refusal_holds_even_where_the_folder_is_not_visible():
    problems, notes = folder_check("/elsewhere/app", roots_of(["/nowhere/projects/*"]),
                                   authoritative=False)
    assert problems == ["project: /elsewhere/app is outside the allowed project folders "
                        "(/nowhere/projects/*)"]
    assert notes == []


# --- where the folder is visible: the real checks ------------------------------------------------


@pytest.fixture
def projects(tmp_path):
    root = tmp_path / "projects"
    project(root / "app")
    return root


@pytest.mark.parametrize("authoritative", [False, True])
def test_a_clean_git_project_inside_a_root_passes(projects, authoritative):
    roots = roots_of([f"{projects}/*"])
    assert folder_check(str(projects / "app"), roots, authoritative=authoritative) == ([], [])


@pytest.mark.parametrize("authoritative", [False, True])
def test_a_link_leading_outside_the_roots_is_refused(projects, tmp_path, authoritative):
    outside = project(tmp_path / "outside")
    (projects / "sneaky").symlink_to(outside)
    roots = roots_of([f"{projects}/*"])
    problems, _ = folder_check(str(projects / "sneaky"), roots, authoritative=authoritative)
    assert problems == [f"project: {projects / 'sneaky'} leads outside the allowed project "
                        "folders through a link"]


def test_a_dirty_tree_is_refused(projects):
    (projects / "app" / "app.py").write_text("changed\n")
    problems, _ = folder_check(str(projects / "app"), roots_of([f"{projects}/*"]),
                               authoritative=True)
    assert problems == [f"project: {DIRTY}"]


def test_a_dirty_tree_no_longer_matters_once_the_team_works_on_its_copies(projects):
    (projects / "app" / "app.py").write_text("changed\n")
    problems, _ = folder_check(str(projects / "app"), roots_of([f"{projects}/*"]),
                               authoritative=True, fresh=False)
    assert problems == []


def test_a_folder_that_is_not_a_git_repository_is_refused(projects):
    (projects / "plain").mkdir()
    problems, _ = folder_check(str(projects / "plain"), roots_of([f"{projects}/*"]),
                               authoritative=True)
    assert problems == [f"project: {NOT_GIT}"]


def test_a_sub_folder_of_a_repository_is_not_its_top(tmp_path):
    (tmp_path / "repo" / "sub").mkdir(parents=True)
    repo = project(tmp_path / "repo", {"sub/a.txt": "a\n"})
    problems, _ = folder_check(str(repo / "sub"), roots_of([str(repo / "sub")]),
                               authoritative=True)
    assert problems == [f"project: {repo / 'sub'} is inside a git repository but is not its "
                        f"top folder ({repo})"]


def test_a_git_dir_outside_the_roots_is_refused(projects, tmp_path):
    """A worktree whose git folders live outside the roots: the team would read them."""
    elsewhere = project(tmp_path / "elsewhere")
    git(elsewhere, "worktree", "add", "-q", str(projects / "wt"), "-b", "wt")
    problems, _ = folder_check(str(projects / "wt"), roots_of([f"{projects}/*"]),
                               authoritative=True)
    assert len(problems) == 1
    assert problems[0].startswith("project: its git folder ")
    assert problems[0].endswith(" is outside the allowed project folders")


def test_a_path_outside_the_roots_is_refused_before_any_file_is_looked_at(projects, tmp_path):
    other = project(tmp_path / "other")
    problems, _ = folder_check(str(other), roots_of([f"{projects}/*"]), authoritative=True)
    assert problems == [f"project: {other} is outside the allowed project folders "
                        f"({projects}/*)"]


# --- the approved branch: a fake host helper ------------------------------------------------------


class FakeHelper:
    """A Unix socket that reads one line and answers ``answer`` (None: closes without one;
    "hang": never answers)."""

    def __init__(self, answer: str | None):
        self.dir = tempfile.mkdtemp(prefix="q48h", dir="/tmp")  # short: socket paths are short
        self.path = os.path.join(self.dir, "helper.sock")
        self.answer = answer
        self.lines: list[str] = []
        self.release = threading.Event()
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(1)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        conn, _ = self.server.accept()
        with conn:
            data = b""
            while b"\n" not in data:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                data += chunk
            self.lines.append(data.decode())
            if self.answer == "hang":
                self.release.wait(10)
                return
            if self.answer is not None:
                conn.sendall(f"{self.answer}\n".encode())

    def close(self) -> None:
        self.release.set()
        self.server.close()
        shutil.rmtree(self.dir, ignore_errors=True)


@pytest.fixture
def helper():
    made: list[FakeHelper] = []

    def make(answer):
        h = FakeHelper(answer)
        made.append(h)
        return h

    yield make
    for h in made:
        h.close()


def _ask(path: str) -> dict:
    return team_branch.make_branch(source="/srv/p/app", leader_git_dir="/runs/x/leader/.git",
                                   commit="a" * 40, trial_id=TRIAL, roots=[],
                                   helper_socket=path)


@pytest.mark.parametrize(("answer", "want"), [
    ("made", {"name": f"team/{TRIAL}", "made": True, "why": None}),
    ("exists", {"name": f"team/{TRIAL}", "made": False, "why": "exists"}),
    ("denied outside the project roots",
     {"name": f"team/{TRIAL}", "made": False, "why": "denied: outside the project roots"}),
    ("denied", {"name": f"team/{TRIAL}", "made": False, "why": "denied"}),
    (None, {"name": f"team/{TRIAL}", "made": False, "why": "the host helper gave no answer"}),
    ("what?", {"name": f"team/{TRIAL}", "made": False,
               "why": "the host helper answered 'what?'"}),
])
def test_the_helper_s_branch_verb_and_its_answers(helper, answer, want):
    """M4 item 0d: one request line per connection, ``branch <repo> <leader git dir> <commit>
    <trial_id>``; the done record's fields are the same whatever the helper answers."""
    h = helper(answer)
    assert _ask(h.path) == want
    assert h.lines == [f"branch /srv/p/app /runs/x/leader/.git {'a' * 40} {TRIAL}\n"]


def test_a_helper_that_never_answers_leaves_done_as_done(helper, monkeypatch):
    monkeypatch.setattr(team_branch, "HELPER_TIMEOUT", 0.3)
    h = helper("hang")
    assert _ask(h.path) == {"name": f"team/{TRIAL}", "made": False,
                            "why": "the host helper gave no answer"}


def test_a_missing_helper_socket_leaves_done_as_done(tmp_path):
    path = str(tmp_path / "no.sock")
    assert _ask(path) == {"name": f"team/{TRIAL}", "made": False,
                          "why": f"the host helper isn't running ({path})"}


# --- the approved branch: in this process ---------------------------------------------------------


@pytest.fixture
def source_and_leader(tmp_path):
    root = tmp_path / "projects"
    source = project(root / "app")
    leader = tmp_path / "copies" / "leader"
    git(tmp_path, "clone", "-q", str(source), str(leader))
    (leader / "app.py").write_text("print('approved')\n")
    git(leader, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "approved")
    return root, source, leader, git(leader, "rev-parse", "HEAD")


def _status(repo: Path) -> tuple[str, str, str]:
    """The working tree, the index and HEAD: the branch never touches them."""
    return (git(repo, "status", "--porcelain"), git(repo, "ls-files", "-s"),
            git(repo, "rev-parse", "--symbolic-full-name", "HEAD"))


def _in_process(root, source, leader, commit) -> dict:
    return team_branch.make_branch(source=str(source), leader_git_dir=str(leader / ".git"),
                                   commit=commit, trial_id=TRIAL, roots=roots_of([f"{root}/*"]))


def test_in_process_the_branch_is_made_at_the_commit_and_nothing_else_moves(source_and_leader):
    root, source, leader, commit = source_and_leader
    before = _status(source)
    assert _in_process(root, source, leader, commit) == {
        "name": f"team/{TRIAL}", "made": True, "why": None}
    assert git(source, "rev-parse", f"refs/heads/team/{TRIAL}") == commit
    assert _status(source) == before
    assert git(source, "for-each-ref", "refs/temper") == ""  # the temporary ref is gone
    assert git(source, "remote") == ""  # nothing pushed anywhere, no remote added


def test_in_process_a_branch_already_at_the_commit_counts_as_made(source_and_leader):
    root, source, leader, commit = source_and_leader
    assert _in_process(root, source, leader, commit)["made"] is True
    assert _in_process(root, source, leader, commit) == {
        "name": f"team/{TRIAL}", "made": True, "why": None}


def test_in_process_a_branch_elsewhere_is_never_moved(source_and_leader):
    root, source, leader, commit = source_and_leader
    git(source, "branch", f"team/{TRIAL}")
    start = git(source, "rev-parse", "HEAD")
    assert _in_process(root, source, leader, commit) == {
        "name": f"team/{TRIAL}", "made": False, "why": "exists"}
    assert git(source, "rev-parse", f"refs/heads/team/{TRIAL}") == start


def test_in_process_a_source_outside_the_roots_is_left_alone(source_and_leader, tmp_path):
    _root, source, leader, commit = source_and_leader
    got = team_branch.make_branch(source=str(source), leader_git_dir=str(leader / ".git"),
                                  commit=commit, trial_id=TRIAL,
                                  roots=roots_of([str(tmp_path / "elsewhere")]))
    assert got["made"] is False
    assert got["why"] == (f"project: {source} is outside the allowed project folders "
                          f"({tmp_path / 'elsewhere'})")
    assert git(source, "branch", "--list", f"team/{TRIAL}") == ""
