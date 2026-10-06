"""A member's own trees (M4 ADR-M4-08): its role snapshot (SW-25) and Temper's reads of what the
member writes (SW-51). No model and no container: folders in pytest's tmp dir, a private SQLite
ledger, and one child process that dies mid-copy.

SW-25, as the checklist words it: the role folder is copied to a temporary folder next to the
target; the source before copying, the source after and the copy must have one digest, else
the copy is made once more and then refused; it is renamed into place in one step and its
digest recorded on the participant row. Links are never followed: one pointing inside the role
folder is kept as a link, one pointing outside refuses the snapshot, naming it. A crash
mid-copy leaves nothing reusable: the next prepare removes the temporary folder and copies
afresh. (In M1's live run Design's real folder changed mid-run: L4-F4.)

SW-51: a read of a member-written tree never follows a link out of it -- links to /etc and to
another member's folder are planted at each reader.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from temper_ai.llm.pi_stream import Redactor
from temper_ai.pi_agent import member_tree as mt
from temper_ai.pi_agent.box import (
    MEMBER_GUIDANCE,
    BoxError,
    WorkerBox,
    check_session,
    session_started,
)
from temper_ai.pi_agent.host import prepare_participant
from temper_ai.pi_agent.ledger import Ledger
from temper_ai.pi_agent.member_tree import (
    MemberLink,
    SnapshotRefused,
    leftovers,
    list_member_dir,
    member_entry,
    member_file_sha256,
    read_member_text,
    replace_snapshot,
    take_snapshot,
    tree_digest,
    write_member_file,
)
from temper_ai.pi_agent.turn import TurnRequest, run_turn
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox

REPO = Path(__file__).resolve().parents[2]
WHAT = "role folder 'scout'"
NOTEBOOK = "## Check\nThe check word is plum.\n"


def make_role(root: Path, name: str = "scout") -> Path:
    """A role folder as a role's memory holds it: identity, about page, notebook, notes and a
    skill -- enough files that a copy can die halfway."""
    role = root / "identities" / name
    (role / "notes").mkdir(parents=True)
    (role / "skills" / "check").mkdir(parents=True)
    (role / "identity.json").write_text(json.dumps({"id": name, "title": name.title()}))
    (role / "about.md").write_text(f"# {name}\n")
    (role / "notebook.md").write_text(NOTEBOOK)
    for i in range(4):
        (role / "notes" / f"n{i}.md").write_text(f"note {i}\n")
    (role / "skills" / "check" / "SKILL.md").write_text("---\nname: check\n---\nSteps.\n")
    return role


def snapshot_at(pdir: Path, role: str = "scout") -> Path:
    return pdir / "memory" / "identities" / role


@pytest.fixture
def led(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'ledger.db'}")
    ledger = Ledger(engine)
    ledger.ensure()
    yield ledger
    engine.dispose()


@pytest.fixture
def member(tmp_path, led):
    """A participant row, its folder and a stand-in box config naming the role folders."""
    src = make_role(tmp_path / "roles")
    part, created = led.attach_participant("run-1", "talk", "scout", role="scout",
                                           session_root=str(tmp_path / "state"),
                                           pin={"model": "m"}, attempt_id="a1")
    assert created
    pdir = Path(part["session_dir"]).parent
    return SimpleNamespace(src=src, part=part, pdir=pdir, dst=snapshot_at(pdir),
                           box=SimpleNamespace(identities_dir=str(src.parent)),
                           cfg={"role": "scout"})


def _files(folder: Path) -> dict[str, str]:
    return {str(p.relative_to(folder)): p.read_text() for p in sorted(folder.rglob("*"))
            if p.is_file() and not p.is_symlink()}


# --- SW-25: the snapshot ---------------------------------------------------------------------


def test_sw25_the_snapshot_is_an_exact_copy_put_in_place_by_one_rename(tmp_path, monkeypatch):
    src = make_role(tmp_path)
    dst = snapshot_at(tmp_path / "p")
    renames: list[tuple[Path, Path]] = []
    real_rename = os.rename

    def rename(a, b):
        renames.append((Path(a), Path(b)))
        return real_rename(a, b)

    monkeypatch.setattr(mt.os, "rename", rename)
    digest = take_snapshot(src, dst, what=WHAT)
    ((tmp, into),) = renames
    assert into == dst and tmp.parent == dst.parent and tmp.name.startswith(".scout.partial-")
    assert _files(dst) == _files(src)
    assert digest == tree_digest(src) == tree_digest(dst)
    assert leftovers(dst) == []
    with pytest.raises(SnapshotRefused, match="snapshot is already in place"):
        take_snapshot(src, dst, what=WHAT)


CRASH = """
import os, sys
from pathlib import Path
from temper_ai.pi_agent import member_tree as mt

