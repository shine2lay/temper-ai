"""C2 declaration contract only; no custody/transaction/runner proof from these fakes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError
from typing import get_args, get_type_hints

import pytest
from sqlmodel import Session

from temper_ai.private_context import composition
from temper_ai.private_context.authority import RunAuthority
from temper_ai.private_context.contracts import PrivateBinding

from .ipd1 import require
from .test_contracts import binding


def test_combined_new_retry_bootstrap_callback_contract() -> None:
    """Exercise the reconciled callback vocabulary together, not concrete C1 atomicity."""
    effects = []
    bound = binding()
    # No engine/session commit and no runner is claimed by this declaration test.
    with Session() as session:
        def queue(given: Session, execution_id: str) -> None:
            require(given is session and execution_id == bound.execution_id)
            effects.append("queued")

        queue(session, bound.execution_id)
        new = composition.BindingAdmission(bound, True)
        retry = composition.BindingAdmission(new.binding, False)
        for admission in (new, retry):
            if admission.created:
                effects.append("dispatch")
        require(effects == ["queued", "dispatch"] and retry.binding is new.binding)
        require("context_ref" not in repr(new))
        with pytest.raises(FrozenInstanceError):
            new.created = False  # type: ignore[misc]
        with pytest.raises(TypeError):
            composition.PrivateComposition()  # type: ignore[misc]
        with pytest.raises(TypeError):
            composition.BindingAdmission()  # type: ignore[call-arg]

    # Canonical imports, not a locally invented authority/binding record.
    hints = get_type_hints(composition.PrivateComposition.bind_and_queue_in)
    require(hints["return"] is composition.BindingAdmission)
    require(hints["queue"] == Callable[[Session, str], None])
    hints = get_type_hints(composition.PrivateComposition.worker_bootstrap_in)
    require(hints["return"] is RunAuthority)
    require(hints["effect"] == Callable[[Session, RunAuthority], None])
    hints = get_type_hints(composition.PrivateComposition.lifecycle_in)
    require(hints["effect"] == Callable[[Session, PrivateBinding], None])
    require(set(get_args(hints["action"])) == {"resume", "fork", "cancel"})


@pytest.mark.parametrize("method,names", [
    ("caller_for_context", ["self", "context_ref", "authorize"]),
    ("binding_for_run", ["self", "execution_id", "authorize"]),
    ("bind_and_queue_in", ["self", "session", "caller", "context_ref", "context_version",
                           "execution_id", "profile_revision", "queue"]),
    ("lifecycle_in", ["self", "session", "caller", "execution_id", "action", "effect"]),
    ("worker_bootstrap_in", ["self", "session", "execution_id", "effect"]),
    ("worker_current_in", ["self", "session", "principal"]),
    ("worker_lease", ["self", "principal", "lease_id"]),
    ("worker_reservation", ["self", "principal", "invocation_id", "attempt_id"]),
])
def test_exact_composition_signature(method: str, names: list[str]) -> None:
    import inspect

    require(list(inspect.signature(getattr(composition.PrivateComposition, method)).parameters) == names)
