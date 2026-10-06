"""Which box each workflow's launch may have: the gate's classification of every launch (BS1).

A launch is everything a run of one workflow loads from configs/: the workflow, its
agents and stages (nested, dispatched and stage-referenced), the MCP servers its
tools name, and the asset files any of them name. Its closure digest covers those
files' contents (as git blob ids).

The rules are this module: landed engine code. Nothing a workflow, agent or stage says,
nothing in a workspace and nothing a run writes can declare or change its own class.
The worker works the class out again from the files themselves whenever it starts a
box (start, resume, replacement, takeover), and the box itself checks that the files
it loads are the ones that were classified and refuses anything outside them
(spawner/box_guard.py).

Each launch is one of:

  sealed   every part is a class a sealed box enforces, all known before the run
           starts: agent types, tools, providers (fallbacks and the install's default
           included), provider settings, step strategies, MCP servers and asset files
           on the lists below. Gate-classified: no Security review of any launch stands
           behind it
  legacy   needs what only a legacy box has: keys, the main repo copy, the shared
           workspaces tree, a shared root, an MCP server started in the box, a Pi step
  refused  can't be known before the box starts (agents, steps or providers chosen at
           run time, names that don't resolve) or isn't classified (an unknown tool,
           agent type, provider, setting or strategy)

A legacy install runs every launch as before, whatever its class; the class is only
recorded. A sealed install starts only sealed launches, and refuses the others with
these reasons (BS1 has no mixed boxes).

The engine's own launch paths are classified here too (ENGINE_LAUNCHES): a sealed box
starts only when the code it mounts has no place that starts a program missing from
that list.

    python -m temper_ai.spawner.box_launches report [--configs DIR] [--default-provider P] [--json]
    python -m temper_ai.spawner.box_launches sites [--root DIR] [--prefix P]
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeGuard

import yaml

from temper_ai.config.importer import NON_CONFIG_DIRS, TEAM_SETTINGS_DIR, TRIAL_PREFIX

SEALED = "sealed"
LEGACY = "legacy"
REFUSED = "refused"
GENERATOR = "box-launches/2"
#: What a sealed class means, said the same way everywhere it is shown.
LABEL = "gate-classified; not reviewed by Security"


# -- the classes a sealed box enforces --------------------------------------------------------

_OWN_MOUNTS = "works on the box's own mounts, as the box's user"
_NETWORK = "calls out over the network (the network is a residual until BS5)"
_SERVER_API = ("calls the server's API with the run's own key, from the box's environment "
               "(a residual until BS2)")
_INTEGRATION = ("calls an integration's API with keys from the box's environment "
                "(a residual until BS2/BS3)")

#: Tools a sealed box runs, and why each stays inside what the box enforces.
SEALED_TOOLS = {
    "Bash": _OWN_MOUNTS,
    "Calculator": "does arithmetic only",
    "Edit": _OWN_MOUNTS,
    "Glob": _OWN_MOUNTS,
    "Grep": _OWN_MOUNTS,
    "Read": _OWN_MOUNTS,
    "Write": _OWN_MOUNTS,
    "git": _OWN_MOUNTS,
    "http": _NETWORK,
    "WebFetch": _NETWORK,
    "WebSearch": _NETWORK,
    "GitHubComment": _SERVER_API,
    "GitHubFiles": _SERVER_API,
    "GitHubPullDiff": _SERVER_API,
    "GitHubReview": _SERVER_API,
    "GitHubThread": _SERVER_API,
    "QueryRunState": "reads run rows with the database login (a residual until BS4)",
    "LinearMoveIssue": _INTEGRATION,
    "NotionComment": _INTEGRATION,
    "NotionRead": _INTEGRATION,
    "NotionSearch": _INTEGRATION,
    "NotionUpsert": _INTEGRATION,
    "NotionWrite": _INTEGRATION,
    "SlackPost": _INTEGRATION,
    "SlackReadThread": _INTEGRATION,
    "SlackReply": _INTEGRATION,
    "TelegramSend": _INTEGRATION,
}
#: Tools that need what only a legacy box has (why, in plain words).
LEGACY_TOOLS = {
    "OpenPullRequest": "opens pull requests from the shared /app/workspaces/repos tree",
    "OpenPullRequestAsApp": "opens pull requests from the shared /app/workspaces/repos tree",
    "RoameeData": "asks roamee-reader through its socket folder, a shared root",
    "RoameeStack": "asks roamee-reader through its socket folder, a shared root",
    "RoameeWork": "asks roamee-reader through its socket folder, a shared root",
}
#: Tools that choose agents or steps while the run goes: the launch isn't known before it.
RUN_TIME_TOOLS = {
    "Delegate": "runs agents it names at run time",
    "AddNode": "adds steps at run time",
    "RemoveNode": "removes steps at run time",
}
AGENT_TYPES = {"llm", "script"}
LEGACY_AGENT_TYPES = {"pi": "a Pi step: the Pi lane keeps its own box design (M4)"}
#: Providers whose login a sealed box can use (keys in its environment: BS2, BS6).
SEALED_PROVIDERS = frozenset({"claude", "claude_v2", "anthropic"})
#: Provider settings that only tune the model call. Anything else (mcp_config starts MCP
#: servers through the provider's command-line client) isn't classified.
SEALED_PROVIDER_SETTINGS = frozenset({"effort", "max_tokens", "cache_ttl", "temperature"})
#: Step strategies whose agents are the ones listed (team and registered ones aren't).
SEALED_STRATEGIES = frozenset({None, "parallel", "sequential", "leader"})

#: Settings each level may have. Anything else isn't classified, so it refuses sealed
#: (memory stores, failure handlers, strategy settings, skipped policies among them).
WORKFLOW_SETTINGS = frozenset({"name", "description", "version", "nodes", "inputs", "outputs",
                               "safety", "defaults", "notify", "starts_runs"})
DEFAULTS_SETTINGS = frozenset({"provider", "model", "provider_config", "temperature",
                               "max_tokens", "dispatch"})
STEP_SETTINGS = frozenset({
    "name", "type", "agent", "agents", "nodes", "ref", "strategy", "depends_on", "condition",
    "loop_to", "max_loops", "loop_condition", "on_max_loops", "run_after_failure", "undoes",
    "required_files", "renamed_from", "timeout_seconds", "gate", "input_map", "inputs",
    "outputs", "task_template", "system_prompt", "role", "model", "provider", "temperature",
    "max_tokens", "token_budget", "tools",
})
ENTRY_SETTINGS = frozenset({"agent", "ref", "name", "role", "task_template", "config",
                            "system_prompt", "model", "provider", "temperature", "max_tokens",
                            "token_budget", "tools"})
AGENT_SETTINGS = frozenset({
    "name", "type", "description", "version", "model", "provider", "provider_config",
    "fallback", "tools", "dispatch", "system_prompt", "task_template", "role", "message",
    "max_context_tokens", "max_iterations", "script_template", "strict_undefined", "thinking",
    "timeout_seconds", "token_budget", "total_timeout", "workspace_files", "wrap_up_turns",
    "temperature", "max_tokens", "output_schema", "structured_output", "inputs", "outputs",
})
_FALLBACK_SETTINGS = frozenset({"provider", "model", "provider_config"})

#: Text that names something only a legacy box has. Generic; a spawn adds the
#: template's own mounts that a sealed box doesn't get (absent_roots).
LEGACY_MARKERS = (
    ("/app/repo", "the main repo copy (/app/repo)"),
    ("/app/workspaces", "the shared workspaces tree (/app/workspaces)"),
    (".credentials.json", "the Claude login file"),
    ("/.ssh", "ssh keys"),
    ("ssh -i", "an ssh key"),
    ("GIT_SSH", "an ssh key for git"),
    ("worktree add", "git worktrees, whose backing repo is outside the run's own workspace"),
    ("docker.sock", "the docker socket"),
)
#: Text that needs a box whose secrets are its environment: a oneshot box (BS2) has them
#: only in its runner. A spawn under TEMPER_BOX_SECRET_BOOTSTRAP=oneshot adds these.
ONESHOT_MARKERS = (
    ("PENPOT_AGENT_PASSWORD",
     "the Penpot password: until BS3 gives it a channel of its own, a script reaches it only "
     "from a legacy box's start environment, which a oneshot box doesn't have; run it on an "
     "explicit legacy profile"),
)
_CONFIG_REF = re.compile(r"(?:/app/)?(?<![\w.-])configs/([A-Za-z0-9_][A-Za-z0-9_./-]*)")


def blob_id(data: bytes) -> str:
    """git's blob id for ``data`` (the same digest from a checkout and from history)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def closure_digest(files: Mapping[str, str]) -> str:
    lines = "".join(f"{path}\0{blob}\n" for path, blob in sorted(files.items()))
    return "sha256:" + hashlib.sha256(lines.encode()).hexdigest()


