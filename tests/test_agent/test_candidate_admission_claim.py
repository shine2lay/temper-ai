"""Real native claim use sites on owned synthetic fds. No provider or model.

FakeTransport is explicitly an isolated T2 protocol adapter, not durable proof.
These tests do not read actual Stage1 roots, keys, configs, prompts or answers.
"""
import copy
import os
from dataclasses import replace

import pytest

from temper_ai.agent import single_call_agent as native
from temper_ai.agent.admission_use import CandidateUse
from temper_ai.agent.single_call_agent import _Attempt
from temper_ai.config.admission_contract import (
    AdmissionRecord,
    AdmissionRefused,
    OpenedRoot,
)
from tests.test_stage.test_candidate_admission_consumers import NONCE, RUN, Rig, dump


def attempt(rig):
    return _Attempt(copy.deepcopy(rig.native), rig.native_context())


def test_same_owned_fd_claim_then_reads_no_reopen_and_consumed_claim(tmp_path, monkeypatch):
    rig = Rig(tmp_path)
    rig.prepare_only()
    state = attempt(rig)
    opened = []
    original = native._new_file

    def claim(fd, name):
        assert rig.transport.inside
        assert fd == state.root == state.candidate_root.root
        opened.append(os.fstat(fd).st_ino)
        return original(fd, name)
    monkeypatch.setattr(native, "_new_file", claim)
    try:
        state.claim_slot()
        assert state.claimed and len(opened) == 1
        root_fd = state.root
        # Hook borrowed rather than closing the descriptor.
        assert os.fstat(root_fd).st_ino == rig.receipt.value()["root"]["inode"]
        monkeypatch.setattr(os, "open", lambda *a, **k: pytest.fail("reopened after claim"))
        assert state.candidate_root.read(str(rig.prompt), 18) == b"synthetic fixture\n"
        assert state.candidate_root.read(str(rig.pricing), 65536) == b"{}"
    finally:
        state.close()
    monkeypatch.undo()
    second = attempt(rig)
    try:
        with pytest.raises(FileExistsError):
            second.claim_slot()
        assert not second.claimed
    finally:
        second.close()
    assert (rig.root / "A1.claim").exists()


@pytest.mark.parametrize("change", ["root-mode", "file-mode", "length", "hash", "file-inode", "symlink", "parent-symlink", "root-symlink", "hardlink"])
def test_actual_root_and_file_drift_refuses_before_exclusive_claim(tmp_path, monkeypatch, change):
    rig = Rig(tmp_path)
    rig.prepare_only()
    if change == "root-mode":
        rig.root.chmod(0o755)
    elif change == "file-mode":
        rig.prompt.chmod(0o644)
    elif change == "length":
        rig.prompt.write_bytes(b"different-size")
    elif change == "hash":
        rig.prompt.write_bytes(b"x" * 18)
    elif change == "file-inode":
        moved = rig.prompt.with_suffix(".old")
        rig.prompt.rename(moved)
        rig.prompt.write_bytes(moved.read_bytes())
        rig.prompt.chmod(0o600)
    elif change == "symlink":
        rig.prompt.unlink()
        rig.prompt.symlink_to(rig.pricing)
    elif change == "hardlink":
        os.link(rig.prompt, rig.root / "extra-link")
    elif change == "root-symlink":
        moved = tmp_path / "moved"
        rig.root.rename(moved)
        rig.root.symlink_to(moved, target_is_directory=True)
    else:
        moved = tmp_path.with_name(tmp_path.name + "-moved")
        tmp_path.rename(moved)
        tmp_path.symlink_to(moved, target_is_directory=True)
    monkeypatch.setattr(native, "_new_file", lambda *_: pytest.fail("claim allocated before drift refusal"))
    state = attempt(rig)
    try:
        with pytest.raises((AdmissionRefused, OSError)):
            state.claim_slot()
        assert not state.claimed
    finally:
        state.close()


@pytest.mark.parametrize("field,value", [("device", 0), ("inode", 0), ("uid", 999999), ("gid", 999999), ("mode", 0o644)])
def test_literal_identity_controls_refuse_actual_fstat(tmp_path, monkeypatch, field, value):
    rig = Rig(tmp_path)
    rig.prepare_only()
    # Change both synthetic trusted readiness and context to reach the use-site
    # fstat check. This is test input construction, not real custody evidence.
    r = rig.receipt.value()
    r["files"][0]["stat"][field] = value
    data = rig.use.record.value()
    data["readiness"] = [r]
    rig.use.record = rig.transport.record = AdmissionRecord(dump(data))
    monkeypatch.setattr(native, "_new_file", lambda *_: pytest.fail("claim allocated with wrong identity"))
    state = attempt(rig)
    try:
        with pytest.raises(AdmissionRefused):
            state.claim_slot()
    finally:
        state.close()


