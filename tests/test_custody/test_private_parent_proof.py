"""The private parent proof (configs/custody/bin/private_parent_proof.py; temper queue #211, Stage1 P1).

Synthetic trees under tmp_path stand in for the run's workspace W, and FakeHost for the run's box: it
makes up the identity and the mount table and injects the faults, while every file-system call stays
real. The combined happy path comes first, then one test per guard, named for it: with the guard
taken out of the script (a bite), the test named for it fails. PRIVATE_PARENT_PROOF_SCRIPT,
PRIVATE_PARENT_PROOF_AGENT and PRIVATE_PARENT_PROOF_WORKFLOW point these tests at other copies of
the script, the agent and the workflow; the bites use them.
"""

from __future__ import annotations

import copy
import errno
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = Path(os.environ.get("PRIVATE_PARENT_PROOF_SCRIPT") or REPO / "configs/custody/bin/private_parent_proof.py")
AGENT = Path(os.environ.get("PRIVATE_PARENT_PROOF_AGENT") or REPO / "configs/custody/agents/private_parent_proof.yaml")
WORKFLOW = Path(os.environ.get("PRIVATE_PARENT_PROOF_WORKFLOW")
                or REPO / "configs/custody/workflows/private_parent_proof.yaml")
BOX_SCRIPT = "/app/configs/custody/bin/private_parent_proof.py"


