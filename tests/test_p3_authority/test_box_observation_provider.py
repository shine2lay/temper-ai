"""P3 T5-N4: the worker box, both roots and the write fence, from supplied snapshots.

Model-free and Docker-free: the sealed profile comes from box_profile.compile_profile,
the container from a fixed ``docker inspect`` object, the roots from fixed stat
records. The provider runs inside the real WorkerObservationAdapter (the
WorkerObserver) and its root_observer (the RootObserver).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

import pytest

from temper_ai.p3_authority import box_observation_provider as provider_module
from temper_ai.p3_authority import worker_observation as worker_module
from temper_ai.p3_authority.boundary_types import CurrentObservationCursors
from temper_ai.p3_authority.box_observation_provider import (
    BoxInspectSnapshot,
    BoxMount,
    BoxObservationProvider,
    RootKind,
    RootPin,
    RootStatSnapshot,
)
from temper_ai.p3_authority.child_registration import ChildRegistrationTicket
from temper_ai.p3_authority.contract import (
    AcceptedData,
    BothRootObservations,
    Boundary,
    NativeProcessRef,
    NativeRootObject,
    ObservationGrant,
    Refusal,
    RefusalCode,
    RootObservation,
    RootScope,
    SelectedJob,
    WorkerObservation,
)
from temper_ai.p3_authority.effect_fence import DeterministicEffectFenceProvider
from temper_ai.p3_authority.worker_observation import (
    RootOwnerVsActorAssertion,
    SuppliedWorkerFrame,
    WorkerObservationAdapter,
)
from temper_ai.spawner import box_profile
from temper_ai.spawner.box_view import SEALED
from tests.test_p3_authority.test_child_registration import (
    _GrantRef,
    _Interval,
    _ObservationGrant,
    _Permission,
    _ProcessRef,
    make_child_pair,
    make_grant,
    make_host_and_worker_processes,
    make_selected_job,
    make_selected_op,
    make_supplied_worker_frame,
    make_witness,
)
from tests.test_p3_authority.test_effect_fence import (
    _advance_cursors,
    _build_cursors,
    writes_admitted_on_master,
)
from tests.test_spawner.test_box_profile import _doc

BOUNDARY: Boundary = "C_BEFORE_COUNT"
WORKER_UID = 1001
ACTOR = _ProcessRef("worker")
PERMISSION = "granted-263"
PUB_DEV, PUB_INO = 41, 7001
EV_DEV, EV_INO = 41, 9002


@dataclass(frozen=True, slots=True)
class RootObject:
    """A root's filesystem object (NativeRootObject)."""

    filesystem_object: str
    mount_identity: str
    namespace_identity: str
    observation_epoch: str


def root_object(label: str) -> RootObject:
    return RootObject(
        filesystem_object=f"fs:{label}",
        mount_identity=f"mnt:{label}",
        namespace_identity="mntns-container",
        observation_epoch="epoch-1",
    )


@dataclass(frozen=True, slots=True)
class Existing:
    """An existing subject (ExistingSubject): a process or a root object."""

    identity: NativeProcessRef | NativeRootObject
    subject_kind: Literal["existing"] = "existing"


# -- the fixed world ----------------------------------------------------------------------


def grant_entry(target: str, dev: int, ino: int, *, read_only: bool) -> dict[str, Any]:
    return {
        "target": target,
        "read_only": read_only,
        "pin": {"dev": dev, "ino": ino, "type": "dir"},
    }


def sealed_profile(
    *,
    generation: int = 1,
    evidence_read_only: bool = False,
    evidence_pin: tuple[int, int] = (EV_DEV, EV_INO),
) -> dict[str, Any]:
    return _doc(
        SEALED,
        generation=generation,
        grants=[
            grant_entry("/workspace/pub", PUB_DEV, PUB_INO, read_only=True),
            grant_entry("/workspace/evidence", *evidence_pin, read_only=evidence_read_only),
        ],
        tmpfs=["/tmp:size=64m"],
        runtime={
            "interpreter": "/app/.venv/bin/python",
            "path": ["/usr/bin", "/bin"],
            "home": "/app",
            "user": f"{WORKER_UID}:{WORKER_UID}",
        },
    )


