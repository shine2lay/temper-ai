"""FilePublicationCohortStore: QA's read-only, content-addressed cohort source (N5c).

Every refusal has its own case, and every guard its own bite: turn that one guard
off and its own case stops being refused with its code.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from p3_host_contracts import (
    HostEffect,
    LifecycleKey,
    OccurrenceHandle,
    RawPublication,
    RawRef,
    RootScope,
    RowKey,
)
from p3_source_closure import N3SourceEpoch
from temper_ai.p3_authority import qa_publication_store as store_module
from temper_ai.p3_authority.contract import RefusalCode
from temper_ai.p3_authority.native_values import (
    NativeIntervalValue,
    NativeProcessRefValue,
    NativeRootObjectValue,
    NativeWitnessValue,
)
from temper_ai.p3_authority.qa_publication_store import (
    MAX_SNAPSHOT_BYTES,
    SNAPSHOT_SCHEMA,
    CohortSnapshotRefusal,
    FilePublicationCohortStore,
    encode_cohort_snapshot,
)
from temper_ai.p3_authority.qa_receiving import (
    OriginalExpectations,
    PublicationCohort,
    PublicationCohortMember,
    PublicationCohortQAReceivingVerifier,
    PublicationCohortSource,
)
from temper_ai.p3_authority.registry import (
    ExistingSubjectRecord,
    FutureSubjectRecord,
    ImmutableReferenceRecord,
)
from temper_ai.p3_authority.selection_snapshot import HostSelectionHandle
from tests.test_p3_authority._composition_fixtures import (
    make_populated_test_rig,
    populate_boundary_happy_path_observations,
)
from tests.test_p3_authority.test_qa_receiving import (
    _ARCH_BIN,
    _TEST_BOUNDARIES,
    _load_module_from_path,
)

Refusal = CohortSnapshotRefusal
_MODULE_PATH = Path(store_module.__file__)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _raw_ref(path: str, label: str) -> RawRef:
    return RawRef(
        root_locator="root:qa-cohort-1",
        relative_path=path,
        byte_length=128,
        sha256=_sha(label),
    )


# ---------------------------------------------------------------------------
# World: a Chromium + WebKit + host-row cohort built from production carriers
# ---------------------------------------------------------------------------


@dataclass
class StoreWorld:
    rig: Any
    root: Path
    store: FilePublicationCohortStore
    expectations: OriginalExpectations
    selection_revision: str
    cohort: PublicationCohort
    raw: bytes
    reference: ImmutableReferenceRecord
    qa_receiving: Any

    @property
    def cohorts(self) -> Path:
        return self.root / "cohorts"

    def put(self, raw: bytes) -> ImmutableReferenceRecord:
        """Write ``raw`` at its content address; return a reference to it."""
        digest = hashlib.sha256(raw).hexdigest()
        (self.cohorts / f"{digest}.json").write_bytes(raw)
        return replace(self.reference, digest=digest, length=len(raw))

    def read(self, reference: object, selection_revision: object = None) -> Any:
        revision = self.selection_revision if selection_revision is None else selection_revision
        return self.store.read_cohort_snapshot(
            reference,  # type: ignore[arg-type]
            selection_revision=revision,  # type: ignore[arg-type]
        )

    def verify(self, reference: ImmutableReferenceRecord, boundary: Any) -> Any:
        verifier = PublicationCohortQAReceivingVerifier(
            cohort_source=self.store, expectations=self.expectations
        )
        return verifier.verify_qa_receiving(
            replace(self.qa_receiving, receiving_reference=reference),
            selected_job=self.rig.running_job,
            boundary=boundary,
        )


def _build_cohort(obs: dict[str, Any], selection_revision: str, expectations: OriginalExpectations) -> PublicationCohort:
    expected = obs["w_arm"].expected
    source_epoch = N3SourceEpoch(
        expected.reviewed_graph, expected.review_ref, expected.binding.selection_revision
    )
    observation_epoch = obs["epoch"]
    selection = HostSelectionHandle(
        selection_reference=f"sel:{selection_revision}", selection_revision=selection_revision
    )
    witness = NativeWitnessValue(witness_reference="wit:qa-cohort-1")
    host = NativeProcessRefValue(process_registration="proc:host-1")
    worker = NativeProcessRefValue(process_registration="proc:worker-1")
    publisher = NativeProcessRefValue(process_registration="proc:qa-publisher-1")
    root_object = NativeRootObjectValue(
        filesystem_object="fs:qa-cohort-1",
        mount_identity="mount:root-1",
        namespace_identity="mnt:[4026531840]",
        observation_epoch="obs-epoch-1",
    )
    future = FutureSubjectRecord(selected_scope_reference="scope:qa-cohort-1")
    effect = HostEffect(
        kind="publish-receipt",
        selection=selection,
        target=future,
        operation="publish",
        actor=ExistingSubjectRecord(identity=publisher),
        purpose="qa-cohort",
        roots=(
            RootScope(
                role="publication",
                actor=ExistingSubjectRecord(identity=root_object),
                selected_locator="root:qa-cohort-1",
                expected_existing_object=root_object,
                new_leaf="cohort",
                required_rights=frozenset({"read", "write"}),
            ),
        ),
        boundary="C_BEFORE_COUNT",
    )
    interval = NativeIntervalValue(clock_domain="monotonic:host-1", interval_witness=witness)
    pub_schema = expectations.publication_schema

    def occurrence(key: Any, controller: Any) -> OccurrenceHandle[Any, Any, Any, Any, Any, Any, Any, Any]:
        return OccurrenceHandle(
            key=key,
            witness=witness,
            admitting_process=host,
            controller=controller,
            executing_processes=(worker,),
            route_witness=witness,
            targets=(future,),
            source_epoch=source_epoch,
            observation_epoch=observation_epoch,
            admission_boundary=effect,
            state="completed",
        )

    def member(leg: Any, key: Any, label: str, *, row: bool) -> PublicationCohortMember:
        receipt = _raw_ref(f"cohort/{label}-receipt.json", f"{label}-receipt-v1")
        request = _raw_ref(f"cohort/{label}-request.json", f"{label}-request-v1")
        extra = _raw_ref(f"cohort/{label}-extra.json", f"{label}-extra-v1") if row else None
        publication = RawPublication(
            occurrence=occurrence(key, host if row else None),
            producer_instance=worker,
            publisher_instance=publisher,
            request_raw_ref=request,
            receipt_raw_ref=receipt,
            evidence_refs=(receipt,),
            window_ref=extra,
            numbered_log_ref=extra,
            current_row_ref=extra,
            publication_steps=(witness,),
            observed_interval=interval,
            outcome="success",
            cleanup_state="complete",
        )
        return PublicationCohortMember(
            leg=leg,
            publication=publication,
            publication_schema=pub_schema,
            inventory_receipt_sha256=receipt.sha256,
        )

    def row_key(row: str, operation: str, sequence: int) -> RowKey[Any]:
        return RowKey(
            selection=selection,
            window_id="win-1",
            binding_ref=_raw_ref(f"cohort/{row}-binding.json", f"{row}-binding-v1"),
            writer="checker",
            row=row,
            operation=operation,
            request_id=f"req-{row}-{sequence}",
            sequence=sequence,
            request_raw_ref=_raw_ref(f"cohort/{row}-row-request.json", f"{row}-row-request-v1"),
        )

    return PublicationCohort(
        cohort_schema=expectations.cohort_schema,
        kit_id=expectations.kit_id,
        kit_sha256=expectations.kit_sha256,
        final_sha256=expectations.final_sha256,
        complete_publication=True,
        members=(
            member("chromium", LifecycleKey(selection, "launch-chromium-1", "browser-chromium"), "chromium", row=False),
            member("webkit", LifecycleKey(selection, "launch-webkit-1", "browser-webkit"), "webkit", row=False),
            member("host_row", row_key("D-1", "crash", 1), "d1", row=True),
            member("host_row", row_key("D-5", "start", 2), "d5", row=True),
        ),
    )


def pinned_expectations() -> OriginalExpectations:
    """The real P3 expectations, from configs/architecture/bin (tests may read configs)."""
    kit = _load_module_from_path("first_app_p3", _ARCH_BIN / "first_app_p3.py")
    rows = _load_module_from_path("first_app_p3_rows", _ARCH_BIN / "first_app_p3_rows.py")
    binding = _load_module_from_path("ops_host_binding", _ARCH_BIN / "ops_host_binding.py")
    return OriginalExpectations(
        kit_id=kit.KIT_ID,
        kit_sha256=kit.KIT_SHA256,
        final_sha256=rows.FINAL_SHA256,
        publication_schema=binding.PUBLICATION_SCHEMA,
        cohort_schema=binding.COHORT_SCHEMA,
    )


@pytest.fixture(scope="module")
def real_expectations() -> OriginalExpectations:
    return pinned_expectations()


@pytest.fixture()
def world(real_expectations: OriginalExpectations, tmp_path: Path) -> StoreWorld:
    rig = make_populated_test_rig(writes_enabled=True)
    obs = populate_boundary_happy_path_observations(rig)
    selection_revision = rig.running_job.selection_revision
    cohort = _build_cohort(obs, selection_revision, real_expectations)
    raw = encode_cohort_snapshot(cohort, selection_revision=selection_revision)
    root = tmp_path / "qa-publication"
    (root / "cohorts").mkdir(parents=True)
    digest = hashlib.sha256(raw).hexdigest()
    (root / "cohorts" / f"{digest}.json").write_bytes(raw)
    reference = ImmutableReferenceRecord(
        path="qa/receiving/p3-cohort.json", digest=digest, length=len(raw), revision="qa-recv-rev-1"
    )
    return StoreWorld(
        rig=rig,
        root=root,
        store=FilePublicationCohortStore(root),
        expectations=real_expectations,
        selection_revision=selection_revision,
        cohort=cohort,
        raw=raw,
        reference=reference,
        qa_receiving=obs["qa_recv"],
    )


def _document(world: StoreWorld) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(world.raw)
    return document


def _dump(document: Any) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _first_member_publication(document: dict[str, Any]) -> dict[str, Any]:
    publication: dict[str, Any] = document["members"][0]["publication"]
    return publication


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_round_trip_loads_the_exact_cohort_and_snapshot_reference(world: StoreWorld) -> None:
    assert isinstance(world.store, PublicationCohortSource)
    assert world.store.root == str(world.root)
    read = world.read(world.reference)
    assert read.refusal is None
    assert read.cohort == world.cohort
    assert world.store.load_cohort(world.reference, selection_revision=world.selection_revision) == world.cohort
    loaded = world.store.load_cohort_snapshot(world.reference, selection_revision=world.selection_revision)
    assert loaded is not None
    cohort, snapshot_reference = loaded
    assert cohort == world.cohort
    assert snapshot_reference == ImmutableReferenceRecord(
        path=world.reference.path,
        digest=hashlib.sha256(world.raw).hexdigest(),
        length=len(world.raw),
        revision=world.reference.revision,
    )
    # The canonical encoding is stable: decode then encode gives the same bytes.
    assert encode_cohort_snapshot(cohort, selection_revision=world.selection_revision) == world.raw
    # Decoded slots are production carriers, not test fakes.
    publication = cohort.members[2].publication
    assert type(publication.occurrence.witness) is NativeWitnessValue
    assert type(publication.occurrence.controller) is NativeProcessRefValue
    assert type(publication.observed_interval) is NativeIntervalValue
    assert type(publication.occurrence.key.selection) is HostSelectionHandle
    assert type(publication.occurrence.admission_boundary.roots[0].expected_existing_object) is NativeRootObjectValue
    assert type(publication.occurrence.targets[0]) is FutureSubjectRecord
    assert type(publication.occurrence.source_epoch) is N3SourceEpoch


@pytest.mark.parametrize("boundary", _TEST_BOUNDARIES)
def test_verifier_over_store_accepts_the_published_cohort(world: StoreWorld, boundary: Any) -> None:
    assert world.verify(world.reference, boundary) is None


def test_store_reads_never_change_the_tree(world: StoreWorld) -> None:
    def listing() -> list[tuple[str, int, int]]:
        return sorted(
            (str(path.relative_to(world.root)), path.stat().st_size, path.stat().st_mtime_ns)
            for path in world.root.rglob("*")
        )

    before = listing()
    world.read(world.reference)
    world.read(replace(world.reference, digest="0" * 64))
    assert listing() == before


def test_module_never_writes_and_imports_no_configs_or_service() -> None:
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    forbidden = {"O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND", "write", "mkdir",
                 "makedirs", "rename", "replace", "unlink", "remove", "rmdir", "symlink", "mkfifo"}
    # The only opens are os.open with the module's two read-only flag sets.
    assert not any(isinstance(node, ast.Name) and node.id == "open" for node in ast.walk(tree))
    assert names & forbidden == set()
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
    assert not any(name == "configs" or name.startswith("configs.") for name in imported)
    assert "temper_ai.p3_authority.service" not in imported
    assert "temper_ai.p3_authority._providers" not in imported


def test_size_limit_equals_the_r2_receiving_limit() -> None:
    binding = _load_module_from_path("ops_host_binding", _ARCH_BIN / "ops_host_binding.py")
    assert MAX_SNAPSHOT_BYTES == binding.MAX_DOCUMENT == 16777216


# ---------------------------------------------------------------------------
# Lookup is by (digest, selection_revision) only
# ---------------------------------------------------------------------------


def test_path_never_finds_a_file(world: StoreWorld) -> None:
    other_document = _document(world)
    other_document["complete_publication"] = False
    other = world.put(_dump(other_document))
    # The path names the other cohort's file; lookup still goes by digest.
    pointing = replace(world.reference, path=str(world.cohorts / f"{other.digest}.json"))
    read = world.read(pointing)
    assert read.refusal is None
    assert read.cohort == world.cohort
    assert read.snapshot_reference.path == pointing.path
    # A digest with no snapshot is absent, whatever existing file the path names.
    absent = replace(world.reference, digest=_sha("no-such-cohort"), path=pointing.path)
    assert world.read(absent).refusal is Refusal.SNAPSHOT_ABSENT


def test_same_digest_other_selection_revision_is_refused(world: StoreWorld) -> None:
    read = world.read(world.reference, "sel-rev-other")
    assert read.refusal is Refusal.SELECTION_REVISION_MISMATCH
    assert read.cohort is None and read.snapshot_reference is None


def test_same_selection_other_digest_is_absent(world: StoreWorld) -> None:
    assert world.read(replace(world.reference, digest=_sha("other-digest"))).refusal is Refusal.SNAPSHOT_ABSENT


def test_revision_is_compared_exactly_without_normalization(world: StoreWorld) -> None:
    for revision in (f" {world.selection_revision}", world.selection_revision.upper()):
        assert world.read(world.reference, revision).refusal is Refusal.SELECTION_REVISION_MISMATCH


# ---------------------------------------------------------------------------
# One case per refusal; each also refuses through the verifier
# ---------------------------------------------------------------------------

Case = Callable[[StoreWorld], tuple[Any, Any]]


def _same(world: StoreWorld, reference: Any) -> tuple[Any, Any]:
    return reference, world.selection_revision


def _case_digest_uppercase(world: StoreWorld) -> tuple[Any, Any]:
    return _same(world, replace(world.reference, digest=world.reference.digest.upper()))


def _case_digest_short(world: StoreWorld) -> tuple[Any, Any]:
    return _same(world, replace(world.reference, digest=world.reference.digest[:63]))


def _case_digest_not_str(world: StoreWorld) -> tuple[Any, Any]:
    return _same(world, _object_reference(world, digest=None))


def _case_selection_revision_empty(world: StoreWorld) -> tuple[Any, Any]:
    return world.reference, ""


def _case_selection_revision_not_str(world: StoreWorld) -> tuple[Any, Any]:
    return world.reference, 1


def _case_reference_length_bool(world: StoreWorld) -> tuple[Any, Any]:
    return _same(world, replace(world.reference, length=True))


def _object_reference(world: StoreWorld, **changes: Any) -> Any:
    """A reference-shaped object that skips ImmutableReferenceRecord's own checks."""
    fields = {
        "path": world.reference.path,
        "digest": world.reference.digest,
        "length": world.reference.length,
        "revision": world.reference.revision,
    }
    fields.update(changes)
    return type("Reference", (), fields)()


