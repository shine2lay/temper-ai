"""A team's version records (M4 ADR-M4-12 H, SW-36): what team_version serves.

The members' copies live only in the Pi lane, so pi-worker writes a record of each version
there: when the leader makes a version (asks for a review: ``review``) and when the team is
done (``done``, the reviewed version that was decided done). A record holds the version's
commit, the start commit, every file with its sha256 (the first ``MAX_FILES``) and the diff
against the start commit, cut at :data:`MAX_DIFF_BYTES` with a note saying so and where the
whole diff is.

Before a record is stored, everything the version would bring out of the run -- the diff, the
file names and the whole content of every added or changed file -- is scanned for login
tokens (SW-52, token_scan.py). A hit stores no files and no diff, only which rules matched in
which files; the trial's branch is then not made either.

The server serves the newest record from the table (``GET /api/team/runs/{id}/version``); it
never reads a copy.
"""

from __future__ import annotations

import hashlib
from typing import Any

import sqlalchemy as sa

from temper_ai.pi_agent import token_scan
from temper_ai.pi_agent.ledger import _now, versions

#: The diff a record keeps, in bytes; past it the record says it was cut.
MAX_DIFF_BYTES = 200_000
#: review: asked for review (old round teams); share: a free-flowing member's share into the
#: team's shared version; done: the team's done version.
KINDS = ("review", "share", "done")
#: The record's columns that hold the version itself (the rest say whose and when).
CONTENT = ("commit_sha", "start_commit", "files", "files_total", "diff", "diff_bytes",
           "truncated", "note", "scan")


def _file_entry(path: str, digest: str) -> dict:
    if ":" in digest:  # a submodule's commit or another non-file entry: ``kind:object id``
        kind, _, oid = digest.partition(":")
        return {"path": path, "sha256": None, "kind": kind, "object": oid}
    return {"path": path, "sha256": digest}


def build(project: Any, member: str, sha: str, *, files: dict[str, str] | None = None,
          files_total: int | None = None) -> dict:
    """A version record's content, read from ``member``'s copy at commit ``sha``
    (``project``: team_leader.ProjectCopies). Raises CopyError when the copy can't be read."""
    if files is None:
        files, files_total = project.files(member, sha)
    start = project.record().get("commit")
    base = project.diff_base(member, sha)
    diff = project.diff(member, base, sha)
    hits = token_scan.scan_all(
        [("the file names", "\n".join(files))]
        + [(f"file {path}", data) for path, data in project.changed_blobs(member, base, sha)]
        + [("the diff", diff)])
    record: dict[str, Any] = {"commit_sha": sha, "start_commit": start,
                              "files_total": int(files_total or len(files)),
                              "diff_bytes": len(diff)}
    if hits:
        return {**record, "files": [], "diff": "", "truncated": False, "scan": hits.record(),
                "note": f"withheld: this version holds {hits.words()}; none of its files or "
                        "diff was stored, and no branch is made from it"}
    truncated = len(diff) > MAX_DIFF_BYTES
    note = None
    if truncated:
        note = (f"the diff is cut at {MAX_DIFF_BYTES} of {len(diff)} bytes; the whole diff is "
                "on the trial's branch once the team is done, or in the leader's kept copy "
                f"(git diff {base[:12]} {sha[:12]})")
    return {**record, "files": [_file_entry(p, d) for p, d in files.items()],
            "diff": diff[:MAX_DIFF_BYTES].decode("utf-8", "replace"), "truncated": truncated,
            "note": note, "scan": None}


def _version_id(run_id: str, host_path: str, kind: str, key: str) -> str:
    return hashlib.sha256(f"{run_id}\0{host_path}\0{kind}\0{key}".encode()).hexdigest()[:32]


def store(conn: Any, *, run_id: str, host_path: str, kind: str, record: dict,
          act_id: str | None = None, review_id: str | None = None,
          round_no: int | None = None, member: str | None = None) -> str:
    """Store a version record once (in the caller's transaction): the same review's record,
    or the team's done record, stored again is a no-op. Returns its id."""
    if kind not in KINDS:
        raise ValueError(f"unknown version kind {kind!r}")
    vid = _version_id(run_id, host_path, kind, act_id or review_id or "")
    if conn.execute(sa.select(versions.c.version_id).where(
            versions.c.version_id == vid)).first() is not None:
        return vid
    seq = (conn.execute(sa.select(sa.func.max(versions.c.seq)).where(
        versions.c.run_id == run_id, versions.c.host_path == host_path)).scalar() or 0) + 1
    conn.execute(versions.insert().values(
        version_id=vid, run_id=run_id, host_path=host_path, seq=seq, kind=kind, act_id=act_id,
        review_id=review_id, round=round_no, member=member, created_at=_now(),
        **{k: record.get(k) for k in CONTENT}))
    return vid


def of_review(conn: Any, run_id: str, host_path: str, review_id: str) -> dict | None:
    """The record made when the review was asked for, or None."""
    row = conn.execute(sa.select(versions).where(
        versions.c.run_id == run_id, versions.c.host_path == host_path,
        versions.c.kind == "review", versions.c.review_id == review_id)).mappings().first()
    return dict(row) if row else None


def latest(engine: Any, run_id: str, host_path: str) -> dict | None:
    """The team's newest version record, or None."""
    with engine.connect() as conn:
        row = conn.execute(sa.select(versions).where(
            versions.c.run_id == run_id, versions.c.host_path == host_path).order_by(
            versions.c.seq.desc()).limit(1)).mappings().first()
    return dict(row) if row else None


def of_share(ledger: Any, run_id: str, host_path: str, version_no: int) -> dict | None:
    """A particular shared version, by the share event's version number (not table seq)."""
    event = next((e for e in ledger.events_after(run_id, host_path, 0, 100_000)
                  if e["kind"] == "share"
                  and (e["data"] or {}).get("version_no") == version_no), None)
    if event is None:
        return None
    with ledger.engine.connect() as conn:
        row = conn.execute(sa.select(versions).where(
            versions.c.run_id == run_id, versions.c.host_path == host_path,
            versions.c.kind == "share",
            versions.c.act_id == event["data"].get("act_id"))).mappings().first()
    return dict(row) if row else None


def withheld(record: dict | None) -> bool:
    """True when the token scan refused the version: nothing of it may leave the run."""
    return bool(((record or {}).get("scan") or {}).get("refused"))


def view(row: dict, branch: Any = None) -> dict:
    """team_version's answer (M3 contract, as amended: the stored record, the diff capped)."""
    return {
        "commit": row["commit_sha"], "start_commit": row["start_commit"], "kind": row["kind"],
        **({"review_id": row["review_id"], "round": row["round"]}
           if row["review_id"] is not None or row["round"] is not None else {}),
        "made_by": row["member"],
        "files": list(row["files"] or []), "files_total": row["files_total"],
        "diff": row["diff"], "diff_bytes": row["diff_bytes"], "truncated": row["truncated"],
        "note": row["note"],
        "withheld": ({"rules": row["scan"].get("rules"), "paths": row["scan"].get("paths")}
                     if withheld(row) else None),
        "branch": branch, "made_at": row["created_at"],
    }