# -- config trees ---------------------------------------------------------------------------


class ConfigTree:
    """configs/ as files: relative paths ("configs/agents/x.yaml") and their bytes."""

    def paths(self) -> list[str]:
        raise NotImplementedError

    def read(self, path: str) -> bytes:
        raise NotImplementedError


class FsTree(ConfigTree):
    def __init__(self, configs_dir: str | Path) -> None:
        self.root = Path(configs_dir)

    def paths(self) -> list[str]:
        out = []
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                out.append("configs/" + path.relative_to(self.root).as_posix())
        return out

    def read(self, path: str) -> bytes:
        return (self.root / path.removeprefix("configs/")).read_bytes()


# -- the index ------------------------------------------------------------------------------


@dataclass
class ConfigIndex:
    """Every config by kind and name, as the importer would load them (later file wins).

    The importer's skips apply (temper_ai/config/importer.py): its settings folders, the
    Team page's settings folder under the root, and team trials' names, which only the
    Team page writes (a launch naming one doesn't resolve, so it refuses sealed). MCP
    server files are read here too, for the servers a launch's tools name.
    """

    tree: ConfigTree
    by_kind: dict[str, dict[str, str]] = field(default_factory=dict)
    duplicates: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    docs: dict[str, dict] = field(default_factory=dict)
    blobs: dict[str, str] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    broken: dict[str, str] = field(default_factory=dict)

    @classmethod
    def of(cls, tree: ConfigTree) -> ConfigIndex:
        index = cls(tree=tree)
        index.files = tree.paths()
        for path in index.files:
            data = tree.read(path)
            index.blobs[path] = blob_id(data)
            if not path.endswith(".yaml"):
                continue
            parts = path.split("/")[1:-1]
            text = data.decode("utf-8", "replace")
            index.texts[path] = text
            try:
                doc = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                index.broken[path] = f"not readable YAML ({type(exc).__name__})"
                continue
            if not isinstance(doc, dict):
                continue
            kind = "mcp_server" if "mcp_servers" in parts else next(
                (k for k in ("workflow", "agent", "stage") if k in doc), None)
            if kind is None or (kind != "mcp_server" and (
                    any(p in NON_CONFIG_DIRS for p in parts)
                    or parts[:1] == [TEAM_SETTINGS_DIR])):
                continue
            inner = doc.get(kind)
            if not isinstance(inner, dict) or not inner.get("name"):
                continue
            name = inner["name"]
            if kind != "mcp_server" and str(name).startswith(TRIAL_PREFIX):
                continue
            index.docs[path] = inner
            names = index.by_kind.setdefault(kind, {})
            if name in names:
                index.duplicates.setdefault((kind, name), [names[name]]).append(path)
            names[name] = path
        return index

    def under(self, rel: str) -> list[str]:
        """Files at ``configs/<rel>``: the file itself, or everything below a folder."""
        rel = rel.rstrip("/.")
        exact = f"configs/{rel}"
        return [p for p in self.files if p == exact or p.startswith(exact + "/")]


