"""Explicit, dormant composition bundle; not another profile/identity registry.

E supplies adapters over the SAME canonical configured authority and C1 custody.
There are no default profiles, services, dispatchers, runtime installs or keys.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .composition import PrivateComposition
from .contracts import CallerPrincipal, PrivateBinding, PrivateContextService
from .errors import PrivateDraftErrorCode as Code
from .errors import PrivateDraftFailure

if TYPE_CHECKING:
    from .authority import ProfileAuthority


@dataclass(frozen=True, repr=False)
class PrivateBoundary:
    service: PrivateContextService
    composition: PrivateComposition
    # Config readers only; never supplied by wire. C1 independently fences the
    # canonical profile and key source during effects. No parallel mutable map.
    preflight: Callable[[str], None]
    may: Callable[[str, str, str], bool]
    profile: Callable[[CallerPrincipal], ProfileAuthority]
    designates: Callable[[str], bool]
    # Preparation returns a post-commit dispatcher. It must check mode support
    # WITHOUT effects; absent support refuses before queue/binding. E joins real
    # agent execution, not a fake production success callback.
    prepare_dispatch: Callable[[str], Callable[[PrivateBinding], None]]

    def __reduce_ex__(self, protocol):
        raise TypeError("private serialization forbidden")


# One explicit composition root per process, not a second authority registry.
# Merely importing/registering routes does not install a boundary. E owns the
# production join; tests inject recording fakes and restore this reference.
_boundary: PrivateBoundary | None = None


def configure_private_boundary(boundary: PrivateBoundary | None) -> None:
    global _boundary
    _boundary = boundary


def get_private_boundary() -> PrivateBoundary | None:
    return _boundary


def require_boundary(boundary: PrivateBoundary | None) -> PrivateBoundary:
    if boundary is None or boundary.service is None or boundary.composition is None:
        raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
    return boundary


def caller_boundary(boundary: PrivateBoundary | None) -> PrivateBoundary:
    from temper_ai.api.private_identity import verified_named_caller

    name = verified_named_caller()
    configured = require_boundary(boundary)
    # Missing caller assignments/profile/schema/authority refuses before body
    # consumption. Ref-specific scope is rechecked after strict envelope decode.
    configured.preflight(name)
    return configured


def authorize_scope(boundary: PrivateBoundary, owner: str, namespace: str,
                    profile: str) -> CallerPrincipal:
    from temper_ai.api.private_identity import issue_private_caller

    return issue_private_caller(owner, namespace, profile, boundary.may)
