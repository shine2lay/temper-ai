"""Stand-ins for the leader loop's tests (#38): a team opened as the team node opens it, the
review tools as a member's box calls them, the owner, and git projects. No model, no network:
every member is pi_team/support.py's scripted Pi.

The owner stands in for ``ask_owner`` underneath the real bridge
(:func:`temper_ai.pi_agent.owner_waits.ask_owner_for_wait`), so every ask still goes through the
bridge's own checks: a wait is asked only once its ``pi_waits`` row is written, under that
row's id. Each ask is logged with the row as it was at that moment.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from temper_ai.pi_agent import owner_waits
from temper_ai.pi_agent.ledger import Ledger, acts, reviews, waits
from temper_ai.pi_agent.team_leader import LeaderTeam, ProjectCopies
from temper_ai.stage.exceptions import RunParked
from temper_ai.stage.step_waits import OwnerAnswer
from tests.test_runner.pi_team import support as ts

GOAL = "This tiny project has no README. Write a short one."
#: A leader loop pausing after 2 keep-goings in a row.
LEADER_SETTINGS = {"mode": {"type": "leader", "leader": "lead"},
                   "communication": {"type": "all"}, "pause_after_rounds": 2}
GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


# --- a project --------------------------------------------------------------------------------


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV},
                         capture_output=True, text=True, check=True, timeout=60)
    return out.stdout.strip()


def allow_projects(monkeypatch, settings_root: Path, *entries: str) -> Path:
    """The team settings this test's Temper reads (M3 E5): ``project_roots`` = ``entries``, as
    the owner's git-ignored local file would list them at switch-on. Only the default configs
    root is replaced; an explicit ``config_dir`` still reads its own files. Returns the file."""
    import yaml

    from temper_ai.pi_agent import team_config

    local = settings_root / team_config.TEAM_DIR / "local" / "team.yaml"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(yaml.safe_dump({"project_roots": list(entries)}), encoding="utf-8")
    real = team_config.settings_paths

    def settings_paths(config_dir: str | Path | None = None) -> tuple[Path, Path]:
        return real(config_dir if config_dir else settings_root)

    monkeypatch.setattr(team_config, "settings_paths", settings_paths)
    return local


def project(root: Path, files: dict[str, str] | None = None) -> Path:
    """A tiny git project with one commit (the run's workspace)."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    for name, text in (files or {"app.py": "print('hello')\n"}).items():
        (root / name).write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "start")
    return root


# --- the team, opened as the team node opens it ------------------------------------------------


def make_leader(led: Ledger, box: Any, *, run_id: str, source: Path | None = None,
                settings: dict | None = None, names: tuple[str, ...] = ts.NAMES,
                attempt: str = "attempt-1", recorder: ts.Recorder | None = None,
                goal: str = GOAL, members: list | None = None, cancel_event: Any = None,
                host: str = ts.HOST) -> LeaderTeam:
    s = settings or LEADER_SETTINGS
    team = LeaderTeam(led, box, run_id=run_id, host_path=host,
                      members=members or [ts.member(n) for n in names], team_settings=s,
                      recorder=recorder or ts.Recorder(), attempt_id=attempt,
                      workflow="team_test", cancel_event=cancel_event,
                      leader=s["mode"]["leader"], pause_after=s["pause_after_rounds"],
                      goal=goal, project=None)  # type: ignore[arg-type]
    team.project = ProjectCopies(team.root, source)
    return team


def open_leader(led: Ledger, box: Any, **kw: Any) -> LeaderTeam:
    """Open the team, make each member's project copy and give the leader the brief, exactly
    as ``run_team_node`` does before it drives the team."""
    team = make_leader(led, box, **kw)
    refusal = team.open({"goal": team.goal})
    assert refusal is None, refusal
    for name, row in team._member_rows().items():
        team.project.ensure(name, team._pdir(row))
    team.post(team.leader, team.goal, sender="temper", sender_kind="temper", kind="goal",
              dedupe_key=f"{team.run_id}:{team.host_path}:brief")
    return team


def workspace(team: LeaderTeam, name: str) -> Path:
    return team._pdir(team._member_rows()[name]) / "workspace"


def copy_git(team: LeaderTeam, name: str, *args: str) -> str:
    """git in a member's copy: its own git dir, kept outside the copy the box mounts."""
    return git(workspace(team, name), f"--git-dir={team.project.git_dir(name)}",
               f"--work-tree={workspace(team, name)}", *args)