def _load():
    spec = importlib.util.spec_from_file_location("private_parent_proof", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


proof = _load()

COLLECTION = "context-profile"
PROFILE = "cp-test-01"
FAMILIES = ["admission", "packets", "native", "native/k01-a", "native/k02-b", "reports", "receipts"]
RUN_ID = "0f0e0d0c-0b0a-4909-8807-060504030201"


def _flag(read_only: bool) -> str:
    return "ro" if read_only else "rw"


def _escape(path: Path) -> str:
    return str(path).replace("\\", "\\134").replace(" ", "\\040").replace("\t", "\\011").replace("\n", "\\012")


def _mountinfo(w: Path, *, code_ro: bool = True, config_ro: bool = True, w_ro: bool = False) -> str:
    """A box's mount table: an overlay root, code and config bound read-only, W bound on its own."""
    return "\n".join([
        "20 1 0:50 / / rw,relatime - overlay overlay rw,lowerdir=/l,upperdir=/u,workdir=/k",
        f"30 20 259:2 /temper_ai {proof.CODE_ROOT} {_flag(code_ro)},relatime - ext4 /dev/disk rw",
        f"31 20 259:2 /configs {proof.CONFIG_ROOT} {_flag(config_ro)},relatime - ext4 /dev/disk rw",
        f"32 20 259:2 /w {_escape(w)} {_flag(w_ro)},relatime master:1 - ext4 /dev/disk rw",
    ]) + "\n"


class FakeHost(proof.Host):
    """The real file-system calls, the box's identity and mount table made up, fsyncs recorded."""

    def __init__(self, w: Path, **mounts: bool) -> None:
        self.mount_text: str | Exception = _mountinfo(w, **mounts)
        self.ident = (os.geteuid(), os.getegid(), sorted(set(os.getgroups())))
        self.synced: list[tuple[int, int]] = []
        self.fail_sync_at: int | None = None
        self.uid_lies: dict[tuple[int, int], int] = {}
        self.umasks: list[int] = []

    def identity(self) -> tuple[int, int, list[int]]:
        return self.ident

    def mkdir(self, name: str, dir_fd: int) -> None:
        self.umasks.append(_umask())
        super().mkdir(name, dir_fd)

    def create_file(self, name: str, dir_fd: int) -> int:
        self.umasks.append(_umask())
        return super().create_file(name, dir_fd)

    def mountinfo(self) -> str:
        if isinstance(self.mount_text, Exception):
            raise self.mount_text
        return self.mount_text

    def fsync(self, fd: int) -> None:
        if self.fail_sync_at == len(self.synced):
            raise OSError(errno.EIO, "injected")
        super().fsync(fd)
        st = os.fstat(fd)
        self.synced.append((st.st_dev, st.st_ino))

    def fstat(self, fd: int) -> os.stat_result:
        st = super().fstat(fd)
        uid = self.uid_lies.get((st.st_dev, st.st_ino))
        if uid is None:
            return st
        fields = list(st[:10])
        fields[4] = uid
        return os.stat_result(fields)


def _w(tmp_path: Path) -> Path:
    base = Path(os.path.realpath(tmp_path)) / "workspaces"
    base.mkdir()
    w = base / "stage1-custody"
    w.mkdir(mode=0o755)
    return w


def _env(w: Path, **override: str) -> dict[str, str]:
    st = os.lstat(w)
    env = {"PROOF_WORKSPACE": str(w), "PROOF_EXPECTED_W_DEV": str(st.st_dev), "PROOF_EXPECTED_W_INO": str(st.st_ino),
           "PROOF_COLLECTION": COLLECTION, "PROOF_PROFILE_ID": PROFILE, "PROOF_FAMILIES": json.dumps(FAMILIES),
           "PROOF_RUN_ID": RUN_ID}
    env.update(override)
    return env


def _umask() -> int:
    current = os.umask(0o022)
    os.umask(current)
    return current


def _fds() -> list[str]:
    return sorted(os.listdir("/proc/self/fd"))


def _key(path: Path) -> tuple[int, int]:
    st = os.lstat(path)
    return st.st_dev, st.st_ino


def _tree(root: Path) -> list[str]:
    """Every name under root, relative to it; links are listed, never followed."""
    names = []
    for folder, dirs, files in os.walk(root):
        names += [os.path.relpath(os.path.join(folder, name), root) for name in dirs + files]
    return sorted(names)


def _strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)] + [k for k in value if isinstance(k, str)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return [value] if isinstance(value, str) else []


def _path_of(w: Path, object_id: str) -> Path:
    p = w / COLLECTION / PROFILE
    return {"CP": w / COLLECTION, "P": p, "proof": p / proof.PROOF_FILE}.get(object_id) or p / object_id[len("family:"):]


def _refused(out: dict, reason: str, failed_object: str | None, *, phase: str = "before_write",
             err: str | None = None) -> None:
    assert proof.check_projection(out) == []
    assert (out["outcome"], out["phase"], out["reason"], out["failed_object"], out["repair"], out["errno"]) == (
        "REFUSED", phase, reason, failed_object, proof.REPAIRS[reason], err)
    if phase == "before_write":
        assert out["objects"] == [] and out["proof"] is None and out["fsyncs"] == 0


def _kept(w: Path, out: dict) -> None:
    """Everything the run reported making is still there, the very same object (nothing deleted)."""
    for record in out["objects"]:
        assert _key(_path_of(w, record["id"])) == (record["dev"], record["ino"]), record["id"]


def _wrap(host: FakeHost, name: str, before=None, after=None) -> None:
    """Put a fault before or after one of host's calls (the call itself stays real)."""
    real = getattr(host, name)

    def call(*args):
        if before:
            before(*args)
        result = real(*args)
        if after:
            after(*args, result)
        return result

    setattr(host, name, call)


# --- the happy path, everything at once ---------------------------------------------------------


def test_happy_path_the_run_creates_p_its_families_and_proof_and_the_host_reads_them_back(tmp_path):
    w = _w(tmp_path)
    w_before = os.lstat(w)
    host = FakeHost(w)
    umask_before = _umask()
    fds_before = _fds()
    out = proof.run(_env(w), host)

    assert _fds() == fds_before, "every fd the run opened is closed"
    assert proof.check_projection(out) == []
    assert (out["format"], out["outcome"], out["phase"]) == ("private-parent-proof/1", "CREATED", "complete")
    assert (out["reason"], out["errno"], out["failed_object"], out["repair"]) == (None, None, None, None)
    euid, egid = os.geteuid(), os.getegid()
    assert out["identity"] == {"euid": euid, "egid": egid, "groups": sorted(set(os.getgroups())),
                               "umask_before": f"{umask_before:04o}", "umask_used": "0077"}
    assert _umask() == umask_before, "the umask is put back"
    assert (out["run_id"], out["collection"], out["profile_id"]) == (RUN_ID, COLLECTION, PROFILE)
    assert out["expected"] == {"w_dev": w_before.st_dev, "w_ino": w_before.st_ino}
    assert out["mounts"] == {
        "W": {"mount_id": 32, "fstype": "ext4", "dev": "259:2", "ro": False, "match": "exact"},
        "code": {"mount_id": 30, "fstype": "ext4", "dev": "259:2", "ro": True, "match": "exact"},
        "config": {"mount_id": 31, "fstype": "ext4", "dev": "259:2", "ro": True, "match": "exact"}}
    assert out["w"] == {"dev": w_before.st_dev, "ino": w_before.st_ino, "uid": euid, "gid": w_before.st_gid,
                        "mode": "0755", "type": "dir", "nlink": w_before.st_nlink, "entries": 0}
    assert (out["private_reads"], out["private_input_custody"], out["rights_beyond_objects"]) == (None, None, None)

    # The host's read-back: each object, links not followed, against what the run reported.
    p = w / COLLECTION / PROFILE
    made = [w / COLLECTION, p] + [p / family for family in FAMILIES]
    assert [o["id"] for o in out["objects"]] == ["CP", "P"] + [f"family:{f}" for f in FAMILIES]
    for path, record in zip(made, out["objects"], strict=True):
        st = os.lstat(path)
        assert stat.S_ISDIR(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o700 and st.st_uid == euid
        assert record == {"id": record["id"], "dev": st.st_dev, "ino": st.st_ino, "uid": euid, "gid": st.st_gid,
                          "mode": "0700", "type": "dir", "nlink": record["nlink"]}
        subdirs = sum(1 for other in made if other.parent == path)
        assert st.st_nlink == record["nlink"] + subdirs, "a directory's count grows by its new subdirectories"
    proof_path = p / "P1-PROOF.json"
    st = os.lstat(proof_path)
    body = proof_path.read_bytes()
    assert out["proof"] == {"id": "proof", "dev": st.st_dev, "ino": st.st_ino, "uid": euid, "gid": st.st_gid,
                            "mode": "0600", "type": "file", "nlink": 1, "size": len(body),
                            "sha256": hashlib.sha256(body).hexdigest()}
    assert stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o600 and st.st_nlink == 1
    written = json.loads(body)
    assert set(written) == {"format", "run_id", "collection", "profile_id", "identity", "w", "objects", "created_utc"}
    assert (written["format"], written["run_id"], written["collection"], written["profile_id"]) == (
        "private-parent-proof-file/1", RUN_ID, COLLECTION, PROFILE)
    assert written["identity"] == {"euid": euid, "egid": egid, "groups": sorted(set(os.getgroups()))}
    assert written["w"] == {"dev": w_before.st_dev, "ino": w_before.st_ino}
    assert written["objects"] == [{"id": o["id"], "dev": o["dev"], "ino": o["ino"]} for o in out["objects"]]

    # Nothing else made, W itself untouched.
    tree = [COLLECTION, f"{COLLECTION}/{PROFILE}", f"{COLLECTION}/{PROFILE}/P1-PROOF.json"]
    assert _tree(w) == sorted(tree + [f"{COLLECTION}/{PROFILE}/{family}" for family in FAMILIES])
    assert (_key(w), stat.S_IMODE(os.lstat(w).st_mode)) == ((w_before.st_dev, w_before.st_ino), 0o755)

    # Every new object fsynced, then its parent; the proof file, then P.
    barriers = [key for path in made for key in (_key(path), _key(path.parent))] + [_key(proof_path), _key(p)]
    assert host.synced == barriers and out["fsyncs"] == len(barriers) == 2 * (2 + len(FAMILIES)) + 2
    assert host.umasks == [0o077] * (len(made) + 1), "umask 077 is in force at every create"

    # Closed: no path anywhere in what the run says.
    assert not [s for s in _strings(out) if s.startswith("/") or str(tmp_path) in s or "stage1-custody" in s]


# --- before anything is written ---------------------------------------------------------------


def test_wrong_actor_refuses_before_writing(tmp_path):
    w = _w(tmp_path)
    host = FakeHost(w)
    host.ident = (os.geteuid() + 1, os.getegid(), [])
    out = proof.run(_env(w), host)
    _refused(out, "w_owner_not_euid", "W")
    assert (out["identity"]["euid"], out["w"]["uid"]) == (os.geteuid() + 1, os.geteuid())
    assert out["w"]["entries"] is None, "someone else's W is not even listed"
    assert _tree(w) == []


def test_root_refuses_before_writing(tmp_path):
    w = _w(tmp_path)
    host = FakeHost(w)
    host.ident = (0, 0, [0])
    _refused(proof.run(_env(w), host), "euid_root", None)
    assert _tree(w) == []


def test_writable_code_mount_refuses(tmp_path):
    w = _w(tmp_path)
    out = proof.run(_env(w), FakeHost(w, code_ro=False))
    _refused(out, "code_mount_writable", "code")
    assert out["mounts"]["code"]["ro"] is False and _tree(w) == []


def test_writable_config_mount_refuses(tmp_path):
    w = _w(tmp_path)
    _refused(proof.run(_env(w), FakeHost(w, config_ro=False)), "config_mount_writable", "config")
    assert _tree(w) == []


def test_read_only_workspace_mount_refuses(tmp_path):
    w = _w(tmp_path)
    _refused(proof.run(_env(w), FakeHost(w, w_ro=True)), "w_mount_readonly", "W")
    assert _tree(w) == []


@pytest.mark.parametrize("case", ["unreadable", "garbage", "empty", "workspace_outside"])
def test_an_unreadable_or_partial_mount_table_refuses(tmp_path, case):
    w = _w(tmp_path)
    host = FakeHost(w)
    host.mount_text = {
        "unreadable": PermissionError(errno.EACCES, "injected"),
        "garbage": "this is not a mount table\n",
        "empty": "",
        "workspace_outside": "\n".join(line for line in _mountinfo(w).splitlines() if " / / " not in line
                                       and _escape(w) not in line),
    }[case]
    out = proof.run(_env(w), host)
    _refused(out, "mountinfo_unreadable", None)
    assert out["mounts"] is None and _tree(w) == []


@pytest.mark.parametrize("case", ["leaf", "ancestor"])
def test_a_missing_workspace_refuses(tmp_path, case):
    w = _w(tmp_path)
    env = _env(w)
    if case == "leaf":
        w.rmdir()
    else:
        env["PROOF_WORKSPACE"] = str(w.parent / "absent" / w.name)
    _refused(proof.run(env, FakeHost(w)), "w_missing", "W", err="ENOENT")


def test_a_workspace_that_is_a_link_refuses(tmp_path):
    w = _w(tmp_path)
    target = w.with_name("target")
    w.rename(target)
    w.symlink_to(target)
    out = proof.run(_env(w), FakeHost(w))
    _refused(out, "w_symlink", "W")
    assert out["w"]["type"] == "symlink" and _tree(target) == []


def test_a_workspace_reached_through_a_link_refuses(tmp_path):
    w = _w(tmp_path)
    link = w.parent.with_name("link")
    link.symlink_to(w.parent)
    via = link / w.name
    # Linux answers ENOTDIR, not ELOOP, when O_NOFOLLOW meets a link and O_DIRECTORY is also set.
    _refused(proof.run(_env(via), FakeHost(via)), "w_path_unsafe", "W", err="ENOTDIR")
    assert _tree(w) == []


def test_a_workspace_that_is_not_a_directory_refuses(tmp_path):
    w = _w(tmp_path)
    w.rmdir()
    w.write_text("")
    out = proof.run(_env(w), FakeHost(w))
    _refused(out, "w_not_directory", "W")
    assert out["w"]["type"] == "file" and w.read_text() == ""


@pytest.mark.parametrize("case", ["replaced", "wrong_dev", "wrong_ino"])
def test_a_workspace_that_is_not_the_recorded_one_refuses(tmp_path, case):
    w = _w(tmp_path)
    env = _env(w)
    if case == "replaced":
        w.rename(w.with_name("old"))
        w.mkdir(0o755)
    else:
        key = "PROOF_EXPECTED_W_DEV" if case == "wrong_dev" else "PROOF_EXPECTED_W_INO"
        env[key] = str(int(env[key]) + 1)
    _refused(proof.run(env, FakeHost(w)), "w_identity_mismatch", "W")
    assert _tree(w) == []


@pytest.mark.parametrize("case", ["link", "file", "other_directory"])
def test_a_workspace_swapped_after_its_lstat_is_not_followed_or_used(tmp_path, case):
    w = _w(tmp_path)
    host = FakeHost(w)
    moved = w.with_name("moved")

    def swap(name, dir_fd, result):
        if name == w.name:
            os.rename(name, moved.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
            if case == "link":
                os.symlink(moved.name, name, dir_fd=dir_fd)
            elif case == "file":
                os.close(os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644, dir_fd=dir_fd))
            else:
                os.mkdir(name, dir_fd=dir_fd)

    _wrap(host, "lstat", after=swap)
    out = proof.run(_env(w), host)
    if case == "other_directory":
        _refused(out, "w_identity_mismatch", "W")
    else:  # neither a link nor a file is opened as a directory
        _refused(out, "w_path_unsafe", "W", err="ENOTDIR")
    assert _tree(moved) == []


def test_a_workspace_that_cannot_be_listed_refuses(tmp_path):
    w = _w(tmp_path)
    host = FakeHost(w)

    def entries(fd):
        raise PermissionError(errno.EACCES, "injected")

    host.entries = entries  # type: ignore[method-assign]
    _refused(proof.run(_env(w), host), "w_path_unsafe", "W", err="EACCES")


def test_nonempty_workspace_refuses(tmp_path):
    w = _w(tmp_path)
    (w / "left-over").write_text("theirs")
    out = proof.run(_env(w), FakeHost(w))
    _refused(out, "w_not_empty", "W")
    assert out["w"]["entries"] == 1 and _tree(w) == ["left-over"] and (w / "left-over").read_text() == "theirs"


BAD_INPUTS = {
    "missing": {"PROOF_RUN_ID": None},
    "relative_workspace": {"PROOF_WORKSPACE": "workspaces/w"},
    "root_workspace": {"PROOF_WORKSPACE": "/"},
    "double_slash": {"PROOF_WORKSPACE": "/{W}"},
    "nul": {"PROOF_WORKSPACE": "{W}\x00"},
    "dotdot_workspace": {"PROOF_WORKSPACE": "{W}/../stage1-custody"},
    "trailing_slash": {"PROOF_WORKSPACE": "{W}/"},
    "dev_not_decimal": {"PROOF_EXPECTED_W_DEV": "0x10"},
    "ino_empty": {"PROOF_EXPECTED_W_INO": ""},
    "collection_with_slash": {"PROOF_COLLECTION": "context/profile"},
    "profile_dotdot": {"PROOF_PROFILE_ID": ".."},
    "profile_upper": {"PROOF_PROFILE_ID": "CP-TEST"},
    "run_id_space": {"PROOF_RUN_ID": "a run"},
    "families_not_json": {"PROOF_FAMILIES": "[native"},
    "families_not_list": {"PROOF_FAMILIES": '{"native": 1}'},
    "family_not_text": {"PROOF_FAMILIES": "[1]"},
    "family_three_levels": {"PROOF_FAMILIES": '["a", "a/b", "a/b/c"]'},
    "family_twice": {"PROOF_FAMILIES": '["native", "native"]'},
    "family_dotdot": {"PROOF_FAMILIES": '["..", "../x"]'},  # parent listed first: only the name pattern catches it
    "family_child_first": {"PROOF_FAMILIES": '["native/k01", "native"]'},
}


@pytest.mark.parametrize("case", sorted(BAD_INPUTS))
def test_invalid_inputs_refuse_and_echo_nothing(tmp_path, case):
    w = _w(tmp_path)
    env: dict[str, Any] = _env(w)
    for key, value in BAD_INPUTS[case].items():
        if value is None:
            del env[key]
        else:
            env[key] = value.replace("{W}", str(w))
    out = proof.run(env, FakeHost(w))
    _refused(out, "input_invalid", None)
    assert (out["run_id"], out["collection"], out["profile_id"], out["expected"], out["w"]) == (None,) * 5
    assert _tree(w) == []


# --- while creating -----------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "reason", "object_id"), [
    (COLLECTION, "cp_exists", "CP"), (PROFILE, "p_exists", "P"), ("native", "family_exists", "family:native")])
