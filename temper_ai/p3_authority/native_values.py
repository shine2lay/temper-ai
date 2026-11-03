"""Concrete immutable values of the native reference protocols in ``references``.

``NativeWitnessValue``, ``NativeProcessRefValue``, ``NativeIntervalValue`` and
``NativeRootObjectValue`` carry the plain strings of a ``NativeWitness``,
``NativeProcessRef``, ``NativeInterval`` and ``NativeRootObject``. The issuer
verifier, the selection snapshot and the QA publication store share them.

A value is data, never proof: holding one says nothing about who made it or
whether a service accepted it. This leaf imports only the standard library and
``references``, so a caller gets the values without cryptography, the issuer
or the admission contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from temper_ai.p3_authority.references import NativeWitness


@dataclass(frozen=True, slots=True)
class NativeWitnessValue:
    witness_reference: str

    @property
    def witness_registration(self) -> str:
        return self.witness_reference


@dataclass(frozen=True, slots=True)
class NativeProcessRefValue:
    process_registration: str

    @property
    def process_reference(self) -> str:
        return self.process_registration


@dataclass(frozen=True, slots=True)
class NativeRootObjectValue:
    filesystem_object: str
    mount_identity: str
    namespace_identity: str
    observation_epoch: str


@dataclass(frozen=True, slots=True)
class NativeIntervalValue:
    clock_domain: str
    interval_witness: NativeWitness


__all__ = [
    "NativeIntervalValue",
    "NativeProcessRefValue",
    "NativeRootObjectValue",
    "NativeWitnessValue",
]
