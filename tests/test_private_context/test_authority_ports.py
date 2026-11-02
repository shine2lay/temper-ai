"""Canonical C1 declarations; no default verifier, profile or runner authority."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from inspect import signature

import pytest

from temper_ai.private_context.authority import (
    PrivateAuthority,
    ProfileAuthority,
    RunAuthority,
)

from . import ipd1


def test_authority_contract_combined_records_and_transaction_ports():
    profile = ProfileAuthority(
        owner_principal="owner-1", namespace="scope-1", profile="synthetic-reply-v1",
        profile_revision="profile-v1", workflow="synthetic-reply", workflow_revision="workflow-v1",
        node_path="writer", schema=ipd1.schemas(),
        credential_deadline=datetime(2099, 1, 1, tzinfo=UTC),
    )
    run = RunAuthority(profile, ipd1.RUN, 1, profile.credential_deadline, False)
    ipd1.require(run.profile is profile and run.runner_generation == 1)
    expected = {
        "caller_in": ("self", "session", "caller"),
        "binding_in": ("self", "session", "caller", "execution_id"),
        "run_in": ("self", "session", "principal"),
        "bootstrap_in": ("self", "session", "execution_id"),
    }
    for method, names in expected.items():
        ipd1.require(tuple(signature(getattr(PrivateAuthority, method)).parameters) == names)
    for record in (profile, run):
        ipd1.require(ipd1.scan({ipd1.Surface.ERROR: repr(record)}).clean)
    with pytest.raises(FrozenInstanceError):
        run.revoked = True
    with pytest.raises(FrozenInstanceError):
        profile.namespace = "foreign"


def test_authority_protocol_cannot_supply_default_success():
    with pytest.raises(TypeError):
        PrivateAuthority()
    with pytest.raises(TypeError):
        ProfileAuthority()
    with pytest.raises(TypeError):
        RunAuthority()