def _case_reference_path_empty(world: StoreWorld) -> tuple[Any, Any]:
    return _same(world, _object_reference(world, path=""))


def _case_reference_revision_empty(world: StoreWorld) -> tuple[Any, Any]:
    return _same(world, _object_reference(world, revision=""))


def _case_reference_length_zero(world: StoreWorld) -> tuple[Any, Any]:
    return _same(world, _object_reference(world, length=0))


def _case_root_removed(world: StoreWorld) -> tuple[Any, Any]:
    moved = world.root.with_name("moved-away")
    world.root.rename(moved)
    return _same(world, world.reference)


def _case_root_now_symlink(world: StoreWorld) -> tuple[Any, Any]:
    moved = world.root.with_name("moved-away")
    world.root.rename(moved)
    world.root.symlink_to(moved, target_is_directory=True)
    return _same(world, world.reference)


def _case_cohorts_directory_absent(world: StoreWorld) -> tuple[Any, Any]:
    world.cohorts.rename(world.root / "elsewhere")
    return _same(world, world.reference)


def _case_cohorts_directory_symlink(world: StoreWorld) -> tuple[Any, Any]:
    real = world.root.parent / "real-cohorts"
    world.cohorts.rename(real)
    world.cohorts.symlink_to(real, target_is_directory=True)
    return _same(world, world.reference)


