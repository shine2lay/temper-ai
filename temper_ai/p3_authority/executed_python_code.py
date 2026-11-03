"""Which bytes CPython executes for a source module: its cached ``.pyc`` or the ``.py`` source.

N3 worker closure (T5-N3W; Architecture #485 C8, Systems rm-f8ac59b5): a stale but
valid ``__pycache__`` .pyc (source ``X = 1``, pyc ``X = 2``, same size and mtime) runs
instead of its source, and ``python -B`` does not stop .pyc reads. An observer that
hashes only the source reports the reviewed bytes and the comparator returns a false
MATCH. The comparator catches it only when the observer reports what CPython executed.

``executed_python_code`` makes CPython's own ``SourceFileLoader`` decision over the
worker's files and interpreter flags: where the .pyc lives (``__pycache__`` or the
``pycache_prefix`` tree, with the optimization tag), and whether it is used (magic
number, flags, then the source's mtime and size for a timestamp .pyc, or the source
hash for a checked hash-based .pyc). ``observe_python_module_execution`` turns that
decision into the ``ObservedLoad`` the worker closure collector records: a ``cache``
event for the reviewed ``cached_code`` node carrying the .pyc bytes, or a ``load`` of
the source node carrying the source bytes. Running the worker with
``-X pycache_prefix=<empty dir>`` means no .pyc is found, so the source is what runs.

It decides as this interpreter's importlib does (``importlib.util.MAGIC_NUMBER``,
``sys.implementation.cache_tag``, ``importlib.util.source_hash``): call it under the
worker's interpreter. The worker's runtime flags are explicit arguments, never read
from this process. Inert: nothing in production calls it.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from temper_ai.p3_authority.contract import Boundary, Refusal, RefusalCode
from temper_ai.p3_authority.coverage_bookkeeping import make_refusal
from temper_ai.p3_authority.worker_closure_capture import (
    ObservedLoad,
    byte_content_identity,
)

HashBasedPycCheck = Literal["default", "always", "never"]
Optimization = Literal["", "1", "2"]

_PYC_HEADER_SIZE = 16
_FLAG_HASH_BASED = 0b01
_FLAG_CHECK_SOURCE = 0b10
_KNOWN_FLAGS = _FLAG_HASH_BASED | _FLAG_CHECK_SOURCE
_UINT32_MASK = 0xFFFFFFFF


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutedPythonCode:
    """What CPython runs for one source module: the bytes and the file they came from."""

    representation: Literal["source", "cached"]
    path: Path
    raw: bytes


def _validate_flags(
    source_path: Path,
    pycache_prefix: Path | None,
    optimization: str,
    check_hash_based_pycs: str,
) -> None:
    if not isinstance(source_path, Path) or not source_path.is_absolute():
        raise ValueError("source_path must be an absolute Path")
    if pycache_prefix is not None and (
        not isinstance(pycache_prefix, Path) or not pycache_prefix.is_absolute()
    ):
        raise ValueError("pycache_prefix must be None or an absolute Path")
    if optimization not in ("", "1", "2"):
        raise ValueError("optimization must be '', '1' or '2' (the worker's -O level)")
    if check_hash_based_pycs not in ("default", "always", "never"):
        raise ValueError("check_hash_based_pycs must be 'default', 'always' or 'never'")


def cached_python_code_path(
    source_path: Path,
    *,
    pycache_prefix: Path | None = None,
    optimization: Optimization = "",
) -> Path | None:
    """Where CPython looks for the .pyc of ``source_path``; ``None`` if it caches nothing.

    Same rule as ``importlib.util.cache_from_source``, with the worker's
    ``sys.pycache_prefix`` and optimization level given instead of this process's.
    """
    _validate_flags(source_path, pycache_prefix, optimization, "default")
    cache_tag = sys.implementation.cache_tag
    if cache_tag is None:
        return None
    base, dot, rest = source_path.name.rpartition(".")
    name = f"{base if base else rest}{dot}{cache_tag}"
    if optimization:
        name = f"{name}.opt-{optimization}"
    name += importlib.machinery.BYTECODE_SUFFIXES[0]
    if pycache_prefix is None:
        return source_path.parent / "__pycache__" / name
    return pycache_prefix / str(source_path.parent).lstrip(os.sep) / name


def _cached_code_is_used(
    data: bytes,
    *,
    source_mtime: float,
    source_size: int,
    source_raw: bytes,
    check_hash_based_pycs: HashBasedPycCheck,
) -> bool:
    """CPython's header checks: an invalid .pyc falls back to the source."""
    if len(data) < _PYC_HEADER_SIZE or data[:4] != importlib.util.MAGIC_NUMBER:
        return False
    flags = int.from_bytes(data[4:8], "little")
    if flags & ~_KNOWN_FLAGS:
        return False
    if flags & _FLAG_HASH_BASED:
        check_source = bool(flags & _FLAG_CHECK_SOURCE)
        if check_hash_based_pycs != "never" and (
            check_source or check_hash_based_pycs == "always"
        ):
            return data[8:16] == importlib.util.source_hash(source_raw)
        return True
    return int.from_bytes(data[8:12], "little") == (
        int(source_mtime) & _UINT32_MASK
    ) and int.from_bytes(data[12:16], "little") == (source_size & _UINT32_MASK)