def inspect_json(doc: dict[str, Any]) -> dict[str, Any]:
    """The worker container as ``docker inspect`` shows it, started with ``doc``."""
    env = {**box_profile.env_for(doc), "HOME": "/app", "PATH": "/usr/bin:/bin"}
    granted = [
        {"Type": "bind", "Destination": g["target"], "RW": not g["read_only"]}
        for g in doc["grants"]
    ]
    return {
        "Id": "container-1",
        "State": {"Running": True, "Pid": 52001},
        "Config": {
            "User": f"{WORKER_UID}:{WORKER_UID}",
            "Env": [f"{k}={v}" for k, v in env.items()],
        },
        "HostConfig": {
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapAdd": None,
            "PidMode": "",
            "IpcMode": "private",
            "UsernsMode": "",
            "NetworkMode": "temper-run-run-1",
        },
        "Mounts": [*granted, {"Type": "tmpfs", "Destination": "/tmp", "RW": True}],
    }


def snapshot_of(inspect: dict[str, Any]) -> BoxInspectSnapshot:
    return BoxInspectSnapshot.from_inspect(
        inspect,
        pid_namespace_id="pidns-container",
        mount_namespace_id="mntns-container",
        user_namespace_id="userns-container",
        launch_requests=(("agent_types", "script"),),
    )


def root_pins() -> dict[RootKind, RootPin]:
    validity = _Interval("interval-286", "monotonic", make_witness("wit-root"))
    grant_refs = (_GrantRef("grant-286-1"),)
    return {
        "publication": RootPin(
            root_kind="publication",
            host_path="/srv/temper/pub",
            actor_path="/workspace/pub",
            dev=PUB_DEV,
            ino=PUB_INO,
            generation=3,
            required_rights=frozenset({"observe", "read", "traverse"}),
            grant_refs=grant_refs,
            validity=validity,
        ),
        "host_evidence": RootPin(
            root_kind="host_evidence",
            host_path="/srv/temper/evidence",
            actor_path="/workspace/evidence",
            dev=EV_DEV,
            ino=EV_INO,
            generation=1,
            required_rights=frozenset({"observe", "traverse", "write"}),
            grant_refs=grant_refs,
            validity=validity,
        ),
    }


def root_stat(pin: RootPin, *, owner_uid: int, owner: str, rights: set[str]) -> RootStatSnapshot:
    return RootStatSnapshot(
        root_kind=pin.root_kind,
        host_path=pin.host_path,
        actor_path=pin.actor_path,
        dev=pin.dev,
        ino=pin.ino,
        generation=pin.generation,
        owner_uid=owner_uid,
        owner_principal=owner,
        actor_uid=WORKER_UID,
        actor_principal="actor-worker",
        granted_rights=frozenset(rights),
        root_object=root_object(pin.root_kind),
        mount_witness=make_witness(f"mnt-{pin.root_kind}"),
        provenance=(make_witness(f"stat-{pin.root_kind}"),),
    )


def root_stats(pins: dict[RootKind, RootPin]) -> dict[RootKind, RootStatSnapshot]:
    return {
        "publication": root_stat(
            pins["publication"], owner_uid=1000, owner="host-builder",
            rights={"observe", "read", "traverse"},
        ),
        "host_evidence": root_stat(
            pins["host_evidence"], owner_uid=0, owner="host-root-owner",
            rights={"observe", "traverse", "write"},
        ),
    }


@dataclass
class World:
    job: SelectedJob
    grant: ObservationGrant
    doc: dict[str, Any]
    inspect: BoxInspectSnapshot
    frame: SuppliedWorkerFrame
    pins: dict[RootKind, RootPin]
    stats: dict[RootKind, RootStatSnapshot]
    frontier: CurrentObservationCursors
    fence: DeterministicEffectFenceProvider | None

    def provider(self) -> BoxObservationProvider:
        return BoxObservationProvider(
            selected_job=self.job,
            sealed_profile=self.doc,
            inspect=self.inspect,
            worker_frame=self.frame,
            actor=ACTOR,
            permitted_observation=PERMISSION,
            root_pins=self.pins,
            root_stats=self.stats,
            effect_fence=self.fence,
            fence_frontier=self.frontier,
        )


def open_fence(
    job: SelectedJob, frontier: CurrentObservationCursors
) -> DeterministicEffectFenceProvider:
    return DeterministicEffectFenceProvider(
        writes_enabled=True,
        fence_open=True,
        selected_job=job,
        fenced_actor=ACTOR,
        expected_frontier=frontier,
    )