def _case_cohorts_not_directory(world: StoreWorld) -> tuple[Any, Any]:
    world.cohorts.rename(world.root.parent / "kept-cohorts")
    world.cohorts.write_bytes(b"not a directory")
    return _same(world, world.reference)


def _case_snapshot_absent(world: StoreWorld) -> tuple[Any, Any]:
    (world.cohorts / f"{world.reference.digest}.json").unlink()
    return _same(world, world.reference)


def _case_snapshot_symlink(world: StoreWorld) -> tuple[Any, Any]:
    leaf = world.cohorts / f"{world.reference.digest}.json"
    target = world.root.parent / "outside.json"
    leaf.rename(target)
    leaf.symlink_to(target)
    return _same(world, world.reference)


def _case_snapshot_directory(world: StoreWorld) -> tuple[Any, Any]:
    leaf = world.cohorts / f"{world.reference.digest}.json"
    leaf.unlink()
    leaf.mkdir()
    return _same(world, world.reference)


def _case_snapshot_fifo(world: StoreWorld) -> tuple[Any, Any]:
    leaf = world.cohorts / f"{world.reference.digest}.json"
    leaf.unlink()
    os.mkfifo(leaf)
    return _same(world, world.reference)


def _padded(world: StoreWorld, size: int) -> bytes:
    return world.raw + b" " * (size - len(world.raw))


