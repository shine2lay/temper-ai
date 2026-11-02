"""Request-lifetime named-key provenance, not a second identity or rights store.

Caller labels and A's principal records are not credentials. The real HTTP edge
binds the exact Caller plus the verified header credential; C1's authority adapter
can check exact issued-object provenance here and then lock its configured rights.
Nothing is installed, provisioned or read at import time.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import NoReturn, SupportsIndex

from temper_ai.api.caller import Caller, current_caller
from temper_ai.private_context.contracts import CallerPrincipal
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.errors import PrivateDraftFailure

ScopeCheck = Callable[[str, str, str], bool]


class _VerifiedRequest:
    __slots__ = ("caller", "__key", "issued")

    def __init__(self, caller: Caller, key: str) -> None:
        self.caller = caller
        self.__key = key
        self.issued: list[CallerPrincipal] = []

    def __repr__(self) -> str:
        return "<verified private request>"

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        raise TypeError("private serialization forbidden")

    def current_name(self) -> str:
        from temper_ai.api.auth import identify_verified_named_key

        # Key revocation and request rebinding invalidate existing issued records.
        if current_caller() is not self.caller:
            raise PrivateDraftFailure(Code.UNAUTHENTICATED)
        name = identify_verified_named_key(self.__key)
        if name is None or name != self.caller.name:
            raise PrivateDraftFailure(Code.UNAUTHENTICATED)
        return name

    def close(self) -> None:
        self.__key = ""
        self.issued.clear()


_verified: ContextVar[_VerifiedRequest | None] = ContextVar("private_verified_request", default=None)


@contextmanager
def bound_verified_named_key(caller: Caller, key: str | None) -> Iterator[None]:
    """HTTP-edge hook: reverify a strict header key, never promote a Caller label.

    Trusted internal integrations may reuse this same credential verification,
    never acting_as(), to enter private operations. It is not a sandbox against
    arbitrary Python executing in the trusted server process.
    """
    from temper_ai.api.auth import identify_verified_named_key

    name = identify_verified_named_key(key) if key else None
    request = _VerifiedRequest(caller, key) if key and name is not None and name == caller.name else None
    token = _verified.set(request)
    try:
        yield
    finally:
        if request is not None:
            request.close()
        _verified.reset(token)


def verified_named_caller() -> str:
    """Current credential-backed principal name; guard off/record never relaxes it."""
    request = _verified.get()
    if request is None:
        raise PrivateDraftFailure(Code.UNAUTHENTICATED)
    return request.current_name()


def issue_private_caller(owner: str, namespace: str, profile: str, may: ScopeCheck) -> CallerPrincipal:
    """Issue for exact configured scope after verified named identity, not ref possession.

    `may` is the injected configured-rights reader, NOT a wire value or registry
    owned here. C1 still rechecks and fences authority in its own transaction.
    """
    name = verified_named_caller()
    if name != owner or may(name, namespace, profile) is not True:
        raise PrivateDraftFailure(Code.SCOPE_DENIED)
    principal = CallerPrincipal(principal_id=name, namespace=namespace, profile=profile,
                                provenance="verified_named_key")
    request = _verified.get()
    assert request is not None  # established above, no await/callback before identity read
    request.issued.append(principal)
    return principal


def require_private_caller_provenance(principal: CallerPrincipal) -> str:
    """C1 adapter hook: exact issued principal + still-current credential required."""
    name = verified_named_caller()
    request = _verified.get()
    if request is None or not any(item is principal for item in request.issued):
        raise PrivateDraftFailure(Code.UNAUTHENTICATED)
    if principal.principal_id != name:
        raise PrivateDraftFailure(Code.SCOPE_DENIED)
    return name