real, copied = mt._copy_file, []

def dies_mid_copy(src, dst):
    real(src, dst)
    copied.append(dst)
    if len(copied) == 2:
        os._exit(9)  # no clean-up at all: what a power cut or an OOM kill leaves

mt._copy_file = dies_mid_copy
mt.take_snapshot(Path(sys.argv[1]), Path(sys.argv[2]), what="role folder 'scout'")
"""


def test_sw25_a_crash_mid_copy_leaves_no_reusable_partial(member, led):
    """The process dies after two files: nothing is in place, only a temporary folder, which
    is never used as the snapshot -- the next prepare removes it and copies afresh."""
    died = subprocess.run([sys.executable, "-c", CRASH, str(member.src), str(member.dst)],
                          cwd=REPO, env={**os.environ, "PYTHONPATH": str(REPO)},
                          capture_output=True, text=True, timeout=120)
    assert died.returncode == 9, died.stderr[-2000:]
    assert not os.path.lexists(member.dst)
    (partial,) = leftovers(member.dst)
    assert partial.name.startswith(".scout.partial-")
    assert len([p for p in partial.rglob("*") if p.is_file()]) == 2  # half a copy

    digest = prepare_participant(member.box, member.pdir, member.cfg, {}, ledger=led,
                                 participant=member.part)
    assert leftovers(member.dst) == [] and not partial.exists()
    assert _files(member.dst) == _files(member.src)
    assert digest == tree_digest(member.src) == tree_digest(member.dst)
    assert led.participant(member.part["participant_id"])["snapshot_sha256"] == digest


def test_sw25_a_snapshot_put_in_place_but_never_recorded_is_taken_again(member, led):
    """A crash after the rename but before the digest reached the row: the copy in place is not
    on record, so the next prepare throws it away and copies afresh (no turn ran on it)."""
    take_snapshot(member.src, member.dst, what=WHAT)
    (member.dst / "stray.md").write_text("left by the attempt that died\n")
    (member.src / "notebook.md").write_text(NOTEBOOK + "A rule added since.\n")

    digest = prepare_participant(member.box, member.pdir, member.cfg, {}, ledger=led,
                                 participant=member.part)
    assert not (member.dst / "stray.md").exists()
    assert _files(member.dst) == _files(member.src)
    assert led.participant(member.part["participant_id"])["snapshot_sha256"] == digest \
        == tree_digest(member.src)


@pytest.mark.parametrize("change", ["edit", "add", "remove"])
def test_sw25_a_source_changing_mid_copy_is_copied_again_then_refused(tmp_path, monkeypatch,
                                                                      change):
    src = make_role(tmp_path)
    dst = snapshot_at(tmp_path / "p")
    real, changes = mt._copy_file, []

    def someone_writes_while_copying(s, d):
        real(s, d)
        if s.endswith("notebook.md"):  # each attempt copies the notebook once
            changes.append(s)
            n = len(changes)
            if change == "edit":
                (src / "notebook.md").write_text(f"{NOTEBOOK}edit {n}\n")
            elif change == "add":
                (src / "notes" / f"new-{n}.md").write_text("a new note\n")
            else:
                (src / "notes" / f"n{n}.md").unlink()

    monkeypatch.setattr(mt, "_copy_file", someone_writes_while_copying)
    with pytest.raises(SnapshotRefused) as refused:
        take_snapshot(src, dst, what=WHAT)
    assert str(refused.value) == (
        "the role folder 'scout' kept changing while Temper copied it (twice); nothing was put "
        "in place. Try again once nothing is writing to it")
    assert len(changes) == 2  # copied twice, never a third time
    assert not os.path.lexists(dst) and leftovers(dst) == []


def test_sw25_a_source_that_changed_once_is_copied_again_and_the_second_copy_kept(tmp_path,
                                                                                monkeypatch):
    src = make_role(tmp_path)
    dst = snapshot_at(tmp_path / "p")
    real, copies = mt._copy_file, []

    def edited_during_the_first_copy(s, d):
        real(s, d)
        if s.endswith("notebook.md"):
            copies.append(s)
            if len(copies) == 1:
                (src / "notebook.md").write_text(NOTEBOOK + "The owner's new rule.\n")

    monkeypatch.setattr(mt, "_copy_file", edited_during_the_first_copy)
    digest = take_snapshot(src, dst, what=WHAT)
    assert len(copies) == 2
    assert (dst / "notebook.md").read_text() == NOTEBOOK + "The owner's new rule.\n"
    assert digest == tree_digest(src) == tree_digest(dst) and leftovers(dst) == []


def test_sw25_a_link_inside_the_role_folder_is_kept_as_a_link(tmp_path):
    src = make_role(tmp_path)
    os.symlink("notes/n1.md", src / "latest.md")            # a file inside
    os.symlink("../notes", src / "skills" / "notes")        # a folder inside, up and back down
    os.symlink("not-yet.md", src / "dangling.md")           # nothing yet, but inside
    dst = snapshot_at(tmp_path / "p")
    digest = take_snapshot(src, dst, what=WHAT)
    for rel, target in (("latest.md", "notes/n1.md"), ("skills/notes", "../notes"),
                        ("dangling.md", "not-yet.md")):
        assert os.path.islink(dst / rel) and os.readlink(dst / rel) == target, rel
    # the copy's links point into the copy, never back at the role's real folder
    assert (dst / "latest.md").resolve() == (dst / "notes" / "n1.md").resolve()
    assert digest == tree_digest(src) == tree_digest(dst)


@pytest.mark.parametrize("plant", ["etc", "absolute_into_itself", "up_and_out", "other_member",
                                   "chain"])
def test_sw25_a_link_pointing_outside_the_role_folder_refuses_the_snapshot_naming_it(
        member, led, plant):
    other = make_role(member.src.parent.parent / "elsewhere", "design")  # another role's folder
    their_pdir = member.pdir.parent / "p-theirs"
    (their_pdir / "workspace").mkdir(parents=True)
    links = {
        "etc": ("notes/passwd", "/etc/passwd"),
        # absolute, even into the folder itself: in the copy it would lead back to the live folder
        "absolute_into_itself": ("rules.md", str(member.src / "notebook.md")),
        "up_and_out": ("notes/theirs.md", "../../../elsewhere/identities/design/notebook.md"),
        "other_member": ("workspace", str(their_pdir / "workspace")),
        "chain": ("a.md", "b.md"),  # inside, but b.md leads out
    }
    rel, target = links[plant]
    os.symlink(target, member.src / rel)
    if plant == "chain":
        os.symlink("/etc/hostname", member.src / "b.md")
    with pytest.raises(SnapshotRefused) as refused:
        prepare_participant(member.box, member.pdir, member.cfg, {}, ledger=led,
                            participant=member.part)
    text = str(refused.value)
    if plant == "chain":
        assert text.startswith("the role folder 'scout' has a link 'a.md' pointing outside it "
                               "('b.md')") or text.startswith(
            "the role folder 'scout' has a link 'b.md' pointing outside it ('/etc/hostname')")
    else:
        assert text.startswith(f"the role folder 'scout' has a link {rel!r} pointing outside it "
                               f"({target!r}); Temper never follows links out of a role folder")
    assert text.endswith("Remove the link or point it inside the folder")
    # nothing in place, nothing half made, nothing on record, nothing touched
    assert not os.path.lexists(member.dst) and leftovers(member.dst) == []
    assert led.participant(member.part["participant_id"])["snapshot_sha256"] is None
    assert _files(other)["notebook.md"] == NOTEBOOK and list((their_pdir / "workspace").iterdir()) == []


def test_sw25_a_special_file_in_the_role_folder_refuses_the_snapshot(tmp_path):
    src = make_role(tmp_path)
    os.mkfifo(src / "pipe")
    dst = snapshot_at(tmp_path / "p")
    with pytest.raises(SnapshotRefused, match="'pipe', which is not a file, folder or link"):
        take_snapshot(src, dst, what=WHAT)
    assert not os.path.lexists(dst) and leftovers(dst) == []


@pytest.mark.parametrize("what_src", ["missing", "link", "file"])
def test_sw25_only_a_real_role_folder_is_snapshotted(tmp_path, what_src):
    src = tmp_path / "identities" / "scout"
    if what_src == "link":
        real = make_role(tmp_path / "real")
        src.parent.mkdir(parents=True)
        os.symlink(real, src)
    elif what_src == "file":
        src.parent.mkdir(parents=True)
        src.write_text("not a folder")
    with pytest.raises(SnapshotRefused, match="the role folder 'scout' (does not exist|is not a "
                                              "folder)"):
        take_snapshot(src, snapshot_at(tmp_path / "p"), what=WHAT)


def test_sw25_the_digest_is_on_the_participant_row_and_the_snapshot_is_then_left_alone(member,
                                                                                    led):
    """Recorded last, once; from then on the role's real folder may change (M1's live run:
    Design's folder changed mid-run, L4-F4) -- the member keeps the snapshot it joined with."""
    cfg = {"role": "scout", "workspace_files": {"brief.md": "Goal: {{ goal }}\n"}}
    digest = prepare_participant(member.box, member.pdir, cfg, {"goal": "ship it"}, ledger=led,
                                 participant=member.part)
    pid = member.part["participant_id"]
    row = led.participant(pid)
    assert row["snapshot_sha256"] == digest == tree_digest(member.dst) == tree_digest(member.src)
    assert len(digest) == 64
    assert (member.pdir / "workspace" / "brief.md").read_text() == "Goal: ship it"

    (member.src / "notebook.md").write_text("Rewritten while the run goes on.\n")
    (member.src / "notes" / "n9.md").write_text("a new note\n")
    assert prepare_participant(member.box, member.pdir, cfg, {"goal": "other"}, ledger=led,
                               participant=row) is None
    assert (member.dst / "notebook.md").read_text() == NOTEBOOK
    assert not (member.dst / "notes" / "n9.md").exists()
    assert (member.pdir / "workspace" / "brief.md").read_text() == "Goal: ship it"
    # the first digest stays: a later one never writes over it
    assert led.record_snapshot(pid, "f" * 64) == digest
    assert led.participant(pid)["snapshot_sha256"] == digest