def executed_python_code(
    source_path: Path,
    *,
    pycache_prefix: Path | None = None,
    optimization: Optimization = "",
    check_hash_based_pycs: HashBasedPycCheck = "default",
) -> ExecutedPythonCode:
    """The bytes CPython executes when it imports ``source_path`` with these flags.

    A valid .pyc at ``cached_python_code_path`` runs instead of the source, even a
    stale one whose recorded mtime and size match. Raises ``OSError`` if the source
    can't be read, ``ValueError`` on a bad argument.
    """
    _validate_flags(source_path, pycache_prefix, optimization, check_hash_based_pycs)
    source_raw = source_path.read_bytes()
    stat = source_path.stat()
    pyc_path = cached_python_code_path(
        source_path, pycache_prefix=pycache_prefix, optimization=optimization
    )
    if pyc_path is not None:
        try:
            data = pyc_path.read_bytes()
        except OSError:
            data = None
        if data is not None and _cached_code_is_used(
            data,
            source_mtime=stat.st_mtime,
            source_size=stat.st_size,
            source_raw=source_raw,
            check_hash_based_pycs=check_hash_based_pycs,
        ):
            return ExecutedPythonCode(representation="cached", path=pyc_path, raw=data)
    return ExecutedPythonCode(representation="source", path=source_path, raw=source_raw)


def observe_python_module_execution(
    *,
    source_node_id: str,
    cached_node_id: str | None,
    source_path: Path,
    boundary: Boundary,
    pycache_prefix: Path | None = None,
    optimization: Optimization = "",
    check_hash_based_pycs: HashBasedPycCheck = "default",
) -> ObservedLoad | Refusal:
    """The observed load for one imported module: what CPython executed, never the name.

    - a used .pyc -> ``ObservedLoad(event_kind="cache")`` for ``cached_node_id`` with
      the .pyc bytes (a stale .pyc then compares BYTE_SUBSTITUTION + CACHED_CODE);
    - a used .pyc with no reviewed cached node -> ``CLOSURE_MISMATCH`` (unreviewed
      cached code runs);
    - otherwise -> ``ObservedLoad(event_kind="load")`` for ``source_node_id`` with the
      source bytes;
    - an unreadable source -> ``OBSERVATION_GAP``.
    """
    if not isinstance(source_node_id, str) or not source_node_id:
        raise ValueError("source_node_id must be a non-empty string")
    if cached_node_id is not None and (
        not isinstance(cached_node_id, str) or not cached_node_id
    ):
        raise ValueError("cached_node_id must be None or a non-empty string")
    try:
        executed = executed_python_code(
            source_path,
            pycache_prefix=pycache_prefix,
            optimization=optimization,
            check_hash_based_pycs=check_hash_based_pycs,
        )
    except OSError:
        return make_refusal(RefusalCode.OBSERVATION_GAP, boundary)
    if executed.representation == "source":
        return ObservedLoad(
            node_id=source_node_id, loaded=byte_content_identity(executed.raw)
        )
    if cached_node_id is None:
        return make_refusal(RefusalCode.CLOSURE_MISMATCH, boundary)
    return ObservedLoad(
        node_id=cached_node_id,
        loaded=byte_content_identity(executed.raw),
        event_kind="cache",
    )
