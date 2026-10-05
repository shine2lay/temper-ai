"""Named API keys for actions that change state, stored as hashes only.

The keys file (``TEMPER_API_KEYS_FILE``, else ``configs/api/local/keys.json``)
holds one sha256 per name::

    {"keys": {"owner-dashboard": "sha256:9f86d0...", "autopilot": "sha256:..."}}

The keys themselves never reach the server: each lives in a file of its
own on the machine, readable by its user only, outside every folder mounted
into the server, the worker or a run's box (scripts/api_key.py makes them).
A box that can read this file learns nothing it could send.

Re-read when the file changes, so removing a name stops its key on the next
request, with no restart. A missing file means no named keys; an unreadable
one means none accepted, logged, never raised.

Unlike TEMPER_API_TOKEN / TEMPER_API_TOKENS_FILE (api/auth.py), these keys
do not close the API to reads: they name whoever changes something.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

KEYS_FILE_ENV_VAR = "TEMPER_API_KEYS_FILE"
HASH_PREFIX = "sha256:"
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
# Names the server gives callers itself; a key may not pose as one of them.
RESERVED_PREFIXES = ("box:", "slack:", "telegram:", "hook:", "trigger:")
RESERVED_NAMES = frozenset({"server", "pickup", "carry-on", "unknown", "shared", "box", "slack",
                            "telegram"})

_lock = threading.Lock()
_cache: tuple[str, tuple[int, int], dict[str, str]] | None = None


def default_keys_path() -> Path:
    from temper_ai.shared.box_env import default_config_dir

    return default_config_dir() / "api" / "local" / "keys.json"


def keys_path() -> Path:
    raw = os.environ.get(KEYS_FILE_ENV_VAR, "").strip()
    return Path(raw) if raw else default_keys_path()


def hash_key(raw: str) -> str:
    """The stored form of a key."""
    return HASH_PREFIX + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_keys(text: str) -> tuple[dict[str, str], list[str]]:
    """(name -> hash, problems) from the file's text. Bad entries are left out."""
    problems: list[str] = []
    try:
        raw = json.loads(text)
    except ValueError as exc:
        return {}, [f"not JSON: {exc}"]
    entries = raw.get("keys") if isinstance(raw, dict) else None
    if not isinstance(entries, dict):
        return {}, ['expected {"keys": {"<name>": "sha256:<64 hex>"}}']
    keys: dict[str, str] = {}
    for name, value in entries.items():
        name = str(name)
        if not NAME_RE.match(name) or name in RESERVED_NAMES or name.startswith(RESERVED_PREFIXES):
            problems.append(f"{name!r}: not a usable name (lowercase letters, digits, . _ -; not a name the server gives)")
            continue
        if not isinstance(value, str) or not _HASH_RE.match(value.strip()):
            problems.append(f"{name!r}: the value must be sha256:<64 hex>, the key's hash, never the key itself")
            continue
        keys[name] = value.strip()
    return keys, problems


def named_keys() -> dict[str, str]:
    """name -> stored hash, re-read whenever the file changes."""
    global _cache
    path = keys_path()
    try:
        st = path.stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        with _lock:
            if _cache is not None and _cache[2]:
                logger.warning("API keys file %s is gone; no named keys accepted", path)
            _cache = (str(path), (0, 0), {})
        return {}
    with _lock:
        if _cache is not None and _cache[0] == str(path) and _cache[1] == stamp:
            return _cache[2]
    try:
        keys, problems = parse_keys(path.read_text(encoding="utf-8"))
    except OSError as exc:
        keys, problems = {}, [str(exc)]
    for problem in problems:
        logger.warning("API keys file %s: %s", path, problem)
    logger.info("API keys file %s loaded: %d name(s)", path, len(keys))
    with _lock:
        _cache = (str(path), stamp, keys)
    return keys


def identify_key(presented: str | None) -> str | None:
    """The name whose key was presented, or None.

    Every stored hash is compared, in constant time, so the reply time says
    nothing about which name matched or how far down the list it was.
    """
    if not presented:
        return None
    digest = hash_key(presented)
    matched: str | None = None
    for name, stored in named_keys().items():
        if hmac.compare_digest(digest, stored):
            matched = matched or name
    return matched


def check_keys_file(path: str | Path | None = None) -> list[str]:
    """Problems with the keys file, for ``temper check`` (none when it is absent)."""
    target = Path(path) if path is not None else keys_path()
    if not target.is_file():
        return []
    try:
        _, problems = parse_keys(target.read_text(encoding="utf-8"))
    except OSError as exc:
        return [f"{target}: {exc}"]
    return [f"{target}: {p}" for p in problems]


# --- the client side: which key a temper client sends ------------------------------------------

CLIENT_KEY_FILE_ENV_VAR = "TEMPER_API_KEY_FILE"


def client_key(environ: dict[str, str] | None = None) -> str | None:
    """The key a temper client (``temper run``, the MCP bridge, temper-ci) sends, if any.

    In order: the file named by TEMPER_API_KEY_FILE (a named key, read from
    its file each time, never kept in the environment), the run's own key
    TEMPER_RUN_TOKEN (a script step of a ``starts_runs`` workflow), then
    TEMPER_API_TOKEN (the all-routes token, api/auth.py). None when there is
    none: inside the server's own container that is the caller "server".
    """
    env = os.environ if environ is None else environ
    path = (env.get(CLIENT_KEY_FILE_ENV_VAR) or "").strip()
    if path:
        try:
            value = Path(path).expanduser().read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("%s=%s can't be read (%s); sending no key", CLIENT_KEY_FILE_ENV_VAR, path,
                           type(exc).__name__)
            value = ""
        if value:
            return value
    for name in ("TEMPER_RUN_TOKEN", "TEMPER_API_TOKEN"):
        value = (env.get(name) or "").strip()
        if value:
            return value
    return None


def _reset_for_tests() -> None:
    global _cache
    with _lock:
        _cache = None
