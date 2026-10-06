"""A run's box profile, schema version 2: what its box is, settled before the box exists.

Box secrets design v2 (docs/boxes.md, "The box profile") closes what a run's box can
reach in six steps, each behind a setting of its own. Every setting defaults to how
boxes worked before:

  BS1  TEMPER_BOX_RUNTIME_BOUNDARY   legacy | sealed    built
  BS2  TEMPER_BOX_SECRET_BOOTSTRAP   env                not built yet
  BS3  TEMPER_BOX_CAPABILITIES       legacy             not built yet
  BS4  TEMPER_BOX_STATE_ACCESS       legacy             not built yet
  BS5  TEMPER_BOX_TOOL_ISOLATION     in_process         not built yet
  BS6  TEMPER_BOX_MODEL_ACCESS       direct             not built yet

A step that is not built refuses any other value: a setting that claims more than
the code does would be worse than none.

The trusted worker (or the server, when it spawns runs itself) compiles one profile
per box before `docker run`, from its own settings, the template container, the
launch's classification (box_launches.py) and, for a sealed box, the mount plan
(box_seal.py). Nothing a run controls goes in: not agent YAML, not workspace files,
not run output. The profile's digest and generation are stored on the run's row
(spawner_metadata["box_profile"]) and handed to the box, which checks both before
anything else happens (box_view.py, run_workflow.py). Each new box for the same run
(a resume, a replacement, a takeover) gets the next generation; an older box that
finds a newer generation on the row stops without touching it. A run that ever had
a sealed box never gets a legacy one: rolling back means a fresh run.

BS1 alone is partial hardening. Every profile says so, and lists what is still as
before: BS2-BS6, and a network graph recorded as mixed, not closed.
"""

from __future__ import annotations

import hashlib
import os
import socket
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from temper_ai.shared.clock import utcnow
from temper_ai.spawner.base import SpawnerError
from temper_ai.spawner.box_view import (
    DIGEST_ENV,
    GENERATION_ENV,
    PROFILE_ENV,
    SCHEMA_VERSION,
    SEALED,
    BoxStartRefused,
    canonical,
    digest_of,
    profile_from_env,
)

__all__ = ["BoxStartRefused", "canonical", "digest_of", "profile_from_env"]

METADATA_KEY = "box_profile"
BOUNDARY_ENV = "TEMPER_BOX_RUNTIME_BOUNDARY"
LEGACY = "legacy"

#: How a sealed profile names itself: its class comes from the gate's rules, and no
#: Security review of any profile or launch stands behind it.
SEALED_LABEL = ("sealed (BS1-partial): gate-classified, not reviewed by Security; still open: "
                "the runner's environment and memory secrets, the run's GitHub key among them "
                "(BS2), database and Redis reach (BS4, BS5), the network (BS5)")
LEGACY_LABEL = "legacy: the box gets the template's mounts as they are"

#: (setting, step, default, values built so far)
SETTINGS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (BOUNDARY_ENV, "BS1", LEGACY, (LEGACY, SEALED)),
    ("TEMPER_BOX_SECRET_BOOTSTRAP", "BS2", "env", ("env",)),
    ("TEMPER_BOX_CAPABILITIES", "BS3", "legacy", ("legacy",)),
    ("TEMPER_BOX_STATE_ACCESS", "BS4", "legacy", ("legacy",)),
    ("TEMPER_BOX_TOOL_ISOLATION", "BS5", "in_process", ("in_process",)),
    ("TEMPER_BOX_MODEL_ACCESS", "BS6", "direct", ("direct",)),
)

#: What stays as before after BS1, whichever boundary the box has.
LATER_STEPS = (
    ("BS2", "the runner's environment and memory hold its secrets, the run's GitHub key "
            "(TEMPER_RUN_GITHUB_KEY) among them; its tools can read them through /proc "
            "(same user)"),
    ("BS3", "integrations, messaging and Penpot work with the box's own keys"),
    ("BS4", "the runner and its tools reach the database with the shared login, and Redis "
            "with no password (BS4 brings a restricted login and a Redis broker; tools still "
            "reach SQL until BS5)"),
    ("BS5", "tools run in the runner's own container (same pid, mount and network "
            "namespace), and the box's network is open"),
    ("BS6", "model calls use upstream credentials inside the box; the Claude CLI holds a token"),
)


class BoxProfileError(SpawnerError):
    """The profile can't be compiled, or refuses this launch. Said in plain words."""


class BoxIsStale(Exception):
    """A newer box has the run now: this one stops without touching its row."""