# -- one launch -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Launch:
    workflow: str
    boundary: str
    reasons: tuple[str, ...]
    files: Mapping[str, str]
    digest: str | None
    configs: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    allowed: Mapping[str, list[str]] = field(default_factory=dict)
    default_provider: str | None = None

    def as_dict(self) -> dict:
        """What the profile records: the box checks its files and allows only these classes."""
        return {"workflow": self.workflow, "boundary": self.boundary,
                "reasons": list(self.reasons), "digest": self.digest,
                "files": dict(sorted(self.files.items())),
                "configs": {kind: dict(sorted(names.items()))
                            for kind, names in sorted(self.configs.items())},
                "allowed": {kind: list(names) for kind, names in sorted(self.allowed.items())},
                "default_provider": self.default_provider,
                "classified_by": GENERATOR, "label": LABEL}


def _plain(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value) and "{{" not in value and "{%" not in value


@dataclass
class _Walk:
    index: ConfigIndex
    files: set[str] = field(default_factory=set)
    legacy: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    seen: set[tuple[str, str]] = field(default_factory=set)
    configs: dict[str, dict[str, str]] = field(default_factory=dict)
    tools: set[str] = field(default_factory=set)
    providers: set[str] = field(default_factory=set)
    agent_types: set[str] = field(default_factory=set)
    mcp_servers: set[str] = field(default_factory=set)
    no_provider: list[str] = field(default_factory=list)

    def add(self, kind: str, name: Any, via: str) -> None:
        if not isinstance(name, str) or not name:
            self.refused.append(f"{via} names a {kind} that isn't a plain name ({name!r})")
            return
        if not _plain(name):
            self.refused.append(f"{via} picks its {kind} from a template ({name}): "
                                "it is only known while the run goes")
            return
        if (kind, name) in self.seen:
            return
        self.seen.add((kind, name))
        path = self.index.by_kind.get(kind, {}).get(name)
        if path is None:
            self.refused.append(f"{via} names {kind} {name!r}, which isn't in configs/")
            return
        if (kind, name) in self.index.duplicates:
            self.refused.append(f"{kind} {name!r} is defined more than once "
                                f"({', '.join(self.index.duplicates[(kind, name)])})")
        self.files.add(path)
        self.configs.setdefault(kind, {})[name] = path
        doc = self.index.docs[path]
        if kind == "agent":
            self._agent(doc, f"agent {name!r}")
        elif kind == "mcp_server":
            self._mcp(name, doc)
        elif kind == "workflow":
            self._workflow(doc, f"workflow {name!r}")
        else:
            self._step(doc, f"stage {name!r}")

    # -- settings ---------------------------------------------------------------------------

    def _settings(self, doc: Mapping, allowed: frozenset[str], via: str) -> None:
        for key, value in doc.items():
            if key not in allowed and value is not None:
                self.refused.append(f"{via} has setting {key!r}, which isn't classified "
                                    "for sealed boxes")

    def _list(self, value: Any, via: str, what: str) -> list:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        self.refused.append(f"{via}'s {what} isn't a plain list ({str(value)[:60]!r}): "
                            "it is only known while the run goes")
        return []

    def _provider(self, provider: Any, via: str) -> None:
        if not _plain(provider) or provider not in SEALED_PROVIDERS:
            self.refused.append(f"{via} uses provider {provider!r}, whose login isn't "
                                "classified for sealed boxes")
        else:
            self.providers.add(provider)

    def _provider_settings(self, settings: Any, via: str) -> None:
        if settings is None:
            return
        if not isinstance(settings, dict):
            self.refused.append(f"{via}'s provider_config isn't a mapping")
            return
        for key in settings:
            if key not in SEALED_PROVIDER_SETTINGS:
                self.refused.append(f"{via}'s provider setting {key!r} isn't classified for "
                                    "sealed boxes")

    def _fallback(self, fallback: Any, via: str) -> None:
        if fallback is None or isinstance(fallback, str):
            return  # none, or another model on the same provider
        for entry in fallback if isinstance(fallback, list) else [fallback]:
            if isinstance(entry, str):
                continue
            if not isinstance(entry, dict):
                self.refused.append(f"{via}'s fallback {entry!r} isn't a model or a mapping")
                continue
            self._settings(entry, _FALLBACK_SETTINGS, f"{via}'s fallback")
            if entry.get("provider") is not None:
                self._provider(entry["provider"], f"{via}'s fallback")
            self._provider_settings(entry.get("provider_config"), f"{via}'s fallback")

    def _overrides(self, doc: Mapping, via: str) -> None:
        """A step's or agent entry's own provider and tools, which replace the agent's."""
        if doc.get("provider") is not None:
            self._provider(doc["provider"], via)
        self._tools(doc.get("tools"), via)

    # -- the graph --------------------------------------------------------------------------

    def _workflow(self, doc: dict, via: str) -> None:
        self._settings(doc, WORKFLOW_SETTINGS, via)
        defaults = doc.get("defaults")
        if isinstance(defaults, dict):
            here = f"{via}'s defaults"
            self._settings(defaults, DEFAULTS_SETTINGS, here)
            if defaults.get("provider") is not None:
                self._provider(defaults["provider"], here)
            self._provider_settings(defaults.get("provider_config"), here)
        elif defaults is not None:
            self.refused.append(f"{via}'s defaults aren't a mapping")
        for node in self._list(doc.get("nodes"), via, "nodes"):
            self._step(node, via)

    def _step(self, node: Any, via: str) -> None:
        if not isinstance(node, dict):
            self.refused.append(f"{via} has a step that isn't a mapping ({str(node)[:60]!r})")
            return
        here = f"{via}'s step {node['name']!r}" if node.get("name") else via
        self._settings(node, STEP_SETTINGS, here)
        kind = node.get("type")
        if kind == "template":
            self.refused.append(f"{here} is a template step: its agents come from the run's "
                                "inputs")
        elif kind not in (None, "agent", "stage"):
            self.refused.append(f"{here} has type {kind!r}, which isn't classified for "
                                "sealed boxes")
        if node.get("strategy") not in SEALED_STRATEGIES:
            self.refused.append(f"{here} uses strategy {node.get('strategy')!r}, which isn't "
                                "classified for sealed boxes")
        self._overrides(node, here)
        agent = node.get("agent")
        if isinstance(agent, dict):
            self._agent(agent, f"{here}'s inline agent")
        elif agent is not None:
            self.add("agent", agent, here)
        for item in self._list(node.get("agents"), here, "agents"):
            if isinstance(item, dict) and ("agent" in item or "ref" in item):
                entry = f"{here}'s agent entry"
                self._settings(item, ENTRY_SETTINGS, entry)
                self._overrides(item, entry)
                self.add("agent", item.get("agent") or item.get("ref"), here)
            elif isinstance(item, dict):
                self._agent(item, f"{here}'s inline agent")
            else:
                self.add("agent", item, here)
        if "ref" in node:
            self.add_graph(node["ref"], here)
        for child in self._list(node.get("nodes"), here, "nodes"):
            self._step(child, here)

    def add_graph(self, ref: Any, via: str) -> None:
        """A step's ref, as the loader reads it: stages/x or workflows/x, else a stage, else a workflow."""
        if not _plain(ref):
            self.add("stage", ref, via)  # refused there, with the reason
            return
        prefix, _, rest = ref.partition("/")
        explicit = {"stages": "stage", "stage": "stage", "workflows": "workflow",
                    "workflow": "workflow"}
        if rest and prefix in explicit:
            self.add(explicit[prefix], rest, via)
        elif ref in self.index.by_kind.get("stage", {}):
            self.add("stage", ref, via)
        else:
            self.add("workflow", ref, via)

    def _agent(self, doc: dict, via: str) -> None:
        kind = doc.get("type", "llm")
        if kind in LEGACY_AGENT_TYPES:
            self.legacy.append(f"{via}: {LEGACY_AGENT_TYPES[kind]}")
            return
        if kind not in AGENT_TYPES:
            self.refused.append(f"{via} has type {kind!r}, which isn't classified for sealed "
                                "boxes")
        else:
            self.agent_types.add(kind)
        self._settings(doc, AGENT_SETTINGS, via)
        if doc.get("provider") is not None:
            self._provider(doc["provider"], via)
        elif kind == "llm":
            self.no_provider.append(via)
        self._provider_settings(doc.get("provider_config"), via)
        self._fallback(doc.get("fallback"), via)
        self._tools(doc.get("tools"), via)
        if doc.get("dispatch") is not None:
            self._dispatch(doc["dispatch"], f"{via}'s dispatch")

    def _dispatch(self, block: Any, via: str) -> None:
        """Steps a dispatch block adds: each one's agents are part of the launch."""
        for op in self._list(block, via, "operations"):
            if not isinstance(op, dict):
                self.refused.append(f"{via} has an operation that isn't a mapping")
                continue
            if op.get("node") is not None:
                self._step(op["node"], via)
            for node in self._list(op.get("nodes"), via, "nodes"):
                self._step(node, via)

    def _tools(self, tools: Any, via: str) -> None:
        for tool in self._list(tools, via, "tools"):
            name = tool.get("name") if isinstance(tool, dict) else tool
            if not _plain(name):
                self.refused.append(f"{via} names a tool that isn't a plain name ({name!r})")
            else:
                self._tool(name, via)

    def _tool(self, tool: str, via: str) -> None:
        if "." in tool:
            self.tools.add(tool)
            self.add("mcp_server", tool.split(".", 1)[0], f"{via}'s tool {tool}")
        elif tool in SEALED_TOOLS:
            self.tools.add(tool)
        elif tool in LEGACY_TOOLS:
            self.legacy.append(f"{via}'s tool {tool} {LEGACY_TOOLS[tool]}")
        elif tool in RUN_TIME_TOOLS:
            self.refused.append(f"{via}'s tool {tool} {RUN_TIME_TOOLS[tool]}: "
                                "the launch is only known while the run goes")
        else:
            self.refused.append(f"{via}'s tool {tool!r} isn't classified for sealed boxes")

    def _mcp(self, name: str, doc: dict) -> None:
        transport = doc.get("transport", "stdio")  # as MCPClientManager._open reads it
        if transport == "stdio" or doc.get("command"):
            self.legacy.append(f"MCP server {name!r} starts {doc.get('command')!r} in the box "
                               "(stdio): a program fetched or run at run time, not baked into "
                               "the image")
        elif transport in ("http", "streamable_http") and _plain(doc.get("url")):
            self.mcp_servers.add(name)
        else:
            self.refused.append(f"MCP server {name!r} (transport {transport!r}, url "
                                f"{doc.get('url')!r}) isn't a kind a sealed box classifies")

    def scan_texts(self, markers: Iterable[tuple[str, str]]) -> None:
        """Asset files the closure names, and anything only a legacy box has."""
        pending = sorted(self.files)
        done: set[str] = set()
        while pending:
            path = pending.pop()
            if path in done:
                continue
            done.add(path)
            text = self.index.texts.get(path)
            if text is None:
                try:
                    text = self.index.tree.read(path).decode("utf-8", "replace")
                except OSError:
                    continue
            for match in _CONFIG_REF.finditer(text):
                ref = match.group(1).rstrip(".,:;)'\"`")
                if not ref or ref.endswith((".yaml", ".yml")):
                    continue  # configs reach the closure by name, not by mention
                found = [p for p in self.index.under(ref) if not p.endswith((".yaml", ".yml"))]
                if not found and not self.index.under(ref):
                    self.refused.append(f"{path} names configs/{ref}, which isn't there")
                for asset in found:
                    if asset not in self.files:
                        self.files.add(asset)
                        pending.append(asset)
            for needle, what in markers:
                if needle in text:
                    self.legacy.append(f"{path} uses {what}")