def test_an_existing_collection_profile_or_family_is_not_adopted(tmp_path, name, reason, object_id):
    w = _w(tmp_path)
    host = FakeHost(w)

    def theirs(made, dir_fd):
        if made == name:  # someone else's folder, made while the proof's umask 077 is in force
            os.mkdir(made, dir_fd=dir_fd)
            os.chmod(made, 0o755, dir_fd=dir_fd)

    _wrap(host, "mkdir", before=theirs)
    out = proof.run(_env(w), host)
    _refused(out, reason, object_id, phase="during_create", err="EEXIST")
    existing = _path_of(w, object_id)
    assert object_id not in [o["id"] for o in out["objects"]]
    assert stat.S_IMODE(os.lstat(existing).st_mode) == 0o755 and _tree(existing) == []
    _kept(w, out)


def test_an_existing_proof_file_is_not_overwritten(tmp_path):
    w = _w(tmp_path)
    host = FakeHost(w)

    def theirs(name, dir_fd):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644, dir_fd=dir_fd)
        os.write(fd, b"theirs")
        os.close(fd)

    _wrap(host, "create_file", before=theirs)
    out = proof.run(_env(w), host)
    _refused(out, "proof_exists", "proof", phase="during_create", err="EEXIST")
    assert _path_of(w, "proof").read_bytes() == b"theirs" and out["proof"] is None
    _kept(w, out)


