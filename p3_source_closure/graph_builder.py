"""Deterministic candidate p3-reviewed-source-graph/1 generator from Git objects.

Reads only committed Git objects (git rev-parse / ls-tree / cat-file) at the
requested commit — never the working tree — and computes static import closure
with ast. Produces a candidate ReviewedSourceGraph with completeness_review_ref
always None; generator self-consistency never claims independent review.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from . import records as t
from .parsing import byte_identity, canonical_bytes
from .reviewed_graph import validate_reviewed_graph


class _StrPathLike(Protocol):
    def __fspath__(self) -> str: ...

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


class GraphBuildError(ValueError):
    """Fail-loud error listing every unresolved import, dynamic construct, or input defect."""

    def __init__(self, code: str, items: Sequence[str] = ()) -> None:
        if not code:
            raise ValueError("GraphBuildError requires a non-empty code")
        self.code: str = code
        self.items: tuple[str, ...] = tuple(sorted(set(items)))
        detail = f": {', '.join(self.items)}" if self.items else ""
        super().__init__(f"{code}{detail}")


@dataclass(frozen=True, slots=True)
class EntrypointSpec:
    id: str
    profile_id: str
    target: str
    symbol: str
    bootstrap_chain: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProcessProfileSpec:
    id: str
    role: t.Role
    entrypoint_ids: tuple[str, ...]
    runtime_nodes: tuple[str, ...]
    extra_required_load_ids: tuple[str, ...] = ()
    extra_allowed_node_ids: tuple[str, ...] = ()
    child_profiles: tuple[str, ...] = ()
    load_policy_ref: t.EvidenceRef | None = None


@dataclass(frozen=True, slots=True)
class DeclaredNodeSpec:
    node: t.SourceNode
    module_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DynamicImportSpec:
    source: str
    target: str
    condition_ref: t.EvidenceRef


@dataclass(frozen=True, slots=True)
class _GitTreeEntry:
    mode: str
    obj_type: str
    object_id: str
    path: str
    module_name: str | None
    package_name: str | None


def _run_git(repo_dir: str, args: Sequence[str]) -> bytes:
    subprocess = __import__("subprocess")
    proc = subprocess.run(
        ["git", "-C", repo_dir, *args],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise GraphBuildError("GIT_OBJECT_ERROR", (f"git {' '.join(args)} rc={proc.returncode}",))
    return bytes(proc.stdout)


def _module_from_path(rel_path: str) -> tuple[str | None, str | None]:
    if not rel_path.endswith(".py"):
        return None, None
    if rel_path == "__init__.py":
        return None, None
    if rel_path.endswith("/__init__.py"):
        mod = rel_path[: -len("/__init__.py")].replace("/", ".")
        return mod, mod
    mod = rel_path[:-3].replace("/", ".")
    pkg = mod.rpartition(".")[0]
    return mod, pkg


def _load_git_tree(repo_dir: str, commit: str) -> tuple[Literal["sha1", "sha256"], str, dict[str, _GitTreeEntry], dict[str, _GitTreeEntry], list[str]]:
    if not isinstance(commit, str) or _COMMIT_RE.fullmatch(commit) is None:
        raise GraphBuildError("INVALID_COMMIT", (str(commit),))
    obj_type = _run_git(repo_dir, ("cat-file", "-t", commit)).decode("ascii", errors="replace").strip()
    if obj_type != "commit":
        raise GraphBuildError("INVALID_COMMIT", (commit,))
    tree_oid = _run_git(repo_dir, ("rev-parse", "--verify", f"{commit}^{{tree}}")).decode("ascii", errors="replace").strip()
    if _COMMIT_RE.fullmatch(tree_oid) is None or len(tree_oid) != len(commit):
        raise GraphBuildError("INVALID_TREE", (tree_oid,))
    object_format: Literal["sha1", "sha256"] = "sha256" if len(commit) == 64 else "sha1"
    raw = _run_git(repo_dir, ("ls-tree", "-r", "-z", tree_oid))
    by_path: dict[str, _GitTreeEntry] = {}
    by_module: dict[str, _GitTreeEntry] = {}
    collisions: list[str] = []
    for record in raw.split(b"\x00"):
        if not record:
            continue
        header, sep, path_bytes = record.partition(b"\t")
        if not sep:
            raise GraphBuildError("GIT_TREE_PARSE_ERROR", ("malformed ls-tree entry",))
        parts = header.decode("ascii", errors="replace").split(" ")
        if len(parts) != 3:
            raise GraphBuildError("GIT_TREE_PARSE_ERROR", ("malformed ls-tree header",))
        mode, entry_type, oid = parts
        rel_path = path_bytes.decode("utf-8", errors="strict")
        mod_name, pkg_name = _module_from_path(rel_path)
        entry = _GitTreeEntry(
            mode=mode,
            obj_type=entry_type,
            object_id=oid,
            path=rel_path,
            module_name=mod_name,
            package_name=pkg_name,
        )
        by_path[rel_path] = entry
        if mod_name is not None:
            if mod_name in by_module:
                collisions.append(f"module_collision:{mod_name}:{by_module[mod_name].path}:{rel_path}")
            else:
                by_module[mod_name] = entry
    return object_format, tree_oid, by_path, by_module, collisions


def _resolve_module_target(
    mod_name: str,
    by_module: dict[str, _GitTreeEntry],
    declared_by_module: dict[str, str],
) -> tuple[str, ...] | None:
    """Resolve a dotted module name to one or more node IDs (including parent packages)."""
    if not mod_name:
        return None
    parts = mod_name.split(".")
    if mod_name in by_module:
        targets: list[str] = []
        for idx in range(1, len(parts) + 1):
            prefix = ".".join(parts[:idx])
            if prefix in by_module:
                targets.append(prefix)
            elif prefix in declared_by_module:
                targets.append(declared_by_module[prefix])
        return tuple(dict.fromkeys(targets))
    for idx in range(len(parts), 0, -1):
        prefix = ".".join(parts[:idx])
        if prefix in declared_by_module:
            return (declared_by_module[prefix],)
    return None


def _collect_module_ast_deps(
    *,
    source_id: str,
    entry: _GitTreeEntry,
    blob_bytes: bytes,
    by_module: dict[str, _GitTreeEntry],
    by_path: dict[str, _GitTreeEntry],
    declared_by_id: dict[str, t.SourceNode],
    declared_by_module: dict[str, str],
    dynamic_map: dict[tuple[str, str], t.EvidenceRef],
    errors: list[str],
) -> tuple[tuple[str, ...], tuple[tuple[str, t.EvidenceRef], ...]]:
    rel_path = entry.path
    if entry.mode not in ("100644", "100755") or entry.obj_type != "blob":
        errors.append(f"{rel_path}:0:unsupported_git_entry:{entry.mode}:{entry.obj_type}")
        return (), ()
    if _ID_RE.fullmatch(source_id) is None:
        errors.append(f"{rel_path}:0:invalid_node_id:{source_id}")
        return (), ()
    try:
        source_text = blob_bytes.decode("utf-8")
        tree = ast.parse(source_text, filename=rel_path)
    except (UnicodeDecodeError, SyntaxError, ValueError) as exc:
        errors.append(f"{rel_path}:0:syntax_error:{type(exc).__name__}")
        return (), ()

    static_targets: list[str] = []
    dynamic_targets: list[tuple[str, t.EvidenceRef]] = []
    pkg_name = entry.package_name or ""

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = _resolve_module_target(alias.name, by_module, declared_by_module)
                if resolved is None:
                    errors.append(f"{rel_path}:{node.lineno}:unresolved_import:{alias.name}")
                else:
                    static_targets.extend(resolved)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                pkg_parts = pkg_name.split(".") if pkg_name else []
                up = node.level - 1
                if up > len(pkg_parts):
                    errors.append(f"{rel_path}:{node.lineno}:unresolved_import:relative_escape")
                    continue
                prefix_parts = pkg_parts[: len(pkg_parts) - up]
                base_mod = ".".join([*prefix_parts, node.module] if node.module else prefix_parts)
            else:
                base_mod = node.module or ""

            for alias in node.names:
                if alias.name == "*":
                    resolved_base = _resolve_module_target(base_mod, by_module, declared_by_module)
                    if resolved_base is None:
                        errors.append(f"{rel_path}:{node.lineno}:unresolved_import:{base_mod}.*")
                    else:
                        static_targets.extend(resolved_base)
                    continue
                cand_sub = f"{base_mod}.{alias.name}" if base_mod else alias.name
                resolved_sub = _resolve_module_target(cand_sub, by_module, declared_by_module)
                if resolved_sub is not None and (cand_sub in by_module or cand_sub in declared_by_module):
                    resolved_base = _resolve_module_target(base_mod, by_module, declared_by_module) if base_mod else ()
                    if resolved_base:
                        static_targets.extend(resolved_base)
                    static_targets.extend(resolved_sub)
                else:
                    resolved_base = _resolve_module_target(base_mod, by_module, declared_by_module)
                    if resolved_base is None:
                        errors.append(f"{rel_path}:{node.lineno}:unresolved_import:{cand_sub}")
                    else:
                        static_targets.extend(resolved_base)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in ("exec", "eval", "compile"):
                construct = func.id
                errors.append(f"{rel_path}:{node.lineno}:unresolved_dynamic:{construct}")
            elif (isinstance(func, ast.Name) and func.id in ("__import__", "import_module")) or (
                isinstance(func, ast.Attribute) and func.attr == "import_module"
            ):
                func_name = func.id if isinstance(func, ast.Name) else f"*.{func.attr}"
                if (
                    node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    raw_target = node.args[0].value
                    target_id = _resolve_ref_to_node_id(raw_target, by_path, by_module, declared_by_id, declared_by_module)
                    if target_id is not None and (source_id, target_id) in dynamic_map:
                        dynamic_targets.append((target_id, dynamic_map[(source_id, target_id)]))
                    else:
                        construct = f"{func_name}({raw_target})"
                        errors.append(f"{rel_path}:{node.lineno}:unresolved_dynamic:{construct}")
                else:
                    construct = func_name
                    errors.append(f"{rel_path}:{node.lineno}:unresolved_dynamic:{construct}")

    return tuple(dict.fromkeys(static_targets)), tuple(dict.fromkeys(dynamic_targets))


def _resolve_ref_to_node_id(
    ref_name: str,
    by_path: dict[str, _GitTreeEntry],
    by_module: dict[str, _GitTreeEntry],
    declared_by_id: dict[str, t.SourceNode],
    declared_by_module: dict[str, str],
) -> str | None:
    if ref_name in by_module:
        return ref_name
    if ref_name in by_path and by_path[ref_name].module_name is not None:
        return by_path[ref_name].module_name
    if ref_name in declared_by_id:
        return ref_name
    if ref_name in declared_by_module:
        return declared_by_module[ref_name]
    return None


def build_reviewed_source_graph(
    *,
    repo_path: str | _StrPathLike,
    commit: str,
    entrypoints: Sequence[EntrypointSpec],
    process_profiles: Sequence[ProcessProfileSpec],
    declared_nodes: Sequence[t.SourceNode | DeclaredNodeSpec] = (),
    dynamic_imports: Sequence[DynamicImportSpec] = (),
    graph_id: str = "candidate-graph",
    repository_id: str = "repo",
    repository_owner: Literal["ops", "architecture", "qa", "temper", "systems"] = "temper",
    supplier: str = "systems-graph-builder",
) -> t.ReviewedSourceGraph:
    """Build a candidate ReviewedSourceGraph from committed Git objects and declared profiles.

    Never reads working-tree files and never sets completeness_review_ref.
    """
    repo_dir = (
        str(repo_path)
        if not isinstance(repo_path, bool)
        and (isinstance(repo_path, str) or hasattr(repo_path, "__fspath__"))
        else ""
    )
    if not repo_dir:
        raise GraphBuildError("INVALID_REPO_PATH", ("empty repo_path",))
    if not entrypoints:
        raise GraphBuildError("EMPTY_ENTRYPOINTS", ("entrypoints must not be empty",))
    if not process_profiles:
        raise GraphBuildError("EMPTY_PROFILES", ("process_profiles must not be empty",))

    object_format, tree_oid, by_path, by_module, collisions = _load_git_tree(repo_dir, commit)
    if collisions:
        raise GraphBuildError("MODULE_COLLISION", collisions)

    declared_by_id: dict[str, t.SourceNode] = {}
    declared_by_module: dict[str, str] = {}
    config_errors: list[str] = []

    for item in declared_nodes:
        spec = item if isinstance(item, DeclaredNodeSpec) else DeclaredNodeSpec(node=item)
        node = spec.node
        if type(node) is not t.SourceNode:
            config_errors.append(f"invalid_declared_node:{node!r}")
            continue
        if node.id in declared_by_id or node.id in by_module:
            config_errors.append(f"duplicate_node_id:{node.id}")
            continue
        declared_by_id[node.id] = node
        for mod_name in spec.module_names:
            if mod_name in declared_by_module and declared_by_module[mod_name] != node.id:
                config_errors.append(f"duplicate_declared_module:{mod_name}")
            else:
                declared_by_module[mod_name] = node.id
        if node.kind in ("stdlib", "package", "generated", "cached_code", "native_binary"):
            declared_by_module.setdefault(node.id, node.id)

    dynamic_map: dict[tuple[str, str], t.EvidenceRef] = {}
    for dyn in dynamic_imports:
        src_id = _resolve_ref_to_node_id(dyn.source, by_path, by_module, declared_by_id, declared_by_module)
        dst_id = _resolve_ref_to_node_id(dyn.target, by_path, by_module, declared_by_id, declared_by_module)
        if src_id is None or dst_id is None:
            config_errors.append(f"invalid_dynamic_import_spec:{dyn.source}->{dyn.target}")
            continue
        dynamic_map[(src_id, dst_id)] = dyn.condition_ref

    profiles_by_id: dict[str, ProcessProfileSpec] = {}
    for prof in process_profiles:
        if prof.id in profiles_by_id:
            config_errors.append(f"duplicate_profile_id:{prof.id}")
            continue
        profiles_by_id[prof.id] = prof
        if not prof.entrypoint_ids:
            config_errors.append(f"empty_profile_entrypoints:{prof.id}")
        if not prof.runtime_nodes:
            config_errors.append(f"empty_profile_runtime_nodes:{prof.id}")
        has_interpreter = False
        for rt_id in prof.runtime_nodes:
            rt_node = declared_by_id.get(rt_id)
            if rt_node is None:
                config_errors.append(f"unknown_runtime_node:{prof.id}:{rt_id}")
            elif rt_node.kind == "interpreter":
                has_interpreter = True
        if not has_interpreter:
            config_errors.append(f"missing_interpreter_runtime_node:{prof.id}")

    entries_by_id: dict[str, EntrypointSpec] = {}
    resolved_entry_nodes: dict[str, str] = {}
    resolved_entry_boots: dict[str, tuple[str, ...]] = {}
    seed_nodes: list[str] = []

    for entry_spec in entrypoints:
        if entry_spec.id in entries_by_id:
            config_errors.append(f"duplicate_entrypoint_id:{entry_spec.id}")
            continue
        entries_by_id[entry_spec.id] = entry_spec
        if entry_spec.profile_id not in profiles_by_id:
            config_errors.append(f"unknown_entrypoint_profile:{entry_spec.id}:{entry_spec.profile_id}")
        node_id = _resolve_ref_to_node_id(entry_spec.target, by_path, by_module, declared_by_id, declared_by_module)
        if node_id is None:
            config_errors.append(f"unknown_entrypoint_target:{entry_spec.id}:{entry_spec.target}")
        else:
            resolved_entry_nodes[entry_spec.id] = node_id
            seed_nodes.append(node_id)
        boots: list[str] = []
        for boot_ref in entry_spec.bootstrap_chain:
            boot_id = _resolve_ref_to_node_id(boot_ref, by_path, by_module, declared_by_id, declared_by_module)
            if boot_id is None:
                config_errors.append(f"unknown_bootstrap_target:{entry_spec.id}:{boot_ref}")
            else:
                boots.append(boot_id)
                seed_nodes.append(boot_id)
        resolved_entry_boots[entry_spec.id] = tuple(boots)

    resolved_extra_req: dict[str, tuple[str, ...]] = {}
    resolved_extra_allow: dict[str, tuple[str, ...]] = {}
    for prof in process_profiles:
        for entry_id in prof.entrypoint_ids:
            if entry_id not in entries_by_id:
                config_errors.append(f"unknown_profile_entrypoint:{prof.id}:{entry_id}")
        for child_id in prof.child_profiles:
            if child_id not in profiles_by_id:
                config_errors.append(f"unknown_child_profile:{prof.id}:{child_id}")
        req_ids: list[str] = []
        for ref_name in prof.extra_required_load_ids:
            nid = _resolve_ref_to_node_id(ref_name, by_path, by_module, declared_by_id, declared_by_module)
            if nid is None:
                config_errors.append(f"unknown_required_load:{prof.id}:{ref_name}")
            else:
                req_ids.append(nid)
                seed_nodes.append(nid)
        resolved_extra_req[prof.id] = tuple(req_ids)
        allow_ids: list[str] = []
        for ref_name in prof.extra_allowed_node_ids:
            nid = _resolve_ref_to_node_id(ref_name, by_path, by_module, declared_by_id, declared_by_module)
            if nid is None:
                config_errors.append(f"unknown_allowed_node:{prof.id}:{ref_name}")
            else:
                allow_ids.append(nid)
                seed_nodes.append(nid)
        resolved_extra_allow[prof.id] = tuple(allow_ids)
        seed_nodes.extend(prof.runtime_nodes)

    if config_errors:
        raise GraphBuildError("INVALID_GRAPH_SPEC", config_errors)

    blob_cache: dict[str, bytes] = {}

    def read_blob(oid: str) -> bytes:
        if oid not in blob_cache:
            blob_cache[oid] = _run_git(repo_dir, ("cat-file", "blob", oid))
        return blob_cache[oid]

    reached_nodes: set[str] = set()
    queue: list[str] = list(dict.fromkeys(seed_nodes))
    static_adj: dict[str, list[str]] = {}
    dynamic_adj: dict[str, list[tuple[str, t.EvidenceRef]]] = {}
    edge_map: dict[tuple[str, str, str], t.SourceEdge] = {}
    closure_errors: list[str] = []

    def add_edge(src: str, dst: str, kind: Literal["bootstrap", "import", "dynamic_import", "resource", "generates", "generated_input", "links", "cache_of", "spawns"], cond: t.EvidenceRef | None = None) -> None:
        key = (src, dst, kind)
        if key not in edge_map:
            edge_map[key] = t.SourceEdge(source=src, target=dst, kind=kind, condition_ref=cond)

    for entry_spec in entrypoints:
        entry_nid = resolved_entry_nodes[entry_spec.id]
        for boot_nid in resolved_entry_boots[entry_spec.id]:
            add_edge(entry_nid, boot_nid, "bootstrap", None)
            static_adj.setdefault(entry_nid, []).append(boot_nid)

    while queue:
        current = queue.pop(0)
        if current in reached_nodes:
            continue
        reached_nodes.add(current)

        if current in by_module:
            git_entry = by_module[current]
            blob = read_blob(git_entry.object_id)
            stat_targets, dyn_targets = _collect_module_ast_deps(
                source_id=current,
                entry=git_entry,
                blob_bytes=blob,
                by_module=by_module,
                by_path=by_path,
                declared_by_id=declared_by_id,
                declared_by_module=declared_by_module,
                dynamic_map=dynamic_map,
                errors=closure_errors,
            )
            for target_id in stat_targets:
                add_edge(current, target_id, "import", None)
                static_adj.setdefault(current, []).append(target_id)
                if target_id not in reached_nodes:
                    queue.append(target_id)
            for target_id, cond_ref in dyn_targets:
                add_edge(current, target_id, "dynamic_import", cond_ref)
                dynamic_adj.setdefault(current, []).append((target_id, cond_ref))
                if target_id not in reached_nodes:
                    queue.append(target_id)
        elif current in declared_by_id:
            dec_node = declared_by_id[current]
            prov = dec_node.provenance
            if type(prov) is t.GeneratedProvenance:
                for inp in prov.inputs:
                    inp_id = _resolve_ref_to_node_id(inp, by_path, by_module, declared_by_id, declared_by_module)
                    if inp_id is None:
                        closure_errors.append(f"generated:{current}:unknown_input:{inp}")
                    else:
                        add_edge(inp_id, current, "generated_input", None)
                        if inp_id not in reached_nodes:
                            queue.append(inp_id)
                for gen in prov.generators:
                    gen_id = _resolve_ref_to_node_id(gen, by_path, by_module, declared_by_id, declared_by_module)
                    if gen_id is None:
                        closure_errors.append(f"generated:{current}:unknown_generator:{gen}")
                    else:
                        add_edge(gen_id, current, "generates", None)
                        if gen_id not in reached_nodes:
                            queue.append(gen_id)
            elif type(prov) is t.CachedProvenance:
                for src in prov.source_nodes:
                    src_id = _resolve_ref_to_node_id(src, by_path, by_module, declared_by_id, declared_by_module)
                    if src_id is None:
                        closure_errors.append(f"cached_code:{current}:unknown_source:{src}")
                    else:
                        add_edge(current, src_id, "cache_of", None)
                        if src_id not in reached_nodes:
                            queue.append(src_id)
            elif type(prov) is t.ArtifactProvenance:
                for src in (*prov.sources, *prov.dependencies):
                    src_id = _resolve_ref_to_node_id(src, by_path, by_module, declared_by_id, declared_by_module)
                    if src_id is None:
                        closure_errors.append(f"artifact:{current}:unknown_dependency:{src}")
                    elif src_id not in reached_nodes:
                        queue.append(src_id)
                if prov.interpreter and prov.interpreter not in reached_nodes:
                    interp_id = _resolve_ref_to_node_id(prov.interpreter, by_path, by_module, declared_by_id, declared_by_module)
                    if interp_id is None:
                        closure_errors.append(f"artifact:{current}:unknown_interpreter:{prov.interpreter}")
                    elif interp_id not in reached_nodes:
                        queue.append(interp_id)

    if closure_errors:
        raise GraphBuildError("UNRESOLVED_CLOSURE", closure_errors)

    for prof in process_profiles:
        parent_entries = [resolved_entry_nodes[eid] for eid in prof.entrypoint_ids]
        for child_prof_id in prof.child_profiles:
            child_prof = profiles_by_id[child_prof_id]
            for pe in parent_entries:
                for ce_id in child_prof.entrypoint_ids:
                    add_edge(pe, resolved_entry_nodes[ce_id], "spawns", None)

    nodes_out: list[t.SourceNode] = []
    for node_id in sorted(reached_nodes):
        if node_id in by_module:
            git_entry = by_module[node_id]
            blob = read_blob(git_entry.object_id)
            mode_lit: Literal["100644", "100755"] = "100755" if git_entry.mode == "100755" else "100644"
            membership_ref = t.EvidenceRef(
                "p3-evidence/1",
                byte_identity(f"membership:{repository_id}:{commit}:{tree_oid}:{git_entry.path}:{mode_lit}:{git_entry.object_id}".encode()),
                supplier,
                f"membership-{node_id}",
            )
            git_prov = t.GitProvenance(
                tag="git",
                repository=repository_id,
                commit=commit,
                tree=tree_oid,
                path=git_entry.path,
                mode=mode_lit,
                object_id=git_entry.object_id,
                membership_ref=membership_ref,
                target_chain=(),
                representation="regular",
            )
            nodes_out.append(
                t.SourceNode(
                    id=node_id,
                    kind="git_source",
                    content=byte_identity(blob),
                    logical_origin=f"git:{repository_id}:{git_entry.path}",
                    mode=mode_lit,
                    provenance=git_prov,
                )
            )
        else:
            nodes_out.append(declared_by_id[node_id])

    entrypoints_out = tuple(
        t.Entrypoint(
            id=espec.id,
            profile_id=espec.profile_id,
            node=resolved_entry_nodes[espec.id],
            symbol_or_invocation=espec.symbol,
            bootstrap_chain=resolved_entry_boots[espec.id],
        )
        for espec in entrypoints
    )

    def transitive_static(seeds: Sequence[str]) -> list[str]:
        seen: list[str] = []
        work = list(seeds)
        while work:
            cur = work.pop(0)
            if cur in seen:
                continue
            seen.append(cur)
            for nxt in static_adj.get(cur, ()):
                if nxt not in seen:
                    work.append(nxt)
        return seen

    def transitive_allowed(seeds: Sequence[str]) -> list[str]:
        seen: list[str] = []
        work = list(seeds)
        while work:
            cur = work.pop(0)
            if cur in seen:
                continue
            seen.append(cur)
            for nxt in static_adj.get(cur, ()):
                if nxt not in seen:
                    work.append(nxt)
            for dyn_nxt, _cond in dynamic_adj.get(cur, ()):
                if dyn_nxt not in seen:
                    work.append(dyn_nxt)
        return seen

    profiles_out: list[t.ProcessProfile] = []
    for prof in process_profiles:
        req_seeds: list[str] = []
        for eid in prof.entrypoint_ids:
            req_seeds.append(resolved_entry_nodes[eid])
            req_seeds.extend(resolved_entry_boots[eid])
        req_seeds.extend(resolved_extra_req[prof.id])
        runtime_set = set(prof.runtime_nodes)
        extra_req_set = set(resolved_extra_req[prof.id])
        req_closure = [
            nid
            for nid in transitive_static(req_seeds)
            if nid not in runtime_set or nid in extra_req_set
        ]
        allow_seeds = [*prof.runtime_nodes, *req_closure, *resolved_extra_allow[prof.id]]
        allow_closure = transitive_allowed(allow_seeds)
        policy_ref = prof.load_policy_ref or t.EvidenceRef(
            "p3-evidence/1",
            byte_identity(f"policy:{graph_id}:{prof.id}".encode()),
            supplier,
            f"policy-{prof.id}",
        )
        profiles_out.append(
            t.ProcessProfile(
                id=prof.id,
                role=prof.role,
                entrypoint_ids=prof.entrypoint_ids,
                runtime_nodes=prof.runtime_nodes,
                allowed_node_ids=tuple(allow_closure),
                required_load_ids=tuple(req_closure),
                child_profiles=prof.child_profiles,
                load_policy_ref=policy_ref,
            )
        )

    repo_record = t.Repository(
        id=repository_id,
        owner=repository_owner,
        object_format=object_format,
        commit=commit,
        tree=tree_oid,
    )
    edges_out = tuple(edge_map[k] for k in sorted(edge_map))
    graph = t.SourceGraph(
        schema="p3-reviewed-source-graph/1",
        graph_id=graph_id,
        repositories=(repo_record,),
        nodes=tuple(nodes_out),
        edges=edges_out,
        entrypoints=entrypoints_out,
        process_profiles=tuple(profiles_out),
        completeness_review_ref=None,
    )
    return validate_reviewed_graph(canonical_bytes(graph))
