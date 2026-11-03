"""P3 T5-N4: the worker box, both roots and the write fence, from supplied snapshots.

Model-free and Docker-free: the sealed profile comes from box_profile.compile_profile,
the container from a fixed ``docker inspect`` object shaped as the launcher's flags
leave it, the roots from fixed stat records. The provider runs inside the real
WorkerObservationAdapter (the WorkerObserver) and its root_observer (the RootObserver).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal, cast

import pytest

from temper_ai.p3_authority import box_observation_provider as provider_module
from temper_ai.p3_authority import worker_observation as worker_module
from temper_ai.p3_authority._providers import (
    InMemoryRootObserver,
    InMemoryWorkerObserver,
)
from temper_ai.p3_authority.boundary_types import CurrentObservationCursors
from temper_ai.p3_authority.box_observation_provider import (
    KEPT_ENVIRONMENT,
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
    RootBinding,
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
    WorkerRootObservationAdapter,
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
OTHER_BOUNDARY: Boundary = "C_PRE_EXECUTION"
WORKER_UID = 1001
ACTOR = _ProcessRef("worker")
PERMISSION = "granted-263"
PUB_DEV, PUB_INO = 41, 7001
EV_DEV, EV_INO = 41, 9002
TMPFS_OPTIONS = "rw,exec,nosuid,nodev,mode=1777"
# A credential in the container's environment: never kept, printed or echoed.
SECRET_NAME = "ANTHROPIC_API_KEY"
SECRET = "sk-canary-286-never-kept"


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


def grant_entry(
    target: str, source: str, dev: int, ino: int, *, read_only: bool
) -> dict[str, Any]:
    """One profile grant, as box_seal.Grant.to_profile writes it."""
    return {
        "source": source,
        "target": target,
        "read_only": read_only,
        "kind": "bind",
        "pin": {"dev": dev, "ino": ino, "type": "dir"},
    }


def sealed_profile(
    *,
    generation: int = 1,
    evidence_read_only: bool = False,
    evidence_pin: tuple[int, int] = (EV_DEV, EV_INO),
    evidence_target: str = "/workspace/evidence",
    evidence_source: str = "/srv/temper/evidence",
) -> dict[str, Any]:
    return _doc(
        SEALED,
        generation=generation,
        grants=[
            grant_entry(
                "/workspace/pub", "/srv/temper/pub", PUB_DEV, PUB_INO, read_only=True
            ),
            grant_entry(
                evidence_target,
                evidence_source,
                *evidence_pin,
                read_only=evidence_read_only,
            ),
        ],
        tmpfs=[f"/tmp:{TMPFS_OPTIONS}"],
        runtime={
            "interpreter": "/app/.venv/bin/python",
            "path": ["/usr/bin", "/bin"],
            "home": "/app",
            "user": f"{WORKER_UID}:{WORKER_UID}",
        },
    )


def inspect_json(doc: dict[str, Any]) -> dict[str, Any]:
    """The worker container as ``docker inspect`` shows it after the sealed launch."""
    env = {
        **box_profile.env_for(doc),
        "HOME": "/app",
        "PATH": "/usr/bin:/bin",
        SECRET_NAME: SECRET,
    }
    granted = [
        {
            "Type": "bind",
            "Source": g["source"],
            "Destination": g["target"],
            "RW": not g["read_only"],
            "Propagation": "rprivate",
        }
        for g in doc["grants"]
    ]
    return {
        "Id": "container-1",
        "Image": doc["image"]["id"],
        "State": {"Running": True, "Pid": 52001},
        "Config": {
            "User": f"{WORKER_UID}:{WORKER_UID}",
            "Env": [f"{k}={v}" for k, v in env.items()],
        },
        "HostConfig": {
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapAdd": None,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "Devices": [],
            "DeviceCgroupRules": None,
            "GroupAdd": None,
            "PidMode": "",
            "IpcMode": "private",
            "UsernsMode": "",
            "UTSMode": "",
            "CgroupnsMode": "private",
            "NetworkMode": "temper",
            "Tmpfs": {"/tmp": TMPFS_OPTIONS},
        },
        "Mounts": granted,
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


def root_stat(
    pin: RootPin, *, owner_uid: int, owner: str, rights: set[str]
) -> RootStatSnapshot:
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
            pins["publication"],
            owner_uid=1000,
            owner="host-builder",
            rights={"observe", "read", "traverse"},
        ),
        "host_evidence": root_stat(
            pins["host_evidence"],
            owner_uid=0,
            owner="host-root-owner",
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
    job: SelectedJob,
    frontier: CurrentObservationCursors,
    actor: NativeProcessRef = ACTOR,
) -> DeterministicEffectFenceProvider:
    return DeterministicEffectFenceProvider(
        writes_enabled=True,
        fence_open=True,
        selected_job=job,
        fenced_actor=actor,
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
        frame=make_supplied_worker_frame(
            Provide_roots=False, effect_fence_verified=False
        ),
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


def publication_scope(world: World, **changes: Any) -> RootScope:
    scope: RootScope = RootScope(
        role="publication",
        actor=Existing(identity=ACTOR),
        selected_locator="/workspace/pub",
        expected_existing_object=root_object("publication"),
        new_leaf=None,
        required_rights=frozenset({"read"}),
    )
    return replace(scope, **changes)


def host_evidence_scope(world: World, **changes: Any) -> RootScope:
    scope = publication_scope(
        world,
        role="host-evidence",
        selected_locator="/workspace/evidence",
        expected_existing_object=root_object("host_evidence"),
        required_rights=frozenset({"write"}),
    )
    return replace(scope, **changes)


# -- the combined happy path (bp-be8d76b9) -------------------------------------------------


def test_combined_happy_path_sealed_box_both_roots_open_fence_accepts() -> None:
    """Valid grant + container/process/UID/GID/namespaces/read-only mounts and hardening
    matching the sealed profile + both roots with distinct owner and actor + open fence
    -> the WorkerObserver and RootObserver accept, and the service's lookups find them
    at exactly the selection and boundary they were accepted at."""
    world = clean()
    revision = world.job.selection_revision
    provider = world.provider()
    adapter = WorkerObservationAdapter(provider=provider)

    worker = adapter.observe(world.grant, world.job, BOUNDARY)
    assert isinstance(worker, AcceptedData)
    assert isinstance(worker.data, WorkerObservation)
    assert worker.data.selection_revision == revision
    container = worker.data.worker_instance.container_instance
    assert container is not None and container.full_container_id == "container-1"
    assert (
        adapter.lookup_worker_observation(
            selection_revision=revision, boundary=BOUNDARY
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
    for kind, accepted in (("publication", pub), ("host_evidence", ev)):
        assert (
            roots.lookup_root_observation(process_registration="worker", root_kind=kind)
            == accepted
        )
    # A root binding is a one-root read's parent access: none until such a read is accepted.
    assert (
        roots.lookup_root_binding(selection_revision=revision, boundary=BOUNDARY)
        is None
    )
    one = roots.observe(
        world.grant,
        ACTOR,
        publication_scope(world),
        world.job.authorized_operations,
        BOUNDARY,
    )
    assert isinstance(one, AcceptedData)
    assert isinstance(one.data, RootObservation)
    assert one.data.binding == pub.binding
    assert (
        roots.lookup_root_binding(selection_revision=revision, boundary=BOUNDARY)
        == pub.binding
    )

    # the frame (its roots included), the direct both-roots read, the one-root read
    assert provider.snapshot_reads == 3
    assert writes_admitted_on_master() is False
    unconfigured = WorkerObservationAdapter()
    assert (
        refusal_code(unconfigured.observe(world.grant, world.job, BOUNDARY))
        == RefusalCode.AUTHORITY_UNAVAILABLE
    )


# -- the named guards (each bitten below) --------------------------------------------------


def test_unpermitted_grant_refused_before_any_snapshot_read() -> None:
    world = clean()
    foreign = with_permission(world.grant, "someone-elses-permission")
    provider = world.provider()
    for result in (
        provider.verify_grant(foreign, world.job, BOUNDARY),
        provider.collect_worker_frame(foreign, world.job, BOUNDARY),
        provider.observe_both_roots(foreign, world.job, BOUNDARY),
        provider.collect_root_observation(
            foreign,
            ACTOR,
            publication_scope(world),
            world.job.authorized_operations,
            BOUNDARY,
        ),
        WorkerObservationAdapter(provider=provider).observe(
            foreign, world.job, BOUNDARY
        ),
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
    result = WorkerObservationAdapter(
        provider=provider
    ).root_observer.verify_both_roots(
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


def test_container_environment_beyond_the_profile_is_never_kept_or_printed() -> None:
    """Only the box profile variables, HOME and PATH are kept; nothing prints them."""
    raw = inspect_json(sealed_profile())
    snapshot = snapshot_of(raw)
    assert set(snapshot.environ) == set(KEPT_ENVIRONMENT)
    world = replace(clean(), inspect=snapshot)
    provider = world.provider()
    refused = provider.verify_grant(
        with_permission(world.grant, ""), world.job, BOUNDARY
    )
    _, drifted = observe(replace(world, inspect=replace(snapshot, user="1002:1002")))
    assert refusal_code(drifted) == RefusalCode.RUNTIME_CHANGED
    for text in (
        repr(snapshot),
        str(snapshot),
        repr(provider),
        repr(refused),
        repr(drifted),
    ):
        assert SECRET not in text and SECRET_NAME not in text
    malformed: list[dict[str, Any]] = []
    for bad_entry in (f"NO_EQUALS_{SECRET}", f"{SECRET_NAME}=again-{SECRET}"):
        broken = copy.deepcopy(raw)
        broken["Config"]["Env"].append(bad_entry)
        malformed.append(broken)
    for broken in malformed:
        with pytest.raises(ValueError, match=r"Config\.Env\[\d+\]") as error:
            snapshot_of(broken)
        assert SECRET not in str(error.value) and SECRET_NAME not in str(error.value)


# -- the service's lookups: one table for the doubles and the adapter -----------------------


@dataclass
class Observers:
    """A WorkerObserver and RootObserver pair, with what they accepted at (S, BOUNDARY)."""

    workers: WorkerObservationAdapter | InMemoryWorkerObserver
    roots: WorkerRootObservationAdapter | InMemoryRootObserver
    worker: WorkerObservation
    root_by_kind: dict[str, RootObservation]
    binding: RootBinding


def accepted_by_doubles(world: World) -> Observers:
    """The landed in-memory doubles, registered with what the adapter would accept."""
    accepted = accepted_by_adapter(world)
    workers, roots = InMemoryWorkerObserver(), InMemoryRootObserver()
    workers.register_worker_observation(
        selection_revision=world.job.selection_revision,
        boundary=BOUNDARY,
        observation=accepted.worker,
    )
    for kind, root in accepted.root_by_kind.items():
        roots.register_root_observation(
            process_registration="worker", root_kind=kind, observation=root
        )
    roots.register_root_binding(
        selection_revision=world.job.selection_revision,
        boundary=BOUNDARY,
        binding=accepted.binding,
    )
    return replace(accepted, workers=workers, roots=roots)


def accepted_by_adapter(world: World) -> Observers:
    adapter = WorkerObservationAdapter(provider=world.provider())
    worker = adapter.observe(world.grant, world.job, BOUNDARY)
    assert isinstance(worker, AcceptedData)
    one = adapter.root_observer.observe(
        world.grant,
        ACTOR,
        publication_scope(world),
        world.job.authorized_operations,
        BOUNDARY,
    )
    assert isinstance(one, AcceptedData)
    roots = adapter.root_observer
    root_by_kind = {
        kind: roots.lookup_root_observation(
            process_registration="worker", root_kind=kind
        )
        for kind in ("publication", "host_evidence")
    }
    assert all(root is not None for root in root_by_kind.values())
    return Observers(
        workers=adapter,
        roots=roots,
        worker=worker.data,
        root_by_kind=cast(dict[str, RootObservation], root_by_kind),
        binding=one.data.binding,
    )


@pytest.mark.parametrize("make", [accepted_by_doubles, accepted_by_adapter])
def test_lookups_answer_only_the_exact_selection_and_boundary(
    make: Callable[[World], Observers],
) -> None:
    world = clean()
    revision = world.job.selection_revision
    seen = make(world)
    assert (
        seen.workers.lookup_worker_observation(
            selection_revision=revision, boundary=BOUNDARY
        )
        == seen.worker
    )
    assert (
        seen.roots.lookup_root_binding(selection_revision=revision, boundary=BOUNDARY)
        == seen.binding
    )
    for kind, root in seen.root_by_kind.items():
        assert (
            seen.roots.lookup_root_observation(
                process_registration="worker", root_kind=kind
            )
            == root
        )
    for selection, boundary in (("sel-other", BOUNDARY), (revision, OTHER_BOUNDARY)):
        assert (
            seen.workers.lookup_worker_observation(
                selection_revision=selection, boundary=boundary
            )
            is None
        )
        assert (
            seen.roots.lookup_root_binding(
                selection_revision=selection, boundary=boundary
            )
            is None
        )
    for kind in seen.root_by_kind:
        assert (
            seen.roots.lookup_root_observation(
                process_registration="checker", root_kind=kind
            )
            is None
        )
    for fresh_workers, fresh_roots in (
        (InMemoryWorkerObserver(), InMemoryRootObserver()),
        (
            WorkerObservationAdapter(provider=world.provider()),
            WorkerRootObservationAdapter(),
        ),
    ):
        assert (
            fresh_workers.lookup_worker_observation(
                selection_revision=revision, boundary=BOUNDARY
            )
            is None
        )
        assert (
            fresh_roots.lookup_root_binding(
                selection_revision=revision, boundary=BOUNDARY
            )
            is None
        )
        assert (
            fresh_roots.lookup_root_observation(
                process_registration="worker", root_kind="publication"
            )
            is None
        )


def assert_adapter_answers_nothing(
    adapter: WorkerObservationAdapter, revision: str
) -> None:
    assert (
        adapter.lookup_worker_observation(
            selection_revision=revision, boundary=BOUNDARY
        )
        is None
    )
    for kind in ("publication", "host_evidence"):
        assert (
            adapter.root_observer.lookup_root_observation(
                process_registration="worker", root_kind=kind
            )
            is None
        )


def test_refused_frame_after_accepted_roots_keeps_nothing() -> None:
    """The provider accepts both roots, the adapter then refuses the frame: no lookup answers."""
    world = clean()
    frame = replace(world.frame, collector_provenance=())
    adapter = WorkerObservationAdapter(provider=replace(world, frame=frame).provider())
    assert isinstance(adapter.observe(world.grant, world.job, BOUNDARY), Refusal)
    assert_adapter_answers_nothing(adapter, world.job.selection_revision)

    checked = WorkerObservationAdapter(provider=world.provider())
    both = world.provider().observe_both_roots(world.grant, world.job, BOUNDARY)
    assert isinstance(both, AcceptedData)
    verified = checked.root_observer.verify_both_roots(
        both.data,
        actor_instance=ACTOR,
        root_owner_assertions=(),
        boundary=BOUNDARY,
        evidence=both.evidence,
    )
    assert isinstance(verified, AcceptedData)
    assert_adapter_answers_nothing(checked, world.job.selection_revision)


def test_refused_reobservation_leaves_no_stale_lookup() -> None:
    """Accepted, then refused at the same selection and boundary: nothing earlier answers."""
    world = clean()
    revision = world.job.selection_revision
    assert world.fence is not None
    adapter = WorkerObservationAdapter(provider=world.provider())
    assert isinstance(adapter.observe(world.grant, world.job, BOUNDARY), AcceptedData)
    ops = world.job.authorized_operations
    roots = adapter.root_observer
    assert isinstance(
        roots.observe(world.grant, ACTOR, publication_scope(world), ops, BOUNDARY),
        AcceptedData,
    )
    assert (
        roots.lookup_root_binding(selection_revision=revision, boundary=BOUNDARY)
        is not None
    )

    world.fence.close_fence()
    assert (
        refusal_code(adapter.observe(world.grant, world.job, BOUNDARY))
        == RefusalCode.WRITES_DISABLED
    )
    assert_adapter_answers_nothing(adapter, revision)
    # The refused worker observation saw the runtime change: the binding goes too.
    assert (
        roots.lookup_root_binding(selection_revision=revision, boundary=BOUNDARY)
        is None
    )
    other_object = publication_scope(
        world, expected_existing_object=root_object("elsewhere")
    )
    assert (
        refusal_code(roots.observe(world.grant, ACTOR, other_object, ops, BOUNDARY))
        == RefusalCode.ROOT_MISMATCH
    )
    assert (
        roots.lookup_root_binding(selection_revision=revision, boundary=BOUNDARY)
        is None
    )


def test_root_binding_lookup_answers_the_latest_accepted_read() -> None:
    """Two different accepted bindings at one (S, B) answer the second, adapter and double alike.

    A refused read after an accepted one answers none in the adapter. The double differs
    there: its bindings come only from register_root_binding, and its reads never touch them.
    """
    world = clean()
    revision = world.job.selection_revision
    ops = world.job.authorized_operations
    roots = WorkerObservationAdapter(provider=world.provider()).root_observer
    double = InMemoryRootObserver()

    def lookups() -> tuple[RootBinding | None, RootBinding | None]:
        return (
            roots.lookup_root_binding(selection_revision=revision, boundary=BOUNDARY),
            double.lookup_root_binding(selection_revision=revision, boundary=BOUNDARY),
        )

    accepted: list[RootBinding] = []
    for scope in (
        publication_scope(world),
        host_evidence_scope(world),
        publication_scope(world),
    ):
        read = roots.observe(world.grant, ACTOR, scope, ops, BOUNDARY)
        assert isinstance(read, AcceptedData)
        double.register_root_binding(
            selection_revision=revision, boundary=BOUNDARY, binding=read.data.binding
        )
        accepted.append(read.data.binding)
        assert lookups() == (read.data.binding, read.data.binding)
    assert accepted[0] != accepted[1]
    assert (accepted[0].role, accepted[1].role) == ("publication", "host-evidence")

    elsewhere = publication_scope(
        world, expected_existing_object=root_object("elsewhere")
    )
    refused = roots.observe(world.grant, ACTOR, elsewhere, ops, BOUNDARY)
    assert refusal_code(refused) == RefusalCode.ROOT_MISMATCH
    double_refused = double.observe(world.grant, ACTOR, elsewhere, ops, BOUNDARY)
    assert refusal_code(double_refused) == RefusalCode.ROOT_MISMATCH
    assert lookups() == (None, accepted[-1])


def test_attempt_at_a_new_boundary_hides_the_earlier_boundarys_roots() -> None:
    world = clean()
    assert world.fence is not None
    adapter = WorkerObservationAdapter(provider=world.provider())
    assert isinstance(adapter.observe(world.grant, world.job, BOUNDARY), AcceptedData)
    world.fence.close_fence()
    assert isinstance(adapter.observe(world.grant, world.job, OTHER_BOUNDARY), Refusal)
    revision = world.job.selection_revision
    # The earlier boundary's worker record stays exact; the roots answer for the latest one.
    assert (
        adapter.lookup_worker_observation(
            selection_revision=revision, boundary=BOUNDARY
        )
        is not None
    )
    assert (
        adapter.lookup_worker_observation(
            selection_revision=revision, boundary=OTHER_BOUNDARY
        )
        is None
    )
    for kind in ("publication", "host_evidence"):
        assert (
            adapter.root_observer.lookup_root_observation(
                process_registration="worker", root_kind=kind
            )
            is None
        )


# -- refusal twins --------------------------------------------------------------------------


def test_missing_permission_or_another_selection_or_job_refuses_before_any_collection() -> (
    None
):
    world = clean()
    provider, result = observe(replace(world, grant=with_permission(world.grant, "")))
    assert refusal_code(result) == RefusalCode.OBSERVATION_NOT_AUTHORIZED
    assert provider.snapshot_reads == 0
    other_selection = make_selected_job(selection_revision="sel-other")
    same_selection_other_job = make_selected_job(
        execution_uuid="00000000-0000-4000-8000-000000000999"
    )
    assert same_selection_other_job.selection_revision == world.job.selection_revision
    assert same_selection_other_job != world.job
    cases: dict[str, tuple[ObservationGrant, SelectedJob, RefusalCode]] = {
        "asked-about-other-selection": (
            world.grant,
            other_selection,
            RefusalCode.SELECTION_CHANGED,
        ),
        "grant-for-other-selection": (
            make_grant(other_selection),
            world.job,
            RefusalCode.SELECTION_CHANGED,
        ),
        "asked-about-other-job": (
            world.grant,
            same_selection_other_job,
            RefusalCode.DISPATCH_CHANGED,
        ),
        "grant-for-other-job": (
            make_grant(same_selection_other_job),
            world.job,
            RefusalCode.DISPATCH_CHANGED,
        ),
    }
    for case, (grant, job, code) in cases.items():
        provider = world.provider()
        assert refusal_code(provider.verify_grant(grant, job, BOUNDARY)) == code, case
        assert (
            refusal_code(provider.collect_worker_frame(grant, job, BOUNDARY)) == code
        ), case
        assert provider.snapshot_reads == 0, case


Change = Callable[[World], World]


def inspect_with(**changes: Any) -> Change:
    return lambda w: replace(w, inspect=replace(w.inspect, **changes))


def environ_with(**changes: str) -> Change:
    return lambda w: replace(
        w, inspect=replace(w.inspect, environ={**w.inspect.environ, **changes})
    )


def mounts_with(
    change: Callable[[tuple[BoxMount, ...]], tuple[BoxMount, ...]],
) -> Change:
    return lambda w: replace(
        w, inspect=replace(w.inspect, mounts=change(w.inspect.mounts))
    )


def mount_at(target: str, **changes: Any) -> Change:
    return mounts_with(
        lambda ms: tuple(replace(m, **changes) if m.target == target else m for m in ms)
    )


def started_with_other_profile(w: World) -> World:
    other = snapshot_of(inspect_json(sealed_profile(generation=2)))
    return replace(w, inspect=replace(w.inspect, environ=other.environ))


def started_without_profile(w: World) -> World:
    return replace(
        w, inspect=replace(w.inspect, environ={"HOME": "/app", "PATH": "/usr/bin:/bin"})
    )


# Each case changes exactly one fact the sealed profile fixes, so it gives exactly one
# box problem: dropping that one check lets its case through and fails this test.
BOX_DRIFT_CASES: dict[str, Change] = {
    "other-image": inspect_with(image_id="sha256:" + "e" * 64),
    "uid-gid": inspect_with(user="1002:1002"),
    "user-by-name": inspect_with(user="worker"),
    "writable-root": inspect_with(readonly_rootfs=False),
    "home": environ_with(HOME="/root"),
    "path": environ_with(PATH="/tmp/bin:/usr/bin"),
    "started-with-other-profile": started_with_other_profile,
    "other-network": inspect_with(network_mode="bridge"),
    "no-no-new-privileges": inspect_with(security_opt=()),
    "no-new-privileges-false": inspect_with(security_opt=("no-new-privileges=false",)),
    "seccomp-unconfined": inspect_with(
        security_opt=("no-new-privileges", "seccomp=unconfined")
    ),
    "apparmor-unconfined": inspect_with(
        security_opt=("no-new-privileges", "apparmor=unconfined")
    ),
    "label-disable": inspect_with(security_opt=("no-new-privileges", "label:disable")),
    "systempaths-unconfined": inspect_with(
        security_opt=("no-new-privileges", "systempaths=unconfined")
    ),
    "no-cap-drop-all": inspect_with(cap_drop=("NET_RAW",)),
    "cap-add": inspect_with(cap_add=("SYS_ADMIN",)),
    "privileged": inspect_with(privileged=True),
    "host-device": inspect_with(device_count=1),
    "device-cgroup-rule": inspect_with(device_cgroup_rules=("c 1:3 rwm",)),
    "extra-group": inspect_with(group_add=("docker",)),
    "host-cgroup-namespace": inspect_with(cgroupns_mode="host"),
    "tmpfs-other-options": inspect_with(tmpfs={"/tmp": "rw,exec,suid,mode=1777"}),
    "tmpfs-missing": inspect_with(tmpfs={}),
    "tmpfs-extra": inspect_with(tmpfs={"/tmp": TMPFS_OPTIONS, "/run": "rw"}),
    "bind-at-tmpfs-target": mounts_with(
        lambda ms: (
            *ms,
            BoxMount(
                target="/tmp",
                source="/srv/tmp",
                read_only=False,
                kind="bind",
                propagation="rprivate",
            ),
        )
    ),
    "volume-at-grant-target": mount_at("/workspace/pub", kind="volume"),
    "grant-from-other-source": mount_at("/workspace/pub", source="/srv/elsewhere"),
    "grant-source-not-normal": mount_at("/workspace/pub", source="/srv/temper//pub"),
    "grant-propagation-rshared": mount_at("/workspace/pub", propagation="rshared"),
    "read-only-grant-mounted-writable": mount_at("/workspace/pub", read_only=False),
    "grant-not-mounted": mounts_with(
        lambda ms: tuple(m for m in ms if m.target != "/workspace/pub")
    ),
    "ungranted-mount": mounts_with(
        lambda ms: (
            *ms,
            BoxMount(
                target="/srv/secrets",
                source="/srv/secrets",
                read_only=True,
                kind="bind",
                propagation="rprivate",
            ),
        )
    ),
    "unclassified-tool": inspect_with(launch_requests=(("tools", "Bash"),)),
    "unknown-launch-class": inspect_with(launch_requests=(("plugins", "x"),)),
}


@pytest.mark.parametrize("case", sorted(BOX_DRIFT_CASES))
def test_box_drift_from_its_sealed_profile_refuses_runtime_changed(case: str) -> None:
    drifted = BOX_DRIFT_CASES[case](clean())
    assert len(drifted.provider()._box_problems()) == 1
    _, result = observe(drifted)
    assert refusal_code(result) == RefusalCode.RUNTIME_CHANGED


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
    "started-without-profile": started_without_profile,
    "worker-process-uid": worker_process_uid,
    "host-pid-mode": inspect_with(pid_mode="host"),
    "other-containers-pid": inspect_with(pid_mode="container:other"),
    "host-ipc-mode": inspect_with(ipc_mode="host"),
    "other-containers-ipc": inspect_with(ipc_mode="container:other"),
    "host-network": inspect_with(network_mode="host"),
    "other-containers-network": inspect_with(network_mode="container:other"),
    "host-userns": inspect_with(userns_mode="host"),
    "host-uts": inspect_with(uts_mode="host"),
    "other-container": inspect_with(container_id="container-2"),
    "not-running": inspect_with(running=False),
    "no-host-pid": inspect_with(host_pid=0),
    "pid-namespace-drift": inspect_with(pid_namespace_id="pidns-other"),
    "mount-namespace-drift": inspect_with(mount_namespace_id="mntns-other"),
    "user-namespace-drift": inspect_with(user_namespace_id="userns-other"),
    "worker-in-host-mount-namespace": worker_in_host_mount_namespace,
}


@pytest.mark.parametrize("case", sorted(RUNTIME_CHANGED_CASES))
def test_collapsed_runtime_or_process_drift_refuses_runtime_changed(case: str) -> None:
    _, result = observe(RUNTIME_CHANGED_CASES[case](clean()))
    assert refusal_code(result) == RefusalCode.RUNTIME_CHANGED


def stat_with(kind: RootKind, **changes: Any) -> Change:
    return lambda w: replace(
        w, stats={**w.stats, kind: replace(w.stats[kind], **changes)}
    )


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


def evidence_root_at(*, actor_path: str, host_path: str) -> Change:
    """The evidence root granted, mounted, pinned and stat'ed at the given paths."""

    def change(w: World) -> World:
        w = profile_with(evidence_target=actor_path, evidence_source=host_path)(w)
        return root_moved("host_evidence", actor_path=actor_path, host_path=host_path)(
            w
        )

    return change


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
    "host-paths-nested": evidence_root_at(
        actor_path="/workspace/evidence", host_path="/srv/temper/pub/evidence"
    ),
    "actor-paths-nested": evidence_root_at(
        actor_path="/workspace/pub/evidence", host_path="/srv/temper/evidence"
    ),
    "pin-not-the-profiles": root_moved("publication", ino=7999),
    "root-not-mounted": root_moved("host_evidence", actor_path="/workspace/elsewhere"),
    "mounted-from-another-source": root_moved(
        "host_evidence", host_path="/srv/temper/evidence2"
    ),
    "no-provenance": stat_with("host_evidence", provenance=()),
}