def clean() -> World:
    job = make_selected_job()
    doc = sealed_profile()
    pins = root_pins()
    frontier = _build_cursors()
    return World(
        job=job,
        grant=make_grant(job),
        doc=doc,
        inspect=snapshot_of(inspect_json(doc)),
        frame=make_supplied_worker_frame(Provide_roots=False, effect_fence_verified=False),
        pins=pins,
        stats=root_stats(pins),
        frontier=frontier,
        fence=open_fence(job, frontier),
    )


def observe(world: World) -> tuple[BoxObservationProvider, object]:
    provider = world.provider()
    adapter = WorkerObservationAdapter(provider=provider)
    return provider, adapter.observe(world.grant, world.job, BOUNDARY)


def refusal_code(result: object) -> RefusalCode | None:
    return result.code if isinstance(result, Refusal) else None


def with_permission(grant: ObservationGrant, permission: str) -> ObservationGrant:
    assert isinstance(grant, _ObservationGrant)
    return replace(grant, permission=_Permission(permission))


# -- the combined happy path (bp-be8d76b9) -------------------------------------------------


def test_combined_happy_path_sealed_box_both_roots_open_fence_accepts() -> None:
    """Valid grant + container/process/UID/GID/namespaces/read-only mounts matching the
    sealed profile + both roots with distinct owner and actor + open fence -> the
    WorkerObserver and RootObserver accept, and the service's lookups find them."""
    world = clean()
    provider = world.provider()
    adapter = WorkerObservationAdapter(provider=provider)
    assert provider.box_problems() == []

    worker = adapter.observe(world.grant, world.job, BOUNDARY)
    assert isinstance(worker, AcceptedData)
    assert isinstance(worker.data, WorkerObservation)
    assert worker.data.selection_revision == world.job.selection_revision
    container = worker.data.worker_instance.container_instance
    assert container is not None and container.full_container_id == "container-1"
    assert (
        adapter.lookup_worker_observation(
            selection_revision=world.job.selection_revision, boundary=BOUNDARY
        )
        == worker.data
    )

    both = provider.observe_both_roots(world.grant, world.job, BOUNDARY)
    assert isinstance(both, AcceptedData)
    assert isinstance(both.data, BothRootObservations)
    pub, ev = both.data.publication, both.data.host_evidence
    assert (pub.root_kind, pub.binding.role) == ("publication", "publication")
    assert (ev.root_kind, ev.binding.role) == ("host_evidence", "host-evidence")
    assert pub.binding.host_visible_path == "/srv/temper/pub"
    assert pub.binding.actor_instance == ACTOR == ev.binding.actor_instance
    assert pub.binding.object_identity != ev.binding.object_identity
    assert pub.binding.rights == frozenset({"observe", "read", "traverse"})
    assert "write" in ev.binding.rights

    roots = adapter.root_observer
    assert roots.lookup_root_observation(process_registration="worker", root_kind="publication") == pub
    assert roots.lookup_root_binding(selection_revision=world.job.selection_revision, boundary=BOUNDARY) == pub.binding
    assert roots.lookup_root_binding(root_kind="host_evidence") == ev.binding
    scope: RootScope = RootScope(
        role="publication",
        actor=Existing(identity=ACTOR),
        selected_locator="/workspace/pub",
        expected_existing_object=pub.binding.object_identity,
        new_leaf=None,
        required_rights=frozenset({"read"}),
    )
    one = roots.observe(world.grant, ACTOR, scope, world.job.authorized_operations, BOUNDARY)
    assert isinstance(one, AcceptedData)
    assert isinstance(one.data, RootObservation)
    assert one.data.binding == pub.binding

    # frame + its two roots, the direct both-roots read, the one-root read
    assert provider.snapshot_reads == 4
    assert writes_admitted_on_master() is False
    unconfigured = WorkerObservationAdapter()
    assert refusal_code(unconfigured.observe(world.grant, world.job, BOUNDARY)) == RefusalCode.AUTHORITY_UNAVAILABLE


# -- the named guards (each bitten below) --------------------------------------------------


