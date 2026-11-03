"""P3 T5-N4: worker-box and root observation from caller-supplied snapshots.

``BoxObservationProvider`` is a concrete ``WorkerObservationProviderPort``. Put it in
``WorkerObservationAdapter(provider=...)`` and that adapter (the ``WorkerObserver``)
and its ``root_observer`` (the ``RootObserver``) check a real worker box instead of a
test double. It checks:

- the worker container against its sealed box profile: the profile the box was
  started with (``box_view.profile_from_env`` over the inspected environment) is the
  sealed one, by digest; the container runs the profile's image, user, HOME and
  PATH on a read-only root, on a network the profile names; the launcher's
  hardening holds (no-new-privileges, every capability dropped and none added, no
  confinement switched off, no devices or extra groups, its own cgroup namespace);
  each grant is bind-mounted from its source with its write access and private
  propagation, the tmpfs mounts are the profile's, and nothing else is mounted;
  nothing the run loads is outside the classified launch (``box_guard.Guard.check``);
- the worker process against the container and the host: same container id,
  user and namespaces as observed, and none of its pid/mount/user namespaces or
  Docker pid/ipc/user/uts/network modes shared with the host or another container
  (a collapsed runtime);
- both roots, publication and host_evidence, by (dev, ino, generation) and path
  against the pins its grant fixed, each mounted where the sealed profile grants it
  from the root's host path with the same (dev, ino) pin, neither inside the other,
  the actor never the file owner, and no write right through a read-only mount;
- the write fence (``DeterministicEffectFenceProvider``) open and current.

These are facts of the snapshots the caller supplies, checked against the sealed
profile; they attest nothing the snapshots don't show. Inside the box, the same
profile is enforced by ``box_view.check_box`` at start and by the launcher's flags.

``box_view.view_problems``/``check_box`` examine the process that calls them
(``os.getuid``, ``/proc/self``, ``os.stat``), so they can only run inside the box.
From outside, this module reuses ``box_view.profile_from_env``/``digest_of`` and
``box_guard.Guard.check`` and checks the same profile facts against the inspect
snapshot instead.

Inputs are plain snapshots the caller took (``docker inspect`` JSON, ``stat`` of each
root, the N3 worker frame). This module makes no Docker, host, database or model
call, and nothing constructs it by default. It never changes ``WRITES_ADMITTED``.

Refusals: missing/unpermitted grant, checked before any snapshot is read ->
OBSERVATION_NOT_AUTHORIZED; collapsed runtime, UID/GID/namespace/mount/profile drift
-> RUNTIME_CHANGED; a missing half-root, (dev, ino, generation) or path mismatch ->
ROOT_MISMATCH; a missing read/traverse/write right or actor-is-owner ->
RIGHTS_MISSING; closed fence -> WRITES_DISABLED; stale frontier after a wait ->
RUNTIME_CHANGED.
"""

from __future__ import annotations

import posixpath
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from p3_source_closure import N3ObservationEpoch
from temper_ai.p3_authority.boundary_types import CurrentObservationCursors
from temper_ai.p3_authority.child_registration import ChildRegistrationTicket
from temper_ai.p3_authority.contract import (
    AcceptedData,
    BothRootObservations,
    Boundary,
    DecisionEvidence,
    EffectSet,
    NativeGrantRef,
    NativeInterval,
    NativeProcessRef,
    NativeRootObject,
    NativeWitness,
    ObservationGrant,
    ProcessInstance,
    Refusal,
    RefusalCode,
    Result,
    RetryKind,
    RootBinding,
    RootObservation,
    RootScope,
    SelectedJob,
)
from temper_ai.p3_authority.coverage_bookkeeping import make_refusal
from temper_ai.p3_authority.effect_fence import (
    DeterministicEffectFenceProvider,
    decision_evidence_for,
)
from temper_ai.p3_authority.worker_observation import (
    RootOwnerVsActorAssertion,
    SuppliedWorkerFrame,
    WorkerObservationProviderPort,
    actor_owns_root,
)
from temper_ai.spawner import box_guard, box_view