def _case_snapshot_too_large(world: StoreWorld) -> tuple[Any, Any]:
    return _same(world, world.put(_padded(world, MAX_SNAPSHOT_BYTES + 1)))


def _case_length_mismatch(world: StoreWorld) -> tuple[Any, Any]:
    return _same(world, replace(world.reference, length=world.reference.length + 1))


def _tampered_same_length(world: StoreWorld) -> bytes:
    kit = world.expectations.kit_id.encode("utf-8")
    tampered = world.raw.replace(kit, kit[:-1] + (b"X" if kit[-1:] != b"X" else b"Y"), 1)
    assert tampered != world.raw and len(tampered) == len(world.raw)
    return tampered


def _case_digest_mismatch(world: StoreWorld) -> tuple[Any, Any]:
    (world.cohorts / f"{world.reference.digest}.json").write_bytes(_tampered_same_length(world))
    return _same(world, world.reference)


def _case_json_not_utf8(world: StoreWorld) -> tuple[Any, Any]:
    return _same(world, world.put(world.raw.replace(b'"members"', b'"m\xffmbers"', 1)))


def _duplicate_kit_id(world: StoreWorld) -> bytes:
    return b'{"kit_id":"duplicate-first",' + world.raw[1:]


def _case_json_duplicate_key(world: StoreWorld) -> tuple[Any, Any]:
    return _same(world, world.put(_duplicate_kit_id(world)))