def test_unpermitted_grant_refused_before_any_snapshot_read() -> None:
    world = clean()
    foreign = with_permission(world.grant, "someone-elses-permission")
    provider = world.provider()
    for result in (
        provider.verify_grant(foreign, world.job, BOUNDARY),
        provider.collect_worker_frame(foreign, world.job, BOUNDARY),
        provider.observe_both_roots(foreign, world.job, BOUNDARY),
        WorkerObservationAdapter(provider=provider).observe(foreign, world.job, BOUNDARY),
    ):
        assert refusal_code(result) == RefusalCode.OBSERVATION_NOT_AUTHORIZED
    assert provider.snapshot_reads == 0


def test_publication_alone_is_not_both_roots() -> None:
    world = clean()
    world = replace(world, stats={"publication": world.stats["publication"]})
    provider = world.provider()
    result = provider.observe_both_roots(world.grant, world.job, BOUNDARY)
    assert refusal_code(result) == RefusalCode.ROOT_MISMATCH


def test_actor_owning_its_root_refused_by_provider() -> None:
    world = clean()
    owned = replace(world.stats["publication"], owner_uid=WORKER_UID)
    world = replace(world, stats={**world.stats, "publication": owned})
    provider = world.provider()
    result = provider.observe_both_roots(world.grant, world.job, BOUNDARY)
    assert refusal_code(result) == RefusalCode.RIGHTS_MISSING


def test_actor_owning_its_root_refused_by_adapter() -> None:
    world = clean()
    provider = world.provider()
    both = provider.observe_both_roots(world.grant, world.job, BOUNDARY)
    assert isinstance(both, AcceptedData)
    owns = RootOwnerVsActorAssertion(
        root_kind="publication",
        actor_process_ref="worker",
        actor_principal="actor-worker",
        actor_uid=WORKER_UID,
        file_owner_principal="host-builder",
        file_owner_uid=WORKER_UID,
    )
    result = WorkerObservationAdapter(provider=provider).root_observer.verify_both_roots(
        both.data,
        actor_instance=ACTOR,
        root_owner_assertions=(owns,),
        boundary=BOUNDARY,
        evidence=both.evidence,
    )
    assert refusal_code(result) == RefusalCode.RIGHTS_MISSING


def test_closed_fence_never_admits() -> None:
    world = clean()
    closed = DeterministicEffectFenceProvider(
        selected_job=world.job, fenced_actor=ACTOR, expected_frontier=world.frontier
    )
    assert (closed.writes_enabled, closed.fence_open) == (False, False)
    _, result = observe(replace(world, fence=closed))
    assert refusal_code(result) == RefusalCode.WRITES_DISABLED


# -- refusal twins --------------------------------------------------------------------------


def test_missing_or_empty_permission_refuses_before_any_collection() -> None:
    world = clean()
    provider, result = observe(replace(world, grant=with_permission(world.grant, "")))
    assert refusal_code(result) == RefusalCode.OBSERVATION_NOT_AUTHORIZED
    assert provider.snapshot_reads == 0
    for wrong in (
        replace(world, job=make_selected_job(selection_revision="sel-other")),
        replace(world, grant=make_grant(make_selected_job(selection_revision="sel-other"))),
    ):
        provider = wrong.provider() if wrong.job is world.job else world.provider()
        result = provider.verify_grant(wrong.grant, wrong.job, BOUNDARY)
        assert refusal_code(result) == RefusalCode.SELECTION_CHANGED
        assert provider.snapshot_reads == 0


Change = Callable[[World], World]


def inspect_with(**changes: Any) -> Change:
    return lambda w: replace(w, inspect=replace(w.inspect, **changes))


def environ_with(**changes: str) -> Change:
    return lambda w: replace(w, inspect=replace(w.inspect, environ={**w.inspect.environ, **changes}))


def mounts_with(change: Callable[[tuple[BoxMount, ...]], tuple[BoxMount, ...]]) -> Change:
    return lambda w: replace(w, inspect=replace(w.inspect, mounts=change(w.inspect.mounts)))


def started_with_other_profile(w: World) -> World:
    other = snapshot_of(inspect_json(sealed_profile(generation=2)))
    return replace(w, inspect=replace(w.inspect, environ=other.environ))


def started_without_profile(w: World) -> World:
    return replace(w, inspect=replace(w.inspect, environ={"HOME": "/app", "PATH": "/usr/bin:/bin"}))


def worker_in_host_mount_namespace(w: World) -> World:
    host_ns = w.frame.host_instance.mount_namespace_id
    worker = replace(w.frame.worker_instance, mount_namespace_id=host_ns)
    return replace(
        w,
        frame=replace(w.frame, worker_instance=worker),
        inspect=replace(w.inspect, mount_namespace_id=host_ns),
    )


