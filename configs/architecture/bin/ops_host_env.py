"""P4: pure Env data comparator for the ops host client (ABI A5, CASE F4).

Compares exact Env arrays a caller supplies (image baseline, recorded creation array, later
observed array) and returns an immutable, always UNTRUSTED EnvAssessment. It never collects
anything: no Docker, files, network, subprocess or clock. An argument named image_env is data,
not proof of image authenticity or order; P5 proves the baseline array, its order and the
creation inputs on its own.

Received semantics (Ops429 P4-01..12) are kept as written: tokens split at the first '=' only,
nonempty key, no NUL, empty values and further '=' kept; no normalization, filtering, sorting,
deduplication or last-wins; missing or malformed input refuses instead of defaulting; the APP
gets exactly four overrides on top of the full inherited baseline, the forwarder gets none; a
well-formed duplicate in a container array is an env mismatch; initial map equivalence, then
full ordered equality of the later array with the recorded creation array. A5 is separate:
its own key regex, duplicate refusal, four-key baseline exclusion and mandatory argv/env data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A7 closed refusal vocabulary, in A7 order. This module itself raises only EVIDENCE_INVALID.
REFUSAL_CODES = (
    "TARGET_CONTEXT_MISSING",
    "TARGET_ISSUER_UNTRUSTED",
    "TARGET_PUBLICATION_INVALID",
    "TARGET_SELECTOR_MISSING",
    "TARGET_SELECTOR_AMBIGUOUS",
    "TARGET_BINDING_INVALID",
    "TARGET_SCHEMA_MISMATCH",
    "TARGET_SOURCE_MISSING",
    "TARGET_SOURCE_DRIFT",
    "TARGET_REVIEW_MISSING",
    "TARGET_EVIDENCE_INVALID",
)
EVIDENCE_INVALID = "TARGET_EVIDENCE_INVALID"

REASONS = ("NONE", "ENV_VALUE", "ENV_DUPLICATE", "ENV_ORDER")
TRUST = "UNTRUSTED"
TARGETS = ("app", "forwarder")

# Bound on one array's total UTF-8 bytes: hostproto MAX_SNAPSHOT, the limit of any snapshot that
# carries these arrays. Over it refuses; nothing is ever truncated into success.
MAX_ARRAY_BYTES = 1048576
PORT_MIN, PORT_MAX = 1, 65535

# A5 only (create_spec): key grammar and the four APP keys a baseline may not carry.
A5_KEY = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
APP_KEYS = ("HOST", "PORT", "DATA_DIR", "ALLOWED_HOSTS")
_APP_ADDRESS = "100.110.162.4"


class TargetRefused(ValueError):
    """Local fixed refusal: args, str and repr carry exactly the code, never a value or path."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in REFUSAL_CODES:
            raise ValueError("unknown refusal code")
        super().__init__(code)
        self._code = code

    @property
    def code(self) -> str:
        return self._code


@dataclass(frozen=True, slots=True)
class EnvAssessment:
    """Comparison result: fixed reason only, no Env content. Never trusted on its own."""

    trust: str
    env_matches: bool
    creation_matches: bool
    reason: str

    def __post_init__(self) -> None:
        consistent = (
            type(self.trust) is str
            and self.trust == TRUST
            and type(self.env_matches) is bool
            and type(self.creation_matches) is bool
            and type(self.reason) is str
            and self.reason in REASONS
            and (self.reason == "NONE") is self.env_matches
            and (self.creation_matches or not self.env_matches)
            and (self.reason != "ENV_ORDER" or not self.creation_matches)
        )
        if not consistent:
            raise TargetRefused(EVIDENCE_INVALID)


def _utf8_size(item: str) -> int:
    """Encoded size, or -1 for text that is not valid UTF-8 (lone surrogates)."""
    try:
        return len(item.encode("utf-8"))
    except UnicodeEncodeError:
        return -1


def _strings(value: object) -> tuple[str, ...]:
    """Exact tuple of exact nonempty, NUL-free, valid UTF-8 str, bounded; else refuse."""
    if type(value) is not tuple or len(value) > MAX_ARRAY_BYTES:
        raise TargetRefused(EVIDENCE_INVALID)
    total = 0
    for item in value:
        if type(item) is not str or not item or "\x00" in item:
            raise TargetRefused(EVIDENCE_INVALID)
        size = _utf8_size(item)
        if size < 0:
            raise TargetRefused(EVIDENCE_INVALID)
        total += size
        if total > MAX_ARRAY_BYTES:
            raise TargetRefused(EVIDENCE_INVALID)
    return value


