"""Dedicated hash-only usage-feed credentials; no general API/write authority.

Nothing reads or creates a registry at import. An absent or wholly invalid store
is OFF. The future feed handler must self-authenticate even for in-process calls;
none of the existing general-auth paths consults this module. See
``docs/usage-feed-auth.md`` for custody and the separate operational approvals.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import threading
from collections.abc import Iterable
from pathlib import Path

from temper_ai.api.api_keys import NAME_RE, RESERVED_NAMES, hash_key

logger = logging.getLogger(__name__)

KEYS_FILE_ENV_VAR = "TEMPER_USAGE_FEED_KEYS_FILE"
MAX_FEED_KEYS = 16
_HASH_RE = re.compile(r"sha256:[0-9a-f]{64}")
_lock = threading.Lock()
_last_count: int | None = None


def default_keys_path() -> Path:
    from temper_ai.shared.box_env import default_config_dir

    return default_config_dir() / "api" / "local" / "usage-feed-keys.json"


def keys_path() -> Path:
    raw = os.environ.get(KEYS_FILE_ENV_VAR, "").strip()
    return Path(raw) if raw else default_keys_path()


def valid_name(name: str) -> bool:
    # The grammar itself excludes all reserved colon-prefixed namespaces.
    return bool(NAME_RE.fullmatch(name) and name not in RESERVED_NAMES)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate field")
        result[name] = value
    return result


def parse_keys(text: str) -> tuple[dict[str, str], list[str]]:
    """Validate the WHOLE closed store. Problems are fixed text, never input.

    An empty keys object is valid for removal of the last key, but remains OFF.
    Unlike general api_keys.parse_keys, one invalid entry discards every entry.
    """
    try:
        raw = json.loads(text, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        return {}, ["invalid feed key store"]
    if not isinstance(raw, dict) or set(raw) != {"keys"}:
        return {}, ["invalid feed key store"]
    entries = raw["keys"]
    if not isinstance(entries, dict) or len(entries) > MAX_FEED_KEYS:
        return {}, ["invalid feed key store"]
    keys: dict[str, str] = {}
    for name, value in entries.items():
        if not valid_name(name) or not isinstance(value, str) or not _HASH_RE.fullmatch(value):
            return {}, ["invalid feed key store"]
        keys[name] = value
    return keys, []


def feed_keys() -> dict[str, str]:
    """Fresh name -> hash mapping, or none accepted. Never retain stale authority.

    Read each time (at most 16 valid entries), rather than relying on mtime/size
    alone: an atomic replacement or same-sized edit must revoke on the next call.
    Logging reports only a changed accepted count; no path, name or parse error.
    """
    global _last_count
    try:
        keys, _ = parse_keys(keys_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        keys = {}
    count = len(keys)
    with _lock:
        if count != _last_count:
            if count:
                logger.info("usage feed key store loaded: %d name(s)", count)
            else:
                logger.warning("usage feed key store OFF")
            _last_count = count
    return keys


def identify_feed_key(presented: str | None) -> str | None:
    """Feed principal only, or None. No database, fallback, Caller or write power.

    Refuse other credential classes even if their hash is also in this store.
    Every dedicated hash is compared, without an early return on a match.
    """
    keys = feed_keys()
    if not keys or not presented:
        return None
    from temper_ai.api.run_tokens import is_run_key

    if is_run_key(presented):
        return None
    # Real keys are ASCII. hmac's string comparison of non-ASCII would raise in
    # general auth.identify; malformed headers must instead get the same refusal.
    if not presented.isascii():
        return None
    from temper_ai.api import api_keys, auth

    if auth.identify(presented) is not None:
        return None
    if api_keys.identify_key(presented) is not None:
        return None
    digest = hash_key(presented)
    matched: str | None = None
    for name, stored in keys.items():
        if hmac.compare_digest(digest, stored):
            matched = matched or name
    return matched


def identify_feed_headers(headers: Iterable[tuple[bytes, bytes]]) -> str | None:
    """Headers only: Bearer (even empty) precedes X-Temper-Token, never a cookie."""
    from temper_ai.api.auth import _write_key

    return identify_feed_key(_write_key({"headers": list(headers)}))
