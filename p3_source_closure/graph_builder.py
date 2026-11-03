"""Deterministic candidate p3-reviewed-source-graph/1 generator from Git objects.

Reads only committed Git objects (git rev-parse / ls-tree / cat-file) at the
requested commits — never the working tree — and computes static import closure
with ast. Produces a candidate ReviewedSourceGraph with completeness_review_ref
always None; generator self-consistency never claims independent review.

Two input forms, exactly one per call:
- single repository (repo_path, commit, repository_id, repository_owner): modules
  are named from the repository root and node ids are those module names;
- several repositories (repositories=[RepositorySpec, ...]): every process profile
  names its ordered import roots (module_path, like sys.path), every reference to
  a repository file is "<repository_id>:<path or module>", and git node ids are
  "<repository_id>.<module named from that repository's root>".
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, get_args

from . import records as t
from .import_roots import (
    ImportRoot,
    ModuleRootResolver,
    RepositoryTree,
    Resolution,
    UnsupportedEntry,
    import_root_problems,
    module_from_path,
)
from .parsing import byte_identity, canonical_bytes
from .reviewed_graph import validate_reviewed_graph


class _StrPathLike(Protocol):
    def __fspath__(self) -> str: ...

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")

RepositoryOwner = Literal["ops", "architecture", "qa", "temper", "systems"]
_EdgeKind = Literal["bootstrap", "import", "dynamic_import", "resource", "generates", "generated_input", "links", "cache_of", "spawns"]


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
class RepositorySpec:
    """One repository at one commit; the same repository at two commits is two specs with distinct ids.

    Node ids are "<id>.<module from the repository root>", unique per graph (NODE_ID_COLLISION
    otherwise). An id may hold ".", so read a node's repository and path from its provenance,
    never by splitting its id.
    """

    id: str
    owner: RepositoryOwner
    repo_path: str | _StrPathLike
    commit: str


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
    # Ordered (repository_id, directory) import roots, like sys.path; required with
    # repositories=, must stay empty in the single-repository form (repository root).
    module_path: tuple[ImportRoot, ...] = ()


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


@dataclass(frozen=True, slots=True)
class _LoadedRepository:
    id: str
    owner: RepositoryOwner
    repo_dir: str
    object_format: Literal["sha1", "sha256"]
    commit: str
    tree: str
    by_path: dict[str, _GitTreeEntry]
    by_module: dict[str, _GitTreeEntry]


@dataclass(frozen=True, slots=True)
class _GitNode:
    repository: _LoadedRepository
    entry: _GitTreeEntry


@dataclass(frozen=True, slots=True)
class _Reach:
    """A node reached by an import, with the module name it binds as (None: not a named source module)."""

    node_id: str
    module_name: str | None


class _ImportScope(Protocol):
    """How one walk context (a profile's import roots, or the single repository root) resolves imports."""

    label: str

    def package_for(self, node_id: str, module_name: str | None) -> str | None: ...

    def resolve_module(self, name: str) -> tuple[_Reach, ...] | None: ...

    def is_importable_module(self, name: str) -> bool: ...

    def resolve_dynamic_target(self, name: str) -> _Reach | None: ...

    def reach(self, node_id: str) -> _Reach: ...


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


def _is_regular_file(entry: _GitTreeEntry) -> bool:
    return entry.mode in ("100644", "100755") and entry.obj_type == "blob"


def _module_from_path(rel_path: str) -> tuple[str | None, str | None]:
    return module_from_path(rel_path)


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
    return _resolve_declared_prefix(mod_name, declared_by_module)


def _resolve_declared_prefix(mod_name: str, declared_by_module: dict[str, str]) -> tuple[str, ...] | None:
    """Longest declared module prefix of a dotted name (stdlib, packages, generated code)."""
    parts = mod_name.split(".")
    for idx in range(len(parts), 0, -1):
        prefix = ".".join(parts[:idx])
        if prefix in declared_by_module:
            return (declared_by_module[prefix],)
    return None


def _collect_module_ast_deps(
    *,
    source_id: str,
    entry: _GitTreeEntry,
    error_path: str,
    blob_bytes: bytes,
    package_name: str | None,
    resolve_module: Callable[[str], tuple[str, ...] | None],
    is_importable_module: Callable[[str], bool],
    resolve_dynamic_target: Callable[[str], str | None],
    dynamic_map: dict[tuple[str, str], t.EvidenceRef],
    errors: list[str],
) -> tuple[tuple[str, ...], tuple[tuple[str, t.EvidenceRef], ...]]:
    """Static and declared-dynamic import targets of one source file; package_name None = no parent package.

    error_path names the file in error items: its path, repository-qualified with several repositories.
    """
    rel_path = error_path
    if not _is_regular_file(entry):
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

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = resolve_module(alias.name)
                if resolved is None:
                    errors.append(f"{rel_path}:{node.lineno}:unresolved_import:{alias.name}")
                else:
                    static_targets.extend(resolved)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                if package_name is None:
                    errors.append(f"{rel_path}:{node.lineno}:unresolved_import:relative_without_package")
                    continue
                pkg_parts = package_name.split(".") if package_name else []
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
                    resolved_base = resolve_module(base_mod)
                    if resolved_base is None:
                        errors.append(f"{rel_path}:{node.lineno}:unresolved_import:{base_mod}.*")
                    else:
                        static_targets.extend(resolved_base)
                    continue
                cand_sub = f"{base_mod}.{alias.name}" if base_mod else alias.name
                resolved_sub = resolve_module(cand_sub)
                if resolved_sub is not None and is_importable_module(cand_sub):
                    resolved_base = resolve_module(base_mod) if base_mod else ()
                    if resolved_base:
                        static_targets.extend(resolved_base)
                    static_targets.extend(resolved_sub)
                else:
                    resolved_base = resolve_module(base_mod)
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
                    target_id = resolve_dynamic_target(raw_target)
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


class _RepositoryRootScope:
    """Single-repository form: modules named from the repository root, node id = module name."""

    label = "repository-root"

    def __init__(
        self,
        repository: _LoadedRepository,
        declared_by_id: dict[str, t.SourceNode],
        declared_by_module: dict[str, str],
    ) -> None:
        self._repository = repository
        self._declared_by_id = declared_by_id
        self._declared_by_module = declared_by_module

    def package_for(self, node_id: str, module_name: str | None) -> str | None:
        return self._repository.by_module[node_id].package_name or ""

    def resolve_module(self, name: str) -> tuple[_Reach, ...] | None:
        resolved = _resolve_module_target(name, self._repository.by_module, self._declared_by_module)
        return None if resolved is None else tuple(_Reach(node_id, node_id) for node_id in resolved)

    def is_importable_module(self, name: str) -> bool:
        return name in self._repository.by_module or name in self._declared_by_module

    def resolve_dynamic_target(self, name: str) -> _Reach | None:
        node_id = _resolve_ref_to_node_id(
            name, self._repository.by_path, self._repository.by_module, self._declared_by_id, self._declared_by_module
        )
        return None if node_id is None else _Reach(node_id, node_id)

    def reach(self, node_id: str) -> _Reach:
        return _Reach(node_id, node_id)


class _ProfileRootsScope:
    """Several-repository form: one profile's ordered import roots, resolved in Python's import order."""

    def __init__(
        self,
        profile_id: str,
        resolver: ModuleRootResolver,
        git_nodes: dict[str, _GitNode],
        git_node_ids: dict[tuple[str, str], str],
        declared_by_id: dict[str, t.SourceNode],
        declared_by_module: dict[str, str],
    ) -> None:
        self.label = profile_id
        self._resolver = resolver
        self._git_nodes = git_nodes
        self._git_node_ids = git_node_ids
        self._declared_by_id = declared_by_id
        self._declared_by_module = declared_by_module
        self._unsupported: dict[str, None] = {}

    def unsupported_entry_errors(self) -> tuple[str, ...]:
        """Closure error items for symlinks and gitlinks an import met at a search position."""
        return tuple(self._unsupported)

    def _resolve(self, name: str) -> Resolution | None:
        resolution = self._resolver.resolve(name)
        if isinstance(resolution, UnsupportedEntry):
            item = f"{resolution.repository_id}:{resolution.path}:0:unsupported_git_entry:{resolution.mode}:{resolution.object_type}"
            self._unsupported[item] = None
            return None
        return resolution

    def package_for(self, node_id: str, module_name: str | None) -> str | None:
        if module_name is None:
            return None
        is_package = self._git_nodes[node_id].entry.path.endswith("/__init__.py")
        package = module_name if is_package else module_name.rpartition(".")[0]
        return package or None

    def resolve_module(self, name: str) -> tuple[_Reach, ...] | None:
        resolution = self._resolve(name)
        if resolution is None:
            return None
        reaches = [
            _Reach(self._git_node_ids[(module.repository_id, module.path)], module.module_name)
            for module in resolution.files
        ]
        if resolution.declared_module is not None:
            reaches.append(_Reach(self._declared_by_module[resolution.declared_module], None))
        return tuple(reaches)

    def is_importable_module(self, name: str) -> bool:
        resolution = self._resolve(name)
        return resolution is not None and resolution.declared_module in (None, name)

    def resolve_dynamic_target(self, name: str) -> _Reach | None:
        resolution = self._resolve(name)
        if resolution is not None and resolution.declared_module is None and resolution.files:
            module = resolution.files[-1]
            if module.module_name == name:
                return _Reach(self._git_node_ids[(module.repository_id, module.path)], name)
        if resolution is not None and resolution.declared_module == name:
            return _Reach(self._declared_by_module[name], None)
        if name in self._declared_by_id:
            return _Reach(name, None)
        return None

    def reach(self, node_id: str) -> _Reach:
        git_node = self._git_nodes.get(node_id)
        if git_node is None:
            return _Reach(node_id, None)
        return _Reach(node_id, self._resolver.module_name_for_file(git_node.repository.id, git_node.entry.path))


def _repo_dir_of(repo_path: object) -> str:
    return (
        str(repo_path)
        if not isinstance(repo_path, bool)
        and (isinstance(repo_path, str) or hasattr(repo_path, "__fspath__"))
        else ""
    )


def _load_repositories(repositories: Sequence[RepositorySpec]) -> dict[str, _LoadedRepository]:
    specs = tuple(repositories)
    if not specs:
        raise GraphBuildError("EMPTY_REPOSITORIES", ("repositories must not be empty",))
    spec_errors: list[str] = []
    for spec in specs:
        if type(spec) is not RepositorySpec:
            spec_errors.append(f"invalid_repository_spec:{spec!r}")
            continue
        if not isinstance(spec.id, str) or _ID_RE.fullmatch(spec.id) is None:
            spec_errors.append(f"invalid_repository_id:{spec.id}")
        if not _repo_dir_of(spec.repo_path):
            spec_errors.append(f"empty_repo_path:{spec.id}")
        if spec.owner not in get_args(RepositoryOwner):
            spec_errors.append(f"invalid_repository_owner:{spec.id}:{spec.owner}")
    ids = [spec.id for spec in specs if type(spec) is RepositorySpec]
    spec_errors.extend(f"duplicate_repository_id:{repo_id}" for repo_id in ids if ids.count(repo_id) > 1)
    if spec_errors:
        raise GraphBuildError("INVALID_REPOSITORY_SPEC", spec_errors)
    loaded: dict[str, _LoadedRepository] = {}
    collisions: list[str] = []
    for spec in specs:
        repo_dir = _repo_dir_of(spec.repo_path)
        object_format, tree_oid, by_path, by_module, repo_collisions = _load_git_tree(repo_dir, spec.commit)
        collisions.extend(f"{spec.id}:{item}" for item in repo_collisions)
        loaded[spec.id] = _LoadedRepository(
            id=spec.id,
            owner=spec.owner,
            repo_dir=repo_dir,
            object_format=object_format,
            commit=spec.commit,
            tree=tree_oid,
            by_path=by_path,
            by_module=by_module,
        )
    if collisions:
        raise GraphBuildError("MODULE_COLLISION", collisions)
    return loaded


def build_reviewed_source_graph(
    *,
    repo_path: str | _StrPathLike | None = None,
    commit: str | None = None,
    entrypoints: Sequence[EntrypointSpec],
    process_profiles: Sequence[ProcessProfileSpec],
    declared_nodes: Sequence[t.SourceNode | DeclaredNodeSpec] = (),
    dynamic_imports: Sequence[DynamicImportSpec] = (),
    graph_id: str = "candidate-graph",
    repository_id: str | None = None,
    repository_owner: RepositoryOwner | None = None,
    repositories: Sequence[RepositorySpec] | None = None,
    supplier: str = "systems-graph-builder",
) -> t.ReviewedSourceGraph:
    """Build a candidate ReviewedSourceGraph from committed Git objects and declared profiles.

    Give either the single-repository keywords (repo_path, commit, optional
    repository_id/repository_owner) or repositories=, never both or neither.
    Never reads working-tree files and never sets completeness_review_ref.
    """
    single_form = any(value is not None for value in (repo_path, commit, repository_id, repository_owner))
    if single_form and repositories is not None:
        raise GraphBuildError("INVALID_REPOSITORY_FORM", ("give single-repository keywords or repositories, not both",))
    if not single_form and repositories is None:
        raise GraphBuildError("INVALID_REPOSITORY_FORM", ("give single-repository keywords or repositories",))
    if single_form:
        repo_dir = _repo_dir_of(repo_path)
        if not repo_dir:
            raise GraphBuildError("INVALID_REPO_PATH", ("empty repo_path",))
    if not entrypoints:
        raise GraphBuildError("EMPTY_ENTRYPOINTS", ("entrypoints must not be empty",))
    if not process_profiles:
        raise GraphBuildError("EMPTY_PROFILES", ("process_profiles must not be empty",))

    loaded: dict[str, _LoadedRepository]
    if single_form:
        single_commit = commit if commit is not None else ""
        object_format, tree_oid, by_path, by_module, collisions = _load_git_tree(repo_dir, single_commit)
        if collisions:
            raise GraphBuildError("MODULE_COLLISION", collisions)
        single_repository = _LoadedRepository(
            id=repository_id if repository_id is not None else "repo",
            owner=repository_owner if repository_owner is not None else "temper",
            repo_dir=repo_dir,
            object_format=object_format,
            commit=single_commit,
            tree=tree_oid,
            by_path=by_path,
            by_module=by_module,
        )
        loaded = {single_repository.id: single_repository}
        git_nodes = {mod: _GitNode(single_repository, entry) for mod, entry in by_module.items()}
    else:
        loaded = _load_repositories(repositories or ())
        git_nodes = {}
        id_collisions: list[str] = []
        for repository in loaded.values():
            for mod, entry in repository.by_module.items():
                prefixed_id = f"{repository.id}.{mod}"
                other = git_nodes.get(prefixed_id)
                if other is not None:
                    id_collisions.append(
                        f"{prefixed_id}:{other.repository.id}:{other.entry.path}:{repository.id}:{entry.path}"
                    )
                else:
                    git_nodes[prefixed_id] = _GitNode(repository, entry)
        if id_collisions:
            raise GraphBuildError("NODE_ID_COLLISION", id_collisions)
    git_node_ids = {(node.repository.id, node.entry.path): node_id for node_id, node in git_nodes.items()}

    declared_by_id: dict[str, t.SourceNode] = {}
    declared_by_module: dict[str, str] = {}
    config_errors: list[str] = []

    for item in declared_nodes:
        spec = item if isinstance(item, DeclaredNodeSpec) else DeclaredNodeSpec(node=item)
        node = spec.node
        if type(node) is not t.SourceNode:
            config_errors.append(f"invalid_declared_node:{node!r}")
            continue
        if node.id in declared_by_id or node.id in git_nodes:
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

    def resolve_ref(ref_name: str) -> str | None:
        """Entry, bootstrap, extra and dynamic-spec references to node ids."""
        if single_form:
            return _resolve_ref_to_node_id(
                ref_name, single_repository.by_path, single_repository.by_module, declared_by_id, declared_by_module
            )
        repo_id, sep, rest = ref_name.partition(":")
        if sep:
            repository = loaded.get(repo_id)
            if repository is None:
                return None
            if rest in repository.by_module:
                return f"{repo_id}.{rest}"
            path_entry = repository.by_path.get(rest)
            if path_entry is not None and path_entry.module_name is not None:
                return f"{repo_id}.{path_entry.module_name}"
            return None
        if ref_name in declared_by_id:
            return ref_name
        if ref_name in declared_by_module:
            return declared_by_module[ref_name]
        return None

    def resolve_node(ref_name: str) -> str | None:
        """Node-id references inside declared provenance."""
        if single_form:
            return resolve_ref(ref_name)
        if ref_name in git_nodes or ref_name in declared_by_id:
            return ref_name
        return declared_by_module.get(ref_name)

    def ref_error(kind: str, owner: str, ref_name: str) -> str:
        if not single_form and ":" not in ref_name:
            return f"unqualified_ref:{kind}:{owner}:{ref_name}"
        return f"{kind}:{owner}:{ref_name}"

    dynamic_map: dict[tuple[str, str], t.EvidenceRef] = {}
    for dyn in dynamic_imports:
        src_id = resolve_ref(dyn.source)
        dst_id = resolve_ref(dyn.target)
        if src_id is None or dst_id is None:
            failed_refs = [ref for ref, nid in ((dyn.source, src_id), (dyn.target, dst_id)) if nid is None]
            unqualified = not single_form and any(":" not in ref for ref in failed_refs)
            prefix = "unqualified_ref:dynamic_import" if unqualified else "invalid_dynamic_import_spec"
            config_errors.append(f"{prefix}:{dyn.source}->{dyn.target}")
            continue
        dynamic_map[(src_id, dst_id)] = dyn.condition_ref

    trees = (
        {
            repo_id: RepositoryTree.from_paths(
                repository.by_path,
                {path: (entry.mode, entry.obj_type) for path, entry in repository.by_path.items() if not _is_regular_file(entry)},
            )
            for repo_id, repository in loaded.items()
        }
        if not single_form
        else {}
    )
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
        if single_form:
            if prof.module_path:
                config_errors.append(f"module_path_needs_repositories:{prof.id}")
        elif not prof.module_path:
            config_errors.append(f"missing_module_path:{prof.id}")
        else:
            config_errors.extend(
                f"invalid_module_path:{prof.id}:{problem}" for problem in import_root_problems(prof.module_path, trees)
            )

    entries_by_id: dict[str, EntrypointSpec] = {}
    resolved_entry_nodes: dict[str, str] = {}
    resolved_entry_boots: dict[str, tuple[str, ...]] = {}
    seed_nodes: list[tuple[str, str]] = []

    for entry_spec in entrypoints:
        if entry_spec.id in entries_by_id:
            config_errors.append(f"duplicate_entrypoint_id:{entry_spec.id}")
            continue
        entries_by_id[entry_spec.id] = entry_spec
        if entry_spec.profile_id not in profiles_by_id:
            config_errors.append(f"unknown_entrypoint_profile:{entry_spec.id}:{entry_spec.profile_id}")
        node_id = resolve_ref(entry_spec.target)
        if node_id is None:
            config_errors.append(ref_error("unknown_entrypoint_target", entry_spec.id, entry_spec.target))
        else:
            resolved_entry_nodes[entry_spec.id] = node_id
            seed_nodes.append((entry_spec.profile_id, node_id))
        boots: list[str] = []
        for boot_ref in entry_spec.bootstrap_chain:
            boot_id = resolve_ref(boot_ref)
            if boot_id is None:
                config_errors.append(ref_error("unknown_bootstrap_target", entry_spec.id, boot_ref))
            else:
                boots.append(boot_id)
                seed_nodes.append((entry_spec.profile_id, boot_id))
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
            nid = resolve_ref(ref_name)
            if nid is None:
                config_errors.append(ref_error("unknown_required_load", prof.id, ref_name))
            else:
                req_ids.append(nid)
                seed_nodes.append((prof.id, nid))
        resolved_extra_req[prof.id] = tuple(req_ids)
        allow_ids: list[str] = []
        for ref_name in prof.extra_allowed_node_ids:
            nid = resolve_ref(ref_name)
            if nid is None:
                config_errors.append(ref_error("unknown_allowed_node", prof.id, ref_name))
            else:
                allow_ids.append(nid)
                seed_nodes.append((prof.id, nid))
        resolved_extra_allow[prof.id] = tuple(allow_ids)
        seed_nodes.extend((prof.id, rt_id) for rt_id in prof.runtime_nodes)

    if config_errors:
        raise GraphBuildError("INVALID_GRAPH_SPEC", config_errors)

    scopes: dict[str, _ImportScope] = {}
    profile_scopes: list[_ProfileRootsScope] = []
    if single_form:
        single_scope = _RepositoryRootScope(single_repository, declared_by_id, declared_by_module)
        scopes = {prof_id: single_scope for prof_id in profiles_by_id}
    else:
        for prof_id, prof in profiles_by_id.items():
            profile_scope = _ProfileRootsScope(
                prof_id,
                ModuleRootResolver(prof.module_path, trees, frozenset(declared_by_module)),
                git_nodes,
                git_node_ids,
                declared_by_id,
                declared_by_module,
            )
            scopes[prof_id] = profile_scope
            profile_scopes.append(profile_scope)

    blob_cache: dict[str, bytes] = {}

    def read_blob(git_node: _GitNode) -> bytes:
        oid = git_node.entry.object_id
        if oid not in blob_cache:
            blob_cache[oid] = _run_git(git_node.repository.repo_dir, ("cat-file", "blob", oid))
        return blob_cache[oid]

    # A walk state is (scope label, node id, module name the node binds as). The single-repository
    # form has one scope and one state per node; with import roots each profile walks its own roots.
    reached_nodes: set[str] = set()
    seen_states: set[tuple[str, str, str | None]] = set()
    queue: list[tuple[_ImportScope, _Reach]] = []
    static_adj: dict[str, list[str]] = {}
    dynamic_adj: dict[str, list[tuple[str, t.EvidenceRef]]] = {}
    first_analysis: dict[str, tuple[tuple[str, ...], tuple[tuple[str, t.EvidenceRef], ...], str]] = {}
    edge_map: dict[tuple[str, str, str], t.SourceEdge] = {}
    closure_errors: list[str] = []
    conflicts: list[str] = []

    def add_edge(src: str, dst: str, kind: _EdgeKind, cond: t.EvidenceRef | None = None) -> None:
        key = (src, dst, kind)
        if key not in edge_map:
            edge_map[key] = t.SourceEdge(source=src, target=dst, kind=kind, condition_ref=cond)

    def enqueue(scope: _ImportScope, reach: _Reach) -> None:
        if (scope.label, reach.node_id, reach.module_name) not in seen_states:
            queue.append((scope, reach))

    for entry_spec in entrypoints:
        entry_nid = resolved_entry_nodes[entry_spec.id]
        for boot_nid in resolved_entry_boots[entry_spec.id]:
            add_edge(entry_nid, boot_nid, "bootstrap", None)
            static_adj.setdefault(entry_nid, []).append(boot_nid)

    for prof_id, seed_id in dict.fromkeys(seed_nodes):
        enqueue(scopes[prof_id], scopes[prof_id].reach(seed_id))

    while queue:
        scope, reach = queue.pop(0)
        state = (scope.label, reach.node_id, reach.module_name)
        if state in seen_states:
            continue
        seen_states.add(state)
        current = reach.node_id
        reached_nodes.add(current)

        if current in git_nodes:
            git_node = git_nodes[current]
            bound_names: dict[str, list[str | None]] = {}

            def resolve_ids(name: str, scope: _ImportScope = scope, bound_names: dict[str, list[str | None]] = bound_names) -> tuple[str, ...] | None:
                reaches = scope.resolve_module(name)
                if reaches is None:
                    return None
                for item in reaches:
                    bound_names.setdefault(item.node_id, []).append(item.module_name)
                return tuple(dict.fromkeys(item.node_id for item in reaches))

            def resolve_dynamic_id(name: str, scope: _ImportScope = scope, bound_names: dict[str, list[str | None]] = bound_names) -> str | None:
                target = scope.resolve_dynamic_target(name)
                if target is None:
                    return None
                bound_names.setdefault(target.node_id, []).append(target.module_name)
                return target.node_id

            stat_targets, dyn_targets = _collect_module_ast_deps(
                source_id=current,
                entry=git_node.entry,
                error_path=git_node.entry.path if single_form else f"{git_node.repository.id}:{git_node.entry.path}",
                blob_bytes=read_blob(git_node),
                package_name=scope.package_for(current, reach.module_name),
                resolve_module=resolve_ids,
                is_importable_module=scope.is_importable_module,
                resolve_dynamic_target=resolve_dynamic_id,
                dynamic_map=dynamic_map,
                errors=closure_errors,
            )
            context = f"{scope.label}/{reach.module_name}"
            previous = first_analysis.get(current)
            if previous is None:
                first_analysis[current] = (stat_targets, dyn_targets, context)
                for target_id in stat_targets:
                    add_edge(current, target_id, "import", None)
                    static_adj.setdefault(current, []).append(target_id)
                for target_id, cond_ref in dyn_targets:
                    add_edge(current, target_id, "dynamic_import", cond_ref)
                    dynamic_adj.setdefault(current, []).append((target_id, cond_ref))
            elif (previous[0], previous[1]) != (stat_targets, dyn_targets):
                conflicts.append(f"{current}:{previous[2]}:{context}")
            for target_id in (*stat_targets, *(target for target, _cond in dyn_targets)):
                for module_name in dict.fromkeys(bound_names.get(target_id) or [scope.reach(target_id).module_name]):
                    enqueue(scope, _Reach(target_id, module_name))
        elif current in declared_by_id:
            dec_node = declared_by_id[current]
            prov = dec_node.provenance
            if type(prov) is t.GeneratedProvenance:
                for inp in prov.inputs:
                    inp_id = resolve_node(inp)
                    if inp_id is None:
                        closure_errors.append(f"generated:{current}:unknown_input:{inp}")
                    else:
                        add_edge(inp_id, current, "generated_input", None)
                        enqueue(scope, scope.reach(inp_id))
                for gen in prov.generators:
                    gen_id = resolve_node(gen)
                    if gen_id is None:
                        closure_errors.append(f"generated:{current}:unknown_generator:{gen}")
                    else:
                        add_edge(gen_id, current, "generates", None)
                        enqueue(scope, scope.reach(gen_id))
            elif type(prov) is t.CachedProvenance:
                for src in prov.source_nodes:
                    src_id = resolve_node(src)
                    if src_id is None:
                        closure_errors.append(f"cached_code:{current}:unknown_source:{src}")
                    else:
                        add_edge(current, src_id, "cache_of", None)
                        enqueue(scope, scope.reach(src_id))
            elif type(prov) is t.ArtifactProvenance:
                for src in (*prov.sources, *prov.dependencies):
                    src_id = resolve_node(src)
                    if src_id is None:
                        closure_errors.append(f"artifact:{current}:unknown_dependency:{src}")
                    else:
                        enqueue(scope, scope.reach(src_id))
                if prov.interpreter and prov.interpreter not in reached_nodes:
                    interp_id = resolve_node(prov.interpreter)
                    if interp_id is None:
                        closure_errors.append(f"artifact:{current}:unknown_interpreter:{prov.interpreter}")
                    else:
                        enqueue(scope, scope.reach(interp_id))

    for profile_scope in profile_scopes:
        closure_errors.extend(profile_scope.unsupported_entry_errors())
    if closure_errors:
        raise GraphBuildError("UNRESOLVED_CLOSURE", closure_errors)
    if conflicts:
        raise GraphBuildError("CONFLICTING_RESOLUTION", conflicts)

    for prof in process_profiles:
        parent_entries = [resolved_entry_nodes[eid] for eid in prof.entrypoint_ids]
        for child_prof_id in prof.child_profiles:
            child_prof = profiles_by_id[child_prof_id]
            for pe in parent_entries:
                for ce_id in child_prof.entrypoint_ids:
                    add_edge(pe, resolved_entry_nodes[ce_id], "spawns", None)

    nodes_out: list[t.SourceNode] = []
    for node_id in sorted(reached_nodes):
        if node_id in git_nodes:
            git_node = git_nodes[node_id]
            repository = git_node.repository
            git_entry = git_node.entry
            blob = read_blob(git_node)
            mode_lit: Literal["100644", "100755"] = "100755" if git_entry.mode == "100755" else "100644"
            membership_ref = t.EvidenceRef(
                "p3-evidence/1",
                byte_identity(f"membership:{repository.id}:{repository.commit}:{repository.tree}:{git_entry.path}:{mode_lit}:{git_entry.object_id}".encode()),
                supplier,
                f"membership-{node_id}",
            )
            git_prov = t.GitProvenance(
                tag="git",
                repository=repository.id,
                commit=repository.commit,
                tree=repository.tree,
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
                    logical_origin=f"git:{repository.id}:{git_entry.path}",
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

    repository_records = tuple(
        t.Repository(
            id=repository.id,
            owner=repository.owner,
            object_format=repository.object_format,
            commit=repository.commit,
            tree=repository.tree,
        )
        for repository in loaded.values()
    )
    edges_out = tuple(edge_map[k] for k in sorted(edge_map))
    graph = t.SourceGraph(
        schema="p3-reviewed-source-graph/1",
        graph_id=graph_id,
        repositories=repository_records,
        nodes=tuple(nodes_out),
        edges=edges_out,
        entrypoints=entrypoints_out,
        process_profiles=tuple(profiles_out),
        completeness_review_ref=None,
    )
    return validate_reviewed_graph(canonical_bytes(graph))