def classify(index: ConfigIndex, workflow: str, *, default_provider: str | None = None,
             absent_roots: Iterable[tuple[str, str]] = (),
             extra_markers: Iterable[tuple[str, str]] = ()) -> Launch:
    """One workflow's launch class, with every reason found (not just the first).

    ``default_provider`` is the provider a sealed box pins for agents that name none
    (the install's TEMPER_DEFAULT_PROVIDER); without it their provider would only be
    chosen at run time. ``extra_markers``: more (text, what) pairs that make a launch
    legacy (ONESHOT_MARKERS for a oneshot install).
    """
    walk = _Walk(index)
    walk.add("workflow", workflow, "the run")
    walk.scan_texts([*LEGACY_MARKERS, *absent_roots, *extra_markers])
    for path in sorted(walk.files):
        if path in index.broken:
            walk.refused.append(f"{path} is {index.broken[path]}")
    pinned = None
    if walk.no_provider:
        names = ", ".join(walk.no_provider[:3]) + (" and more" if len(walk.no_provider) > 3
                                                   else "")
        if default_provider is None:
            walk.refused.append(
                f"{names} name no provider: the install's default is chosen at run time "
                "unless TEMPER_DEFAULT_PROVIDER pins one",
            )
        elif default_provider not in SEALED_PROVIDERS:
            walk.refused.append(
                f"{names} use the install's default provider {default_provider!r}, whose "
                "login isn't classified for sealed boxes",
            )
        else:
            pinned = default_provider
            walk.providers.add(default_provider)
    files = {path: index.blobs[path] for path in walk.files if path in index.blobs}
    digest = closure_digest(files) if files else None
    refused = sorted(set(walk.refused))
    legacy = sorted(set(walk.legacy))
    boundary = REFUSED if refused else LEGACY if legacy else SEALED
    allowed = {"agent_types": sorted(walk.agent_types), "mcp_servers": sorted(walk.mcp_servers),
               "providers": sorted(walk.providers), "tools": sorted(walk.tools)}
    return Launch(workflow=workflow, boundary=boundary, reasons=tuple(refused + legacy),
                  files=files, digest=digest, configs=walk.configs, allowed=allowed,
                  default_provider=pinned)