def head(team: LeaderTeam, name: str) -> str:
    return copy_git(team, name, "rev-parse", "HEAD")


# --- what a member does in a turn ---------------------------------------------------------------


def write(name: str, text: str) -> dict:
    """The member edits a file in its own project copy."""
    def call(box: Any, _message: str) -> None:
        (Path(box.pdir) / "workspace" / name).write_text(text)
    return {"call": call}


def op(name: str, **fields: Any) -> dict:
    """A review-tool call as the member's box sends it on the team socket. A field given as a
    callable is computed from the turn's prompt."""
    def build(prompt: str) -> dict:
        out = {"op": name}
        for key, value in fields.items():
            out[key] = value(prompt) if callable(value) else value
        return out
    return {"send": build}


def request_review(note: str | None = None, **extra: Any) -> dict:
    return op("request_review", **({"note": note} if note else {}), **extra)


def latest_review(led: Ledger, run_id: str | None, host: str = ts.HOST) -> Any:
    """The newest review's id, read when the member's turn calls the tool. With no ``run_id``
    (a run started through the API, whose id is not known yet when the scripts are written),
    the team of the turn being played."""
    def find(_prompt: str) -> str:
        run, team = run_id, host
        if run is None:
            binding = ts.CURRENT["binding"]
            run, team = binding.run_id, binding.host_path
        with led.engine.connect() as conn:
            row = conn.execute(sa.select(reviews.c.review_id).where(
                reviews.c.run_id == run, reviews.c.host_path == team,
            ).order_by(reviews.c.round.desc())).first()
        assert row is not None, "no review yet"
        return row[0]
    return find


def give_view(led: Ledger, run_id: str | None, verdict: str = "satisfied",
              note: str = "looks right", **extra: Any) -> dict:
    return op("give_view", review_id=latest_review(led, run_id), verdict=verdict, note=note,
              **extra)


def decide(led: Ledger, run_id: str | None, decision: str = "done",
           summary: str = "The README is done.", **extra: Any) -> dict:
    return op("decide", review_id=latest_review(led, run_id), decision=decision,
              summary=summary, **extra)


def replies(member: str) -> list[dict]:
    """Temper's answers to the member's tool calls, in order."""
    return [s["reply"] for s in ts.SENDS if s["member"] == member]


# --- reading the tables -------------------------------------------------------------------------


def table(led: Ledger, tbl: sa.Table, run_id: str, host: str = ts.HOST) -> list[dict]:
    order = {"pi_team_acts": acts.c.seq, "pi_reviews": reviews.c.round,
             "pi_waits": waits.c.opened_at}.get(tbl.name)
    with led.engine.connect() as conn:
        q = sa.select(tbl).where(tbl.c.run_id == run_id, tbl.c.host_path == host)
        if order is not None:
            q = q.order_by(order)
        return [dict(r) for r in conn.execute(q).mappings().all()]


# --- the owner ----------------------------------------------------------------------------------


class Owner:
    """Stands in for ``ask_owner`` beneath the real bridge. ``answers`` are given in order; with
    none left the run parks (``RunParked``, as in a Pi workflow). Every ask is logged with its
    ``pi_waits`` row as it was when the owner was asked."""

    def __init__(self, led: Ledger, *answers: str) -> None:
        self.led = led
        self.answers = list(answers)
        self.asked: list[dict] = []

    def __call__(self, context: Any, wait_id: str, *, question: str, header: str = "",
                 detail: str = "", options: tuple = ()) -> OwnerAnswer:
        row = owner_waits.wait_row(self.led, wait_id)
        self.asked.append({"wait_id": wait_id, "row": row, "question": question,
                           "header": header, "options": tuple(options)})
        if not self.answers:
            raise RunParked(event_id=f"ev-{uuid.uuid4().hex[:8]}", node="team",
                            path=getattr(context, "step_path", "") or "", round=1,
                            checkpoint_id="cp", wait_id=wait_id)
        text = self.answers.pop(0)
        return OwnerAnswer(wait_id=wait_id, event_id=f"ev-{wait_id[:8]}", round=1,
                           response={"response": text, "text": text})

    def install(self, monkeypatch: Any) -> Owner:
        monkeypatch.setattr(owner_waits, "ask_owner", self)
        return self


class Context:
    """The bits of a step's context the leader loop reads."""

    def __init__(self, step_path: str = ts.HOST, cancel_event: Any = None) -> None:
        self.step_path = step_path
        self.cancel_event = cancel_event
