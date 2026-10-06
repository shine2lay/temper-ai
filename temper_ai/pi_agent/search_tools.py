"""Static rg and fd for Pi's grep and find inside the sealed, offline worker box (queue #47).

Pi 0.87.1's ``grep`` tool runs ripgrep (``rg``) and its ``find`` tool runs ``fd``. Pi looks for
each in its own tools folder (``/w/agent/bin``, made fresh at every start, so always empty), then
runs ``rg --version`` / ``fd --version`` on ``PATH``, and would otherwise download it. The box
can't download (``--network none``, ``PI_OFFLINE=1``) and its image has neither, so without
these two binaries both tools always fail (M2-roles finding P1).

The fix puts both at the top level of a pinned runtime folder: ``/pi-runtime/rg`` and
``/pi-runtime/fd`` in the box, where ``/pi-runtime`` is first on the box ``PATH``. Pi's code is
unchanged; it finds them by itself. ``scripts/pi_search_tools.py`` makes such a runtime on the
host, from these pins, as a new read-only copy of an existing runtime; nothing downloads at run
time.

Three records hold the same versions and digests:

* :data:`PINS` here (the download: release URL, archive digest, the binary's path in the
  archive and its own digest);
* the runtime folder's manifest, ``search-tools.json``, written by the script;
* the worker box config's ``search_tools`` block, ``{name: {version, sha256}}``, next to
  ``runtime_dir`` and ``pi_version``. :class:`temper_ai.pi_agent.box.BoxConfig` checks the
  binaries against it on the host when the config loads and again before every turn's
  read-only mount.

Official static musl builds for aarch64 only (spark is arm64); the script refuses any other
machine.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

#: The only machine the pinned builds run on (``platform.machine()`` on the host).
MACHINE = "aarch64"
#: Pi's tools that need a search binary, and the binary each one runs.
TOOL_NEEDS: dict[str, str] = {"grep": "rg", "find": "fd"}
#: The script that makes a runtime with them (named in every refusal).
SCRIPT = "scripts/pi_search_tools.py"
#: The manifest the script writes at the new runtime's top level.
MANIFEST = "search-tools.json"


@dataclass(frozen=True)
class SearchBinary:
    """One pinned search binary: where it comes from and the digests it must have."""

    #: The file name at the runtime folder's top level (``/pi-runtime/<name>`` in the box).
    name: str
    version: str
    #: The first line of ``<name> --version`` for this build (read back in the box test).
    version_line: str
    url: str
    #: The release asset's digest (GitHub's asset digest).
    archive_sha256: str
    #: The binary's path inside the archive; nothing else is taken out.
    member: str
    #: The binary's own digest, worked out once from the verified archive.
    sha256: str


PINS: dict[str, SearchBinary] = {
    "rg": SearchBinary(
        name="rg", version="15.2.0", version_line="ripgrep 15.2.0 (rev e89fff89ac)",
        url="https://github.com/BurntSushi/ripgrep/releases/download/15.2.0/"
            "ripgrep-15.2.0-aarch64-unknown-linux-musl.tar.gz",
        archive_sha256="800b1e7206afe799dfb5a6901f23147cfaabe0e52210538100f61e86e1740915",
        member="ripgrep-15.2.0-aarch64-unknown-linux-musl/rg",
        sha256="c14cdb389f34e504d69e386cfc67d5c5d9a730a990de03ca6910b2a15e30386a"),
    "fd": SearchBinary(
        name="fd", version="10.5.0", version_line="fd 10.5.0",
        url="https://github.com/sharkdp/fd/releases/download/v10.5.0/"
            "fd-v10.5.0-aarch64-unknown-linux-musl.tar.gz",
        archive_sha256="d76c4317f7d5dba69f8a2a15856c90c777e7f0dd4e85f0de8c76de6992c374d4",
        member="fd-v10.5.0-aarch64-unknown-linux-musl/fd",
        sha256="90dab774d92889926d75a85b47c4b2dc4c9adfa792cd3a6ccfcb98b0eabc9b94"),
}


def search_tool_problems(tools: Iterable[str], cfg: Any) -> list[str]:
    """Why Pi tools in ``tools`` would always fail in the worker box ``cfg``: ``grep`` without
    ``rg`` pinned, ``find`` without ``fd`` pinned (empty when none would). Checks the box
    config's ``search_tools`` block only; the binaries' digests are the config's own check."""
    pinned = getattr(cfg, "search_tools", None) or {}
    wanted = set(tools)
    return [f"Pi's {tool} tool needs {binary}, which the worker box config doesn't pin "
            f"(search_tools); make a runtime with {SCRIPT} and point the box config at it"
            for tool, binary in TOOL_NEEDS.items() if tool in wanted and binary not in pinned]