def _case_json_nan(world: StoreWorld) -> tuple[Any, Any]:
    return _same(world, world.put(world.raw.replace(b'"complete_publication":true', b'"complete_publication":NaN', 1)))


def _case_json_infinity(world: StoreWorld) -> tuple[Any, Any]:
    return _same(world, world.put(world.raw.replace(b'"complete_publication":true', b'"complete_publication":Infinity', 1)))


def _case_json_array(world: StoreWorld) -> tuple[Any, Any]:
    return _same(world, world.put(b"[" + world.raw + b"]"))


def _case_json_trailing_garbage(world: StoreWorld) -> tuple[Any, Any]:
    return _same(world, world.put(world.raw + b"x"))


def _with(world: StoreWorld, change: Callable[[dict[str, Any]], None]) -> tuple[Any, Any]:
    document = _document(world)
    change(document)
    return _same(world, world.put(_dump(document)))


def _case_schema_wrong(world: StoreWorld) -> tuple[Any, Any]:
    return _with(world, lambda d: d.update(schema="qa-p3-publication-cohort-snapshot/2"))


def _case_schema_missing(world: StoreWorld) -> tuple[Any, Any]:
    return _with(world, lambda d: d.pop("schema"))


def _case_shape_extra_key(world: StoreWorld) -> tuple[Any, Any]:
    return _with(world, lambda d: d.update(note="extra"))


def _case_shape_missing_key(world: StoreWorld) -> tuple[Any, Any]:
    return _with(world, lambda d: d.pop("final_sha256"))


def _case_shape_complete_publication_int(world: StoreWorld) -> tuple[Any, Any]:
    return _with(world, lambda d: d.update(complete_publication=1))


def _case_shape_members_object(world: StoreWorld) -> tuple[Any, Any]:
    return _with(world, lambda d: d.update(members={}))


def _case_shape_kit_id_empty(world: StoreWorld) -> tuple[Any, Any]:
    return _with(world, lambda d: d.update(kit_id=""))


def _case_embedded_revision_other(world: StoreWorld) -> tuple[Any, Any]:
    return _with(world, lambda d: d.update(selection_revision="sel-rev-other"))


def _case_member_unknown_leg(world: StoreWorld) -> tuple[Any, Any]:
    return _with(world, lambda d: d["members"][0].update(leg="firefox"))


def _case_member_extra_key(world: StoreWorld) -> tuple[Any, Any]:
    return _with(world, lambda d: d["members"][0].update(note="extra"))