def classify_all(index: ConfigIndex, *, default_provider: str | None = None,
                 absent_roots: Iterable[tuple[str, str]] = (),
                 extra_markers: Iterable[tuple[str, str]] = ()) -> list[Launch]:
    roots, markers = list(absent_roots), list(extra_markers)
    return [classify(index, name, default_provider=default_provider, absent_roots=roots,
                     extra_markers=markers)
            for name in sorted(index.by_kind.get("workflow", {}))]


def summary_rows(launches: Iterable[Launch]) -> Iterator[str]:
    for launch in launches:
        yield f"{launch.boundary:8} {launch.workflow}"
        for reason in launch.reasons:
            yield f"         - {reason}"


# -- the engine's own launch paths (G11) --------------------------------------------------------

#: Every place the engine's code starts a program, and where that code runs. Keys are
#: "<path under its root>::<function>" ("<module>" for module level); the local code
#: (the private providers and agents a box mounts at /app/local) is listed under "local/".
#: A sealed box starts only when the code it mounts has no launch site missing here; a
#: new one is classified by adding it, through the gate.
_WORKER = "worker: runs in the trusted worker or server, never in a run's box"
_PI = "legacy: the Pi lane (M4), which only legacy boxes run"
_BOX_TOOL = "box: a tool on SEALED_TOOLS, run as the box's user in its own mounts"
_BOX_CLI = ("box: the provider's command-line client, baked into the image; reached only "
            "through a provider on SEALED_PROVIDERS (its login is a residual until BS6)")