@pytest.mark.parametrize("case", sorted(ROOT_MISMATCH_CASES))
def test_half_root_or_dev_ino_generation_or_path_mismatch_refuses_root_mismatch(
    case: str,
) -> None:
    _, result = observe(ROOT_MISMATCH_CASES[case](clean()))
    assert refusal_code(result) == RefusalCode.ROOT_MISMATCH


RIGHTS_MISSING_CASES: dict[str, Change] = {
    "owner-uid-is-actor": stat_with("publication", owner_uid=WORKER_UID),
    "owner-principal-is-actor": stat_with(
        "host_evidence", owner_principal="actor-worker"
    ),
    "rights-of-another-uid": stat_with("publication", actor_uid=1002),
    "rights-of-another-principal": stat_with(
        "publication", actor_principal="actor-other"
    ),
    "no-read": stat_with(
        "publication", granted_rights=frozenset({"observe", "traverse"})
    ),
    "no-traverse": stat_with(
        "publication", granted_rights=frozenset({"observe", "read"})
    ),
    "no-write": stat_with(
        "host_evidence", granted_rights=frozenset({"observe", "traverse"})
    ),
    "write-through-read-only-mount": profile_with(evidence_read_only=True),
    "unknown-right": stat_with(
        "publication",
        granted_rights=frozenset({"observe", "read", "traverse", "admin"}),
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


def test_absent_closed_disabled_or_foreign_fence_refuses() -> None:
    for make_fence in (lambda w: None, closed_fence, disabled_fence):
        world = clean()
        _, result = observe(replace(world, fence=make_fence(world)))
        assert refusal_code(result) == RefusalCode.WRITES_DISABLED
    world = clean()
    other_job = make_selected_job(execution_uuid="00000000-0000-4000-8000-000000000999")
    foreign: dict[str, tuple[DeterministicEffectFenceProvider, RefusalCode]] = {
        "other-selection": (
            open_fence(
                make_selected_job(selection_revision="sel-other"), world.frontier
            ),
            RefusalCode.SELECTION_CHANGED,
        ),
        "other-job": (
            open_fence(other_job, world.frontier),
            RefusalCode.DISPATCH_CHANGED,
        ),
        "other-actor": (
            open_fence(world.job, world.frontier, _ProcessRef("checker")),
            RefusalCode.SUBJECT_MISMATCH,
        ),
    }
    for case, (fence, code) in foreign.items():
        _, result = observe(replace(world, fence=fence))
        assert refusal_code(result) == code, case


def test_stale_frontier_after_wait_refuses_runtime_changed() -> None:
    world = clean()
    assert world.fence is not None
    adapter = WorkerObservationAdapter(provider=world.provider())
    assert isinstance(adapter.observe(world.grant, world.job, BOUNDARY), AcceptedData)
    world.fence.advance_frontier(_advance_cursors(world.frontier))
    assert (
        refusal_code(adapter.observe(world.grant, world.job, BOUNDARY))
        == RefusalCode.RUNTIME_CHANGED
    )

    later = clean()
    assert later.fence is not None
    later.fence.mark_frontier_stale()
    _, result = observe(later)
    assert refusal_code(result) == RefusalCode.RUNTIME_CHANGED


def test_one_root_reads_refuse_scope_drift_other_actor_and_host_parent() -> None:
    world = clean()
    provider = world.provider()
    ops = world.job.authorized_operations
    scope = publication_scope(world)
    accepted = provider.collect_root_observation(
        world.grant, ACTOR, scope, ops, BOUNDARY
    )
    assert isinstance(accepted, AcceptedData)
    root_mismatches = {
        "host-parent": replace(
            scope, role="host-parent", selected_locator="/srv/temper"
        ),
        "other-locator": replace(scope, selected_locator="/workspace/evidence"),
        "other-object": replace(
            scope, expected_existing_object=root_object("elsewhere")
        ),
        "write-through-read-only-mount": replace(
            scope, required_rights=frozenset({"write"})
        ),
    }
    for case, drifted in root_mismatches.items():
        result = provider.collect_root_observation(
            world.grant, ACTOR, drifted, ops, BOUNDARY
        )
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
        result = provider.collect_root_observation(
            world.grant, actor, drifted, ops, BOUNDARY
        )
        assert refusal_code(result) == RefusalCode.SUBJECT_MISMATCH
    drifted_world = BOX_DRIFT_CASES["uid-gid"](world)
    result = drifted_world.provider().collect_root_observation(
        world.grant, ACTOR, scope, ops, BOUNDARY
    )
    assert refusal_code(result) == RefusalCode.RUNTIME_CHANGED


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
    assert (
        refusal_code(world.provider().verify_child_launch(ticket))
        == RefusalCode.PEER_UNVERIFIED
    )


def broken_inspect(change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    raw = copy.deepcopy(inspect_json(sealed_profile()))
    change(raw)
    return raw


MALFORMED_INSPECT: dict[str, tuple[Callable[[dict[str, Any]], None], str]] = {
    "no-readonly-rootfs": (
        lambda r: r["HostConfig"].pop("ReadonlyRootfs"),
        r"docker inspect has no HostConfig\.ReadonlyRootfs",
    ),
    "no-state": (lambda r: r.pop("State"), r"docker inspect has no State$"),
    "no-image": (lambda r: r.pop("Image"), r"docker inspect has no Image$"),
    "rw-not-bool": (
        lambda r: r["Mounts"][0].update(RW="yes"),
        r"docker inspect Mounts\[0\]\.RW is not true or false",
    ),
    "mount-without-source": (
        lambda r: r["Mounts"][1].pop("Source"),
        r"docker inspect has no Mounts\[1\]\.Source",
    ),
    "pid-not-number": (
        lambda r: r["State"].update(Pid=True),
        r"docker inspect State\.Pid is not a number",
    ),
    "env-not-list": (
        lambda r: r["Config"].update(Env="HOME=/app"),
        r"docker inspect Config\.Env is not a list",
    ),
    "cap-drop-not-strings": (
        lambda r: r["HostConfig"].update(CapDrop=[1]),
        r"docker inspect HostConfig\.CapDrop is not a list of strings",
    ),
    "tmpfs-not-map": (
        lambda r: r["HostConfig"].update(Tmpfs=["/tmp"]),
        r"docker inspect HostConfig\.Tmpfs is not a map of strings",
    ),
    "same-target-twice": (
        lambda r: r["Mounts"].append(dict(r["Mounts"][0])),
        r"docker inspect Mounts\[2\]\.Destination is mounted twice",
    ),
}


@pytest.mark.parametrize("case", sorted(MALFORMED_INSPECT))
def test_malformed_inspect_fails_loud_naming_the_field(case: str) -> None:
    change, message = MALFORMED_INSPECT[case]
    with pytest.raises(ValueError, match=message):
        snapshot_of(broken_inspect(change))


def test_malformed_provider_inputs_fail_loud() -> None:
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
    pin = world.pins["publication"]
    for bad, message in (
        ({"host_path": "/srv/temper//pub"}, "absolute and normal"),
        ({"actor_path": "workspace/pub"}, "absolute and normal"),
        (
            {"required_rights": frozenset({"admin"})},
            "observe, read, traverse and write",
        ),
        ({"root_kind": "host-parent"}, "publication or host_evidence"),
    ):
        with pytest.raises(ValueError, match=message):
            replace(pin, **bad)
    with pytest.raises(ValueError, match="environ keeps only"):
        replace(world.inspect, environ={**world.inspect.environ, SECRET_NAME: "x"})
    with pytest.raises(TypeError, match="launch_requests"):
        cast(Any, BoxInspectSnapshot.from_inspect)(
            inspect_json(world.doc),
            pid_namespace_id="pidns-container",
            mount_namespace_id="mntns-container",
            user_namespace_id="userns-container",
        )


# -- guard bites: drop a guard -> its named test fails; restore -> it passes ---------------


def keep_frame_roots_before_acceptance(m: pytest.MonkeyPatch) -> None:
    """Mutation: the root adapter keeps a frame's roots as soon as it verifies them."""
    verify = WorkerRootObservationAdapter.verify_both_roots

    def verify_and_keep(
        self: WorkerRootObservationAdapter, both: Any, **kwargs: Any
    ) -> Any:
        result = verify(self, both, **kwargs)
        if isinstance(result, AcceptedData) and both is not None:
            self._accept_frame_roots(
                make_selected_job().selection_revision,
                kwargs["boundary"],
                "worker",
                both,
            )
        return result

    m.setattr(WorkerRootObservationAdapter, "verify_both_roots", verify_and_keep)


GuardBite = tuple[
    Callable[[pytest.MonkeyPatch], None], Callable[[], None], type[Exception]
]

# Unguarded, each named test fails: an accepted result or a kept value (AssertionError),
# or for a missing half-root a crash on the absent stat instead of a refusal (KeyError).
GUARD_BITES: dict[str, GuardBite] = {
    "grant-before-any-read": (
        lambda m: m.setattr(
            BoxObservationProvider, "_grant_refusal", lambda *a, **k: None
        ),
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
            DeterministicEffectFenceProvider,
            "refusal_if_closed_or_stale",
            lambda *a, **k: None,
        ),
        test_closed_fence_never_admits,
        AssertionError,
    ),
    "environment-kept-only-for-the-profile": (
        lambda m: m.setattr(
            provider_module, "KEPT_ENVIRONMENT", (*KEPT_ENVIRONMENT, SECRET_NAME)
        ),
        test_container_environment_beyond_the_profile_is_never_kept_or_printed,
        AssertionError,
    ),
    "attempt-forgets-earlier-roots": (
        lambda m: m.setattr(
            WorkerRootObservationAdapter,
            "_forget_frame_attempt",
            lambda self, selection, boundary, actor: self._mark_latest(
                selection, boundary, actor
            ),
        ),
        test_refused_reobservation_leaves_no_stale_lookup,
        AssertionError,
    ),
    "frame-roots-kept-only-once-accepted": (
        keep_frame_roots_before_acceptance,
        test_refused_frame_after_accepted_roots_keeps_nothing,
        AssertionError,
    ),
    "refused-frame-drops-binding": (
        lambda m: m.setattr(
            WorkerObservationAdapter,
            "observe",
            lambda self, grant, job, boundary, since_cursor=None: self._observe_frame(
                grant, job, boundary, since_cursor
            ),
        ),
        test_refused_reobservation_leaves_no_stale_lookup,
        AssertionError,
    ),
    "refused-read-drops-binding": (
        lambda m: m.setattr(
            WorkerRootObservationAdapter,
            "_forget_binding",
            lambda self, selection, boundary: None,
        ),
        test_root_binding_lookup_answers_the_latest_accepted_read,
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