def test_sw25_a_participant_that_already_had_turns_is_never_snapshotted_again(member, led):
    """A row from before the digest existed whose member already worked: its folder is the
    member's, so nothing is copied over it."""
    led.post("run-1", "talk", "scout", "hello", dedupe_key="run-1:talk:seed:0")
    led.claim_turn("run-1", "talk", attempt_id="a1")
    assert prepare_participant(member.box, member.pdir, member.cfg, {}, ledger=led,
                               participant=member.part) is None
    assert not os.path.lexists(member.dst)
    assert led.participant(member.part["participant_id"])["snapshot_sha256"] is None


def test_sw25_a_working_folder_that_is_a_link_refuses_the_prepare(member, led):
    their_work = member.pdir.parent / "p-theirs" / "workspace"
    their_work.mkdir(parents=True)
    member.pdir.mkdir(parents=True, exist_ok=True)
    os.symlink(their_work, member.pdir / "workspace")
    cfg = {"role": "scout", "workspace_files": {"brief.md": "x"}}
    with pytest.raises(SnapshotRefused, match="working folder .* is not a folder \\(a link or a "
                                              "file\\); Temper won't write into it"):
        prepare_participant(member.box, member.pdir, cfg, {}, ledger=led,
                            participant=member.part)
    assert list(their_work.iterdir()) == []
    assert led.participant(member.part["participant_id"])["snapshot_sha256"] is None