def worker_process_uid(w: World) -> World:
    closure = replace(w.frame.worker_closure_instance, uid=1002)
    return replace(w, frame=replace(w.frame, worker_closure_instance=closure))


RUNTIME_CHANGED_CASES: dict[str, Change] = {
    "uid-gid": inspect_with(user="1002:1002"),
    "user-by-name": inspect_with(user="worker"),
    "worker-process-uid": worker_process_uid,
    "writable-root": inspect_with(readonly_rootfs=False),
    "host-pid-mode": inspect_with(pid_mode="host"),
    "host-ipc-mode": inspect_with(ipc_mode="host"),
    "host-network": inspect_with(network_mode="host"),
    "host-userns": inspect_with(userns_mode="host"),
    "privileged": inspect_with(privileged=True),
    "cap-add": inspect_with(cap_add=("SYS_ADMIN",)),
    "other-container": inspect_with(container_id="container-2"),
    "not-running": inspect_with(running=False),
    "pid-namespace-drift": inspect_with(pid_namespace_id="pidns-other"),
    "mount-namespace-drift": inspect_with(mount_namespace_id="mntns-other"),
    "user-namespace-drift": inspect_with(user_namespace_id="userns-other"),
    "worker-in-host-mount-namespace": worker_in_host_mount_namespace,
    "unclassified-tool": inspect_with(launch_requests=(("tools", "Bash"),)),
    "unknown-launch-class": inspect_with(launch_requests=(("plugins", "x"),)),
    "home": environ_with(HOME="/root"),
    "path": environ_with(PATH="/tmp/bin:/usr/bin"),
    "started-with-other-profile": started_with_other_profile,
    "started-without-profile": started_without_profile,
    "ungranted-mount": mounts_with(
        lambda ms: (*ms, BoxMount(target="/srv/secrets", read_only=True, kind="bind"))
    ),
    "read-only-grant-mounted-writable": mounts_with(
        lambda ms: tuple(replace(m, read_only=False) for m in ms)
    ),
    "grant-not-mounted": mounts_with(
        lambda ms: tuple(m for m in ms if m.target != "/workspace/pub")
    ),
}


@pytest.mark.parametrize("case", sorted(RUNTIME_CHANGED_CASES))
def test_collapsed_runtime_or_box_drift_refuses_runtime_changed(case: str) -> None:
    _, result = observe(RUNTIME_CHANGED_CASES[case](clean()))
    assert refusal_code(result) == RefusalCode.RUNTIME_CHANGED


def stat_with(kind: RootKind, **changes: Any) -> Change:
    return lambda w: replace(w, stats={**w.stats, kind: replace(w.stats[kind], **changes)})


def without_stat(kind: RootKind) -> Change:
    return lambda w: replace(w, stats={k: v for k, v in w.stats.items() if k != kind})


def without_pin(kind: RootKind) -> Change:
    return lambda w: replace(w, pins={k: v for k, v in w.pins.items() if k != kind})


def profile_with(**profile_facts: Any) -> Change:
    """A box whose sealed profile (and so its container) differs as given."""

    def change(w: World) -> World:
        doc = sealed_profile(**profile_facts)
        return replace(w, doc=doc, inspect=snapshot_of(inspect_json(doc)))

    return change


def root_moved(kind: RootKind, **changes: Any) -> Change:
    """The pin and the stat agree with each other, both changed as given."""
    return lambda w: replace(
        w,
        pins={**w.pins, kind: replace(w.pins[kind], **changes)},
        stats={**w.stats, kind: replace(w.stats[kind], **changes)},
    )


def both_roots_one_object(w: World) -> World:
    w = profile_with(evidence_pin=(PUB_DEV, PUB_INO))(w)
    return root_moved("host_evidence", dev=PUB_DEV, ino=PUB_INO)(w)


