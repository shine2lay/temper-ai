"""What a sealed box's runner may load and start: its classified launch, nothing else (BS1).

The worker classified the run's launch from the config files themselves before it
started the box (box_launches.py) and wrote the result into the box's profile: every
closure file with its git blob id, the configs by kind and name, and the agent types,
tools, providers and MCP servers the launch may use. Static rules can miss a path, so
the box backs them:

- before anything is loaded, every closure file is read and checked against its blob
  id (a file changed after the worker classified it refuses the box);
- configs are served from those files only, never from the database, which anything
  holding the database login could have written (ConfigStore.get);
- an agent type, tool, provider or MCP server outside the classification is refused
  where it would be used (create_agent, the run's tool registration, get_llm,
  MCPClientManager.ensure_connected), before any tool of it runs or any server is started.

A legacy box has no guard, and everything works as before.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from temper_ai.config.helpers import (
    MAX_CONFIG_SIZE,
    ConfigNotFoundError,
    check_schema_version,
    substitute_env_vars,
)
from temper_ai.spawner import box_bootstrap
from temper_ai.spawner.box_launches import blob_id

#: Where a sealed box has its configs (box_seal.CONFIG_TARGET).
CONFIGS_ROOT = "/app/configs"
_KINDS = ("agent_types", "mcp_servers", "providers", "tools")


class LaunchRefused(RuntimeError):
    """The box was asked for something its classified launch doesn't have."""


class NotInLaunch(ConfigNotFoundError):
    """A config that isn't part of the run's classified launch (for callers, not found)."""


@dataclass(frozen=True)
class Guard:
    workflow: str
    files: Mapping[str, bytes]
    configs: Mapping[str, Mapping[str, str]]
    allowed: Mapping[str, frozenset[str]]
    # Retained at activation for the opt-in raw adapter. Not caller-supplied
    # mutable mappings: later edits to files/configs cannot change raw identity.
    _raw_files: tuple[tuple[str, str], ...] = ()
    _raw_configs: tuple[tuple[str, str, str], ...] = ()

    def raw_config_record(self, name: str, config_type: str) -> tuple[str, bytes]:
        """Exact activated classified path/bytes, before YAML or substitution.

        No new file read and no database fallback. The caller parses these SAME
        bytes with its duplicate/alias policy and binds the authorized launch id.
        """
        from temper_ai.config.admission_contract import AdmissionRefused, RefusalCode

        if self is not active() or type(name) is not str or type(config_type) is not str:
            raise AdmissionRefused(RefusalCode.ORIGIN)
        path = self.configs.get(config_type, {}).get(name)
        if (config_type, name, path) not in self._raw_configs:
            raise AdmissionRefused(RefusalCode.LOOKUP)
        if (type(path) is not str or not path.startswith("configs/")
                or any(p in ("", ".", "..") for p in path.split("/")) or "\0" in path):
            raise AdmissionRefused(RefusalCode.ORIGIN)
        data = self.files.get(path)
        if (type(data) is not bytes or len(data) > MAX_CONFIG_SIZE
                or (path, blob_id(data)) not in self._raw_files):
            raise AdmissionRefused(RefusalCode.ORIGIN)
        return path, data

    def _refuse(self, what: str) -> LaunchRefused:
        return LaunchRefused(f"{what} isn't part of this run's classified launch "
                             f"(workflow {self.workflow!r}); a sealed box refuses it")

    def check(self, kind: str, name: str | None) -> None:
        if name not in self.allowed[kind]:
            raise self._refuse(f"{kind.rstrip('s').replace('_', ' ')} {name!r}")

    def allows_tool(self, name: str) -> bool:
        return name in self.allowed["tools"]

    def config(self, name: str, config_type: str) -> dict[str, Any]:
        """A config as ConfigStore.get gives it, from the checked file: never the database."""
        path = self.configs.get(config_type, {}).get(name)
        if path is None:
            raise NotInLaunch(f"{config_type} config '{name}' isn't part of this run's "
                              f"classified launch (workflow {self.workflow!r})")
        data = self.files[path]
        if len(data) > MAX_CONFIG_SIZE:
            raise LaunchRefused(f"{path} is larger than a config may be")
        config = yaml.safe_load(data.decode("utf-8"))
        if not isinstance(config, dict):
            raise LaunchRefused(f"{path} isn't a mapping")
        check_schema_version({"schema_version": config.get("schema_version", "1.0")})
        return substitute_env_vars(config)


_ACTIVE: Guard | None = None


def activate(doc: Mapping[str, Any] | None, root: str | Path | None = None) -> Guard | None:
    """The guard for a box's checked profile: None for a legacy box (or none).

    A sealed profile's closure files are read and checked here, all of them, before the
    runner loads anything. Raises LaunchRefused when one is missing or changed.
    """
    global _ACTIVE
    _ACTIVE = None
    if not doc or doc.get("boundary") != "sealed":
        return None
    launch = doc.get("launch") or {}
    files = launch.get("files")
    allowed = launch.get("allowed")
    configs = launch.get("configs")
    if not isinstance(files, dict) or not files or not isinstance(allowed, dict) \
            or not isinstance(configs, dict):
        raise LaunchRefused("the box's profile doesn't say which files and classes its launch "
                            "has; a sealed box loads nothing without that")
    base = Path(root if root is not None else CONFIGS_ROOT)
    checked: dict[str, bytes] = {}
    for path, blob in sorted(files.items()):
        if not path.startswith("configs/") or ".." in Path(path).parts:
            raise LaunchRefused(f"the profile names {path!r}, which isn't a config file")
        try:
            data = (base / path.removeprefix("configs/")).read_bytes()
        except OSError as exc:
            raise LaunchRefused(f"{path} can't be read in this box ({exc.strerror})") from exc
        if blob_id(data) != blob:
            raise LaunchRefused(f"{path} isn't the file that was classified: it changed after "
                                "the worker classified the launch")
        checked[path] = data
    for names in configs.values():
        for path in names.values():
            if path not in checked:
                raise LaunchRefused(f"the profile's config {path!r} isn't among its files")
    _ACTIVE = Guard(
        workflow=str(launch.get("workflow")),
        files=checked,
        configs={kind: dict(names) for kind, names in configs.items()},
        allowed={kind: frozenset(allowed.get(kind) or ()) for kind in _KINDS},
        _raw_files=tuple(sorted(files.items())),
        _raw_configs=tuple(sorted((kind, name, path)
                                  for kind, names in configs.items()
                                  for name, path in names.items())),
    )
    return _ACTIVE


def active() -> Guard | None:
    return _ACTIVE


def reset() -> None:
    """Forget the guard (tests; a process runs one box's launch)."""
    global _ACTIVE
    _ACTIVE = None


# -- the places a run would use something -------------------------------------------------------


def check(kind: str, name: str | None) -> None:
    """Refuse ``name`` (an agent type, tool, provider or MCP server) outside the launch.

    In a oneshot box nothing is used before the runner's delivery is taken (BS2).
    """
    if not box_bootstrap.tools_allowed():
        raise LaunchRefused(f"{kind} {name!r} can't be used before the box's one-shot "
                            "delivery is taken and acknowledged")
    if _ACTIVE is not None:
        _ACTIVE.check(kind, name)


def classified_tools(names: Iterable[str]) -> tuple[list[str], list[str]]:
    """(kept, left out): the tool names a run may register."""
    names = list(names)
    if _ACTIVE is None:
        return names, []
    kept = [n for n in names if _ACTIVE.allows_tool(n)]
    return kept, [n for n in names if not _ACTIVE.allows_tool(n)]