RootKind = Literal["publication", "host_evidence"]
ROOT_KINDS: tuple[RootKind, ...] = ("publication", "host_evidence")
ROOT_RIGHTS: frozenset[str] = frozenset({"observe", "read", "traverse", "write"})
_BINDING_ROLE: dict[RootKind, Literal["publication", "host-evidence"]] = {
    "publication": "publication",
    "host_evidence": "host-evidence",
}
# The only environment variables a snapshot keeps: the box's own profile, HOME, PATH.
# Everything else in Config.Env (keys, tokens) is never kept or printed.
KEPT_ENVIRONMENT: tuple[str, ...] = (
    box_view.PROFILE_ENV,
    box_view.DIGEST_ENV,
    box_view.GENERATION_ENV,
    "HOME",
    "PATH",
)
# SecurityOpt entries that switch a kernel confinement off.
_UNCONFINED_OPTIONS = frozenset(
    {
        ("seccomp", "unconfined"),
        ("apparmor", "unconfined"),
        ("label", "disable"),
        ("systempaths", "unconfined"),
    }
)
# Mount propagation that sends no mount events between the box and the host.
_PRIVATE_PROPAGATION = ("", "rprivate")


def _inspect_field(where: str, key: str) -> str:
    return f"{where}.{key}" if where else key


def _need(section: Any, key: str, where: str) -> Any:
    if not isinstance(section, Mapping):
        raise ValueError(f"docker inspect {where or 'top level'} is not an object")
    if key not in section:
        raise ValueError(f"docker inspect has no {_inspect_field(where, key)}")
    return section[key]


def _need_str(section: Any, key: str, where: str) -> str:
    value = _need(section, key, where)
    if not isinstance(value, str):
        raise ValueError(f"docker inspect {_inspect_field(where, key)} is not a string")
    return value


def _need_bool(section: Any, key: str, where: str) -> bool:
    value = _need(section, key, where)
    if not isinstance(value, bool):
        raise ValueError(
            f"docker inspect {_inspect_field(where, key)} is not true or false"
        )
    return value


def _need_int(section: Any, key: str, where: str) -> int:
    value = _need(section, key, where)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"docker inspect {_inspect_field(where, key)} is not a number")
    return value


def _need_list(section: Any, key: str, where: str) -> list[Any]:
    """A list Docker may also show as null (= empty)."""
    value = _need(section, key, where)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"docker inspect {_inspect_field(where, key)} is not a list")
    return value


def _need_str_list(section: Any, key: str, where: str) -> tuple[str, ...]:
    value = _need_list(section, key, where)
    if not all(isinstance(item, str) for item in value):
        raise ValueError(
            f"docker inspect {_inspect_field(where, key)} is not a list of strings"
        )
    return tuple(value)


def _optional_str_map(section: Any, key: str, where: str) -> dict[str, str]:
    """A map Docker leaves out or shows as null when empty (HostConfig.Tmpfs)."""
    value = section.get(key) if isinstance(section, Mapping) else None
    if value is None:
        return {}
    if not isinstance(value, Mapping) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise ValueError(
            f"docker inspect {_inspect_field(where, key)} is not a map of strings"
        )
    return dict(value)


def _kept_environment(config: Any) -> dict[str, str]:
    """Config.Env, keeping only KEPT_ENVIRONMENT. Errors name the entry's index, never its text."""
    kept: dict[str, str] = {}
    seen: set[str] = set()
    for index, entry in enumerate(_need_list(config, "Env", "Config")):
        if not isinstance(entry, str) or "=" not in entry:
            raise ValueError(f"docker inspect Config.Env[{index}] is not NAME=value")
        name, _, value = entry.partition("=")
        if name in seen:
            raise ValueError(
                f"docker inspect Config.Env[{index}] sets a variable again"
            )
        seen.add(name)
        if name in KEPT_ENVIRONMENT:
            kept[name] = value
    return kept


def _shares_namespace(mode: str) -> bool:
    """A Docker namespace mode that joins the host's or another container's namespace."""
    return mode == "host" or mode.startswith("container:")


def _option_name_value(option: str) -> tuple[str, str]:
    """``seccomp=unconfined`` (or the older ``seccomp:unconfined``) -> (name, value)."""
    for separator in ("=", ":"):
        name, found, value = option.partition(separator)
        if found:
            return name, value
    return option, ""


def _normal_absolute(path: str) -> bool:
    return posixpath.isabs(path) and posixpath.normpath(path) == path


def _same_path(a: str, b: str) -> bool:
    """Both absolute, both already normal, and equal (pure; no host lookup)."""
    return _normal_absolute(a) and _normal_absolute(b) and a == b