_BOX_MCP = ("box: starts an MCP server program; reached only through stdio MCP servers, "
            "which are legacy (a sealed box's MCPClientManager.ensure_connected refuses them)")
_NOT_SEALED_AGENT = ("refused: an agent type that isn't on AGENT_TYPES, so no sealed launch "
                     "reaches it")
_LEGACY_TOOL = "legacy: a tool on LEGACY_TOOLS, so no sealed launch reaches it"
ENGINE_LAUNCHES: dict[str, str] = {
    "temper_ai/pi_agent/assets/entry.py::main": _PI,
    "temper_ai/pi_agent/box.py::WorkerBox._docker": _PI,
    "temper_ai/pi_agent/box.py::WorkerBox._host_pi_token": _PI,
    "temper_ai/pi_agent/box.py::WorkerBox.close": _PI,
    "temper_ai/pi_agent/box.py::_docker_cli": _PI,
    "temper_ai/pi_agent/box.py::_no_such_container": _PI,
    "temper_ai/pi_agent/box.py::stop_leftover_box": _PI,
    "temper_ai/pi_agent/rpc.py::Rpc.__init__": _PI,
    "temper_ai/pi_agent/rpc.py::Rpc.close": _PI,
    "temper_ai/pi_agent/team_folders.py::run_git": (
        "legacy: the Pi team's folder checks, in the Pi lane (M4), which only legacy boxes "
        "run, or in the trusted server (the Team page's check and a trial's start)"),
    "temper_ai/pi_agent/team_leader.py::ProjectCopies._g": _PI,
    "temper_ai/spawner/box_bootstrap.py::protect_process": (
        "box: the runner's and the delivery writer's own prctl and rlimit calls (libc "
        "through ctypes); starts no program"),
    "temper_ai/spawner/box_view.py::main": (
        "box: the sealed box's view check, which becomes the runner (the image's own "
        "interpreter) once the view is right"),
    "temper_ai/spawner/docker_spawner.py::DockerSpawner.__init__": _WORKER,
    "temper_ai/spawner/docker_spawner.py::DockerSpawner._deliver": _WORKER,
    "temper_ai/spawner/docker_spawner.py::DockerSpawner._docker_run": _WORKER,
    "temper_ai/spawner/docker_spawner.py::DockerSpawner._handle": _WORKER,
    "temper_ai/spawner/docker_spawner.py::_delivery_status": _WORKER,
    "temper_ai/spawner/subprocess_spawner.py::SubprocessSpawner.__init__": _WORKER,
    "temper_ai/spawner/subprocess_spawner.py::SubprocessSpawner._collect": _WORKER,
    "temper_ai/spawner/subprocess_spawner.py::SubprocessSpawner.reap": _WORKER,
    "temper_ai/spawner/subprocess_spawner.py::SubprocessSpawner.spawn": _WORKER,
    "temper_ai/tools/bash.py::_kill_group": _BOX_TOOL,
    "temper_ai/tools/bash.py::_pump": _BOX_TOOL,
    "temper_ai/tools/bash.py::_reap": _BOX_TOOL,
    "temper_ai/tools/bash.py::_run_streaming": _BOX_TOOL,
    "temper_ai/tools/bash.py::_run_subprocess": _BOX_TOOL,
    "temper_ai/tools/bash.py::_signal_group": _BOX_TOOL,
    "temper_ai/tools/bash.py::_wait": _BOX_TOOL,
    "temper_ai/tools/git.py::Git._run_git": _BOX_TOOL,
    "temper_ai/tools/github_pr.py::OpenPullRequest.execute": _LEGACY_TOOL,
    "temper_ai/tools/github_pr.py::_git": _LEGACY_TOOL,
    "temper_ai/tools/mcp_client.py::<module>": _BOX_MCP,
    "local/agents/claude_code_agent.py::ClaudeCodeAgent._execute": _NOT_SEALED_AGENT,
    "local/providers/claude_code.py::ClaudeCodeLLM.complete": _BOX_CLI,
    "local/providers/claude_code.py::ClaudeCodeLLM.stream": _BOX_CLI,
    "local/providers/claude_code_v2.py::ClaudeCodeV2LLM._capture": _BOX_CLI,
    "local/providers/claude_code_v2.py::ClaudeCodeV2LLM._paste_and_submit": _BOX_CLI,
    "local/providers/claude_code_v2.py::ClaudeCodeV2LLM._run": _BOX_CLI,
    "local/providers/claude_code_v2.py::ClaudeCodeV2LLM._session_alive": _BOX_CLI,
    "local/providers/claude_code_v2.py::ClaudeCodeV2LLM._tmux": _BOX_CLI,
    "local/providers/claude_code_v2.py::_kill_our_sessions": _BOX_CLI,
    "local/providers/claude_code_v2.py::_list_sessions": _BOX_CLI,
    "local/providers/claude_code_v2.py::_sweep_orphan_sessions": _BOX_CLI,
}


