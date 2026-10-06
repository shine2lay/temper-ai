"""A member's own trees: its role snapshot (SW-25) and Temper's reads of what it writes (SW-51).

M4 ADR-M4-08. Both are about links, and both never follow one.

* **The role snapshot.** A member works from a private copy of its role folder, taken when it
  joins. The copy is made in a temporary folder next to the target and digested three times
  -- the source before copying, the source after, the copy -- and moved into place by one
  rename only when all three match; on a mismatch it is made once more, then refused. A crash
  mid-copy leaves at most a temporary folder, which is never used as the snapshot: the next
  attempt removes it and copies afresh. A link is copied as a link when it points inside the
  role folder; one that points out of it (or is absolute) refuses the snapshot, naming it.
* **Reads of member-written trees.** Everything under a member's folder may have been written
  by the member (its box mounts the folder read-write), so Temper reads there without
  following any link: each path component below the folder is opened no-follow and only a
  regular file is read. A link on the way is refused (:class:`MemberLink`) -- to ``/etc``, to
  another member's folder, or anywhere else -- never followed.
"""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import stat
import uuid
from pathlib import Path

#: The temporary copy is ``.<target name>.partial-<id>``, next to the target.
PARTIAL = ".partial-"

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_CHUNK = 1 << 20


class SnapshotRefused(Exception):
    """The role folder could not be snapshotted; the message is the plain problem."""