ROOT_MISMATCH_CASES: dict[str, Change] = {
    "no-host-evidence-stat": without_stat("host_evidence"),
    "no-host-evidence-pin": without_pin("host_evidence"),
    "no-publication-stat": without_stat("publication"),
    "ino-drift": stat_with("publication", ino=PUB_INO + 1),
    "dev-drift": stat_with("host_evidence", dev=EV_DEV + 1),
    "generation-drift": stat_with("publication", generation=4),
    "host-path-escape": stat_with("publication", host_path="/srv/temper/pub/../other"),
    "host-path-not-normal": stat_with("publication", host_path="/srv/temper//pub"),
    "other-host-path": stat_with("host_evidence", host_path="/srv/temper/evidence2"),
    "actor-subpath": stat_with("publication", actor_path="/workspace/pub/inner"),
    "both-roots-one-object": both_roots_one_object,
    "pin-not-the-profiles": root_moved("publication", ino=7999),
    "root-not-mounted": root_moved("host_evidence", actor_path="/workspace/elsewhere"),
    "no-provenance": stat_with("host_evidence", provenance=()),
}


@pytest.mark.parametrize("case", sorted(ROOT_MISMATCH_CASES))
def test_half_root_or_dev_ino_generation_or_path_mismatch_refuses_root_mismatch(case: str) -> None:
    _, result = observe(ROOT_MISMATCH_CASES[case](clean()))
    assert refusal_code(result) == RefusalCode.ROOT_MISMATCH


RIGHTS_MISSING_CASES: dict[str, Change] = {
    "owner-uid-is-actor": stat_with("publication", owner_uid=WORKER_UID),
    "owner-principal-is-actor": stat_with("host_evidence", owner_principal="actor-worker"),
    "rights-of-another-uid": stat_with("publication", actor_uid=1002),
    "rights-of-another-principal": stat_with("publication", actor_principal="actor-other"),
    "no-read": stat_with("publication", granted_rights=frozenset({"observe", "traverse"})),
    "no-traverse": stat_with("publication", granted_rights=frozenset({"observe", "read"})),
    "no-write": stat_with("host_evidence", granted_rights=frozenset({"observe", "traverse"})),
    "write-through-read-only-mount": profile_with(evidence_read_only=True),
    "unknown-right": stat_with(
        "publication", granted_rights=frozenset({"observe", "read", "traverse", "admin"})
    ),
}


@pytest.mark.parametrize("case", sorted(RIGHTS_MISSING_CASES))
def test_missing_right_or_actor_is_owner_refuses_rights_missing(case: str) -> None:
    _, result = observe(RIGHTS_MISSING_CASES[case](clean()))
    assert refusal_code(result) == RefusalCode.RIGHTS_MISSING


def closed_fence(world: World) -> DeterministicEffectFenceProvider:
    fence = open_fence(world.job, world.frontier)
    fence.close_fence()
    return fence


def disabled_fence(world: World) -> DeterministicEffectFenceProvider:
    fence = open_fence(world.job, world.frontier)
    fence.disable_writes()
    return fence


def test_absent_closed_or_disabled_fence_refuses_writes_disabled() -> None:
    for make_fence in (lambda w: None, closed_fence, disabled_fence):
        world = clean()
        _, result = observe(replace(world, fence=make_fence(world)))
        assert refusal_code(result) == RefusalCode.WRITES_DISABLED


def test_stale_frontier_after_wait_refuses_runtime_changed() -> None:
    world = clean()
    assert world.fence is not None
    adapter = WorkerObservationAdapter(provider=world.provider())
    assert isinstance(adapter.observe(world.grant, world.job, BOUNDARY), AcceptedData)
    world.fence.advance_frontier(_advance_cursors(world.frontier))
    assert refusal_code(adapter.observe(world.grant, world.job, BOUNDARY)) == RefusalCode.RUNTIME_CHANGED

    later = clean()
    assert later.fence is not None
    later.fence.mark_frontier_stale()
    _, result = observe(later)
    assert refusal_code(result) == RefusalCode.RUNTIME_CHANGED