def _case_member_empty_witness(world: StoreWorld) -> tuple[Any, Any]:
    return _with(world, lambda d: _first_member_publication(d)["occurrence"]["witness"].update(witness_reference=""))


def _case_member_sequence_bool(world: StoreWorld) -> tuple[Any, Any]:
    return _with(world, lambda d: d["members"][2]["publication"]["occurrence"]["key"].update(sequence=True))


def _case_member_unknown_identity_kind(world: StoreWorld) -> tuple[Any, Any]:
    return _with(
        world,
        lambda d: _first_member_publication(d)["occurrence"]["admission_boundary"]["actor"]["identity"].update(
            identity_kind="container"
        ),
    )


def _case_member_row_without_controller(world: StoreWorld) -> tuple[Any, Any]:
    return _with(world, lambda d: d["members"][2]["publication"]["occurrence"].update(controller=None))


def _case_member_epoch_tampered(world: StoreWorld) -> tuple[Any, Any]:
    return _with(world, lambda d: _first_member_publication(d)["occurrence"]["source_epoch"].update(extra="x"))


def _case_member_duplicate_right(world: StoreWorld) -> tuple[Any, Any]:
    return _with(
        world,
        lambda d: _first_member_publication(d)["occurrence"]["admission_boundary"]["roots"][0].update(
            required_rights=["read", "read"]
        ),
    )


REFUSAL_CASES: dict[str, tuple[Case, Refusal]] = {
    "digest_uppercase": (_case_digest_uppercase, Refusal.DIGEST_MALFORMED),
    "digest_short": (_case_digest_short, Refusal.DIGEST_MALFORMED),
    "digest_not_str": (_case_digest_not_str, Refusal.DIGEST_MALFORMED),
    "selection_revision_empty": (_case_selection_revision_empty, Refusal.SELECTION_REVISION_MALFORMED),
    "selection_revision_not_str": (_case_selection_revision_not_str, Refusal.SELECTION_REVISION_MALFORMED),
    "reference_length_bool": (_case_reference_length_bool, Refusal.REFERENCE_MALFORMED),
    "reference_length_zero": (_case_reference_length_zero, Refusal.REFERENCE_MALFORMED),
    "reference_path_empty": (_case_reference_path_empty, Refusal.REFERENCE_MALFORMED),
    "reference_revision_empty": (_case_reference_revision_empty, Refusal.REFERENCE_MALFORMED),
    "root_removed": (_case_root_removed, Refusal.ROOT_UNAVAILABLE),
    "root_now_symlink": (_case_root_now_symlink, Refusal.ROOT_UNAVAILABLE),
    "cohorts_directory_absent": (_case_cohorts_directory_absent, Refusal.SNAPSHOT_ABSENT),
    "cohorts_directory_symlink": (_case_cohorts_directory_symlink, Refusal.COHORTS_DIRECTORY_SYMLINK),
    "cohorts_not_directory": (_case_cohorts_not_directory, Refusal.COHORTS_DIRECTORY_INVALID),
    "snapshot_absent": (_case_snapshot_absent, Refusal.SNAPSHOT_ABSENT),
    "snapshot_symlink": (_case_snapshot_symlink, Refusal.SNAPSHOT_SYMLINK),
    "snapshot_directory": (_case_snapshot_directory, Refusal.SNAPSHOT_NOT_REGULAR),
    "snapshot_fifo": (_case_snapshot_fifo, Refusal.SNAPSHOT_NOT_REGULAR),
    "snapshot_too_large": (_case_snapshot_too_large, Refusal.SNAPSHOT_TOO_LARGE),
    "length_mismatch": (_case_length_mismatch, Refusal.LENGTH_MISMATCH),
    "digest_mismatch": (_case_digest_mismatch, Refusal.DIGEST_MISMATCH),
    "json_not_utf8": (_case_json_not_utf8, Refusal.JSON_INVALID),
    "json_duplicate_key": (_case_json_duplicate_key, Refusal.JSON_INVALID),
    "json_nan": (_case_json_nan, Refusal.JSON_INVALID),
    "json_infinity": (_case_json_infinity, Refusal.JSON_INVALID),
    "json_array": (_case_json_array, Refusal.JSON_INVALID),
    "json_trailing_garbage": (_case_json_trailing_garbage, Refusal.JSON_INVALID),
    "schema_wrong": (_case_schema_wrong, Refusal.SCHEMA_MISMATCH),
    "schema_missing": (_case_schema_missing, Refusal.SCHEMA_MISMATCH),
    "shape_extra_key": (_case_shape_extra_key, Refusal.SHAPE_INVALID),
    "shape_missing_key": (_case_shape_missing_key, Refusal.SHAPE_INVALID),
    "shape_complete_publication_int": (_case_shape_complete_publication_int, Refusal.SHAPE_INVALID),
    "shape_members_object": (_case_shape_members_object, Refusal.SHAPE_INVALID),
    "shape_kit_id_empty": (_case_shape_kit_id_empty, Refusal.SHAPE_INVALID),
    "embedded_revision_other": (_case_embedded_revision_other, Refusal.SELECTION_REVISION_MISMATCH),
    "member_unknown_leg": (_case_member_unknown_leg, Refusal.MEMBER_INVALID),
    "member_extra_key": (_case_member_extra_key, Refusal.MEMBER_INVALID),
    "member_empty_witness": (_case_member_empty_witness, Refusal.MEMBER_INVALID),
    "member_sequence_bool": (_case_member_sequence_bool, Refusal.MEMBER_INVALID),
    "member_unknown_identity_kind": (_case_member_unknown_identity_kind, Refusal.MEMBER_INVALID),
    "member_row_without_controller": (_case_member_row_without_controller, Refusal.MEMBER_INVALID),
    "member_epoch_tampered": (_case_member_epoch_tampered, Refusal.MEMBER_INVALID),
    "member_duplicate_right": (_case_member_duplicate_right, Refusal.MEMBER_INVALID),
}