class MemberLink(OSError):
    """A read under a member's folder met a link or something that is not a regular file:
    refused, never followed. An ``OSError``, so a reader that treats an unreadable file as
    missing keeps doing so."""

    def __init__(self, message: str):
        super().__init__(errno.ELOOP, message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class _Changed(Exception):
    """An entry vanished or changed kind while the tree was read: the tree is changing."""


class _Outside(Exception):
    def __init__(self, rel: str, target: str):
        super().__init__(rel)
        self.rel, self.target = rel, target


class _Special(Exception):
    def __init__(self, rel: str):
        super().__init__(rel)
        self.rel = rel


# --- one tree, read without following links -------------------------------------------------


def _file_digest(path: str) -> str:
    try:
        fd = os.open(path, _FILE_FLAGS)
    except (FileNotFoundError, NotADirectoryError):
        raise _Changed(path) from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:  # it became a link since it was listed
            raise _Changed(path) from None
        raise
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise _Changed(path)
        h = hashlib.sha256()
        while chunk := os.read(fd, _CHUNK):
            h.update(chunk)
        return h.hexdigest()
    finally:
        os.close(fd)


def _link_inside(root: str, rel: str, target: str) -> bool:
    """Whether the link at ``rel`` points inside ``root``: a relative target that stays in the
    folder both as written and as resolved on disk now."""
    if not target or os.path.isabs(target):
        return False
    lexical = os.path.normpath(os.path.join(os.path.dirname(rel), target))
    if lexical == ".." or lexical.startswith("../") or os.path.isabs(lexical):
        return False
    real_root = os.path.realpath(root)
    real = os.path.realpath(os.path.join(root, rel))
    return real == real_root or real.startswith(real_root.rstrip(os.sep) + os.sep)


def _scan(root: str) -> list[tuple[str, str, str]]:
    """Every entry below ``root``, sorted by path: (path, kind, what it holds) -- a file's
    content digest, a link's target text, nothing for a folder. Never follows a link; raises
    :class:`_Outside` for a link out of the folder and :class:`_Special` for anything that is
    not a file, folder or link."""
    out: list[tuple[str, str, str]] = []
    stack = [""]
    while stack:
        rel_dir = stack.pop()
        path = os.path.join(root, rel_dir) if rel_dir else root
        try:
            with os.scandir(path) as listing:
                found = list(listing)
        except (FileNotFoundError, NotADirectoryError):
            raise _Changed(path) from None
        for entry in found:
            rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except FileNotFoundError:
                raise _Changed(rel) from None
            if stat.S_ISLNK(mode):
                try:
                    target = os.readlink(entry.path)
                except (FileNotFoundError, OSError):
                    raise _Changed(rel) from None
                if not _link_inside(root, rel, target):
                    raise _Outside(rel, target)
                out.append((rel, "link", target))
            elif stat.S_ISDIR(mode):
                out.append((rel, "dir", ""))
                stack.append(rel)
            elif stat.S_ISREG(mode):
                out.append((rel, "file", _file_digest(entry.path)))
            else:
                raise _Special(rel)
    out.sort()
    return out


def _digest(entries: list[tuple[str, str, str]]) -> str:
    h = hashlib.sha256()
    for rel, kind, held in entries:
        h.update(f"{kind}\0{rel}\0{held}\n".encode("utf-8", "surrogateescape"))
    return h.hexdigest()


def tree_digest(root: Path | str) -> str:
    """One digest over a folder as it is on disk -- each entry's path and kind, a file's
    content, a link's target text -- read without following any link. The digest a member's
    role snapshot records (SW-25). Raises :class:`SnapshotRefused` for a folder that can't be
    snapshotted (a link out of it, a special file)."""
    root = str(root)
    try:
        return _digest(_scan(root))
    except _Outside as exc:
        raise SnapshotRefused(_outside_text(root, exc)) from None
    except _Special as exc:
        raise SnapshotRefused(f"the folder {root} has {exc.rel!r}, which is not a file, folder "
                              "or link") from None


# --- the role snapshot (SW-25) ---------------------------------------------------------------


def _outside_text(where: str, exc: _Outside) -> str:
    return (f"{where} has a link {exc.rel!r} pointing outside it ({exc.target!r}); Temper "
            "never follows links out of a role folder, so it won't snapshot it. Remove the link "
            "or point it inside the folder")


def _remove(path: Path) -> None:
    """Remove a file, link or folder, never following a link (rmtree removes links, not what
    they point at)."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISDIR(st.st_mode):
        for sub in [path, *_dirs_below(path)]:
            os.chmod(sub, stat.S_IMODE(os.lstat(sub).st_mode) | 0o700)
        shutil.rmtree(path)
    else:
        os.unlink(path)


def _dirs_below(root: Path) -> list[Path]:
    out = []
    for here, dirs, _files in os.walk(root, followlinks=False):
        out += [Path(here) / d for d in dirs if not os.path.islink(Path(here) / d)]
    return out


def leftovers(target: Path) -> list[Path]:
    """Temporary copies a crash left next to ``target``: never the snapshot, always removed."""
    prefix = f".{target.name}{PARTIAL}"
    try:
        return sorted(p for p in target.parent.iterdir() if p.name.startswith(prefix))
    except FileNotFoundError:
        return []


def _copy_file(src: str, dst: str) -> None:
    try:
        sfd = os.open(src, _FILE_FLAGS)
    except (FileNotFoundError, NotADirectoryError):
        raise _Changed(src) from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise _Changed(src) from None
        raise
    try:
        st = os.fstat(sfd)
        if not stat.S_ISREG(st.st_mode):
            raise _Changed(src)
        dfd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                      0o600)
        with os.fdopen(dfd, "wb") as out:
            while chunk := os.read(sfd, _CHUNK):
                out.write(chunk)
        os.chmod(dst, stat.S_IMODE(st.st_mode) | 0o600)
        os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))
    finally:
        os.close(sfd)


def _copy(src: str, dst: str, entries: list[tuple[str, str, str]]) -> None:
    """Copy the listed entries: folders made, links made as links (never followed), files
    copied no-follow. Folders keep their mode with the owner's rwx added, files theirs with the
    owner's rw added, so the copy stays the member's to write and Temper's to remove."""
    os.mkdir(dst, 0o700)
    made: list[tuple[str, str]] = [(src, dst)]
    for rel, kind, held in entries:  # sorted: a folder before what is in it
        s, d = os.path.join(src, rel), os.path.join(dst, rel)
        if kind == "dir":
            os.mkdir(d, 0o700)
            made.append((s, d))
        elif kind == "link":
            os.symlink(held, d)
        else:
            _copy_file(s, d)
    for s, d in reversed(made):
        try:
            st = os.lstat(s)
        except FileNotFoundError:
            raise _Changed(s) from None
        os.chmod(d, stat.S_IMODE(st.st_mode) | 0o700)
        os.utime(d, ns=(st.st_atime_ns, st.st_mtime_ns))


def take_snapshot(src: Path, dst: Path, *, what: str) -> str:
    """Snapshot the folder ``src`` at ``dst`` (which must not exist) and return its digest.

    ``what`` names the folder in a refusal ("role folder 'design'"). The copy is made at
    ``.<dst name>.partial-<id>`` next to ``dst``, then the source before, the source after and
    the copy must have one digest; only then is it renamed into place, in one step. On a
    mismatch the copy is thrown away and made once more; a second mismatch is refused. A
    temporary copy is never used as the snapshot: on refusal it is removed, and one a crash
    left behind is removed by the caller's next attempt (:func:`leftovers`)."""
    src, dst = Path(src), Path(dst)
    try:
        st = os.lstat(src)
    except FileNotFoundError:
        raise SnapshotRefused(f"the {what} does not exist") from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise SnapshotRefused(f"the {what} is not a folder (a link or a file); Temper "
                              "snapshots only a real folder")
    if os.path.lexists(dst):
        raise SnapshotRefused(f"the {what}'s snapshot is already in place")
    dst.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in (1, 2):  # the first copy, and once more if the source changed meanwhile
        tmp = dst.parent / f".{dst.name}{PARTIAL}{uuid.uuid4().hex[:12]}"
        try:
            before = _scan(str(src))
            _copy(str(src), str(tmp), before)
            after = _scan(str(src))
            copied = _scan(str(tmp))
        except _Changed:
            _remove(tmp)
            continue
        except _Outside as exc:
            _remove(tmp)
            raise SnapshotRefused(_outside_text(f"the {what}", exc)) from None
        except _Special as exc:
            _remove(tmp)
            raise SnapshotRefused(f"the {what} has {exc.rel!r}, which is not a file, folder or "
                                  "link; Temper won't snapshot it") from None
        except Exception:
            _remove(tmp)
            raise
        if _digest(before) == _digest(after) == _digest(copied):
            os.rename(tmp, dst)
            return _digest(copied)
        _remove(tmp)
    raise SnapshotRefused(f"the {what} kept changing while Temper copied it (twice); nothing "
                          "was put in place. Try again once nothing is writing to it")


def replace_snapshot(src: Path, dst: Path, *, what: str) -> str:
    """Take a fresh snapshot at ``dst``: first remove what a crash left (temporary copies, and a
    snapshot whose digest was never recorded -- the caller's call to make), then
    :func:`take_snapshot`."""
    for left in leftovers(Path(dst)):
        _remove(left)
    _remove(Path(dst))
    return take_snapshot(src, dst, what=what)


# --- reads of member-written trees (SW-51) ---------------------------------------------------


def _parts(rel: str | Path) -> list[str]:
    parts = [p for p in Path(rel).parts if p not in ("", ".")]
    if not parts or Path(rel).is_absolute() or ".." in parts:
        raise ValueError(f"not a path inside the folder: {rel!s}")
    return parts


def _open_dir(root: Path, parts: list[str]) -> int:
    """A file descriptor of ``root/<parts>``, every component below ``root`` opened no-follow
    (``root`` itself too: its last component is no link either)."""
    try:
        fd = os.open(root, _DIR_FLAGS)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise MemberLink(f"{root} is a link, not a folder: refused") from None
        raise
    try:
        for i, part in enumerate(parts):
            try:
                nfd = os.open(part, _DIR_FLAGS, dir_fd=fd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    where = "/".join(parts[:i + 1])
                    raise MemberLink(f"{where} under {root} is a link or a file, not a folder; "
                                     "Temper does not follow links in a member's folder") from None
                raise
            os.close(fd)
            fd = nfd
    except BaseException:
        os.close(fd)
        raise
    return fd


def read_member_bytes(root: Path | str, rel: str | Path, *, limit: int | None = None) -> bytes:
    """The bytes of ``root/rel``, where ``root`` is a member's folder (or a folder in it):
    no component below ``root`` is followed if it is a link, and only a regular file is read.
    Raises :class:`MemberLink` for a link or non-regular file, ``FileNotFoundError`` when it
    is missing."""
    root = Path(root)
    parts = _parts(rel)
    dfd = _open_dir(root, parts[:-1])
    try:
        try:
            fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=dfd)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise MemberLink(f"{'/'.join(parts)} under {root} is a link; Temper does not "
                                 "follow links in a member's folder") from None
            raise
    finally:
        os.close(dfd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise MemberLink(f"{'/'.join(parts)} under {root} is not a regular file: refused")
        chunks, size = [], 0
        while chunk := os.read(fd, _CHUNK):
            chunks.append(chunk)
            size += len(chunk)
            if limit is not None and size > limit:
                raise MemberLink(f"{'/'.join(parts)} under {root} is larger than {limit} bytes")
        return b"".join(chunks)
    finally:
        os.close(fd)


def read_member_text(root: Path | str, rel: str | Path) -> str:
    return read_member_bytes(root, rel).decode("utf-8")


def member_file_sha256(root: Path | str, rel: str | Path) -> str | None:
    """The digest of a member-written file read no-follow; None when missing, a link or not a
    regular file."""
    try:
        return hashlib.sha256(read_member_bytes(root, rel)).hexdigest()
    except OSError:
        return None


def member_entry(root: Path | str, rel: str | Path) -> str:
    """What ``root/rel`` is, without following any link: ``file``, ``dir``, ``link``,
    ``other`` or ``missing``. A link on the way to it counts as ``link``."""
    root = Path(root)
    parts = _parts(rel)
    try:
        dfd = _open_dir(root, parts[:-1])
    except MemberLink:
        return "link"
    except (FileNotFoundError, NotADirectoryError):
        return "missing"
    try:
        st = os.stat(parts[-1], dir_fd=dfd, follow_symlinks=False)
    except FileNotFoundError:
        return "missing"
    finally:
        os.close(dfd)
    if stat.S_ISLNK(st.st_mode):
        return "link"
    if stat.S_ISREG(st.st_mode):
        return "file"
    return "dir" if stat.S_ISDIR(st.st_mode) else "other"


def list_member_dir(root: Path | str, rel: str | Path) -> list[tuple[str, str]]:
    """``(name, kind)`` of each entry of the folder ``root/rel``, read without following any
    link (kinds as :func:`member_entry`). Raises :class:`MemberLink` when the folder itself, or
    one on the way to it, is a link."""
    root = Path(root)
    fd = _open_dir(root, _parts(rel))
    try:
        out = []
        with os.scandir(fd) as listing:
            for entry in listing:
                mode = entry.stat(follow_symlinks=False).st_mode
                kind = ("link" if stat.S_ISLNK(mode) else "file" if stat.S_ISREG(mode)
                        else "dir" if stat.S_ISDIR(mode) else "other")
                out.append((entry.name, kind))
        return sorted(out)
    finally:
        os.close(fd)


def write_member_file(root: Path | str, rel: str | Path, text: str) -> bool:
    """Create ``root/rel`` with ``text`` unless something is already there (a file, or a link:
    never written through), every component below ``root`` opened no-follow. Returns whether
    it was written."""
    root = Path(root)
    parts = _parts(rel)
    dfd = _open_dir(root, parts[:-1])
    try:
        try:
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                         | os.O_CLOEXEC, 0o644, dir_fd=dfd)
        except FileExistsError:
            return False
    finally:
        os.close(dfd)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(text)
    return True