@dataclass
class _SiteScan(ast.NodeVisitor):
    rel: str
    sites: set[str] = field(default_factory=set)
    scope: list[str] = field(default_factory=list)
    modules: dict[str, str] = field(default_factory=dict)
    names: set[str] = field(default_factory=set)

    #: Modules whose every use counts (they start programs, or call libc, which can).
    _MODULES = frozenset({"subprocess", "pty", "multiprocessing", "ctypes", "pexpect",
                          "ptyprocess", "sh", "plumbum"})
    _OS = frozenset({"system", "popen", "fork", "forkpty", "posix_spawn", "posix_spawnp",
                     "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp",
                     "execvpe", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv",
                     "spawnve", "spawnvp", "spawnvpe"})
    _ANYWHERE = frozenset({"create_subprocess_exec", "create_subprocess_shell",
                           "subprocess_exec", "subprocess_shell"})
    _IMPORTS = ("mcp.client.stdio",)

    def _site(self) -> None:
        self.sites.add(f"{self.rel}::{'.'.join(self.scope) or '<module>'}")

    def _scoped(self, node: ast.AST, name: str) -> None:
        self.scope.append(name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scoped(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scoped(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scoped(node, node.name)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top = alias.name.split(".", 1)[0]
            self.modules[alias.asname or top] = alias.name if alias.asname else top
            if alias.name.startswith(self._IMPORTS):
                self._site()

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module.startswith(self._IMPORTS):
            self._site()
        for alias in node.names:
            name = alias.asname or alias.name
            if module.split(".", 1)[0] in self._MODULES and not node.level:
                self.names.add(name)
            elif module == "os" and alias.name in self._OS:
                self.names.add(name)
            elif alias.name in self._ANYWHERE:
                self.names.add(name)
            elif alias.name in self._MODULES and module == "":
                self.modules[name] = alias.name

    def visit_Attribute(self, node: ast.Attribute) -> None:
        value = node.value
        module = self.modules.get(value.id) if isinstance(value, ast.Name) else None
        if module is not None and module.split(".", 1)[0] in self._MODULES:
            self._site()
        elif module == "os" and node.attr in self._OS:
            self._site()
        elif node.attr in self._ANYWHERE:
            self._site()
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self.names and isinstance(node.ctx, ast.Load):
            self._site()


def launch_sites(root: str | Path, *, prefix: str = "", only: Iterable[str] = ()) -> set[str]:
    """Every place the Python code under ``root`` starts a program (or may: G11's scan).

    ``only`` limits the scan to these entries under ``root`` (the local code a box
    mounts). A file that can't be read or parsed is a site of its own: it can't be checked.
    The scan finds direct uses (the modules above, os's exec, spawn, system, popen and
    fork, asyncio's subprocesses, the stdio MCP client); a program started through a
    dynamic import, or by a third-party package the engine calls, is not found here: the
    gate's review of engine changes covers those.
    """
    base = Path(root)
    entries = [base / entry for entry in only] if only else [base]
    files: list[Path] = []
    for entry in entries:
        if entry.is_file() and entry.suffix == ".py":
            files.append(entry)
        elif entry.is_dir():
            files += [p for p in entry.rglob("*.py") if "__pycache__" not in p.parts]
    sites: set[str] = set()
    for path in sorted(files):
        rel = prefix + path.relative_to(base).as_posix()
        try:
            tree = ast.parse(path.read_bytes(), filename=str(path))
        except (OSError, SyntaxError, ValueError):
            sites.add(f"{rel}::<unreadable>")
            continue
        scan = _SiteScan(rel)
        scan.visit(tree)
        sites |= scan.sites
    return sites


def unclassified_sites(sites: Iterable[str],
                       table: Mapping[str, str] | None = None) -> list[str]:
    """Launch sites the table doesn't classify (a sealed box doesn't start while any is)."""
    known = ENGINE_LAUNCHES if table is None else table
    return sorted(site for site in sites if site not in known)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m temper_ai.spawner.box_launches")
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report", help="classify every workflow under a configs folder")
    report.add_argument("--configs", default="configs")
    report.add_argument("--default-provider", default=None)
    report.add_argument("--json", action="store_true")
    report.add_argument("--oneshot", action="store_true",
                        help="classify as a oneshot install would (BS2)")
    sites = sub.add_parser("sites", help="the engine's launch sites and their classes")
    sites.add_argument("--root", default="temper_ai")
    sites.add_argument("--prefix", default="temper_ai/")
    args = parser.parse_args(argv)
    if args.command == "sites":
        found = launch_sites(args.root, prefix=args.prefix)
        for site in sorted(found):
            print(f"{site}\t{ENGINE_LAUNCHES.get(site, 'UNCLASSIFIED')}")
        return 1 if unclassified_sites(found) else 0
    launches = classify_all(ConfigIndex.of(FsTree(args.configs)),
                            default_provider=args.default_provider,
                            extra_markers=ONESHOT_MARKERS if args.oneshot else ())
    if args.json:
        print(json.dumps([launch.as_dict() for launch in launches], indent=1))
    else:
        print("\n".join(summary_rows(launches)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