def _nested(a: str, b: str) -> bool:
    """One path is the other or lies inside it."""
    return (
        a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")
    )


def _tmpfs_entry(entry: str) -> tuple[str, str]:
    """A profile tmpfs line ``target:options`` -> (target, options)."""
    target, _, options = entry.partition(":")
    return target, options


@dataclass(frozen=True, slots=True, kw_only=True)
class BoxMount:
    """One mount as ``docker inspect`` lists it (``Mounts[]``)."""

    target: str
    source: str
    read_only: bool
    kind: str
    propagation: str


@dataclass(frozen=True, slots=True, kw_only=True)
class BoxInspectSnapshot:
    """The worker container as the caller read it: ``docker inspect`` plus /proc ns links.

    ``pid_namespace_id``/``mount_namespace_id``/``user_namespace_id`` are the worker's
    namespaces as the caller read them (``/proc/<pid>/ns/*``); ``launch_requests`` are
    the (kind, name) pairs this run will load, checked against the classified launch.
    ``environ`` keeps only KEPT_ENVIRONMENT and is left out of repr.
    """

    container_id: str
    image_id: str
    running: bool
    host_pid: int
    user: str
    environ: Mapping[str, str] = field(repr=False)
    readonly_rootfs: bool
    privileged: bool
    cap_add: tuple[str, ...]
    cap_drop: tuple[str, ...]
    security_opt: tuple[str, ...]
    device_count: int
    device_cgroup_rules: tuple[str, ...]
    group_add: tuple[str, ...]
    pid_mode: str
    ipc_mode: str
    userns_mode: str
    uts_mode: str
    cgroupns_mode: str
    network_mode: str
    tmpfs: Mapping[str, str]
    mounts: tuple[BoxMount, ...]
    pid_namespace_id: str
    mount_namespace_id: str
    user_namespace_id: str
    launch_requests: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not set(self.environ) <= set(KEPT_ENVIRONMENT):
            raise ValueError(
                "environ keeps only the box profile variables, HOME and PATH"
            )

    @classmethod
    def from_inspect(
        cls,
        inspect: Mapping[str, Any],
        *,
        pid_namespace_id: str,
        mount_namespace_id: str,
        user_namespace_id: str,
        launch_requests: tuple[tuple[str, str], ...],
    ) -> BoxInspectSnapshot:
        """Parse one ``docker inspect`` object. Raises ValueError naming the bad field."""
        state = _need(inspect, "State", "")
        config = _need(inspect, "Config", "")
        host = _need(inspect, "HostConfig", "")
        mounts: list[BoxMount] = []
        for index, entry in enumerate(_need_list(inspect, "Mounts", "")):
            where = f"Mounts[{index}]"
            mount = BoxMount(
                target=_need_str(entry, "Destination", where),
                source=_need_str(entry, "Source", where),
                read_only=not _need_bool(entry, "RW", where),
                kind=_need_str(entry, "Type", where),
                propagation=_need_str(entry, "Propagation", where),
            )
            if any(m.target == mount.target for m in mounts):
                raise ValueError(f"docker inspect {where}.Destination is mounted twice")
            mounts.append(mount)
        return cls(
            container_id=_need_str(inspect, "Id", ""),
            image_id=_need_str(inspect, "Image", ""),
            running=_need_bool(state, "Running", "State"),
            host_pid=_need_int(state, "Pid", "State"),
            user=_need_str(config, "User", "Config"),
            environ=_kept_environment(config),
            readonly_rootfs=_need_bool(host, "ReadonlyRootfs", "HostConfig"),
            privileged=_need_bool(host, "Privileged", "HostConfig"),
            cap_add=_need_str_list(host, "CapAdd", "HostConfig"),
            cap_drop=_need_str_list(host, "CapDrop", "HostConfig"),
            security_opt=_need_str_list(host, "SecurityOpt", "HostConfig"),
            device_count=len(_need_list(host, "Devices", "HostConfig")),
            device_cgroup_rules=_need_str_list(host, "DeviceCgroupRules", "HostConfig"),
            group_add=_need_str_list(host, "GroupAdd", "HostConfig"),
            pid_mode=_need_str(host, "PidMode", "HostConfig"),
            ipc_mode=_need_str(host, "IpcMode", "HostConfig"),
            userns_mode=_need_str(host, "UsernsMode", "HostConfig"),
            uts_mode=_need_str(host, "UTSMode", "HostConfig"),
            cgroupns_mode=_need_str(host, "CgroupnsMode", "HostConfig"),
            network_mode=_need_str(host, "NetworkMode", "HostConfig"),
            tmpfs=_optional_str_map(host, "Tmpfs", "HostConfig"),
            mounts=tuple(mounts),
            pid_namespace_id=pid_namespace_id,
            mount_namespace_id=mount_namespace_id,
            user_namespace_id=user_namespace_id,
            launch_requests=launch_requests,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RootPin:
    """The root object the grant fixed: what every later stat of it must still be."""

    root_kind: RootKind
    host_path: str
    actor_path: str
    dev: int
    ino: int
    generation: int
    required_rights: frozenset[str]
    grant_refs: tuple[NativeGrantRef, ...]
    validity: NativeInterval

    def __post_init__(self) -> None:
        if self.root_kind not in ROOT_KINDS:
            raise ValueError("a root pin is publication or host_evidence")
        if not (_normal_absolute(self.host_path) and _normal_absolute(self.actor_path)):
            raise ValueError("a root pin's paths must be absolute and normal")
        if not self.required_rights <= ROOT_RIGHTS:
            raise ValueError(
                "a root pin may require only observe, read, traverse and write"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class RootStatSnapshot:
    """One caller-taken ``stat`` of a root, with its owner and the actor's rights on it."""

    root_kind: RootKind
    host_path: str
    actor_path: str
    dev: int
    ino: int
    generation: int
    owner_uid: int
    owner_principal: str
    actor_uid: int
    actor_principal: str
    granted_rights: frozenset[str]
    root_object: NativeRootObject
    mount_witness: NativeWitness
    provenance: tuple[NativeWitness, ...]


def missing_root_halves(
    pins: Mapping[RootKind, RootPin],
    stats: Mapping[RootKind, RootStatSnapshot],
) -> tuple[RootKind, ...]:
    """The root kinds without both a pin and a stat (publication alone is not both)."""
    return tuple(kind for kind in ROOT_KINDS if kind not in pins or kind not in stats)


def owner_vs_actor(
    stat: RootStatSnapshot, actor: NativeProcessRef
) -> RootOwnerVsActorAssertion:
    """The owner-vs-actor facts one root stat carries."""
    return RootOwnerVsActorAssertion(
        root_kind=stat.root_kind,
        actor_process_ref=actor.process_registration,
        actor_principal=stat.actor_principal,
        actor_uid=stat.actor_uid,
        file_owner_principal=stat.owner_principal,
        file_owner_uid=stat.owner_uid,
    )


def _uid_gid(user: str) -> tuple[int, int] | None:
    """``"1001:1001"`` -> (1001, 1001); a name, a missing half or garbage -> None."""
    uid, sep, gid = str(user).partition(":")
    if not sep or not uid.isdigit() or not gid.isdigit():
        return None
    return int(uid), int(gid)


class BoxObservationProvider(WorkerObservationProviderPort):
    """Snapshot-driven worker box and both-root observation (inert unless constructed).

    Constructor inputs (all supplied by the caller, none fetched here):
      selected_job: the one job this provider observes;
      sealed_profile: the box profile document ``box_profile.compile_profile`` sealed;
      inspect: the worker container (``BoxInspectSnapshot.from_inspect``);
      worker_frame: the N3 worker frame (processes, load facts, streams);
      actor: the worker's process ref the grant names;
      permitted_observation: the observation permission the service issued;
      root_pins / root_stats: per root kind, the pin and the current stat;
      effect_fence / fence_frontier: the write fence and the frontier it is bound to.
    """

    def __init__(
        self,
        *,
        selected_job: SelectedJob,
        sealed_profile: Mapping[str, Any],
        inspect: BoxInspectSnapshot,
        worker_frame: SuppliedWorkerFrame,
        actor: NativeProcessRef,
        permitted_observation: str,
        root_pins: Mapping[RootKind, RootPin],
        root_stats: Mapping[RootKind, RootStatSnapshot],
        effect_fence: DeterministicEffectFenceProvider | None = None,
        fence_frontier: CurrentObservationCursors | None = None,
    ) -> None:
        if not permitted_observation:
            raise ValueError("permitted_observation must name the issued permission")
        self._job = selected_job
        self._profile = dict(sealed_profile)
        self._inspect = inspect
        self._frame = worker_frame
        self._actor = actor
        self._permitted_observation = permitted_observation
        self._root_pins = dict(root_pins)
        self._root_stats = dict(root_stats)
        self._effect_fence = effect_fence
        self._fence_frontier = fence_frontier
        self.snapshot_reads = 0

    # -- the grant, before anything is read --------------------------------------------

    def _grant_refusal(
        self,
        grant: ObservationGrant | None,
        selected_job: SelectedJob,
        boundary: Boundary,
    ) -> Refusal | None:
        if grant is None or not grant.permission.observation_permission:
            return make_refusal(RefusalCode.OBSERVATION_NOT_AUTHORIZED, boundary)
        # The whole selected job must be the one this provider observes.
        if selected_job != self._job:
            code = (
                RefusalCode.SELECTION_CHANGED
                if selected_job.selection_revision != self._job.selection_revision
                else RefusalCode.DISPATCH_CHANGED
            )
            return make_refusal(
                code, boundary, retry_kind=RetryKind.NEW_BINDING_REQUIRED
            )
        if grant.permission.observation_permission != self._permitted_observation:
            return make_refusal(RefusalCode.OBSERVATION_NOT_AUTHORIZED, boundary)
        job = self._job
        authority = grant.authority
        if authority.issuer_identity != job.selector_issuer.issuer_id:
            return make_refusal(RefusalCode.OBSERVATION_NOT_AUTHORIZED, boundary)
        if authority.subject.selection_revision != job.selection_revision:
            return make_refusal(
                RefusalCode.SELECTION_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if authority.subject.job != job.pre_dispatch_or_running_job:
            return make_refusal(
                RefusalCode.DISPATCH_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if self._actor not in authority.actors:
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        return None

    def verify_grant(
        self,
        grant: ObservationGrant,
        selected_job: SelectedJob,
        boundary: Boundary,
    ) -> Result[DecisionEvidence]:
        refused = self._grant_refusal(grant, selected_job, boundary)
        if refused is not None:
            return refused
        evidence = decision_evidence_for(
            selected_job=self._job, actor=self._actor, boundary=boundary
        )
        return AcceptedData(data=evidence, evidence=evidence)

    # -- the write fence ------------------------------------------------------------------

    def _fence_refusal(
        self, selected_job: SelectedJob, boundary: Boundary
    ) -> Refusal | None:
        if self._effect_fence is None or self._fence_frontier is None:
            return make_refusal(
                RefusalCode.WRITES_DISABLED,
                boundary,
                retry_kind=RetryKind.NOT_APPLICABLE,
            )
        return self._effect_fence.refusal_if_closed_or_stale(
            selected_job=selected_job,
            actor=self._actor,
            frontier=self._fence_frontier,
            boundary=boundary,
        )

    # -- the worker box -------------------------------------------------------------------

    def _box_problems(self) -> list[str]:
        """What about the inspected box differs from its sealed profile ([] = nothing)."""
        doc = self._profile
        box = self._inspect
        problems: list[str] = []
        image_id = (doc.get("image") or {}).get("id")
        if not image_id or box.image_id != image_id:
            problems.append("the box runs another image than the profile's")
        if doc.get("boundary") != box_view.SEALED:
            problems.append("the profile is not a sealed box profile")
        try:
            started_with = box_view.profile_from_env(box.environ)
        except box_view.BoxStartRefused as exc:
            started_with = None
            problems.append(f"the box's own profile is refused: {exc}")
        if started_with is None or box_view.digest_of(
            started_with
        ) != box_view.digest_of(doc):
            problems.append("the box was not started with the sealed profile")
        runtime = doc.get("runtime") or {}
        want_user = _uid_gid(str(runtime.get("user") or ""))
        if want_user is None or _uid_gid(box.user) != want_user:
            problems.append(f"the box runs as {box.user!r}, not the profile's user")
        if want_user is not None and 0 in want_user:
            problems.append("the profile's user is root")
        if not box.readonly_rootfs or doc.get("rootfs") != "read-only":
            problems.append(
                "the root filesystem is writable; a sealed box's is read-only"
            )
        if box.environ.get("HOME") != runtime.get("home"):
            problems.append("HOME is not the one the profile fixed")
        if (box.environ.get("PATH") or "").split(":") != list(
            runtime.get("path") or []
        ):
            problems.append("PATH is not the one the profile fixed")
        if box.network_mode not in self._profile_networks() | {"none"}:
            problems.append("the box is on a network its profile does not name")
        problems += self._hardening_problems()
        problems += self._mount_problems()
        problems += self._launch_problems()
        return sorted(set(problems))

    def _profile_networks(self) -> set[str]:
        return {
            str(network)
            for entry in self._profile.get("network_graph") or []
            for network in ((entry.get("identity") or {}).get("network") or [])
        }

    def _hardening_problems(self) -> list[str]:
        """The launcher's own flags: no-new-privileges, every capability dropped, no devices."""
        box = self._inspect
        options = [_option_name_value(option) for option in box.security_opt]
        problems: list[str] = []
        no_new_privileges = [
            value for name, value in options if name == "no-new-privileges"
        ]
        if not no_new_privileges or no_new_privileges[-1] not in ("", "true"):
            problems.append("the box may gain privileges (no no-new-privileges)")
        if any(option in _UNCONFINED_OPTIONS for option in options):
            problems.append("the box switches a kernel confinement off")
        if "ALL" not in {cap.upper() for cap in box.cap_drop}:
            problems.append(
                "the box keeps Docker's default capabilities (no cap-drop ALL)"
            )
        if box.privileged or box.cap_add:
            problems.append("the box is privileged or adds capabilities")
        if box.device_count or box.device_cgroup_rules:
            problems.append("the box is given host devices")
        if box.group_add:
            problems.append("the box adds supplementary groups")
        if box.cgroupns_mode != "private":
            problems.append("the box has no cgroup namespace of its own")
        return problems

    def _mount_problems(self) -> list[str]:
        """Each grant bind-mounted from its source with its write access; tmpfs as profiled."""
        box = self._inspect
        grants = {str(g["target"]): g for g in self._profile.get("grants") or []}
        problems: list[str] = []
        want_tmpfs = dict(
            _tmpfs_entry(str(t)) for t in self._profile.get("tmpfs") or []
        )
        if dict(box.tmpfs) != want_tmpfs:
            problems.append("the box's tmpfs mounts are not the profile's")
        by_target = {m.target: m for m in box.mounts}
        for target, grant in grants.items():
            mount = by_target.get(target)
            if mount is None:
                problems.append(f"{target} is granted but not mounted")
                continue
            if mount.kind != "bind":
                problems.append(f"{target} is not a bind mount of its grant")
            if not _same_path(mount.source, str(grant.get("source") or "")):
                problems.append(
                    f"{target} is mounted from another source than its grant"
                )
            if mount.read_only != bool(grant.get("read_only")):
                problems.append(
                    f"{target} is mounted with other write access than its grant"
                )
            if mount.propagation not in _PRIVATE_PROPAGATION:
                problems.append(f"{target} shares mount events with the host")
        for target in by_target:
            if target not in grants:
                problems.append(
                    f"{target} is mounted but the profile grants nothing there"
                )
        return problems

    def _launch_problems(self) -> list[str]:
        launch = self._profile.get("launch") or {}
        allowed = launch.get("allowed") or {}
        guard = box_guard.Guard(
            workflow=str(launch.get("workflow")),
            files={},
            configs={},
            allowed={kind: frozenset(names or ()) for kind, names in allowed.items()},
        )
        problems: list[str] = []
        for kind, name in self._inspect.launch_requests:
            try:
                if kind not in guard.allowed:
                    raise box_guard.LaunchRefused(f"{kind} is not a launch class")
                guard.check(kind, name)
            except box_guard.LaunchRefused as exc:
                problems.append(str(exc))
        return problems

    def _runtime_refusal(self, boundary: Boundary) -> Refusal | None:
        """Collapsed host/worker runtime or any drift from container/profile -> refusal."""
        frame = self._frame
        box = self._inspect
        host: ProcessInstance = frame.host_instance
        worker: ProcessInstance = frame.worker_instance
        closure = frame.worker_closure_instance
        container = worker.container_instance
        want_user = _uid_gid(box.user)
        collapsed = (
            container is None
            or not box.running
            or box.host_pid < 1
            or any(
                _shares_namespace(mode)
                for mode in (
                    box.pid_mode,
                    box.ipc_mode,
                    box.userns_mode,
                    box.uts_mode,
                    box.network_mode,
                )
            )
            or worker.pid_namespace_id == host.pid_namespace_id
            or worker.mount_namespace_id == host.mount_namespace_id
            or worker.user_namespace_id == host.user_namespace_id
        )
        drifted = (
            container is None
            or container.full_container_id != box.container_id
            or box.pid_namespace_id != worker.pid_namespace_id
            or box.mount_namespace_id != worker.mount_namespace_id
            or box.user_namespace_id != worker.user_namespace_id
            or want_user is None
            or (closure.uid, closure.gid) != want_user
            or closure.container_identity != box.container_id
            or bool(self._box_problems())
        )
        if collapsed or drifted:
            return make_refusal(
                RefusalCode.RUNTIME_CHANGED,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        return None

    # -- the two roots --------------------------------------------------------------------

    def _profile_grant(self, actor_path: str) -> Mapping[str, Any] | None:
        """The sealed profile's grant mounted at ``actor_path`` (None: nothing granted there)."""
        for grant in self._profile.get("grants") or []:
            if grant.get("target") == actor_path:
                return grant
        return None

    def _observe_one_root(
        self,
        root_kind: RootKind,
        boundary: Boundary,
        *,
        required_rights: frozenset[str] = frozenset(),
    ) -> Result[RootObservation]:
        """Check one present root's stat against its pin and build its observation.

        No grant or runtime check here: its callers make both first, and check the
        root is there.
        """
        pin = self._root_pins[root_kind]
        stat = self._root_stats[root_kind]
        if pin.root_kind != root_kind or stat.root_kind != root_kind:
            return make_refusal(RefusalCode.ROOT_MISMATCH, boundary)
        if not (
            _same_path(stat.host_path, pin.host_path)
            and _same_path(stat.actor_path, pin.actor_path)
        ):
            return make_refusal(
                RefusalCode.ROOT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        if (stat.dev, stat.ino, stat.generation) != (pin.dev, pin.ino, pin.generation):
            return make_refusal(
                RefusalCode.ROOT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        mount_grant = self._profile_grant(pin.actor_path)
        profile_pin = (mount_grant or {}).get("pin") or {}
        if (
            mount_grant is None
            or (profile_pin.get("dev"), profile_pin.get("ino")) != (pin.dev, pin.ino)
            or not _same_path(str(mount_grant.get("source") or ""), pin.host_path)
        ):
            return make_refusal(
                RefusalCode.ROOT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        closure = self._frame.worker_closure_instance
        if (
            stat.actor_uid != closure.uid
            or stat.actor_principal != closure.principal
            or actor_owns_root(owner_vs_actor(stat, self._actor))
        ):
            return make_refusal(RefusalCode.RIGHTS_MISSING, boundary)
        # A read-only mount takes away whatever write right the stat says the actor has.
        usable = stat.granted_rights - (
            frozenset({"write"}) if mount_grant.get("read_only") else frozenset()
        )
        needed = pin.required_rights | required_rights
        if not stat.granted_rights <= ROOT_RIGHTS or not needed <= usable:
            return make_refusal(RefusalCode.RIGHTS_MISSING, boundary)
        if not stat.provenance:
            return make_refusal(RefusalCode.ROOT_MISMATCH, boundary)
        binding = RootBinding(
            role=_BINDING_ROLE[root_kind],
            object_identity=stat.root_object,
            actor_instance=self._actor,
            namespace_and_mount_identity=stat.mount_witness,
            actor_visible_path=stat.actor_path,
            host_visible_path=stat.host_path,
            rights=usable,
            grant_refs=pin.grant_refs,
            validity=pin.validity,
            mapping_witness=stat.mount_witness,
        )
        observation = RootObservation(
            root_kind=root_kind,
            binding=binding,
            traversal_chain=(stat.root_object,),
            observed_access=usable,
            observation_boundary=boundary,
            provenance=stat.provenance,
        )
        evidence = decision_evidence_for(
            selected_job=self._job, actor=self._actor, boundary=boundary
        )
        return AcceptedData(data=observation, evidence=evidence)

    def observe_both_roots(
        self,
        grant: ObservationGrant,
        selected_job: SelectedJob,
        boundary: Boundary,
    ) -> Result[BothRootObservations]:
        """Both roots or neither: publication and host_evidence, distinct objects."""
        refused = self._grant_refusal(grant, selected_job, boundary)
        if refused is not None:
            return refused
        self.snapshot_reads += 1
        refused = self._runtime_refusal(boundary)
        if refused is not None:
            return refused
        return self._both_roots(boundary)

    def _both_roots(self, boundary: Boundary) -> Result[BothRootObservations]:
        """Both roots or neither, two separate objects. Callers check grant and runtime first."""
        if missing_root_halves(self._root_pins, self._root_stats):
            return make_refusal(RefusalCode.ROOT_MISMATCH, boundary)
        halves: dict[RootKind, RootObservation] = {}
        for kind in ROOT_KINDS:
            res = self._observe_one_root(kind, boundary)
            if isinstance(res, Refusal):
                return res
            halves[kind] = res.data
        pub, ev = self._root_stats["publication"], self._root_stats["host_evidence"]
        if (
            (pub.dev, pub.ino) == (ev.dev, ev.ino)
            or _nested(pub.host_path, ev.host_path)
            or _nested(pub.actor_path, ev.actor_path)
        ):
            return make_refusal(RefusalCode.ROOT_MISMATCH, boundary)
        both = BothRootObservations(
            publication=halves["publication"], host_evidence=halves["host_evidence"]
        )
        evidence = decision_evidence_for(
            selected_job=self._job, actor=self._actor, boundary=boundary
        )
        return AcceptedData(data=both, evidence=evidence)

    def root_owner_assertions(self) -> tuple[RootOwnerVsActorAssertion, ...]:
        """The owner-vs-actor facts of both roots, for the adapter to check again."""
        return tuple(
            owner_vs_actor(stat, self._actor)
            for kind in ROOT_KINDS
            if (stat := self._root_stats.get(kind)) is not None
        )

    # -- the port ---------------------------------------------------------------------------

    def collect_worker_frame(
        self,
        grant: ObservationGrant,
        selected_job: SelectedJob,
        boundary: Boundary,
        since_cursor: N3ObservationEpoch | None = None,
    ) -> Result[SuppliedWorkerFrame]:
        refused = self._grant_refusal(grant, selected_job, boundary)
        if refused is not None:
            return refused
        self.snapshot_reads += 1
        refused = self._fence_refusal(selected_job, boundary) or self._runtime_refusal(
            boundary
        )
        if refused is not None:
            return refused
        roots = self._both_roots(boundary)
        if isinstance(roots, Refusal):
            return roots
        frame = replace(
            self._frame,
            both_roots=roots.data,
            root_owner_assertions=self.root_owner_assertions(),
            effect_fence_verified=True,
        )
        return AcceptedData(data=frame, evidence=roots.evidence)

    def collect_root_observation(
        self,
        grant: ObservationGrant,
        actor_instance: NativeProcessRef,
        selected_root: RootScope,
        required_operations: EffectSet,
        boundary: Boundary,
    ) -> Result[RootObservation]:
        refused = self._grant_refusal(grant, self._job, boundary)
        if refused is not None:
            return refused
        scope_actor = selected_root.actor
        if (
            actor_instance != self._actor
            or scope_actor.subject_kind != "existing"
            or getattr(scope_actor, "identity", None) != self._actor
        ):
            return make_refusal(
                RefusalCode.SUBJECT_MISMATCH,
                boundary,
                retry_kind=RetryKind.NEW_BINDING_REQUIRED,
            )
        self.snapshot_reads += 1
        refused = self._runtime_refusal(boundary)
        if refused is not None:
            return refused
        kind: RootKind = (
            "publication" if selected_root.role == "publication" else "host_evidence"
        )
        pin = self._root_pins.get(kind)
        stat = self._root_stats.get(kind)
        expected_object = selected_root.expected_existing_object
        if (
            selected_root.role == "host-parent"
            or pin is None
            or stat is None
            or selected_root.selected_locator != pin.actor_path
            or (expected_object is not None and expected_object != stat.root_object)
        ):
            return make_refusal(RefusalCode.ROOT_MISMATCH, boundary)
        return self._observe_one_root(
            kind, boundary, required_rights=frozenset(selected_root.required_rights)
        )

    def verify_child_launch(
        self, ticket: ChildRegistrationTicket
    ) -> Result[DecisionEvidence]:
        """Children are not this provider's: it verifies the worker box and roots only."""
        return make_refusal(
            RefusalCode.PEER_UNVERIFIED,
            ticket.boundary,
            retry_kind=RetryKind.NOT_APPLICABLE,
        )