def _pairs(value: object) -> tuple[tuple[str, str], ...]:
    """Generic Config.Env grammar: split at the first '=' only, nonempty key, value kept as is."""
    pairs = []
    for item in _strings(value):
        key, sep, rest = item.partition("=")
        if not sep or not key:
            raise TargetRefused(EVIDENCE_INVALID)
        pairs.append((key, rest))
    return tuple(pairs)


def _a5_pairs(value: object) -> tuple[tuple[str, str], ...]:
    """A5 grammar: generic tokens whose keys match the A5 regex, with no duplicate key."""
    pairs = _pairs(value)
    seen = set()
    for key, _ in pairs:
        if A5_KEY.fullmatch(key) is None or key in seen:
            raise TargetRefused(EVIDENCE_INVALID)
        seen.add(key)
    return pairs


def _unique_map(pairs: tuple[tuple[str, str], ...]) -> dict[str, str] | None:
    """Map of a duplicate-free array; None when any key repeats (never last-wins)."""
    result: dict[str, str] = {}
    for key, val in pairs:
        if key in result:
            return None
        result[key] = val
    return result


def _ordered_equal(observed: tuple[str, ...], creation: tuple[str, ...]) -> bool:
    """Later observation equals the recorded creation array: every token, in order."""
    return observed == creation


def _verdict(
    expected: dict[str, str],
    creation_pairs: tuple[tuple[str, str], ...],
    observed_pairs: tuple[tuple[str, str], ...],
    creation_env: tuple[str, ...],
    observed_env: tuple[str, ...],
    *,
    argv_matches: bool,
) -> EnvAssessment:
    """Initial map equivalence for both arrays, then full ordered equality; fixed reason only."""
    creation_map = _unique_map(creation_pairs)
    observed_map = _unique_map(observed_pairs)
    creation_matches = _ordered_equal(observed_env, creation_env)
    if creation_map is None or observed_map is None:
        reason = "ENV_DUPLICATE"
    elif not argv_matches or creation_map != expected or observed_map != expected:
        reason = "ENV_VALUE"
    elif not creation_matches:
        reason = "ENV_ORDER"
    else:
        reason = "NONE"
    return EnvAssessment(TRUST, reason == "NONE", creation_matches, reason)


def _app_overrides(port: int) -> dict[str, str]:
    """The exact four APP overrides (the window runtime env); nothing inherited."""
    return {
        "HOST": "0.0.0.0",
        "PORT": "8000",
        "DATA_DIR": "/data",
        "ALLOWED_HOSTS": f"{_APP_ADDRESS}:{port},scanapp:8080",
    }


def compare_window_env(image_env: tuple, creation_env: tuple, observed_env: tuple, *, target: str, port: int) -> EnvAssessment:
    """Window app/forwarder Env: full image baseline (+ four APP overrides), then order."""
    image_pairs = _pairs(image_env)
    creation_pairs = _pairs(creation_env)
    observed_pairs = _pairs(observed_env)
    if type(target) is not str or target not in TARGETS:
        raise TargetRefused(EVIDENCE_INVALID)
    if type(port) is not int or not PORT_MIN <= port <= PORT_MAX:
        raise TargetRefused(EVIDENCE_INVALID)
    expected = _unique_map(image_pairs)
    if expected is None:
        raise TargetRefused(EVIDENCE_INVALID)
    if target == "app":
        expected.update(_app_overrides(port))
    return _verdict(expected, creation_pairs, observed_pairs, creation_env, observed_env, argv_matches=True)


def compare_a5_env(
    image_env: tuple,
    creation_env: tuple,
    observed_env: tuple,
    *,
    expected_argv: tuple,
    observed_argv: tuple,
    expected_env: tuple,
) -> EnvAssessment:
    """A5 holder/case: separately frozen argv/env supplied as data; nothing here is a recipe."""
    image_pairs = _a5_pairs(image_env)
    creation_pairs = _a5_pairs(creation_env)
    observed_pairs = _a5_pairs(observed_env)
    recipe_pairs = _a5_pairs(expected_env)
    if not _strings(expected_argv):
        raise TargetRefused(EVIDENCE_INVALID)
    _strings(observed_argv)
    if any(key in APP_KEYS for key, _ in image_pairs):
        raise TargetRefused(EVIDENCE_INVALID)
    expected = dict(image_pairs)
    expected.update(recipe_pairs)
    argv_matches = observed_argv == expected_argv
    return _verdict(expected, creation_pairs, observed_pairs, creation_env, observed_env, argv_matches=argv_matches)
