#!/usr/bin/env python3
"""Make, list and remove temper's named API keys (docs/api-access.md).

    python3 scripts/api_key.py add autopilot      # a new key for "autopilot"
    python3 scripts/api_key.py list               # the names the server knows
    python3 scripts/api_key.py remove autopilot   # stops working on the next request

``add`` writes the key itself to ~/.config/temper/api-keys/<name>.key (folder
700, file 600) and only its sha256 to the server's keys file
(configs/api/local/keys.json, git-ignored). The key is never printed: whoever
uses it reads it from its file. Keep that folder out of every path mounted
into temper's containers; this script refuses a key folder inside the repo.

``remove`` drops the name from the keys file (the server re-reads it, no
restart) and deletes the key file.

``--feed`` selects the separate strict hash-only usage-feed registry, never a
general writer. It is inert until a separately authorized host operation; see
docs/usage-feed-auth.md. Raw custody-changing feed operations require read-only
Docker mount inspection, and refuse when that inspection is unavailable.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_KEYS_FILE = REPO / "configs" / "api" / "local" / "keys.json"
DEFAULT_KEY_DIR = Path.home() / ".config" / "temper" / "api-keys"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
RESERVED = {"server", "pickup", "unknown", "shared", "box", "slack", "telegram"}
RESERVED_PREFIXES = ("box:", "slack:", "telegram:", "hook:", "trigger:")


def _load(path: Path) -> dict:
    if not path.is_file():
        return {"keys": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("keys"), dict):
        raise SystemExit(f"{path}: expected {{\"keys\": {{...}}}}; fix it by hand first")
    return data


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o644)  # hashes only: the server's user must read it
    tmp.replace(path)


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def add(name: str, keys_file: Path, key_dir: Path) -> int:
    if not NAME_RE.match(name) or name in RESERVED or name.startswith(RESERVED_PREFIXES):
        print(f"{name!r} is not a usable name (lowercase letters, digits, . _ -)", file=sys.stderr)
        return 2
    if _inside(key_dir, REPO) or _inside(key_dir, Path.home() / "temper-ai"):
        print(f"{key_dir} is inside temper's repo, which is mounted into its containers", file=sys.stderr)
        return 2
    data = _load(keys_file)
    key_file = key_dir / f"{name}.key"
    if name in data["keys"] or key_file.exists():
        print(f"{name} already has a key; remove it first to make a new one", file=sys.stderr)
        return 1
    key_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(key_dir, 0o700)
    raw = "tk_" + secrets.token_urlsafe(32)
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(raw + "\n")
    data["keys"][name] = "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
    _save(keys_file, data)
    print(f"made a key for {name}: {key_file} (600); its hash is in {keys_file}")
    return 0


def remove(name: str, keys_file: Path, key_dir: Path) -> int:
    data = _load(keys_file)
    had = data["keys"].pop(name, None)
    if had is not None:
        _save(keys_file, data)
    key_file = key_dir / f"{name}.key"
    existed = key_file.exists()
    if existed:
        key_file.unlink()
    print(f"{name}: {'removed from the keys file' if had else 'was not in the keys file'}; "
          f"{'key file deleted' if existed else 'no key file'}")
    return 0


def _feed_mount_sources() -> list[Path]:
    """Read-only host custody check; fail closed if current mounts are unknown."""
    worktrees = subprocess.run(
        ["git", "-C", str(REPO), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, check=True, timeout=10,
    )
    roots = [REPO, Path.home() / "temper-ai"]
    roots.extend(Path(line[9:]) for line in worktrees.stdout.splitlines()
                 if line.startswith("worktree "))
    containers = subprocess.run(
        ["docker", "ps", "-aq"], capture_output=True, text=True, check=True, timeout=10,
    ).stdout.split()
    if containers:
        mounts = subprocess.run(
            ["docker", "inspect", "--format", "{{json .Mounts}}", *containers],
            capture_output=True, text=True, check=True, timeout=10,
        )
        lines = mounts.stdout.splitlines()
        if len(lines) != len(containers):
            raise ValueError("mount inspection unavailable")
        for line in lines:
            entries = json.loads(line)
            if not isinstance(entries, list):
                raise ValueError("mount inspection unavailable")
            for entry in entries:
                if isinstance(entry, dict) and entry.get("Type") == "tmpfs":
                    continue  # no host source can contain a raw key
                source = entry.get("Source") if isinstance(entry, dict) else None
                if not isinstance(source, str) or not source.startswith("/"):
                    raise ValueError("mount inspection unavailable")
                roots.append(Path(source))
    return roots


def _feed_registry_safe(keys_file: Path, key_dir: Path) -> None:
    from temper_ai.api import api_keys

    protected = {DEFAULT_KEYS_FILE.resolve(), api_keys.keys_path().resolve(),
                 api_keys.default_keys_path().resolve()}
    tokens_file = os.environ.get("TEMPER_API_TOKENS_FILE", "").strip()
    if tokens_file:
        protected.add(Path(tokens_file).resolve())
    if (keys_file.is_symlink() or keys_file.resolve() in protected
            or _inside(keys_file, key_dir)):
        raise ValueError("feed registry must be separate")


def _feed_load(keys_file: Path) -> dict[str, str]:
    from temper_ai.api.usage_feed_keys import parse_keys

    try:
        text = keys_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    keys, problems = parse_keys(text)
    if problems:
        raise ValueError("invalid feed key store")
    return keys


def _feed_save(keys_file: Path, keys: dict[str, str]) -> None:
    """Atomic hash-only replacement; called while holding the parent-dir lock."""
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=keys_file.parent,
            prefix=".usage-feed-", suffix=".tmp", delete=False,
        ) as handle:
            tmp = Path(handle.name)
            json.dump({"keys": keys}, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fchmod(handle.fileno(), 0o644)  # hashes only: readable by the server
            os.fsync(handle.fileno())
        tmp.replace(keys_file)
        fd = os.open(keys_file.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def _feed_change(action: str, name: str, keys_file: Path, key_dir: Path) -> int:
    from temper_ai.api import api_keys, usage_feed_keys

    if not usage_feed_keys.valid_name(name):
        raise ValueError("invalid feed key name")
    if key_dir.is_symlink() or any(
        _inside(key_dir, root) or _inside(root, key_dir) for root in _feed_mount_sources()
    ):
        raise ValueError("raw feed key directory overlaps a repo or container mount")
    if name in api_keys.named_keys():
        raise ValueError("name belongs to a general API key")
    # Lock the existing hash directory, not a new persistent lock/state store.
    # All supported feed writers serialize even when --key-dir differs.
    if action == "add":
        keys_file.parent.mkdir(parents=True, exist_ok=True)
    elif not keys_file.parent.exists():
        print("feed key was not registered; no raw file changed")
        return 0
    lock_fd = os.open(keys_file.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        keys = _feed_load(keys_file)
        key_file = key_dir / f"{name}.key"
        if action == "remove":
            if name not in keys:
                print("feed key was not registered; no raw file changed")
                return 0
            del keys[name]
            _feed_save(keys_file, keys)  # revoke before unlink; no activation on unlink error
            key_file.unlink(missing_ok=True)
            print("feed key removed")
            return 0
        if name in keys or key_file.exists() or key_file.is_symlink():
            raise ValueError("feed key already exists")
        if len(keys) >= usage_feed_keys.MAX_FEED_KEYS:
            raise ValueError("feed key store is full")
        key_dir.mkdir(parents=True, exist_ok=True)
        if key_dir.stat().st_uid != os.getuid():
            raise ValueError("raw feed key directory has a different owner")
        os.chmod(key_dir, 0o700)
        raw = "tk_" + secrets.token_urlsafe(32)
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(raw + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            keys[name] = api_keys.hash_key(raw)
            _feed_save(keys_file, keys)
        except (OSError, ValueError):
            key_file.unlink(missing_ok=True)  # only the file created by this invocation
            raise
        print("feed key added")
        return 0
    finally:
        os.close(lock_fd)


def feed_command(action: str, name: str | None, keys_file: Path, key_dir: Path) -> int:
    """Strict feed branch. Errors never print input, credentials or exception text."""
    try:
        _feed_registry_safe(keys_file, key_dir)
        if action == "list":
            for registered in sorted(_feed_load(keys_file)):
                print(registered)
            return 0
        return _feed_change(action, name or "", keys_file, key_dir)
    except (OSError, ValueError, subprocess.SubprocessError):
        print("feed key operation refused", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("add", "remove", "list"))
    parser.add_argument("name", nargs="?")
    parser.add_argument("--keys-file", type=Path)
    parser.add_argument("--key-dir", type=Path, default=DEFAULT_KEY_DIR)
    parser.add_argument("--feed", action="store_true", help="dedicated feed registry; no general API authority")
    args = parser.parse_args(argv)
    if args.action != "list" and not args.name:
        parser.error(f"{args.action} needs a name")
    if args.feed:
        # Standalone host invocation need not have the package installed.
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from temper_ai.api.usage_feed_keys import keys_path

        return feed_command(args.action, args.name, args.keys_file or keys_path(), args.key_dir)
    keys_file = args.keys_file or DEFAULT_KEYS_FILE
    if args.action == "list":
        for name in sorted(_load(keys_file)["keys"]):
            print(name)
        return 0
    if args.action == "add":
        return add(args.name, keys_file, args.key_dir)
    return remove(args.name, keys_file, args.key_dir)


if __name__ == "__main__":
    raise SystemExit(main())