# -- settings -----------------------------------------------------------------------------


def install_settings(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The six settings as this install has them, or BoxProfileError for a value not built."""
    env = os.environ if environ is None else environ
    settings: dict[str, str] = {}
    for name, step, default, built in SETTINGS:
        value = (env.get(name) or "").strip().lower() or default
        if value not in built:
            known = " or ".join(built)
            raise BoxProfileError(
                f"{name}={value!r} is not something this temper can do ({step}: {known}); "
                "no run can start until it is unset or set to one of those",
            )
        settings[name] = value
    return settings


def boundary_setting(environ: Mapping[str, str] | None = None) -> str:
    """legacy or sealed, as the install asks (BoxProfileError for anything else)."""
    return install_settings(environ)[BOUNDARY_ENV]


def refuse_unboxed_under_sealed(how: str, environ: Mapping[str, str] | None = None) -> None:
    """A sealed install runs every run in a docker box: anything else is refused, never a fallback.

    ``how`` names what was about to run the workflow (the subprocess spawner, the server's
    own process). Explicit no-socket development counts as unboxed too.
    """
    if boundary_setting(environ) == SEALED:
        raise BoxProfileError(
            f"{BOUNDARY_ENV}=sealed runs workflows only in docker boxes (TEMPER_SPAWNER=docker, "
            f"TEMPER_EXECUTION_MODE=external or subprocess); {how} has no box, so the run is refused",
        )


# -- digests ------------------------------------------------------------------------------


def tree_digest(root: str | Path, *, only: Iterable[str] | None = None) -> str:
    """sha256 over a tree's files (relative path + content), __pycache__ left out.

    ``only`` limits it to those entries directly under ``root`` (files or folders).
    Symlinks count by their target text, never followed.
    """
    base = Path(root)
    h = hashlib.sha256()
    tops = sorted(only) if only is not None else None
    starts = [base / t for t in tops] if tops is not None else [base]
    for start in starts:
        if start.is_symlink() or start.is_file():
            _digest_entry(h, base, start)
            continue
        for dirpath, dirnames, filenames in os.walk(start):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for name in sorted(filenames):
                _digest_entry(h, base, Path(dirpath) / name)
    return "sha256:" + h.hexdigest()


def _digest_entry(h: Any, base: Path, path: Path) -> None:
    rel = path.relative_to(base).as_posix()
    if path.is_symlink():
        h.update(f"L {rel}\0{os.readlink(path)}\0".encode())
        return
    with open(path, "rb") as fh:
        h.update(f"F {rel}\0".encode() + hashlib.sha256(fh.read()).digest())


# -- the network graph, recorded honestly -------------------------------------------------


def network_graph(container: str, networks: list[str], extra_hosts: list[str]) -> list[dict]:
    """The one launch class a box has before BS5: the runner and its tools, mixed.

    Recorded, not enforced. Nothing outside the box limits where it connects, so the
    graph's closure is negative (see closure()). BS5 gives tools their own graph.
    """
    grants: list[dict] = [
        {"to": f"docker network {n}", "port": "any", "protocol": "any",
         "what": "every service on that network (database, Redis, the server's API, MCP services)",
         "enforced_by": None}
        for n in networks
    ]
    grants += [{"to": f"extra host {h}", "port": "any", "protocol": "any",
                "what": "the address docker maps that name to", "enforced_by": None}
               for h in extra_hosts]
    grants.append({"to": "internet", "port": "any", "protocol": "any",
                   "what": "any address the network routes to", "enforced_by": None})
    return [{
        "class": "runner+tools (mixed, in-process)",
        "identity": {"container": container, "pid": "one namespace, runner and tools together",
                     "mounts": "one namespace, runner and tools together",
                     "network": list(networks)},
        "grants": grants,
        "enforcer": None,
        "address_families": "whatever the docker network gives, not restricted",
        "dns": "docker's resolver, not restricted", "redirects": "not restricted",
        "proxy": None,
        "verification": "start: the box checks the profile; nothing checks connections",
    }]


def closure(graph: list[dict]) -> dict:
    """What the graph proves: nothing yet, and it says so."""
    open_edges = [f"{g.get('to')} (no enforcer)" for entry in graph
                  for g in entry.get("grants") or []
                  if g.get("enforced_by") is None]
    return {"network": "negative", "state": "negative", "evidence": [],
            "residual_edges": open_edges,
            "why": "before BS5 the runner and its tools share one network identity; "
                   "before BS4 they share the database login"}


def residuals(boundary: str, legacy_mounts: list[dict] | None = None) -> list[dict]:
    """What this profile does not protect: BS2-BS6, the network, and BS1 itself when legacy."""
    items = [{"step": step, "still": "legacy", "what": what} for step, what in LATER_STEPS]
    items.append({"step": "network", "still": "mixed",
                  "what": "the network graph is recorded, not enforced: closure is negative"})
    items.append({"step": "history", "still": "legacy",
                  "what": "a run's profile history lives in its row, which boxes holding the "
                          "database login can write (BS4)"})
    if boundary == LEGACY:
        kinds = sorted({m["class"] for m in legacy_mounts or [] if m["class"] != "code"})
        items.insert(0, {"step": "BS1", "still": "legacy",
                         "what": "the box gets the template's mounts as they are"
                                 + (f": {', '.join(kinds)}" if kinds else "")
                                 + "; its runtime files are writable"})
    else:
        items.append({"step": "mixed install", "still": "legacy",
                      "what": "launches declared legacy in this install keep their wider mounts; "
                              "a sealed install refuses any of them that could write a sealed root"})
        items.append({"step": "BS6", "still": "legacy",
                      "what": "the Claude CLI keeps its state in a writable /app/.claude "
                              "(the direct-token CLI class)"})
    return items


# -- compile ------------------------------------------------------------------------------

#: Facts a sealed profile can't do without. Missing or unknown -> refused.
_SEALED_FACTS = ("image", "source", "launch", "grants", "runtime", "network_graph")


def compile_profile(
    *,
    execution_id: str,
    generation: int,
    settings: Mapping[str, str],
    boundary: str,
    image: Mapping[str, Any],
    source: Mapping[str, Any],
    launch: Mapping[str, Any],
    grants: list[dict],
    tmpfs: list[str],
    runtime: Mapping[str, Any],
    limits: Mapping[str, Any],
    graph: list[dict],
    legacy_mounts: list[dict] | None = None,
    compiled_by: str = "worker",
) -> dict:
    """One immutable profile document. Refuses a sealed one with any fact missing or unknown."""
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "execution_id": execution_id,
        "generation": generation,
        "compiled_by": {"component": compiled_by, "host": socket.gethostname()},
        "compiled_at": utcnow().isoformat(),
        "settings": dict(settings),
        "boundary": boundary,
        "hardening": "partial",
        "label": SEALED_LABEL if boundary == SEALED else LEGACY_LABEL,
        "classification": {"by": launch.get("classified_by", "none"),
                           "label": launch.get("label", "not classified (a legacy box)")},
        "image": dict(image),
        "source": dict(source),
        "versions": {"schema": SCHEMA_VERSION, "protocol": "box-profile/2",
                     "runtime": image.get("id"), "config": launch.get("digest"),
                     "grant": "bs1-manifest/1" if boundary == SEALED else "legacy-inherit",
                     "operation": "legacy (BS3 not built)"},
        "launch": dict(launch),
        "grants": list(grants),
        "tmpfs": list(tmpfs),
        "rootfs": "read-only" if boundary == SEALED else "writable",
        "runtime": dict(runtime),
        "state": {"access": "legacy",
                  "note": "the runner and its tools reach SQL and Redis as before (BS4 not built)"},
        "limits": dict(limits),
        "network_graph": graph,
        "closure": closure(graph),
        "residuals": residuals(boundary, legacy_mounts),
    }
    if boundary == SEALED:
        missing = [k for k in _SEALED_FACTS if _unknown(doc.get(k))]
        missing += [f"{k} ({v})" for k, v in _unknown_inside(doc)]
        if missing:
            raise BoxProfileError(
                "a sealed box needs facts that are missing or unknown: " + ", ".join(missing)
                + "; the launch is refused",
            )
    return doc


def _unknown(value: Any) -> bool:
    return value in (None, "", [], {}) or value == "unknown"


def _unknown_inside(doc: Mapping[str, Any]) -> list[tuple[str, str]]:
    found = []
    image = doc.get("image") or {}
    if not str(image.get("id") or "").startswith("sha256:"):
        found.append(("image.id", "not a content digest"))
    for name, src in (doc.get("source") or {}).items():
        if _unknown((src or {}).get("digest")):
            found.append((f"source.{name}", "no digest"))
    for grant in doc.get("grants") or []:
        if grant.get("pin") is None:
            found.append((f"grant {grant.get('target')}", "not pinned"))
    for key in ("interpreter", "path", "home", "user"):
        if _unknown((doc.get("runtime") or {}).get(key)):
            found.append((f"runtime.{key}", "unknown"))
    for entry in doc.get("network_graph") or []:
        if _unknown(entry.get("class")) or "grants" not in entry:
            found.append(("network_graph", "an entry without class or grants"))
    launch = doc.get("launch") or {}
    if launch.get("boundary") != SEALED:
        found.append(("launch", f"classified {launch.get('boundary')!r}"))
    for key in ("digest", "files", "configs", "allowed", "engine"):
        if _unknown(launch.get(key)):
            found.append((f"launch.{key}", "unknown"))
    return found


# -- what the row keeps -------------------------------------------------------------------


@dataclass(frozen=True)
class StoredProfile:
    """The profile a run's row holds, checked to be the one the worker stored."""

    digest: str
    generation: int
    boundary: str
    doc: dict
    history: tuple[dict, ...]

    @property
    def ever_sealed(self) -> bool:
        return self.boundary == SEALED or any(h.get("boundary") == SEALED for h in self.history)


def stored_profile(metadata: Mapping[str, Any] | None) -> StoredProfile | None:
    """The row's profile, or None when it has none. BoxProfileError when it doesn't add up.

    A record whose digest is not its document's, or whose numbers disagree, was changed
    outside the worker: nothing can be built on it.
    """
    record = (metadata or {}).get(METADATA_KEY)
    if record is None:
        return None
    try:
        doc = dict(record["doc"])
        digest = str(record["digest"])
        generation = int(record["generation"])
        boundary = str(record["boundary"])
        history = tuple(dict(h) for h in record.get("history") or [])
    except (KeyError, TypeError, ValueError) as exc:
        raise BoxProfileError(f"this run's stored box profile is malformed ({exc!r})") from exc
    if (digest_of(doc) != digest or doc.get("generation") != generation
            or doc.get("boundary") != boundary):
        raise BoxProfileError(
            "this run's stored box profile does not match its own digest: it was changed "
            "outside the worker, so no box is built on it; start a fresh run",
        )
    return StoredProfile(digest=digest, generation=generation, boundary=boundary, doc=doc,
                         history=history)


def looks_sealed(record: Any) -> bool:
    """Whether a stored record that can't be read whole still says a box was sealed."""
    if not isinstance(record, Mapping):
        return False
    history = record.get("history")
    return record.get("boundary") == SEALED or (isinstance(history, list) and any(
        isinstance(h, Mapping) and h.get("boundary") == SEALED for h in history))


def next_generation(previous: StoredProfile | None, boundary: str) -> int:
    """The generation the next box gets; refuses turning a sealed run into a legacy one."""
    if previous is not None and previous.ever_sealed and boundary != SEALED:
        raise BoxProfileError(
            "this run had a sealed box; a later box for it can't be legacy (that would take "
            "back what the earlier one promised). Start a fresh run on a declared legacy "
            "profile instead",
        )
    return 1 if previous is None else previous.generation + 1


def record_for(doc: Mapping[str, Any], previous: StoredProfile | None) -> dict:
    """What goes on the row: the document, its digest and generation, and a short history."""
    history = list(previous.history) if previous else []
    if previous is not None:
        history.append({"generation": previous.generation, "digest": previous.digest,
                        "boundary": previous.boundary})
    return {"schema_version": SCHEMA_VERSION, "digest": digest_of(doc),
            "generation": doc["generation"], "boundary": doc["boundary"],
            "hardening": doc["hardening"], "doc": dict(doc), "history": history[-20:]}


def env_for(doc: Mapping[str, Any]) -> dict[str, str]:
    """The variables a box gets so it can check itself before anything else runs."""
    return {PROFILE_ENV: canonical(doc), DIGEST_ENV: digest_of(doc),
            GENERATION_ENV: str(doc["generation"])}


@dataclass(frozen=True)
class RunFacts:
    """What the worker reads from a run's row to build its box."""

    workflow_name: str
    metadata: dict


#: Run statuses whose box may still be going (or start again soon).
ACTIVE_STATUSES = frozenset({"pending", "queued", "running", "waiting", "parked"})


class ProfileStore(Protocol):
    def load(self, execution_id: str) -> RunFacts | None:
        """The run's workflow and spawner_metadata (None when the run has no row)."""

    def save(self, execution_id: str, record: dict, expected_generation: int | None) -> None:
        """Store ``record`` if the row still holds ``expected_generation`` (else BoxProfileError)."""

    def neighbours(self, execution_id: str, forms: list[str]) -> list[str]:
        """Other runs whose workspace holds or is inside this one (``forms``: its spellings)."""


class DbProfileStore:
    """The run's row in the database: spawner_metadata["box_profile"]."""

    def load(self, execution_id: str) -> RunFacts | None:
        from sqlmodel import select

        from temper_ai.database import get_session
        from temper_ai.runner.models import WorkflowRun

        with get_session() as session:
            row = session.exec(
                select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
            ).first()
            if row is None:
                return None
            return RunFacts(workflow_name=row.workflow_name,
                            metadata=dict(row.spawner_metadata or {}))

    def neighbours(self, execution_id: str, forms: list[str]) -> list[str]:
        """Runs inside this workspace (any status), or holding it or sharing it while active."""
        from sqlalchemy import or_
        from sqlmodel import col, select

        from temper_ai.database import get_session
        from temper_ai.runner.models import WorkflowRun

        above = {str(p) for f in forms for p in Path(f).parents if str(p) != "/"} | set(forms)
        path = col(WorkflowRun.workspace_path)
        found = []
        with get_session() as session:
            rows = session.exec(
                select(WorkflowRun.execution_id, WorkflowRun.workspace_path, WorkflowRun.status)
                .where(WorkflowRun.execution_id != execution_id)
                .where(or_(path.in_(sorted(above)),
                           *[path.startswith(f.rstrip("/") + "/", autoescape=True)
                             for f in forms])),
            ).all()
        for other, where, status in rows:
            inside = any(where.startswith(f.rstrip("/") + "/") for f in forms)
            if inside or status in ACTIVE_STATUSES:
                found.append(f"{other} ({where}, {status})")
        return sorted(found)

    def save(self, execution_id: str, record: dict, expected_generation: int | None) -> None:
        from sqlmodel import select

        from temper_ai.database import get_session
        from temper_ai.runner.models import WorkflowRun

        with get_session() as session:
            row = session.exec(
                select(WorkflowRun).where(WorkflowRun.execution_id == execution_id)
                .with_for_update(),
            ).first()
            if row is None:
                raise BoxProfileError(f"no WorkflowRun row for {execution_id} to store its profile on")
            meta = dict(row.spawner_metadata or {})
            held = (meta.get(METADATA_KEY) or {}).get("generation")
            if held != expected_generation:
                raise BoxProfileError(
                    f"another box profile was stored for {execution_id} meanwhile "
                    f"(generation {held}, expected {expected_generation})",
                )
            meta[METADATA_KEY] = record
            row.spawner_metadata = meta
            session.add(row)


# -- the box's side -----------------------------------------------------------------------


def check_row(doc: Mapping[str, Any] | None, metadata: Mapping[str, Any] | None) -> None:
    """Is this box the one the row says the run has now? Raises BoxIsStale or BoxStartRefused."""
    try:
        stored = stored_profile(metadata)
    except BoxProfileError as exc:
        if doc is None and not looks_sealed((metadata or {}).get(METADATA_KEY)):
            return  # a box started without a profile, as before; the record isn't its own
        raise BoxStartRefused(str(exc)) from exc
    if doc is None:
        if stored is not None and stored.ever_sealed:
            raise BoxStartRefused(
                "this run's box profile is sealed, but this process started without one "
                "(a downgrade): refused",
            )
        return
    mine = int(doc["generation"])
    if stored is not None and stored.generation > mine:
        raise BoxIsStale(
            f"the run has box generation {stored.generation} now; this box is {mine}",
        )
    if doc.get("boundary") != SEALED and not (stored is not None and stored.ever_sealed):
        return  # a legacy box is never stopped by its profile, only by a newer box
    if stored is None:
        raise BoxStartRefused("the run's row holds no box profile for this box")
    if stored.generation != mine or stored.digest != digest_of(doc):
        raise BoxStartRefused(
            f"the run's row holds box profile generation {stored.generation} "
            f"({stored.digest[:19]}), not this box's ({mine}, {digest_of(doc)[:19]})",
        )


def summary(doc: Mapping[str, Any]) -> str:
    """One line for logs: boundary, generation, digest, launch class."""
    launch = doc.get("launch") or {}
    boundary = doc.get("boundary")
    shown = (f"{boundary} (BS1-partial; gate-classified, not reviewed by Security)"
             if boundary == SEALED else f"{boundary} ({doc.get('hardening')} hardening)")
    return (f"box profile g{doc.get('generation')} {shown} {digest_of(doc)[:19]}; launch "
            f"{launch.get('workflow')!r}: {launch.get('boundary')}")