def test_sw25_replace_snapshot_removes_every_leftover_then_copies(tmp_path):
    src = make_role(tmp_path)
    dst = snapshot_at(tmp_path / "p")
    for n in range(2):
        (dst.parent / f".scout.partial-dead{n}" / "notes").mkdir(parents=True)
    os.chmod(dst.parent / ".scout.partial-dead0" / "notes", 0o500)  # even a read-only one
    digest = replace_snapshot(src, dst, what=WHAT)
    assert leftovers(dst) == [] and digest == tree_digest(dst)


# --- SW-51: reads of member-written trees ----------------------------------------------------


@pytest.fixture
def two(tmp_path):
    """Two members' folders side by side, as a team's state root holds them."""
    mine, theirs = tmp_path / "state" / "p-mine", tmp_path / "state" / "p-theirs"
    for pdir in (mine, theirs):
        for sub in ("state", "workspace", "sessions"):
            (pdir / sub).mkdir(parents=True)
    (theirs / "workspace" / "work.md").write_text("their work\n")
    (theirs / "state" / "box-state.json").write_text('{"v": 1}')
    return SimpleNamespace(mine=mine, theirs=theirs)


@pytest.mark.parametrize("target", ["/etc/passwd", "other_member"])
def test_sw51_a_file_link_is_never_read(two, target):
    target = str(two.theirs / "state" / "box-state.json") if target == "other_member" else target
    os.symlink(target, two.mine / "state" / "box-state.json")
    with pytest.raises(MemberLink, match=r"^state/box-state\.json under .* is a link; Temper does "
                                         r"not follow links in a member's folder$"):
        read_member_text(two.mine, "state/box-state.json")
    assert member_entry(two.mine, "state/box-state.json") == "link"
    assert member_file_sha256(two.mine, "state/box-state.json") is None


