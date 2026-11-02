"""Process and root descriptions, not process lookup or filesystem authority."""

from dataclasses import dataclass
from typing import Generic, Literal

from ._parameters import (
    BirthT,
    ContainerT,
    GrantT,
    IntervalT,
    ObservedT,
    ProcessT,
    RootObjectT,
    SubjectT,
    WitnessT,
)
from ._shape import choice, integer, items, references, text_fields, words


@dataclass(frozen=True, slots=True)
class ProcessInstance(Generic[WitnessT, BirthT, ProcessT, ObservedT, ContainerT]):
    native_identity: WitnessT
    host_instance_id: str
    boot_id: str
    pid_namespace_id: str
    pid: int
    start_identity: BirthT
    exec_generation: WitnessT
    launch_id: str
    parent_instance: ProcessT | None
    role: str
    runtime_ref: ObservedT
    container_instance: ContainerT | None
    mount_namespace_id: str
    user_namespace_id: str

    def __post_init__(self) -> None:
        references(
            native_identity=self.native_identity,
            start_identity=self.start_identity,
            exec_generation=self.exec_generation,
            runtime_ref=self.runtime_ref,
        )
        text_fields(
            host_instance_id=self.host_instance_id,
            boot_id=self.boot_id,
            pid_namespace_id=self.pid_namespace_id,
            launch_id=self.launch_id,
            role=self.role,
            mount_namespace_id=self.mount_namespace_id,
            user_namespace_id=self.user_namespace_id,
        )
        integer("pid", self.pid, minimum=1)


@dataclass(frozen=True, slots=True)
class RootScope(Generic[SubjectT, RootObjectT]):
    role: Literal["publication", "host-parent", "host-evidence"]
    actor: SubjectT
    selected_locator: str
    expected_existing_object: RootObjectT | None
    new_leaf: str | None
    required_rights: frozenset[str]

    def __post_init__(self) -> None:
        choice("role", self.role, ("publication", "host-parent", "host-evidence"))
        references(actor=self.actor)
        text_fields(selected_locator=self.selected_locator)
        if self.new_leaf is not None:
            text_fields(new_leaf=self.new_leaf)
        words("required_rights", self.required_rights)


@dataclass(frozen=True, slots=True)
class RootBinding(Generic[RootObjectT, ProcessT, WitnessT, GrantT, IntervalT]):
    role: Literal["publication", "host-parent", "host-evidence"]
    object_identity: RootObjectT
    actor_instance: ProcessT
    namespace_and_mount_identity: WitnessT
    actor_visible_path: str
    host_visible_path: str
    rights: frozenset[str]
    grant_refs: tuple[GrantT, ...]
    validity: IntervalT
    mapping_witness: WitnessT

    def __post_init__(self) -> None:
        choice("role", self.role, ("publication", "host-parent", "host-evidence"))
        references(
            object_identity=self.object_identity,
            actor_instance=self.actor_instance,
            namespace_and_mount_identity=self.namespace_and_mount_identity,
            validity=self.validity,
            mapping_witness=self.mapping_witness,
        )
        text_fields(
            actor_visible_path=self.actor_visible_path,
            host_visible_path=self.host_visible_path,
        )
        words("rights", self.rights)
        items("grant_refs", self.grant_refs)