def test_one_root_reads_refuse_scope_drift_other_actor_and_host_parent() -> None:
    world = clean()
    provider = world.provider()
    ops = world.job.authorized_operations
    scope: RootScope = RootScope(
        role="publication",
        actor=Existing(identity=ACTOR),
        selected_locator="/workspace/pub",
        expected_existing_object=root_object("publication"),
        new_leaf=None,
        required_rights=frozenset({"read"}),
    )
    accepted = provider.collect_root_observation(world.grant, ACTOR, scope, ops, BOUNDARY)
    assert isinstance(accepted, AcceptedData)
    root_mismatches = {
        "host-parent": replace(scope, role="host-parent", selected_locator="/srv/temper"),
        "other-locator": replace(scope, selected_locator="/workspace/evidence"),
        "other-object": replace(scope, expected_existing_object=root_object("elsewhere")),
        "write-through-read-only-mount": replace(scope, required_rights=frozenset({"write"})),
    }
    for case, drifted in root_mismatches.items():
        result = provider.collect_root_observation(world.grant, ACTOR, drifted, ops, BOUNDARY)
        expected = (
            RefusalCode.RIGHTS_MISSING
            if case == "write-through-read-only-mount"
            else RefusalCode.ROOT_MISMATCH
        )
        assert refusal_code(result) == expected, case
    checker = _ProcessRef("checker")
    for actor, drifted in (
        (checker, scope),
        (ACTOR, replace(scope, actor=Existing(identity=checker))),
    ):
        result = provider.collect_root_observation(world.grant, actor, drifted, ops, BOUNDARY)
        assert refusal_code(result) == RefusalCode.SUBJECT_MISMATCH


def test_child_launches_are_not_verified_by_the_box_provider() -> None:
    world = clean()
    _, _, worker_proc, worker_closure = make_host_and_worker_processes()
    child, child_closure = make_child_pair(worker_proc, worker_closure)
    ticket = ChildRegistrationTicket(
        selected_job=world.job,
        grant=world.grant,
        parent_instance=worker_proc,
        child_instance=child,
        closure_instance=child_closure,
        boundary=BOUNDARY,
        intended_effect=make_selected_op(),
    )
    assert refusal_code(world.provider().verify_child_launch(ticket)) == RefusalCode.PEER_UNVERIFIED


def test_malformed_inputs_fail_loud_naming_what_is_missing() -> None:
    broken = inspect_json(sealed_profile())
    del broken["HostConfig"]["ReadonlyRootfs"]
    with pytest.raises(ValueError, match=r"docker inspect has no HostConfig\.ReadonlyRootfs"):
        snapshot_of(broken)
    del broken["State"]
    with pytest.raises(ValueError, match="docker inspect has no State$"):
        snapshot_of(broken)
    world = clean()
    with pytest.raises(ValueError, match="permitted_observation"):
        BoxObservationProvider(
            selected_job=world.job,
            sealed_profile=world.doc,
            inspect=world.inspect,
            worker_frame=world.frame,
            actor=ACTOR,
            permitted_observation="",
            root_pins=world.pins,
            root_stats=world.stats,
        )


# -- guard bites: drop a guard -> its named test fails; restore -> it passes ---------------

GuardBite = tuple[Callable[[pytest.MonkeyPatch], None], Callable[[], None], type[Exception]]

# Unguarded, each named test fails: an accepted result (AssertionError), or for a
# missing half-root a crash on the absent stat instead of a refusal (KeyError).
GUARD_BITES: dict[str, GuardBite] = {
    "grant-before-any-read": (
        lambda m: m.setattr(BoxObservationProvider, "_grant_refusal", lambda *a, **k: None),
        test_unpermitted_grant_refused_before_any_snapshot_read,
        AssertionError,
    ),
    "both-halves-of-the-roots": (
        lambda m: m.setattr(provider_module, "missing_root_halves", lambda *a, **k: ()),
        test_publication_alone_is_not_both_roots,
        KeyError,
    ),
    "provider-actor-not-owner": (
        lambda m: m.setattr(provider_module, "actor_owns_root", lambda *a, **k: False),
        test_actor_owning_its_root_refused_by_provider,
        AssertionError,
    ),
    "adapter-actor-not-owner": (
        lambda m: m.setattr(worker_module, "actor_owns_root", lambda *a, **k: False),
        test_actor_owning_its_root_refused_by_adapter,
        AssertionError,
    ),
    "closed-fence-never-admits": (
        lambda m: m.setattr(
            DeterministicEffectFenceProvider, "refusal_if_closed_or_stale", lambda *a, **k: None
        ),
        test_closed_fence_never_admits,
        AssertionError,
    ),
}


@pytest.mark.parametrize("guard", sorted(GUARD_BITES))
def test_guard_mutation_bites(guard: str, monkeypatch: pytest.MonkeyPatch) -> None:
    drop_guard, named_test, failure = GUARD_BITES[guard]
    named_test()
    with monkeypatch.context() as m:
        drop_guard(m)
        with pytest.raises(failure):
            named_test()
    named_test()