@pytest.mark.parametrize("target", ["/etc", "other_member", "relative_other_member"])
def test_sw51_a_folder_link_is_never_followed(two, target):
    shutil.rmtree(two.mine / "workspace")
    target = {"/etc": "/etc", "other_member": str(two.theirs / "workspace"),
              "relative_other_member": "../p-theirs/workspace"}[target]
    os.symlink(target, two.mine / "workspace")
    for rel in ("workspace/work.md", "workspace/passwd"):
        with pytest.raises(MemberLink, match=r"^workspace under .* is a link or a file, not a "
                                             r"folder; Temper does not follow links"):
            read_member_text(two.mine, rel)
        assert member_entry(two.mine, rel) == "link"
    with pytest.raises(MemberLink):
        list_member_dir(two.mine, "workspace")
    with pytest.raises(MemberLink):
        write_member_file(two.mine, "workspace/new.md", "never written through\n")
    assert sorted(p.name for p in (two.theirs / "workspace").iterdir()) == ["work.md"]


def test_sw51_a_file_is_never_written_through_a_link(two):
    os.symlink(two.theirs / "workspace" / "work.md", two.mine / "workspace" / "brief.md")
    assert write_member_file(two.mine, "workspace/brief.md", "overwritten\n") is False
    assert (two.theirs / "workspace" / "work.md").read_text() == "their work\n"
    assert write_member_file(two.mine, "workspace/plan.md", "mine\n") is True
    assert read_member_text(two.mine, "workspace/plan.md") == "mine\n"


def test_sw51_plain_files_and_folders_read_as_before(two):
    (two.mine / "state" / "ok.json").write_text('{"v": 1}')
    assert read_member_text(two.mine, "state/ok.json") == '{"v": 1}'
    assert member_entry(two.mine, "state") == "dir"
    assert member_entry(two.mine, "state/ok.json") == "file"
    assert member_entry(two.mine, "state/none.json") == "missing"
    assert list_member_dir(two.mine, "state") == [("ok.json", "file")]
    with pytest.raises(FileNotFoundError):
        read_member_text(two.mine, "state/none.json")
    with pytest.raises(ValueError):
        read_member_text(two.mine, "../p-theirs/workspace/work.md")


SID = "sess-1"


def _session_line() -> str:
    return json.dumps({"type": "session", "id": SID, "cwd": "/w/workspace"}) + "\n"


