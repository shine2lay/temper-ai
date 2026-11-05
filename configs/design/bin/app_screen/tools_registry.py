"""Design's registry of existing tools (configs/design/knowledge/tools.yaml): check it, list a stage's tools.

Rule 36 (reuse first): before a stage writes new code it looks here. check() runs on the host and fails loud on
a missing field, an unknown stage, a duplicate id or a path that does not exist (a tool given by url is not
path-checked). stage_tools(stage) lists the entries for one app-screen stage, and task_section(stage) is the
input section a stage's task text carries ("Existing tools; use before writing new code"). Model-free.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]                    # configs/design/bin/app_screen -> temper-ai
REGISTRY = Path(__file__).resolve().parents[2] / "knowledge" / "tools.yaml"
FIELDS = ("id", "job", "inputs", "outputs", "proven_on", "owner", "stages")
STAGES = ("intake", "existing", "ground", "directions", "build", "checks", "review", "show", "handoff")
TITLE = "Existing tools; use before writing new code (context for later stages, not sources to cite)"


class ToolsRegistryError(RuntimeError):
    pass


def load(registry: Path | None = None) -> list[dict]:
    path = registry or REGISTRY
    if not path.is_file():
        raise ToolsRegistryError(f"the tool registry {path} is missing")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("tools"), list) or not data["tools"]:
        raise ToolsRegistryError(f"{path} holds no 'tools:' list")
    return data["tools"]


def _where(tool: dict, repo: Path) -> Path | None:
    if "path" not in tool:
        return None
    p = Path(tool["path"])
    return None if p.is_absolute() else repo / p


def problems(tools: list[dict], repo: Path | None = None) -> list[str]:
    repo = repo or REPO
    out, seen = [], set()
    for n, tool in enumerate(tools):
        label = f"tools[{n}] {tool.get('id', '?')}" if isinstance(tool, dict) else f"tools[{n}]"
        if not isinstance(tool, dict):
            out.append(f"{label}: not a mapping")
            continue
        out += [f"{label}: missing {f}" for f in FIELDS if tool.get(f) in (None, "", [])]
        if ("path" in tool) == ("url" in tool):
            out.append(f"{label}: give exactly one of path or url")
        if "path" in tool and Path(tool["path"]).is_absolute():
            out.append(f"{label}: path {tool['path']} is absolute; paths in the registry must be relative to the repo")
        where = _where(tool, repo)
        if where is not None and not where.exists():
            out.append(f"{label}: path {tool['path']} does not exist")
        bad = [s for s in tool.get("stages") or [] if s not in STAGES]
        if bad:
            out.append(f"{label}: unknown stage(s) {', '.join(map(str, bad))}; stages are {', '.join(STAGES)}")
        if tool.get("id") in seen:
            out.append(f"{label}: duplicate id")
        seen.add(tool.get("id"))
    return out


def check(registry: Path | None = None, repo: Path | None = None) -> dict:
    """Fail loud on any problem; else the registry's size per stage."""
    tools = load(registry)
    found = problems(tools, repo)
    if found:
        raise ToolsRegistryError(f"{registry or REGISTRY}: {len(found)} problem(s): " + "; ".join(found))
    return {"tools": len(tools), "per_stage": {s: len(stage_tools(s, tools)) for s in STAGES}}


def stage_tools(stage: str, tools: list[dict] | None = None) -> list[dict]:
    if stage not in STAGES:
        raise ToolsRegistryError(f"unknown stage {stage!r}; stages are {', '.join(STAGES)}")
    return [t for t in (tools if tools is not None else load()) if stage in t.get("stages", [])]


def task_section(stage: str, tools: list[dict] | None = None) -> list[str]:
    """The task text's input section for one stage: one line per tool (id: job; path or url)."""
    entries = stage_tools(stage, tools)
    if not entries:
        return []
    return ["", f"## {TITLE}"] + [f"- {t['id']}: {t['job']} ({t.get('path') or t.get('url')})" for t in entries]
