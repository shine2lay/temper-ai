"""The leader loop of a Pi team (task #38; switched off with the rest of the Pi agent).

A ``strategy: team`` stage runs as one node (:class:`~temper_ai.pi_agent.team_node.TeamNode`),
built on #37's team runtime (:class:`~temper_ai.pi_agent.team_runtime.Team` and the Pi ledger)
to Architecture's rules (R2 B7-B16, PARK P1/P2, the T4T5 bindings, M1/answer-1.md).

The leader gets the brief. The team works in review rounds:

1. The leader calls ``request_review``. Once its turn has finished, Temper commits the
   leader's project copy and moves every reviewer's copy to that commit, so everyone sees
   exactly that version, and sends each reviewer a review request.
2. Each reviewer calls ``give_view``: satisfied or changes, with a short note.
3. When every asked reviewer has given a view -- or the team has nothing left to do --
   Temper passes the views to the leader, one message per view, from its reviewer.
4. The leader calls ``decide``: done or keep_going. Done counts only if the leader's copy is
   still exactly the reviewed commit and no new work reached the leader after its deciding
   turn began; otherwise it is refused, with the reason, and counts as a keep-going (R2 B9).

Only Temper records done: the decision, the version (commit and file hashes), the round, each
reviewer's last view, the leader's summary, the number of rounds and the cost -- the node's
outputs. After done, stop or cancel the team takes no new work.

A review-tool call is recorded with the calling turn (``pi_team_acts``) and counts only once
that turn has finished -- completed, or accepted at a recovery wait. Temper carries it out
before the team's next turn, on every path (the loop, a resume after a park, a restart); a call of a turn
that failed, was retried or was cancelled never counts.

Every owner wait the team opens -- the pause after ``pause_after_rounds`` keep-goings in a row
(R2 B10), the stalled question, a recovery wait for a cut-off turn (B11), an owner question --
is one ``pi_waits`` row, written before it is asked through ``ask_owner`` under that row's own
id (:func:`~temper_ai.pi_agent.owner_waits.ask_owner_for_wait`). In a Pi workflow an unanswered
wait parks the run: no worker is held, and the answer carries the run on, through this node
again, from the tables. Nothing here catches ``RunParked``.

Each member works on its own git copy of the project -- the run's workspace, committed content
only -- in its own folder. The copies' git data stays outside every member's folder, so nothing a
member writes can change how Temper's git runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from temper_ai.pi_agent import team_versions, token_scan
from temper_ai.pi_agent.accounts import refusal_problem, run_account
from temper_ai.pi_agent.event_guard import guarded_context
from temper_ai.pi_agent.host import INVALID, _slug, ask_text, owner_reply
from temper_ai.pi_agent.inbox import render_batch
from temper_ai.pi_agent.ledger import (
    _LOCK,
    ACCOUNT_REFUSED,
    Binding,
    Ledger,
    LedgerLayoutError,
    TakeoverRefused,
    _fence,
    _new_id,
    _now,
    acts,
    messages,
    reviews,
    turns,
    waits,
)
from temper_ai.pi_agent.member_tree import member_entry
from temper_ai.pi_agent.owner_waits import WaitDecided, ask_owner_for_wait
from temper_ai.pi_agent.route import model as route_model
from temper_ai.pi_agent.route.router import IDENTITY_CLAIMS, Refusal, content_digest
from temper_ai.pi_agent.settings_wait import (
    GO_ON,
    SETTINGS,
    STOP,
    changed_names,
    same_change,
    settings_asked_again,
    settings_word,
    team_subject,
)
from temper_ai.pi_agent.team_folders import GIT, NOT_GIT, format_problem
from temper_ai.pi_agent.team_runtime import (
    Team,
    TeamChannel,
    TeamMember,
    member_tools,
    stop_ends_cancelled,
    stop_text,
    stop_words,
)
from temper_ai.runner.lanes import OUTSIDE_PI_LANE, in_pi_lane
from temper_ai.runner.pi_lane import leave_if_draining
from temper_ai.shared.types import ExecutionContext, NodeResult, Status
from temper_ai.stage.exceptions import CancellationError, ReplacedByLaterAttempt

logger = logging.getLogger(__name__)

REQUEST_REVIEW = "request_review"
GIVE_VIEW = "give_view"
DECIDE = "decide"
REVIEW_OPS = (REQUEST_REVIEW, GIVE_VIEW, DECIDE)
#: The leader's review tools and a reviewer's (Pi activates only the ones ``--tools`` names).
LEADER_TOOLS = (REQUEST_REVIEW, DECIDE)
REVIEWER_TOOLS = (GIVE_VIEW,)
OP_FIELDS = {REQUEST_REVIEW: ("note",), GIVE_VIEW: ("review_id", "verdict", "note"),
             DECIDE: ("review_id", "decision", "summary")}
VERDICTS = ("satisfied", "changes")
DECISIONS = ("done", "keep_going")
MAX_NOTE = 1000
MAX_SUMMARY = 4000
#: A review-tool call the team's state does not allow right now.
NOT_NOW = "not_now"
#: The policy a view message travels under: Temper hands it from reviewer to leader.
REVIEW_POLICY = "temper-review@1"
PAUSE_OPTIONS = ("continue", "guide", "stop")
STALLED_OPTIONS = ("nudge", "stop")
#: Keep-going decisions: a refused done counts as one (R2 B9).
KEEP_GOINGS = ("keep_going", "done_refused")
MAX_FILES = 500
GIT_TIMEOUT = 120

TOOLS_NOTE = ("Temper note: in this Temper run your tools are: {tools}. Notes, memory, questions "
              "to the owner and queue tools are not available in a Temper run: put any lessons "
              "and questions in your reply.")


def tools_note(tools: list[str]) -> str:
    """The fixed note in every member's framing: exactly the member's tools, and what a Temper
    run does not have (M2-roles: the role rules name tools a member's box doesn't get)."""
    return TOOLS_NOTE.format(tools=", ".join(sorted(tools)))


def framing(name: str, leader: str, roster: list[str], tools: list[str]) -> str:
    """Temper's own lines before a turn's messages: who the member is in the team, how a round
    works, and the tools note. Never anything a member wrote (R2 B5): the messages follow,
    framed by :func:`~temper_ai.pi_agent.inbox.render_batch`."""
    others = [m for m in roster if m != name]
    lines = [f"[Temper] You are {name}, a member of a team working through Temper: "
             + ", ".join(roster) + f". {leader} leads."]
    if name == leader:
        lines.append(
            "You lead. Do the work in your project copy (your working folder), then call "
            "request_review: when this turn has finished, Temper commits your copy and gives "
            + (", ".join(others) if others else "every other member")
            + " exactly that version to review. Their views reach you as messages; then call "
            "decide, naming the review: done (the reviewed version is the result) or keep_going. "
            "Done counts only if your copy is still exactly the reviewed version.")
    else:
        lines.append(
            f"You review {leader}'s work. When a review request reaches you, your project copy "
            "(your working folder) holds exactly the version under review: look at it, then "
            "call give_view naming the review: satisfied, or changes with a short note saying "
            "what to change.")
    lines.append("Use send_message to message another member; Temper delivers it at their next "
                 "turn.")
    lines.append(tools_note(tools))
    return "\n".join(lines)


def usage_of(outcome: Any) -> dict:
    """A turn's model usage, kept with the turn's worker receipt (no keys, no text)."""
    tokens = getattr(outcome, "tokens", None) or {}
    return {"cost_usd": float(tokens.get("cost_usd") or 0.0),
            "total_tokens": int(tokens.get("total_tokens") or 0),
            "llm_calls": int(getattr(outcome, "llm_calls", 0) or 0)}


def owner_words(answer: Any) -> tuple[str, str]:
    """(choice, words) of the owner's answer (M3 E17): a picked option is the choice and the
    typed text the words; with no pick, the typed text's first word is the choice and the rest
    the words (:func:`~temper_ai.pi_agent.host.owner_reply`)."""
    return owner_reply(getattr(answer, "response", None))


def answer_who(answer: Any) -> dict:
    """Who answered a wait, as the API guard recorded the caller on the answer (#45): the
    credential name (``by``; None when there was none) and where the answer came from
    (``source``, for display only; M3 E15, E21), with the answer's request id. Never the
    self-declared ``by`` of the approve body."""
    return {"by": getattr(answer, "caller", None), "source": getattr(answer, "caller_source", None),
            "request_id": getattr(answer, "request_id", None)}


def _one_line(text: str, limit: int = MAX_NOTE) -> str:
    return " ".join(str(text or "").split())[:limit]


def _slug_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:64] or "member"


# --- the project copies --------------------------------------------------------------------


class CopyError(Exception):
    """A project copy could not be made, committed or moved: the team fails red."""


class CopyFormatError(CopyError):
    """git can't read the workspace's repository format: named before any model call."""


class TeamFailure(Exception):
    """The team can't go on (a copy failed, another attempt holds the team): red."""


_GIT = GIT  # the hardened git command line, shared with the folder checks and the branch


class ProjectCopies:
    """Each member's own git copy of the project, in its folder's ``workspace`` -- the box's
    working folder, mounted only into that member's box (W3). Only committed content is copied:
    the run's workspace at its HEAD, never untracked or ignored files (W1); without a workspace
    every member starts from an empty commit. The copies have no remote and no hooks, and their
    git data lives under ``<team root>/git``, outside every member's folder."""

    def __init__(self, root: Path, source: str | None):
        self.root = Path(root)
        self.source = source
        self.record_path = self.root / "project.json"

    def git_dir(self, member: str) -> Path:
        return self.root / "git" / f"{_slug_name(member)}.git"

    @staticmethod
    def worktree(pdir: Path) -> Path:
        return Path(pdir) / "workspace"

    def checked_worktree(self, pdir: Path, *, make: bool = False) -> Path:
        """The member's working folder, checked without following links before git is given
        it (SW-51): the member may have replaced it, and git would follow a link there -- read
        /etc into a commit, or reset and clean another member's folder. Only a real folder is
        used; ``make`` creates a missing one."""
        wt = self.worktree(pdir)
        kind = member_entry(pdir, "workspace")
        if kind == "missing" and make:
            wt.mkdir(parents=True, exist_ok=True)
            kind = member_entry(pdir, "workspace")
        if kind != "dir":
            raise CopyError(f"the member's working folder {wt} is "
                            + ("a link" if kind == "link" else f"not a folder ({kind})")
                            + "; Temper does not follow links in a member's folder")
        return wt

    def _g(self, args: list[str], *, git_dir: Path | None = None,
           work_tree: Path | None = None, cwd: Path | None = None,
           stdin: bytes | None = None) -> bytes:
        cmd = list(_GIT)
        if git_dir is not None:
            cmd.append(f"--git-dir={git_dir}")
        if work_tree is not None:
            cmd.append(f"--work-tree={work_tree}")
        cmd += args
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
               "GIT_TERMINAL_PROMPT": "0", "HOME": str(self.root), "LC_ALL": "C"}
        try:
            done = subprocess.run(cmd, cwd=str(cwd or work_tree or self.root), env=env,
                                  input=stdin, capture_output=True, timeout=GIT_TIMEOUT,
                                  check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CopyError(f"git {args[0]} could not run ({exc.__class__.__name__})") from None
        if done.returncode != 0:
            stderr = done.stderr.decode("utf-8", "replace")
            unreadable = format_problem(stderr)
            if unreadable:
                raise CopyFormatError(unreadable)
            err = stderr.strip().splitlines()
            raise CopyError(f"git {args[0]} failed: {(err[-1] if err else '')[:200]}")
        return done.stdout

    def _head(self, git_dir: Path) -> str | None:
        if not (git_dir / "HEAD").exists():
            return None
        try:
            return self._g(["rev-parse", "--verify", "-q", "HEAD^{commit}"],
                           git_dir=git_dir).decode().strip() or None
        except CopyError:
            return None

    @staticmethod
    def recorded(root: Path) -> dict:
        """What a team root's copies were made from (``{source, commit}``), read only:
        ``{}`` before the first copy."""
        try:
            rec = json.loads((Path(root) / "project.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return rec if isinstance(rec, dict) else {}

    def record(self) -> dict:
        """What the team works on, fixed at its first copy: ``{source, commit}``."""
        try:
            return json.loads(self.record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        rec = self._source_commit()
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.record_path.with_name(f".project.{uuid.uuid4().hex}.json")
        tmp.write_text(json.dumps(rec, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.record_path)
        return rec

    def _source_commit(self) -> dict:
        if not self.source:
            return {"source": None, "commit": None}
        src = Path(self.source)
        if not src.is_dir():
            raise CopyError(f"the workspace {self.source} is not a folder")
        try:
            self._g(["rev-parse", "--show-toplevel"], cwd=src)
        except CopyFormatError:
            raise
        except CopyError:
            raise CopyError(NOT_GIT) from None
        try:
            commit = self._g(["rev-parse", "--verify", "-q", "HEAD^{commit}"],
                             cwd=src).decode().strip()
        except CopyError:
            raise CopyError("the workspace's git repository has no commit yet: the team works "
                            "on copies of its committed content") from None
        if self._g(["status", "--porcelain", "--untracked-files=no"], cwd=src).strip():
            raise CopyError("the workspace has uncommitted changes to tracked files; commit or "
                            "stash them first: the team copies committed content only")
        return {"source": str(src), "commit": commit}

    def ensure(self, member: str, pdir: Path) -> str:
        """The member's copy, made once; returns its commit. A copy that exists is never reset:
        the member's work in it stays."""
        gd = self.git_dir(member)
        head = self._head(gd)
        if head:
            return head
        rec = self.record()
        gd.parent.mkdir(parents=True, exist_ok=True)
        wt = self.checked_worktree(pdir, make=True)
        if not (gd / "HEAD").exists():
            self._g(["init", "-q"], git_dir=gd)
        if rec.get("commit"):
            # Committed content only, through git's own transfer (never hard links to the
            # workspace's files): no submodule's content and no LFS object -- the copy has no
            # filter configured, so an LFS file stays its pointer (ADR-M4-12, SW-34).
            self._g(["fetch", "-q", "--no-tags", "--no-recurse-submodules", rec["source"],
                     rec["commit"]], git_dir=gd)
            self._g(["reset", "-q", "--hard", "--no-recurse-submodules", rec["commit"]],
                    git_dir=gd, work_tree=wt)
        else:
            self._g(["commit", "-q", "--allow-empty", "--no-verify", "-m",
                     "Temper: the team's project starts empty"], git_dir=gd, work_tree=wt)
        head = self._head(gd)
        if not head:
            raise CopyError(f"{member}'s project copy has no commit")
        return head

    def commit_review(self, member: str, pdir: Path, act_id: str) -> str:
        """Commit the member's copy as it is, for the review ``act_id`` asked for (once)."""
        gd, wt = self.git_dir(member), self.checked_worktree(pdir)
        tag = f"[temper-act {act_id}]"
        head = self._head(gd)
        if head and tag in self._g(["log", "-1", "--format=%B"], git_dir=gd).decode():
            sha = head
        else:
            self._g(["add", "-A"], git_dir=gd, work_tree=wt)
            self._g(["commit", "-q", "--allow-empty", "--no-verify", "-m",
                     f"Temper review commit {tag}"], git_dir=gd, work_tree=wt)
            sha = self._head(gd) or ""
            if not sha:
                raise CopyError(f"{member}'s review commit was not made")
        self._g(["update-ref", f"refs/temper/review/{act_id}", sha], git_dir=gd)
        return sha

    def files(self, member: str, sha: str) -> tuple[dict[str, str], int]:
        """``{path: sha256}`` of the commit's files (at most ``MAX_FILES``) and their count."""
        gd = self.git_dir(member)
        listing = self._g(["ls-tree", "-r", "-z", "--full-tree", sha], git_dir=gd)
        entries = [e for e in listing.split(b"\0") if e]
        out: dict[str, str] = {}
        for entry in entries[:MAX_FILES]:
            meta, _, raw_path = entry.partition(b"\t")
            _mode, kind, oid = meta.decode().split()
            path = raw_path.decode("utf-8", "replace")
            if kind == "blob":
                data = self._g(["cat-file", "blob", oid], git_dir=gd)
                out[path] = hashlib.sha256(data).hexdigest()
            else:
                out[path] = f"{kind}:{oid}"
        return out, len(entries)

    def diff_base(self, member: str, sha: str) -> str:
        """What a version's diff is taken against: the start commit the copies were made from,
        or (a team that started empty) the copy's first commit."""
        start = self.record().get("commit")
        if start:
            return str(start)
        roots = self._g(["rev-list", "--max-parents=0", sha],
                        git_dir=self.git_dir(member)).decode().split()
        if not roots:
            raise CopyError(f"{member}'s copy has no first commit")
        return roots[-1]

    def diff(self, member: str, base: str, sha: str) -> bytes:
        """The text diff from ``base`` to ``sha`` (binary files are only named)."""
        return self._g(["diff", "--no-color", "--no-ext-diff", "--no-textconv",
                        "--no-renames", base, sha], git_dir=self.git_dir(member))

    def changed_blobs(self, member: str, base: str, sha: str) -> list[tuple[str, bytes]]:
        """Every file added or changed from ``base`` to ``sha``, with its whole content (binary
        files too): what the token scan reads before a version leaves the run."""
        gd = self.git_dir(member)
        raw = self._g(["diff", "--raw", "-z", "--no-renames", "--no-abbrev", base, sha],
                      git_dir=gd).split(b"\0")
        wanted: list[tuple[str, str]] = []
        for meta, raw_path in zip(raw[0::2], raw[1::2], strict=False):
            fields = meta.decode("ascii", "replace").lstrip(":").split()
            if len(fields) < 5:
                continue
            new_mode, new_oid = fields[1], fields[3]
            if new_mode == "160000" or set(new_oid) == {"0"}:
                continue  # a submodule's commit id, or a deleted file: no content leaves
            wanted.append((raw_path.decode("utf-8", "replace"), new_oid))
        if not wanted:
            return []
        out = self._g(["cat-file", "--batch"], git_dir=gd,
                      stdin="".join(f"{oid}\n" for _p, oid in wanted).encode())
        found: list[tuple[str, bytes]] = []
        pos = 0
        for path, _oid in wanted:
            end = out.index(b"\n", pos)
            header = out[pos:end].split()
            if len(header) < 3 or header[1] == b"missing":
                raise CopyError(f"{member}'s copy is missing the content of {path}")
            size = int(header[2])
            found.append((path, out[end + 1:end + 1 + size]))
            pos = end + 1 + size + 1
        return found

    def move_to(self, member: str, pdir: Path, leader: str, act_id: str, sha: str) -> None:
        """Make the member's copy exactly commit ``sha`` of the leader's copy."""
        gd, wt = self.git_dir(member), self.checked_worktree(pdir)
        if self._head(gd) == sha and self.changes(member, pdir) == 0:
            return
        ref = f"refs/temper/review/{act_id}"
        self._g(["fetch", "-q", "--no-tags", str(self.git_dir(leader)), f"+{ref}:{ref}"],
                git_dir=gd)
        self._g(["reset", "-q", "--hard", sha], git_dir=gd, work_tree=wt)
        self._g(["clean", "-q", "-ffdx"], git_dir=gd, work_tree=wt)

    def changes(self, member: str, pdir: Path) -> int:
        out = self._g(["status", "--porcelain", "--untracked-files=all"],
                      git_dir=self.git_dir(member), work_tree=self.checked_worktree(pdir))
        return len([line for line in out.decode("utf-8", "replace").splitlines() if line])

    def differs(self, member: str, pdir: Path, sha: str) -> str | None:
        """Why the member's copy is not exactly commit ``sha`` (None when it is)."""
        head = self._head(self.git_dir(member))
        if head != sha:
            return (f"your copy is at commit {str(head)[:12]}, not the reviewed commit "
                    f"{sha[:12]}")
        n = self.changes(member, pdir)
        if n:
            return f"your copy has {n} change(s) since the reviewed version"
        return None


# --- the team -------------------------------------------------------------------------------


@dataclass
class Outcome:
    """How the team node ends: ``done``, ``stopped``, ``failed`` or ``cancelled``."""

    status: str
    text: str = ""
    record: dict = field(default_factory=dict)


class LeaderChannel(TeamChannel):
    """A member's team socket in the leader loop: messages exactly as in #37, plus the review
    tools, bound to the turn Temper claimed (R2 B2) and fenced by its epoch."""

    def __init__(self, team: LeaderTeam, binding: Binding, reachable_names: list[str]):
        super().__init__(team.ledger, binding, reachable_names)
        self.team = team

    def handle(self, payload: Any) -> dict:
        if isinstance(payload, dict) and "op" in payload:
            return self.team.record_act(self.binding, payload)
        return super().handle(payload)


class TeamRows:
    """Reads of one team's rows in the ledger, shared by the leader loop and the Team page's
    read of a run (team_view.py), which has no box or recorder: ``ledger``, ``run_id``,
    ``host_path`` and ``leader`` are all it needs."""

    ledger: Ledger
    run_id: str
    host_path: str
    leader: str

    def _where(self, table: sa.Table) -> tuple:
        return (table.c.run_id == self.run_id, table.c.host_path == self.host_path)

    def _rows(self, table: sa.Table, *where: Any, order: Any = None) -> list[dict]:
        with _LOCK, self.ledger.engine.connect() as conn:
            q = sa.select(table).where(*self._where(table), *where)
            if order is not None:
                q = q.order_by(order)
            return [dict(r) for r in conn.execute(q).mappings().all()]

    def _member_rows(self) -> dict[str, dict]:
        return {r["member"]: r for r in self.ledger.participants_of(self.run_id, self.host_path)}

    def _reviews(self) -> list[dict]:
        return self._rows(reviews, order=reviews.c.round)

    def usage(self) -> dict:
        """The team's model usage so far, from its turns' receipts."""
        total = {"cost_usd": 0.0, "total_tokens": 0, "llm_calls": 0, "turns": 0}
        for t in self._rows(turns):
            u = (t.get("worker") or {}).get("usage") or {}
            total["cost_usd"] += float(u.get("cost_usd") or 0.0)
            total["total_tokens"] += int(u.get("total_tokens") or 0)
            total["llm_calls"] += int(u.get("llm_calls") or len(t.get("model_call_ids") or []))
            total["turns"] += 1
        total["cost_usd"] = round(total["cost_usd"], 6)
        return total

    def stopped(self) -> str | None:
        """Why the team was stopped, from its decided waits (None when not stopped). The text
        is neutral engine text (M3 E16): it never names who stopped it -- that is the
        outcome's ``by``."""
        stop = self.stop_wait()
        return stop_text(stop) if stop else None

    def stop_wait(self) -> dict | None:
        """The decided wait whose answer stopped the team (the first, by when it was decided),
        or None."""
        for w in self._rows(waits, waits.c.state == "decided", order=waits.c.decided_at):
            if stop_text(w) is not None:
                return dict(w)
        return None

    def done_review(self) -> dict | None:
        return next((r for r in self._reviews() if r["decision"] == "done"), None)

    def keep_goings(self, pauses: list[dict] | None = None) -> list[dict]:
        """The reviews that kept going since the last pause answered continue or guide: the
        count the pause is opened by (R2 B10)."""
        if pauses is None:
            pauses = self._rows(waits, waits.c.kind == "pause", order=waits.c.opened_at)
        answered = max(((w["subject"] or {}).get("round") or 0 for w in pauses
                        if w["state"] == "decided"
                        and (w["decision"] or {}).get("answer") in ("continue", "guide")),
                       default=0)
        return [r for r in self._reviews() if r["decision"] in KEEP_GOINGS
                and r["round"] > answered]


class LeaderTeam(TeamRows, Team):
    """#37's team, driven by the leader loop. Everything is read from and written to the
    ledger, so a later attempt (a resume after a park, a restart) carries on from the tables."""

    def __init__(self, *args: Any, leader: str, pause_after: int, goal: str,
                 project: ProjectCopies, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.leader = leader
        self.pause_after = int(pause_after)
        self.goal = goal
        self.project = project

    # --- Team seams -------------------------------------------------------------------

    @staticmethod
    def turn_runner(box: Any, req: Any, ledger: Any) -> Any:  # type: ignore[override]
        """#37's turn runner; the turn's usage is kept with its worker receipt (the cost of
        the done record)."""
        from temper_ai.pi_agent.turn import run_turn

        report = (Team.turn_runner or run_turn)(box, req, ledger)
        report.worker = {**(report.worker or {}), "usage": usage_of(report.outcome)}
        return report

    def tools_for(self, member: TeamMember) -> list[str]:
        own = LEADER_TOOLS if member.name == self.leader else REVIEWER_TOOLS
        return sorted(set(member_tools(member.config)) | set(own))

    def channel_for(self, binding: Binding, reachable_names: list[str]) -> TeamChannel:
        return LeaderChannel(self, binding, reachable_names)

    def prompt_for(self, member: TeamMember, turn: dict, batch: list[dict]) -> str:
        return (framing(member.name, self.leader, sorted(self.members), self.tools_for(member))
                + "\n\n" + render_batch(batch, team=True))

    # --- reading the team ----------------------------------------------------------------

    @staticmethod
    def _pdir(row: dict) -> Path:
        return Path(row["session_dir"]).parent

    def _end_reason(self) -> str | None:
        rows = list(self._member_rows().values())
        ended = [r for r in rows if r["state"] == "ended"]
        return (ended[0]["ended_reason"] or "run_cancelled") if ended else None

    # --- the review tools (recorded with the calling turn) ---------------------------------

    def record_act(self, binding: Binding, payload: dict) -> dict:
        """One review-tool call from a member's box, checked and recorded with its turn: it
        counts only once the turn has finished (completed or accepted). Returns what the tool
        shows the model: ``{ok, act_id, detail, duplicate}`` or ``{ok: False, code, detail}``."""
        with _LOCK, self.ledger._team_tx(binding.run_id, binding.host_path) as conn:
            if not _fence(conn, binding.turn_id, binding.epoch):
                logger.info("pi team: a review call on a closed channel was refused")
                return {"ok": False, "code": route_model.INVALID_CHANNEL,
                        "detail": "this turn's message channel is closed"}
            try:
                token_scan.refuse_tokens(payload)
                return self._admit_act(conn, binding, payload)
            except Refusal as refusal:
                Ledger._audit(conn, binding, refusal, payload)
                return {"ok": False, "code": refusal.code, "detail": refusal.detail}

    def _admit_act(self, conn: Any, binding: Binding, payload: dict) -> dict:
        op = payload.get("op")
        if op not in REVIEW_OPS:
            raise Refusal(route_model.INVALID_MESSAGE, "op must be one of: " + ", ".join(REVIEW_OPS))
        trusted = binding.trusted()
        forged = tuple(k for k in IDENTITY_CLAIMS
                       if k in payload and str(payload[k]) != str(trusted.get(k, "")))
        if forged:
            raise Refusal(route_model.IDENTITY_CLAIM_MISMATCH,
                          "a call cannot say who made it: Temper fills that in", claims=forged)
        allowed = {"op", "client_msg_id", *OP_FIELDS[op], *IDENTITY_CLAIMS}
        unknown = sorted(k for k in payload if k not in allowed)
        if unknown:
            raise Refusal(route_model.INVALID_MESSAGE, "unknown field(s): " + ", ".join(unknown)[:200])
        key = payload.get("client_msg_id")
        if not isinstance(key, str) or not 0 < len(key) <= 128:
            raise Refusal(route_model.INVALID_MESSAGE, "client_msg_id is missing")
        args = self._act_args(op, payload)
        digest = hashlib.sha256(json.dumps({"op": op, **args}, sort_keys=True).encode()).hexdigest()
        existing = conn.execute(sa.select(acts).where(
            acts.c.run_id == binding.run_id, acts.c.participant_id == binding.participant_id,
            acts.c.client_msg_id == key)).mappings().first()
        if existing is not None:
            if existing["content_sha256"] != digest:
                raise Refusal(route_model.IDEMPOTENCY_CONFLICT,
                              "that call id was already used for a different call")
            first = (existing["result"] or {}).get("reply") or {}
            return {**first, "ok": True, "act_id": existing["act_id"], "duplicate": True}
        is_leader = binding.member == self.leader
        if op in LEADER_TOOLS and not is_leader:
            raise Refusal(route_model.NOT_AUTHORIZED, f"only the leader ({self.leader}) can {op}")
        if op == GIVE_VIEW and is_leader:
            raise Refusal(route_model.NOT_AUTHORIZED, "the leader gives no view on its own work")
        mine = [dict(r) for r in conn.execute(sa.select(acts).where(
            acts.c.run_id == binding.run_id, acts.c.host_path == binding.host_path,
            acts.c.turn_id == binding.turn_id, acts.c.epoch == binding.epoch,
            acts.c.state != "void")).mappings().all()]
        revs = {r["review_id"]: dict(r) for r in conn.execute(sa.select(reviews).where(
            reviews.c.run_id == binding.run_id,
            reviews.c.host_path == binding.host_path)).mappings().all()}
        detail = getattr(self, f"_allow_{op}")(conn, binding, args, mine, revs)
        seq = (conn.execute(sa.select(sa.func.max(acts.c.seq)).where(
            acts.c.run_id == binding.run_id,
            acts.c.host_path == binding.host_path)).scalar() or 0) + 1
        act_id = _new_id()
        reply = {"detail": detail}
        conn.execute(acts.insert().values(
            act_id=act_id, run_id=binding.run_id, host_path=binding.host_path, seq=seq,
            participant_id=binding.participant_id, member=binding.member,
            turn_id=binding.turn_id, epoch=binding.epoch, client_msg_id=key,
            content_sha256=digest, op=op, args=args, review_id=args.get("review_id"),
            state="recorded", result={"reply": reply}, created_at=_now(), carried_at=None))
        return {"ok": True, "act_id": act_id, "detail": detail, "duplicate": False}

    @staticmethod
    def _act_args(op: str, payload: dict) -> dict:
        def text(name: str, limit: int, required: bool) -> str | None:
            value = payload.get(name)
            if value is None and not required:
                return None
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                need = "required" if required else "optional"
                raise Refusal(route_model.INVALID_MESSAGE,
                              f"{name} must be text of at most {limit} characters ({need})")
            return value.strip()

        def word(name: str, choices: tuple[str, ...]) -> str:
            value = payload.get(name)
            value = value.strip().lower() if isinstance(value, str) else value
            if value not in choices:
                raise Refusal(route_model.INVALID_MESSAGE,
                              f"{name} must be one of: " + ", ".join(choices))
            return str(value)

        if op == REQUEST_REVIEW:
            note = text("note", MAX_NOTE, required=False)
            return {"note": note} if note else {}
        review_id = text("review_id", 64, required=True)
        if op == GIVE_VIEW:
            return {"review_id": review_id, "verdict": word("verdict", VERDICTS),
                    "note": text("note", MAX_NOTE, required=True)}
        return {"review_id": review_id, "decision": word("decision", DECISIONS),
                "summary": text("summary", MAX_SUMMARY, required=True)}

    def _allow_request_review(self, conn: Any, binding: Binding, args: dict, mine: list[dict],
                              revs: dict[str, dict]) -> str:
        if any(a["op"] == REQUEST_REVIEW for a in mine):
            raise Refusal(NOT_NOW, "this turn already asked for a review")
        if any(a["op"] == DECIDE and a["args"].get("decision") == "done" for a in mine):
            raise Refusal(NOT_NOW, "you decided done in this turn")
        if any(r["decision"] == "done" for r in revs.values()):
            raise Refusal(NOT_NOW, "the team is done")
        if any(r["state"] == "open" for r in revs.values()):
            raise Refusal(NOT_NOW, "a review is still collecting views; wait for them")
        pending = [r for r in revs.values() if r["state"] == "collected" and not r["decision"]]
        decided_now = {a["args"].get("review_id") for a in mine if a["op"] == DECIDE}
        for r in pending:
            if r["review_id"] not in decided_now:
                raise Refusal(NOT_NOW, f"decide on review {r['review_id']} first (done or "
                                       "keep_going)")
        return ("Recorded. When this turn has finished, Temper commits your copy as it is then "
                "and gives every reviewer exactly that version.")

    def _allow_give_view(self, conn: Any, binding: Binding, args: dict, mine: list[dict],
                         revs: dict[str, dict]) -> str:
        rid = args["review_id"]
        rev = revs.get(rid)
        if rev is None or rev["state"] != "open":
            raise Refusal(route_model.INVALID_REFERENCE, "no review with that id is collecting "
                                                         "views")
        asked = conn.execute(sa.select(sa.func.count()).select_from(messages).where(
            messages.c.run_id == binding.run_id, messages.c.host_path == binding.host_path,
            messages.c.review_id == rid, messages.c.kind == "review_request",
            messages.c.to_participant == binding.participant_id,
            messages.c.state == "consumed")).scalar_one()
        if not asked:
            raise Refusal(route_model.NOT_AUTHORIZED, "you were not asked to review that version")
        earlier = conn.execute(sa.select(sa.func.count()).select_from(acts).where(
            acts.c.run_id == binding.run_id, acts.c.host_path == binding.host_path,
            acts.c.participant_id == binding.participant_id, acts.c.op == GIVE_VIEW,
            acts.c.review_id == rid, acts.c.state != "void")).scalar_one()
        if earlier:
            raise Refusal(NOT_NOW, "you already gave your view on that review")
        return (f"Recorded your view ({args['verdict']}). Temper passes it to {self.leader} "
                "when this turn has finished.")

    def _allow_decide(self, conn: Any, binding: Binding, args: dict, mine: list[dict],
                      revs: dict[str, dict]) -> str:
        rev = revs.get(args["review_id"])
        if rev is None or rev["state"] != "collected" or rev["decision"]:
            raise Refusal(NOT_NOW, "no review with that id is waiting for your decision")
        if any(a["op"] == DECIDE for a in mine):
            raise Refusal(NOT_NOW, "this turn already decided")
        if args["decision"] == "done":
            return ("Recorded: done. When this turn has finished, Temper checks it: done counts "
                    "only if your copy is still exactly the reviewed version and nothing new "
                    "reached you since this turn began; otherwise it counts as keep going.")
        return ("Recorded: keep going. When this turn has finished, Temper records it; call "
                "request_review when the next version is ready.")

    # --- carrying the calls out -------------------------------------------------------------

    def carry_out(self) -> None:
        """Carry out, in order and once, every review-tool call whose turn has finished; a call
        of a turn that failed, was retried or cancelled is void. Runs before every claim of
        the team's next turn, so the next turn always sees what the last one asked for."""
        while True:
            act = self._next_act()
            if act is None:
                break
            state = act["turn_state"]
            if state in ("failed", "superseded", "cancelled"):
                self._settle_act(act, "void", {"void": f"its turn {state}"})
                continue
            if state not in ("completed", "accepted"):
                break  # its turn has not settled: nothing after it is carried out either
            getattr(self, f"_carry_{act['op']}")(act)
        self._close_reviews(idle=False)

    def _next_act(self) -> dict | None:
        with _LOCK, self.ledger.engine.connect() as conn:
            row = conn.execute(sa.select(acts, turns.c.state.label("turn_state")).join(
                turns, turns.c.turn_id == acts.c.turn_id).where(
                acts.c.run_id == self.run_id, acts.c.host_path == self.host_path,
                acts.c.state == "recorded").order_by(acts.c.seq).limit(1)).mappings().first()
            return dict(row) if row else None

    def _settle_act(self, act: dict, state: str, result: dict, conn: Any = None) -> bool:
        """Compare-and-set the call recorded -> ``state`` (once, whoever gets there first)."""
        values = {"state": state, "result": {**(act.get("result") or {}), **result},
                  "carried_at": _now()}
        if "review_id" in result and act["op"] == REQUEST_REVIEW:
            values["review_id"] = result["review_id"]
        stmt = acts.update().where(acts.c.act_id == act["act_id"],
                                   acts.c.state == "recorded").values(**values)
        if conn is not None:
            return conn.execute(stmt).rowcount == 1
        with _LOCK, self.ledger._team_tx(self.run_id, self.host_path) as c:
            return c.execute(stmt).rowcount == 1

    def _carry_request_review(self, act: dict) -> None:
        rows = self._member_rows()
        lead = rows.get(self.leader)
        if lead is None:
            raise TeamFailure(f"the leader {self.leader} has no conversation")
        reviewers = [r for name, r in sorted(rows.items())
                     if name != self.leader and r["state"] not in ("retired", "ended")]
        try:
            sha = self.project.commit_review(self.leader, self._pdir(lead), act["act_id"])
            files, count = self.project.files(self.leader, sha)
            # The leader made a version: its record, token-scanned, is what team_version
            # serves (ADR-M4-12 H, SW-36, SW-52).
            version = team_versions.build(self.project, self.leader, sha, files=files,
                                          files_total=count)
            for r in reviewers:
                self.project.move_to(r["member"], self._pdir(r), self.leader, act["act_id"], sha)
        except CopyError as exc:
            raise TeamFailure(f"the review of round {self._next_round()} could not be set up: "
                              f"{exc}") from None
        if team_versions.withheld(version):
            files = {}  # nothing of a version holding a login token leaves the run
        note = (act["args"] or {}).get("note")
        with _LOCK, self.ledger._team_tx(self.run_id, self.host_path) as conn:
            round_no = (conn.execute(sa.select(sa.func.max(reviews.c.round)).where(
                *self._where(reviews))).scalar() or 0) + 1
            rid = _new_id()
            if not self._settle_act(act, "carried_out", {
                    "review_id": rid, "round": round_no, "commit": sha,
                    "reviewers": [r["member"] for r in reviewers], "file_count": count},
                    conn=conn):
                return
            conn.execute(reviews.insert().values(
                review_id=rid, run_id=self.run_id, host_path=self.host_path, round=round_no,
                leader_participant=lead["participant_id"], asked_turn=act["turn_id"],
                commit_sha=sha, files=files, state="open" if reviewers else "collected",
                decision=None, decided_turn=None, summary=None, cost=None, opened_at=_now(),
                decided_at=None))
            team_versions.store(conn, run_id=self.run_id, host_path=self.host_path,
                                kind="review", record=version, act_id=act["act_id"],
                                review_id=rid, round_no=round_no, member=self.leader)
            for r in reviewers:
                body = "\n".join(filter(None, [
                    f"Review {rid} (round {round_no}) from {self.leader}: your project copy now "
                    f"holds exactly the version to review (commit {sha[:12]}).",
                    f"The team's goal: {_one_line(self.goal, MAX_SUMMARY)}",
                    f"{self.leader}'s note: {_one_line(note)}" if note else "",
                    f"Look at it, then call give_view with review_id {rid}: satisfied, or "
                    "changes with a short note saying what to change."]))
                self.ledger.post(self.run_id, self.host_path, r["member"], body,
                                 sender="temper", sender_kind="temper", kind="review_request",
                                 dedupe_key=f"review:{rid}:ask:{r['member']}", review_id=rid,
                                 conn=conn)
            if not reviewers:
                self.ledger.post(self.run_id, self.host_path, self.leader,
                                 f"Review {rid} (round {round_no}): this team has no other "
                                 "member to review it. Decide with the decide tool, naming "
                                 f"review {rid}: done or keep_going.",
                                 sender="temper", sender_kind="temper", kind="notice",
                                 dedupe_key=f"review:{rid}:none", review_id=rid, conn=conn)

    def _next_round(self) -> int:
        return (max((r["round"] for r in self._reviews()), default=0)) + 1

    def _carry_give_view(self, act: dict) -> None:
        rid = (act["args"] or {}).get("review_id")
        rev = next((r for r in self._reviews() if r["review_id"] == rid), None)
        if rev is None or rev["state"] != "open":
            self._settle_act(act, "void", {"void": "the review was no longer collecting views"})
            return
        self._settle_act(act, "carried_out", {"verdict": act["args"]["verdict"]})

    def _carry_decide(self, act: dict) -> None:
        args = act["args"] or {}
        rid = args.get("review_id")
        rev = next((r for r in self._reviews() if r["review_id"] == rid), None)
        if rev is None or rev["state"] != "collected" or rev["decision"]:
            self._settle_act(act, "void", {"void": "the review was not waiting for a decision"})
            return
        refused = None
        if args.get("decision") == "done":
            refused = self._done_refusal(rev)
        decision = (args.get("decision") if refused is None else "done_refused")
        cost = self.usage() if decision == "done" else None
        with _LOCK, self.ledger._team_tx(self.run_id, self.host_path) as conn:
            if not self._settle_act(act, "carried_out", {"decision": decision,
                                                         **({"refused": refused} if refused
                                                            else {})}, conn=conn):
                return
            conn.execute(reviews.update().where(
                reviews.c.review_id == rid, reviews.c.state == "collected").values(
                state="decided", decision=decision, decided_turn=act["turn_id"],
                summary=args.get("summary"), cost=cost, decided_at=_now()))
            if decision == "done":
                return
            if refused:
                self.ledger.post(self.run_id, self.host_path, self.leader,
                                 f"Done on review {rid} was refused: {refused}. It counts as "
                                 "keep going.", sender="temper", sender_kind="temper",
                                 kind="notice", dedupe_key=f"act:{act['act_id']}:refused",
                                 review_id=rid, conn=conn)
            asked_again = conn.execute(sa.select(sa.func.count()).select_from(acts).where(
                acts.c.run_id == self.run_id, acts.c.host_path == self.host_path,
                acts.c.turn_id == act["turn_id"], acts.c.op == REQUEST_REVIEW,
                acts.c.state != "void")).scalar_one()
            if not asked_again:
                self.ledger.post(self.run_id, self.host_path, self.leader,
                                 "Keep going: when the next version is ready, call "
                                 "request_review.", sender="temper", sender_kind="temper",
                                 kind="notice", dedupe_key=f"act:{act['act_id']}:next",
                                 conn=conn)

    def _done_refusal(self, rev: dict) -> str | None:
        """Why the leader's done can't count (None when it can): its copy must still be exactly
        the reviewed commit, and no work for it may have arrived after its deciding turn began
        (T4T5 C6: read from the leader's pending and held work at decision time)."""
        lead = self._member_rows().get(self.leader)
        if lead is None:
            return "the leader has no conversation"
        try:
            why = self.project.differs(self.leader, self._pdir(lead), rev["commit_sha"])
        except CopyError as exc:
            why = f"Temper could not compare your copy ({exc})"
        if why:
            return why
        waiting = self._rows(messages, messages.c.to_participant == lead["participant_id"],
                             messages.c.state.in_(("pending", "held")))
        if waiting:
            return (f"{len(waiting)} new message(s) reached you after your deciding turn began; "
                    "read them first")
        return None

    def _close_reviews(self, *, idle: bool) -> bool:
        """Pass a review's views to the leader once every asked reviewer has given one -- or,
        when the team has nothing left to do (``idle``), with the missing ones named."""
        closed = False
        for rev in self._reviews():
            if rev["state"] != "open":
                continue
            asked = {m["to_participant"] for m in self._rows(
                messages, messages.c.review_id == rev["review_id"],
                messages.c.kind == "review_request")}
            views = self._rows(acts, acts.c.review_id == rev["review_id"],
                               acts.c.op == GIVE_VIEW, acts.c.state == "carried_out",
                               order=acts.c.seq)
            missing = asked - {v["participant_id"] for v in views}
            if missing and not idle:
                continue
            closed = self._collect(rev, views, missing) or closed
        return closed

    def _collect(self, rev: dict, views: list[dict], missing: set[str]) -> bool:
        rows = self._member_rows()
        by_pid = {r["participant_id"]: r for r in rows.values()}
        lead = rows.get(self.leader)
        if lead is None:
            return False
        rid, round_no = rev["review_id"], rev["round"]
        with _LOCK, self.ledger._team_tx(self.run_id, self.host_path) as conn:
            if conn.execute(reviews.update().where(
                    reviews.c.review_id == rid, reviews.c.state == "open").values(
                    state="collected")).rowcount != 1:
                return False
            now = _now()
            for v in views:
                sender = by_pid[v["participant_id"]]
                args = v["args"] or {}
                body = (f"View on review {rid} (round {round_no}, version "
                        f"{rev['commit_sha'][:12]}): {args.get('verdict')}. Note: "
                        f"{_one_line(args.get('note') or '')}")
                mid = _new_id()
                conn.execute(messages.insert().values(
                    message_id=mid, dedupe_key=f"review:{rid}:view:{v['act_id']}",
                    run_id=self.run_id, host_path=self.host_path,
                    to_participant=lead["participant_id"], to_member=self.leader,
                    sender=sender["member"], sender_kind="member",
                    sender_participant=sender["participant_id"],
                    sender_session=sender["session_id"], sender_turn=v["turn_id"],
                    sender_epoch=v["epoch"], kind="view", client_msg_id=f"view:{v['act_id']}",
                    content_sha256=content_digest("view", self.leader, body, None, None),
                    in_reply_to=None, thread_id=mid, outcome=None,
                    policy_version=REVIEW_POLICY, body=body, state="pending", turn_id=None,
                    delivery_count=0, redeliver_turn=None, undelivered_reason=None,
                    released_at=now, delivered_at=None, review_id=rid, created_at=now))
            verdicts = [(v["args"] or {}).get("verdict") for v in views]
            gone = sorted(by_pid[p]["member"] for p in missing if p in by_pid)
            summary = (f"{verdicts.count('satisfied')} satisfied, "
                       f"{verdicts.count('changes')} changes")
            self.ledger.post(
                self.run_id, self.host_path, self.leader,
                f"Review {rid} (round {round_no}): the views are in ({summary})"
                + (f"; no view from {', '.join(gone)}" if gone else "")
                + f". Decide with the decide tool, naming review {rid}: done (the reviewed "
                  "version is the result) or keep_going.",
                sender="temper", sender_kind="temper", kind="notice",
                dedupe_key=f"review:{rid}:collected", review_id=rid, conn=conn)
        return True

    # --- the owner's waits ----------------------------------------------------------------

    def _open_pause_if_due(self) -> dict | None:
        """The pause after ``pause_after_rounds`` keep-goings in a row: one owner wait in the
        same run (R2 B10). Continue and guide restart the count; it never expires."""
        pauses = self._rows(waits, waits.c.kind == "pause", order=waits.c.opened_at)
        if any(w["state"] == "open" for w in pauses):
            return None
        kept = self.keep_goings(pauses)
        if len(kept) < self.pause_after:
            return None
        round_no = max(r["round"] for r in kept)
        label = f"pause-after-round-{round_no}"
        subject = {
            "label": label, "header": label, "round": round_no, "keep_goings": len(kept),
            "question": (f"The team kept going {len(kept)} round(s) in a row "
                         f"(pause_after_rounds {self.pause_after}) and is paused after round "
                         f"{round_no}."),
            "reply_hint": f"Reply 'continue', 'guide: <what to tell {self.leader}>', or 'stop'.",
            "options": list(PAUSE_OPTIONS),
        }
        return self._open_wait("pause", subject, only_if_none_of_kind=True)

    def _open_stalled(self) -> dict | None:
        subject = {
            "header": "team-stalled",
            "question": (f"The team is stalled: nothing is running, nothing is waiting to be "
                         f"delivered and {self.leader} has not said done."),
            "reply_hint": (f"Reply 'nudge' (optionally with a message for {self.leader}) "
                           "or 'stop'."),
            "options": list(STALLED_OPTIONS),
        }
        return self._open_wait("stalled", subject, only_if_none_of_kind=False)

    def _open_wait(self, kind: str, subject: dict, *, only_if_none_of_kind: bool) -> dict | None:
        """Write the wait's row first (it is asked afterwards, under the row's id)."""
        with _LOCK, self.ledger._team_tx(self.run_id, self.host_path) as conn:
            q = sa.select(sa.func.count()).select_from(waits).where(
                *self._where(waits), waits.c.state == "open")
            if only_if_none_of_kind:
                q = q.where(waits.c.kind == kind)
            if conn.execute(q).scalar_one():
                return None
            return self.ledger._open_wait(conn, self.run_id, self.host_path, kind, subject,
                                          self.attempt_id)

    def ask(self, context: Any, wait: dict) -> Any:
        """The owner's answer at an open wait, asked under the wait row's own id. In a Pi
        workflow an unanswered wait parks the run (``RunParked`` goes up untouched). None when
        another attempt decided the wait meanwhile."""
        subject = wait["subject"] or {}
        question = ask_text(subject, "The team is waiting for you.")
        header = subject.get("header") or (
            f"{subject.get('member')} turn {subject.get('turn_no')}"
            if wait["kind"] == "recovery" else wait["kind"])
        try:
            return ask_owner_for_wait(context, self.ledger, wait["wait_id"], question=question,
                                      header=str(header), options=subject.get("options") or ())
        except WaitDecided:
            return None  # decided (or cancelled with the team's end) meanwhile: re-read
        except ReplacedByLaterAttempt:
            # A later attempt of the run took the wait over: the team is that attempt's
            # now, so nothing here ends or writes anything (SW-84).
            raise
        except CancellationError:
            self.end("run_cancelled")  # the run was stopped while the owner was asked (B12)
            raise

    def apply(self, wait: dict, answer: Any) -> None:
        """Apply the owner's answer once (the wait row's compare-and-set): continue / guide /
        stop at the pause, nudge / stop when stalled, accept / retry / stop at a recovery wait,
        any answer to an owner question (delivered to the member who asked).

        Every decision keeps who answered (``by``, ``source``: the API guard's record of the
        caller, M3 E21); a stop keeps the words given with it as ``words`` (E18), which become
        the outcome's ``owner_words``."""
        kind, wid = wait["kind"], wait["wait_id"]
        subject = wait["subject"] or {}
        text = str(getattr(answer, "text", "") or "")
        sha = hashlib.sha256(text.encode()).hexdigest()
        who = answer_who(answer)
        # The picked option or the typed answer's first word, never the rendered
        # "Q: ... A: ..." text (M3 F1): a pick of "retry" is a retry. The words come apart
        # from the choice (E17).
        word, rest = owner_words(answer)
        if kind == "recovery":
            self.decide(wait, f"{word} {rest}".strip(), words=rest, who=who)
            return
        if kind == SETTINGS:
            self._apply_settings(wait, settings_word(word, rest), rest,
                                 {"text_sha256": sha, **who})
            return
        if kind == "pause":
            r = subject.get("round")
            base = {"round": r, "text_sha256": sha, **who}
            if word == "continue":
                self.ledger.decide_wait(wid, {"answer": "continue", **base}, self.attempt_id)
            elif word == "guide" and rest:
                self.ledger.decide_wait(
                    wid, {"answer": "guide", **base}, self.attempt_id,
                    deliveries=[(self.leader, f"Guidance from the owner at the pause after "
                                              f"round {r}: {rest}")])
            elif word == "stop":
                self.ledger.decide_wait(wid, {"answer": "stop", **base,
                                              "words": stop_words(rest)}, self.attempt_id)
            else:  # never taken as a continue or as done: the owner is asked again
                self.ledger.decide_wait(wid, {"answer": "invalid", **base}, self.attempt_id)
            return
        if kind == "stalled":
            base = {"text_sha256": sha, **who}
            if word == "nudge":
                self.ledger.decide_wait(
                    wid, {"answer": "nudge", **base}, self.attempt_id,
                    deliveries=[(self.leader, "A nudge from the owner: the team has nothing to "
                                              "do and you have not said done."
                                              + (f" {rest}" if rest else ""))])
            elif word == "stop":
                self.ledger.decide_wait(wid, {"answer": "stop", **base,
                                              "words": stop_words(rest)}, self.attempt_id)
            else:
                self.ledger.decide_wait(wid, {"answer": "invalid", **base}, self.attempt_id)
            return
        member = subject.get("member")
        self.ledger.decide_wait(wid, {"answer": "given", "text_sha256": sha, **who},
                                self.attempt_id,
                                deliveries=[(member, text)] if member and text else [])

    def _apply_settings(self, wait: dict, choice: str | None, rest: str, base: dict) -> None:
        """The owner's answer at the team's settings wait (SW-85). ``go on``: every member it
        named is re-pinned to its new settings in one transaction -- only when the settings
        now are exactly the ones it named (compare-and-set on each stored pin); when they
        changed again meanwhile, nothing is re-pinned (``applied`` false) and the loop opens
        a new settings wait naming the newer ones. ``stop``: the team stops (its end comes
        from :meth:`TeamRows.stopped`), keeping the words given with it. Anything else is
        never a go on or a stop: the owner is asked again."""
        wid, subject = wait["wait_id"], wait["subject"] or {}
        base = {**base, "changed": changed_names(subject.get("settings_changes") or []),
                "pins": [{k: e.get(k) for k in ("member", "pin_old", "pin_new")}
                         for e in subject.get("pins") or []]}
        if choice is None:
            self.ledger.decide_wait(wid, {"answer": INVALID, **base}, self.attempt_id,
                                    reask=settings_asked_again(subject))
            return
        if choice == STOP:
            self.ledger.decide_wait(wid, {"answer": STOP, **base, "words": stop_words(rest)},
                                    self.attempt_id)
            return
        changed = self.settings_changed()
        now = team_subject(changed)["pins"] if changed else []
        if now and same_change(subject, now):
            repin = [(e["participant_id"], str(e["pin_old"]), self.pins[e["member"]])
                     for e in subject.get("pins") or []]
            self.ledger.decide_wait(wid, {"answer": GO_ON, **base}, self.attempt_id,
                                    repin=repin)
            return
        self.ledger.decide_wait(
            wid, {"answer": GO_ON, **base, "applied": False,
                  "why": ("the settings changed again before this answer was applied" if now
                          else "the settings are no longer changed")}, self.attempt_id)

    # --- the loop ---------------------------------------------------------------------------

    def drive(self, context: Any) -> Outcome:
        """Run the team until it is done, stopped, failed or cancelled; an unanswered owner wait
        parks the run on the way (``RunParked``), and the next go carries on from the tables.
        The run view follows along (:meth:`show`), up to the moment it parks or ends."""
        try:
            return self._drive(context)
        finally:
            self.show()

    def _drive(self, context: Any) -> Outcome:
        while True:
            self.show()
            reason = self._end_reason()
            if reason == "team_done":
                return Outcome("done", record=self.done_record())
            if reason == "team_stopped":
                return Outcome("stopped", self.stopped() or "the team was stopped")
            if reason == "run_cancelled":
                return Outcome("cancelled", "the run was cancelled")
            if reason == ACCOUNT_REFUSED:
                # The run's account refused a model call: no reset fixes that, so the team
                # stays stopped, also on a Resume (ADR-M4-16).
                return Outcome("failed", refusal_problem(self.account_slot))
            if reason is not None:
                return Outcome("failed", f"the team ended ({reason}) before it was done")
            if self.cancel_event is not None and self.cancel_event.is_set():
                self.end("run_cancelled")
                continue
            # A member's settings or the team's changed since its conversations started (a
            # deploy while the team waited): the owner is asked first, before anything else is
            # done (SW-85). Not when the team is stopping or done: nothing more runs in it.
            if (not self.stopped() and not self.done_review()
                    and self.open_settings_wait()):
                wait = self.ledger.open_waits(self.run_id, self.host_path)[0]
                answer = self.ask(context, wait)
                if answer is not None:
                    self.apply(wait, answer)
                continue
            try:
                self.carry_out()
            except TeamFailure as exc:
                return Outcome("failed", str(exc))
            if self.done_review():
                self.end("team_done")
                continue
            if self.stopped():
                self.end("team_stopped")
                continue
            self._open_pause_if_due()
            open_waits = self.ledger.open_waits(self.run_id, self.host_path)
            if open_waits:
                wait = open_waits[0]
                answer = self.ask(context, wait)
                if answer is not None:
                    self.apply(wait, answer)
                continue
            # A turn boundary: a Pi lane that is stopping lets the run go here, before the
            # next member turn; the lane's next start carries the team on from the ledger.
            leave_if_draining(f"team {self.host_path}")
            result = self.step()
            if result.kind in ("completed", "held", "waiting"):
                continue
            if result.kind == "idle":
                if not self._close_reviews(idle=True):
                    self._open_stalled()
                continue
            if result.kind == "failed":
                return Outcome("failed", result.error or f"{result.member}'s turn failed")
            if result.kind == "refused":
                # The account refused the call: the turn is red (it names the slot and the
                # refusal) and the team stops. No wait, no other slot, no retry.
                self.end(ACCOUNT_REFUSED)
                continue
            return Outcome("failed", "another attempt of this run is running the team: "
                                     "refusing to run it twice")

    def done_record(self) -> dict:
        """Temper's record of done: the node's outputs for later nodes (R2 B9)."""
        rev = self.done_review() or {}
        last_views: dict[str, dict] = {}
        views_on_done: dict[str, dict] = {}
        earlier: dict[str, dict] = {}
        rounds = {r["review_id"]: r["round"] for r in self._reviews()}
        for v in self._rows(acts, acts.c.op == GIVE_VIEW, acts.c.state == "carried_out",
                            order=acts.c.seq):
            args = v["args"] or {}
            view = {"verdict": args.get("verdict"), "note": args.get("note"),
                    "review_id": v["review_id"], "round": rounds.get(v["review_id"])}
            last_views[v["member"]] = view
            if rev and v["review_id"] == rev.get("review_id"):
                views_on_done[v["member"]] = view
            else:
                earlier[v["member"]] = view
        return {
            "objections": self._objections(rev, views_on_done, earlier),
            "branch": None,
            "decision": "done",
            "review_id": rev.get("review_id"),
            "round": rev.get("round"),
            "version": {"commit": rev.get("commit_sha"), "files": rev.get("files") or {}},
            "views": last_views,
            "summary": rev.get("summary"),
            "rounds": len(self._reviews()),
            "cost": rev.get("cost") or self.usage(),
            "project": self.project.record() if self.project.record_path.exists() else {},
            "leader": self.leader,
        }

    def done_version(self, record: dict) -> tuple[dict | None, str | None]:
        """Store the done version's record (kind ``done``; ADR-M4-12 H): the record made when
        its review was asked for, or (a review made before records were kept) one read now
        from the leader's copy. Returns it and, when no branch may be made from it, why: it
        holds a login token, or it couldn't be checked for one. Never raises: done stays
        done."""
        sha = (record.get("version") or {}).get("commit")
        if not sha:
            return None, None
        rid = record.get("review_id")
        try:
            with _LOCK, self.ledger._team_tx(self.run_id, self.host_path) as conn:
                made = (team_versions.of_review(conn, self.run_id, self.host_path, rid)
                        if rid else None)
            if made is None or made["commit_sha"] != sha:
                made = team_versions.build(self.project, self.leader, sha)
            with _LOCK, self.ledger._team_tx(self.run_id, self.host_path) as conn:
                team_versions.store(conn, run_id=self.run_id, host_path=self.host_path,
                                    kind="done", record=made, review_id=rid,
                                    round_no=record.get("round"), member=self.leader)
        except Exception:  # noqa: BLE001 - done stays done; nothing unchecked leaves the run
            logger.warning("pi team: the done version's record could not be made",
                           exc_info=True)
            return None, ("the version could not be checked for login tokens, so no branch "
                          "was made from it")
        if team_versions.withheld(made):
            return made, (f"the version holds {token_scan.Hits.of(made['scan']).words()}, so "
                          "no branch was made from it")
        return made, None

    def _objections(self, rev: dict, on_done: dict[str, dict],
                    last: dict[str, dict]) -> list[dict]:
        """Who didn't agree with the version that was done (M3 E1): each member asked to review
        it, or who gave a view on it, whose view on it isn't ``satisfied`` (``changes``), or who
        gave none (``none``, with their last earlier view as context). The rule of
        M1/harness/m1_proof.py."""
        rid = rev.get("review_id")
        if not rid:
            return []
        asked = {m["to_member"] for m in self._rows(
            messages, messages.c.kind == "review_request", messages.c.review_id == rid)}
        out = []
        for member in sorted(asked | set(on_done)):
            if member == self.leader:
                continue
            view = on_done.get(member)
            if view is not None:
                if view["verdict"] == "satisfied":
                    continue
                out.append({"member": member, "verdict": "changes", "note": view["note"],
                            "view_round": view["round"]})
                continue
            earlier = last.get(member) or {}
            out.append({"member": member, "verdict": "none", "note": earlier.get("note"),
                        "view_round": earlier.get("round")})
        return out

    # --- the run view -------------------------------------------------------------------------

    def show(self) -> None:
        """Put the team's story on the team node's row for the run view: messages sender to
        receiver, each review with its views, each owner wait with its answer, and the decision
        (``collaboration_events``, the stage view's Collaboration fold). Built from the tables, so
        a later attempt shows the whole story; sent only when it changed. Never fails the team:
        a view that could not be written is logged (nothing here asks the owner)."""
        if not self.parent_event_id or self.recorder is None:
            return
        try:
            story = run_view(self)
            digest = hashlib.sha256(json.dumps(story, sort_keys=True, default=str)
                                    .encode()).hexdigest()
            if digest == getattr(self, "_shown", None):
                return
            self.recorder.update_event(self.parent_event_id,
                                       data={"collaboration_events": story})
            self._shown = digest
        except Exception:  # noqa: BLE001 - the view only; the team's own records are the tables
            logger.warning("team %s %s: the run view could not be updated", self.run_id,
                           self.host_path, exc_info=True)


#: The run view keeps the newest entries (a long team's story is still in its tables).
VIEW_LIMIT = 400
VIEW_PREVIEW = 160


def _at(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


#: The wait kinds as the Team page names them: a member's question is ``owner`` in the ledger.
WAIT_KIND_SHOWN = {"owner": "question", "pause": "pause", "stalled": "stalled",
                   "recovery": "recovery", SETTINGS: SETTINGS}


def run_view(team: TeamRows) -> list[dict]:
    """The team's story in the run view's collaboration-event shape (``event_type``,
    ``from_agent``, ``to_agent``, ``timestamp``, ``data``, plus the typed fields of M3 E14),
    oldest first: the newest :data:`VIEW_LIMIT` entries, after one saying how many earlier
    ones are not shown."""
    out = story(team)
    if len(out) > VIEW_LIMIT:
        hidden = len(out) - VIEW_LIMIT
        out = [{"event_type": f"{hidden} earlier entries not shown", "data": {}},
               *out[-VIEW_LIMIT:]]
    return out


def story(team: TeamRows, *, full: bool = False, answers: tuple | list = (),
          turn_rows: tuple | list = ()) -> list[dict]:
    """Every entry of the team's story, oldest first. Each carries the typed fields the Team
    page reads (M3 E14) -- ``entry`` (message, review_round, view, decision, owner_wait,
    owner_answer, member_turn), ``message_kind``, ``round``, ``decision``, ``wait_kind`` -- so
    nothing has to parse ``event_type``, which stays the run page's text.

    The run page's story has messages, review rounds, decisions, owner waits and the stop.
    The Team page's (``full``, team_view.py) adds each view, each owner answer (``answers``:
    entries built by the caller, with who answered) and each member turn (``turn_rows``)."""
    entries: list[tuple[str, float, dict]] = []
    for m in team._rows(messages, order=messages.c.seq):
        body = str(m["body"] or "")
        data: dict[str, Any] = {"message_id": m["message_id"], "state": m["state"],
                                "deliveries": m["delivery_count"]}
        if m["review_id"]:
            data["review_id"] = m["review_id"]
        if m["undelivered_reason"]:
            data["undelivered"] = m["undelivered_reason"]
        data["preview"] = body[:VIEW_PREVIEW] + ("..." if len(body) > VIEW_PREVIEW else "")
        entries.append((_at(m["created_at"]) or "", 0, {
            "event_type": f"message: {m['kind']}", "from_agent": m["sender"],
            "to_agent": m["to_member"], "timestamp": _at(m["created_at"]), "data": data,
            "entry": "message", "message_kind": m["kind"]}))
    rounds = {r["review_id"]: r["round"] for r in team._reviews()}
    views: dict[str, dict[str, dict]] = {}
    for a in team._rows(acts, acts.c.op == GIVE_VIEW, acts.c.state == "carried_out",
                        order=acts.c.seq):
        args = a["args"] or {}
        view = {"verdict": args.get("verdict"), "note": str(args.get("note") or "")[:VIEW_PREVIEW]}
        views.setdefault(a["review_id"], {})[a["member"]] = view
        if full:
            entries.append((_at(a["carried_at"]) or "", 1.5, {
                "event_type": f"view: {view['verdict']}", "from_agent": a["member"],
                "to_agent": team.leader, "timestamp": _at(a["carried_at"]),
                "data": {"review_id": a["review_id"], **view},
                "entry": "view", "round": rounds.get(a["review_id"])}))
    for r in team._reviews():
        entries.append((_at(r["opened_at"]) or "", 1, {
            "event_type": f"review round {r['round']}", "from_agent": team.leader,
            "timestamp": _at(r["opened_at"]),
            "data": {"review_id": r["review_id"], "state": r["state"],
                     "commit": r["commit_sha"], "files": r["files"] or {},
                     "views": views.get(r["review_id"], {}), "decision": r["decision"]},
            "entry": "review_round", "round": r["round"]}))
        if r["decision"]:
            entries.append((_at(r["decided_at"]) or "", 2, {
                "event_type": f"decision: {r['decision']}", "from_agent": team.leader,
                "timestamp": _at(r["decided_at"]),
                "data": {"review_id": r["review_id"], "round": r["round"],
                         "commit": r["commit_sha"],
                         "summary": str(r["summary"] or "")[:VIEW_PREVIEW]},
                "entry": "decision", "round": r["round"],
                # A refused done counts as keep going (its why is on the review).
                "decision": "done" if r["decision"] == "done" else "keep_going"}))
    for w in team._rows(waits, order=waits.c.opened_at):
        s, d = w["subject"] or {}, w["decision"] or {}
        data = {"wait_id": w["wait_id"], "state": w["state"],
                **{k: s[k] for k in ("round", "member", "turn_no", "header") if k in s}}
        answer = d.get("answer") or d.get("recovery")
        if answer:
            data["answer"] = answer
        typed: dict[str, Any] = {"entry": "owner_wait",
                                 "wait_kind": WAIT_KIND_SHOWN.get(w["kind"], w["kind"])}
        if isinstance(s.get("round"), int):
            typed["round"] = s["round"]
        entries.append((_at(w["opened_at"]) or "", 3, {
            "event_type": f"owner wait: {w['kind']}", "from_agent": "temper",
            "to_agent": "owner", "timestamp": _at(w["opened_at"]), "data": data, **typed}))
    for a in answers:
        entries.append((a.get("timestamp") or "", 3.5, a))
    for t in turn_rows:
        entries.append((t.get("timestamp") or "", -1, t))
    stopped = team.stopped()
    if stopped:
        entries.append(("~", 4, {"event_type": "decision: stopped", "from_agent": "owner",
                                 "data": {"reason": stopped},
                                 "entry": "decision", "decision": "stopped"}))
    entries.sort(key=lambda e: (e[0], e[1]))
    return [e for _when, _order, e in entries]


# --- the node -------------------------------------------------------------------------------


def run_team_node(node: Any, input_data: dict, context: ExecutionContext) -> NodeResult:
    """A team stage's node: check again, open the team, drive it (TeamNode.run).

    Every way out writes the team's outcome (``pi_team_outcomes``, M3 E2/E3/E16, A2), the
    only record the Team page reads; ``structured_output`` carries a copy for the workflow's
    outputs. A stop at the pause or when the team had nothing left to do ends the node
    cancelled, not failed (E18): it was the owner's decision and nothing failed."""
    from temper_ai.database import get_database
    from temper_ai.pi_agent import end_cancelled_teams
    from temper_ai.pi_agent.team import member_name
    from temper_ai.pi_agent.team_check import check_team, load_box
    from temper_ai.pi_agent.team_config import load_team_config, trial_id_of
    from temper_ai.pi_agent.team_folders import folder_check, roots_of
    from temper_ai.pi_agent.team_outcome import cancel_record
    from temper_ai.runner.attempts import later_attempts, stand_down_if_replaced

    # A later attempt of the run has started: the team is its now (SW-84).
    stand_down_if_replaced(context.run_id, context.graph_event_id,
                           where="before its team step starts")
    started = time.monotonic()
    settings = node.settings.as_dict()
    host_path = context.step_path or (f"{context.node_path}.{node.name}" if context.node_path
                                      else node.name)
    trial_id = trial_id_of(context.workflow_name)
    if not in_pi_lane():
        # The backstop behind the lane mark and the claim filters (SW-42): nothing of the
        # team is opened or written outside the Pi lane.
        text = f"{OUTSIDE_PI_LANE}: this worker isn't the Pi lane, so the team did not start"
        return NodeResult(status=Status.FAILED, output=text, error=text,
                          duration_seconds=time.monotonic() - started,
                          metadata={"team": {"settings": settings}})
    ledger = Ledger(get_database().engine)
    try:
        ledger.ensure()
    except LedgerLayoutError as exc:  # SW-13: refuse a layout this build doesn't know,
        text = f"Pi refused this database: {exc}"  # writing nothing at all
        return NodeResult(status=Status.FAILED, output=text, error=text,
                          duration_seconds=time.monotonic() - started,
                          metadata={"team": {"settings": settings}})

    def outcome(decision: str, reason: str, **fields: Any) -> None:
        """The team's typed outcome; a record that could not be written is logged, never
        fails the run (the run's own status still tells how it ended)."""
        try:
            ledger.write_outcome(context.run_id, host_path, decision=decision, reason=reason,
                                 trial_id=trial_id, **fields)
        except Exception:  # noqa: BLE001 - the Team page's copy only
            logger.warning("team %s %s: its outcome could not be written", context.run_id,
                           host_path, exc_info=True)

    def began() -> bool:
        return ledger.any_turn_began(context.run_id, host_path)

    def failed(text: str, *, problems: list[str] | None = None, **extra: Any) -> NodeResult:
        decision = "failed" if began() else "didnt_start"
        outcome(decision, text, problems=problems or [])
        if problems:
            extra["problems"] = problems
        return NodeResult(status=Status.FAILED, output=text, error=text,
                          structured_output={"decision": decision, "reason": text},
                          duration_seconds=time.monotonic() - started,
                          metadata={"team": {"settings": settings, **extra}})

    goal = (input_data or {}).get("goal")
    if goal is not None and not isinstance(goal, str):
        goal = json.dumps(goal, sort_keys=True, default=str)
    # The run-start check never sees a resume or a fork (they run the workflow config as it is
    # now) nor a goal mapped from an earlier node: check again here, with the goal this node
    # was handed, before any member is set up (M2 binding). The project folder is checked
    # here for real, where the team's copies are made (M4 item 0): the server only sees it
    # when it is mounted there.
    box, box_problem = load_box()
    problems = check_team(node.members, settings, inputs={"goal": goal},
                          box=box, box_problem=box_problem)
    roots = roots_of(load_team_config().project_roots)
    if context.workspace_path:
        # The same check the Pi lane ran when it claimed the run (runner/pi_lane.py).
        start_commit = None
        if box is not None:
            start_commit = ProjectCopies.recorded(
                Path(box.state_root) / context.run_id / _slug(host_path)).get("commit")
        folder_problems, _notes = folder_check(str(context.workspace_path), roots,
                                               authoritative=True, fresh=not began(),
                                               start_commit=start_commit)
        problems += folder_problems
    if problems:
        # A3: before any turn of this team began it can't start; after, it can't go on.
        head = "the team can't go on: " if began() else "the team can't start: "
        return failed(head + "; ".join(problems), problems=problems)
    if context.event_recorder is None or box is None:
        return failed("the team needs the run's event recorder and the worker box config")
    # From here on the team and its owner waits record through the door (event_guard).
    context = guarded_context(context)
    end_cancelled_teams(ledger)  # G-a: a cancelled run's team the process died before ending
    members = [TeamMember(member_name(cfg), cfg) for cfg in node.members]
    attempt_id = context.graph_event_id or f"attempt-{uuid.uuid4().hex}"
    team = LeaderTeam(
        ledger, box, run_id=context.run_id, host_path=host_path, members=members,
        team_settings=settings, recorder=context.event_recorder, attempt_id=attempt_id,
        parent_event_id=context.parent_event_id, workflow=context.workflow_name,
        cancel_event=context.cancel_event, leader=node.settings.mode.leader,
        pause_after=node.settings.pause_after_rounds, goal=str(goal),
        # The run's one account, settled when the Pi lane claimed the run (ADR-M4-09).
        account=run_account(context.run_id),
        project=None)  # type: ignore[arg-type]
    team.project = ProjectCopies(team.root, context.workspace_path)
    refusal = team.open({"goal": goal, **(input_data or {})})
    if refusal:
        return failed(f"the team can't open: {refusal}")
    try:
        for name, row in team._member_rows().items():
            team.project.ensure(name, team._pdir(row))
    except CopyError as exc:
        return failed(f"the team's project copies could not be made: {exc}")
    team.post(team.leader, str(goal), sender="temper", sender_kind="temper", kind="goal",
              dedupe_key=f"{context.run_id}:{host_path}:brief")
    # Never a turn of an attempt that started after this one: that one is alive, and this
    # one stands down instead of taking its turns over.
    stand_down_if_replaced(context.run_id, context.graph_event_id,
                           where="before it takes its team's turns over")
    try:
        team.resume(newer_attempts=lambda: later_attempts(context.run_id,
                                                          context.graph_event_id))
    except TakeoverRefused as exc:
        # another attempt holds the team: its ending is that attempt's to write
        return NodeResult(status=Status.FAILED, output=str(exc), error=str(exc),
                          duration_seconds=time.monotonic() - started,
                          metadata={"team": {"settings": settings}})
    ledger.start_outcome(context.run_id, host_path, trial_id=trial_id)
    try:
        ended = team.drive(context)
    except ReplacedByLaterAttempt:
        raise  # the team's outcome is the newer attempt's to write (SW-84)
    except CancellationError:
        _write_cancelled(outcome, context.run_id, cancel_record)
        raise
    usage = team.usage()
    meta = {"team": {"settings": settings, "host_path": host_path, "outcome": ended.status,
                     "usage": usage}}
    spent: dict[str, Any] = {
        "cost_usd": float(usage["cost_usd"]), "total_tokens": int(usage["total_tokens"]),
        "duration_seconds": time.monotonic() - started, "metadata": meta}
    if ended.status == "done":
        record = dict(ended.record)
        _made, no_branch = team.done_version(record)
        if _made is not None and team_versions.withheld(_made):
            # Nothing of a version holding a login token leaves the run: not its file names.
            record["version"] = {**record["version"], "files": {},
                                 "withheld": dict(_made["scan"].get("rules") or {})}
        if trial_id and context.workspace_path and (record.get("version") or {}).get("commit"):
            if no_branch:
                from temper_ai.pi_agent.team_branch import branch_name

                record["branch"] = {"name": branch_name(trial_id), "made": False,
                                    "why": no_branch}
            else:
                record["branch"] = _trial_branch(team, record, trial_id,
                                                 str(context.workspace_path), roots, box)
        outcome("done", str(record.get("summary") or "done"), record=record)
        return NodeResult(status=Status.COMPLETED, output=str(record.get("summary") or ""),
                          structured_output=record, **spent)
    if ended.status == "cancelled":
        _write_cancelled(outcome, context.run_id, cancel_record)
        return NodeResult(status=Status.CANCELLED, output=ended.text, error=ended.text,
                          structured_output={"decision": "cancelled", "reason": ended.text},
                          **spent)
    if ended.status == "stopped":
        stop = team.stop_wait() or {}
        decided = stop.get("decision") or {}
        outcome("stopped", ended.text, owner_words=decided.get("words"),
                decided_by=decided.get("by"), by_source=decided.get("source"))
        status = Status.CANCELLED if stop_ends_cancelled(stop) else Status.FAILED
        return NodeResult(status=status, output=ended.text, error=ended.text,
                          structured_output={"decision": "stopped", "reason": ended.text},
                          **spent)
    # failed: red at member, team and stage level (R2 B13), never done
    if not ended.text.startswith("another attempt of this run"):
        outcome("failed" if began() else "didnt_start", ended.text)
    return NodeResult(status=Status.FAILED, output=ended.text, error=ended.text,
                      structured_output={"decision": ended.status, "reason": ended.text},
                      **spent)


def _write_cancelled(outcome: Any, run_id: str, cancel_record: Any) -> None:
    """The team ended because its run was cancelled: who cancelled it and their words, from
    the cancel's own record (the cancel route fills them in later when it isn't there yet)."""
    rec = cancel_record(run_id) or {}
    outcome("cancelled", "the run was cancelled", owner_words=rec.get("words"),
            decided_by=rec.get("caller"), by_source=rec.get("source"))


def _trial_branch(team: LeaderTeam, record: dict, trial_id: str, source: str, roots: Any,
                  box: Any) -> dict:
    """The trial's approved version as local branch ``team/<trial_id>`` in its source repo
    (M3 E10): through the host helper when one is configured, else in this process. Never
    fails the done team: a branch that wasn't made says why."""
    from temper_ai.pi_agent.team_branch import make_branch

    return make_branch(source=source, leader_git_dir=str(team.project.git_dir(team.leader)),
                       commit=str(record["version"]["commit"]), trial_id=trial_id, roots=roots,
                       helper_socket=getattr(box, "host_helper_socket", "") or "")