def test_sw51_a_session_folder_that_is_a_link_is_refused(two):
    (two.theirs / "sessions" / f"2026_{SID}.jsonl").write_text(_session_line())
    shutil.rmtree(two.mine / "sessions")
    os.symlink(two.theirs / "sessions", two.mine / "sessions")
    with pytest.raises(BoxError) as err:
        check_session(two.mine / "sessions", SID, must_exist=False)
    assert err.value.code == "session_folder_not_private" and "is a link" in str(err.value)
    assert session_started(two.mine) is True  # counted as started, so the check runs and refuses


@pytest.mark.parametrize("target", ["/etc/passwd", "other_member"])
def test_sw51_a_session_file_that_is_a_link_is_refused(two, target):
    theirs = two.theirs / "sessions" / f"2026_{SID}.jsonl"
    theirs.write_text(_session_line())
    os.symlink(str(theirs) if target == "other_member" else target,
               two.mine / "sessions" / f"2026_{SID}.jsonl")
    with pytest.raises(BoxError) as err:
        check_session(two.mine / "sessions", SID, must_exist=True)
    assert err.value.code == "session_folder_not_private"


def test_sw51_session_started_reads_the_folder_without_following_links(two):
    assert session_started(two.mine) is False
    assert session_started(two.mine.parent / "p-nobody") is False
    (two.mine / "sessions" / f"2026_{SID}.jsonl").write_text(_session_line())
    assert session_started(two.mine) is True


class _LinkingBox(FakeBox):
    """Answers /temper-box-state like the stand-in worker, then swaps the state file for a link
    -- to another member's good-looking answer, or to /etc."""

    target: str = ""

    def answer(self, rid, command, fields):
        out = super().answer(rid, command, fields)
        if command == "prompt" and fields.get("message") == "/temper-box-state":
            state = self.pdir / "state" / "box-state.json"
            if self.target == "other_member":
                theirs = self.pdir.parent / "p-theirs" / "state" / "box-state.json"
                theirs.parent.mkdir(parents=True, exist_ok=True)
                theirs.write_text(state.read_text())
                target = str(theirs)
            else:
                target = self.target
            state.unlink()
            os.symlink(target, state)
        return out


class _Recorder:
    def record(self, event_type, data=None, parent_id=None, execution_id=None, status=None,
               event_id=None):
        return event_id or "ev"

    def broadcast_stream_chunk(self, *a, **k):
        pass


class _TurnLedger:
    def record_box(self, turn_id, epoch, name):
        return True

    def mark_effect(self, turn_id, state, *, epoch=None):
        return True


@pytest.mark.parametrize("target", ["other_member", "/etc/hostname"])
def test_sw51_a_turn_never_reads_the_box_state_through_a_link(tmp_path, monkeypatch, target):
    monkeypatch.setattr(_LinkingBox, "target", target)
    cfg = sup.box_config(tmp_path / "box")
    pdir = tmp_path / "state" / "p"
    role = pdir / "memory" / "identities" / sup.ROLE
    role.mkdir(parents=True)
    (role / "notebook.md").write_text(f"The check word is {sup.CHECK_WORD}.\n")
    req = TurnRequest(run_id="run-1", agent_name="talk", node_path="talk",
                      participant={"participant_id": "p1"},
                      turn={"turn_id": "t1", "turn_no": 1, "epoch": 1},
                      text="Say hello.", spec=sup.spec(pdir), agent_event_id="agent-1",
                      recorder=_Recorder(), first_start=True)
    report = run_turn(cfg, req, _TurnLedger(), box_factory=_LinkingBox)
    assert report.state == "failed"
    assert report.error.startswith("member_link_refused: state/box-state.json under ")
    assert "model_call" not in json.dumps(report.checks)


@pytest.fixture
def short_root():
    root = Path(tempfile.mkdtemp(prefix="pibox-", dir="/tmp"))
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _worker_box(tmp_path, short_root, pdir):
    cfg = sup.box_config(tmp_path / "box", socket_root=str(short_root))
    return WorkerBox(cfg, sup.spec(pdir), Redactor(), owner_token=lambda _p: "",
                     connector=lambda _host: socket.socketpair()[0])