@pytest.mark.parametrize(("name", "object_id"), [(COLLECTION, "CP"), (PROFILE, "P"), ("native", "family:native")])
def test_a_created_directory_swapped_for_a_link_is_not_followed(tmp_path, name, object_id):
    w = _w(tmp_path)
    host = FakeHost(w)

    def swap(made, dir_fd, result):
        if made == name:
            os.rename(made, made + ".moved", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
            os.symlink(made + ".moved", made, dir_fd=dir_fd)

    _wrap(host, "mkdir", after=swap)
    out = proof.run(_env(w), host)
    _refused(out, "open_failed", object_id, phase="during_create", err="ENOTDIR")
    moved = _path_of(w, object_id).with_name(name + ".moved")
    assert _tree(moved) == [] and os.path.islink(_path_of(w, object_id))
    _kept(w, out)


def test_a_created_directory_owned_by_someone_else_refuses(tmp_path):
    w = _w(tmp_path)
    host = FakeHost(w)

    def lie(made, dir_fd, result):
        if made == PROFILE:
            st = os.stat(made, dir_fd=dir_fd, follow_symlinks=False)
            host.uid_lies[(st.st_dev, st.st_ino)] = os.geteuid() + 1

    _wrap(host, "mkdir", after=lie)
    out = proof.run(_env(w), host)
    _refused(out, "owner_mismatch", "P", phase="during_create")
    assert out["objects"][-1]["uid"] == os.geteuid() + 1
    _kept(w, out)


def test_a_created_directory_with_another_mode_refuses(tmp_path):
    w = _w(tmp_path)
    host = FakeHost(w)

    def loosen(made, dir_fd, result):
        if made == "packets":
            os.chmod(made, 0o750, dir_fd=dir_fd)

    _wrap(host, "mkdir", after=loosen)
    out = proof.run(_env(w), host)
    _refused(out, "mode_mismatch", "family:packets", phase="during_create")
    assert (out["objects"][-1]["id"], out["objects"][-1]["mode"]) == ("family:packets", "0750")
    _kept(w, out)


def test_a_proof_file_with_a_second_link_refuses(tmp_path):
    w = _w(tmp_path)
    host = FakeHost(w)

    def link(name, dir_fd, fd):
        os.link(name, "second-link", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)

    _wrap(host, "create_file", after=link)
    out = proof.run(_env(w), host)
    _refused(out, "proof_not_single_link", "proof", phase="during_create")
    assert out["proof"]["nlink"] == 2
    _kept(w, out)


def test_a_proof_file_owned_by_someone_else_refuses(tmp_path):
    w = _w(tmp_path)
    host = FakeHost(w)

    def lie(name, dir_fd, fd):
        st = os.fstat(fd)
        host.uid_lies[(st.st_dev, st.st_ino)] = os.geteuid() + 1

    _wrap(host, "create_file", after=lie)
    _refused(proof.run(_env(w), host), "owner_mismatch", "proof", phase="during_create")


def test_a_proof_file_with_another_mode_refuses(tmp_path):
    w = _w(tmp_path)
    host = FakeHost(w)
    _wrap(host, "create_file", after=lambda name, dir_fd, fd: os.fchmod(fd, 0o640))
    out = proof.run(_env(w), host)
    _refused(out, "mode_mismatch", "proof", phase="during_create")
    assert out["proof"]["mode"] == "0640"


def _refuse_for(name: str):
    def fault(made, *rest):
        if made == name:
            raise PermissionError(errno.EACCES, "injected")
    return fault


@pytest.mark.parametrize("fault", ["mkdir", "open", "create", "write", "fsync"])
def test_a_storage_fault_stops_there_and_keeps_what_was_made(tmp_path, fault):
    w = _w(tmp_path)
    host = FakeHost(w)
    if fault == "mkdir":
        _wrap(host, "mkdir", before=_refuse_for("native"))
        want = ("mkdir_failed", "family:native", "EACCES", 4)
    elif fault == "open":
        _wrap(host, "open_dir", before=_refuse_for("reports"))
        want = ("open_failed", "family:reports", "EACCES", 7)
    elif fault == "create":
        _wrap(host, "create_file", before=_refuse_for(proof.PROOF_FILE))
        want = ("open_failed", "proof", "EACCES", 9)
    elif fault == "write":
        zeros = []

        def write_nothing(fd, data):
            zeros.append(fd)
            if len(zeros) > 3:
                raise AssertionError("the write loop does not stop on a write of nothing")
            return 0

        host.write = write_nothing  # type: ignore[method-assign]
        want = ("write_failed", "proof", "EIO", 9)
    else:
        host.fail_sync_at = 2  # CP and W done, then P's own fsync
        want = ("fsync_failed", "P", "EIO", 2)
    out = proof.run(_env(w), host)
    reason, object_id, err, made = want
    _refused(out, reason, object_id, phase="during_create", err=err)
    assert len(out["objects"]) == made
    _kept(w, out)


def test_short_writes_are_carried_on_until_the_whole_proof_is_written(tmp_path):
    w = _w(tmp_path)
    host = FakeHost(w)
    pieces = []

    def short(fd, data):
        pieces.append(len(data))
        return os.write(fd, data[:7])

    host.write = short  # type: ignore[method-assign]
    out = proof.run(_env(w), host)
    assert out["outcome"] == "CREATED" and len(pieces) > 1
    body = _path_of(w, "proof").read_bytes()
    assert (len(body), hashlib.sha256(body).hexdigest()) == (out["proof"]["size"], out["proof"]["sha256"])
    assert json.loads(body)["run_id"] == RUN_ID


def test_the_modes_hold_without_the_umask(tmp_path):
    w = _w(tmp_path)
    host = FakeHost(w)
    host.umask = lambda mask: 0  # type: ignore[method-assign]  # a umask that does nothing
    saved = os.umask(0)
    try:
        out = proof.run(_env(w), host)
    finally:
        os.umask(saved)
    assert out["outcome"] == "CREATED" and host.umasks == [0] * (len(out["objects"]) + 1)
    assert {o["mode"] for o in out["objects"]} == {"0700"} and out["proof"]["mode"] == "0600"


def test_each_create_flag_holds_on_its_own(tmp_path):
    folder = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        (tmp_path / "target").write_text("theirs")
        (tmp_path / proof.PROOF_FILE).symlink_to("target")
        for without, err in ((os.O_EXCL, errno.ELOOP), (os.O_NOFOLLOW, errno.EEXIST)):
            with pytest.raises(OSError) as raised:
                os.close(os.open(proof.PROOF_FILE, proof.CREATE_FLAGS & ~without, 0o600, dir_fd=folder))
            assert raised.value.errno == err
        assert (tmp_path / "target").read_text() == "theirs"
    finally:
        os.close(folder)


def test_an_unexpected_error_is_a_closed_refusal_that_keeps_what_was_made(tmp_path):
    w = _w(tmp_path)
    host = FakeHost(w)

    def broken():
        raise RuntimeError(str(w))

    host.utc_now = broken  # type: ignore[method-assign]
    fds_before = _fds()
    out = proof.run(_env(w), host)
    assert _fds() == fds_before
    _refused(out, "internal_error", None, phase="during_create")
    assert len(out["objects"]) == 2 + len(FAMILIES) and out["proof"] is None
    assert not (_path_of(w, "proof")).exists() and str(w) not in json.dumps(out)
    _kept(w, out)


# --- the projection, the mount table, main ------------------------------------------------------


SOMEONE = "/home/someone"
REFUSAL = {"outcome": "REFUSED", "reason": "w_missing", "repair": "create_w_by_host_operator"}
# One way each to spoil a good projection; check_projection must catch every one.
SPOILERS = {
    "extra_key": lambda p: p.update(note="free text"),
    "missing_key": lambda p: p.pop("fsyncs"),
    "other_format": lambda p: p.update(format=SOMEONE),
    "unknown_outcome": lambda p: p.update(outcome="MAYBE"),
    "path_as_phase": lambda p: p.update(REFUSAL, phase=SOMEONE),
    "created_not_complete": lambda p: p.update(phase="before_write"),
    "created_with_a_reason": lambda p: p.update(reason="w_missing"),
    "created_without_proof": lambda p: p.update(proof=None),
    "refused_complete": lambda p: p.update(REFUSAL),
    "free_text_reason": lambda p: p.update(REFUSAL, phase="before_write", reason="W is gone", repair=None),
    "wrong_repair": lambda p: p.update(REFUSAL, phase="before_write", repair="correct_inputs"),
    # on an otherwise good refusal, so that only the errno or object check can catch them
    "path_as_errno": lambda p: p.update(REFUSAL, phase="before_write", errno=SOMEONE),
    "path_as_failed_object": lambda p: p.update(REFUSAL, phase="before_write", failed_object="family:../x"),
    "path_as_run_id": lambda p: p.update(run_id=SOMEONE),
    "path_as_profile": lambda p: p.update(profile_id=SOMEONE),
    "text_in_expected": lambda p: p["expected"].update(w_dev=SOMEONE),
    "env_in_identity": lambda p: p["identity"].update(home=SOMEONE),
    "euid_as_text": lambda p: p["identity"].update(euid="1000"),
    "text_in_groups": lambda p: p["identity"].update(groups=[SOMEONE]),
    "text_as_umask": lambda p: p["identity"].update(umask_used=SOMEONE),
    "extra_mount": lambda p: p["mounts"].update(home=dict(p["mounts"]["W"])),
    "mount_point_kept": lambda p: p["mounts"]["W"].update(point=SOMEONE),
    "mount_id_as_text": lambda p: p["mounts"]["W"].update(mount_id="32"),
    "text_in_mount": lambda p: p["mounts"]["W"].update(fstype="ext4 /home/someone"),
    "text_as_mount_dev": lambda p: p["mounts"]["W"].update(dev=SOMEONE),
    "text_as_ro": lambda p: p["mounts"]["W"].update(ro="no"),
    "text_as_match": lambda p: p["mounts"]["W"].update(match=SOMEONE),
    "path_beside_stat": lambda p: p["w"].update(path=SOMEONE),
    "text_as_entries": lambda p: p["w"].update(entries=SOMEONE),
    "objects_not_list": lambda p: p.update(objects=5),
    "path_as_object": lambda p: p["objects"][0].update(id=SOMEONE),
    "w_as_object": lambda p: p["objects"][0].update(id="W"),
    "text_as_ino": lambda p: p["objects"][0].update(ino=SOMEONE),
    "text_as_mode": lambda p: p["objects"][0].update(mode=SOMEONE),
    "text_as_type": lambda p: p["objects"][0].update(type=SOMEONE),
    "path_beside_proof": lambda p: p["proof"].update(path=SOMEONE),
    "proof_id_path": lambda p: p["proof"].update(id=SOMEONE),
    "text_as_size": lambda p: p["proof"].update(size=SOMEONE),
    "short_digest": lambda p: p["proof"].update(sha256="abc"),
    "bool_as_count": lambda p: p.update(fsyncs=True),
    "negative_count": lambda p: p.update(fsyncs=-1),
    "private_read_claimed": lambda p: p.update(private_reads="none"),
    "rights_claimed": lambda p: p.update(rights_beyond_objects=[]),
}


def test_the_projection_check_passes_the_real_projections(tmp_path):
    w = _w(tmp_path)
    assert proof.check_projection(proof.run(_env(w), FakeHost(w))) == []
    assert proof.check_projection(proof.fallback()) == []
    refused = copy.deepcopy(proof.run(_env(w), FakeHost(w)))  # the base the errno and object spoilers start from
    refused.update(REFUSAL, phase="before_write", errno="ENOENT", failed_object="family:native/k01-a")
    assert proof.check_projection(refused) == []


@pytest.mark.parametrize("spoiler", sorted(SPOILERS))
def test_the_projection_check_lets_only_closed_values_through(tmp_path, spoiler):
    w = _w(tmp_path)
    spoiled = copy.deepcopy(proof.run(_env(w), FakeHost(w)))
    SPOILERS[spoiler](spoiled)
    assert proof.check_projection(spoiled)


def test_the_mount_table_is_read_as_proc_5_says():
    table = proof.parse_mountinfo("\n".join([
        "1 0 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw",
        "2 1 8:2 /x /a\\040b ro,nosuid master:2 - xfs /dev/sda2 rw",
        "3 1 0:5 / /a ro - tmpfs tmpfs rw",
        "4 1 0:6 / /a rw - tmpfs tmpfs ro",
        "5 1 0:7 / /odd rw - Not_A_Type x rw",
    ]))
    assert [tuple(m) for m in table] == [(1, "/", "ext4", "8:1", False), (2, "/a b", "xfs", "8:2", True),
                                         (3, "/a", "tmpfs", "0:5", True), (4, "/a", "tmpfs", "0:6", False),
                                         (5, "/odd", None, "0:7", False)]
    assert proof.covering(table, "/a b/c") == (table[1], "ancestor")
    assert proof.covering(table, "/a") == (table[3], "exact"), "of two at one point, the later is on top"
    assert proof.covering(table, "/a/x") == (table[3], "ancestor")
    assert proof.covering(table, "/ab") == (table[0], "ancestor")
    assert proof.covering(table[1:], "/elsewhere") is None
    for garbage in ("", "1 0 8:1 / / rw", "x 0 8:1 / / rw - ext4 a rw", "+1 0 8:1 / / rw - ext4 a rw",
                    "1 0 81 / / rw - ext4 a rw", "1 0 8:1 / / rw - ", "1 0 8:1 / - ext4 a rw"):
        with pytest.raises(ValueError):
            proof.parse_mountinfo(garbage)


def test_main_prints_one_closed_line_and_nothing_on_stderr(tmp_path):
    w = _w(tmp_path)
    done = subprocess.run([sys.executable, "-I", str(SCRIPT)], env=_env(w), capture_output=True, text=True,
                          timeout=60, check=False)
    assert (done.returncode, done.stderr) == (0, "")
    lines = done.stdout.splitlines()
    assert len(lines) == 1
    out = json.loads(lines[0])
    assert proof.check_projection(out) == []
    if out["phase"] == "before_write":  # this machine's own mount table decides how far it gets
        assert _tree(w) == []


@pytest.mark.parametrize("case", ["spoiled", "raises"])
def test_main_replaces_a_projection_that_fails_its_check(monkeypatch, capsys, case):
    def spoiled(env):
        return {**proof.blank(), "note": "/home/someone"}

    def raises(env):
        raise RuntimeError("/home/someone")

    monkeypatch.setattr(proof, "run", spoiled if case == "spoiled" else raises)
    assert proof.main() == 0
    printed = capsys.readouterr()
    assert json.loads(printed.out) == proof.fallback() and printed.err == ""


# --- the configs ----------------------------------------------------------------------------


def test_configs_fit_together():
    from temper_ai.cli.check import _FileConfigs
    from temper_ai.stage.loader import GraphLoader

    for public in (AGENT, WORKFLOW, SCRIPT):
        text = public.read_text()
        assert "/home/" not in text and "shinelay" not in text, f"{public.name} names a host path"
    agent = yaml.safe_load(AGENT.read_text())["agent"]
    flow = yaml.safe_load(WORKFLOW.read_text())["workflow"]
    assert agent["type"] == "script" and not {"model", "provider", "system_prompt", "tools"} & set(agent)
    template = agent["script_template"]
    assert template.splitlines()[1] == "exec 2>/dev/null", "stderr goes nowhere before anything runs"
    assert f'"$TEMPER_PYTHON" -I {BOX_SCRIPT}' in template and (REPO / BOX_SCRIPT[len("/app/"):]).is_file()
    assert "${" not in AGENT.read_text() + WORKFLOW.read_text()
    assert [(node["name"], node["agent"]) for node in flow["nodes"]] == [("proof", "private_parent_proof")]
    inputs = {"expected_w_dev", "expected_w_ino", "collection", "profile_id", "families"}
    assert set(flow["inputs"]) == inputs and all(flow["inputs"][name]["required"] for name in inputs)
    assert flow["nodes"][0]["input_map"] == {name: f"input.{name}" for name in inputs}
    assert flow["outputs"] == {key: f"proof.structured.{key}" for key in proof.TOP_KEYS}
    nodes, _ = GraphLoader(_FileConfigs(REPO / "configs")).load_workflow(  # type: ignore[arg-type]
        "private_parent_proof", inputs={name: "x" for name in inputs})
    assert [node.name for node in nodes] == ["proof"]
    departments = (REPO / "docs/departments.md").read_text()
    for name in ("custody/workflows/private_parent_proof.yaml", "custody/agents/private_parent_proof.yaml",
                 "custody/bin/private_parent_proof.py"):
        assert f"`{name}`" in departments, f"docs/departments.md does not list {name}"


def test_the_agent_hands_the_script_the_run_and_its_inputs(tmp_path):
    from unittest.mock import MagicMock

    from temper_ai.agent.script_agent import ScriptAgent
    from temper_ai.tools.bash import Bash
    from temper_ai.tools.executor import ToolExecutor

    w = _w(tmp_path)
    executor = ToolExecutor(workspace_root=str(w))
    executor.register_tools({"Bash": Bash(config={"workspace_root": str(w)})})
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name, ctx.workspace_path = RUN_ID, "proof", "private_parent_proof", str(w)
    ctx.skip_policies, ctx.parent_event_id, ctx.tool_executor = None, None, executor
    env = _env(w)
    inputs = {"expected_w_dev": env["PROOF_EXPECTED_W_DEV"], "expected_w_ino": env["PROOF_EXPECTED_W_INO"],
              "collection": COLLECTION, "profile_id": PROFILE, "families": env["PROOF_FAMILIES"]}
    config = yaml.safe_load(AGENT.read_text())["agent"]

    stub = tmp_path / "stub.py"
    stub.write_text("import json, os, sys\n"
                    "sys.stderr.write('/home/someone\\n')\n"
                    "handed = {k: v for k, v in os.environ.items() if k.startswith('PROOF_')}\n"
                    "print(json.dumps({**handed, 'isolated': sys.flags.isolated}))\n")
    handed = ScriptAgent(config={**config, "script_template": config["script_template"].replace(
        BOX_SCRIPT, str(stub))}).run(inputs, ctx)
    assert handed.status.value == "completed" and handed.structured_output == {**env, "isolated": 1}
    assert "/home/someone" not in handed.output, "stderr goes nowhere"

    real = ScriptAgent(config={**config, "script_template": config["script_template"].replace(
        BOX_SCRIPT, str(SCRIPT))}).run(inputs, ctx)
    assert real.status.value == "completed" and "STDERR" not in real.output
    assert proof.check_projection(real.structured_output) == []
    assert real.output.strip() == json.dumps(real.structured_output, sort_keys=True, separators=(",", ":"))