def test_every_refusal_code_has_a_case() -> None:
    assert {code for _, code in REFUSAL_CASES.values()} == set(Refusal) - {Refusal.SNAPSHOT_UNREADABLE}


@pytest.mark.parametrize("name", sorted(REFUSAL_CASES))
def test_refusal_case_returns_none_with_its_code(world: StoreWorld, name: str) -> None:
    case, code = REFUSAL_CASES[name]
    reference, revision = case(world)
    read = world.read(reference, revision)
    assert read.refusal is code
    assert read.cohort is None and read.snapshot_reference is None
    assert world.store.load_cohort(reference, selection_revision=revision) is None
    assert world.store.load_cohort_snapshot(reference, selection_revision=revision) is None


@pytest.mark.parametrize("name", sorted(REFUSAL_CASES))
def test_refusal_case_through_verifier_is_qa_receiving_missing(world: StoreWorld, name: str) -> None:
    case, _ = REFUSAL_CASES[name]
    reference, revision = case(world)
    selected_job = world.rig.running_job
    if revision != world.selection_revision:
        selected_job = replace(selected_job, selection_revision=revision)
    verifier = PublicationCohortQAReceivingVerifier(cohort_source=world.store, expectations=world.expectations)
    for boundary in _TEST_BOUNDARIES:
        refusal = verifier.verify_qa_receiving(
            replace(world.qa_receiving, receiving_reference=reference),
            selected_job=selected_job,
            boundary=boundary,
        )
        assert refusal is not None and refusal.code is RefusalCode.QA_RECEIVING_MISSING


def test_snapshot_of_exactly_the_limit_is_accepted(world: StoreWorld) -> None:
    reference = world.put(_padded(world, MAX_SNAPSHOT_BYTES))
    read = world.read(reference)
    assert read.refusal is None and read.cohort == world.cohort
    assert read.snapshot_reference.length == MAX_SNAPSHOT_BYTES