@pytest.mark.parametrize("change", ["config-extra", "config-type", "workspace", "run", "position", "nonce", "generation", "ready-missing", "fd-mismatch"])
def test_claim_checks_full_config_context_current_generation_and_borrowed_fd(tmp_path, monkeypatch, change):
    rig = Rig(tmp_path)
    rig.prepare_only()
    state = attempt(rig)
    if change == "config-extra":
        state.config["extra"] = None
    elif change == "config-type":
        state.config["single_call"]["prompt_bytes"] = True
    elif change == "workspace":
        state.context.workspace_path = "/other"
    elif change == "run":
        state.context.run_id = NONCE
    elif change == "position":
        state.context.admission = replace(state.context.admission, position_id="other")
    elif change == "ready-missing":
        state.context.admission = replace(state.context.admission, readiness=None)
    elif change == "fd-mismatch":
        original = native._CandidateRoot.verify
        wrong = os.open(str(tmp_path), os.O_RDONLY | os.O_DIRECTORY)

        def mismatch(root):
            opened = original(root)
            return OpenedRoot(wrong, opened.traversal)
        monkeypatch.setattr(native._CandidateRoot, "verify", mismatch)
    else:
        value = rig.transport.record.value()
        if change == "nonce":
            value["dispatch"]["dispatch_nonce"] = RUN
        else:
            value["dispatch"]["running_attempt"] = 2
        rig.transport.record = AdmissionRecord(dump(value))
    monkeypatch.setattr(native, "_new_file", lambda *_: pytest.fail("claim allocated before check"))
    try:
        with pytest.raises(AdmissionRefused):
            state.claim_slot()
        assert not state.claimed
    finally:
        state.close()
        if change == "fd-mismatch":
            os.close(wrong)


@pytest.mark.parametrize("mutation", ["type", "member", "deleted", "late-config", "late-context"])
def test_late_native_metadata_config_context_checks_inside_fence(tmp_path, monkeypatch, mutation):
    rig = Rig(tmp_path, native_metadata=True)
    rig.prepare_only()
    state = attempt(rig)

    def mutate():
        if mutation == "type":
            state.config["_KNOWN_FIELDS"] = sorted(state.config["_KNOWN_FIELDS"])
        elif mutation == "member":
            state.config["_KNOWN_FIELDS"] = frozenset({"name", "type"})
        elif mutation == "deleted":
            del state.config["_KNOWN_FIELDS"]
        elif mutation == "late-config":
            state.config["single_call"]["prompt_bytes"] = True
        else:
            state.context.workspace_path = "/unadmitted"
    rig.transport.mutate = mutate
    monkeypatch.setattr(native, "_new_file", lambda *_: pytest.fail("late mutation reached claim"))
    try:
        with pytest.raises(AdmissionRefused):
            state.claim_slot()
    finally:
        state.close()


def test_native_frozenset_guard_removal_bite(tmp_path, monkeypatch):
    rig = Rig(tmp_path, native_metadata=True)
    rig.prepare_only()
    state = attempt(rig)
    state.config["_KNOWN_FIELDS"] = sorted(state.config["_KNOWN_FIELDS"])
    try:
        with pytest.raises(AdmissionRefused):
            state.claim_slot()
    finally:
        state.close()
    monkeypatch.setattr(CandidateUse, "_metadata", lambda *a, **k: None)
    mutant = attempt(rig)
    mutant.config["_KNOWN_FIELDS"] = sorted(mutant.config["_KNOWN_FIELDS"])
    try:
        mutant.claim_slot()
        assert mutant.claimed
    finally:
        mutant.close()


def test_swap_after_open_is_checked_inside_generation_fence(tmp_path, monkeypatch):
    rig = Rig(tmp_path)
    rig.prepare_only()
    state = attempt(rig)
    old = rig.prompt.with_suffix(".old")

    def swap():
        rig.prompt.rename(old)
        rig.prompt.write_bytes(old.read_bytes())
        rig.prompt.chmod(0o600)
    rig.transport.mutate = swap
    monkeypatch.setattr(native, "_new_file", lambda *_: pytest.fail("late swap reached claim"))
    try:
        with pytest.raises(AdmissionRefused):
            state.claim_slot()
    finally:
        state.close()


def test_consumed_claim_survives_transaction_failure_without_provider_or_retry(tmp_path, monkeypatch):
    rig = Rig(tmp_path)
    rig.prepare_only()
    rig.transport.fail_commit = True
    monkeypatch.setattr(_Attempt, "call", lambda *_: pytest.fail("provider path after failed claim transaction"))
    state = attempt(rig)
    try:
        with pytest.raises(RuntimeError, match="synthetic_commit_failed"):
            state.claim_slot()
        assert state.claimed
    finally:
        state.close()
    assert (rig.root / "A1.claim").exists()
    rig.transport.fail_commit = False
    second = attempt(rig)
    try:
        with pytest.raises(FileExistsError):
            second.claim_slot()
    finally:
        second.close()


def test_guard_removal_bite_for_current_generation(tmp_path, monkeypatch):
    rig = Rig(tmp_path)
    rig.prepare_only()
    value = rig.transport.record.value()
    value["dispatch"]["dispatch_nonce"] = RUN
    rig.transport.record = AdmissionRecord(dump(value))
    state = attempt(rig)
    try:
        with pytest.raises(AdmissionRefused):
            state.claim_slot()
        assert not (rig.root / "A1.claim").exists()
    finally:
        state.close()
    # Deliberate in-memory mutant: dropping current-record validation permits the
    # stale synthetic transport callback to allocate. This is the guard's bite.
    monkeypatch.setattr(CandidateUse, "_current", lambda self, current: current)
    mutant = attempt(rig)
    try:
        mutant.claim_slot()
        assert mutant.claimed and (rig.root / "A1.claim").exists()
    finally:
        mutant.close()
