"""Explicit synthetic recording ports, NEVER production custody or durability proof."""
from __future__ import annotations

from datetime import UTC, datetime

from temper_ai.api.private_identity import require_private_caller_provenance
from temper_ai.private_context.authority import ProfileAuthority
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.private_json import encode_private
from temper_ai.private_context.runtime import PrivateBoundary
from temper_ai.private_context.wire import (
    VERSION,
    AcknowledgedReceipt,
    ContextReceipt,
    ContextStatus,
    DraftReceipt,
    RevokedReceipt,
    decode_result,
    decode_wire,
)

from . import ipd1
from .test_contracts import binding, receipt

SYNTHETIC_KEY = "synthetic-owner-credential"


class RecordingPorts:
    """Fake application reads; record only operation names, never private bytes."""
    def __init__(self):
        self.calls: list[str] = []
        self.allowed = True
        self.available = True
        self.bound = binding()
        self._registration = None
        self.registration_lost = False

    def preflight(self, name):
        if not self.available:
            raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
        if name != self.bound.owner_principal or not self.allowed:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)

    def may(self, name, namespace, profile):
        b = self.bound
        return self.allowed and (name, namespace, profile) == (b.owner_principal, b.namespace, b.profile)

    def profile(self, caller):
        require_private_caller_provenance(caller)
        b = self.bound
        return ProfileAuthority(owner_principal=b.owner_principal, namespace=b.namespace,
            profile=b.profile, profile_revision=b.profile_revision, workflow=b.workflow,
            workflow_revision=b.workflow_revision, node_path=b.node_path,
            schema=ipd1.schemas(), credential_deadline=datetime(2099, 1, 1, tzinfo=UTC))

    def boundary(self):
        return PrivateBoundary(service=self, composition=self, preflight=self.preflight,
            may=self.may, profile=self.profile, designates=lambda name: name == self.bound.workflow,
            prepare_dispatch=lambda mode: lambda bound: self.calls.append("dispatch"))

    def caller_for_context(self, context_ref, authorize):
        b = self.bound
        caller = authorize(b.owner_principal, b.namespace, b.profile)
        if context_ref != b.context_ref:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        return caller

    def register(self, caller, context):
        require_private_caller_provenance(caller)
        ipd1.schemas().validate_registration(context)
        if self.registration_lost:
            raise PrivateDraftFailure(Code.CONTEXT_LOST)
        if self._registration is not None and self._registration != context.to_private_json():
            raise PrivateDraftFailure(Code.CONTEXT_CONFLICT)
        self._registration = context.to_private_json()
        self.calls.append("register")
        return decode_wire(encode_private(dict(context_ref=ipd1.REF, context_version=1,
            expires_at=ipd1.EXPIRY, profile=self.bound.profile)), ContextReceipt)

    def status(self, caller, wanted):
        require_private_caller_provenance(caller)
        self.calls.append("status")
        return ContextStatus(context_ref=ipd1.REF, context_version=1,
                             execution_id=None, state="registered")

    def result(self, caller, wanted):
        require_private_caller_provenance(caller)
        self.calls.append("result")
        return decode_result(encode_private(dict(version=VERSION, execution_id=ipd1.RUN,
            draft_ref=ipd1.DRAFT, result_schema=self.bound.result_schema,
            draft=ipd1.draft().open_private())))

    def ack(self, caller, wanted):
        require_private_caller_provenance(caller)
        self.calls.append("ack")
        return AcknowledgedReceipt(version=VERSION, draft_ref=ipd1.DRAFT, state="acknowledged")

    def delete(self, caller, context_ref):
        require_private_caller_provenance(caller)
        self.calls.append("delete")
        return RevokedReceipt(context_ref=context_ref, state="revoked")

    def draft_receipt(self):
        return decode_wire(encode_private(receipt()), DraftReceipt)


def fake_key_sources(monkeypatch):
    """Exercise real lookup/middleware with synthetic key sources; never local key files."""
    from temper_ai.api import api_keys, auth

    monkeypatch.setattr(api_keys, "identify_key", lambda raw: None)
    monkeypatch.setattr(auth, "named_tokens", lambda: {"owner-1": SYNTHETIC_KEY,
                                                     "other-owner": "synthetic-other-credential"})
    monkeypatch.setattr(auth, "configured_token", lambda: "synthetic-shared-credential")
