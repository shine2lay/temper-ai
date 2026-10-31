"""Adapt canonical M0 inputs to M1's deliberately path-local exact types.

This is type adaptation, not validation or persistence. M1 owns the complete
checker, its error recovery, and preparation/composition. Imports reuse M1's
existing module (including its schema load); operations open no sources.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from configs.architecture.bin import context_profile_clarification_caller as preparation
from temper_ai.clarifications.contracts import CallerInput, ContractRefusal, RefusalCode

__all__ = ["compose_supplement", "prepare"]


def _invoke(operation: Callable[..., dict[str, Any]], caller: CallerInput) -> dict[str, Any]:
    if type(caller) is not CallerInput:
        raise preparation.CallerRefusal("caller.type", "expected a canonical CallerInput")
    local = preparation.contracts
    try:
        adapted = local.CallerInput(
            stream=local.StreamKey(caller.stream.namespace, caller.stream.brief_sha256),
            original_text=caller.original_text,
            original_sha256=caller.original_sha256,
            candidate_json=caller.candidate_json,
            candidate_sha256=caller.candidate_sha256,
            candidate_ref=caller.candidate_ref,
            candidate_brief_sha256=caller.candidate_brief_sha256,
            prior_revision=caller.prior_revision,
            prior_record_json=caller.prior_record_json,
            prior_record_sha256=caller.prior_record_sha256,
            question_ids=caller.question_ids,
            source_authority_ref=caller.source_authority_ref,
            transport=local.TransportNamespace(caller.transport.transport, caller.transport.bot_id),
            chat_id=caller.chat_id,
            responder_policy_ref=caller.responder_policy_ref,
            affected_decisions=caller.affected_decisions,
        )
        return operation(adapted)
    except local.ContractRefusal as refusal:
        # The enum's values are the frozen M0 wire contract; enum classes differ.
        raise ContractRefusal(RefusalCode(refusal.code.value), refusal.guard, refusal.where) from refusal


def prepare(caller: CallerInput) -> dict[str, Any]:
    """Return M1's fresh display; complete checking precedes record/selection work."""
    return _invoke(preparation.prepare, caller)


def compose_supplement(caller: CallerInput) -> dict[str, Any]:
    """Return M1's separate original, supplement and current-source identities."""
    return _invoke(preparation.compose_supplement, caller)
