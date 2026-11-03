"""The shared linked-receipt rules, one check per case (each check's bite).

``temper_ai.p3_authority.linked_receipt_rules`` is used by the service, the
test double and the conformance kit; there other checks overlap these, so each
rule is held here on its own.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from temper_ai.p3_authority.linked_receipt_rules import (
    continuation_predecessor_refusal,
    exact_receipt_equal,
    is_successful_row_receipt,
    linked_predecessor_mismatch,
)
from temper_ai.p3_authority.refusals import RefusalCode
from tests.test_p3_authority._composition_fixtures import (
    make_populated_test_rig,
    populate_boundary_happy_path_observations,
)


@pytest.fixture(scope="module")
def obs() -> dict[str, Any]:
    rig = make_populated_test_rig()
    return populate_boundary_happy_path_observations(
        rig, predecessor_row="D-1", counted_row="D-5"
    )


def _subclass_of(record: Any, *, equal_to_anything: bool) -> Any:
    """A copy of ``record`` as a subclass; optionally one whose ``==`` is always True."""
    record_class = type(record)
    members: dict[str, Any] = {"__slots__": ()}
    if equal_to_anything:
        members["__eq__"] = lambda self, other: True
        members["__hash__"] = None
    subclass = type(f"Lookalike{record_class.__name__}", (record_class,), members)
    return subclass(
        **{name: getattr(record, name) for name in record_class.__dataclass_fields__}
    )


# -- exact_receipt_equal ------------------------------------------------------


def test_exact_receipt_equal_needs_the_exact_class_on_both_sides(obs: dict[str, Any]) -> None:
    receipt = obs["pred_prov"]
    assert exact_receipt_equal(receipt, replace(receipt))
    assert not exact_receipt_equal(receipt, obs["prov"])
    assert not exact_receipt_equal(None, None)
    lookalike = _subclass_of(receipt, equal_to_anything=False)
    assert not exact_receipt_equal(lookalike, lookalike)
    # A subclass whose == is always True is asked first from either side, so
    # only the type checks refuse it: first argument, then second.
    always_equal = _subclass_of(receipt, equal_to_anything=True)
    assert receipt == always_equal and always_equal == receipt
    assert not exact_receipt_equal(always_equal, receipt)
    assert not exact_receipt_equal(receipt, always_equal)


# -- linked_predecessor_mismatch (ruling C2) ----------------------------------


def test_linked_predecessor_must_match_exactly_both_ways(obs: dict[str, Any]) -> None:
    receipt = obs["pred_prov"]
    assert linked_predecessor_mismatch(None, None) is None
    assert linked_predecessor_mismatch(receipt, replace(receipt)) is None
    assert linked_predecessor_mismatch(None, receipt) is RefusalCode.PRIOR_MISSING
    assert linked_predecessor_mismatch(receipt, None) is RefusalCode.PRIOR_UNVERIFIED
    assert linked_predecessor_mismatch(receipt, obs["prov"]) is RefusalCode.PRIOR_UNVERIFIED


# -- is_successful_row_receipt ------------------------------------------------


def _publication(receipt: Any, **changes: Any) -> Any:
    return replace(receipt, raw_publication=replace(receipt.raw_publication, **changes))


def _occurrence(receipt: Any, **changes: Any) -> Any:
    occurrence = replace(receipt.raw_publication.occurrence, **changes)
    return _publication(receipt, occurrence=occurrence)


_NOT_SUCCESSFUL = {
    "receipt-of-another-class": lambda o: _subclass_of(
        o["pred_prov"], equal_to_anything=False
    ),
    "key-of-another-class": lambda o: replace(
        o["pred_prov"],
        operation_key=_subclass_of(o["pred_key"], equal_to_anything=False),
    ),
    "incomplete": lambda o: replace(o["pred_prov"], state="incomplete"),
    "failed-outcome": lambda o: _publication(o["pred_prov"], outcome="app-failure"),
    "occurrence-failed": lambda o: _occurrence(o["pred_prov"], state="failed"),
    "occurrence-of-another-key": lambda o: _occurrence(o["pred_prov"], key=o["req_id"]),
}


def test_a_successful_row_receipt_is_successful(obs: dict[str, Any]) -> None:
    assert is_successful_row_receipt(obs["pred_prov"])


@pytest.mark.parametrize("kind", sorted(_NOT_SUCCESSFUL))
def test_each_failed_part_makes_a_receipt_unsuccessful(
    obs: dict[str, Any], kind: str
) -> None:
    assert not is_successful_row_receipt(_NOT_SUCCESSFUL[kind](obs))


# -- continuation_predecessor_refusal (REQUIRED_PREDECESSOR_ROW) --------------


def _predecessor_key(o: dict[str, Any], **changes: Any) -> Any:
    key = replace(o["pred_key"], **changes)
    return replace(_occurrence(o["pred_prov"], key=key), operation_key=key)


_CONTINUATIONS = {
    # name: (counted key, predecessor, answer)
    "not-a-continuation-row": (
        lambda o: replace(o["req_id"], row="D-1"), lambda o: None, None
    ),
    "good": (lambda o: o["req_id"], lambda o: o["pred_prov"], None),
    "no-predecessor": (lambda o: o["req_id"], lambda o: None, RefusalCode.PRIOR_MISSING),
    "unsuccessful-predecessor": (
        lambda o: o["req_id"],
        lambda o: replace(o["pred_prov"], state="incomplete"),
        RefusalCode.PRIOR_UNVERIFIED,
    ),
    "other-row": (
        lambda o: o["req_id"],
        lambda o: _predecessor_key(o, row="R-1i"),
        RefusalCode.PRIOR_UNVERIFIED,
    ),
    "other-revision": (
        lambda o: o["req_id"],
        lambda o: _predecessor_key(o, selection=o["sel_pre"]),
        RefusalCode.PRIOR_UNVERIFIED,
    ),
    "other-window": (
        lambda o: o["req_id"],
        lambda o: _predecessor_key(o, window_id="win-2"),
        RefusalCode.PRIOR_UNVERIFIED,
    ),
}


@pytest.mark.parametrize("kind", sorted(_CONTINUATIONS))
def test_continuation_rule_answers_each_case(obs: dict[str, Any], kind: str) -> None:
    key, predecessor, expected = _CONTINUATIONS[kind]
    assert continuation_predecessor_refusal(key(obs), predecessor(obs)) is expected
