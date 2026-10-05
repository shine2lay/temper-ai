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
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("add", "remove", "list"))
    parser.add_argument("name", nargs="?")
    parser.add_argument("--keys-file", type=Path, default=DEFAULT_KEYS_FILE)
    parser.add_argument("--key-dir", type=Path, default=DEFAULT_KEY_DIR)
    args = parser.parse_args(argv)
    if args.action == "list":
        for name in sorted(_load(args.keys_file)["keys"]):
            print(name)
        return 0
    if not args.name:
        parser.error(f"{args.action} needs a name")
    if args.action == "add":
        return add(args.name, args.keys_file, args.key_dir)
    return remove(args.name, args.keys_file, args.key_dir)


if __name__ == "__main__":
    raise SystemExit(main())
