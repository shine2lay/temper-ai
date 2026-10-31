"""Final Docker bind arguments checked against independent declarations.

This is a source/target/access check, not a container launcher, a private-root exclusion,
project ownership check or race-proof pin. Fixed declarations grant exactly one bind;
root rules grant only their caller's separately checked target/access variant. A template
is a trust input, not evidence that the template itself is safe.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


class MountRefused(ValueError):
    """Safe refusal: no argv, environment, paths or command payload in its message."""

    def __init__(self, category: str, *, site: str = "bind", targets: tuple[str, ...] = ()):
        self.category = category
        self.site = site
        self.targets = targets  # Only the historical Pi API uses these in its own message.
        super().__init__(f"container bind refused: site={site} category={category}")


@dataclass(frozen=True)
class Bind:
    source: str
    target: str
    read_only: bool = False


ResolvePath = Callable[[str], str]


def inside_roots(path: str | os.PathLike[str], roots: Sequence[str], *,
                 resolve: ResolvePath = os.path.realpath) -> bool:
    """Canonical containment in the namespace supplied by ``resolve``.

    The default is the local host namespace (also Pi's identity-mapped roots). A worker
    whose paths differ from Docker's must supply its host-path resolver, not local realpath.
    Neither form pins mutable links between this check and Docker's use.
    """
    if not path or not os.path.isabs(path):
        return False
    real = Path(resolve(os.fspath(path)))
    return any(real.is_relative_to(resolve(root)) for root in roots
               if root and os.path.isabs(root))


def check_bind_sources(mounts: Sequence[tuple[str, str, bool]], roots: Sequence[str]) -> None:
    """Pi's historical source-only check; empty roots deliberately retain compatibility."""
    if not roots:
        return
    outside = tuple(sorted(dst for src, dst, _ in mounts if not inside_roots(src, roots)))
    if outside:
        raise MountRefused("source_outside_roots", targets=outside)


@dataclass(frozen=True)
class RootBind:
    """Roots come from config; accepts checks the caller's existing target/access rules."""

    roots: tuple[str, ...]
    accepts: Callable[[Bind], bool]
    resolve: ResolvePath = os.path.realpath

    def permits(self, bind: Bind) -> bool:
        return inside_roots(bind.source, self.roots, resolve=self.resolve) and self.accepts(bind)


@dataclass(frozen=True)
class MountPolicy:
    fixed: tuple[Bind, ...] = ()
    rooted: tuple[RootBind, ...] = ()
    # None means fixed declarations alone. Pi supplies roots, or None for compatibility.
    source_roots: tuple[str, ...] | None = None
    resolve: ResolvePath = os.path.realpath


# Only options used by these launchers, plus their unambiguous short forms. Unknown options
# fail closed: guessing whether one consumes a value can mistake that value for the image.
_VALUE_OPTIONS = frozenset({
    "--name", "--hostname", "--label", "--security-opt", "--cap-drop", "--network",
    "--add-host", "--env", "--user", "--workdir", "--entrypoint", "--memory", "--cpus",
    "--pids-limit", "--pull", "--log-driver", "--dns", "--dns-search", "--tmpfs",
    "-e", "-h", "-l", "-u", "-w",
})
_BOOL_OPTIONS = frozenset({
    "--detach", "--rm", "--init", "--no-healthcheck", "--interactive", "--read-only",
    "--tty", "-d", "-i", "-t",
})
_INDIRECT_OPTIONS = frozenset({
    "--volumes-from", "--volume-driver", "--device", "--device-cgroup-rule", "--gpus",
    "--privileged", "--storage-opt",
})
_ALIASES = {"src": "source", "dst": "target", "destination": "target", "ro": "readonly"}


def _path(value: str) -> str:
    if (not value or not os.path.isabs(value) or value.startswith("//")
            or any(c in value for c in "\x00\n\r")
            or os.path.normpath(value) != value):
        raise MountRefused("malformed_mount")
    return value


def _mount(value: str) -> tuple[str, Bind | None]:
    # Current serializers produce plain CSV fields, never quoted fields. Do not guess at
    # Docker's more permissive CSV/driver extensions or accept an unreadable declaration.
    if any(c in value for c in '\x00\n\r"'):
        raise MountRefused("malformed_mount")
    fields: dict[str, str | None] = {}
    for part in value.split(","):
        key, sep, val = part.partition("=")
        key = _ALIASES.get(key, key)
        if not key or key in fields:
            raise MountRefused("malformed_mount")
        fields[key] = val if sep else None
    kind = fields.get("type")
    target = _path(fields.get("target") or "")
    if kind == "bind":
        if set(fields) - {"type", "source", "target", "readonly", "bind-propagation"}:
            raise MountRefused("unsupported_mount")
        if fields.get("bind-propagation", "rprivate") != "rprivate":
            raise MountRefused("permission_widening")
        ro = fields.get("readonly")
        if ro not in (None, "true", "false", "1", "0"):
            raise MountRefused("malformed_mount")
        return target, Bind(_path(fields.get("source") or ""), target,
                            "readonly" in fields and ro not in ("false", "0"))
    if kind == "tmpfs":
        if set(fields) - {"type", "target", "tmpfs-size", "tmpfs-mode"}:
            raise MountRefused("unsupported_mount")
        options = [f"{key[6:]}={val or ''}" for key, val in fields.items()
                   if key.startswith("tmpfs-")]
        _tmpfs(target + (":" + ",".join(options) if options else ""))
        return target, None
    if kind == "volume":
        # Only anonymous volumes. Named volumes/drivers can conceal a host bind.
        if set(fields) != {"type", "target"}:
            raise MountRefused("indirect_host_mount")
        return target, None
    raise MountRefused("unsupported_mount")


def _volume(value: str) -> tuple[str, Bind | None]:
    parts = value.split(":")
    if len(parts) == 1:
        return _path(parts[0]), None  # anonymous volume, not a host source
    if len(parts) not in (2, 3):
        raise MountRefused("malformed_mount")
    source, target = parts[:2]
    if not os.path.isabs(source):
        raise MountRefused("indirect_host_mount")
    mode = parts[2] if len(parts) == 3 else "rw"
    modes = mode.split(",")
    if len(modes) != len(set(modes)) or set(modes) - {"ro", "rw", "rprivate"}:
        raise MountRefused("unsupported_mount")
    if "ro" in modes and "rw" in modes:
        raise MountRefused("malformed_mount")
    return _path(target), Bind(_path(source), target, "ro" in modes)


def _tmpfs(value: str) -> str:
    target, sep, options = value.partition(":")
    _path(target)
    seen: set[str] = set()
    for part in options.split(",") if sep else ():
        key, equals, val = part.partition("=")
        if not key or key in seen:
            raise MountRefused("malformed_mount")
        seen.add(key)
        if key in {"rw", "ro", "exec", "noexec", "nosuid", "nodev"} and not equals:
            continue
        if key in {"uid", "gid"} and equals and re.fullmatch(r"[0-9]+", val):
            continue
        if key == "mode" and equals and re.fullmatch(r"[0-7]{3,4}", val):
            continue
        if key == "size" and equals and re.fullmatch(r"[0-9]+(?:[kKmMgGtT](?:[iI]?[bB])?|[bB])?", val):
            continue
        raise MountRefused("unsupported_mount")
    if {"rw", "ro"} <= seen or {"exec", "noexec"} <= seen:
        raise MountRefused("malformed_mount")
    return target


def launch_binds(argv: Sequence[str]) -> tuple[Bind, ...]:
    """Read Docker options only: image ends parsing, its command is never inspected.

    Called on the fully assembled run/create argv, including the executable. An explicit
    -- ends Docker options too. Option values are consumed even when they look like flags.
    """
    if len(argv) < 3 or not isinstance(argv[1], str) or argv[1] not in {"run", "create"}:
        raise MountRefused("not_a_container_launch")
    binds: list[Bind] = []
    targets: list[str] = []
    i = 2
    while i < len(argv):
        arg = argv[i]
        if not isinstance(arg, str) or not arg or "\x00" in arg:
            raise MountRefused("unreadable_arguments")
        if arg == "--":
            i += 1
            break
        if not arg.startswith("-"):
            break
        option, equals, value = arg.partition("=")
        if arg.startswith("-v") and not arg.startswith("--"):
            option, value = "-v", arg[2:].removeprefix("=")
            equals = "=" if value else ""
        if option in _INDIRECT_OPTIONS:
            raise MountRefused("indirect_host_mount")
        if option in _BOOL_OPTIONS:
            if equals and value not in {"true", "false", "1", "0"}:
                raise MountRefused("unreadable_arguments")
        elif option in _VALUE_OPTIONS or option in {"--mount", "--volume", "-v"}:
            if not equals:
                i += 1
                if i >= len(argv):
                    raise MountRefused("unreadable_arguments")
                value = argv[i]
            if not isinstance(value, str) or not value or "\x00" in value:
                raise MountRefused("unreadable_arguments")
            if option in {"--mount", "--volume", "-v"}:
                target, bind = _mount(value) if option == "--mount" else _volume(value)
                targets.append(target)
                if bind is not None:
                    binds.append(bind)
            elif option == "--tmpfs":
                targets.append(_tmpfs(value))
        elif not equals and arg.startswith("-") and not arg.startswith("--") \
                and set(arg[1:]) <= {"i", "t", "d"}:
            pass
        else:
            raise MountRefused("unreadable_arguments")
        i += 1
    if i >= len(argv) or not isinstance(argv[i], str) or not argv[i] or argv[i].startswith("-"):
        raise MountRefused("missing_image")
    if "\x00" in argv[i]:
        raise MountRefused("unreadable_arguments")
    if len(set(targets)) != len(targets):
        raise MountRefused("ambiguous_mounts")
    return tuple(binds)


def check_launch(argv: Sequence[str], policy: MountPolicy, *, site: str) -> None:
    """Reject final bind additions/widening without deriving permission from those binds."""
    try:
        binds = launch_binds(argv)
        fixed = set(policy.fixed)
        if policy.source_roots is not None and any(
            not inside_roots(b.source, policy.source_roots, resolve=policy.resolve) for b in binds
        ):
            raise MountRefused("source_outside_roots")
        for bind in binds:
            if bind in fixed:
                continue
            permitted = False
            for rule in policy.rooted:
                if not rule.permits(bind):
                    continue
                # Root membership never expands a fixed read-only source's target or
                # access. Keep this independent of each caller's dynamic validation.
                if any(b.read_only and (
                    Path(bind.target).is_relative_to(b.target)
                    or inside_roots(bind.source, (b.source,), resolve=rule.resolve)
                ) for b in fixed):
                    raise MountRefused("permission_widening")
                permitted = True
                break
            if not permitted:
                raise MountRefused("undeclared_bind")
        if not fixed.issubset(binds):
            raise MountRefused("missing_declared_bind")
    except MountRefused as exc:
        raise MountRefused(exc.category, site=site) from None
    except (OSError, ValueError, RuntimeError):
        raise MountRefused("unreadable_host_path", site=site) from None