def test_unreadable_snapshot_is_refused(world: StoreWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_read(descriptor: int, size: int) -> bytes:
        raise OSError("simulated EIO")

    monkeypatch.setattr(store_module.os, "read", failing_read)
    assert world.read(world.reference).refusal is Refusal.SNAPSHOT_UNREADABLE


# ---------------------------------------------------------------------------
# Constructor fails loud
# ---------------------------------------------------------------------------


def test_constructor_rejects_unusable_roots(tmp_path: Path) -> None:
    directory = tmp_path / "root"
    directory.mkdir()
    file_root = tmp_path / "file"
    file_root.write_bytes(b"x")
    link = tmp_path / "link"
    link.symlink_to(directory, target_is_directory=True)
    for bad in ("relative/root", str(tmp_path / "missing"), str(file_root), str(link)):
        with pytest.raises(ValueError):
            FilePublicationCohortStore(bad)
    for wrong_type in (os.fsencode(str(directory)), 42, None):
        with pytest.raises(TypeError):
            FilePublicationCohortStore(wrong_type)  # type: ignore[arg-type]
    assert FilePublicationCohortStore(directory).root == str(directory)


def test_encoder_refuses_test_only_carriers(world: StoreWorld) -> None:
    from tests.test_p3_authority._composition_fixtures import WITNESS_1

    member = world.cohort.members[0]
    bad_occurrence = replace(member.publication.occurrence, witness=WITNESS_1)
    bad_member = replace(member, publication=replace(member.publication, occurrence=bad_occurrence))
    bad = replace(world.cohort, members=(bad_member,))
    with pytest.raises(TypeError):
        encode_cohort_snapshot(bad, selection_revision=world.selection_revision)
    with pytest.raises(ValueError):
        encode_cohort_snapshot(world.cohort, selection_revision="")
    assert SNAPSHOT_SCHEMA in world.raw.decode("utf-8")


# ---------------------------------------------------------------------------
# Bites: one per guard; its own case stops being refused with its code
# ---------------------------------------------------------------------------


def _always(value: bool) -> Callable[..., bool]:
    return lambda *args, **kwargs: value


BITES: dict[str, tuple[str, Callable[[pytest.MonkeyPatch], None], bool]] = {
    # name -> (case, how to turn the guard off, cohort loads once the guard is off)
    "digest_well_formed": ("digest_uppercase", lambda m: m.setattr(store_module, "_digest_is_well_formed", _always(True)), False),
    "selection_revision_well_formed": (
        "selection_revision_empty",
        lambda m: m.setattr(store_module, "_selection_revision_is_well_formed", _always(True)),
        False,
    ),
    "reference_well_formed": (
        "reference_revision_empty",
        lambda m: m.setattr(store_module, "_reference_is_well_formed", _always(True)),
        False,
    ),
    "cohorts_directory_nofollow": (
        "cohorts_directory_symlink",
        lambda m: m.setattr(store_module, "_DIRECTORY_OPEN_FLAGS", os.O_RDONLY | os.O_DIRECTORY),
        True,
    ),
    "snapshot_nofollow": (
        "snapshot_symlink",
        lambda m: m.setattr(store_module, "_SNAPSHOT_OPEN_FLAGS", os.O_RDONLY | os.O_NONBLOCK),
        True,
    ),
    "regular_file": ("snapshot_fifo", lambda m: m.setattr(store_module, "_is_regular_file", _always(True)), False),
    "size_limit": ("snapshot_too_large", lambda m: m.setattr(store_module, "_within_size_limit", _always(True)), True),
    "length_matches": ("length_mismatch", lambda m: m.setattr(store_module, "_length_matches", _always(True)), True),
    "digest_matches": ("digest_mismatch", lambda m: m.setattr(store_module, "_digest_matches", _always(True)), True),
    "strict_json": (
        "json_duplicate_key",
        lambda m: m.setattr(store_module, "_strict_json_object", lambda raw: json.loads(raw)),
        True,
    ),
    "schema_matches": ("schema_wrong", lambda m: m.setattr(store_module, "_schema_matches", _always(True)), True),
    "top_level_shape": ("shape_extra_key", lambda m: m.setattr(store_module, "_top_level_shape_is_valid", _always(True)), True),
    "embedded_revision": (
        "embedded_revision_other",
        lambda m: m.setattr(store_module, "_selection_revision_matches", _always(True)),
        True,
    ),
    "member_exact_keys": (
        "member_extra_key",
        lambda m: m.setattr(store_module, "_has_exact_keys", lambda value, keys: keys <= value.keys()),
        True,
    ),
    "member_leg": ("member_unknown_leg", lambda m: m.setattr(store_module, "_LEGS", ("chromium", "webkit", "host_row", "firefox")), True),
    "carrier_text": (
        "member_empty_witness",
        lambda m: m.setattr(store_module, "_is_text", lambda value: type(value) is str),
        True,
    ),
    "unique_rights": (
        "member_duplicate_right",
        lambda m: m.setattr(store_module, "_decode_rights", lambda value: frozenset(value)),
        True,
    ),
}


def test_every_bite_names_a_known_case() -> None:
    assert {case for case, _, _ in BITES.values()} <= set(REFUSAL_CASES)


@pytest.mark.parametrize("name", sorted(BITES))
def test_bite_turning_one_guard_off_lets_its_case_through(
    world: StoreWorld, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    case_name, disable, loads = BITES[name]
    case, code = REFUSAL_CASES[case_name]
    reference, revision = case(world)
    assert world.read(reference, revision).refusal is code  # guard on: refused
    disable(monkeypatch)
    try:
        read = world.read(reference, revision)
    except (TypeError, ValueError):
        # Guard off: the bad input reaches code that assumed it; read now raises.
        assert not loads
        return
    assert read.refusal is not code  # guard off: its own code is gone
    if loads:
        # No later check masks it: the bad snapshot now loads as a cohort.
        assert read.refusal is None and read.cohort is not None