@pytest.mark.parametrize("sub", ["state", "sessions", "memory", "workspace"])
@pytest.mark.parametrize("target", ["/etc", "other_member"])
def test_sw51_a_box_never_starts_over_a_member_folder_that_is_a_link(tmp_path, short_root, sub,
                                                                     target):
    pdir = tmp_path / "state" / "p"
    theirs = tmp_path / "state" / "p-theirs" / sub
    theirs.mkdir(parents=True)
    (theirs / "keep.md").write_text("theirs\n")
    pdir.mkdir(parents=True)
    os.symlink("/etc" if target == "/etc" else theirs, pdir / sub)
    box = _worker_box(tmp_path, short_root, pdir)
    box._docker = lambda *a, **k: pytest.fail("Docker was asked to start a box")
    with pytest.raises(BoxError) as err:
        box.start(lambda _event: None)
    assert err.value.code == "member_link_refused"
    assert str(err.value).endswith(f"the participant's {sub} folder is a link; Temper does not "
                                   "follow links in a member's folder")
    assert sorted(p.name for p in theirs.iterdir()) == ["keep.md"]


def test_sw51_a_link_left_as_the_agent_folder_is_removed_never_followed(tmp_path, short_root):
    pdir = tmp_path / "state" / "p"
    theirs = tmp_path / "state" / "p-theirs" / "agent"
    theirs.mkdir(parents=True)
    (theirs / "settings.json").write_text("{}")
    pdir.mkdir(parents=True)
    os.symlink(theirs, pdir / "agent")
    box = _worker_box(tmp_path, short_root, pdir)
    box._write_agent_dir()
    assert not os.path.islink(pdir / "agent") and (pdir / "agent").is_dir()
    assert [p.name for p in theirs.iterdir()] == ["settings.json"]


# --- SW-27: the member's guidance -------------------------------------------------------------

#: The variables the pinned identity extension renders its guidance template with (A4 run-005's
#: extensions/identity/prompt.ts, renderTemplate); the template may use no others.
IDENTITY_TEMPLATE_VARS = {"title", "id", "folder", "cap", "tidyAt", "indexBudget", "size",
                          "tokens", "notes", "notebookPath", "notesPath", "aboutPath",
                          "ownSkills", "skillsDir", "prompt", "reason", "at"}


def test_sw27_every_member_gets_temper_s_guidance_never_a_chat_s(tmp_path, short_root):
    """M2-roles D1: a chat's guidance tells the role to keep its notebook and daily log with
    tools a member doesn't have. The box gets Temper's text instead, even when the identity
    config has its own; it says those tools are missing and lessons go in the reply."""
    pdir = tmp_path / "state" / "p"
    pdir.mkdir(parents=True)
    box = _worker_box(tmp_path, short_root, pdir)
    chat_text = ("Record lessons with the notebook tool (action record) and memory_write to the "
                 "daily log.\n")
    (Path(box.cfg.identity_config) / "pi-identity-role.md").write_text(chat_text)
    box._write_agent_dir()
    written = (pdir / "agent" / "pi-identity-role.md").read_text()
    assert written == MEMBER_GUIDANCE.read_text() != chat_text
    assert (pdir / "agent" / "pi-identity.json").is_file()  # the identity config still reaches it

    sentences = [s for line in written.splitlines() for s in line.split(". ")]
    for tool in ("notebook", "memory_write", "daily log"):
        mentions = [s for s in sentences if tool in s and not s.startswith("Rules (notebook.md)")]
        assert mentions and all("has no" in s for s in mentions), (tool, mentions)
    assert "Put any lessons, findings and questions for the owner in your reply" in written
    import re

    used = {m.group(1) for m in re.finditer(r"\{\{\s*[#/^]?\s*([A-Za-z_]+)\s*\}\}", written)}
    assert used and used <= IDENTITY_TEMPLATE_VARS, used - IDENTITY_TEMPLATE_VARS


def test_sw27_the_guidance_is_inside_the_pinned_temper_box_folder():
    """The conversation's pin covers the temper-box folder's digest, so a change to the text is
    a settings change a reopened conversation refuses, never a silent swap."""
    from temper_ai.pi_agent.box import PROBE_DIR

    assert MEMBER_GUIDANCE.parent == PROBE_DIR and MEMBER_GUIDANCE.is_file()
