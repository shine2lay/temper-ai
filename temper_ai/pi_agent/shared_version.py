"""A free-flowing team's one shared version (FLOW F3, with Architecture's R3 and S2).

Each member works in its own project copy (:class:`~temper_ai.pi_agent.team_leader.ProjectCopies`,
task #38), which is never reset. The team builds one shared version: a bare git repo at
``<team root>/git/_shared.git``. A member's work reaches it only through :meth:`SharedVersion.share`,
and other members' work reaches a member only through :meth:`SharedVersion.sync`.

What this module touches -- host git folders only, never a database, a box or a mount:

* the shared repo ``<team root>/git/_shared.git``: made by :meth:`~SharedVersion.ensure`, its
  ref ``refs/heads/team`` moved only by :meth:`~SharedVersion.share`;
* one member's copy -- its git folder ``<team root>/git/<member>.git`` and its working folder
  ``<member folder>/workspace`` -- written only by :meth:`~SharedVersion.sync` (before that
  member's turn) and :meth:`~SharedVersion.share` (after that member's turn has settled). The
  caller makes sure the member's box isn't running then, and holds the team lock
  (``ledger._team_tx``) around both. No other member's copy is ever touched.

The shared repo sits outside every member's folder, so no box mounts it; nothing here
changes what a box mounts. Its name starts with ``_`` because a member's name always starts
with a letter (``team_config.NAME_PATTERN``), so it can never be a member's copy, and it
still has the ``<run>/<team>/git/<name>.git`` shape the host helper accepts for the
Project's branch (``scripts/pi_host/temper_pi_host.py`` ``leader_problem``).

Merges and conflicts (R3). Members have no git, so Temper finishes every merge it starts:
on a conflict it records the unmerged paths from git's own list (``git ls-files -u``), then
commits the merge as it stands (``add -A`` + commit, git's markers left in the files), so no
copy is ever left half-merged. Each path is a :class:`Conflict` of kind ``markers`` (git put
its conflict markers in the file) or ``no_markers`` (binary, modify/delete, rename: git
left one side in place with nothing in the file to say so). The caller stores the open
conflicts with the member and passes them back in; the turn's framing names them
(:func:`conflict_lines`). A share is refused while a recorded ``markers`` path still holds
markers. For the ``no_markers`` kinds, the member's next share after it was told counts as
its choice.

Share order (S2). A share moves ``refs/heads/team`` with the expected old value, in one git
transaction with the new version's record (``refs/temper/versions/<n>``, an annotated tag
holding the version's facts), so a share that lost a race moves nothing and is merged again
against the newer shared version. Version numbers follow share order; version 0 is the
Project's start.

Everything is returned as plain results (:class:`Synced`, :class:`Shared`, :class:`Version`);
storing them -- the versions table, events, the member's open conflicts -- is the caller's.
Member notes go only into the version record in the shared repo, never into a commit
message, so nothing a member wrote leaves the run with the Project's branch except files,
which the version's token scan reads (team_versions.build).

Errors: git trouble raises :class:`VersionError` (the team fails red, as with the copies'
``CopyError``); the copies' own checks (a member's working folder that is a link) raise
their ``CopyError``.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from temper_ai.pi_agent.member_tree import MemberLink, member_entry, read_member_bytes
from temper_ai.pi_agent.team_folders import GIT, GIT_TIMEOUT, git_env

if TYPE_CHECKING:
    from temper_ai.pi_agent.team_leader import ProjectCopies

#: The shared repo's name in ``<team root>/git``: no member's name starts with ``_``.
SHARED_NAME = "_shared"
#: The shared version's ref in the shared repo.
BRANCH = "refs/heads/team"
#: One annotated tag per version, ``refs/temper/versions/000000`` on (zero-padded: in order).
VERSIONS = "refs/temper/versions/"
#: Where a member's commit lands in the shared repo before the shared ref is moved to it.
INCOMING = "refs/temper/incoming"
#: Where the shared version lands in a member's copy before it is merged. git labels a
#: conflict's sides with what was merged, so its markers read ``<<<<<<< HEAD`` (the member's
#: copy) and ``>>>>>>> team-version`` (the shared version).
SHARED_LABEL = "team-version"
SHARED_IN_COPY = f"refs/heads/{SHARED_LABEL}"

MARKERS = "markers"
NO_MARKERS = "no_markers"
CONFLICT_KINDS = (MARKERS, NO_MARKERS)
#: Merge results: what a sync or share did to the member's copy.
MERGES = ("up_to_date", "fast_forward", "merged", "conflict")
#: Share results.
SHARE_STATUSES = ("shared", "unchanged", "conflict", "refused")
#: A lost race on the shared ref is merged again this many times before the share is refused.
MAX_RACES = 5
#: The largest file read for conflict markers; past it the file counts as ``no_markers``.
MARKER_SCAN_BYTES = 64 * 1024 * 1024
MAX_NOTE = 1000
#: Paths named in a refusal's text (all of them stay in the conflicts list).
MAX_NAMED = 20

#: Merge settings fixed for every git call, on top of the copies' hardened git (GIT): no
#: reuse of recorded resolutions, no stash, no submodule recursion, standard markers.
_MERGE_CONFIG = ("-c", "rerere.enabled=false", "-c", "merge.autoStash=false", "-c",
                 "submodule.recurse=false", "-c", "merge.conflictStyle=merge", "-c",
                 "core.attributesFile=/dev/null", "-c", "merge.renames=true")
#: What git's unmerged stages say, by the stages present (1 base, 2 the member, 3 the team).
_SIDES = {
    frozenset({1, 2, 3}): "you and the team both changed it",
    frozenset({2, 3}): "you and the team both added it",
    frozenset({1, 2}): "you changed it, and the team deleted or moved it",
    frozenset({1, 3}): "the team changed it, and you deleted or moved it",
    frozenset({2}): "you added or moved it here, in a clash with the team's version",
    frozenset({3}): "the team added or moved it here, in a clash with your copy",
    frozenset({1}): "you and the team both moved or deleted it, in different ways",
}


class VersionError(Exception):
    """The shared version could not be made, read or moved: the team fails red."""


@dataclass(frozen=True)
class Conflict:
    """One path git couldn't merge, as recorded at a sync or a share.

    ``kind``: ``markers`` or ``no_markers``. ``sides``: what git's unmerged stages say, in
    plain words. ``in_copy``: whether the path is in the member's working folder after
    Temper finished the merge. ``told``: whether a turn's framing has named it to the
    member (set by :meth:`SharedVersion.sync`)."""

    path: str
    kind: str
    sides: str
    in_copy: bool
    told: bool = False

    def as_dict(self) -> dict:
        return {"path": self.path, "kind": self.kind, "sides": self.sides,
                "in_copy": self.in_copy, "told": self.told}

    @classmethod
    def from_dict(cls, data: dict) -> Conflict:
        kind = data.get("kind")
        return cls(path=str(data["path"]), kind=kind if kind in CONFLICT_KINDS else NO_MARKERS,
                   sides=str(data.get("sides") or ""), in_copy=bool(data.get("in_copy", True)),
                   told=bool(data.get("told", False)))


@dataclass(frozen=True)
class Version:
    """One shared version: ``version_no`` in share order (0 is the Project's start)."""

    version_no: int
    commit: str
    by: str | None
    at: str
    note: str | None
    files_changed: int
    files_total: int
    parent: str | None

    def as_dict(self) -> dict:
        return {"version_no": self.version_no, "commit": self.commit, "by": self.by,
                "at": self.at, "note": self.note, "files_changed": self.files_changed,
                "files_total": self.files_total, "parent": self.parent}


@dataclass(frozen=True)
class Synced:
    """What :meth:`SharedVersion.sync` did. ``conflicts``: every open conflict, all marked
    told -- store them with the member (they replace what was stored) and name them in the
    turn's framing (:func:`conflict_lines`)."""

    head: str
    shared: str
    kept_leftovers: bool
    merge: str
    conflicts: tuple[Conflict, ...]


@dataclass(frozen=True)
class Shared:
    """What :meth:`SharedVersion.share` did.

    ``status``: ``shared`` (``version`` is the new version), ``unchanged`` (nothing new: the
    shared version already holds the member's work), ``conflict`` (the merge with the shared
    version conflicted: Temper finished it in the member's copy, nothing was shared) or
    ``refused`` (nothing written: markers left, conflicts not yet named, or the shared
    version kept moving). ``text``: plain words for the member's notice. ``conflicts``: the
    member's open conflicts after this share -- store them (they replace what was stored)."""

    status: str
    text: str
    conflicts: tuple[Conflict, ...]
    version: Version | None = None
    head: str | None = None
    races: int = 0


def conflict_lines(conflicts: tuple[Conflict, ...] | list[Conflict]) -> list[str]:
    """One plain line per conflict, for a turn's framing."""
    out = []
    for c in conflicts:
        if c.kind == MARKERS:
            out.append(f"{c.path}: {c.sides}. git's conflict markers are in the file, "
                       "between <<<<<<< HEAD (your copy) and >>>>>>> team-version (the team's "
                       "version): edit it to what the team should have and remove every "
                       "marker. A share is refused while any are left.")
        else:
            where = ("your copy has it as git left it" if c.in_copy
                     else "it is not in your copy now")
            out.append(f"{c.path}: {c.sides}; {where}, with no markers to show it. Your next "
                       "share counts as your choice: change, restore or delete it first if the "
                       "team should have something else.")
    return out


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _one_line(text: str | None, limit: int = MAX_NOTE) -> str | None:
    line = " ".join(str(text or "").split())[:limit]
    return line or None


def _named(paths: list[str]) -> str:
    more = len(paths) - MAX_NAMED
    return ", ".join(paths[:MAX_NAMED]) + (f" and {more} more" if more > 0 else "")


def _has_markers(data: bytes) -> bool:
    """Whether the content holds a conflict marker line (``<<<<<<<`` or ``>>>>>>>``, any
    marker size)."""
    return any(line.startswith((b"<<<<<<<", b">>>>>>>")) for line in data.splitlines())


def _dedupe(conflicts: list[Conflict]) -> list[Conflict]:
    """One conflict per path; a later one replaces an earlier one, in first-seen order."""
    by_path: dict[str, Conflict] = {}
    for c in conflicts:
        by_path.pop(c.path, None)
        by_path[c.path] = c
    return list(by_path.values())


class SharedVersion:
    """The team's shared version, next to the members' copies (``project``)."""

    def __init__(self, project: ProjectCopies):
        self.project = project
        self.root = Path(project.root)
        self.path = self.root / "git" / f"{SHARED_NAME}.git"

    # --- git ------------------------------------------------------------------------------

    def _git(self, args: list[str], *, git_dir: Path | None = None,
             work_tree: Path | None = None, stdin: bytes | None = None,
             env: dict[str, str] | None = None, check: bool = True
             ) -> subprocess.CompletedProcess[bytes]:
        cmd = [*GIT, *_MERGE_CONFIG]
        if git_dir is not None:
            cmd.append(f"--git-dir={git_dir}")
        if work_tree is not None:
            cmd.append(f"--work-tree={work_tree}")
        cmd += args
        full_env = {**git_env(str(self.root)), **(env or {})}
        try:
            done = subprocess.run(cmd, cwd=str(work_tree or self.root), env=full_env,
                                  input=stdin, capture_output=True, timeout=GIT_TIMEOUT,
                                  check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VersionError(f"git {args[0]} could not run ({exc.__class__.__name__})") from None
        if check and done.returncode != 0:
            err = done.stderr.decode("utf-8", "replace").strip().splitlines()
            raise VersionError(f"git {args[0]} failed: {(err[-1] if err else '')[:200]}")
        return done

    def _out(self, args: list[str], **kw: Any) -> str:
        return self._git(args, **kw).stdout.decode("utf-8", "replace").strip()

    def _rev(self, ref: str, git_dir: Path) -> str | None:
        done = self._git(["rev-parse", "--verify", "-q", f"{ref}^{{commit}}"],
                         git_dir=git_dir, check=False)
        sha = done.stdout.decode().strip()
        return sha if done.returncode == 0 and sha else None

    def _copy(self, member: str, pdir: Path) -> tuple[Path, Path]:
        """The member's git folder and its working folder (checked: no link, SW-51)."""
        gd = self.project.git_dir(member)
        if not (gd / "HEAD").exists():
            raise VersionError(f"{member} has no project copy yet")
        return gd, self.project.checked_worktree(pdir)

    def _count(self, args: list[str], git_dir: Path) -> int:
        return len([e for e in self._git(args, git_dir=git_dir).stdout.split(b"\0") if e])

    # --- the shared repo ------------------------------------------------------------------

    def ensure(self) -> Version:
        """Make the shared repo once, seeded with the Project's start commit (or, for a
        Project that starts empty, an empty commit), as version 0. Returns the latest
        version; an existing shared repo is never changed."""
        if (self.path / "HEAD").exists() and self._rev(BRANCH, self.path):
            return self.head()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not (self.path / "HEAD").exists():
            self._git(["init", "-q", "--bare", "--template=", "--initial-branch=team",
                       str(self.path)])
        rec = self.project.record()
        if rec.get("commit"):
            # Committed content only, through git's own transfer, as the copies were made.
            self._git(["fetch", "-q", "--no-tags", "--no-recurse-submodules",
                       "--no-write-fetch-head", rec["source"], f"+{rec['commit']}:{INCOMING}"],
                      git_dir=self.path)
            seed = str(rec["commit"])
        else:
            tree = self._out(["mktree"], git_dir=self.path, stdin=b"")
            seed = self._out(["commit-tree", tree, "-m", "Temper: the team's project starts empty"],
                             git_dir=self.path)
        total = self._count(["ls-tree", "-r", "-z", "--full-tree", "--name-only", seed],
                            self.path)
        start = Version(version_no=0, commit=seed, by=None, at=_now(), note="the Project's start",
                        files_changed=0, files_total=total, parent=None)
        tag = self._tag(start)
        made = self._git(["update-ref", "--stdin"], git_dir=self.path, check=False,
                         stdin=(f"create {BRANCH} {seed}\n"
                                f"create {VERSIONS}{0:06d} {tag}\n").encode())
        if made.returncode != 0 and not self._rev(BRANCH, self.path):
            err = made.stderr.decode("utf-8", "replace").strip().splitlines()
            raise VersionError(f"the shared version could not be started: "
                               f"{(err[-1] if err else '')[:200]}")
        return self.head()

    def _tag(self, v: Version) -> str:
        """An annotated tag object on ``v.commit`` holding the version's facts (one JSON line)."""
        facts = {k: val for k, val in v.as_dict().items() if k != "commit"}
        when = int(datetime.fromisoformat(v.at).timestamp())
        body = (f"object {v.commit}\ntype commit\ntag v{v.version_no}\n"
                f"tagger Temper <temper@localhost> {when} +0000\n\n"
                f"{json.dumps(facts, sort_keys=True)}\n")
        return self._out(["mktag"], git_dir=self.path, stdin=body.encode())

    def versions(self) -> list[Version]:
        """Every shared version, in share order (version 0 first)."""
        out = self._git(["for-each-ref", "--sort=refname",
                         "--format=%(*objectname)%00%(contents:subject)", VERSIONS],
                        git_dir=self.path).stdout.decode("utf-8", "replace")
        found = []
        for line in out.splitlines():
            commit, _, subject = line.partition("\0")
            try:
                facts = json.loads(subject)
            except ValueError:
                raise VersionError("a shared version's record can't be read") from None
            found.append(Version(version_no=int(facts["version_no"]), commit=commit,
                                 by=facts.get("by"), at=str(facts.get("at")),
                                 note=facts.get("note"),
                                 files_changed=int(facts.get("files_changed") or 0),
                                 files_total=int(facts.get("files_total") or 0),
                                 parent=facts.get("parent")))
        return found

    def head(self) -> Version:
        """The latest shared version: its commit is what the shared ref points at -- the
        done record's version and the Project branch's commit."""
        sha = self._rev(BRANCH, self.path)
        if not sha:
            raise VersionError("the team has no shared version yet")
        found = self.versions()
        if not found or found[-1].commit != sha:
            raise VersionError(f"the shared version {sha[:12]} has no record; it was moved "
                               "outside Temper")
        return found[-1]

    # --- merging into a member's copy -----------------------------------------------------

    def _commit_all(self, gd: Path, wt: Path, message: str) -> bool:
        """Commit everything in the member's working folder; False when there was nothing."""
        status = self._git(["status", "--porcelain", "--untracked-files=all"],
                           git_dir=gd, work_tree=wt).stdout
        if not status.strip():
            return False
        self._git(["add", "-A"], git_dir=gd, work_tree=wt)
        self._git(["commit", "-q", "--no-verify", "-m", message], git_dir=gd, work_tree=wt)
        return True

    def _unmerged(self, gd: Path, wt: Path) -> list[Conflict]:
        """The paths git couldn't merge (``ls-files -u``), each classified from the file."""
        raw = self._git(["ls-files", "-u", "-z"], git_dir=gd, work_tree=wt).stdout
        stages: dict[str, set[int]] = {}
        for entry in raw.split(b"\0"):
            if not entry:
                continue
            meta, _, path = entry.partition(b"\t")
            stages.setdefault(path.decode("utf-8", "replace"), set()).add(int(meta.split()[2]))
        return [self._classify(wt, path, frozenset(st)) for path, st in stages.items()]

    def _classify(self, wt: Path, path: str, stages: frozenset[int]) -> Conflict:
        sides = _SIDES.get(stages, "git could not merge it")
        entry = member_entry(wt, path)
        markers = False
        if entry == "file":
            try:
                markers = _has_markers(read_member_bytes(wt, path, limit=MARKER_SCAN_BYTES))
            except (MemberLink, OSError):
                markers = False
        return Conflict(path=path, kind=MARKERS if markers else NO_MARKERS, sides=sides,
                        in_copy=entry != "missing")

    def _markers_left(self, wt: Path, path: str) -> bool:
        if member_entry(wt, path) != "file":
            return False
        try:
            return _has_markers(read_member_bytes(wt, path, limit=MARKER_SCAN_BYTES))
        except (MemberLink, OSError):
            return False

    def _finish(self, member: str, gd: Path, wt: Path, why: str) -> list[Conflict]:
        """Finish a merge git stopped in the member's copy: record the unmerged paths, then
        commit everything as it stands, markers and all."""
        found = self._unmerged(gd, wt)
        self._git(["add", "-A"], git_dir=gd, work_tree=wt)
        self._git(["commit", "-q", "--no-verify", "-m",
                   f"Temper: {member} takes in the team's shared version ({why}; "
                   f"{len(found)} conflict(s) left for {member})"], git_dir=gd, work_tree=wt)
        return found

    def _finish_pending(self, member: str, gd: Path, wt: Path) -> list[Conflict]:
        """A merge an earlier, interrupted call left open is finished first."""
        if not (gd / "MERGE_HEAD").exists():
            return []
        return self._finish(member, gd, wt, "an interrupted merge, finished")

    def _fetch_shared(self, gd: Path) -> str:
        self._git(["fetch", "-q", "--no-tags", "--no-recurse-submodules",
                   "--no-write-fetch-head", str(self.path), f"+{BRANCH}:{SHARED_IN_COPY}"],
                  git_dir=gd)
        sha = self._rev(SHARED_IN_COPY, gd)
        if not sha:
            raise VersionError("the shared version could not be fetched")
        return sha

    def _merge(self, member: str, gd: Path, wt: Path, shared: str) -> tuple[str, list[Conflict]]:
        """Merge the shared commit (just fetched to ``SHARED_IN_COPY``) into the member's
        committed, clean copy. Unrelated histories are allowed because a Project that starts
        empty gives every copy its own empty first commit."""
        before = self._rev("HEAD", gd)
        if self._rev(SHARED_IN_COPY, gd) != shared:
            raise VersionError("the shared version moved in the member's copy during a merge")
        # git labels the shared side of a conflict with the name merged; the full ref is
        # merged instead if the short name ever meant something else in the copy.
        name = SHARED_LABEL if self._rev(SHARED_LABEL, gd) == shared else SHARED_IN_COPY
        done = self._git(["merge", "-q", "--no-edit", "--no-verify", "--no-stat",
                          "--allow-unrelated-histories", "-m",
                          f"Temper: {member} takes in the team's shared version", name],
                         git_dir=gd, work_tree=wt, check=False)
        if done.returncode != 0:
            if not (gd / "MERGE_HEAD").exists():
                err = done.stderr.decode("utf-8", "replace").strip().splitlines()
                raise VersionError(f"git merge failed: {(err[-1] if err else '')[:200]}")
            return "conflict", self._finish(member, gd, wt, "with conflicts")
        after = self._rev("HEAD", gd)
        if after == before:
            return "up_to_date", []
        return ("fast_forward" if after == shared else "merged"), []

    # --- sync and share -------------------------------------------------------------------

    def sync(self, member: str, pdir: Path, recorded: tuple[Conflict, ...] | list[Conflict] = ()
             ) -> Synced:
        """Before the member's turn: commit what it left in its copy, so nothing is lost,
        then merge the shared version into it. ``recorded``: its stored open conflicts.

        Returns every open conflict marked told, because the turn about to start names them:
        recorded ones still open (a ``markers`` path whose markers are gone is settled), plus
        any this merge left."""
        self.ensure()
        gd, wt = self._copy(member, pdir)
        found = self._finish_pending(member, gd, wt)
        kept = self._commit_all(gd, wt, f"Temper: {member}'s work, kept before its next turn")
        shared = self._fetch_shared(gd)
        merge, new = self._merge(member, gd, wt, shared)
        still = [c for c in recorded if c.kind != MARKERS or self._markers_left(wt, c.path)]
        open_ = tuple(replace(c, told=True) for c in _dedupe([*still, *found, *new]))
        return Synced(head=self._rev("HEAD", gd) or "", shared=shared, kept_leftovers=kept,
                      merge=merge, conflicts=open_)

    def share(self, member: str, pdir: Path, recorded: tuple[Conflict, ...] | list[Conflict] = (),
              note: str | None = None) -> Shared:
        """After the member's turn has settled: commit its copy, merge the shared version
        into it and, when that merge is clean, make the result the shared version.
        ``recorded``: its stored open conflicts; ``note``: its share note (token-scanned by
        the caller when the act was recorded)."""
        self.ensure()
        gd, wt = self._copy(member, pdir)
        recorded = tuple(recorded)
        pending = self._finish_pending(member, gd, wt)
        if pending:
            return Shared("conflict", "Your share did not reach the team's version: an "
                          "interrupted merge in your copy left conflicts. They are named at "
                          "your next turn; fix them and share again.",
                          tuple(_dedupe([*recorded, *pending])))
        untold = [c.path for c in recorded if not c.told]
        if untold:
            return Shared("refused", "Not shared: Temper found conflicts in your copy that you "
                          f"haven't been shown yet ({_named(untold)}). They are named at your "
                          "next turn; look at them, then share again.", recorded)
        left = [c.path for c in recorded if c.kind == MARKERS and self._markers_left(wt, c.path)]
        if left:
            return Shared("refused", "Not shared: these files still hold git's conflict markers: "
                          f"{_named(left)}. Remove the markers and share again.", recorded)
        # Every recorded conflict is settled now: the markers are gone, and for the others
        # this share is the member's choice.
        self._commit_all(gd, wt, f"Temper: {member}'s work, shared")
        for races in range(MAX_RACES):
            old = self._fetch_shared(gd)
            merge, new = self._merge(member, gd, wt, old)
            head = self._rev("HEAD", gd) or ""
            if new:
                return Shared("conflict", "Your share did not reach the team's version: merging "
                              f"it with the team's version gave {len(new)} conflict(s). Temper "
                              "finished the merge in your copy; the files are named at your "
                              "next turn. Fix them and share again.", tuple(new), head=head,
                              races=races)
            if head == old:
                return Shared("unchanged", "Nothing new to share: the team's version already "
                              "holds your work.", (), head=head, races=races)
            version = self._move(member, gd, old, head, _one_line(note))
            if version is not None:
                return Shared("shared", f"Shared as team version {version.version_no} "
                              f"({head[:12]}, {version.files_changed} file(s) changed).", (),
                              version=version, head=head, races=races)
        return Shared("refused", "Not shared: the team's version kept changing while Temper "
                      "merged yours. Share again.", (), head=self._rev("HEAD", gd),
                      races=MAX_RACES)

    def _move(self, member: str, gd: Path, old: str, new: str, note: str | None
              ) -> Version | None:
        """Make ``new`` (the member's merged commit) the shared version, if the shared ref is
        still at ``old`` (S2): the ref and the version record move in one transaction. None
        when another share moved it first (nothing written)."""
        self._git(["fetch", "-q", "--no-tags", "--no-recurse-submodules",
                   "--no-write-fetch-head", str(gd), f"+HEAD:{INCOMING}"], git_dir=self.path)
        if self._rev(INCOMING, self.path) != new:
            raise VersionError(f"{member}'s commit did not reach the shared version")
        found = self.versions()
        number = (found[-1].version_no + 1) if found else 1
        version = Version(
            version_no=number, commit=new, by=member, at=_now(), note=note,
            files_changed=self._count(["diff", "--name-only", "-z", "--no-renames", old, new],
                                      self.path),
            files_total=self._count(["ls-tree", "-r", "-z", "--full-tree", "--name-only", new],
                                    self.path),
            parent=old)
        tag = self._tag(version)
        moved = self._git(["update-ref", "--stdin"], git_dir=self.path, check=False,
                          stdin=(f"update {BRANCH} {new} {old}\n"
                                 f"create {VERSIONS}{number:06d} {tag}\n").encode())
        if moved.returncode == 0:
            return version
        if self._rev(BRANCH, self.path) != old:
            return None  # lost the race: nothing moved
        err = moved.stderr.decode("utf-8", "replace").strip().splitlines()
        raise VersionError(f"the shared version could not be moved: {(err[-1] if err else '')[:200]}")
